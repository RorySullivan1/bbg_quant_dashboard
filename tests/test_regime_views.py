"""The two Single Strategy regime views, and the controls they share (#369,
#370).

**The shared module is the point.** Regime resolution had one implementation
and it lived on `PlatformAnalytics`; these two charts ask the same question,
and the risk #363 names is four methods copied into a second class where the
two copies then drift. So `RegimeControls` is pinned here as the one answer,
and both charts are pinned to read it.

The mock catalog's histories share a start date and move together, so the
conditioning tests build **synthetic** series where a bucket is genuinely a
different regime — which is the only way to tell "conditioned" from
"re-sliced the same answer".
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from src.layout.charts import DecileChart, RegimeProfileChart, WeeklyScatterChart
from src.layout.regime_controls import (
    RegimeControls,
    regime_bucket_options,
    regime_window_mask,
)
from src.stats import decile_profile, regime_risk_return
from src.style import Color


@pytest.fixture
def two_regimes() -> pd.DataFrame:
    """A cache whose VIX splits the sample into two genuinely different halves.

    Calm first, stormy second: the strategy earns steadily while VIX is low
    and loses with triple the volatility while it is high. A chart that does
    not actually condition draws the blend for both.
    """
    index = pd.bdate_range("2016-01-01", "2026-01-01")
    half = len(index) // 2
    rng = np.random.default_rng(21)

    vix = np.concatenate([np.full(half, 12.0), np.full(len(index) - half, 30.0)])
    calm = rng.normal(0.0008, 0.004, half)
    storm = rng.normal(-0.0009, 0.012, len(index) - half)
    strategy = np.concatenate([calm, storm])
    bench = np.concatenate(
        [rng.normal(0.0006, 0.005, half), rng.normal(-0.0007, 0.014, len(index) - half)]
    )
    return pd.DataFrame(
        {
            "VIX Index": vix,
            "AAA Index": 100 * np.cumprod(1 + strategy),
            "SPTR Index": 100 * np.cumprod(1 + bench),
        },
        index=index,
    )


def _controls(prices: pd.DataFrame, *, buckets: bool = True) -> RegimeControls:
    state = SimpleNamespace(universe_prices=prices, benchmarks=None)
    return RegimeControls(state, buckets=buckets)


# --- the shared controls ------------------------------------------------------


def test_the_toggle_is_gated_in_the_indicator(two_regimes):
    """v0.9.33's rule, and the reason it is one place.

    An absent indicator already means "draw every day in the window", so the
    off state takes the same path rather than adding a branch at each render
    — and no future reader of the indicator can miss the switch.
    """
    controls = _controls(two_regimes)
    assert controls.on.value is False, "off by default: a bucket is a subset"
    assert controls.indicator() is None

    controls.on.value = True
    assert controls.indicator() is not None


def test_an_unconditioned_mask_selects_every_day(two_regimes):
    index = two_regimes.index
    assert regime_window_mask(None, index, None, None).all()
    # And the three ways there can be no conditioning collapse to one answer.
    controls = _controls(two_regimes)
    low, high = controls.resolve_bucket()
    assert regime_window_mask(controls.indicator(), index, low, high).all()


def test_a_chart_drawing_every_bucket_builds_without_bucket_chips(two_regimes):
    """#363 dec. 8: all three buckets are the chart, so there is nothing for
    a bucket chip to select."""
    controls = _controls(two_regimes, buckets=False)
    assert controls.buckets is None
    assert controls.resolve_bucket() == (None, None)
    # It still enumerates them, which is what the chart loops over.
    assert len(controls.bucket_keys()) == 3


def test_the_bucket_keys_are_the_chips_options(two_regimes):
    """One source, so a bucket cannot exist on the chips and not in a chart."""
    controls = _controls(two_regimes)
    assert controls.bucket_keys() == regime_bucket_options(controls.types.value)
    assert [v for _, v in controls.buckets.options] == [
        v for _, v in controls.bucket_keys()
    ]


# --- the decile chart ---------------------------------------------------------


def test_the_benchmark_decides_the_buckets(two_regimes):
    """Cutting on the strategy's own returns would sort the answer into the
    question and draw a monotone staircase for any series at all."""
    from src.stats import weekly_returns

    weekly = weekly_returns(two_regimes[["AAA Index", "SPTR Index"]])
    profile = decile_profile(weekly["AAA Index"], weekly["SPTR Index"])
    assert len(profile) == 10
    # The benchmark column is monotone by construction — it *is* the sort.
    bench = profile["benchmark"].to_numpy()
    assert (np.diff(bench) > 0).all()


def test_conditioning_the_deciles_changes_them(two_regimes):
    """The acceptance case: on and off must not draw the same columns.

    Re-cutting inside the bucket is the only thing that answers "what does
    this look like when volatility is high" — slicing a full-sample cut would
    keep the calm regime's decile edges.
    """
    from src.stats import weekly_returns

    weekly = weekly_returns(two_regimes[["AAA Index", "SPTR Index"]])
    vix = two_regimes["VIX Index"]

    plain = decile_profile(weekly["AAA Index"], weekly["SPTR Index"])
    stormy = regime_window_mask(vix, weekly.index, 25.0, float("inf"))
    conditioned = decile_profile(weekly["AAA Index"], weekly["SPTR Index"], mask=stormy)

    assert not conditioned.empty
    assert not np.allclose(
        plain["strategy"].to_numpy(), conditioned["strategy"].to_numpy()
    )
    # The stormy bucket is the losing half, so its deciles sit lower.
    assert conditioned["strategy"].mean() < plain["strategy"].mean()


def test_a_sample_too_short_to_cut_draws_nothing(two_regimes):
    short = two_regimes.iloc[:6]
    assert decile_profile(short["AAA Index"], short["SPTR Index"]).empty
    chart = DecileChart()
    chart.update(pd.DataFrame())
    assert len(chart.fig.data) == 0


def test_the_decile_chart_draws_ten_pairs_and_names_the_regime(two_regimes):
    from src.stats import weekly_returns

    weekly = weekly_returns(two_regimes[["AAA Index", "SPTR Index"]])
    chart = DecileChart()
    chart.update(
        decile_profile(weekly["AAA Index"], weekly["SPTR Index"]),
        strategy_label="AAA",
        benchmark_label="SPTR",
        regime_label="Volatility: VIX ≥ 25",
    )
    assert [t.name for t in chart.fig.data] == ["AAA", "SPTR"]
    assert len(chart.fig.data[0].x) == 10
    # The conditioning is in the title, because a narrowed sample the reader
    # cannot see is v0.9.33's whole complaint.
    assert "VIX ≥ 25" in chart.fig.layout.title.text


# --- the regime profile -------------------------------------------------------


def test_the_regime_profile_points_match_regime_risk_return(two_regimes):
    """The acceptance case: the three points against hand-built masks."""
    from src.stats import daily_returns

    rets = daily_returns(two_regimes[["AAA Index"]])
    vix = two_regimes["VIX Index"]
    calm = regime_window_mask(vix, rets.index, -float("inf"), 15.0)
    storm = regime_window_mask(vix, rets.index, 25.0, float("inf"))

    calm_point = regime_risk_return(rets, calm)
    storm_point = regime_risk_return(rets, storm)

    # The synthetic regimes are genuinely different, which is what makes the
    # chart worth drawing at all.
    assert calm_point.loc["AAA Index", "ret"] > storm_point.loc["AAA Index", "ret"]
    assert calm_point.loc["AAA Index", "vol"] < storm_point.loc["AAA Index", "vol"]


def _profile_points(series: str = "AAA", series_index: int = 0) -> pd.DataFrame:
    """One series' anchor plus its three buckets, as the renderer builds them."""
    label = RegimeProfileChart.ANCHOR_LABEL
    return pd.DataFrame(
        {
            "series": [f"{series} — {label}", series, series, series],
            "anchor": [True, False, False, False],
            "series_index": [series_index] * 4,
            "vol": [0.10, 0.05, 0.10, 0.25],
            "ret": [0.04, 0.09, 0.03, -0.12],
        },
        index=pd.Index([label, "VIX < 15", "15 ≤ VIX < 25", "VIX ≥ 25"], name="bucket"),
    )


