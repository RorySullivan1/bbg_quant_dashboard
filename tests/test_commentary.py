"""Unit tests for the commentary builders.

``build_superlatives`` (whole-catalog monthly extremes), ``build_launch_cards``
(new-launch metadata) and ``build_leaderboard`` (v0.9.20, #287 — the top /
bottom rows per metric) are pure functions over small fixed frames, mirroring
the ``test_stats.py`` conventions.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from src import commentary
from src.commentary import (
    LEADERBOARD_METRICS,
    LaunchCard,
    LeaderboardColumn,
    LeaderboardRow,
    SuperlativeCard,
)
from src.config import LEADERBOARD_ROWS, TRADING_DAYS_PER_YEAR
from src.stats import (
    ann_sharpe,
    calmar_ratio,
    daily_returns,
    period_return,
    sortino_ratio,
)
from src.style import Sentiment


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

    assert {c.label for c in cards} == SUPERLATIVE_LABELS
    for c in cards:
        # The field set is the dataclass's now, so there is nothing to assert
        # about which keys are present — only that the values are right.
        assert isinstance(c, SuperlativeCard)
        assert c.description  # every card carries a hover description

    by_label = {c.label: c for c in cards}
    # No asset_class column → all tickers share one cohort, so the demeaned
    # z-rank is monotonic in the raw metric and the extremes match the raw ones.
    assert by_label["Best performer"].ticker == "AAA Index"
    assert by_label["Best performer"].name == "Alpha"
    assert by_label["Worst performer"].ticker == "BBB Index"
    # Opposite-extreme pairs pick opposite tickers.
    assert (
        by_label["Best risk-adjusted"].ticker != by_label["Worst risk-adjusted"].ticker
    )


def test_every_card_sentiment_is_a_sentiment_member(bdays):
    # #224: sentiment used to be a bare string handed to a colour lookup, so a
    # typo ("postive") fell through to neutral instead of failing. Typing the
    # field makes the card's own construction the check.
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
    assert cards
    for c in cards:
        assert isinstance(c.sentiment, Sentiment), c.label


def test_launch_cards_are_typed_with_a_real_date_and_a_numeric_return(bdays):
    # The builder returns a `date` and a `float | None`; turning those into an
    # ISO string and an em dash is the renderer's job (#224).
    prices = _superlative_prices(bdays).rename(columns={"AAA Index": "NEW1 Index"})
    as_of = prices.index.max().date()
    meta = _meta(
        [
            {
                "ticker": "NEW1 Index",
                "name": "Newbie",
                "live_date": (as_of - timedelta(days=10)).isoformat(),
            }
        ]
    )
    cards = commentary.build_launch_cards(meta, prices, as_of=as_of)
    assert len(cards) == 1
    card = cards[0]
    assert isinstance(card, LaunchCard)
    assert isinstance(card.live_date, date)
    assert isinstance(card.since_return, float)

    # No price history for the ticker → no return to show, expressed as None
    # rather than a placeholder string.
    bare = commentary.build_launch_cards(meta, pd.DataFrame(), as_of=as_of)
    assert bare[0].since_return is None


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
    best = next(c for c in cards if c.label == "Best performer")
    assert best.ticker == "BD2 Index"  # cohort-relative winner, not the raw max
    assert best.value == "+6.0%"  # but the displayed value is BD2's raw return


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
    labels = {c.label for c in cards}
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
    top = next(c for c in cards if c.label == "Best performer")
    # Identical paths → tie broken deterministically by sorted ticker.
    assert top.ticker == "AAA Index"


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
    short_top = next(c for c in short if c.label == "Best performer").ticker
    long_top = next(c for c in long if c.label == "Best performer").ticker
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
                "category": "Trend",
                "currency": "USD",
                "live_date": (as_of - timedelta(days=10)).isoformat(),
            },
            {
                "ticker": "NEW2 Index",
                "name": "New Two",
                "asset_class": "Rates",
                "category": "Carry",
                "currency": "EUR",
                "live_date": (as_of - timedelta(days=3)).isoformat(),
            },
            {
                "ticker": "OLD Index",
                "name": "Old",
                "asset_class": "Equity",
                "category": "Beta",
                "currency": "USD",
                "live_date": "2015-01-01",
            },
        ]
    )
    cards = commentary.build_launch_cards(meta, prices, as_of=as_of, new_launch_days=30)
    assert [c.ticker for c in cards] == ["NEW2 Index", "NEW1 Index"]  # newest first
    new1 = next(c for c in cards if c.ticker == "NEW1 Index")
    assert new1.days_ago == 10
    assert new1.meta == "Equity · Trend · USD"
    # Anchored at the live date (first business day >= 2026-05-30, i.e.
    # 2026-06-01), not the 2026-05-20 window start: the post-launch slice runs
    # 102.857 -> 105 over the linspace, a +2.1% move.
    assert new1.since_return == pytest.approx(0.021, abs=5e-4)


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
                "category": "Trend",
                "currency": "USD",
                "live_date": "2026-05-28",
            }
        ]
    )
    cards = commentary.build_launch_cards(meta, prices, as_of=as_of, new_launch_days=30)
    assert len(cards) == 1
    # 110 / 100 - 1 = +10.0% (anchored at launch), NOT 110 / 50 - 1 = +120.0%.
    assert cards[0].since_return == pytest.approx(0.10, abs=5e-4)


def test_build_launch_cards_empty_when_none_recent():
    meta = _meta([{"ticker": "OLD Index", "name": "Old", "live_date": "2015-01-01"}])
    cards = commentary.build_launch_cards(
        meta, pd.DataFrame(), as_of=date(2026, 6, 9), new_launch_days=30
    )
    assert cards == []


# ---- build_leaderboard (#287) ----------------------------------------------


def _leaderboard_prices(bdays, drifts: dict[str, float], n: int = 40) -> pd.DataFrame:
    """One noisy series per ticker.

    The noise is deliberately large relative to the drift: a near-monotonic
    series has no drawdown and no down days, so its Calmar and Sortino are
    NaN by construction and it would fall out of those columns.
    """
    rng = np.random.default_rng(11)
    idx = bdays(n)
    data = {
        t: 100.0 * np.cumprod(1.0 + rng.normal(d, 0.01, len(idx)))
        for t, d in drifts.items()
    }
    return pd.DataFrame(data, index=idx)


def _expected_order(metric: str, prices, returns, window_days: int) -> list[str]:
    """The metric recomputed from `src.stats`, ranked descending, ties by ticker."""
    years = window_days / TRADING_DAYS_PER_YEAR
    series = {
        "return": lambda: period_return(prices, window_days=window_days),
        "sharpe": lambda: ann_sharpe(returns, prices, years),
        "calmar": lambda: calmar_ratio(prices, years),
        "sortino": lambda: sortino_ratio(returns, prices, years),
    }[metric]()
    ranked = series.dropna().sort_index().sort_values(ascending=False, kind="stable")
    return list(ranked.index)


def _leaderboard_meta(tickers) -> pd.DataFrame:
    return _meta(
        [
            {"ticker": t, "name": f"Name {t.split()[0]}", "live_date": "2010-01-01"}
            for t in tickers
        ]
    )


SIX_DRIFTS = {
    "AAA Index": 0.006,
    "BBB Index": 0.004,
    "CCC Index": 0.002,
    "DDD Index": -0.002,
    "EEE Index": -0.004,
    "FFF Index": -0.006,
}


def _build(bdays, drifts=SIX_DRIFTS, **kw):
    prices = _leaderboard_prices(bdays, drifts)
    returns = daily_returns(prices)
    return commentary.build_leaderboard(
        _leaderboard_meta(drifts), prices, returns, window_days=21, **kw
    )


def test_leaderboard_columns_in_declared_order_with_bounded_rows(bdays):
    columns = _build(bdays)

    assert [(c.metric, c.label) for c in columns] == list(LEADERBOARD_METRICS)
    for col in columns:
        assert isinstance(col, LeaderboardColumn)
        assert len(col.top) <= LEADERBOARD_ROWS
        assert len(col.bottom) <= LEADERBOARD_ROWS
        assert all(isinstance(r, LeaderboardRow) for r in col.top + col.bottom)


def test_leaderboard_rank_agrees_with_the_displayed_value(bdays):
    """Rank 1 is the largest raw value, the last bottom row the smallest, and
    the ranks are true catalog positions — six tickers, so the bottom block is
    ranks 4-6. The order is checked against the metric recomputed from
    `src.stats`, so the board cannot drift from the numbers it shows."""
    prices = _leaderboard_prices(bdays, SIX_DRIFTS)
    returns = daily_returns(prices)
    columns = commentary.build_leaderboard(
        _leaderboard_meta(SIX_DRIFTS), prices, returns, window_days=21
    )
    for col in columns:
        rows = col.top + col.bottom
        values = [r.value for r in rows]
        assert values == sorted(values, reverse=True)
        assert [r.rank for r in col.top] == [1, 2, 3]
        assert [r.rank for r in col.bottom] == [4, 5, 6]
        assert len({r.ticker for r in rows}) == 6  # no overlap
        assert [r.ticker for r in rows] == _expected_order(
            col.metric, prices, returns, 21
        )
        assert all(r.name == f"Name {r.ticker.split()[0]}" for r in rows)


def test_leaderboard_excludes_nan_and_ties_by_ticker(bdays):
    prices = _leaderboard_prices(bdays, SIX_DRIFTS)
    # BBB duplicates AAA exactly → an equal value on every metric; the tie
    # resolves alphabetically. ZZZ has no data in the window → excluded.
    prices["BBB Index"] = prices["AAA Index"]
    prices["ZZZ Index"] = np.nan
    returns = daily_returns(prices)
    meta = _leaderboard_meta(prices.columns)
    columns = commentary.build_leaderboard(meta, prices, returns, window_days=21)

    for col in columns:
        rows = col.top + col.bottom
        tickers = [r.ticker for r in rows]
        assert "ZZZ Index" not in tickers
        assert len(tickers) == 6  # the six with data all rank
        # Equal values → adjacent rows, AAA first.
        a, b = tickers.index("AAA Index"), tickers.index("BBB Index")
        assert b == a + 1
        assert rows[a].value == rows[b].value


def test_leaderboard_small_catalog_never_repeats_a_row(bdays):
    four = {t: d for t, d in list(SIX_DRIFTS.items())[:4]}
    for col in _build(bdays, drifts=four):
        assert [r.rank for r in col.top] == [1, 2, 3]
        assert [r.rank for r in col.bottom] == [4]
        assert len({r.ticker for r in col.top + col.bottom}) == 4

    two = {t: d for t, d in list(SIX_DRIFTS.items())[:2]}
    for col in _build(bdays, drifts=two):
        assert [r.rank for r in col.top] == [1, 2]
        assert col.bottom == ()


def test_leaderboard_text_format_and_sentiment_follow_the_metric(bdays):
    by_metric = {c.metric: c for c in _build(bdays)}

    ret = by_metric["return"]
    assert ret.top[0].text.endswith("%") and ret.top[0].text.startswith("+")
    assert ret.top[0].sentiment is Sentiment.POSITIVE
    assert ret.bottom[-1].text.startswith("-")
    assert ret.bottom[-1].sentiment is Sentiment.NEGATIVE

    for metric in ("sharpe", "calmar", "sortino"):
        col = by_metric[metric]
        for r in col.top + col.bottom:
            assert r.text == f"{r.value:.2f}"
            expected = (
                Sentiment.POSITIVE
                if r.value > 0
                else Sentiment.NEGATIVE if r.value < 0 else Sentiment.NEUTRAL
            )
            assert r.sentiment is expected


def test_leaderboard_uses_the_window_it_is_given(bdays):
    """A drift that flips sign inside the 40-day history reorders the board
    between a short and a long window."""
    rng = np.random.default_rng(3)
    idx = bdays(40)
    n = len(idx)
    # AAA: strong early, weak late. BBB: the mirror.
    a = np.concatenate([rng.normal(0.008, 0.001, n - 5), rng.normal(-0.008, 0.001, 5)])
    b = np.concatenate([rng.normal(-0.008, 0.001, n - 5), rng.normal(0.008, 0.001, 5)])
    prices = pd.DataFrame(
        {"AAA Index": 100 * np.cumprod(1 + a), "BBB Index": 100 * np.cumprod(1 + b)},
        index=idx,
    )
    returns = daily_returns(prices)
    meta = _leaderboard_meta(prices.columns)

    short = commentary.build_leaderboard(meta, prices, returns, window_days=5)
    long = commentary.build_leaderboard(meta, prices, returns, window_days=30)
    assert short[0].top[0].ticker == "BBB Index"
    assert long[0].top[0].ticker == "AAA Index"


def test_leaderboard_empty_inputs():
    empty = pd.DataFrame()
    assert commentary.build_leaderboard(pd.DataFrame(), empty, empty) == ()


def test_leaderboard_rows_default_from_config(bdays):
    columns = _build(bdays)
    assert all(len(c.top) == LEADERBOARD_ROWS for c in columns)
    columns = _build(bdays, rows=2)
    assert all([r.rank for r in c.top] == [1, 2] for c in columns)
    assert all([r.rank for r in c.bottom] == [5, 6] for c in columns)
