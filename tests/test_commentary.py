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
    "Top performer",
    "Weakest performer",
    "Strongest trend",
    "Longest bull run",
    "Biggest turnaround",
    "Most extended",
    "Best risk-adjusted",
    "Best Sortino",
    "Highest Calmar",
    "Strongest momentum",
    "Steadiest",
    "Most resilient",
    "Lowest tail risk",
    "Best diversifier",
    "Most volatile",
    "Hardest hit",
    "Longest losing streak",
    "Most oversold",
    "Most below trend",
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
    assert by_label["Top performer"]["ticker"] == "AAA Index"
    assert by_label["Top performer"]["name"] == "Alpha"
    assert by_label["Weakest performer"]["ticker"] == "BBB Index"
    # Opposite-extreme pairs pick opposite tickers.
    assert by_label["Most volatile"]["ticker"] != by_label["Steadiest"]["ticker"]


def test_build_superlatives_empty_inputs():
    assert (
        commentary.build_superlatives(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        == []
    )


def test_build_superlatives_skips_undefined_metric(bdays):
    # A single-ticker universe has no pairwise correlation, so "Best
    # diversifier" must be skipped rather than erroring; the per-ticker
    # cards still render.
    rng = np.random.default_rng(2)
    idx = bdays(40)
    prices = pd.DataFrame(
        {"AAA Index": 100.0 * np.cumprod(1.0 + rng.normal(0.001, 0.01, len(idx)))},
        index=idx,
    )
    meta = _meta([{"ticker": "AAA Index", "name": "Alpha", "live_date": "2010-01-01"}])
    cards = commentary.build_superlatives(meta, prices, daily_returns(prices))
    labels = {c["label"] for c in cards}
    assert "Best diversifier" not in labels  # needs >= 2 tickers
    assert "Top performer" in labels  # well-defined → present


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
    top = next(c for c in cards if c["label"] == "Top performer")
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
    short_top = next(c for c in short if c["label"] == "Top performer")["ticker"]
    long_top = next(c for c in long if c["label"] == "Top performer")["ticker"]
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
    assert new1["since_return"] == "+5.0%"


def test_build_launch_cards_empty_when_none_recent():
    meta = _meta([{"ticker": "OLD Index", "name": "Old", "live_date": "2015-01-01"}])
    cards = commentary.build_launch_cards(
        meta, pd.DataFrame(), as_of=date(2026, 6, 9), new_launch_days=30
    )
    assert cards == []
