"""Unit tests for the v0.8.0 commentary builders.

``build_superlatives`` (whole-catalog monthly extremes) and
``build_launch_cards`` (new-launch metadata) are pure functions over small
fixed frames, mirroring the ``test_stats.py`` conventions. The legacy
``build_highlights`` stays untested here (it is removed in Workstream C).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from src import commentary
from src.stats import daily_returns


def _meta(rows: list[dict]) -> pd.DataFrame:
    """Metadata frame with the columns the builders read."""
    frame = pd.DataFrame(rows)
    frame["live_date"] = pd.to_datetime(frame["live_date"])
    return frame


SUPERLATIVE_LABELS = {
    "Best performer",
    "Worst performer",
    "Most trending",
    "Most mean-reverting",
    "Longest bull run",
    "Longest bear run",
    "Most extended up",
    "Most extended down",
    "Largest drawup",
    "Deepest drawdown",
    "Best risk-adjusted",
    "Worst risk-adjusted",
    "Highest win rate",
    "Lowest win rate",
    "Most positive skew",
    "Most negative skew",
}


def _superlative_prices(bdays):
    """Three noisy series with well-separated drift → deterministic extremes."""
    rng = np.random.default_rng(5)
    idx = bdays(40)
    n = len(idx)
    specs = {"AAA Index": 0.004, "BBB Index": -0.004, "CCC Index": 0.0}
    data = {
        t: 100.0 * np.cumprod(1.0 + rng.normal(d, 0.002, n)) for t, d in specs.items()
    }
    return pd.DataFrame(data, index=idx)


def test_build_superlatives_all_cards_and_extremes(bdays):
    prices = _superlative_prices(bdays)
    returns = daily_returns(prices)
    meta = _meta(
        [
            {"ticker": "AAA Index", "name": "Alpha", "live_date": "2010-01-01"},
            {"ticker": "BBB Index", "name": "Beta", "live_date": "2010-01-01"},
            {"ticker": "CCC Index", "name": "Gamma", "live_date": "2010-01-01"},
        ]
    )
    cards = commentary.build_superlatives(meta, prices, returns, window_days=21)

    assert {c["label"] for c in cards} == SUPERLATIVE_LABELS
    for c in cards:
        assert set(c) >= {
            "label",
            "value",
            "name",
            "ticker",
            "sentiment",
            "description",
        }
        assert c["description"]  # every card carries a hover description

    by_label = {c["label"]: c for c in cards}
    # No asset_class column → all tickers share one cohort, so the demeaned
    # z-rank is monotonic in the raw metric and the extremes match the raw ones.
    assert by_label["Best performer"]["ticker"] == "AAA Index"
    assert by_label["Best performer"]["name"] == "Alpha"
    assert by_label["Worst performer"]["ticker"] == "BBB Index"
    # Opposite-extreme pairs pick opposite tickers.
    assert (
        by_label["Best risk-adjusted"]["ticker"]
        != by_label["Worst risk-adjusted"]["ticker"]
    )


def test_build_superlatives_returns_slice_is_equivalent(bdays):
    # v0.9.13: the highlights panel derives the returns frame over only the
    # trailing window (+1 row) rather than the full 5-year slice. Every
    # returns-based metric tails to ``window_days`` internally, so feeding the
    # short slice must produce byte-identical cards to feeding the full returns.
    idx = bdays(200)
    rng = np.random.default_rng(11)
    prices = pd.DataFrame(
        {
            "AAA Index": 100.0 * np.cumprod(1.0 + rng.normal(0.003, 0.01, len(idx))),
            "BBB Index": 100.0 * np.cumprod(1.0 + rng.normal(-0.002, 0.01, len(idx))),
            "CCC Index": 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.015, len(idx))),
        },
        index=idx,
    )
    meta = _meta(
        [
            {"ticker": "AAA Index", "name": "Alpha", "live_date": "2010-01-01"},
            {"ticker": "BBB Index", "name": "Beta", "live_date": "2010-01-01"},
            {"ticker": "CCC Index", "name": "Gamma", "live_date": "2010-01-01"},
        ]
    )
    full_rets = daily_returns(prices)
    for window_days in (5, 21, 63, 126):  # the four superlative-toggle windows
        short = commentary.superlative_returns(prices, window_days=window_days)
        # The slice is a genuine trailing subset, not the whole history…
        assert len(short) < len(full_rets)
        # …yet every card is byte-identical to feeding the full-history returns.
        full = commentary.build_superlatives(
            meta, prices, full_rets, window_days=window_days
        )
        sliced = commentary.build_superlatives(
            meta, prices, short, window_days=window_days
        )
        assert full == sliced, f"window_days={window_days}"


def test_build_superlatives_z_ranked_value_is_raw_metric(bdays):
    # Two asset classes: Equity sits structurally higher than Bond. The raw top
    # performer is the high-class name (EQ2, +12%), but the asset-class-demeaned
    # z-rank crowns the biggest *cohort-relative* mover (BD2, +6% vs a low Bond
    # cohort). The "Best performer" card must name BD2 while still displaying
    # BD2's raw return — proving value uses the raw metric, winner uses the z-rank.
    idx = bdays(30)

    def ramp(target: float) -> np.ndarray:
        return np.linspace(100.0, 100.0 * (1.0 + target), len(idx))

    prices = pd.DataFrame(
        {
            "EQ1 Index": ramp(0.10),
            "EQ2 Index": ramp(0.12),
            "BD1 Index": ramp(0.01),
            "BD2 Index": ramp(0.06),
        },
        index=idx,
    )
    meta = _meta(
        [
            {
                "ticker": "EQ1 Index",
                "name": "E1",
                "asset_class": "Equity",
                "live_date": "2010-01-01",
            },
            {
                "ticker": "EQ2 Index",
                "name": "E2",
                "asset_class": "Equity",
                "live_date": "2010-01-01",
            },
            {
                "ticker": "BD1 Index",
                "name": "B1",
                "asset_class": "Bond",
                "live_date": "2010-01-01",
            },
            {
                "ticker": "BD2 Index",
                "name": "B2",
                "asset_class": "Bond",
                "live_date": "2010-01-01",
            },
        ]
    )
    cards = commentary.build_superlatives(
        meta, prices, daily_returns(prices), window_days=len(idx)
    )
    best = next(c for c in cards if c["label"] == "Best performer")
    assert best["ticker"] == "BD2 Index"  # cohort-relative winner, not the raw max
    assert best["value"] == "+6.0%"  # but the displayed value is BD2's raw return


def test_build_superlatives_empty_inputs():
    assert (
        commentary.build_superlatives(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        == []
    )


def test_build_superlatives_single_ticker_renders(bdays):
    # A single-ticker universe has a degenerate cross-section (the demeaned
    # z-rank is undefined), so the z-ranked cards fall back to the raw metric
    # rather than erroring; the board still renders without a traceback.
    rng = np.random.default_rng(2)
    idx = bdays(40)
    prices = pd.DataFrame(
        {"AAA Index": 100.0 * np.cumprod(1.0 + rng.normal(0.001, 0.01, len(idx)))},
        index=idx,
    )
    meta = _meta([{"ticker": "AAA Index", "name": "Alpha", "live_date": "2010-01-01"}])
    cards = commentary.build_superlatives(meta, prices, daily_returns(prices))
    labels = {c["label"] for c in cards}
    # The lone ticker is its own extreme on every defined metric (z-ranked cards
    # fall back to the raw value).
    assert "Best performer" in labels
    assert "Best risk-adjusted" in labels
    # Dropped v0.8.0 cards are gone.
    assert "Best diversifier" not in labels
    assert "Steadiest" not in labels


def test_build_superlatives_tie_break_by_ticker(bdays):
    idx = bdays(30)
    ramp = 100.0 * 1.005 ** np.arange(len(idx))
    prices = pd.DataFrame(
        {"AAA Index": ramp.copy(), "ZZZ Index": ramp.copy()}, index=idx
    )
    meta = _meta(
        [
            {"ticker": "ZZZ Index", "name": "Zed", "live_date": "2010-01-01"},
            {"ticker": "AAA Index", "name": "Alpha", "live_date": "2010-01-01"},
        ]
    )
    cards = commentary.build_superlatives(meta, prices, daily_returns(prices))
    top = next(c for c in cards if c["label"] == "Best performer")
    # Identical paths → tie broken deterministically by sorted ticker.
    assert top["ticker"] == "AAA Index"


def test_build_superlatives_window_sensitivity(bdays):
    # An index that fell early then rallied late should be the top performer on
    # a short window but not on a long one — proving the window toggle matters.
    idx = bdays(80)
    n = len(idx)
    # REBOUND falls 100→70 then rallies to 95 (net -5% over the full window, but
    # a strong recent rally); STEADY drifts 100→106 (+6%) throughout.
    early_down_late_up = np.concatenate(
        [np.linspace(100.0, 70.0, n - 10), np.linspace(70.0, 95.0, 10)]
    )
    steady = np.linspace(100.0, 106.0, n)
    prices = pd.DataFrame(
        {"REBOUND Index": early_down_late_up, "STEADY Index": steady}, index=idx
    )
    meta = _meta(
        [
            {"ticker": "REBOUND Index", "name": "Rebound", "live_date": "2010-01-01"},
            {"ticker": "STEADY Index", "name": "Steady", "live_date": "2010-01-01"},
        ]
    )
    returns = daily_returns(prices)
    short = commentary.build_superlatives(meta, prices, returns, window_days=5)
    long = commentary.build_superlatives(meta, prices, returns, window_days=n)
    short_top = next(c for c in short if c["label"] == "Best performer")["ticker"]
    long_top = next(c for c in long if c["label"] == "Best performer")["ticker"]
    assert short_top == "REBOUND Index"  # the late rally dominates a 1W window
    assert long_top == "STEADY Index"  # the full-window drawdown sinks REBOUND


def test_build_launch_cards_metadata_and_order(bdays):
    as_of = date(2026, 6, 9)
    idx = bdays(15, start="2026-05-20")
    prices = pd.DataFrame(
        {
            "NEW1 Index": np.linspace(100.0, 105.0, len(idx)),
            "NEW2 Index": np.linspace(100.0, 98.0, len(idx)),
        },
        index=idx,
    )
    meta = _meta(
        [
            {
                "ticker": "NEW1 Index",
                "name": "New One",
                "asset_class": "Equity",
                "theme": "Trend",
                "currency": "USD",
                "live_date": (as_of - timedelta(days=10)).isoformat(),
            },
            {
                "ticker": "NEW2 Index",
                "name": "New Two",
                "asset_class": "Rates",
                "theme": "Carry",
                "currency": "EUR",
                "live_date": (as_of - timedelta(days=3)).isoformat(),
            },
            {
                "ticker": "OLD Index",
                "name": "Old",
                "asset_class": "Equity",
                "theme": "Beta",
                "currency": "USD",
                "live_date": "2015-01-01",
            },
        ]
    )
    cards = commentary.build_launch_cards(meta, prices, as_of=as_of, new_launch_days=30)
    assert [c["ticker"] for c in cards] == ["NEW2 Index", "NEW1 Index"]  # newest first
    new1 = next(c for c in cards if c["ticker"] == "NEW1 Index")
    assert new1["days_ago"] == 10
    assert new1["meta"] == "Equity · Trend · USD"
    # Anchored at the live date (first business day >= 2026-05-30, i.e.
    # 2026-06-01), not the 2026-05-20 window start: the post-launch slice runs
    # 102.857 -> 105 over the linspace, a +2.1% move.
    assert new1["since_return"] == "+2.1%"


def test_build_launch_cards_since_return_anchors_at_live_date(bdays):
    # Pre-launch (backtest / mock-fill) history must not leak into the
    # since-launch return: it is measured from the live date forward.
    as_of = date(2026, 6, 2)
    idx = bdays(10, start="2026-05-20")  # live 2026-05-28 sits at position 6
    # Flat 50 before launch, then 100 -> 110 from the live date onward.
    series = [50.0] * 6 + [100.0, 105.0, 108.0, 110.0]
    prices = pd.DataFrame({"NEW Index": series}, index=idx)
    meta = _meta(
        [
            {
                "ticker": "NEW Index",
                "name": "New",
                "asset_class": "Equity",
                "theme": "Trend",
                "currency": "USD",
                "live_date": "2026-05-28",
            }
        ]
    )
    cards = commentary.build_launch_cards(meta, prices, as_of=as_of, new_launch_days=30)
    assert len(cards) == 1
    # 110 / 100 - 1 = +10.0% (anchored at launch), NOT 110 / 50 - 1 = +120.0%.
    assert cards[0]["since_return"] == "+10.0%"


def test_build_launch_cards_empty_when_none_recent():
    meta = _meta([{"ticker": "OLD Index", "name": "Old", "live_date": "2015-01-01"}])
    cards = commentary.build_launch_cards(
        meta, pd.DataFrame(), as_of=date(2026, 6, 9), new_launch_days=30
    )
    assert cards == []