def test_the_regime_profile_sets_the_anchor_apart_by_shape(two_regimes):
    chart = RegimeProfileChart()
    chart.update(_profile_points(), regime_label="Volatility")

    label = RegimeProfileChart.ANCHOR_LABEL
    anchor = next(t for t in chart.fig.data if label in t.name)
    buckets = next(t for t in chart.fig.data if t.name == "AAA")
    assert len(buckets.x) == 3, "one marker per bucket"
    assert anchor.marker.symbol == "diamond-open", "the anchor is set apart"
    assert anchor.marker.size > buckets.marker.size
    assert "Volatility" in chart.fig.layout.title.text


def test_the_anchor_is_called_full_period_everywhere(two_regimes):
    """#381. One spelling, read from the chart rather than typed at the
    renderer — it was "Whole window" in `charts.py` and "whole window" in
    `single_strategy.py`, two strings that had to agree by hand."""
    assert RegimeProfileChart.ANCHOR_LABEL == "Full period"

    chart = RegimeProfileChart()
    chart.update(_profile_points())
    names = [t.name for t in chart.fig.data]
    assert any("Full period" in n for n in names)
    assert not any("whole window" in n.lower() for n in names)


def test_the_anchor_wears_its_own_series_colour(two_regimes):
    """#381. The anchor and its buckets are one series and read as one, so
    they share a colour; the two *series* differ.

    The bug this pins: `groupby` enumeration coloured by **group**, and with
    a benchmark on there are four groups for two series — so a series' anchor
    and its cloud came out in different colours and the pairing was legend
    work rather than something the eye did.
    """
    points = pd.concat([_profile_points("AAA", 0), _profile_points("BBB", 1)])
    chart = RegimeProfileChart()
    chart.update(points, benchmark_label="BBB")

    label = RegimeProfileChart.ANCHOR_LABEL
    by_name = {t.name: t for t in chart.fig.data}
    assert len(by_name) == 4, "an anchor and a cloud for each of two series"
    for series in ("AAA", "BBB"):
        assert (
            by_name[f"{series} — {label}"].marker.color == by_name[series].marker.color
        ), f"{series}'s anchor and buckets must share a colour"
    assert by_name["AAA"].marker.color != by_name["BBB"].marker.color

    # The text under each marker follows the marker, not a muted grey.
    for trace in chart.fig.data:
        assert trace.textfont.color == trace.marker.color


