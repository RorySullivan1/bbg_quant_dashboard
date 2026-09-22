"""Tests for the Single Strategy tab (v0.9.0 Workstreams C + D).

Covers the pure profile-card renderer (incl. NA-safety), the Section 1 recompute
(`render_single_strategy`), and the Section 2 monthly-return calendar
(`render_calendar` / `set_calendar_kind`) against a mock cache: chart traces, the
benchmark overlay, the perf table, calendar shape/kind switching, and guards.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pandas as pd
from src.layout.html import _fmt_date, _na, _render_profile_card
from src.layout.panes import _SINGLE_BENCHMARK_VIEWS, SINGLE_ANALYSIS_OPTIONS
from src.layout.single_strategy import _CALENDAR_TABS, SingleStrategyPanel
from src.stats import calendar_summary_columns, strategy_metrics


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
    assert "<table class='bbg-metrics'>" in ss.metrics_w.value
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
    assert ss.metrics_w.value == ""
    # Section 1 recompute also drives the calendar — it should clear too.
    assert ss.cal_w.value == ""


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
    html = ss.cal_w.value
    # Default kind is absolute → Return / Vol / Sharpe summary columns, each
    # a header in the rendered table beside the twelve months.
    for column in _cal_cols("absolute"):
        assert f">{column}<" in html
    # Oldest year on top (ascending).
    years = [int(y) for y in re.findall(r"<tr><th>(\d{4})</th>", html)]
    assert years and years == sorted(years)


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
        html = ss.cal_w.value
        for column in _cal_cols(kind):
            assert f">{column}<" in html
        assert "<tbody>" in html and re.search(r"<tr><th>\d{4}</th>", html)


def test_calendar_tabs_cover_every_kind():
    # The chip set and the calendar_return_table kinds stay in lockstep.
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


def _state(universe, *, catalog=("AAA Index", "BBB Index", "CCC Index")):
    """A `DashboardState` stub carrying the fields the panel actually reads.

    A bare `SimpleNamespace(universe_prices=...)` covered every renderer until
    the risk profile, which needs the **catalog** — the percentile axis is a
    cross-section, so the panel reads `arp_universe_prices` too. Building the
    stub in one place keeps a new reader from being a per-test surprise.
    """
    held = [t for t in catalog if t in universe.columns]
    return SimpleNamespace(
        universe_prices=universe,
        arp_universe_prices=universe[held],
        universe_rets=None,
    )


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
    # Markers + quadratic fit, twice: the unconditioned pair and the
    # regime-conditioned pair, both pre-allocated (#382).
    assert len(ss.pane_left.weekly.fig.data) == 4
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
    assert pane.retdist.stats_w.value, "the stats table is drawn too"


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


def test_render_analysis_pane_risk_profile(multiyear_prices, benchmark):
    """The five-β spiderweb on a percentile axis (#372).

    It replaced `FactorScoringChart`, three bars of ERP / Term / Trend — no
    Carry, no Volatility, and no way to tell a large β from a small one, the
    betas being on wildly different scales.
    """
    from src.layout.charts import RISK_PROFILE_FACTORS

    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    universe["BSLXAT Index"] = benchmark  # trend leg
    universe["BSLXAC Index"] = benchmark * 1.01  # carry leg
    ss.state = _state(universe)
    ss.pick.value = "AAA Index"
    pane = ss.pane_left
    _set_pane(pane, "Risk Profile")

    ss.render_analysis_pane(pane, meta, universe.index.min())
    trace = pane.risk_profile.fig.data[0]
    # Volatility has no VIX/MOVE legs in this cache, so it is a **missing
    # spoke** rather than an exception — four points plus the closing one.
    drawn = list(trace.theta)[:-1]
    assert set(drawn) <= set(RISK_PROFILE_FACTORS)
    assert "Volatility" not in drawn
    assert drawn, "the factors that do resolve still draw"
    # Every radius is a percentile, so every one is in [0, 1] — which is the
    # point of the axis, the raw betas being incomparable across spokes.
    assert all(0.0 <= float(r) <= 1.0 for r in trace.r)
    # And the raw β rides in the hover.
    assert len(trace.customdata) == len(trace.r)


def test_the_factor_cross_section_is_measured_once_per_price_frame():
    """Five `factor_beta` passes over the universe on every pick would be the
    one expensive thing on this tab (#363's risk note).

    Cached against the frame's **identity**, the `QuantColumns` pattern: a
    Refresh rebinds `arp_universe_prices` and invalidates it without anything
    having to remember to.
    """
    import numpy as np

    index = pd.bdate_range("2021-01-01", "2026-01-01")
    rng = np.random.default_rng(4)
    frame = pd.DataFrame(
        {
            t: 100 * np.cumprod(1 + rng.normal(0.0003, 0.008, len(index)))
            for t in ("AAA Index", "BBB Index", "CCC Index")
        },
        index=index,
    )
    ss = SingleStrategyPanel(_meta(), None)
    ss.state = _state(frame)

    first = ss._factor_panel()
    assert first is ss._factor_panel(), "a second pick is a lookup"

    # A Refresh rebinds the frame, which is what invalidates it.
    ss.state.arp_universe_prices = frame.copy()
    assert ss._factor_panel() is not first


def test_every_analysis_option_draws(multiyear_prices, benchmark):
    """No option is a dead end (#367).

    Three of eight were: *PCA Analysis* and *Defensive Scoring* drew *coming
    soon*, and *Performance Ranking* drew the same placeholder because
    nothing ever passed it scores. Each is retired into an issue (#374, #375,
    #376) rather than left in a picker.
    """
    meta = _meta()
    ss = SingleStrategyPanel(meta, None)
    universe = _universe_with_factors(multiyear_prices, benchmark)
    universe["BSLXAT Index"] = benchmark
    universe["BSLXAC Index"] = benchmark * 1.01
    ss.state = _state(universe)
    ss.pick.value = "AAA Index"

    for label in SINGLE_ANALYSIS_OPTIONS:
        pane = ss.pane_left
        _set_pane(pane, label)
        ss.render_analysis_pane(pane, meta, universe.index.min())
        figures = [w for w in pane.views[label].children if hasattr(w, "layout")]
        annotations = [
            a
            for fig in figures
            for a in getattr(getattr(fig, "layout", None), "annotations", ()) or ()
        ]
        assert all(
            not (a.text or "").lower().endswith("coming soon") for a in annotations
        ), f"{label} draws a placeholder"


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
    assert len(ss.pane_left.weekly.fig.data) == 4
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
    # Weekly scatter keeps its 4 pre-allocated traces but with no data points.
    assert len(ss.pane_left.weekly.fig.data) == 4
    assert all(not trace.x for trace in ss.pane_left.weekly.fig.data)
    assert len(ss.pane_right.factor.fig.data) == 0


# --- the panel object model (#244) -------------------------------------------


def test_panel_owns_its_widgets_and_opens_on_the_first_calendar_kind():
    import ipywidgets as W
    from src.layout.panes import SingleAnalysisPane

    ss = SingleStrategyPanel(_meta(), None)
    assert isinstance(ss.root, W.VBox)
    assert ss.cal_kind == _CALENDAR_TABS[0][1]
    assert [v for _, v in ss.cal_chips.options] == [k for _, k in _CALENDAR_TABS]
    for pane in (ss.pane_left, ss.pane_right):
        assert isinstance(pane, SingleAnalysisPane)
    assert ss.pane_left is not ss.pane_right


def test_every_bar_chip_group_on_the_tab_lays_out_as_a_row():
    """#383. A `_ChipStack` is a `VBox` that runs horizontally only when built
    with `row=True`. The calendar's *View* chips were the one group in a
    `control_bar` that was not, so five chips stacked five high inside a
    section whose height is fixed at `CALENDAR_HEIGHT`.

    Asserted for every chip group the tab puts in a bar rather than for the
    calendar's alone, so the next one added has to make the same choice
    deliberately.
    """
    ss = SingleStrategyPanel(_meta(), None)
    for name in ("cal_chips", "window_chips", "group_chips", "filter_dim_chips"):
        chips = getattr(ss, name)
        assert "bbg-chip-row" in chips._dom_classes, name
        assert chips.layout.flex_flow == "row wrap", name


def test_two_panels_share_no_widgets():
    # Nothing builds two today, but a shared chart or picker would make one
    # panel's render overwrite the other's — the same trap #216 guarded for.
    a, b = SingleStrategyPanel(_meta(), None), SingleStrategyPanel(_meta(), None)
    assert a.line.fig is not b.line.fig
    assert a.pick is not b.pick
    assert a.pane_left.weekly.fig is not b.pane_left.weekly.fig
    a.set_calendar_kind("outperformance")
    assert b.cal_kind == _CALENDAR_TABS[0][1]


def test_set_calendar_kind_moves_the_chip_group():
    """The chips paint themselves, so the panel only records the kind (#366).

    With `_make_tab_button` pills it had to restyle five buttons by hand and
    a missed one left two looking active; a `ChipGroup`'s selection is a
    trait, so there is one place for it to be wrong.
    """
    ss = SingleStrategyPanel(_meta(), None)
    for _label, kind in _CALENDAR_TABS:
        ss.set_calendar_kind(kind)
        assert ss.cal_kind == kind
        assert ss.cal_chips.value == kind


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
    """Since-inception is whole-frame, so an extra year would deepen it.

    It means "since the fetch start" for any index older than the window;
    what must not happen is that meaning changing under the reader because
    the fetch grew for the leaderboard's benefit. `render` slices to the
    analytics window before measuring, which is what pins it.
    """
    window_start = multiyear_prices.index.min()
    longer = _with_a_year_more(multiyear_prices, window_start)

    short_row = _panel_with(multiyear_prices)
    short_row.render(_meta(), window_start)
    long_row = _panel_with(longer)
    long_row.render(_meta(), window_start)

    assert short_row.metrics_w.value == long_row.metrics_w.value


def test_a_longer_fetch_does_not_fill_a_window_the_window_cannot_serve(
    multiyear_prices,
):
    """The other half of that decision, and the one thing #366 changed.

    `perf_table` kept the **full** frame on purpose, so the extra year the
    fetch carries settled a `3Y` column that blanked on ~20% of business days
    (#311). The metrics table does not: it measures the analytics window, and
    a window the *window* cannot serve stays a dash whatever the fetch holds.
    That is the honest reading — a 3Y number the ten-year window has the data
    for is a 3Y number; one assembled from history the window excludes is a
    number under a label that does not describe it.
    """
    window_start = multiyear_prices.index.min()
    longer = _with_a_year_more(multiyear_prices, window_start)

    short_row = _panel_with(multiyear_prices)
    short_row.render(_meta(), window_start)
    long_row = _panel_with(longer)
    long_row.render(_meta(), window_start)

    # The fixture spans just under three years, so `3Y` is the window on the
    # boundary — and it is unserved on both, because both are sliced to it.
    assert short_row.metrics_w.value == long_row.metrics_w.value
    frame = strategy_metrics(
        multiyear_prices.loc[multiyear_prices.index >= window_start], "AAA Index"
    )
    assert frame.loc["Return", "3Y"] != frame.loc["Return", "3Y"]  # NaN
    assert frame.loc["Return", "1Y"] == frame.loc["Return", "1Y"]  # served


def test_a_longer_fetch_does_not_grow_the_calendar(multiyear_prices):
    # `calendar_return_table` pivots every month it is handed, so an unsliced
    # frame would add a whole year row and restate the oldest year's summary.
    window_start = multiyear_prices.index.min()
    longer = _with_a_year_more(multiyear_prices, window_start)

    short_cal = _panel_with(multiyear_prices)
    short_cal.render(_meta(), window_start)
    long_cal = _panel_with(longer)
    long_cal.render(_meta(), window_start)

    assert short_cal.cal_w.value == long_cal.cal_w.value


def _with_a_year_more(prices: pd.DataFrame, window_start) -> pd.DataFrame:
    """`prices` with a flat year of history bolted on in front of it."""
    older = pd.DataFrame(
        50.0,
        index=pd.bdate_range(window_start - pd.Timedelta(days=365), window_start)[:-1],
        columns=prices.columns,
    )
    return pd.concat([older, prices])
