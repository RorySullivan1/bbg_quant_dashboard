"""The Single Strategy tab: a per-strategy deep-dive.

Four parts, top to bottom:

- the **Strategy** picker — the catalog table in single-select, under the
  *Table view* bar (Group by · Window · Benchmark) and the *Filter* bar
  (Dimension · Values), exactly the surface the Multi-Strategy tab picks its
  basket from (#363 dec. 1). It replaced a `W.Dropdown` inside a *Filters*
  accordion beside a 240px checkbox column — the last of the v0.8 idiom, and
  the last caller of `FilterPanel`;
- **Section 1**, a metadata card beside the cumulative chart;
- **Section 2**, the numbers: an HTML **metrics table** over the windows plus
  since-inception, and the monthly-return **calendar** beneath it. Both were
  `ipydatagrid` canvases until #366 — the theme-refresh invariant (#223) and
  a Lumino canvas, for tables that never sort, scroll sideways or take a
  click. The calendar's heatmap survived; only its grid went;
- **Section 3**, two analysis panes mirroring the Multi-Strategy tab, each
  with its own picker and benchmark dropdown: a weekly-returns β scatter, the
  return distribution, a factor-correlation scatter, drawdown, a **Rolling**
  view whose statistic is a chip (#368), a **Decile** view of returns by
  benchmark decile (#369), a **Regime Profile** across all three buckets of
  one regime (#370), and the five-β **Risk Profile** spiderweb (#372).
  **Every option draws** — the three stubs went to #367, each into an issue
  of its own.

**The pick is a `Pick`, not the grid's selected row** (#363 dec. 2). Five
things write it — a row here, a catalog row, a Leaderboard row, a points-table
row and a basket card — and everything below is a view of it. A pick the
filters hide keeps its card, its numbers and its charts; the table simply has
no row to light, and the profile card says so.

Every control re-renders live off the cached ``state.universe_prices`` — there
is no Refresh on this tab and nothing here issues BQL. The one measurement
expensive enough to be worth not repeating is the factor cross-section the
risk profile's percentile axis needs, and that is cached against the price
frame's identity (`_factor_panel`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import ipywidgets as W
import pandas as pd

from ..config import (
    LOOKBACK_YEARS,
    field_label,
    stat_windows,
    universe_grid_default_window,
    universe_grid_group_fields,
    universe_grid_groupable_fields,
)
from ..stats import (
    calendar_return_table,
    carry_returns,
    cross_section_percentile,
    cum_perf,
    daily_returns,
    decile_profile,
    drawdown_series,
    equity_risk_premium,
    factor_beta_panel,
    monthly_factor_correlations,
    monthly_realized_vol,
    monthly_returns,
    regime_risk_return,
    return_distribution_stats,
    rolling_series,
    span_metrics,
    strategy_metrics,
    term_premium,
    trend_returns,
    volatility_factor,
    weekly_returns,
)
from ..style import (
    CALENDAR_HEIGHT,
    CATALOG_TABLE_HEIGHT,
    FILTER_CHIPS_SHARE,
    FILTER_VALUES_SHARE,
    STRATEGY_METRICS_HEIGHT,
)
from .basket import Pick
from .benchmarks import BenchmarkRegistry
from .charts import (
    LineChart,
    RegimeProfileChart,
)
from .filter_strip import FilterStrip
from .grids import StrategyGrid
from .html import (
    STYLE_CTX,
    _render_calendar,
    _render_profile_card,
    _render_span_readout,
    _render_strategy_metrics,
    render_template,
)
from .panes import (
    SingleAnalysisPane,
    _make_benchmark_dropdown,
    _make_single_analysis_pane,
)
from .quant_columns import QuantColumns
from .rails import (
    FILTER_BAR_TITLE,
    FILTER_DIMENSION_HEADING,
    FILTER_VALUES_HEADING,
    TABLE_BAR_TITLE,
    ChipGroup,
    MultiChipGroup,
    RailSection,
    control_bar,
    section_panel,
)
from .regime_controls import regime_window_mask
from .theme import _short_ticker

if TYPE_CHECKING:
    # `state.py` reaches this module through its own imports, so a runtime
    # `from .state import DashboardState` raises ImportError on a partially
    # initialized module. The annotation needs the name, not the object.
    from .state import DashboardState

# Calendar tabs: (pill label, calendar_return_table `kind`).
_CALENDAR_TABS: tuple[tuple[str, str], ...] = (
    ("Absolute", "absolute"),
    ("Outperformance", "outperformance"),
    ("Vol-adjusted", "vol_adjusted"),
    ("Beta", "beta"),
    ("Correlation", "correlation"),
)

# Calendar kinds that need the shared benchmark to compute their cells.
_CALENDAR_BENCHMARK_KINDS: frozenset[str] = frozenset(
    {"outperformance", "beta", "correlation"}
)


class SingleStrategyPanel:
    """The Single Strategy tab: a per-strategy deep-dive in four parts.

    Owns every widget the builder binds and re-renders — the `pick`, the
    `grid` it is picked in and the two bars above it (`table_bar` /
    `filter_bar`, with `filter_strip` holding the values), the shared
    `bench_dd` + `bench_chk` overlay toggle, the `profile_w` card, the `line`
    cumulative chart, the `metrics_w` table, the calendar (`cal_w` +
    `cal_chips`, with `cal_kind` the active mode), and the two
    `SingleAnalysisPane`s — and renders into them.

    Like `PlatformAnalytics` (#219), **`state` is held and `meta` stays a
    per-call argument**: `state` is one mutable object whose contents change in
    place, while the app re-points `meta` to the pruned catalog after each
    load, so an attribute would go stale silently.
    """

    def __init__(
        self,
        meta: pd.DataFrame,
        state: DashboardState,
        *,
        registry: BenchmarkRegistry | None = None,
        on_filter_change: Callable[[], None] | None = None,
    ) -> None:
        self.state = state
        #: The analytics window the panel last rendered at, kept for
        #: `render_calendar`, which takes no arguments and must slice the
        #: fetched frame like every other consumer (#311). None until the first
        #: `render`, which is also before any strategy is picked.
        self._window_start: pd.Timestamp | None = None
        #: The one strategy every section below draws. Constructed here rather
        #: than injected: the panel is the only thing that has to exist for a
        #: pick to mean anything, and the app reaches it as `panel.pick`.
        self.pick = Pick()
        #: The memo the grid's quant columns are computed through — the same
        #: object the Multi tab holds, one per tab so a benchmark change on one
        #: cannot evict the other's four windows.
        self.quant_columns = QuantColumns()
        self._on_filter_change = on_filter_change
        #: The tickers the table currently draws. Not the catalog and not the
        #: pick — `shows` reads it so the profile card can say when the two
        #: have parted company. **None until the first `render_grid`**, which
        #: is a different fact from an empty frame: a table that has not been
        #: drawn is not hiding anything, and a card that said it was would be
        #: claiming a filter nobody set.
        self._shown: frozenset[str] | None = None
        #: The catalog's factor-β cross-section, and the price frame it was
        #: measured from. Held rather than recomputed per pick — see
        #: `_factor_panel`.
        self._factor_panel_cache: pd.DataFrame = pd.DataFrame()
        self._factor_panel_source: pd.DataFrame | None = None
        self._build(meta, registry=registry)

    def _build(self, meta: pd.DataFrame, *, registry: BenchmarkRegistry | None) -> None:
        # --- the picker (#365) ------------------------------------------------
        #
        # The catalog table in single-select, under the two bars the
        # Multi-Strategy tab picks its basket from. What this replaced was a
        # `W.Dropdown` of ticker strings inside a *Filters* accordion, beside
        # 240px of checkboxes and nine `≥ / ≤` threshold rows typed against
        # numbers that appeared nowhere on screen — while the catalog those
        # rows were narrowing sat one tab away, grouped, with every one of
        # those numbers in a column.
        #
        # The tab's **own** chips over the same option lists the other two
        # read, so the three tables can be looked at through different windows
        # but cannot offer different things (#331 dec. 1).
        self.grid = StrategyGrid(self.pick)
        self.group_chips = MultiChipGroup(
            [(field_label(key), key) for key in universe_grid_groupable_fields()],
            value=universe_grid_group_fields(),
            row=True,
        )
        self.window_chips = ChipGroup(
            [label for label, _ in stat_windows()],
            value=universe_grid_default_window(),
            row=True,
        )
        # One benchmark for the whole tab: the quant columns' Beta and
        # Treynor and the cumulative chart's overlay. A `BenchmarkSelect`
        # through the one factory, never a bare `W.Dropdown` — every benchmark
        # selector in the app is user-extensible (v0.9.14), and a control here
        # that could not take a ticker off the list would be the one
        # exception.
        bench_dd = _make_benchmark_dropdown("", width="200px", registry=registry)
        # The overlay toggle rides with the selector rather than sitting in a
        # section of its own — it does not choose a benchmark, it says whether
        # the cumulative chart draws the one already chosen.
        bench_chk = W.Checkbox(
            value=False,
            description="Show benchmark",
            indent=False,
            layout=W.Layout(width="auto", margin="2px 0 0 0"),
        )
        self.table_bar = control_bar(
            RailSection("Group by", self.group_chips),
            RailSection("Window", self.window_chips),
            RailSection(
                "Benchmark",
                W.VBox([bench_dd, bench_chk], layout=W.Layout(width="auto")),
            ),
            title=TABLE_BAR_TITLE,
        )
        # Structure in the bar, text and numbers in the table (#341 dec. 8):
        # a dimension chip names what is filtered, the strip beside it shows
        # that dimension's values, and anything that is a *number* is a column
        # with the comparison filter row under it. This is the same
        # `FilterStrip` the Multi tab builds, on the same shares — the tab's
        # own instance, so the two tabs' filters are independent.
        self.filter_strip = FilterStrip(meta, on_change=self._filters_changed)
        self.filter_dim_chips = ChipGroup(
            [(self.filter_strip.chip_label(k), k) for k in self.filter_strip.keys],
            value=self.filter_strip.keys[0],
            row=True,
        )
        self.filter_dim_chips.layout.width = "auto"
        self.filter_dim_chips.observe(self._on_filter_dimension, names="value")
        self.filter_bar = control_bar(
            RailSection(
                FILTER_DIMENSION_HEADING, self.filter_dim_chips, FILTER_CHIPS_SHARE
            ),
            RailSection(
                FILTER_VALUES_HEADING, self.filter_strip.root, FILTER_VALUES_SHARE
            ),
            title=FILTER_BAR_TITLE,
        )
        self.filter_bar.add_class("bbg-filter-bar")
        self.picker_section = section_panel(
            "Strategy",
            W.VBox([self.table_bar, self.filter_bar]),
            self.grid.widget,
            height=CATALOG_TABLE_HEIGHT,
        )
        self.group_chips.observe(self._on_grouping, names="value")
        self.window_chips.observe(self._on_window, names="value")

        profile_w = W.HTML()
        line = LineChart()

        profile_header = W.HTML(
            render_template("grid_header", **STYLE_CTX, text="Strategy profile")
        )
        left_col = W.VBox(
            [profile_header, profile_w],
            layout=W.Layout(width="38%", padding="0 8px 0 0"),
        )
        right_col = W.VBox(
            [line.fig],
            layout=W.Layout(width="62%"),
        )
        profile_chart_row = W.HBox(
            [left_col, right_col],
            layout=W.Layout(width="100%", align_items="stretch"),
        )
        section1 = W.VBox(
            [profile_chart_row],
            layout=W.Layout(width="100%"),
        )

        # --- the numbers (#366) -----------------------------------------------
        #
        # Two `ipydatagrid` canvases stood here: a `PerfGrid` of four metrics
        # over three windows, and the calendar's grid. Both carry the v0.6.5
        # theme-refresh invariant (#223) and a Lumino canvas, for tables that
        # never sort, scroll sideways or take a click. They are HTML now, in
        # the app's own type and tokens.
        #
        # **The calendar heatmap survived; only its grid went** (#363 dec. 4
        # left that open). It is the one thing on this tab a desk reads at a
        # glance, and the metrics table does not replace it: that table is
        # summary statistics, this is the path they came from.
        metrics_w = W.HTML()
        self.metrics_section = section_panel(
            "Performance",
            W.Box(layout=W.Layout(display="none")),
            metrics_w,
            height=STRATEGY_METRICS_HEIGHT,
            note="vs the Table view benchmark",
        )
        cal_w = W.HTML()
        # Chips, not `_make_tab_button` pills: the last pill-tabs in the app
        # went with this (#363 dec. 12), and a `ChipGroup` carries the
        # `.value` / `.observe` surface every other enumerated choice on the
        # three tabs presents.
        # `row=True`, as every other chip group in a bar is built (#383). A
        # `_ChipStack` is a `VBox`; it lays out horizontally only when told to,
        # and this one — converted from `_make_tab_button` pills — was not, so
        # five chips stacked five high and took a third of the section's fixed
        # `CALENDAR_HEIGHT` from the calendar they head. `row` also sets the
        # `width` this used to assign by hand.
        self.cal_chips = ChipGroup(
            list(_CALENDAR_TABS), value=_CALENDAR_TABS[0][1], row=True
        )
        self.calendar_section = section_panel(
            "Monthly returns",
            control_bar(RailSection("View", self.cal_chips), title=""),
            cal_w,
            height=CALENDAR_HEIGHT,
        )
        section2_slot = W.VBox(
            [self.metrics_section, self.calendar_section],
            layout=W.Layout(width="100%", padding="8px 0 0 0"),
        )
        # Section 3: a two-pane analysis section mirroring the
        # Multi-Strategy tab. The shared `pick` above feeds both panes; each pane
        # picks which analysis + benchmark to draw, for side-by-side comparison.
        pane_left = _make_single_analysis_pane(
            "left", registry=registry, state=self.state
        )
        pane_right = _make_single_analysis_pane(
            "right", registry=registry, state=self.state
        )
        s3_header = W.HTML(
            render_template("grid_header", **STYLE_CTX, text="Analytics")
        )
        analysis_row = W.HBox(
            [pane_left.root, pane_right.root],
            layout=W.Layout(width="100%", align_items="stretch"),
        )
        section3_slot = W.Box(
            [W.VBox([s3_header, analysis_row], layout=W.Layout(width="100%"))],
            layout=W.Layout(width="100%", padding="8px 0 0 0"),
        )

        root = W.VBox(
            [self.picker_section, section1, section2_slot, section3_slot],
            layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
        )

        self.root = root
        self.bench_dd = bench_dd
        self.bench_chk = bench_chk
        self.profile_w = profile_w
        self.line = line
        # The zoom drives the in-figure readout (#380). Subscribed once, here,
        # rather than re-subscribed per render — `on_range` wraps the figure's
        # own `on_change`, and a second subscription would double every event.
        self.line.on_range(self._on_chart_range)
        self.metrics_w = metrics_w
        self.cal_w = cal_w
        #: The active calendar mode; `set_calendar_kind` moves it.
        self.cal_kind = _CALENDAR_TABS[0][1]
        self.pane_left = pane_left
        self.pane_right = pane_right
        self.section2_slot = section2_slot
        self.section3_slot = section3_slot

    # --- the picker's own controls (#365) -------------------------------------
    #
    # Every one of these re-slices the cache and redraws the table. **None of
    # them fetches**: every price the tab can need is in `universe_prices`
    # already, and the app's Refresh is the only thing that issues BQL.

    def render_grid(self, meta: pd.DataFrame) -> None:
        """Redraw the picker table from the cache, narrowed by the filter bar.

        The search box and the per-column filter row narrow further, in the
        browser — the kernel never guesses what they hold (#341), which is
        also why the pick is re-derived from `self.pick` rather than from a
        row position the last frame happened to use.
        """
        narrowed = self.filter_strip.apply(meta)
        tickers = pd.Index(narrowed["ticker"])
        self.grid.update(
            narrowed,
            self.state.universe_up,
            quant=self.quant_columns.frame(
                self.state.arp_universe_prices,
                tickers,
                benchmark=self.state.universe_prices.get(self.bench_dd.value),
                benchmark_name=self.bench_dd.value,
                returns=self.state.universe_rets,
            ),
        )
        self._shown = frozenset(str(t) for t in tickers)

    def shows(self, ticker: str | None) -> bool:
        """Whether the table currently has a row for `ticker`.

        The profile card's only question: a pick the filters hide is still the
        pick, but nothing on screen would otherwise say why no row is lit.
        True before the first `render_grid` — see `_shown`.
        """
        if ticker is None:
            return False
        return self._shown is None or ticker in self._shown

    def _filters_changed(self, _change=None) -> None:
        """A value chip moved: re-badge its dimension, then redraw."""
        self._sync_filter_badges()
        self._request_render()

    def _on_filter_dimension(self, _change=None) -> None:
        """A dimension chip moved: show that dimension's values.

        No redraw — switching which values are *visible* changes nothing about
        which rows are shown, and every dimension keeps its ticks (#345).
        """
        self.filter_strip.show(self.filter_dim_chips.value)

    def _sync_filter_badges(self) -> None:
        """Re-label the dimension chips with their active-value counts.

        A dimension's values are off screen most of the time, so the badge is
        the only place an active filter on another dimension is visible from.

        `set_options` rebuilds the chips, so the current selection is carried
        across explicitly — it is a relabel, not a change of what is on offer.
        """
        self.filter_dim_chips.set_options(
            [(self.filter_strip.chip_label(k), k) for k in self.filter_strip.keys],
            value=self.filter_dim_chips.value,
        )

    def _on_grouping(self, _change=None) -> None:
        """Group by moved: the row *order* changes, so the table is rebuilt.

        RowGroup only gathers adjacent rows, so there is no way to regroup
        without reordering and no way to reorder without rebuilding (#261).
        """
        self.grid.set_group_fields(tuple(self.group_chips.value))
        self._request_render()

    def _on_window(self, _change=None) -> None:
        """Window moved: switch which stats window the table shows.

        The statistics themselves do not change — every window is measured
        once, up front, and the table hides the columns not on show (#324).
        There is no ranking column here, so unlike the Platform's table
        (#324) this does not re-sort: the picker is a list to find a strategy
        in, and the Platform tab is where the catalog is ranked.
        """
        self.grid.set_window(self.window_chips.value)
        self._request_render()

    def _request_render(self) -> None:
        """Ask the controller to redraw, if one is wired.

        The panel cannot redraw itself: `meta` is the app's, re-pointed to the
        pruned catalog after every load, so it is a per-call argument here and
        never an attribute (#242).
        """
        if self._on_filter_change is not None:
            self._on_filter_change()

    def render(self, meta: pd.DataFrame, window_start: pd.Timestamp) -> None:
        """Render Section 1 for the currently-picked strategy.

        Reads the cached ``self.state.universe_prices`` (no BQL): renders the profile
        card, the cumulative chart (rebased to 100, with the benchmark overlaid when
        the toggle is on), and the compact 1/3/5Y + since-inception perf table. A
        missing ticker / empty cache clears the chart and grid without raising.

        The window is held on the panel because `render_calendar` takes no
        arguments and needs it too: the fetched frame reaches a year further
        back than the app analyses (#311), so every consumer here has to slice.
        """
        self._window_start = window_start
        ticker = self.pick.value
        prices = self.state.universe_prices
        row = (
            meta.loc[meta["ticker"] == ticker] if ticker is not None else meta.iloc[0:0]
        )
        self.profile_w.value = (
            _render_profile_card(row.iloc[0], shown=self.shows(ticker))
            if not row.empty
            else ""
        )

        if (
            ticker is None
            or prices is None
            or prices.empty
            or ticker not in prices.columns
        ):
            self.line.clear()
            self.metrics_w.value = ""
            self.cal_w.value = ""
            return

        cols = [ticker]
        bench = self.bench_dd.value
        has_bench = bench in prices.columns and bench != ticker
        if self.bench_chk.value and has_bench:
            cols.append(bench)
        window = prices.loc[prices.index >= window_start, cols]
        self.line.update(cum_perf(window))
        # A fresh draw autoranges, so the readout goes back to the whole
        # window — the state the chart opens in. It is never blank while a
        # line is drawn.
        self.render_readout()

        # The metrics table reads the **analytics window**, not the fetched
        # frame. The fetch reaches `SCORE_SAMPLE_YEARS` further back for the
        # scorers (#311, #361), so an unsliced frame would make every window
        # right and since-inception a fifteen-year figure under a label that
        # does not say so.
        win = prices.loc[prices.index >= window_start]
        self.metrics_w.value = _render_strategy_metrics(
            strategy_metrics(win, ticker, benchmark=win[bench] if has_bench else None),
            benchmark=bench if has_bench else None,
        )

        self.render_calendar()
        self.render_section3(meta, window_start)

    def _on_chart_range(self, lo, hi) -> None:
        """The cumulative chart was zoomed, panned or reset (#380).

        `lo` / `hi` are `None` on an autorange, which `render_readout` reads
        as "the whole window". Nothing here fetches: it re-slices the same
        cached frame `render` sliced.
        """
        self.render_readout(lo, hi)

    def render_readout(self, lo=None, hi=None) -> None:
        """Measure the picked strategy over the period the chart is showing.

        The readout answers for **the span on screen**, which is the whole
        point of #380 — a zoom used to be cosmetic. `lo` / `hi` default to the
        analytics window, so a fresh render and a double-click land in the
        same place.

        Under a year `span_metrics` drops the annualized rows and reports a
        cumulative return; the panel says which regime it is in, so a missing
        Sharpe reads as a decision rather than as a gap.
        """
        ticker = self.pick.value
        prices = self.state.universe_prices if self.state is not None else None
        if (
            ticker is None
            or prices is None
            or prices.empty
            or ticker not in prices.columns
            or self._window_start is None
        ):
            self.line.set_readout("")
            return

        win = prices.loc[prices.index >= self._window_start]
        if win.empty:
            self.line.set_readout("")
            return
        start = pd.Timestamp(lo) if lo is not None else win.index.min()
        end = pd.Timestamp(hi) if hi is not None else win.index.max()

        bench = self.bench_dd.value
        has_bench = bench in win.columns and bench != ticker
        self.line.set_readout(
            _render_span_readout(
                span_metrics(
                    win,
                    ticker,
                    start,
                    end,
                    benchmark=win[bench] if has_bench else None,
                ),
                benchmark=bench if has_bench else None,
            )
        )

    def set_calendar_kind(self, which: str) -> None:
        """Record which calendar mode is active. **The caller re-renders.**

        The chips paint themselves — that is what a `ChipGroup` is — so this
        is now only the record, where with `_make_tab_button` pills it also
        had to restyle five buttons by hand.
        """
        self.cal_kind = which
        if self.cal_chips.value != which:
            self.cal_chips.value = which

    def render_calendar(self) -> None:
        """Render the monthly calendar for the picked strategy + active kind.

        Reads the cached prices (no BQL). The benchmark-driven kinds (outperformance
        / beta / correlation) use the shared benchmark Dropdown; a missing ticker /
        benchmark clears the grid."""
        prices = self.state.universe_prices
        ticker = self.pick.value
        kind = self.cal_kind
        if (
            ticker is None
            or prices is None
            or prices.empty
            or ticker not in prices.columns
            # No window yet means `render` has not run, which is also before a
            # strategy is picked — there is nothing to draw either way, and
            # drawing it unsliced would be a six-year calendar (#311).
            or self._window_start is None
        ):
            self.cal_w.value = ""
            return
        # The fetch reaches a year further back than the app analyses, and
        # `calendar_return_table` pivots every month it is given — unsliced it
        # would grow an extra year row and restate the oldest year's summary.
        prices = prices.loc[prices.index >= self._window_start]
        benchmark = None
        if kind in _CALENDAR_BENCHMARK_KINDS:
            bench = self.bench_dd.value
            benchmark = prices[bench] if bench in prices.columns else None
        table = calendar_return_table(prices[ticker], kind=kind, benchmark=benchmark)
        self.cal_w.value = _render_calendar(table, kind=kind)

    def render_section3(self, meta: pd.DataFrame, window_start: pd.Timestamp) -> None:
        """Render both Section 3 analysis panes' currently-mounted views for the
        picked strategy over the 5Y window (no BQL)."""
        self.render_analysis_pane(self.pane_left, meta, window_start)
        self.render_analysis_pane(self.pane_right, meta, window_start)

    def _factor_panel(self) -> pd.DataFrame:
        """Every catalog strategy's β to all five factors, **measured once**.

        The percentile axis needs the whole cross-section, which is five
        `factor_beta` passes over the universe. At 18 mock rows that is
        nothing; at a terminal catalog it is the one expensive thing on this
        tab, so it is cached against the price frame's **identity** — the
        `QuantColumns` pattern, and for the same reason (#261: every window
        is measured once). A Refresh rebinds `arp_universe_prices`, which
        invalidates it without anything having to remember to.

        `LOOKBACK_YEARS` rather than a control: the spiderweb has no window
        of its own, and a percentile is only comparable across spokes if
        every β in it was measured over the same sample.
        """
        arp = self.state.arp_universe_prices
        if arp is None or arp.empty:
            return pd.DataFrame()
        if self._factor_panel_source is not arp:
            rets = self.state.universe_rets
            if rets is None or rets.empty:
                rets = daily_returns(arp)
            self._factor_panel_cache = factor_beta_panel(
                rets, _risk_factors(self.state.universe_prices), LOOKBACK_YEARS
            )
            self._factor_panel_source = arp
        return self._factor_panel_cache

    def _render_decile(
        self,
        pane: SingleAnalysisPane,
        win: pd.DataFrame,
        ticker: str,
        benchmark: str,
    ) -> None:
        """The strategy's returns by benchmark decile, optionally conditioned.

        **Weekly**, which is what the chart's axis says (#369): a daily
        decile's tails are single-session noise.

        The regime restricts the **periods cut**, not a slice of an existing
        cut — every bucket is a subset of the window, so re-cutting inside it
        is the only thing that answers "what does this look like when
        volatility is high". Off by default, and off means no mask at all
        rather than an all-True one, because `regime_window_mask` already
        collapses the three ways there can be no conditioning into one.
        """
        if not benchmark:
            pane.decile.clear()
            return
        regime = pane.decile_regime
        weekly = weekly_returns(win[[ticker, benchmark]])
        mask = None
        regime_label = ""
        if regime.on.value:
            low, high = regime.resolve_bucket()
            mask = regime_window_mask(regime.indicator(), weekly.index, low, high)
            regime_label = f"{regime.types.value}: {regime.buckets.label}"
        pane.decile.update(
            decile_profile(weekly[ticker], weekly[benchmark], mask=mask),
            strategy_label=_short_ticker(ticker),
            benchmark_label=_short_ticker(benchmark),
            regime_label=regime_label,
        )

    def _render_regime_profile(
        self,
        pane: SingleAnalysisPane,
        win: pd.DataFrame,
        ticker: str,
        benchmark: str,
    ) -> None:
        """Return vs vol under every bucket of the selected regime (#370).

        The three buckets plus the **unconditioned anchor**, and the
        benchmark's three when one is on. Which days each bucket selects is
        `RegimeControls`' — the same object the Platform card resolves its
        one bucket through, so the two tabs cannot disagree about where a
        regime begins.

        The anchor is drawn whatever the checkbox says; the three buckets only
        while it is on, because with the regime off there is nothing to
        condition and `bucket_bounds` would answer `(None, None)` — the
        all-days mask — three times over, which would draw the anchor three
        more times under three bucket names.
        """
        regime = pane.regime
        columns = [ticker] + ([benchmark] if benchmark else [])
        rets = daily_returns(win[columns])
        series_names = {ticker: _short_ticker(ticker)}
        if benchmark:
            series_names[benchmark] = _short_ticker(benchmark)

        # The series' own slot in the palette, so its anchor and its buckets
        # are drawn the same colour (#381). The chart cannot derive it — it
        # sees groups, and each series contributes two.
        series_index = {column: i for i, column in enumerate(series_names)}

        rows: list[dict] = []
        whole = regime_risk_return(rets, pd.Series(True, index=rets.index))
        for column, name in series_names.items():
            if column in whole.index:
                rows.append(
                    {
                        "bucket": RegimeProfileChart.ANCHOR_LABEL,
                        # The label is the chart's, never re-spelled here.
                        "series": f"{name} — {RegimeProfileChart.ANCHOR_LABEL}",
                        "anchor": True,
                        "series_index": series_index[column],
                        "vol": whole.loc[column, "vol"],
                        "ret": whole.loc[column, "ret"],
                    }
                )
        if regime.on.value:
            indicator = regime.indicator()
            for label, key in regime.bucket_keys():
                low, high = regime.bucket_bounds(key)
                mask = regime_window_mask(indicator, rets.index, low, high)
                bucket = regime_risk_return(rets, mask)
                for column, name in series_names.items():
                    if column not in bucket.index:
                        continue
                    rows.append(
                        {
                            "bucket": label,
                            "series": name,
                            "anchor": False,
                            "series_index": series_index[column],
                            "vol": bucket.loc[column, "vol"],
                            "ret": bucket.loc[column, "ret"],
                        }
                    )
        if not rows:
            pane.regime_profile.clear()
            return
        points = pd.DataFrame(rows).set_index("bucket")
        pane.regime_profile.update(
            points,
            regime_label=regime.types.value if regime.on.value else "",
            benchmark_label=_short_ticker(benchmark) if benchmark else "",
        )

    def _render_risk_profile(self, pane: SingleAnalysisPane, ticker: str) -> None:
        """One strategy's five spokes: its percentile per factor, β in hover."""
        panel = self._factor_panel()
        if panel.empty or ticker not in panel.index:
            pane.risk_profile.clear()
            return
        pane.risk_profile.update(
            cross_section_percentile(panel, ticker), panel.loc[ticker]
        )

    def render_analysis_pane(
        self,
        pane: SingleAnalysisPane,
        meta: pd.DataFrame,
        window_start: pd.Timestamp,
    ) -> None:
        """Render one analysis pane's currently-mounted view for the shared picked
        strategy (`self.pick`) and the pane's own benchmark (no BQL).

        Benchmark-dependent views (weekly scatter / distribution / drawdown) use
        `pane.bench_dd`; the factor scatter / factor scoring use the cached factor
        columns. A missing ticker / benchmark / factor columns clear the affected
        figure without raising — **every option draws** since #367, so there is
        no branch here that returns before reaching the cache."""
        label = pane.picker.value
        prices = self.state.universe_prices
        ticker = self.pick.value

        valid = not (
            ticker is None
            or prices is None
            or prices.empty
            or ticker not in prices.columns
        )
        if not valid:
            _clear_analysis_view(pane, label, meta)
            return

        win = prices.loc[prices.index >= window_start]
        bench = pane.bench_dd.value
        has_bench = bench in win.columns and bench != ticker

        if label == "Weekly Scatter":
            # x = benchmark, y = strategy → quadratic fit shows the strategy's
            # central β (linear term) plus convexity (curvature).
            if has_bench:
                bench_w = weekly_returns(win[[bench]])[bench]
                strat_w = weekly_returns(win[[ticker]])[ticker]
                # The regime picks **which weeks** are drawn on top, over the
                # whole cloud (#382). The mask is built the way the Decile
                # chart builds its own, off the same `RegimeControls`, so the
                # two views cannot disagree about where a bucket begins.
                regime = pane.weekly_regime
                mask = None
                regime_label = ""
                if regime.on.value:
                    low, high = regime.resolve_bucket()
                    mask = regime_window_mask(
                        regime.indicator(), bench_w.index, low, high
                    )
                    regime_label = f"{regime.types.value}: {regime.buckets.label}"
                pane.weekly.update(
                    bench_w, strat_w, mask=mask, regime_label=regime_label
                )
            else:
                pane.weekly.clear()
        elif label == "Return Distribution":
            dist_cols = [ticker, bench] if has_bench else [ticker]
            rets = daily_returns(win[dist_cols])
            pane.retdist.update(rets, return_distribution_stats(rets), meta)
        elif label == "Drawdown":
            dd_cols = [ticker, bench] if has_bench else [ticker]
            pane.dd.update(drawdown_series(win[dd_cols]))
        elif label == "Rolling":
            # The benchmark is passed whatever the chip holds; `rolling_series`
            # ignores it for Sharpe and Calmar, which is what lets this stay
            # one call rather than a branch per statistic (#368).
            stat = pane.rolling_chips.value
            bench_rets = daily_returns(win[[bench]])[bench] if has_bench else None
            pane.rolling.update(
                rolling_series(
                    daily_returns(win[[ticker]]), stat, benchmark=bench_rets
                ),
                stat=stat,
                benchmark_label=bench if has_bench else "",
            )
        elif label == "Factor Scatter":
            _render_factor_scatter(pane, prices, win, ticker)
        elif label == "Decile":
            self._render_decile(pane, win, ticker, bench if has_bench else "")
        elif label == "Regime Profile":
            self._render_regime_profile(pane, win, ticker, bench if has_bench else "")
        elif label == "Risk Profile":
            self._render_risk_profile(pane, ticker)


def _clear_analysis_view(
    pane: SingleAnalysisPane, label: str, meta: pd.DataFrame
) -> None:
    """Clear the figure backing one analysis `label` (no valid selection)."""
    if label == "Weekly Scatter":
        pane.weekly.clear()
    elif label == "Return Distribution":
        pane.retdist.update(pd.DataFrame(), pd.DataFrame(), meta)
    elif label == "Drawdown":
        pane.dd.clear()
    elif label == "Rolling":
        pane.rolling.clear()
    elif label == "Factor Scatter":
        pane.factor.clear()
    elif label == "Decile":
        pane.decile.clear()
    elif label == "Regime Profile":
        pane.regime_profile.clear()
    elif label == "Risk Profile":
        pane.risk_profile.clear()


def _render_factor_scatter(
    pane: SingleAnalysisPane,
    prices: pd.DataFrame,
    win: pd.DataFrame,
    ticker: str,
) -> None:
    """Monthly factor-correlation scatter: x = corr to ERP, y = corr to the term
    premium, colored by the month's risk-adjusted return (monthly return ÷
    within-month realized vol). Missing factor columns clear the figure."""
    erp = equity_risk_premium(prices)
    tp = term_premium(prices)
    strat_prices = win[ticker]
    erp_corr = monthly_factor_correlations(strat_prices, erp)
    tp_corr = monthly_factor_correlations(strat_prices, tp)
    idx = erp_corr.index.intersection(tp_corr.index)
    m_ret = monthly_returns(win[[ticker]])[ticker]
    m_vol = monthly_realized_vol(daily_returns(win[[ticker]]))[ticker]
    risk_adj = m_ret.divide(m_vol.replace(0, pd.NA))
    pane.factor.update(
        erp_corr.reindex(idx),
        tp_corr.reindex(idx),
        risk_adj.reindex(idx),
    )


def _risk_factors(prices: pd.DataFrame) -> dict[str, pd.Series]:
    """The five factor-return series the risk profile takes a β to (#372).

    Built from the one fetched cache, in spoke order. Three shapes, and the
    difference is deliberate — see `stats.factors`: the two premia are
    short-rate spreads, Trend and Carry are the indices' own returns, and
    Volatility is two level series standardized and averaged.

    A leg the feed did not serve comes back empty, which `factor_beta_panel`
    turns into an all-NaN column and the chart into a missing spoke.
    """
    return {
        "ERP": equity_risk_premium(prices),
        "Term": term_premium(prices),
        "Volatility": volatility_factor(prices),
        "Trend": trend_returns(prices),
        "Carry": carry_returns(prices),
    }


def make_single_strategy_panel(
    meta: pd.DataFrame,
    state: DashboardState,
    *,
    registry: BenchmarkRegistry | None = None,
) -> SingleStrategyPanel:
    """Build the Single Strategy tab — a thin constructor wrapper."""
    return SingleStrategyPanel(meta, state, registry=registry)
