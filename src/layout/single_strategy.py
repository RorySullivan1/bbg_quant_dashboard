"""The Single Strategy tab (v0.9.0): a per-strategy deep-dive.

Workstream C delivered the tab **shell** — a single-select strategy picker plus
a shared benchmark selector + overlay toggle — and **Section 1**: a two-column
profile (metadata card on the left; a cumulative chart + compact standard-perf
table on the right). Workstream D adds **Section 2**: a 3-pill monthly-return
calendar (Absolute / Outperformance / Vol-adjusted) over one DataGrid.
Workstream E adds **Section 3**: a two-pane analysis section mirroring the
Multi-Strategy tab — two side-by-side panes, each with the same analysis picker
and a per-pane benchmark dropdown, so users can compare two views of the picked
strategy. Options: weekly-returns β scatter, strategy-vs-benchmark return
distribution, monthly factor-correlation scatter, drawdown, factor scoring
(β to the macro factors), plus performance-ranking / PCA / defensive-scoring
stubs.

v0.9.12 adds a **"Filters"** accordion (``make_filter_panel``) — the same pill
bar / checkbox groups / Characteristics / Quantitative views as the
Multi-Strategy tab — reorganized into a two-column panel: the single-select
strategy picker + benchmark selector + "Show benchmark" toggle on the left, the
filter criteria on the right (equal height), so the criteria narrow the picker
in the same pane. The builder wires it to re-render the tab **live** whenever a
filter input changes (no Refresh-prices button); when the picked strategy is
filtered out, the first still-matching strategy is auto-selected.

Everything reuses the existing layout toolkit — no new runtime deps:
``_line_chart`` / ``_make_benchmark_dropdown`` (panes), ``_perf_grid`` /
``_update_perf_grid`` (grids), ``_update_line`` (charts), ``_ticker_options``
(filters), ``_render_profile_card`` (html), and the stats perf tables. No BQL:
prices come from the cached ``state.universe_prices``.
"""

from __future__ import annotations

from types import SimpleNamespace

import ipywidgets as W
import pandas as pd

from ..config import LOOKBACK_YEARS
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
from ..style import Color
from .benchmarks import BenchmarkRegistry
from .charts import (
    _update_defensive,
    _update_drawdown,
    _update_factor_corr_scatter,
    _update_factor_scoring,
    _update_line,
    _update_pca,
    _update_perf_ranking,
    _update_return_dist,
    _update_weekly_scatter,
)
from .chrome import _make_tab_button, _style_tab_button
from .filter_panel import make_filter_panel
from .filters import _ticker_options
from .grids import _calendar_grid, _perf_grid, _update_calendar_grid, _update_perf_grid
from .html import STYLE_CTX, _render_profile_card, render_template
from .panes import (
    _line_chart,
    _make_benchmark_dropdown,
    _make_single_analysis_pane,
)

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


