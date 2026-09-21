"""The dashboard controller: `DashboardApp` assembles and wires the whole UI.

The notebook is a one-liner that calls `build_app()`; everything the app does
at runtime is set up here. The other `layout/` modules are pure factories —
they build widgets and figures but hold no session state and never fetch. This
module owns the parts they cannot: the data, the wiring, and the lifecycle.

**One fetch, many views.** A single startup BQL call pulls the universe plus
benchmarks, factor proxies, and regime indicators into `DashboardState`. Every
control after that recomputes from that cache; the only refetches are Refresh,
a lookback change, and the delta-fetch for a hand-added benchmark.

**State on an object, not in closures.** The nested handlers mutate
`DashboardState` attributes rather than rebinding names, so they need no
`nonlocal` and the data flow stays inspectable.

**Render lazily, update in place.** A recompute renders only each pane's
mounted view, mutating figures inside `batch_update()` rather than rebuilding.
Whether the overlay paints meanwhile follows `_OVERLAY_PAINT_DELAY_S`.
"""

from __future__ import annotations

import contextlib
import threading
import time
import traceback
import warnings
from datetime import date

import ipywidgets as W
import pandas as pd
from IPython import get_ipython
from IPython.display import display

from ..bql_client import _DEFAULT_CACHE, TickersUnresolved, fetch_prices
from ..commentary import build_launch_cards, build_leaderboard, window_returns
from ..config import (
    BENCHMARK_SHORT_HISTORY_DAYS,
    DEFAULT_RANKING_METRIC,
    FACTOR_TICKERS,
    LEADERBOARD_WINDOW_DAYS,
    LEADERBOARD_WINDOW_OPTIONS,
    LEGAL_DISCLOSURE_PATH,
    LOOKBACK_YEARS,
    MAX_SELECTED_STRATEGIES,
    PERFORMANCE_DISCLAIMER_PATH,
    REGIME_TICKERS,
    RESLICE_DEBOUNCE_S,
    TRADING_DAYS_PER_YEAR,
    UNIVERSE_SOLUTION_VALUES,
    WEEK_WINDOW,
    field_label,
    rankable_metric_chips,
    score_history_years,
    stat_windows,
    universe_grid_default_window,
    universe_grid_group_fields,
    universe_grid_groupable_fields,
)
from ..data import load_metadata
from ..stats import (
    BasketWindow,
    active_columns,
    basket_window,
    daily_returns,
    rolling_metric_zscore,
    universe_perf,
)
from ..style import (
    BASKET_STRIP_HEIGHT,
    CATALOG_TABLE_HEIGHT,
    COMMENTARY_BOX_HEIGHT,
    COMMENTARY_BULLETIN_SHARE,
    COMMENTARY_LEADERBOARD_SHARE,
    StatusTone,
)
from ..user_benchmarks import load_user_benchmarks, save_user_benchmarks
from .basket import Basket, BasketCards, WindowReadout
from .benchmarks import BenchmarkRegistry
from .chrome import (
    _app_css,
    _banner,
    _loading_overlay,
    _make_chip,
    _make_tab_button,
    _render_limit_popup,
    _render_overlay,
    _render_status,
    _selection_limit_popup,
    _status_banner,
    _style_tab_button,
)
from .commentary_pane import CommentaryPane
from .filter_strip import FilterStrip
from .filters import (
    _ticker_options,
)
from .grids import (
    BasketGrid,
    PerfGrid,
    UniverseGrid,
)
from .html import (
    STYLE_CTX,
    _load_disclaimer,
    _render_error,
    render_template,
)
from .leaderboard import Leaderboard
from .multi_strategy import (
    RenderContext,
    bind_lazy_render,
    bind_live_controls,
    clear_pane,
    render_pane,
)
from .panes import SingleAnalysisPane, _make_analysis_pane, _make_benchmark_dropdown
from .platform import PlatformAnalytics
from .quant_columns import QUANT_METRICS, QuantColumns, quant_column_name
from .rails import (
    ChipGroup,
    MultiChipGroup,
    RailSection,
    _section_title,
    control_bar,
    section_panel,
)
from .selection import SelectionSlice
from .single_strategy import _CALENDAR_TABS, SingleStrategyPanel
from .state import DashboardState

# The overlay's paint rule, which three sites below depend on: the frontend
# repaints only when the kernel yields. `display()` mounts a *new* view that is
# born visible and painted at once, but an existing hidden view flipped
# visible→hidden inside one synchronous handler never paints — those comm
# updates coalesce into the final hidden state.
#
# Hence the initial load may stay synchronous (it display()s a fresh overlay),
# while Refresh must thread its blocking work and hold the overlay visible for
# at least this long, or an instant refetch hides it in the same frame.
_OVERLAY_PAINT_DELAY_S = 0.35

#: The two Platform control containers' titles — the bar above the table and
#: the rail beside it. Spelled once so the docs, the tests and the screen agree.
TABLE_BAR_TITLE = "Table view"


