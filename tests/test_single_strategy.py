"""Tests for the Single Strategy tab (v0.9.0 Workstreams C + D).

Covers the pure profile-card renderer (incl. NA-safety), the Section 1 recompute
(`render_single_strategy`), and the Section 2 monthly-return calendar
(`render_calendar` / `set_calendar_kind`) against a mock cache: chart traces, the
benchmark overlay, the perf table, calendar shape/kind switching, and guards.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from src.layout.html import _fmt_date, _na, _render_profile_card
from src.layout.panes import _SINGLE_BENCHMARK_VIEWS, SINGLE_ANALYSIS_OPTIONS
from src.layout.single_strategy import (
    _CALENDAR_TABS,
    make_single_strategy_panel,
    render_analysis_pane,
    render_calendar,
    render_section3,
    render_single_strategy,
    set_calendar_kind,
)
from src.stats import calendar_summary_columns


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "category": ["X", "Y", "Z"],
            "theme": ["T1", "T2", "T3"],
            "return_type": ["Total", "Total", "Excess"],
            "currency": ["USD", "EUR", "USD"],
            "live_date": pd.to_datetime(["2010-03-15", pd.NaT, "2015-07-01"]),
            "description": ["Alpha desc", pd.NA, "Charlie desc"],
        }
    )


def test_na_helper():
    assert _na(pd.NA) == "—"
    assert _na(None) == "—"
    assert _na("   ") == "—"
    assert _na("USD") == "USD"


def test_fmt_date_helper():
    assert _fmt_date(pd.Timestamp("2010-03-15")) == "2010-03-15"
    assert _fmt_date("2010-03-15") == "2010-03-15"
    assert _fmt_date(pd.NaT) == "—"
    assert _fmt_date(None) == "—"
    assert _fmt_date("not a date") == "—"


def test_render_profile_card_contains_fields():
    html = _render_profile_card(_meta().iloc[0])
    for token in ("Alpha", "AAA Index", "USD", "Total", "Alpha desc"):
        assert token in html
    # Launch date is rendered as YYYY-MM-DD.
    assert "Launch Date" in html and "2010-03-15" in html


def test_render_profile_card_is_na_safe():
    # Bravo's description + launch date are NA → render em dashes, no exception.
    html = _render_profile_card(_meta().iloc[1])
    assert "Bravo" in html and "BBB Index" in html
    assert "—" in html


def test_render_single_strategy_populates_chart_and_grid(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = multiyear_prices.copy()
    universe["SPX Index"] = benchmark  # a benchmark column rides along
    state = SimpleNamespace(universe_prices=universe)
    window_start = universe.index.min()

    ss.picker.value = "AAA Index"
    render_single_strategy(ss, state, meta, window_start)
    assert len(ss.line_fig.data) == 1  # strategy only, no overlay
    assert not ss.perf_grid.data.empty
    assert "Alpha" in ss.profile_w.value

    # Toggling the overlay adds the benchmark trace.
    ss.bench_chk.value = True
    ss.bench_dd.value = "SPX Index"
    render_single_strategy(ss, state, meta, window_start)
    assert len(ss.line_fig.data) == 2


def test_render_single_strategy_reacts_to_picker(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = multiyear_prices.copy()
    universe["SPX Index"] = benchmark
    state = SimpleNamespace(universe_prices=universe)
    window_start = universe.index.min()

    ss.picker.value = "AAA Index"
    render_single_strategy(ss, state, meta, window_start)
    assert "Alpha" in ss.profile_w.value
    ss.picker.value = "BBB Index"
    render_single_strategy(ss, state, meta, window_start)
    assert "Bravo" in ss.profile_w.value


def test_render_single_strategy_empty_cache_no_raise():
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    render_single_strategy(ss, state, meta, pd.Timestamp("2020-01-01"))
    assert len(ss.line_fig.data) == 0
    assert ss.perf_grid.data.empty
    # Section 1 recompute also drives the calendar — it should clear too.
    assert ss.cal_grid.data.empty


_CAL_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def _cal_cols(kind: str) -> list[str]:
    return [*_CAL_MONTHS, *calendar_summary_columns(kind)]


def test_render_calendar_populates_year_month_grid(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = multiyear_prices.copy()
    universe["SPX Index"] = benchmark
    state = SimpleNamespace(universe_prices=universe)
    ss.picker.value = "AAA Index"

    render_calendar(ss, state)
    data = ss.cal_grid.data
    # Default kind is absolute → Return / Vol / Sharpe summary columns.
    assert list(data.columns) == _cal_cols("absolute")
    # Oldest year on top (ascending), years rendered as string labels.
    years = [int(y) for y in data.index]
    assert years == sorted(years)


def test_calendar_kind_switch_all_benchmark_kinds(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = multiyear_prices.copy()
    universe["SPX Index"] = benchmark
    state = SimpleNamespace(universe_prices=universe)
    ss.picker.value = "AAA Index"
    ss.bench_dd.value = "SPX Index"

    for kind in ("outperformance", "vol_adjusted", "beta", "correlation"):
        set_calendar_kind(ss, kind)
        assert ss.cal_kind == kind
        render_calendar(ss, state)
        # Each kind drives its own summary columns.
        assert list(ss.cal_grid.data.columns) == _cal_cols(kind)
        assert not ss.cal_grid.data.empty


def test_calendar_tabs_cover_every_kind():
    # The pill set and the calendar_return_table kinds stay in lockstep.
    kinds = {kind for _label, kind in _CALENDAR_TABS}
    assert kinds == {
        "absolute",
        "outperformance",
        "vol_adjusted",
        "beta",
        "correlation",
    }


def _universe_with_factors(multiyear_prices, benchmark):
    """Mock cache with the benchmark + the equity-risk / term-premium factor
    columns so `equity_risk_premium` / `term_premium` resolve."""
    import numpy as np

    universe = multiyear_prices.copy()
    universe["SPX Index"] = benchmark  # benchmark + equity factor leg
    rng = np.random.default_rng(11)
    for col, drift in (("LD12TRUU Index", 5e-5), ("LUTLTRUU Index", 1e-4)):
        rets = rng.normal(drift, 0.003, len(universe))
        universe[col] = 100.0 * np.cumprod(1.0 + rets)
    return universe


def _set_pane(pane, label, bench="SPX Index"):
    """Point a pane at one analysis (and benchmark) without going through the
    widget observer wiring (the builder owns rendering)."""
    pane.bench_dd.value = bench
    pane.picker.value = label
    pane.stack.children = (pane.views[label],)


def test_render_section3_renders_both_panes(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    state = SimpleNamespace(universe_prices=universe)
    ss.picker.value = "AAA Index"
    # Left = weekly scatter (benchmark), right = factor scatter (factors).
    _set_pane(ss.pane_left, "Weekly Scatter")
    _set_pane(ss.pane_right, "Factor Scatter")

    render_section3(ss, state, meta, universe.index.min())
    assert len(ss.pane_left.weekly_fig.data) == 2  # markers + quadratic fit
    assert len(ss.pane_right.factor_fig.data) == 1  # one monthly point cloud


def test_render_analysis_pane_distribution(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    state = SimpleNamespace(universe_prices=universe)
    ss.picker.value = "AAA Index"
    pane = ss.pane_left
    _set_pane(pane, "Return Distribution")

    render_analysis_pane(ss, pane, state, meta, universe.index.min())
    assert len(pane.retdist_fig.data) >= 1
    assert not pane.retdist_stats_grid.data.empty


def test_render_analysis_pane_drawdown(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    state = SimpleNamespace(universe_prices=universe)
    ss.picker.value = "AAA Index"
    pane = ss.pane_left
    _set_pane(pane, "Drawdown")

    render_analysis_pane(ss, pane, state, meta, universe.index.min())
    # Strategy + benchmark drawdown lines.
    assert len(pane.dd_fig.data) == 2


def test_render_analysis_pane_factor_scoring(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    universe["BSLXAT Index"] = benchmark  # trend factor leg
    state = SimpleNamespace(universe_prices=universe)
    ss.picker.value = "AAA Index"
    pane = ss.pane_left
    _set_pane(pane, "Factor Scoring")

    render_analysis_pane(ss, pane, state, meta, universe.index.min())
    bar = pane.factor_score_fig.data[0]
    # All three macro-factor betas resolve from the mock cache.
    assert list(bar.x) == ["Equity risk premium", "Term premium", "Trend"]
    assert len(bar.y) == 3


def test_render_analysis_pane_stubs_show_placeholder():
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    for label, fig_attr in (
        ("Performance Ranking", "ranking_fig"),
        ("PCA Analysis", "pca_fig"),
        ("Defensive Scoring", "defensive_fig"),
    ):
        pane = ss.pane_left
        _set_pane(pane, label)
        render_analysis_pane(ss, pane, state, meta, pd.Timestamp("2020-01-01"))
        fig = getattr(pane, fig_attr)
        assert len(fig.data) == 0
        assert len(fig.layout.annotations) == 1


def test_analysis_options_match_pane_views():
    # The option list and the built view stack stay in lockstep, and every
    # benchmark-dependent view is a real option.
    ss = make_single_strategy_panel(_meta())
    assert set(SINGLE_ANALYSIS_OPTIONS) == set(ss.pane_left.views)
    assert set(SINGLE_ANALYSIS_OPTIONS) >= _SINGLE_BENCHMARK_VIEWS


def test_render_section3_missing_benchmark_keeps_histogram(multiyear_prices):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    # No benchmark / factor columns in the cache — only the strategies.
    state = SimpleNamespace(universe_prices=multiyear_prices)
    ss.picker.value = "AAA Index"
    _set_pane(ss.pane_left, "Weekly Scatter")  # benchmark absent → cleared
    _set_pane(ss.pane_right, "Return Distribution")

    render_section3(ss, state, meta, multiyear_prices.index.min())
    # Weekly scatter traces are pre-allocated (in-place update), so "cleared"
    # means the marker trace has no points, not zero traces.
    assert len(ss.pane_left.weekly_fig.data) == 2
    assert not ss.pane_left.weekly_fig.data[0].x  # no benchmark → cleared
    # Strategy-only histogram still renders.
    assert len(ss.pane_right.retdist_fig.data) >= 1


def test_render_section3_empty_cache_no_raise():
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    _set_pane(ss.pane_left, "Weekly Scatter")
    _set_pane(ss.pane_right, "Factor Scatter")
    render_section3(ss, state, meta, pd.Timestamp("2020-01-01"))
    # Weekly scatter keeps its 2 pre-allocated traces but with no data points.
    assert len(ss.pane_left.weekly_fig.data) == 2
    assert not ss.pane_left.weekly_fig.data[0].x
    assert len(ss.pane_right.factor_fig.data) == 0