def make_single_strategy_panel(
    meta: pd.DataFrame, *, registry: BenchmarkRegistry | None = None
) -> SimpleNamespace:
    """Build the Single Strategy tab widgets and assemble ``.root``.

    Returns a ``SimpleNamespace`` of the live handles the builder binds and
    re-renders: the strategy ``picker``, the shared ``bench_dd`` + ``bench_chk``
    overlay toggle, the ``profile_w`` card, the ``line_fig`` cumulative chart,
    the compact ``perf_grid``, the calendar ``cal_grid`` + ``cal_pills`` (active
    ``cal_kind``), and the Section 3 two-pane analysis section (``pane_left`` /
    ``pane_right``, each a ``_make_single_analysis_pane`` namespace).
    """
    # The "Filters" accordion (v0.9.12, reorganized) is a two-column panel inside
    # one accordion: on the **left**, the single-select strategy picker with a
    # benchmark selector + "Show benchmark" toggle stacked below it; on the
    # **right**, the filter criteria (the same pill bar / checkbox groups /
    # Characteristics / Quantitative views as the Multi-Strategy tab) that narrow
    # the picker's options live. The two columns stretch to equal height. The
    # criteria live in `make_filter_panel`'s right panel (build_root=False so we
    # compose it here); the builder wires its inputs so the tab re-renders on
    # every filter change (no Refresh-prices button).
    filters = make_filter_panel(
        meta,
        build_root=False,
        registry=registry,
        right_panel_layout=W.Layout(
            width="62%", padding="8px", border=f"1px solid {Color.BORDER}"
        ),
    )

    options = _ticker_options(meta)
    picker = W.Dropdown(
        options=options,
        value=options[0][1] if options else None,
        description="Strategy",
        style={"description_width": "70px"},
        layout=W.Layout(width="100%"),
    )
    bench_dd = _make_benchmark_dropdown(width="100%", registry=registry)
    bench_chk = W.Checkbox(
        value=False,
        description="Show benchmark",
        indent=False,
        layout=W.Layout(width="100%"),
    )
    # Left column: the strategy selection + benchmark controls, bordered like the
    # criteria panel and stretched to match its height.
    strategy_panel = W.VBox(
        [picker, bench_dd, bench_chk],
        layout=W.Layout(
            width="38%",
            padding="8px",
            border=f"1px solid {Color.BORDER}",
            display="flex",
            flex_flow="column",
        ),
    )
    filter_box = W.HBox(
        [strategy_panel, filters.right_panel],
        layout=W.Layout(width="100%", align_items="stretch"),
    )
    filters_accordion = W.Accordion(
        children=[filter_box],
        titles=("Filters",),
        selected_index=0,
        layout=W.Layout(width="100%"),
    )

    profile_w = W.HTML()
    line_fig = _line_chart()
    perf_grid = _perf_grid()

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
        [line_fig],
        layout=W.Layout(width="62%"),
    )
    profile_chart_row = W.HBox(
        [left_col, right_col],
        layout=W.Layout(width="100%", align_items="stretch"),
    )
    # Standard-performance table spans the full section width, below the
    # profile-card + cumulative-chart row.
    perf_block = W.VBox(
        [perf_header, perf_grid],
        layout=W.Layout(width="100%", padding="8px 0 0 0"),
    )
    section1 = W.VBox(
        [profile_chart_row, perf_block],
        layout=W.Layout(width="100%"),
    )

    # Section 2 (Workstream D): a 3-pill monthly-return calendar over one grid.
    cal_pills = [
        _make_tab_button(label, active=i == 0)
        for i, (label, _k) in enumerate(_CALENDAR_TABS)
    ]
    cal_pill_bar = W.HBox(
        cal_pills,
        layout=W.Layout(width="100%", margin="0 0 4px 0"),
    )
    cal_grid = _calendar_grid()
    cal_header = W.HTML(
        render_template("grid_header", **STYLE_CTX, text="Monthly return calendar")
    )
    section2_slot = W.Box(
        [W.VBox([cal_header, cal_pill_bar, cal_grid], layout=W.Layout(width="100%"))],
        layout=W.Layout(width="100%", padding="8px 0 0 0"),
    )
    # Section 3 (Workstream E): a two-pane analysis section mirroring the
    # Multi-Strategy tab. The shared `picker` above feeds both panes; each pane
    # picks which analysis + benchmark to draw, for side-by-side comparison.
    pane_left = _make_single_analysis_pane("left", registry=registry)
    pane_right = _make_single_analysis_pane("right", registry=registry)
    s3_header = W.HTML(render_template("grid_header", **STYLE_CTX, text="Analytics"))
    analysis_row = W.HBox(
        [pane_left.root, pane_right.root],
        layout=W.Layout(width="100%", align_items="stretch"),
    )
    section3_slot = W.Box(
        [W.VBox([s3_header, analysis_row], layout=W.Layout(width="100%"))],
        layout=W.Layout(width="100%", padding="8px 0 0 0"),
    )

    root = W.VBox(
        [filters_accordion, section1, section2_slot, section3_slot],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )

    return SimpleNamespace(
        root=root,
        filters=filters,
        picker=picker,
        bench_dd=bench_dd,
        bench_chk=bench_chk,
        profile_w=profile_w,
        line_fig=line_fig,
        perf_grid=perf_grid,
        cal_grid=cal_grid,
        cal_pills=cal_pills,
        cal_kind=_CALENDAR_TABS[0][1],
        pane_left=pane_left,
        pane_right=pane_right,
        section2_slot=section2_slot,
        section3_slot=section3_slot,
    )


def render_single_strategy(
    ss: SimpleNamespace,
    state: object,
    meta: pd.DataFrame,
    window_start: pd.Timestamp,
) -> None:
    """Render Section 1 for the currently-picked strategy.

    Reads the cached ``state.universe_prices`` (no BQL): renders the profile
    card, the cumulative chart (rebased to 100, with the benchmark overlaid when
    the toggle is on), and the compact 1/3/5Y + since-inception perf table. A
    missing ticker / empty cache clears the chart and grid without raising.
    """
    ticker = ss.picker.value
    prices = state.universe_prices
    row = meta.loc[meta["ticker"] == ticker] if ticker is not None else meta.iloc[0:0]
    ss.profile_w.value = _render_profile_card(row.iloc[0]) if not row.empty else ""

    if ticker is None or prices is None or prices.empty or ticker not in prices.columns:
        _update_line(ss.line_fig, pd.DataFrame())
        _update_perf_grid(ss.perf_grid, pd.DataFrame(), meta)
        return

    cols = [ticker]
    if ss.bench_chk.value:
        bench = ss.bench_dd.value
        if bench in prices.columns and bench != ticker:
            cols.append(bench)
    window = prices.loc[prices.index >= window_start, cols]
    _update_line(ss.line_fig, cum_perf(window))

    full = prices[[ticker]]
    pt = pd.concat([perf_table(full), since_inception_perf(full)], axis=1)
    _update_perf_grid(ss.perf_grid, pt, meta)

    render_calendar(ss, state)
    render_section3(ss, state, meta, window_start)


