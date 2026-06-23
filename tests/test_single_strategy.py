"""Tests for the Single Strategy tab (v0.9.0 Workstreams C + D).

Covers the pure profile-card renderer (incl. NA-safety), the Section 1 recompute
(`render_single_strategy`), and the Section 2 monthly-return calendar
(`render_calendar` / `set_calendar_kind`) against a mock cache: chart traces, the
benchmark overlay, the perf table, calendar shape/kind switching, and guards.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from src.layout.html import _na, _render_profile_card
from src.layout.single_strategy import (
    _CALENDAR_TABS,
    _SECTION3_TABS,
    make_single_strategy_panel,
    render_calendar,
    render_section3,
    render_single_strategy,
    set_calendar_kind,
    set_section3_tab,
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
            "description": ["Alpha desc", pd.NA, "Charlie desc"],
        }
    )


def test_na_helper():
    assert _na(pd.NA) == "—"
    assert _na(None) == "—"
    assert _na("   ") == "—"
    assert _na("USD") == "USD"


def test_render_profile_card_contains_fields():
    html = _render_profile_card(_meta().iloc[0])
    for token in ("Alpha", "AAA Index", "USD", "Total", "Alpha desc"):
        assert token in html


def test_render_profile_card_is_na_safe():
    # Bravo's description is NA → renders an em dash, no exception.
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


def test_render_section3_populates_all_three(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    state = SimpleNamespace(universe_prices=universe)
    ss.picker.value = "AAA Index"
    ss.bench_dd.value = "SPX Index"

    render_section3(ss, state, meta, universe.index.min())
    # Weekly scatter: markers + OLS line.
    assert len(ss.weekly_fig.data) == 2
    # Histogram: strategy + benchmark overlaid, stats grid populated.
    assert len(ss.retdist_fig.data) >= 1
    assert not ss.retdist_stats_grid.data.empty
    # Factor scatter: one monthly point cloud.
    assert len(ss.factor_fig.data) == 1


def test_section3_tab_switch_swaps_view():
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    assert ss.s3_stack.children == (ss.s3_views["weekly"],)
    set_section3_tab(ss, "factor")
    assert ss.s3_tab == "factor"
    assert ss.s3_stack.children == (ss.s3_views["factor"],)


def test_section3_tabs_match_view_keys():
    # The pill keys and the built view stack stay in lockstep.
    keys = {key for _label, key in _SECTION3_TABS}
    ss = make_single_strategy_panel(_meta())
    assert keys == set(ss.s3_views)


def test_render_section3_missing_benchmark_keeps_histogram(multiyear_prices):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    # No benchmark / factor columns in the cache — only the strategies.
    state = SimpleNamespace(universe_prices=multiyear_prices)
    ss.picker.value = "AAA Index"
    ss.bench_dd.value = "SPX Index"  # absent from the cache

    render_section3(ss, state, meta, multiyear_prices.index.min())
    assert len(ss.weekly_fig.data) == 0  # no benchmark → cleared
    assert len(ss.retdist_fig.data) >= 1  # strategy-only histogram still renders
    assert len(ss.factor_fig.data) == 0  # no factor columns → cleared


def test_render_section3_empty_cache_no_raise():
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    render_section3(ss, state, meta, pd.Timestamp("2020-01-01"))
    assert len(ss.weekly_fig.data) == 0
    assert len(ss.factor_fig.data) == 0
    assert ss.retdist_stats_grid.data.empty
