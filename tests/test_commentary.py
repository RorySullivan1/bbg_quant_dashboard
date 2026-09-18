"""Unit tests for the commentary builders.

``build_leaderboard`` (v0.9.20 #287 — the top / bottom rows per metric) and
``build_launch_cards`` (new-launch metadata) are pure functions over small
fixed frames, mirroring the ``test_stats.py`` conventions.

The ``build_superlatives`` cases were removed with the board in #291. Every
metric they exercised still has its own unit test in ``test_stats.py``; what
went was the card builder, not the maths.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from src import commentary
from src.commentary import (
    LaunchCard,
    LeaderboardColumn,
    LeaderboardRow,
)
from src.config import (
    LEADERBOARD_ROWS,
    RANKABLE_METRICS,
    SCORE_SAMPLE_DAYS,
    TRADING_DAYS_PER_YEAR,
)
from src.stats import (
    ann_sharpe,
    calmar_ratio,
    daily_returns,
    period_return,
    rolling_metric_zscore,
    sortino_ratio,
)
from src.style import Sentiment


def _meta(rows: list[dict]) -> pd.DataFrame:
    """Metadata frame with the columns the builders read."""
    frame = pd.DataFrame(rows)
    frame["live_date"] = pd.to_datetime(frame["live_date"])
    return frame


def test_launch_cards_are_typed_with_a_real_date_and_a_numeric_return(bdays):
    # The builder returns a `date` and a `float | None`; turning those into an
    # ISO string and an em dash is the renderer's job (#224).
    prices = _leaderboard_prices(bdays, THREE_DRIFTS).rename(
        columns={"AAA Index": "NEW1 Index"}
    )
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
    """The board's order, recomputed from `src.stats`.

    It is the **score** — the metric z-scored against its own rolling history —
    that decides the order since #310, not the raw value the row displays. The
    raw metric is still recomputed by `_expected_values` below, for the numbers
    themselves.
    """
    scores = rolling_metric_zscore(
        prices,
        metric=metric,
        window=window_days,
        zscore_window=SCORE_SAMPLE_DAYS,
        returns=returns,
    )
    ranked = scores.dropna().sort_index().sort_values(ascending=False, kind="stable")
    return list(ranked.index)


def _expected_values(metric: str, prices, returns, window_days: int):
    """The raw metric recomputed from `src.stats` — what a row displays."""
    years = window_days / TRADING_DAYS_PER_YEAR
    return {
        "return": lambda: period_return(prices, window_days=window_days),
        "sharpe": lambda: ann_sharpe(returns, prices, years),
        "calmar": lambda: calmar_ratio(prices, years),
        "sortino": lambda: sortino_ratio(returns, prices, years),
    }[metric]()


def _leaderboard_meta(tickers) -> pd.DataFrame:
    return _meta(
        [
            {"ticker": t, "name": f"Name {t.split()[0]}", "live_date": "2010-01-01"}
            for t in tickers
        ]
    )


#: A small drift set for the launch-card cases, which need three series
#: rather than a full board.
THREE_DRIFTS = {"AAA Index": 0.004, "BBB Index": -0.004, "CCC Index": 0.0}

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

    assert [(c.metric, c.label) for c in columns] == list(RANKABLE_METRICS)
    for col in columns:
        assert isinstance(col, LeaderboardColumn)
        assert len(col.top) <= LEADERBOARD_ROWS
        assert len(col.bottom) <= LEADERBOARD_ROWS
        assert all(isinstance(r, LeaderboardRow) for r in col.top + col.bottom)


def test_leaderboard_rank_agrees_with_the_score_it_leads_with(bdays):
    """Rank 1 is the highest **score**, the last bottom row the lowest.

    #310 moved ranking off the raw value, so the invariant #286 protected —
    rank and the number beside it agreeing — now holds against the score, which
    is the number the row leads with. Both are checked against `src.stats`
    recomputed independently, so the board cannot drift from either.

    The ranks are true catalog positions: six tickers, so the bottom block is
    ranks 4-6.
    """
    prices = _leaderboard_prices(bdays, SIX_DRIFTS)
    returns = daily_returns(prices)
    columns = commentary.build_leaderboard(
        _leaderboard_meta(SIX_DRIFTS), prices, returns, window_days=21
    )
    for col in columns:
        rows = col.top + col.bottom
        scores = [r.score for r in rows]
        assert scores == sorted(scores, reverse=True)
        assert [r.rank for r in col.top] == [1, 2, 3]
        assert [r.rank for r in col.bottom] == [4, 5, 6]
        assert len({r.ticker for r in rows}) == 6  # no overlap
        assert [r.ticker for r in rows] == _expected_order(
            col.metric, prices, returns, 21
        )
        # The value each row carries is still that row's raw metric, unchanged
        # by the score deciding where the row sits.
        expected = _expected_values(col.metric, prices, returns, 21)
        for r in rows:
            assert r.value == pytest.approx(float(expected.loc[r.ticker]))
            assert r.score_text == f"{r.score:+.2f}"
        assert all(r.name == f"Name {r.ticker.split()[0]}" for r in rows)


def test_ranking_by_score_is_not_ranking_by_value(bdays):
    """The test that would fail if the score were cosmetic.

    A catalog where the biggest raw number is not the most unusual one: the
    board must lead with the latter. Without this, a `score` that were merely
    stored and ignored would pass every other assertion here.
    """
    prices = _leaderboard_prices(bdays, SIX_DRIFTS)
    returns = daily_returns(prices)
    columns = commentary.build_leaderboard(
        _leaderboard_meta(SIX_DRIFTS), prices, returns, window_days=21
    )

    differs = []
    for col in columns:
        rows = col.top + col.bottom
        by_value = [r.ticker for r in sorted(rows, key=lambda r: -r.value)]
        differs.append([r.ticker for r in rows] != by_value)
    assert any(differs), "fixture no longer separates score order from value order"


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
            # Sentiment follows the **score** since #310 — it is what the row
            # is ranked and read by, so a row can show a negative raw Sharpe in
            # green when that reading is unusually good for that index.
            expected = (
                Sentiment.POSITIVE
                if r.score > 0
                else Sentiment.NEGATIVE if r.score < 0 else Sentiment.NEUTRAL
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

    # The window reaches both halves of a row. The raw return still flips its
    # leader as it always did — BBB over the last five days, AAA over thirty —
    # and the score moves with it.
    def leader_by_value(columns):
        rows = columns[0].top + columns[0].bottom
        return max(rows, key=lambda r: r.value).ticker

    assert leader_by_value(short) == "BBB Index"
    assert leader_by_value(long) == "AAA Index"
    assert short[0].top[0].score != long[0].top[0].score

    # Not the row order, though: 40 days is far too short a sample for the
    # score to separate two indices, and the board says so by leaving them in
    # the same order rather than inventing a distinction.


def test_leaderboard_empty_inputs():
    empty = pd.DataFrame()
    assert commentary.build_leaderboard(pd.DataFrame(), empty, empty) == ()


def test_leaderboard_rows_default_from_config(bdays):
    columns = _build(bdays)
    assert all(len(c.top) == LEADERBOARD_ROWS for c in columns)
    columns = _build(bdays, rows=2)
    assert all([r.rank for r in c.top] == [1, 2] for c in columns)
    assert all([r.rank for r in c.bottom] == [5, 6] for c in columns)


def test_the_window_returns_tail_gives_the_same_board_as_full_history(bdays):
    """``window_returns`` hands `build_leaderboard` a trailing slice instead of
    the whole 5-year returns frame. That is only safe if the board it produces
    is identical, which is what this pins — the optimisation is invisible or it
    is a bug. (Carried over from the superlatives' version of this test in
    v0.9.13; #291 re-pointed it at the builder that inherited the tail.)"""
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
    meta = _leaderboard_meta(prices.columns)
    full_rets = daily_returns(prices)

    for window_days in (5, 21, 63, 126):  # the four ranking-window options
        short = commentary.window_returns(prices, window_days=window_days)
        # A genuine trailing subset, not the whole history…
        assert len(short) < len(full_rets)
        # …yet the board is identical either way.
        full = commentary.build_leaderboard(
            meta, prices, full_rets, window_days=window_days
        )
        sliced = commentary.build_leaderboard(
            meta, prices, short, window_days=window_days
        )
        assert full == sliced, f"window_days={window_days}"


def test_a_longer_frame_does_not_move_the_raw_values(bdays):
    """The board takes the whole fetched book since #310, for the score's sake.

    The raw values must not notice: every one of them slices internally —
    `period_return` tails by count, the ratios go through `_slice_last_years` —
    so handing `build_leaderboard` a year more history can only change what the
    score is standardized against, never what a row displays.
    """
    idx = bdays(1512)
    rng = np.random.default_rng(7)
    tickers = [f"T{i} Index" for i in range(6)]
    full = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0004, 0.01, (len(idx), 6)), axis=0),
        index=idx,
        columns=tickers,
    )
    shorter = full.tail(1260)
    meta = _leaderboard_meta(tickers)

    for window_days in (5, 21, 63, 126, 252):
        long_board = commentary.build_leaderboard(
            meta, full, daily_returns(full), window_days=window_days
        )
        short_board = commentary.build_leaderboard(
            meta, shorter, daily_returns(shorter), window_days=window_days
        )
        for long_col, short_col in zip(long_board, short_board, strict=True):
            long_values = {r.ticker: r.value for r in long_col.top + long_col.bottom}
            short_values = {r.ticker: r.value for r in short_col.top + short_col.bottom}
            shared = set(long_values) & set(short_values)
            assert shared, f"no overlap at {window_days}d on {long_col.metric}"
            for ticker in shared:
                assert long_values[ticker] == pytest.approx(short_values[ticker])


def test_an_index_without_both_numbers_does_not_reach_the_board(bdays):
    # A row needs a score and a value: a flat index has no drawdown (NaN Calmar)
    # and no variance to standardize against, so it drops out rather than
    # rendering half a row.
    idx = bdays(400)
    rng = np.random.default_rng(2)
    prices = pd.DataFrame(
        {
            "AAA Index": 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(idx))),
            "BBB Index": 100 * np.cumprod(1 + rng.normal(0.0002, 0.01, len(idx))),
            "FLAT Index": np.full(len(idx), 100.0),
        },
        index=idx,
    )
    meta = _leaderboard_meta(prices.columns)

    columns = commentary.build_leaderboard(
        meta, prices, daily_returns(prices), window_days=21
    )

    for col in columns:
        tickers = [r.ticker for r in col.top + col.bottom]
        assert "FLAT Index" not in tickers
        assert all(np.isfinite(r.score) and np.isfinite(r.value) for r in col.top)