class DashboardApp:
    """The dashboard: its widgets, its session state, and its orchestration.

    `build_app` was one 1,100-line function holding 27 closures; the only way
    to reach any orchestration step was to build the whole app. `DashboardState`
    (#6) already held the shared *data* — this holds the *behaviour*, so each
    step has a name that can be imported, read and tested on its own.

    **Startup stays synchronous.** The initial load runs from `__init__`, for
    exactly the reason it ran inline in `build_app` (#179): under Voila the
    notebook is executed to completion and the page assembled from the result,
    so returning before the dashboard is populated serves an empty app.
    Refresh stays threaded — it fires from a click long after the page is live.
    """

    def __init__(self, verbose: bool = False) -> None:
        """Build every widget, wire the observers, and run the initial load."""
        self.verbose = verbose
        self._build_overlay_and_catalog()
        self._build_selection_column()
        self._build_commentary()
        self._build_universe_section()
        self._build_state()
        self._build_tabs()
        self._wire_and_load()

    def _build_overlay_and_catalog(self) -> None:
        """Display the loading overlay, then load the in-universe catalog."""
        self.t0 = time.perf_counter()
        # One date for the whole session, fixed before any widget is built: the
        # commentary header, the fetch window and every window slice must agree,
        # and a build that straddles midnight would otherwise date them apart.
        self.today = date.today()

        # `build_app` is synchronous, so display() the overlay first, push staged
        # progress as each load step completes, then mount the dashboard (which also
        # contains `overlay_w`) and dismiss it. The fresh mount is what makes this
        # paint — see `_OVERLAY_PAINT_DELAY_S`.
        self.overlay_w = _loading_overlay()

        if get_ipython() is not None:
            display(self.overlay_w)
        self._set_progress(0, "Initializing…")

        # `meta_all` is the full in-universe catalog (by solution); the displayed
        # `meta` is later narrowed to indices with recent price movement (post-fetch,
        # via `_prune_stale`). `meta_all` drives the fetch so a ticker that resumes
        # trading can be re-admitted on a later Refresh.
        self.meta_all = load_metadata()
        self.meta_all = self.meta_all[
            self.meta_all["solution"]
            .astype(str)
            .str.lower()
            .isin(UNIVERSE_SOLUTION_VALUES)
        ].reset_index(drop=True)
        self.meta = self.meta_all
        self._log(f"loaded metadata: {len(self.meta)} tickers")
        self._set_progress(25, f"Loaded {len(self.meta)} indices")

    def _build_selection_column(self) -> None:
        """The Multi-Strategy tab's selection surface: the basket, its table
        and the *Table view* bar over it."""
        self.basket = Basket(MAX_SELECTED_STRATEGIES)
        #: The pending debounced re-slice, cancelled and re-armed by the next
        #: basket write (#347).
        self._reslice_timer: threading.Timer | None = None
        #: Set while the load or a Refresh owns the render. Seeding the basket
        #: from `_default_selection` is a basket write like any other, so
        #: without this every load and every Refresh would build the selection
        #: slice **twice** — once for the write, once for the `_recompute` that
        #: follows it — and the second would throw the first away.
        self._reslice_suspended = False
        self._build_refresh_button()
        self._build_benchmarks_and_filters()
        self._build_basket_section()

    def _build_refresh_button(self) -> None:
        """*Refresh prices* — the one control on this tab that fetches.

        It sits on the section's **title line**, not in the bar: the bar holds
        settings that re-slice the cache, and a fetch among them would read as
        a fourth chip group (#341 dec. 11).
        """
        self.limit_popup_w = _selection_limit_popup()
        self._limit_nonce = [0]
        self.apply_btn = W.Button(description="Refresh prices")
        # Green primary action (`.bbg-btn`, GREEN_600) with hover/active/focus
        # states — styled via CSS class, not inline `.style`, so `:hover` works.
        self.apply_btn.add_class("bbg-btn")

    def _build_benchmarks_and_filters(self) -> None:
        """The live benchmark registry and the shared filter panel."""
        self.benchmarks = BenchmarkRegistry()
        # Re-added *after* construction, not as a constructor seed — the
        # constructor's list becomes the curated set, and a user benchmark must stay
        # removable. Before the persister is installed, so loading does not re-save
        # what it just read; before the first `_fetch_tickers()`, so these ride the
        # startup fetch like curated ones.
        for _persisted in load_user_benchmarks():
            self.benchmarks.add(_persisted)
        # Catalog indices ride the same startup fetch as the benchmarks, so they can
        # be offered as a second benchmark source at no BQL cost. Seeded from
        # the full catalog here and re-set from the pruned `meta` once the load has
        # dropped stale/flat indices — a dead index makes a poor benchmark.
        self.benchmarks.set_catalog(_ticker_options(self.meta))

        # **Single Strategy is `FilterPanel`'s only caller now** (#341 dec. 10).
        # The Multi tab composed one with its own picker, Refresh button and
        # date-range row; every one of those is gone, and what it wanted from
        # the panel — a reducer over the catalog — is `FilterStrip.apply`, over
        # values picked in the bar instead of in a 240px checkbox column.
        self.status_w = _status_banner()

    def _build_basket_section(self) -> None:
        """The Multi-Strategy selection surface: the *Table view* bar over the
        basket table, in the Platform tab's chrome (#344).

        What this replaced was the v0.8 idiom the rest of the app had left
        behind — a *Filters* accordion holding a 240px checkbox list of the
        whole catalog beside pill-tabs over more checkbox groups, with the
        analysis date range below it. The catalog it was picking from is the
        one the Platform tab draws grouped, with performance columns, one tab
        away; this is that table with ticks.
        """
        self.basket_grid = BasketGrid(self.basket, on_limit=self._on_basket_limit)
        self.basket_group_chips = MultiChipGroup(
            [(field_label(key), key) for key in universe_grid_groupable_fields()],
            value=universe_grid_group_fields(),
            row=True,
        )
        self.basket_group_chips.observe(self._on_basket_grouping, names="value")
        self.basket_window_chips = ChipGroup(
            [label for label, _ in stat_windows()],
            value=universe_grid_default_window(),
            row=True,
        )
        self.basket_window_chips.observe(self._on_basket_window, names="value")
        # The tab's **own** chips over the same option lists as the Platform's,
        # so the two tables can be read at different windows but cannot offer
        # different things.
        #
        # Benchmark is built here so the bar's shape is final; the quant
        # columns that read it arrive in #345.
        # A `BenchmarkSelect` through the one factory, not a bare `W.Dropdown`:
        # **every** benchmark selector in the app is user-extensible (v0.9.14),
        # and a control here that could not take a ticker off the list would be
        # the single exception.
        self.basket_benchmark_dd = _make_benchmark_dropdown(
            "",
            width="200px",
            registry=self.benchmarks,
        )
        # One benchmark for Beta / Treynor / Jensen, where `QuantFilter` gave
        # each its own: three benchmarks in one table is a comparison nobody
        # asked for, and the bar has room for one control (#341 dec. 9).
        self.basket_benchmark_dd.observe(self._on_basket_benchmark, names="value")
        self.quant_columns = QuantColumns()
        # Structure in the bar, text and numbers in the table (#341 dec. 8).
        # *Filter* names a dimension; the strip below shows its values.
        self.filter_strip = FilterStrip(self.meta, on_change=self._on_filter_change)
        self.filter_dim_chips = ChipGroup(
            [(self.filter_strip.chip_label(k), k) for k in self.filter_strip.keys],
            value=self.filter_strip.keys[0],
            row=True,
        )
        self.filter_dim_chips.observe(self._on_filter_dimension, names="value")
        self.basket_bar = control_bar(
            RailSection("Group by", self.basket_group_chips),
            RailSection("Window", self.basket_window_chips),
            RailSection("Benchmark", self.basket_benchmark_dd),
            RailSection("Filter", self.filter_dim_chips),
            title=TABLE_BAR_TITLE,
        )
        self.basket_section = section_panel(
            "Strategy selection",
            W.VBox([self.basket_bar, self.filter_strip.root]),
            self.basket_grid.widget,
            height=CATALOG_TABLE_HEIGHT,
            actions=self.apply_btn,
        )

        # --- the Basket strip (#346) -----------------------------------------
        self.basket_cards = BasketCards(
            self.basket,
            # A callable, never an attribute: the app re-points `meta` to the
            # pruned catalog after every load (#242).
            lambda: self.meta,
            on_open=self._show_in_single_strategy,
        )
        self.window_readout = WindowReadout()
        clear_basket_btn = _make_chip("Clear all", active=False)
        clear_basket_btn.on_click(lambda _b: self.basket.clear())
        self.basket_note_w = _section_title("Basket", self._basket_note())
        self.basket_strip = W.VBox(
            [
                self.basket_note_w,
                control_bar(
                    RailSection("Analysis window", self.window_readout),
                    RailSection("Basket", clear_basket_btn),
                    title="",
                ),
                self._strip_box(self.basket_cards),
            ],
            layout=W.Layout(width="100%", min_width="0"),
        )
        self.basket.observe(self._on_basket_changed, names="value")

        # Init/pane-error boxes. A sibling of the commentary block's two panes,
        # never inside one, so neither a window change nor a pane switch can wipe
        # an error off the screen.
        self.errors_w = W.HTML("")

    @staticmethod
    def _strip_box(body: W.Widget) -> W.Box:
        """The cards' boxed, fixed-height container.

        Fixed so an empty basket does not collapse the strip and shift
        everything below it the moment the last card is removed.
        """
        box = W.Box(
            [body],
            layout=W.Layout(width="100%", height=BASKET_STRIP_HEIGHT, min_height="0"),
        )
        box.add_class("bbg-section-box")
        return box

    def _basket_note(self) -> str:
        return f"{len(self.basket.value)} / {self.basket.cap} selected"

    def _on_basket_changed(self, _change=None) -> None:
        """A basket write: redraw the count, then schedule the re-slice.

        The cards follow through their own `basket.observe` and the ticks
        through the grid's; this is the controller's share.
        """
        self.basket_note_w.value = _section_title("Basket", self._basket_note()).value
        self._schedule_reslice()

    # --- the live re-slice (#347) --------------------------------------------

    def _schedule_reslice(self) -> None:
        """Re-render the perf grid and both panes, once, after a short pause.

        **No BQL.** Every price the basket can need is already in
        `universe_prices`; the tab used to reach the analytics only through
        *Refresh prices*, which refetched a cache that already held the answer
        (#341 dec. 11). Refresh now means only what it says.

        The timer is cancelled and re-armed by the next write, so ten ticks
        inside the interval produce one recompute.
        """
        if self._reslice_timer is not None:
            self._reslice_timer.cancel()
            self._reslice_timer = None
        if self._reslice_suspended:
            return
        if get_ipython() is None:
            # Headless / pytest: synchronous, so a caller observes the render
            # immediately after the write with no thread to join.
            self._run_reslice()
            return
        timer = threading.Timer(RESLICE_DEBOUNCE_S, self._run_reslice)
        timer.daemon = True
        self._reslice_timer = timer
        timer.start()

    def _run_reslice(self) -> None:
        """The debounced body. Deferred while a Refresh is running.

        Both write `state.cur_prep` and the panes, so they must not overlap.
        Deferring **re-arms** rather than queueing: the basket is read when the
        timer fires, so the later run sees the current one either way.
        """
        self._reslice_timer = None
        if self.refresh_inflight["running"]:
            self._schedule_reslice()
            return
        errors: list[str] = []
        started = time.perf_counter()
        self._render_selection(self._analytics_window_start(), errors)
        self._render_window_readout()
        if errors:
            self.errors_w.value = "".join(_render_error(e) for e in errors)
        self._log(f"basket re-sliced in {time.perf_counter() - started:.2f}s")

    def _render_window_readout(self) -> None:
        """The strip's window readout and the binding member's card marker.

        Recomputed on every slice and never carried over: with the date
        pickers gone there is no range to keep, so a stale window would be a
        number with nothing behind it.
        """
        self.window_readout.update(
            self.state.basket_window, empty=not self.basket.value
        )
        self.basket_cards.set_binding(self.state.basket_window.binding_start)

    def _on_basket_limit(self, result) -> None:
        """A rejected add — say how far over the cap the request was.

        The count is what makes the message actionable: *32 shown, the cap is
        25* tells the user how much to narrow by, where "maximum 25" only tells
        them they failed.
        """
        self._limit_nonce[0] += 1
        self.limit_popup_w.value = _render_limit_popup(
            f"{result.shown} selected — the cap is {result.cap}. Narrow the table "
            "or untick some rows.",
            nonce=self._limit_nonce[0],
            hidden=False,
        )

    def _on_filter_dimension(self, _change=None) -> None:
        """A *Filter* chip: show that dimension's values. No re-render —
        which dimension is on screen does not change what is filtered."""
        self.filter_strip.show(self.filter_dim_chips.value)

    def _sync_filter_badges(self) -> None:
        """Re-label the Filter chips with their active-value counts.

        `set_options` rebuilds the chips, so the current selection is carried
        across explicitly — it is a relabel, not a change of what is on offer.
        """
        self.filter_dim_chips.set_options(
            [(self.filter_strip.chip_label(k), k) for k in self.filter_strip.keys],
            value=self.filter_dim_chips.value,
        )

    def _on_basket_benchmark(self, _change=None) -> None:
        """A benchmark change moves Beta / Treynor / Jensen and nothing else."""
        self._render_basket_grid()

    def _on_basket_grouping(self, _change=None) -> None:
        """Regroup the basket table. The ticks follow, by ticker."""
        self.basket_grid.set_group_fields(tuple(self.basket_group_chips.value))
        self._render_basket_grid()

    def _on_basket_window(self, _change=None) -> None:
        """Switch which stats window the basket table shows."""
        self.basket_grid.set_window(self.basket_window_chips.value)
        self._render_basket_grid()

    def _basket_quant_frame(self, tickers: pd.Index) -> pd.DataFrame:
        """The quant block for the basket table: seven metrics per window.

        Every window is computed up front and the Window chip hides the rest,
        which is the catalog table's own rule (#324) — so switching windows
        never recomputes and never issues BQL.
        """
        arp = self.state.arp_universe_prices
        if arp.empty:
            return pd.DataFrame(index=tickers)
        name = self.basket_benchmark_dd.value
        series = self.state.universe_prices.get(name)
        blocks: list[pd.DataFrame] = []
        for label, days in stat_windows():
            table = self.quant_columns.table(
                arp,
                years=days / TRADING_DAYS_PER_YEAR,
                benchmark=series,
                benchmark_name=name,
                returns=self.state.universe_rets,
            )
            if table.empty:
                continue
            block = table.reindex(columns=list(QUANT_METRICS))
            block.columns = [quant_column_name(label, m) for m in QUANT_METRICS]
            blocks.append(block)
        if not blocks:
            return pd.DataFrame(index=tickers)
        return pd.concat(blocks, axis=1).reindex(tickers)

    def _render_basket_grid(self) -> None:
        """Redraw the basket table from the cache. **No BQL** (#341).

        The frame is narrowed by the filter panel's categorical reducer; since
        #345 the dimensions it reads are the bar's Filter chips rather than the
        retired accordion's checkbox groups, and the search box and the
        per-column filter row narrow further in the browser.
        """
        narrowed = self.filter_strip.apply(self.meta)
        self.basket_grid.update(
            narrowed,
            self.state.universe_up,
            quant=self._basket_quant_frame(pd.Index(narrowed["ticker"])),
        )

    def _build_commentary(self) -> None:
        """The all-catalog commentary block: the ranking window toggle, the
        leaderboard, and the switchable Commentary / New Launches pane."""
        # Chips rather than the `ToggleButtons` this was, so the commentary
        # block reads like the Platform tab instead of like a third control
        # idiom (#306). `ChipGroup` keeps the `.value` / `.observe` surface, so
        # everything that reads this is untouched — the same swap
        # `_build_window_chips` made for the catalog's window.
        self.ranking_window = ChipGroup(
            LEADERBOARD_WINDOW_OPTIONS,
            value=LEADERBOARD_WINDOW_DAYS,
            row=True,
        )
        self.ranking_window_bar = control_bar(
            RailSection("Window", self.ranking_window)
        )
        # A leaderboard row and a catalog row route the same way, through the one
        # method, so the two entry points into Single Strategy cannot diverge.
        self.leaderboard = Leaderboard(on_pick=self._show_in_single_strategy)
        self.commentary_pane = CommentaryPane()
        self.universe_grid = UniverseGrid(on_pick=self._show_in_single_strategy)

    def _build_universe_section(self) -> None:
        """The all-catalog grid and the Metric chips its ranking column reads.

        There is no Window and no Lookback here any more (#324). The score is
        measured over the table's own Window — the one that also decides which
        performance columns are visible — against a fixed five-year sample, so
        the only thing left to choose is which metric.
        """
        # The same four the Leaderboard's columns read, from one declaration
        # (#328) — the two boards rank the same catalog by the same kind of
        # number, so a reader should be able to carry a reading between them.
        # `row=True` since #325: these sit in the table bar now, and a chip
        # group defaults to the vertical stack a rail wants — four metrics down
        # the page would make the bar four rows tall.
        self.z_metric_chips = ChipGroup(
            rankable_metric_chips(),
            value=DEFAULT_RANKING_METRIC,
            row=True,
        )
        # Built here rather than inside `_build_table_bar`, which runs after
        # `PlatformAnalytics` is constructed: since #324 the Window is a
        # ranking control too, and the analytics object is handed it.
        self._build_window_chips()

        self.pane_left = _make_analysis_pane("left", registry=self.benchmarks)
        self.pane_right = _make_analysis_pane("right", registry=self.benchmarks)
        self.analysis_pane_row = W.HBox(
            [self.pane_left.root, self.pane_right.root],
            layout=W.Layout(width="100%", align_items="stretch"),
        )

        self.selected_perf_grid = PerfGrid()

    def _build_table_bar(self) -> W.HBox:
        """The whole control set for the table, in a bar above it.

        **Group by · Metric · Window**, in the order they act in: the chips
        decide what the rows are gathered into, the metric decides what is
        measured, the window decides over how long. They were in three places
        and three idioms not long ago — checkboxes above the table, a radio
        beside it, three dropdowns in a rail — and nothing said they belonged
        together.

        The Metric arrived here in #325, once #324 had made the bar's Window
        the one the score is measured over. Before that the two would have read
        as unrelated neighbours; now they are two thirds of one sentence.

        Across rather than down (`control_bar`): these sit above the table,
        where the eye starts, and a stacked rail there would cost the table
        vertical space for chips that fit comfortably in a row.
        """
        return control_bar(
            RailSection("Group by", self._build_group_chips()),
            RailSection("Metric", self.z_metric_chips),
            RailSection("Window", self.window_chips),
            title=TABLE_BAR_TITLE,
        )

    def _build_group_chips(self) -> MultiChipGroup:
        """One chip per groupable field, in hierarchy order.

        Ticking a chip adds that level to the nesting; it never decides *where*
        the level sits. The order is `UNIVERSE_GRID_GROUPABLE_FIELDS` — asset
        class above the three classification tiers — so the table reads the
        same however the user got there, and ticking order is not invisible
        state anyone has to remember (#273).

        A chip *looks* more like an ordered selection than a checkbox did, so
        the guarantee is structural rather than remembered: `MultiChipGroup`
        reports membership in options order and cannot encode a click sequence
        (#277), and `universe_grid_group_fields` remains the single sort.
        """
        self.group_chips = MultiChipGroup(
            [(field_label(key), key) for key in universe_grid_groupable_fields()],
            value=universe_grid_group_fields(),
            row=True,
        )
        self.group_chips.observe(self._on_grouping_change, names="value")
        return self.group_chips

    def _build_window_chips(self) -> ChipGroup:
        """The stats windows the fetched price history can serve.

        Only those are offered (`stat_windows`): a longer window has nothing to
        measure and would render a full column of dashes, which reads as a
        broken dashboard rather than as a pending feature. Since #324 that cuts
        twice — the window is also what the ranking column is measured over, so
        an unservable window would blank the score as well as the statistics.

        A `ChipGroup` rather than the `W.RadioButtons` this was (#277): every
        other choice in the app is a `.bbg-pill`, and the group keeps the
        radio's `.value` / `.observe` surface, so the swap is chrome only —
        `_on_window_change` below is untouched by it, and so is what the grid
        does with it.
        """
        self.window_chips = ChipGroup(
            [label for label, _ in stat_windows()],
            value=universe_grid_default_window(),
            row=True,
        )
        self.window_chips.observe(self._on_window_change, names="value")
        return self.window_chips

    def _on_window_change(self, _change=None) -> None:
        """Switch the window, which now does two jobs (#324).

        It still chooses which performance columns are visible, and those are
        still hidden rather than dropped — nothing in `universe_up`
        recomputes. But it is also the window the ranking column is measured
        over, so the score's header and the row order both move with it, and
        the table is rebuilt exactly as a grouping change rebuilds it.

        That is why this reads like `_on_grouping_change`: record on the grid,
        then re-render. The selected row does not survive, which is inherent —
        the rows moved.
        """
        self.universe_grid.set_window(self.window_chips.value)
        self.analytics.render_universe_grid(self.meta)

    def _on_grouping_change(self, _change=None) -> None:
        """Regroup the catalog grid from the chips.

        Unlike the window this genuinely rebuilds: grouping decides the row
        order, because RowGroup only gathers consecutive rows. Re-rendering is
        the point, not an oversight.
        """
        chosen = tuple(self.group_chips.value)
        self.universe_grid.set_group_fields(chosen)
        self.analytics.render_universe_grid(self.meta)

    def _build_state(self) -> None:
        """The `DashboardState` every orchestration method reads and writes."""
        self.state = DashboardState(
            benchmarks=self.benchmarks,
            basket=self.basket,
            status_w=self.status_w,
            overlay_w=self.overlay_w,
            universe_grid=self.universe_grid,
            selected_perf_grid=self.selected_perf_grid,
            pane_left=self.pane_left,
            pane_right=self.pane_right,
            errors_w=self.errors_w,
        )

        selected_perf_header = W.HTML(
            render_template(
                "grid_header", **STYLE_CTX, text="Selected-strategy performance"
            )
        )
        self.selected_perf_section = W.VBox(
            [selected_perf_header, self.selected_perf_grid.grid],
            layout=W.Layout(width="100%", padding="4px 0 8px 0"),
        )

        # Two sections of the same shape side by side at 60:40 (#308):
        # Leaderboard left, QIS Bulletin right, each a `section_panel` of
        # title → control bar → boxed body at one height.
        #
        # **Both share, neither absorbs.** `flex: 1 1 <share>` on each is what
        # makes the ratio hold as the viewport narrows; the `0 0 620px` basis
        # this replaced read as 60% at 1030px and 43% at 1440px, so the split
        # was really a width that happened to look right on one screen.
        # `min_width: 0` on both is load-bearing, not tidiness: a flex item's
        # automatic minimum is its content, so without it the leaderboard's
        # four columns would refuse to narrow and push the Bulletin off the row
        # instead of letting both shrink — the same pairing the catalog table
        # needs beside its rail (#276).
        leaderboard_col = W.Box(
            [
                section_panel(
                    "Leaderboard",
                    self.ranking_window_bar,
                    self.leaderboard.root,
                    height=COMMENTARY_BOX_HEIGHT,
                    # The ranking basis, which the board cannot show: the rows
                    # carry a score and a raw value, and nothing on screen
                    # otherwise says the order comes from the former. Reads
                    # `LOOKBACK_YEARS` because that is what
                    # `SCORE_SAMPLE_DAYS` is derived from — a
                    # literal "5Y" here would be free to drift from the sample
                    # the scorer actually standardizes over.
                    note=f"(Ranked By Normalized {LOOKBACK_YEARS}Y Z-Score)",
                )
            ],
            layout=W.Layout(flex=f"1 1 {COMMENTARY_LEADERBOARD_SHARE}", min_width="0"),
        )
        pane_col = W.Box(
            [
                section_panel(
                    "QIS Bulletin",
                    self.commentary_pane.bar,
                    self.commentary_pane.root,
                    height=COMMENTARY_BOX_HEIGHT,
                )
            ],
            layout=W.Layout(
                flex=f"1 1 {COMMENTARY_BULLETIN_SHARE}",
                min_width="0",
                padding="0 0 0 12px",
            ),
        )
        self.commentary_box = W.VBox(
            [
                self.errors_w,
                W.HBox(
                    [leaderboard_col, pane_col],
                    layout=W.Layout(width="100%", align_items="flex-start"),
                ),
            ],
            layout=W.Layout(width="100%", padding="12px 16px"),
        )

        self.universe_header = W.HTML(
            render_template("grid_header", **STYLE_CTX, text="All-catalog performance")
        )

    def _build_tabs(self) -> None:
        """The three tab panels and the top-level tab bar."""
        self.analytics = PlatformAnalytics(
            self.state,
            z_metric_chips=self.z_metric_chips,
            window_chips=self.window_chips,
            # The same route the catalog grid and the leaderboard take, so the
            # three ways into Single Strategy cannot diverge (#286's rule).
            on_open_strategy=self._show_in_single_strategy,
        )
        # A callable, so the observers always see the *current* catalog —
        # `self.meta` is re-pointed to the pruned one after each load (#242).
        self.analytics.wire(lambda: self.meta)

        # The Platform shell: one bar of controls, then the table at full
        # width, then the analytics card. The rail that stood down the table's
        # left side went in #326, once #324 and #325 had emptied it — it was
        # holding 210px for chips that now sit in the bar above.
        self.table_bar = self._build_table_bar()
        platform_panel = W.VBox(
            [
                self.universe_header,
                self.table_bar,
                self.universe_grid.widget,
                self.analytics.card,
            ],
            layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
        )
        selected_panel = W.VBox(
            [
                self.basket_section,
                self.basket_strip,
                self.selected_perf_section,
                self.analysis_pane_row,
            ],
            layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
        )

        # The third top-level tab: a per-strategy deep-dive. Built here so
        # the tab wiring below can swap it in; its picker options are rebuilt against
        # the pruned `meta` once the cache loads.
        self.single_strategy = SingleStrategyPanel(
            self.meta, self.state, registry=self.benchmarks
        )
        self.state.single_strategy = self.single_strategy
        single_panel = self.single_strategy.root

        self.platform_btn = _make_tab_button("Platform", active=True)
        self.selected_btn = _make_tab_button("Multi-Strategy", active=False)
        self.single_btn = _make_tab_button("Single Strategy", active=False)
        self.top_tab_bar = W.HBox(
            [self.platform_btn, self.selected_btn, self.single_btn],
            layout=W.Layout(width="100%"),
        )
        # Stylize the band as the section header (distinct bg + accent underline +
        # inverted active tab); padding/border/background live on `.bbg-tabband`
        # in app_css.html so they stay token-driven.
        self.top_tab_bar.add_class("bbg-tabband")
        self.top_tab_content = W.Box(
            [platform_panel],
            layout=W.Layout(width="100%"),
        )

        self._top_panels = {
            "platform": platform_panel,
            "selected": selected_panel,
            "single": single_panel,
        }

        self.platform_btn.on_click(lambda _b: self._activate_tab("platform"))
        self.selected_btn.on_click(lambda _b: self._activate_tab("selected"))
        self.single_btn.on_click(lambda _b: self._activate_tab("single"))

    def _wire_and_load(self) -> None:
        """Wire every observer, assemble the app container, run the initial load."""
        self._wire_fetch_window()
        self._wire_observers()
        self._assemble_app()

    def _analytics_window_start(self) -> pd.Timestamp:
        """The start of the window every analytic is computed over.

        `LOOKBACK_YEARS` back from today — *not* the fetch start, which reaches
        a year further for the leaderboard's score (#311). One helper rather
        than the four inline copies this replaced: with the two horizons equal,
        a missed slice was harmless; now it is a six-year figure under a `5Y`
        label, and a fifth call site would opt out by omission.

        The scorer in `_render_leaderboard` is the one deliberate exception and
        says so where it reads the unsliced frame.
        """
        return pd.Timestamp(self.today) - pd.DateOffset(years=LOOKBACK_YEARS)

    def _wire_fetch_window(self) -> None:
        """The startup fetch window and the benchmark registry's callbacks."""
        # Single BQL fetch at app-load time, bounded by `score_history_years()`
        # — the longest window the catalog offers plus the sample standardized
        # behind it, so a score is never measured against a truncated history
        # (#322). A wider fetch still (e.g. back to oldest live date) is too
        # slow on the terminal.
        #
        # Everything except the scorers reads `_analytics_window_start()`
        # instead. The two are years apart, so a consumer that skips the slice
        # is a ten-year statistic under a `5Y` label.
        self.universe_start = (
            pd.Timestamp(self.today) - pd.DateOffset(years=score_history_years())
        ).date()

        # Everything the startup fetch pulls (see `config.py` for the ride-along
        # rule). Recomputed per call, so a benchmark added at runtime rides the next
        # Refresh too; driven by `meta_all`, so a stale ticker that resumes returns.

        # --- user-added benchmarks ----------------------------------------
        # A typed ticker needs its own trip to BQL — a delta, via the containment
        # cache. Its two failure modes both surface as an empty column, so only the
        # warning separates them: an *unresolvable* ticker warns as it degrades to
        # NaN, one with *no data in the window* does not. Reported identically the
        # second reads as a bug, so the warning is captured to tell them apart.

        self.benchmarks.set_resolver(self._resolve_new_benchmark)
        self.benchmarks.set_persister(self._persist_benchmarks)

    def _wire_observers(self) -> None:
        """Every live-narrowing, window-toggle and per-pane observer.

        The basket tab's filters wire themselves: `FilterStrip` takes the
        handler at construction, because its controls are built with it rather
        than collected afterwards.
        """

        # Key Highlights depend on the whole catalog, not the selection, so they
        # change only on refetch. Memoized per window (the toggle offers four) and
        # cleared by `_recompute`, so re-toggling a window is a cache hit.
        self.highlights_cache: dict = {}

        self.ranking_window.observe(
            lambda c: self._render_leaderboard(c["new"]), names="value"
        )

        # Guards against a second Refresh being launched while a worker thread is
        # still fetching/recomputing (the button is also disabled for the duration).
        self.refresh_inflight = {"running": False}
        self.apply_btn.on_click(self._refresh_prices)
        bind_live_controls(self.state, self.meta, self.state.pane_left)
        bind_live_controls(self.state, self.meta, self.state.pane_right)
        bind_lazy_render(self.state, self.meta, self.state.pane_left)
        bind_lazy_render(self.state, self.meta, self.state.pane_right)
        self.single_strategy.picker.observe(self._render_single, names="value")
        self.single_strategy.bench_dd.observe(self._render_single, names="value")
        self.single_strategy.bench_chk.observe(self._render_single, names="value")

        for _w in self.single_strategy.filters.inputs:
            _w.observe(self._on_single_filter_change, names="value")

        for pill, (_label, kind) in zip(
            self.single_strategy.cal_pills, _CALENDAR_TABS, strict=True
        ):
            pill.on_click(self._make_cal_kind_handler(kind))

        # Section 3 two-pane analysis: each pane re-renders its mounted view when its
        # analysis picker or benchmark dropdown changes (panes.py already swapped the
        # stack + benchmark visibility on the pick). The shared strategy / window
        # come from `single_strategy.picker` and `today`; no BQL, the other pane
        # untouched.

        for pane in (self.single_strategy.pane_left, self.single_strategy.pane_right):
            handler = self._make_pane_render_handler(pane)
            pane.picker.observe(handler, names="value")
            pane.bench_dd.observe(handler, names="value")

    def _assemble_app(self) -> None:
        """Assemble the app container and run the initial load."""
        perf_disclaimer_w = W.HTML(
            # The period the disclaimer states is the one the numbers cover —
            # the analytics window, not the fetch, which reaches a year further
            # for the leaderboard's score (#311).
            _load_disclaimer(
                PERFORMANCE_DISCLAIMER_PATH,
                start_date=self._analytics_window_start().date().isoformat(),
                end_date=self.today.isoformat(),
            ),
            layout=W.Layout(width="100%", padding="0 16px"),
        )
        legal_w = W.HTML(
            _load_disclaimer(LEGAL_DISCLOSURE_PATH),
            layout=W.Layout(width="100%", padding="0 16px 16px 16px"),
        )

        app = W.VBox(
            [
                _app_css(),  # global stylesheet, injected once
                _banner(),
                self.status_w,
                self.commentary_box,
                self.top_tab_bar,
                self.top_tab_content,
                perf_disclaimer_w,
                legal_w,
                self.overlay_w,  # fixed-position loading overlay
                self.limit_popup_w,  # fixed-position selection-cap error popup
            ],
            layout=W.Layout(width="100%"),
        )
        # Opt the app container into the injected dark-chrome class.
        app.add_class("bbg-app")

        self._start_initial_load()
        self.root = app

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[{time.perf_counter() - self.t0:6.2f}s] {msg}", flush=True)

    def _set_progress(
        self, pct: int, label: str, *, error: bool = False, hidden: bool = False
    ) -> None:
        self.overlay_w.value = _render_overlay(pct, label, error=error, hidden=hidden)
        # Belt-and-braces dismissal. The `.bbg-overlay.is-hidden` rule only sets
        # `opacity: 0`, so if the injected stylesheet isn't applied (or is
        # stripped by the frontend) a "hidden" overlay stays fully opaque at
        # `z-index: 9999` over the whole viewport — the dashboard then loads fine
        # but is invisible behind it. Toggling `layout.display` hides it at the
        # widget level, independent of any CSS.
        self.overlay_w.layout.display = "none" if hidden else ""

    def _set_status(self, text: str, tone: StatusTone = StatusTone.INFO) -> None:
        self.state.status_w.value = _render_status(text, tone=tone)

    def _format_loaded(
        self, df: pd.DataFrame, source: str, elapsed: float
    ) -> tuple[str, StatusTone]:
        n_tickers = df.shape[1]
        n_days = df.shape[0]
        if source == "cache":
            # An in-memory cache hit can report "cache" with no parquet on disk
            # (e.g. a read-only filesystem), so the mtime stamp is best-effort.
            try:
                mtime = _DEFAULT_CACHE.path_for(self.today).stat().st_mtime
                stamp = time.strftime("%H:%M · %m-%d", time.localtime(mtime))
                suffix = f" ({stamp})"
            except OSError:
                suffix = ""
            return (
                f"Loaded {n_tickers} indices · {n_days} trading days "
                f"from cache{suffix}",
                StatusTone.SUCCESS,
            )
        src_label = "BQL" if source == "bql" else "mock prices"
        return (
            f"Loaded {n_tickers} indices · {n_days} trading days · "
            f"fetched from {src_label} in {elapsed:.1f}s",
            StatusTone.SUCCESS,
        )

    def _activate_tab(self, which: str) -> None:
        _style_tab_button(self.platform_btn, active=which == "platform")
        _style_tab_button(self.selected_btn, active=which == "selected")
        _style_tab_button(self.single_btn, active=which == "single")
        self.top_tab_content.children = (self._top_panels[which],)

    def _show_in_single_strategy(self, ticker: str) -> None:
        """Route a click on the all-catalog grid into the Single Strategy tab.

        Sets the picker's value and lets that picker's own observer render,
        rather than rendering here — a click and a manual pick then cannot
        diverge, and this stays one line of routing instead of a second copy of
        the render path.

        The Single Strategy tab has its own filter accordion, which can narrow
        the picker below the full catalog, so a clicked index may not currently
        be on offer. Refusing the click would be a dead end — the user named the
        strategy they want — so the filters are cleared to reach it, and the
        status says so: silently discarding someone's filters is the part that
        would be surprising, not the widening itself.
        """
        panel = self.single_strategy
        offered = {o[1] if isinstance(o, tuple) else o for o in panel.picker.options}
        if ticker not in offered:
            panel.filters.clear_all()
            self._on_single_filter_change()
            self._set_status(
                f"Cleared the Single Strategy filters to show {ticker}.",
                tone=StatusTone.INFO,
            )
        panel.picker.value = ticker
        self._activate_tab("single")

    def _default_selection(self) -> tuple[str, ...]:
        """The startup strategy selection: the 5 indices with the highest
        z-score of (1W Sharpe, 1Y) over the fetched cache, so the Multi-Strategy
        views load populated. Falls back to the first available tickers when the
        z-score is unavailable/degenerate."""
        opt = [str(t) for t in self.meta["ticker"]]
        if not opt:
            return ()
        if not self.state.arp_universe_prices.empty:
            try:
                z = rolling_metric_zscore(
                    self.state.arp_universe_prices,
                    metric="sharpe",
                    window=WEEK_WINDOW,
                    zscore_window=TRADING_DAYS_PER_YEAR,
                    returns=self.state.universe_rets,
                ).dropna()
                top = [t for t in z.nlargest(5).index if t in opt]
                if top:
                    return tuple(top)
            except Exception:
                pass
        return tuple(opt[:5])

    def _fetch_tickers(self) -> list[str]:
        return list(
            dict.fromkeys(
                list(self.meta_all["ticker"])
                + self.benchmarks.tickers
                + list(FACTOR_TICKERS)
                + list(REGIME_TICKERS)
            )
        )

    def _unresolved_message(self, ticker: str) -> str:
        return (
            f"{ticker} did not resolve. Check the ticker and its suffix — "
            f"e.g. 'SPX Index', 'AAPL Equity'."
        )

    def _benchmark_window_note(self, series: pd.Series) -> str:
        """A caveat for a ticker that resolved but covers only part of the window."""
        first = series.first_valid_index()
        if first is None:
            return ""
        # Measured against the analytics window, not the fetch: the fetch
        # reaches a year further for the leaderboard's score (#311), and a
        # benchmark with a full five years of history covers everything shown.
        start = self._analytics_window_start()
        if first <= start + pd.Timedelta(days=BENCHMARK_SHORT_HISTORY_DAYS):
            return ""
        return f" History starts {first.date()}, not {start.date()}."

    def _resolve_new_benchmark(self, ticker: str) -> bool:
        """Fetch a benchmark the user typed; report what happened.

        Returns True once the ticker's prices are in ``state.universe_prices``
        and it is safe to select. Never raises: a bad ticker must not be able
        to break a dashboard that is already loaded.
        """
        existing = self.state.universe_prices
        if ticker in existing.columns and existing[ticker].notna().any():
            return True  # already rode a previous fetch

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                frame, _ = fetch_prices([ticker], self.universe_start, self.today)
        except TickersUnresolved:
            # A one-ticker request has no healthy peers to degrade against, so
            # an unresolvable ticker arrives as this rather than as the NaN
            # column a larger batch would produce.
            self._set_status(self._unresolved_message(ticker), tone=StatusTone.ERROR)
            return False
        except Exception:
            # Anything else is the session or transport, not the ticker.
            self._set_status(
                f"Could not fetch {ticker} — see error below.",
                tone=StatusTone.ERROR,
            )
            self.state.errors_w.value += _render_error(
                f"Adding benchmark {ticker} failed:\n{traceback.format_exc()}"
            )
            return False

        series = frame[ticker] if ticker in frame.columns else None
        if series is None or not series.notna().any():
            # Unresolvable vs. simply empty — see the note above. In a request
            # with healthy peers the bad ticker degrades to NaN and warns.
            unresolved = any(ticker in str(w.message) for w in caught)
            if unresolved:
                message = self._unresolved_message(ticker)
            else:
                message = (
                    f"{ticker} resolved but has no price history between "
                    f"{self.universe_start} and {self.today}."
                )
            self._set_status(message, tone=StatusTone.ERROR)
            return False

        if self.state.universe_prices.empty:
            self.state.universe_prices = series.to_frame(ticker)
        else:
            self.state.universe_prices[ticker] = series.reindex(
                self.state.universe_prices.index
            )
        self._set_status(
            f"Added benchmark {ticker}.{self._benchmark_window_note(series)}",
            tone=StatusTone.SUCCESS,
        )
        return True

    def _persist_benchmarks(self, tickers: list[str]) -> None:
        """Store the user's benchmarks; say so when the filesystem refuses.

        A failed save must never fail the add — on a read-only BQuant
        filesystem the benchmark still works for the session, and the user is
        told rather than discovering it at the next restart."""
        if not save_user_benchmarks(tickers):
            self._set_status(
                "Benchmark added for this session only — could not save it.",
                tone=StatusTone.WARN,
            )

    def _on_filter_change(self, _change=None):
        """A filter moved — re-narrow the basket table's frame.

        **The basket is not touched.** A member the filter hides keeps its
        place and its card (#341 dec. 6); the grid simply has no row to tick
        for it, and `push_ticks` re-derives the ticks from tickers after the
        rebuild. The old code had to union the selected rows back into the
        picker's options to stop them vanishing from the list — a symptom of
        the picker being both the offer and the store.

        The search box and the per-column filter row narrow further, in the
        browser, and never reach here (#285).
        """
        self._sync_filter_badges()
        self._render_basket_grid()

    def _render_leaderboard(self, window_days):
        """Render the whole-catalog leaderboard and launches at ``window_days``.

        Ranks the catalog on the four leaderboard metrics over the chosen
        window and rebuilds the new-launch cards, both from the already-fetched
        ARP cache — no BQL, no dependence on the strategy selection. Shared by
        ``_recompute`` (initial load / Refresh) and the live window-toggle
        observer.

        A compute failure goes to ``errors_w`` and leaves the last good board on
        screen. Blanking it would replace a board that is merely stale with no
        board at all, and the toggle that caused it is one click away from a
        window that works.
        """
        try:
            universe = self.state.arp_universe_prices
            if universe.empty:
                self.leaderboard.clear()
                self.commentary_pane.update_launches([])
                return
            if "launches" not in self.highlights_cache:
                self.highlights_cache["launches"] = build_launch_cards(
                    self.meta, universe, as_of=self.today
                )
            self.commentary_pane.update_launches(self.highlights_cache["launches"])
            columns = self.highlights_cache.get(window_days)
            if columns is None:
                # The one consumer that reads the **unsliced** frame, and the
                # exception `_analytics_window_start` names: the score
                # standardizes a metric against five years of its own rolling
                # history, which is what the fetch was widened for (#311). The
                # raw values are unaffected — every one of them slices
                # internally to `window_days`.
                #
                # Only the trailing window feeds the returns-based metrics, so
                # derive daily_returns over just the span they need rather than
                # over the whole book; the scorer gets the shared full-history
                # returns instead of re-deriving them four times.
                window_rets = window_returns(universe, window_days=window_days)
                columns = build_leaderboard(
                    self.meta,
                    universe,
                    window_rets,
                    history_returns=self.state.universe_rets,
                    window_days=window_days,
                )
                self.highlights_cache[window_days] = columns
            self.leaderboard.update(columns)
        except Exception:
            self.state.errors_w.value += _render_error(traceback.format_exc())

    @contextlib.contextmanager
    def _owns_the_render(self):
        """Suppress the debounced re-slice for the duration.

        For a caller that seeds the basket **and** renders it — the initial
        load and Refresh both do — so the slice is built once, by them.
        """
        self._reslice_suspended = True
        try:
            yield
        finally:
            self._reslice_suspended = False

    def _recompute(self, _btn=None):
        # A recompute rebuilds the selection slice (`cur_prep`), so every
        # memoized benchmark-dependent result is stale — drop them all. This is
        # the single invalidation point (covers Refresh, initial load, and the
        # no-selection guard branches below). Benchmark flips don't call
        # _recompute, so the memo survives across them within a stable slice.
        self.state.memo.clear()
        # The leaderboard is whole-catalog; a fresh fetch invalidates it.
        self.highlights_cache.clear()
        error_html = ""
        # Surface any errors from the initial universe fetch so the user can
        # see what actually went wrong, not just the downstream "cache empty".
        for err in self.state.init_errors:
            error_html += _render_error(err)
        # The leaderboard is always whole-catalog (ARP only), regardless of
        # selection. Render it at the currently-selected window; the toggle
        # re-renders it live (no BQL) through the same method.
        self._render_leaderboard(self.ranking_window.value)

        # The analytics bound for the selected-set slice below.
        universe_window_start = self._analytics_window_start()
        pane_errors: list[str] = []
        self._render_selection(universe_window_start, pane_errors)

        for err in pane_errors:
            error_html += _render_error(err)

        self.state.errors_w.value = error_html

    def _render_selection(
        self, universe_window_start: pd.Timestamp, pane_errors: list[str]
    ) -> None:
        """Rebuild the selection slice and render both panes.

        Takes the error list by parameter rather than reading instance state:
        Refresh runs this on a worker thread, so a per-call temporary must not
        become an attribute.
        """
        try:
            tickers = list(self.state.basket.value)
            if len(tickers) < 1:
                self.state.cur_prep = None
                self.state.basket_window = BasketWindow(None, None)
                self.state.selected_perf_grid.clear()
                clear_pane(self.state.pane_left, self.meta)
                clear_pane(self.state.pane_right, self.meta)
            elif self.state.universe_prices.empty:
                self.state.cur_prep = None
                self.state.basket_window = BasketWindow(None, None)
                pane_errors.append(
                    "Universe price cache is empty — initial BQL fetch returned no rows."
                )
                self.state.selected_perf_grid.clear()
                clear_pane(self.state.pane_left, self.meta)
                clear_pane(self.state.pane_right, self.meta)
            else:
                sel_full = self.state.universe_prices.reindex(columns=tickers)
                sel_5y = sel_full.loc[sel_full.index >= universe_window_start]
                if sel_5y.dropna(how="all").empty:
                    self.state.cur_prep = None
                    self.state.basket_window = BasketWindow(None, None)
                    pane_errors.append(
                        f"No price data in the {LOOKBACK_YEARS}Y window for: {tickers}."
                    )
                    self.state.selected_perf_grid.clear()
                    clear_pane(self.state.pane_left, self.meta)
                    clear_pane(self.state.pane_right, self.meta)
                else:
                    # Bounds = overlap window of the selected set; fall back to
                    # the full 5Y span if the series don't overlap at all.
                    self._render_selected_set(sel_5y, tickers, pane_errors)
        except Exception:
            pane_errors.append(traceback.format_exc())

    def _render_selected_set(
        self, sel_5y: pd.DataFrame, tickers: list[str], pane_errors: list[str]
    ) -> None:
        """Build the selection slice for a non-empty basket and draw both panes.

        **The window is the basket's overlap, and nothing else** (#341 dec.
        12). It starts at the latest first-valid date among the members and
        ends at the earliest last-valid date, so every day in it is a day every
        member traded. The two date pickers that used to let the user narrow
        inside that span are gone: nothing on screen said where the span came
        from or which member set it, so the control was an invitation to
        second-guess a number the tab never explained. `basket_window` names
        the binding member instead, which makes shortening the sample a
        one-click decision — remove that strategy — rather than a slider.
        """
        window = basket_window(sel_5y)
        self.state.basket_window = window
        if window.start is None or window.end is None:
            # No overlap at all. The members have histories, just no shared
            # day; the existing empty-slice path reports it.
            win_start, win_end = sel_5y.index.min(), sel_5y.index.max()
        else:
            win_start, win_end = window.start, window.end
        sel_window = sel_5y.loc[win_start:win_end]
        # Compute the selected-set returns once and thread them into
        # the dependents (perf_table, sz_series, cm, rd_stats) rather
        # than letting each recompute daily_returns.
        t_prep = time.perf_counter()
        # Persist the slice so the live benchmark/regime observers
        # can re-render a single chart without a refetch.
        self.state.cur_prep = SelectionSlice.build(sel_window, win_start, win_end)
        self._log(f"selected prep built in {time.perf_counter() - t_prep:.2f}s")
        self.state.selected_perf_grid.update(self.state.cur_prep.pt, self.meta)
        ctx = RenderContext(
            state=self.state,
            meta=self.meta,
            sel=self.state.cur_prep,
            errors=pane_errors,
        )
        t_panes = time.perf_counter()
        render_pane(ctx, self.state.pane_left)
        render_pane(ctx, self.state.pane_right)
        self._log(
            "panes rendered (mounted views only) in "
            f"{time.perf_counter() - t_panes:.2f}s"
        )

    def _run_refresh(self):
        """The Refresh-prices blocking work: refetch, re-prune, recompute.

        **It never seeds or replaces the basket** (#341 dec. 11) — it re-slices
        the one it finds, dropping only the members the prune removed. The
        re-slice is suspended throughout because the `_recompute` at the end is
        the render, and a basket write here would otherwise queue a second.

        Split out of ``_refresh_prices`` so a live frontend can run it on a
        worker thread (see ``_refresh_prices``). Drives the overlay's staged
        progress from 60% (fetch) through dismissal at 100%."""
        with self._owns_the_render():
            self._run_refresh_body()

    def _run_refresh_body(self):
        try:
            self.state.universe_prices, _ = fetch_prices(
                self._fetch_tickers(), self.universe_start, self.today, use_cache=False
            )
        except Exception:
            self._set_progress(60, "Load failed — see error below", error=True)
            self._set_status("Load failed — see error below", tone=StatusTone.ERROR)
            self.state.init_errors.append(
                f"Universe refresh ({self.universe_start} → {self.today}) failed:\n"
                f"{traceback.format_exc()}"
            )
            self._recompute()
            return
        # Re-prune stale indices from the full catalog against the fresh cache
        # (a resumed ticker can return), then refresh the strategies dropdown.
        if not self.state.universe_prices.empty:
            live = set(
                active_columns(
                    self.state.universe_prices.reindex(columns=self.meta_all["ticker"])
                )
            )
            self.meta = self.meta_all[self.meta_all["ticker"].isin(live)].reset_index(
                drop=True
            )
            # **Re-seat the basket** (#347): a ticker the prune dropped has no
            # prices left, so leaving it in would hand `basket_window` an
            # all-NaN column and collapse the overlap to nothing — the whole
            # analysis breaking because one index went stale. Through
            # `basket.remove`, so the card and the tick go with it.
            self.state.basket.remove(
                [t for t in self.state.basket.value if t not in live]
            )
            self._on_filter_change()
            self.single_strategy.picker.options = _ticker_options(self.meta)
            self.benchmarks.set_catalog(_ticker_options(self.meta))
            self._log(
                f"refresh pruned to {len(self.meta)} of {len(self.meta_all)} indices "
                f"({len(self.meta_all) - len(self.meta)} dropped as stale/flat/all-NaN)"
            )
        self.state.arp_universe_prices = self.state.universe_prices.reindex(
            columns=self.meta["ticker"]
        )
        self.state.universe_rets = daily_returns(self.state.arp_universe_prices)
        try:
            self.state.universe_up = universe_perf(self.state.arp_universe_prices)
            self.analytics.render_universe_grid(self.meta)
            self._render_basket_grid()
            # Fresh data → every analytics tab is stale; re-render the visible
            # one now, the hidden two lazily on next activation.
            self.analytics.invalidate(self.meta)
        except Exception:
            self.state.init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
        self._set_progress(85, "Building catalog…")
        # No post-load toast on Refresh: the loading overlay already signals
        # progress, and the "Loaded N indices …" toast is reserved for the
        # dashboard's *initial* load. (A refresh failure still toasts, above.)
        self._recompute()
        # Re-apply the Single Strategy filters against the fresh cache (arp is
        # updated above) so its picker stays consistent with any active filter;
        # this renders the tab once. (`_on_single_filter_change` is defined
        # below but only ever called at runtime, like `_render_single`.)
        self._on_single_filter_change()
        self._set_progress(100, "Ready", hidden=True)

    def _render_single(self, _change=None) -> None:
        """Re-render the Single Strategy tab's Section 1 from the cache. Bound to
        the picker / benchmark controls and called on load + Refresh. Reads the
        current (possibly re-pruned) `meta` and a 5Y window off `today`."""
        # `_on_single_filter_change` sets the picker options+value in one shot;
        # suppress the intermediate picker-observer renders and render once at
        # the end there instead.
        if getattr(self.single_strategy, "_suspend", False):
            return
        self.single_strategy.render(self.meta, self._analytics_window_start())

    def _refresh_prices(self, _btn=None):
        # The overlay is already in the tree, so re-render its value visible and
        # re-run the staged bar. Because there is no fresh mount here, the
        # blocking fetch/recompute goes to a worker thread and the click handler
        # returns — see `_OVERLAY_PAINT_DELAY_S`.
        self._set_progress(0, "Refreshing…")
        self._set_progress(
            60, f"Fetching prices for {len(self._fetch_tickers())} indices…"
        )

        # A pending re-slice is dropped rather than left to fire mid-fetch:
        # `_run_refresh` ends by rendering the same basket, so the timer would
        # only duplicate it — against a half-replaced cache.
        if self._reslice_timer is not None:
            self._reslice_timer.cancel()
            self._reslice_timer = None
        if get_ipython() is None:
            # Headless / pytest: run synchronously so callers observe the
            # refetch immediately after `.click()` (no frontend to paint for).
            self._run_refresh()
            return

        if self.refresh_inflight["running"]:
            return  # a refresh is already running; ignore re-clicks
        self.refresh_inflight["running"] = True
        self.apply_btn.disabled = True

        def _worker():
            try:
                # See `_OVERLAY_PAINT_DELAY_S`. On this worker thread the sleep
                # leaves the kernel free to flush the paint.
                time.sleep(_OVERLAY_PAINT_DELAY_S)
                self._run_refresh()
            finally:
                self.refresh_inflight["running"] = False
                self.apply_btn.disabled = False

        threading.Thread(target=_worker, name="bbg-refresh", daemon=True).start()

    def _on_single_filter_change(self, _change=None) -> None:
        """Narrow the Single Strategy picker to the filter matches and re-render.

        Live handler for the "Filters" accordion: on any filter input
        change, recompute the matching tickers from the cache, reset the picker
        options, keep the current pick when it still matches (else auto-select
        the first match, or clear when nothing matches), then render once.
        """
        matches = self.single_strategy.filters.matching(self.meta, self.state)
        sub = self.meta.loc[self.meta["ticker"].isin(matches)]
        options = _ticker_options(sub)
        cur = self.single_strategy.picker.value
        # Set options + value atomically without triggering the picker-observer
        # render mid-flight (resetting options fires an intermediate value=None).
        self.single_strategy._suspend = True
        try:
            self.single_strategy.picker.options = options
            if cur in set(sub["ticker"]):
                self.single_strategy.picker.value = cur
            elif options:
                self.single_strategy.picker.value = options[0][1]
            else:
                self.single_strategy.picker.value = None
        finally:
            self.single_strategy._suspend = False
        self._render_single()

    def _make_cal_kind_handler(self, which: str):
        def _handler(_b=None) -> None:
            self.single_strategy.set_calendar_kind(which)
            self.single_strategy.render_calendar()

        return _handler

    def _make_pane_render_handler(self, pane: SingleAnalysisPane):
        def _handler(_change=None) -> None:
            self.single_strategy.render_analysis_pane(
                pane, self.meta, self._analytics_window_start()
            )

        return _handler

    def _run_initial_load(self):
        """The blocking startup work — fetch, prune, compute, first render —
        formerly inline. Runnable on a worker thread (see `_start_initial_load`)
        so the overlay paints while the kernel fetches, mirroring `_run_refresh`.
        `self.meta` is re-pointed to the recent-performance-pruned catalog."""
        self._set_progress(
            60, f"Fetching prices for {len(self._fetch_tickers())} indices…"
        )
        t_fetch = time.perf_counter()
        try:
            self.state.universe_prices, fetch_source = fetch_prices(
                self._fetch_tickers(), self.universe_start, self.today
            )
            fetch_elapsed = time.perf_counter() - t_fetch
            text, tone = self._format_loaded(
                self.state.universe_prices, fetch_source, fetch_elapsed
            )
            self._set_status(text, tone=tone)
        except Exception:
            self._set_progress(60, "Load failed — see error below", error=True)
            self._set_status("Load failed — see error below", tone=StatusTone.ERROR)
            self.state.init_errors.append(
                f"Universe fetch ({self.universe_start} → {self.today}) failed:\n"
                f"{traceback.format_exc()}"
            )

        if not self.state.universe_prices.empty:
            # Drop indices with no recent price movement (stale / delisted /
            # all-NaN); `meta_all` (everything fetched) is kept so a resumed
            # ticker can be re-admitted on a later Refresh.
            live = set(
                active_columns(
                    self.state.universe_prices.reindex(columns=self.meta_all["ticker"])
                )
            )
            self.meta = self.meta_all[self.meta_all["ticker"].isin(live)].reset_index(
                drop=True
            )
            self.single_strategy.picker.options = _ticker_options(self.meta)
            self.benchmarks.set_catalog(_ticker_options(self.meta))
            self._log(
                f"pruned to {len(self.meta)} of {len(self.meta_all)} indices with recent "
                f"performance ({len(self.meta_all) - len(self.meta)} dropped as stale/flat/all-NaN)"
            )
            self.state.arp_universe_prices = self.state.universe_prices.reindex(
                columns=self.meta["ticker"]
            )
            # Whole-universe returns computed once and threaded into the Platform
            # renders + default selection so none re-derive daily_returns.
            self.state.universe_rets = daily_returns(self.state.arp_universe_prices)
            # Startup selection: top 5 by z(1W Sharpe, 1Y) so the Multi-Strategy
            # views load populated (the _recompute below reads this selection).
            self._reslice_suspended = True
            self.state.basket.replace(self._default_selection())
            try:
                self.state.universe_up = universe_perf(self.state.arp_universe_prices)
                self.analytics.render_universe_grid(self.meta)
                # After the perf table, so the stats columns are there, and
                # after the basket is seeded, so the seeded rows tick.
                self._render_basket_grid()
                # Only the visible analytics tab (Sunburst) computes on load; the
                # hidden Regime / Factor tabs render on first pill click.
                self.analytics.invalidate(self.meta)
            except Exception:
                self.state.init_errors.append(
                    f"universe_perf computation failed:\n{traceback.format_exc()}"
                )
            self._set_progress(85, "Building catalog…")
        else:
            self.state.arp_universe_prices = pd.DataFrame()
            self.state.universe_up = pd.DataFrame()

        # First render of the selected-set views + Single Strategy tab, then
        # dismiss the overlay. On a fatal fetch failure the error overlay stays
        # up (the traceback also renders in the commentary block).
        #
        # The seed above suspended the debounced re-slice; this is the render
        # it was suspended for, and from here a basket write is the user's.
        self._reslice_suspended = False
        self._recompute()
        self._render_single()
        if not self.state.universe_prices.empty:
            self._set_progress(100, "Ready", hidden=True)
        self._log(f"build_app initial load TOTAL: {time.perf_counter() - self.t0:.2f}s")

    def _start_initial_load(self):
        """Run the initial load **synchronously**, so ``build_app()`` only returns
        once the dashboard is populated.

        This deliberately does *not* offload to a worker thread the way
        ``_refresh_prices`` does — threading it broke the deployed app.
        Refresh is safe to thread because it fires from a user click, long
        after the page is live and the frontend is servicing comm updates. The
        **initial** load is different: under **Voila** the notebook is executed to
        completion and the page is then assembled from the resulting output, so a
        ``build_app()`` that returns immediately hands Voila an *empty* dashboard
        and the background thread races the page assembly — the app renders stuck
        behind the loading overlay with nothing in it. ``get_ipython()`` is not
        None under Voila either, so it cannot be used to tell an interactive
        notebook (where threading is harmless) from a Voila render (where it is
        fatal). Staying synchronous is correct in every environment; the cost is
        only that the overlay can't animate during the load.
        """
        try:
            self._run_initial_load()
        except Exception:
            # Surface the failure instead of swallowing it: `_run_initial_load`
            # renders `state.init_errors` via `_recompute`, but only if it gets
            # that far — so write the traceback straight into the error box too.
            self.state.init_errors.append(traceback.format_exc())
            self.state.errors_w.value = "".join(
                _render_error(err) for err in self.state.init_errors
            )
            self._set_progress(60, "Load failed — see error below", error=True)
