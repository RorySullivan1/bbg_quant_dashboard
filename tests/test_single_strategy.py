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
from src.layout.single_strategy import _CALENDAR_TABS, SingleStrategyPanel
from src.stats import calendar_summary_columns


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "solution": ["ARP", "ARP", "Smart Beta"],
            "category": ["T1", "T2", "T3"],
            "family": ["X", "Y", "Z"],
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
    # Return Type left the catalog table in #282 but stays here, which is where
    # a user who wants it now reads it.
    assert "Return Type" in html
    # Launch date is rendered as YYYY-MM-DD.
    assert "Launch Date" in html and "2010-03-15" in html


def test_render_profile_card_is_na_safe():
    # Bravo's description + launch date are NA → render em dashes, no exception.
    html = _render_profile_card(_meta().iloc[1])
    assert "Bravo" in html and "BBB Index" in html
    assert "—" in html


def test_render_single_strategy_populates_chart_and_grid(multiyear_prices, benchmark):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = multiyear_prices.copy()
    universe["SPXFP Index"] = benchmark  # a benchmark column rides along
    state = SimpleNamespace(universe_prices=universe)
    window_start = universe.index.min()

    ss.pick.value = "AAA Index"
    ss.state = state
    ss.render(meta, window_start)
    assert len(ss.line.fig.data) == 1  # strategy only, no overlay
    assert not ss.perf_grid.grid.data.empty
    assert "Alpha" in ss.profile_w.value

    # Toggling the overlay adds the benchmark trace.
    ss.bench_chk.value = True
    ss.bench_dd.value = "SPXFP Index"
    ss.state = state
    ss.render(meta, window_start)
    assert len(ss.line.fig.data) == 2


def test_render_single_strategy_reacts_to_pick(multiyear_prices, benchmark):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = multiyear_prices.copy()
    universe["SPXFP Index"] = benchmark
    state = SimpleNamespace(universe_prices=universe)
    window_start = universe.index.min()

    ss.pick.value = "AAA Index"
    ss.state = state
    ss.render(meta, window_start)
    assert "Alpha" in ss.profile_w.value
    ss.pick.value = "BBB Index"
    ss.state = state
    ss.render(meta, window_start)
    assert "Bravo" in ss.profile_w.value


def test_render_single_strategy_empty_cache_no_raise():
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    ss.state = state
    ss.render(meta, pd.Timestamp("2020-01-01"))
    assert len(ss.line.fig.data) == 0
    assert ss.perf_grid.grid.data.empty
    # Section 1 recompute also drives the calendar — it should clear too.
    assert ss.cal_grid.grid.data.empty


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
    ss = SingleStrategyPanel(meta, None)
    universe = multiyear_prices.copy()
    universe["SPXFP Index"] = benchmark
    state = SimpleNamespace(universe_prices=universe)
    ss.pick.value = "AAA Index"

    ss.state = state
    # The panel slices the fetched frame to the analytics window before drawing
    # (#311) — the fetch reaches a year further back than the app analyses, and
    # an unsliced calendar would grow an extra year row. `render` sets this;
    # here the whole fixture is the window.
    ss._window_start = universe.index.min()
    ss.render_calendar()
    data = ss.cal_grid.grid.data
    # Default kind is absolute → Return / Vol / Sharpe summary columns.
    assert list(data.columns) == _cal_cols("absolute")
    # Oldest year on top (ascending), years rendered as string labels.
    years = [int(y) for y in data.index]
    assert years == sorted(years)


def test_calendar_kind_switch_all_benchmark_kinds(multiyear_prices, benchmark):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = multiyear_prices.copy()
    universe["SPXFP Index"] = benchmark
    state = SimpleNamespace(universe_prices=universe)
    ss.pick.value = "AAA Index"
    ss.bench_dd.value = "SPXFP Index"
    ss._window_start = universe.index.min()  # see the note above (#311)

    for kind in ("outperformance", "vol_adjusted", "beta", "correlation"):
        ss.set_calendar_kind(kind)
        assert ss.cal_kind == kind
        ss.state = state
        ss.render_calendar()
        # Each kind drives its own summary columns.
        assert list(ss.cal_grid.grid.data.columns) == _cal_cols(kind)
        assert not ss.cal_grid.grid.data.empty


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
    universe["SPXFP Index"] = benchmark  # benchmark + equity factor leg
    rng = np.random.default_rng(11)
    for col, drift in (("LD12TRUU Index", 5e-5), ("LUTLTRUU Index", 1e-4)):
        rets = rng.normal(drift, 0.003, len(universe))
        universe[col] = 100.0 * np.cumprod(1.0 + rets)
    return universe


def _set_pane(pane, label, bench="SPXFP Index"):
    """Point a pane at one analysis (and benchmark) without going through the
    widget observer wiring (the builder owns rendering)."""
    pane.bench_dd.value = bench
    pane.picker.value = label
    pane.stack.children = (pane.views[label],)


