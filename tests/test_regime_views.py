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
from src.layout.charts import DecileChart, RegimeProfileChart
from src.layout.regime_controls import (
    RegimeControls,
    regime_bucket_options,
    regime_window_mask,
)
from src.stats import decile_profile, regime_risk_return


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


def test_the_regime_profile_draws_the_anchor_muted(two_regimes):
    points = pd.DataFrame(
        {
            "series": ["AAA — whole window", "AAA", "AAA", "AAA"],
            "anchor": [True, False, False, False],
            "vol": [0.10, 0.05, 0.10, 0.25],
            "ret": [0.04, 0.09, 0.03, -0.12],
        },
        index=pd.Index(
            ["Whole window", "VIX < 15", "15 ≤ VIX < 25", "VIX ≥ 25"], name="bucket"
        ),
    )
    chart = RegimeProfileChart()
    chart.update(points, regime_label="Volatility")

    anchor = next(t for t in chart.fig.data if "whole window" in t.name)
    buckets = next(t for t in chart.fig.data if t.name == "AAA")
    assert len(buckets.x) == 3, "one marker per bucket"
    assert anchor.marker.symbol == "diamond-open", "the anchor is set apart"
    assert anchor.marker.size > buckets.marker.size
    assert "Volatility" in chart.fig.layout.title.text


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
