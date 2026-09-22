"""The Single Strategy tab: a per-strategy deep-dive.

Four parts, top to bottom:

- the **Strategy** picker — the catalog table in single-select, under the
  *Table view* bar (Group by · Window · Benchmark) and the *Filter* bar
  (Dimension · Values), exactly the surface the Multi-Strategy tab picks its
  basket from (#363 dec. 1). It replaced a `W.Dropdown` inside a *Filters*
  accordion beside a 240px checkbox column — the last of the v0.8 idiom, and
  the last caller of `FilterPanel`;
- **Section 1**, a metadata card beside a cumulative chart and perf table;
- **Section 2**, a 5-pill monthly-return calendar over one DataGrid;
- **Section 3**, two analysis panes mirroring the Multi-Strategy tab, each with
  its own picker and benchmark dropdown. Weekly-returns β scatter, return
  distribution, factor-correlation scatter, drawdown, and factor scoring are
  functional; performance-ranking, PCA, and defensive scoring are stubs.

**The pick is a `Pick`, not the grid's selected row** (#363 dec. 2). Five
things write it — a row here, a catalog row, a Leaderboard row, a points-table
row and a basket card — and everything below is a view of it. A pick the
filters hide keeps its card, its numbers and its charts; the table simply has
no row to light, and the profile card says so.

Every control re-renders live off the cached ``state.universe_prices`` — there
is no Refresh on this tab and nothing here issues BQL.
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
    cum_perf,
    daily_returns,
    drawdown_series,
    equity_risk_premium,
    factor_beta,
    monthly_factor_correlations,
    monthly_realized_vol,
    monthly_returns,
    perf_table,
    return_distribution_stats,
    since_inception_perf,
    term_premium,
    trend_returns,
    weekly_returns,
)
from ..style import (
    CATALOG_TABLE_HEIGHT,
    FILTER_CHIPS_SHARE,
    FILTER_VALUES_SHARE,
)
from .basket import Pick
from .benchmarks import BenchmarkRegistry
from .charts import (
    LineChart,
)
from .chrome import _make_tab_button, _style_tab_button
from .filter_strip import FilterStrip
from .grids import CalendarGrid, PerfGrid, StrategyGrid
from .html import STYLE_CTX, _render_profile_card, render_template
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
    cumulative chart, the compact `perf_grid`, the calendar (`cal_grid` +
    `cal_pills`, with `cal_kind` the active mode), and the two
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
        perf_grid = PerfGrid()

        profile_header = W.HTML(
            render_template("grid_header", **STYLE_CTX, text="Strategy profile")
        )
        perf_header = W.HTML(
            render_template("grid_header", **STYLE_CTX, text="Standard performance")
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
        # Standard-performance table spans the full section width, below the
        # profile-card + cumulative-chart row.
        perf_block = W.VBox(
            [perf_header, perf_grid.grid],
            layout=W.Layout(width="100%", padding="8px 0 0 0"),
        )
        section1 = W.VBox(
            [profile_chart_row, perf_block],
            layout=W.Layout(width="100%"),
        )

        # Section 2: a 3-pill monthly-return calendar over one grid.
        cal_pills = [
            _make_tab_button(label, active=i == 0)
            for i, (label, _k) in enumerate(_CALENDAR_TABS)
        ]
        cal_pill_bar = W.HBox(
            cal_pills,
            layout=W.Layout(width="100%", margin="0 0 4px 0"),
        )
        cal_grid = CalendarGrid()
        cal_header = W.HTML(
            render_template("grid_header", **STYLE_CTX, text="Monthly return calendar")
        )
        section2_slot = W.Box(
            [
                W.VBox(
                    [cal_header, cal_pill_bar, cal_grid.grid],
                    layout=W.Layout(width="100%"),
                )
            ],
            layout=W.Layout(width="100%", padding="8px 0 0 0"),
        )
        # Section 3: a two-pane analysis section mirroring the
        # Multi-Strategy tab. The shared `pick` above feeds both panes; each pane
        # picks which analysis + benchmark to draw, for side-by-side comparison.
        pane_left = _make_single_analysis_pane("left", registry=registry)
        pane_right = _make_single_analysis_pane("right", registry=registry)
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
        self.perf_grid = perf_grid
        self.cal_grid = cal_grid
        self.cal_pills = cal_pills
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
            self.perf_grid.clear()
            return

        cols = [ticker]
        if self.bench_chk.value:
            bench = self.bench_dd.value
            if bench in prices.columns and bench != ticker:
                cols.append(bench)
        window = prices.loc[prices.index >= window_start, cols]
        self.line.update(cum_perf(window))

        # `perf_table` slices per window internally, so it takes the full frame
        # and its 5Y row benefits from the extra year of history the fetch now
        # carries. `since_inception_perf` reads whatever it is given end to end
        # — handed the full frame it would quietly become a six-year figure, so
        # it gets the analytics window and keeps meaning what it meant (#311).
        full = prices[[ticker]]
        pt = pd.concat(
            [
                perf_table(full),
                since_inception_perf(full.loc[full.index >= window_start]),
            ],
            axis=1,
        )
        self.perf_grid.update(pt, meta)

        self.render_calendar()
        self.render_section3(meta, window_start)

    def set_calendar_kind(self, which: str) -> None:
        """Activate one calendar pill (`absolute` / `outperformance` /
        `vol_adjusted`): restyle the pills and record the kind. The caller
        re-renders via `render_calendar`."""
        self.cal_kind = which
        for pill, (_label, kind) in zip(self.cal_pills, _CALENDAR_TABS, strict=True):
            _style_tab_button(pill, active=kind == which)

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
            self.cal_grid.clear()
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
        self.cal_grid.update(table, kind=kind)

    def render_section3(self, meta: pd.DataFrame, window_start: pd.Timestamp) -> None:
        """Render both Section 3 analysis panes' currently-mounted views for the
        picked strategy over the 5Y window (no BQL)."""
        self.render_analysis_pane(self.pane_left, meta, window_start)
        self.render_analysis_pane(self.pane_right, meta, window_start)

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
        columns; the rest are stubs. A missing ticker / benchmark / factor columns
        clear the affected figure without raising."""
        label = pane.picker.value
        prices = self.state.universe_prices
        ticker = self.pick.value

        # Stubs don't depend on the price cache.
        if label == "Performance Ranking":
            pane.ranking.update(None)
            return
        if label == "PCA Analysis":
            pane.pca.update()
            return
        if label == "Defensive Scoring":
            pane.defensive.update()
            return

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
                pane.weekly.update(bench_w, strat_w)
            else:
                pane.weekly.clear()
        elif label == "Return Distribution":
            dist_cols = [ticker, bench] if has_bench else [ticker]
            rets = daily_returns(win[dist_cols])
            pane.retdist.update(rets, return_distribution_stats(rets), meta)
        elif label == "Drawdown":
            dd_cols = [ticker, bench] if has_bench else [ticker]
            pane.dd.update(drawdown_series(win[dd_cols]))
        elif label == "Factor Scatter":
            _render_factor_scatter(pane, prices, win, ticker)
        elif label == "Factor Scoring":
            pane.factor_score.update(_factor_betas(prices, ticker))


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
    elif label == "Factor Scatter":
        pane.factor.clear()
    elif label == "Factor Scoring":
        pane.factor_score.clear()


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


def _factor_betas(prices: pd.DataFrame, ticker: str) -> pd.Series | None:
    """The strategy's β to each macro-factor proxy (equity risk premium / term
    premium / trend) over the 5Y window. Returns a label-indexed Series, or None
    when no factor columns resolve (e.g. a mock cache without the factor legs)."""
    rets = daily_returns(prices[[ticker]])
    factors = {
        "Equity risk premium": equity_risk_premium(prices),
        "Term premium": term_premium(prices),
        "Trend": trend_returns(prices),
    }
    out: dict[str, float] = {}
    for name, fr in factors.items():
        if fr is None or fr.empty:
            continue
        val = factor_beta(rets, fr, LOOKBACK_YEARS).get(ticker)
        if val is not None and pd.notna(val):
            out[name] = float(val)
    return pd.Series(out, dtype=float) if out else None


def make_single_strategy_panel(
    meta: pd.DataFrame,
    state: DashboardState,
    *,
    registry: BenchmarkRegistry | None = None,
) -> SingleStrategyPanel:
    """Build the Single Strategy tab — a thin constructor wrapper."""
    return SingleStrategyPanel(meta, state, registry=registry)
