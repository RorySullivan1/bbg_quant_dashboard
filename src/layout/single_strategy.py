"""The Single Strategy tab (v0.9.0): a per-strategy deep-dive.

Workstream C delivered the tab **shell** — a single-select strategy picker plus
a shared benchmark selector + overlay toggle — and **Section 1**: a two-column
profile (metadata card on the left; a cumulative chart + compact standard-perf
table on the right). Workstream D adds **Section 2**: a 3-pill monthly-return
calendar (Absolute / Outperformance / Vol-adjusted) over one DataGrid.
Workstream E adds **Section 3**: three tabbed analytics charts — a weekly-returns
β scatter, a strategy-vs-benchmark return distribution, and a monthly
factor-correlation scatter.

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

from ..stats import (
    calendar_return_table,
    cum_perf,
    daily_returns,
    equity_risk_premium,
    monthly_factor_correlations,
    monthly_realized_vol,
    monthly_returns,
    perf_table,
    return_distribution_stats,
    since_inception_perf,
    term_premium,
    weekly_returns,
)
from .charts import (
    _update_factor_corr_scatter,
    _update_line,
    _update_return_dist,
    _update_weekly_scatter,
)
from .chrome import _make_tab_button, _style_tab_button
from .filters import _ticker_options
from .grids import _calendar_grid, _perf_grid, _update_calendar_grid, _update_perf_grid
from .html import STYLE_CTX, _render_profile_card, render_template
from .panes import (
    _factor_corr_chart,
    _line_chart,
    _make_benchmark_dropdown,
    _return_dist_chart,
    _return_dist_stats_grid,
    _weekly_scatter_chart,
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

# Section 3 analytics tabs: (pill label, view key).
_SECTION3_TABS: tuple[tuple[str, str], ...] = (
    ("Weekly scatter", "weekly"),
    ("Distribution", "distribution"),
    ("Factor scatter", "factor"),
)


def make_single_strategy_panel(meta: pd.DataFrame) -> SimpleNamespace:
    """Build the Single Strategy tab widgets and assemble ``.root``.

    Returns a ``SimpleNamespace`` of the live handles the builder binds and
    re-renders: the strategy ``picker``, the shared ``bench_dd`` + ``bench_chk``
    overlay toggle, the ``profile_w`` card, the ``line_fig`` cumulative chart,
    the compact ``perf_grid``, the calendar ``cal_grid`` + ``cal_pills`` (active
    ``cal_kind``), and the Section 3 analytics figures (``weekly_fig`` /
    ``retdist_fig`` / ``factor_fig``) behind their ``s3_pills`` view stack.
    """
    options = _ticker_options(meta)
    picker = W.Dropdown(
        options=options,
        value=options[0][1] if options else None,
        description="Strategy",
        style={"description_width": "70px"},
        layout=W.Layout(width="360px"),
    )
    bench_dd = _make_benchmark_dropdown()
    bench_chk = W.Checkbox(
        value=False,
        description="Show benchmark",
        indent=False,
        layout=W.Layout(width="160px"),
    )
    controls_row = W.HBox(
        [picker, bench_dd, bench_chk],
        layout=W.Layout(width="100%", align_items="center", margin="0 0 6px 0"),
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
        [line_fig, perf_header, perf_grid],
        layout=W.Layout(width="62%"),
    )
    section1 = W.HBox(
        [left_col, right_col],
        layout=W.Layout(width="100%", align_items="stretch"),
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
    # Section 3 (Workstream E): three tabbed analytics charts over one stack.
    weekly_fig = _weekly_scatter_chart()
    retdist_fig = _return_dist_chart()
    retdist_stats_grid = _return_dist_stats_grid()
    factor_fig = _factor_corr_chart()
    s3_views = {
        "weekly": weekly_fig,
        "distribution": W.VBox(
            [retdist_fig, retdist_stats_grid], layout=W.Layout(width="100%")
        ),
        "factor": factor_fig,
    }
    s3_pills = [
        _make_tab_button(label, active=i == 0)
        for i, (label, _k) in enumerate(_SECTION3_TABS)
    ]
    s3_pill_bar = W.HBox(s3_pills, layout=W.Layout(width="100%", margin="0 0 4px 0"))
    s3_stack = W.Box([s3_views[_SECTION3_TABS[0][1]]], layout=W.Layout(width="100%"))
    s3_header = W.HTML(render_template("grid_header", **STYLE_CTX, text="Analytics"))
    section3_slot = W.Box(
        [W.VBox([s3_header, s3_pill_bar, s3_stack], layout=W.Layout(width="100%"))],
        layout=W.Layout(width="100%", padding="8px 0 0 0"),
    )

    root = W.VBox(
        [controls_row, section1, section2_slot, section3_slot],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )

    return SimpleNamespace(
        root=root,
        picker=picker,
        bench_dd=bench_dd,
        bench_chk=bench_chk,
        profile_w=profile_w,
        line_fig=line_fig,
        perf_grid=perf_grid,
        cal_grid=cal_grid,
        cal_pills=cal_pills,
        cal_kind=_CALENDAR_TABS[0][1],
        weekly_fig=weekly_fig,
        retdist_fig=retdist_fig,
        retdist_stats_grid=retdist_stats_grid,
        factor_fig=factor_fig,
        s3_pills=s3_pills,
        s3_views=s3_views,
        s3_stack=s3_stack,
        s3_tab=_SECTION3_TABS[0][1],
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
        _update_line(ss.line_fig, pd.DataFrame(), meta)
        _update_perf_grid(ss.perf_grid, pd.DataFrame(), meta)
        return

    cols = [ticker]
    if ss.bench_chk.value:
        bench = ss.bench_dd.value
        if bench in prices.columns and bench != ticker:
            cols.append(bench)
    window = prices.loc[prices.index >= window_start, cols]
    _update_line(ss.line_fig, cum_perf(window), meta)

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


def set_section3_tab(ss: SimpleNamespace, which: str) -> None:
    """Show one Section 3 analytics view (`weekly` / `distribution` / `factor`):
    restyle the pills and swap the stack. Pure view switch — no recompute, since
    `render_section3` keeps all three figures current."""
    ss.s3_tab = which
    for pill, (_label, key) in zip(ss.s3_pills, _SECTION3_TABS, strict=True):
        _style_tab_button(pill, active=key == which)
    ss.s3_stack.children = (ss.s3_views[which],)


def render_section3(
    ss: SimpleNamespace,
    state: object,
    meta: pd.DataFrame,
    window_start: pd.Timestamp,
) -> None:
    """Render the three Section 3 analytics charts for the picked strategy over
    the 5Y window (no BQL). Weekly scatter + histogram use the shared benchmark;
    the factor scatter uses the cached factor columns. Missing ticker / benchmark
    / factor columns clear the affected figure(s) without raising."""
    prices = state.universe_prices
    ticker = ss.picker.value
    if ticker is None or prices is None or prices.empty or ticker not in prices.columns:
        _update_weekly_scatter(ss.weekly_fig, None, None)
        _update_return_dist(
            ss.retdist_fig, ss.retdist_stats_grid, pd.DataFrame(), pd.DataFrame(), meta
        )
        _update_factor_corr_scatter(ss.factor_fig, None, None, None)
        return

    win = prices.loc[prices.index >= window_start]
    bench = ss.bench_dd.value
    has_bench = bench in win.columns and bench != ticker

    # Weekly scatter: x = benchmark, y = strategy → quadratic fit shows the
    # strategy's central β (linear term) plus convexity (curvature).
    if has_bench:
        bench_w = weekly_returns(win[[bench]])[bench]
        strat_w = weekly_returns(win[[ticker]])[ticker]
        _update_weekly_scatter(ss.weekly_fig, bench_w, strat_w)
    else:
        _update_weekly_scatter(ss.weekly_fig, None, None)

    # Distribution: strategy + benchmark daily returns overlaid.
    dist_cols = [ticker, bench] if has_bench else [ticker]
    rets = daily_returns(win[dist_cols])
    _update_return_dist(
        ss.retdist_fig,
        ss.retdist_stats_grid,
        rets,
        return_distribution_stats(rets),
        meta,
    )

    # Factor scatter: monthly corr to ERP (x) / term premium (y), colored by the
    # month's risk-adjusted return (monthly return ÷ within-month realized vol).
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
        ss.factor_fig,
        erp_corr.reindex(idx),
        tp_corr.reindex(idx),
        risk_adj.reindex(idx),
    )