def set_calendar_kind(ss: SimpleNamespace, which: str) -> None:
    """Activate one calendar pill (`absolute` / `outperformance` /
    `vol_adjusted`): restyle the pills and record the kind. The caller
    re-renders via `render_calendar`."""
    ss.cal_kind = which
    for pill, (_label, kind) in zip(ss.cal_pills, _CALENDAR_TABS, strict=True):
        _style_tab_button(pill, active=kind == which)


def render_calendar(ss: SimpleNamespace, state: object) -> None:
    """Render the monthly calendar for the picked strategy + active kind.

    Reads the cached prices (no BQL). The benchmark-driven kinds (outperformance
    / beta / correlation) use the shared benchmark Dropdown; a missing ticker /
    benchmark clears the grid."""
    prices = state.universe_prices
    ticker = ss.picker.value
    kind = ss.cal_kind
    if ticker is None or prices is None or prices.empty or ticker not in prices.columns:
        _update_calendar_grid(ss.cal_grid, pd.DataFrame(), kind=kind)
        return
    benchmark = None
    if kind in _CALENDAR_BENCHMARK_KINDS:
        bench = ss.bench_dd.value
        benchmark = prices[bench] if bench in prices.columns else None
    table = calendar_return_table(prices[ticker], kind=kind, benchmark=benchmark)
    _update_calendar_grid(ss.cal_grid, table, kind=kind)


def render_section3(
    ss: SimpleNamespace,
    state: object,
    meta: pd.DataFrame,
    window_start: pd.Timestamp,
) -> None:
    """Render both Section 3 analysis panes' currently-mounted views for the
    picked strategy over the 5Y window (no BQL)."""
    render_analysis_pane(ss, ss.pane_left, state, meta, window_start)
    render_analysis_pane(ss, ss.pane_right, state, meta, window_start)


def render_analysis_pane(
    ss: SimpleNamespace,
    pane: SimpleNamespace,
    state: object,
    meta: pd.DataFrame,
    window_start: pd.Timestamp,
) -> None:
    """Render one analysis pane's currently-mounted view for the shared picked
    strategy (`ss.picker`) and the pane's own benchmark (no BQL).

    Benchmark-dependent views (weekly scatter / distribution / drawdown) use
    `pane.bench_dd`; the factor scatter / factor scoring use the cached factor
    columns; the rest are stubs. A missing ticker / benchmark / factor columns
    clear the affected figure without raising."""
    label = pane.picker.value
    prices = state.universe_prices
    ticker = ss.picker.value

    # Stubs don't depend on the price cache.
    if label == "Performance Ranking":
        _update_perf_ranking(pane.ranking_fig, None)
        return
    if label == "PCA Analysis":
        _update_pca(pane.pca_fig)
        return
    if label == "Defensive Scoring":
        _update_defensive(pane.defensive_fig)
        return

    valid = not (
        ticker is None or prices is None or prices.empty or ticker not in prices.columns
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
            _update_weekly_scatter(pane.weekly_fig, bench_w, strat_w)
        else:
            _update_weekly_scatter(pane.weekly_fig, None, None)
    elif label == "Return Distribution":
        dist_cols = [ticker, bench] if has_bench else [ticker]
        rets = daily_returns(win[dist_cols])
        _update_return_dist(
            pane.retdist_fig,
            pane.retdist_stats_grid,
            rets,
            return_distribution_stats(rets),
            meta,
        )
    elif label == "Drawdown":
        dd_cols = [ticker, bench] if has_bench else [ticker]
        _update_drawdown(pane.dd_fig, drawdown_series(win[dd_cols]))
    elif label == "Factor Scatter":
        _render_factor_scatter(pane, prices, win, ticker)
    elif label == "Factor Scoring":
        _update_factor_scoring(pane.factor_score_fig, _factor_betas(prices, ticker))


def _clear_analysis_view(pane: SimpleNamespace, label: str, meta: pd.DataFrame) -> None:
    """Clear the figure backing one analysis `label` (no valid selection)."""
    if label == "Weekly Scatter":
        _update_weekly_scatter(pane.weekly_fig, None, None)
    elif label == "Return Distribution":
        _update_return_dist(
            pane.retdist_fig,
            pane.retdist_stats_grid,
            pd.DataFrame(),
            pd.DataFrame(),
            meta,
        )
    elif label == "Drawdown":
        _update_drawdown(pane.dd_fig, pd.DataFrame())
    elif label == "Factor Scatter":
        _update_factor_corr_scatter(pane.factor_fig, None, None, None)
    elif label == "Factor Scoring":
        _update_factor_scoring(pane.factor_score_fig, None)


def _render_factor_scatter(
    pane: SimpleNamespace,
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
    _update_factor_corr_scatter(
        pane.factor_fig,
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