def test_render_section3_renders_both_panes(multiyear_prices, benchmark):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    state = SimpleNamespace(universe_prices=universe)
    ss.pick.value = "AAA Index"
    # Left = weekly scatter (benchmark), right = factor scatter (factors).
    _set_pane(ss.pane_left, "Weekly Scatter")
    _set_pane(ss.pane_right, "Factor Scatter")

    ss.state = state
    ss.render_section3(meta, universe.index.min())
    assert len(ss.pane_left.weekly.fig.data) == 2  # markers + quadratic fit
    assert len(ss.pane_right.factor.fig.data) == 1  # one monthly point cloud


def test_render_analysis_pane_distribution(multiyear_prices, benchmark):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    state = SimpleNamespace(universe_prices=universe)
    ss.pick.value = "AAA Index"
    pane = ss.pane_left
    _set_pane(pane, "Return Distribution")

    ss.state = state
    ss.render_analysis_pane(pane, meta, universe.index.min())
    assert len(pane.retdist.fig.data) >= 1
    assert not pane.retdist.stats_grid.data.empty


def test_render_analysis_pane_drawdown(multiyear_prices, benchmark):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    state = SimpleNamespace(universe_prices=universe)
    ss.pick.value = "AAA Index"
    pane = ss.pane_left
    _set_pane(pane, "Drawdown")

    ss.state = state
    ss.render_analysis_pane(pane, meta, universe.index.min())
    # Strategy + benchmark drawdown lines.
    assert len(pane.dd.fig.data) == 2


def test_render_analysis_pane_factor_scoring(multiyear_prices, benchmark):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    universe["BSLXAT Index"] = benchmark  # trend factor leg
    state = SimpleNamespace(universe_prices=universe)
    ss.pick.value = "AAA Index"
    pane = ss.pane_left
    _set_pane(pane, "Factor Scoring")

    ss.state = state
    ss.render_analysis_pane(pane, meta, universe.index.min())
    bar = pane.factor_score.fig.data[0]
    # All three macro-factor betas resolve from the mock cache.
    assert list(bar.x) == ["Equity risk premium", "Term premium", "Trend"]
    assert len(bar.y) == 3


def test_render_analysis_pane_stubs_show_placeholder():
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    for label, chart_attr in (
        ("Performance Ranking", "ranking"),
        ("PCA Analysis", "pca"),
        ("Defensive Scoring", "defensive"),
    ):
        pane = ss.pane_left
        _set_pane(pane, label)
        ss.state = state
        ss.render_analysis_pane(pane, meta, pd.Timestamp("2020-01-01"))
        fig = getattr(pane, chart_attr).fig
        assert len(fig.data) == 0
        assert len(fig.layout.annotations) == 1


def test_analysis_options_match_pane_views():
    # The option list and the built view stack stay in lockstep, and every
    # benchmark-dependent view is a real option.
    ss = SingleStrategyPanel(_meta(), None)
    assert set(SINGLE_ANALYSIS_OPTIONS) == set(ss.pane_left.views)
    assert set(SINGLE_ANALYSIS_OPTIONS) >= _SINGLE_BENCHMARK_VIEWS


def test_render_section3_missing_benchmark_keeps_histogram(multiyear_prices):
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    # No benchmark / factor columns in the cache — only the strategies.
    state = SimpleNamespace(universe_prices=multiyear_prices)
    ss.pick.value = "AAA Index"
    _set_pane(ss.pane_left, "Weekly Scatter")  # benchmark absent → cleared
    _set_pane(ss.pane_right, "Return Distribution")

    ss.state = state
    ss.render_section3(meta, multiyear_prices.index.min())
    # Weekly scatter traces are pre-allocated (in-place update), so "cleared"
    # means the marker trace has no points, not zero traces.
    assert len(ss.pane_left.weekly.fig.data) == 2
    assert not ss.pane_left.weekly.fig.data[0].x  # no benchmark → cleared
    # Strategy-only histogram still renders.
    assert len(ss.pane_right.retdist.fig.data) >= 1


def test_render_section3_empty_cache_no_raise():
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    _set_pane(ss.pane_left, "Weekly Scatter")
    _set_pane(ss.pane_right, "Factor Scatter")
    ss.state = state
    ss.render_section3(meta, pd.Timestamp("2020-01-01"))
    # Weekly scatter keeps its 2 pre-allocated traces but with no data points.
    assert len(ss.pane_left.weekly.fig.data) == 2
    assert not ss.pane_left.weekly.fig.data[0].x
    assert len(ss.pane_right.factor.fig.data) == 0


# --- the panel object model (#244) -------------------------------------------


def test_panel_owns_its_widgets_and_opens_on_the_first_calendar_kind():
    import ipywidgets as W
    from src.layout.panes import SingleAnalysisPane

    ss = SingleStrategyPanel(_meta(), None)
    assert isinstance(ss.root, W.VBox)
    assert ss.cal_kind == _CALENDAR_TABS[0][1]
    assert len(ss.cal_pills) == len(_CALENDAR_TABS)
    for pane in (ss.pane_left, ss.pane_right):
        assert isinstance(pane, SingleAnalysisPane)
    assert ss.pane_left is not ss.pane_right