def test_a_bucket_with_too_few_days_is_absent_not_invented(two_regimes):
    """`regime_risk_return` gives an empty frame below two days, and a point
    built from one would be the worst kind of wrong on this chart."""
    from src.stats import daily_returns

    rets = daily_returns(two_regimes[["AAA Index"]])
    one_day = pd.Series(False, index=rets.index)
    one_day.iloc[5] = True
    assert regime_risk_return(rets, one_day).empty


def test_an_empty_frame_clears_rather_than_drawing_axes(two_regimes):
    chart = RegimeProfileChart()
    chart.update(pd.DataFrame())
    assert len(chart.fig.data) == 0


# --- the Weekly Scatter's regime (#382) ---------------------------------------


def _weekly_pair(prices: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    from src.stats import weekly_returns

    weekly = weekly_returns(prices[["SPTR Index", "AAA Index"]])
    return weekly["SPTR Index"], weekly["AAA Index"]


def test_the_weekly_scatter_is_unchanged_with_no_regime(two_regimes):
    """Off is the path both states share, not a second branch (v0.9.33). With
    no mask the conditioned pair is empty and hidden, and the full cloud keeps
    its own colour rather than being muted for a subject that is not there."""
    x, y = _weekly_pair(two_regimes)
    chart = WeeklyScatterChart()
    chart.update(x, y)

    marker, fit, in_marker, in_fit = chart.fig.data
    assert len(marker.x) == len(x.dropna())
    assert len(fit.x) > 0
    assert not in_marker.x and not in_fit.x
    assert in_marker.visible is False and in_fit.visible is False
    assert marker.marker.color != Color.TEXT_MUTED.value


def test_a_regime_draws_both_clouds_and_moves_the_fit(two_regimes):
    """The ask: the conditioned series **and** the unconditioned one, so the
    reader sees the relationship move rather than a cloud that shrank.

    On this fixture the calm half and the stormy half are genuinely different
    regressions, so a chart that merely re-sliced the same answer would give
    the two fits the same coefficients.
    """
    x, y = _weekly_pair(two_regimes)
    controls = _controls(two_regimes)
    controls.on.value = True
    controls.types.value = "Volatility"
    controls.sync()
    low, high = controls.resolve_bucket()
    mask = regime_window_mask(controls.indicator(), x.index, low, high)

    chart = WeeklyScatterChart()
    chart.update(x, y, mask=mask, regime_label="Volatility: VIX < 15")

    marker, fit, in_marker, in_fit = chart.fig.data
    # Both clouds are on screen, and the conditioned one is the subset.
    assert len(marker.x) == len(x.dropna())
    assert 0 < len(in_marker.x) < len(marker.x)
    assert in_marker.visible and in_fit.visible
    # The full cloud steps back so the conditioned one reads as the subject.
    assert marker.marker.color == Color.TEXT_MUTED.value
    # Two genuinely different fits, not one answer drawn twice.
    assert list(fit.y) != list(in_fit.y)
    # And the panel reports both, labelled.
    text = chart.fig.layout.annotations[0].text
    assert "all:" in text and "Volatility: VIX < 15" in text
    assert "<br>" in text, "one line per fit"


def test_too_few_conditioned_weeks_still_draw_their_markers(two_regimes):
    """A bucket with almost no weeks keeps its points and says why there is no
    fit — an empty panel would read as "the regime never happened"."""
    x, y = _weekly_pair(two_regimes)
    mask = pd.Series(False, index=x.index)
    mask.iloc[0] = True

    chart = WeeklyScatterChart()
    chart.update(x, y, mask=mask, regime_label="Volatility: VIX ≥ 25")

    _marker, _fit, in_marker, in_fit = chart.fig.data
    assert len(in_marker.x) == 1
    assert not in_fit.x, "one week cannot be fitted"
    assert "too few to fit" in chart.fig.layout.annotations[0].text


def test_the_weekly_scatter_has_its_own_regime_controls():
    """Its own instance, like the Decile chart's: two views each conditioning
    their own chart is two selections, not one shared one."""
    from src.layout.panes import _make_single_analysis_pane

    pane = _make_single_analysis_pane("left")
    assert pane.weekly_regime is not None
    assert pane.weekly_regime is not pane.decile_regime
    assert pane.weekly_regime is not pane.regime
    # Off by default, and its dependents are mounted in the view.
    assert pane.weekly_regime.on.value is False
    mounted = pane.views["Weekly Scatter"].children
    for control in (
        pane.weekly_regime.on,
        pane.weekly_regime.types,
        pane.weekly_regime.source,
        pane.weekly_regime.buckets,
    ):
        assert control in mounted