def test_two_panels_share_no_widgets():
    # Nothing builds two today, but a shared chart or picker would make one
    # panel's render overwrite the other's — the same trap #216 guarded for.
    a, b = SingleStrategyPanel(_meta(), None), SingleStrategyPanel(_meta(), None)
    assert a.line.fig is not b.line.fig
    assert a.pick is not b.pick
    assert a.pane_left.weekly.fig is not b.pane_left.weekly.fig
    a.set_calendar_kind("outperformance")
    assert b.cal_kind == _CALENDAR_TABS[0][1]


def test_set_calendar_kind_restyles_only_the_active_pill():
    ss = SingleStrategyPanel(_meta(), None)
    for _label, kind in _CALENDAR_TABS:
        ss.set_calendar_kind(kind)
        assert ss.cal_kind == kind
        active = [
            k
            for pill, (_l, k) in zip(ss.cal_pills, _CALENDAR_TABS, strict=True)
            if "is-active" in pill._dom_classes
        ]
        assert active == [kind]


# --- the fetched frame is longer than the analysis window (#311) -----------
#
# The fetch reaches a year further back than the app analyses, so the panel has
# to slice. Two of its consumers read whatever frame they are given end to end
# — `since_inception_perf` and `calendar_return_table` — and neither sliced
# before, because until #311 the two horizons were the same number. These pin
# that a longer frame changes neither.


def _panel_with(prices: pd.DataFrame) -> SingleStrategyPanel:
    ss = SingleStrategyPanel(_meta(), None)
    ss.state = SimpleNamespace(universe_prices=prices)
    ss.pick.value = "AAA Index"
    return ss


def test_a_longer_fetch_does_not_move_the_since_inception_row(multiyear_prices):
    """SI is whole-frame, so an extra year of history would silently deepen it.

    It means "since the fetch start" already, for any index older than the
    window; what must not happen is that meaning changing under the reader
    because the fetch grew for the leaderboard's benefit.
    """
    window_start = multiyear_prices.index.min()
    older = pd.DataFrame(
        50.0,
        index=pd.bdate_range(window_start - pd.Timedelta(days=365), window_start)[:-1],
        columns=multiyear_prices.columns,
    )
    longer = pd.concat([older, multiyear_prices])

    short_row = _panel_with(multiyear_prices)
    short_row.render(_meta(), window_start)
    long_row = _panel_with(longer)
    long_row.render(_meta(), window_start)

    si = [c for c in short_row.perf_grid.grid.data.columns if str(c).startswith("SI")]
    assert si, "no since-inception columns on the perf grid"
    pd.testing.assert_frame_equal(
        short_row.perf_grid.grid.data[si], long_row.perf_grid.grid.data[si]
    )


def test_a_longer_fetch_fills_a_window_the_shorter_one_left_blank(multiyear_prices):
    """The other half of the same decision, and a pre-existing bug it fixes.

    `perf_table` keeps the **full** frame on purpose: it slices per window
    internally, and it blanks a window whose first valid row is even a day
    short of `years * 365.25`. The fetch start is a `DateOffset` and the first
    trading row snaps forward off a weekend, so the two disagree — measured on
    2026-09-18 the catalog's whole `5Y` column is blank, and it blanks on ~20%
    of business days. The extra year the fetch now carries settles it.
    """
    window_start = multiyear_prices.index.min()
    older = pd.DataFrame(
        50.0,
        index=pd.bdate_range(window_start - pd.Timedelta(days=365), window_start)[:-1],
        columns=multiyear_prices.columns,
    )
    longer = pd.concat([older, multiyear_prices])

    short_row = _panel_with(multiyear_prices)
    short_row.render(_meta(), window_start)
    long_row = _panel_with(longer)
    long_row.render(_meta(), window_start)

    # The fixture spans just under three years, so `3Y` is the window on the
    # boundary: blank on the short frame, populated once the history reaches.
    assert short_row.perf_grid.grid.data["3Y Return"].isna().all()
    assert long_row.perf_grid.grid.data["3Y Return"].notna().all()


def test_a_longer_fetch_does_not_grow_the_calendar(multiyear_prices):
    # `calendar_return_table` pivots every month it is handed, so an unsliced
    # frame would add a whole year row and restate the oldest year's summary.
    window_start = multiyear_prices.index.min()
    older = pd.DataFrame(
        50.0,
        index=pd.bdate_range(window_start - pd.Timedelta(days=365), window_start)[:-1],
        columns=multiyear_prices.columns,
    )
    longer = pd.concat([older, multiyear_prices])

    short_cal = _panel_with(multiyear_prices)
    short_cal.render(_meta(), window_start)
    long_cal = _panel_with(longer)
    long_cal.render(_meta(), window_start)

    pd.testing.assert_frame_equal(
        short_cal.cal_grid.grid.data, long_cal.cal_grid.grid.data
    )
