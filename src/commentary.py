"""All-catalog commentary: the leaderboard, the Market Superlatives and the
New Launches cards.

Computes the Key Highlights sections from the already-fetched price frame and
the catalog metadata — no BQL call of its own. The leaderboard ranks the whole
catalog over a trailing window on four metrics (return, Sharpe, Calmar,
Sortino) and keeps the top and bottom few of each; superlatives pick the single
most extreme index per indicator over the same kind of window (best/worst
return, highest Sharpe, longest streaks, largest MACD extension, …); launch
cards pick out indices that went live within `NEW_LAUNCH_DAYS`.

Each superlative is declared as a spec — a metric function plus a label,
formatter, sentiment, and description — so adding one means adding a spec
rather than a branch. Both builders return frozen dataclasses
(`SuperlativeCard` / `LaunchCard`), so the field set lives here and the
renderers in `layout/html.py` read attributes rather than guessing at dict keys
with `.get()` defaults. Values that are *presentation* — the launch date's
format, the em dash for a return that cannot be computed — are left to those
renderers; this module returns a `date` and a `float | None`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import (
    LAUNCH_CARD_META_FIELDS,
    LEADERBOARD_ROWS,
    NEW_LAUNCH_DAYS,
    SUPERLATIVE_WINDOW_DAYS,
    TRADING_DAYS_PER_YEAR,
)
from .stats import (
    ann_sharpe,
    asset_class_demeaned_zscore,
    calmar_ratio,
    daily_returns,
    longest_down_streak,
    longest_up_streak,
    macd_histogram,
    max_drawdown,
    max_drawup,
    period_return,
    return_autocorr,
    return_skew,
    sortino_ratio,
    win_rate,
)
from .style import Sentiment


@dataclass(frozen=True)
class SuperlativeCard:
    """One Market Superlative: the single most extreme index for a metric.

    `value` is the **already-formatted** raw metric (the formatter differs per
    card — percent, 2dp, signed), while `description` states only how the metric
    is calculated and becomes the card's hover tooltip.
    """

    label: str
    value: str
    name: str
    ticker: str
    sentiment: Sentiment
    description: str = ""


@dataclass(frozen=True)
class LaunchCard:
    """One New Launch: an index that went live within `NEW_LAUNCH_DAYS`.

    `since_return` is the simple cumulative return since `live_date`, or None
    when the window holds too little history to compute one — the renderer
    decides what that looks like on screen.
    """

    name: str
    ticker: str
    meta: str
    live_date: date
    days_ago: int
    since_return: float | None


@dataclass(frozen=True)
class LeaderboardRow:
    """One ranked index in a leaderboard column.

    `rank` is the index's true 1-based position across the whole catalog for
    that metric, so a bottom row reads e.g. "52" of 54 rather than "3rd from
    last". `value` is the raw metric; `text` is its formatted form (percent for
    the window return, two decimals for the ratios), because the formatter
    differs per column and the widget should not re-derive it.
    """

    rank: int
    ticker: str
    name: str
    value: float
    text: str
    sentiment: Sentiment


@dataclass(frozen=True)
class LeaderboardColumn:
    """One metric's ranking: the top rows and the bottom rows of the catalog.

    Both tuples run in rank order (rank 1 first; the catalog's last index
    last). They never share a ticker — a small catalog yields a short `bottom`
    rather than a repeated row.
    """

    metric: str
    label: str
    top: tuple[LeaderboardRow, ...]
    bottom: tuple[LeaderboardRow, ...]


#: The leaderboard's columns in display order, as (metric key, display label).
#: Declared once, here, so the widget titles its columns from the data it is
#: handed rather than respelling the labels.
LEADERBOARD_METRICS: tuple[tuple[str, str], ...] = (
    ("return", "Return"),
    ("sharpe", "Sharpe"),
    ("calmar", "Calmar"),
    ("sortino", "Sortino"),
)


def _sign_sentiment(value: float) -> Sentiment:
    if value > 0:
        return Sentiment.POSITIVE
    if value < 0:
        return Sentiment.NEGATIVE
    return Sentiment.NEUTRAL


def _rank_column(
    metric: str,
    label: str,
    series: pd.Series,
    *,
    fmt: Callable[[float], str],
    name_of: Callable[[str], str],
    rows: int,
) -> LeaderboardColumn:
    """Rank `series` descending and keep its first and last `rows` entries.

    The rank is by the **raw** value — the number the row displays — so rank 1
    always carries the largest figure. NaN and infinite values (a ratio whose
    denominator degenerated) are excluded before ranking, and ties resolve by
    ticker so the board is deterministic run to run.
    """
    s = series.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    # Sort by ticker first, then a stable sort by value, so equal values keep
    # ticker order — the tie-break — without a second sort key.
    ranked = s.sort_index().sort_values(ascending=False, kind="stable")

    def row(position: int) -> LeaderboardRow:
        ticker = str(ranked.index[position])
        value = float(ranked.iloc[position])
        return LeaderboardRow(
            rank=position + 1,
            ticker=ticker,
            name=name_of(ticker),
            value=value,
            text=fmt(value),
            sentiment=_sign_sentiment(value),
        )

    n = len(ranked)
    top = tuple(row(i) for i in range(min(rows, n)))
    # The bottom block starts after the top block even when the catalog is too
    # small for both, so no ticker appears twice.
    bottom = tuple(row(i) for i in range(max(rows, n - rows), n))
    return LeaderboardColumn(metric=metric, label=label, top=top, bottom=bottom)


def build_leaderboard(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    window_days: int = SUPERLATIVE_WINDOW_DAYS,
    rows: int = LEADERBOARD_ROWS,
) -> tuple[LeaderboardColumn, ...]:
    """Whole-catalog top / bottom `rows` on return, Sharpe, Calmar and Sortino.

    Every column is scoped to the trailing ``window_days``: the return is the
    simple window return (``period_return``, not annualized), and the three
    ratios take ``years = window_days / TRADING_DAYS_PER_YEAR`` — the same
    scoping the superlatives' Sharpe card uses, so the board and the cards
    agree on what "past month" means. ``returns`` is expected to be the
    ``superlative_returns`` tail of ``prices``. Computed from the fetched
    frames only, no BQL. An empty catalog yields an empty tuple; a metric that
    is NaN for every index yields a column with no rows.
    """
    if prices.empty or returns.empty:
        return ()

    name_lookup = meta.set_index("ticker")["name"].to_dict() if not meta.empty else {}

    def name_of(ticker: str) -> str:
        return name_lookup.get(ticker, ticker)

    def pct(v: float) -> str:
        return f"{v:+.1%}"

    def num2(v: float) -> str:
        return f"{v:.2f}"

    years = window_days / TRADING_DAYS_PER_YEAR
    series_by_metric: dict[str, tuple[pd.Series, Callable[[float], str]]] = {
        "return": (period_return(prices, window_days=window_days), pct),
        "sharpe": (ann_sharpe(returns, prices, years), num2),
        "calmar": (calmar_ratio(prices, years), num2),
        "sortino": (sortino_ratio(returns, prices, years), num2),
    }
    return tuple(
        _rank_column(
            metric,
            label,
            series_by_metric[metric][0],
            fmt=series_by_metric[metric][1],
            name_of=name_of,
            rows=rows,
        )
        for metric, label in LEADERBOARD_METRICS
    )


@dataclass
class _SuperlativeBoard:
    """Accumulates the cards, owning the lookups every pick shares.

    That shared context — the ticker→name lookup and the asset-class series
    behind the cross-asset-neutral z-rank — used to be captured by a nested
    closure, reachable only from inside `build_superlatives`.
    """

    name_lookup: dict[str, str]
    asset_class: pd.Series
    cards: list[SuperlativeCard] = field(default_factory=list)

    def name_of(self, ticker: str) -> str:
        return self.name_lookup.get(ticker, ticker)

    def acz(self, metric: pd.Series) -> pd.Series:
        """The metric's asset-class-demeaned z-score, for cross-asset-neutral ranking."""
        return asset_class_demeaned_zscore(metric, self.asset_class)

    def pick(
        self,
        label: str,
        series: pd.Series,
        *,
        mode: str,
        fmt: Callable[[float], str],
        sentiment: Sentiment,
        description: str = "",
        rank_by: pd.Series | None = None,
    ) -> None:
        """Add the card for `series`' most extreme index, or nothing if it is all-NaN."""
        s = series.dropna()
        if s.empty:
            return
        s = s.sort_index()  # deterministic tie-break by ticker
        ranking = s
        if rank_by is not None:
            r = rank_by.reindex(s.index).dropna()
            if not r.empty:  # fall back to the raw metric if the z-rank is degenerate
                ranking = r.sort_index()
        ticker = ranking.idxmax() if mode == "max" else ranking.idxmin()
        self.cards.append(
            SuperlativeCard(
                label=label,
                value=fmt(s[ticker]),  # always the raw metric value
                name=self.name_of(ticker),
                ticker=ticker,
                sentiment=sentiment,
                description=description,
            )
        )


def superlative_returns(
    prices: pd.DataFrame, *, window_days: int = SUPERLATIVE_WINDOW_DAYS
) -> pd.DataFrame:
    """Daily returns over just the trailing span ``build_superlatives`` needs.

    Every returns-based superlative tails to ``window_days``, and the deepest
    reach is the Sharpe card's ``ann_volatility``, which slices returns to its
    ~``window_days``-trading-day date window. Deriving returns from the full
    multi-year price history is therefore wasted work. This returns
    ``daily_returns`` over a price tail that is a strict superset of every
    returns-based metric's window — including one extra leading row so the
    oldest kept return is computed against its true prior price — so feeding it
    to ``build_superlatives`` yields identical cards to feeding the full-history
    returns, without the whole-history ``pct_change``.
    """
    if prices.empty:
        return prices
    end = prices.index.max()
    reach_days = int(window_days / TRADING_DAYS_PER_YEAR * 365.25)
    n_reach = int((prices.index >= end - timedelta(days=reach_days)).sum())
    # +1 price row so the oldest kept return has its true prior; and at least
    # window_days + 1 rows for the count-based (``.tail(window_days)``) metrics.
    n_slice = max(n_reach + 1, window_days + 1)
    return daily_returns(prices.tail(n_slice))


def build_superlatives(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    window_days: int = SUPERLATIVE_WINDOW_DAYS,
) -> list[SuperlativeCard]:
    """Whole-catalog "Market Superlatives" over the trailing window.

    A board of **symmetric best/worst** pairs plus a single (Lowest VaR), built
    from technical / character-based indicators (persistence, momentum,
    win-rate, skew) and computed over the trailing ``window_days`` from the
    already-fetched prices/returns (no BQL). Each card names the single most
    extreme index across the catalog.

    Scale-dependent metrics (performer, MACD, drawup/drawdown, Sharpe, VaR) are
    ranked **cross-asset-neutrally** by the metric's *asset-class-demeaned*
    z-score, so an index wins for being extreme relative to its asset-class
    cohort rather than because its whole class is structurally loud — while the
    card still displays the **raw** metric value. RSI and MACD are fixed-lookback
    oscillators (14d / 12-26-9) evaluated at the window end, intentionally
    independent of ``window_days``; the rest re-scope on it. Names with
    insufficient history surface as NaN and are skipped (so short windows simply
    drop a few cards); ties break deterministically by ticker. See
    `SuperlativeCard` for the card's fields.
    """
    if prices.empty or returns.empty:
        return []

    # Per-ticker asset class for the cross-asset-neutral z-ranking. Tickers with
    # no mapped class share one cohort so the demeaned z-rank stays defined.
    if "asset_class" in meta.columns:
        asset_class = meta.set_index("ticker")["asset_class"]
    else:
        asset_class = pd.Series(dtype=object)
    board = _SuperlativeBoard(
        name_lookup=meta.set_index("ticker")["name"].to_dict(),
        asset_class=asset_class.reindex(prices.columns).fillna("Unclassified"),
    )

    years = window_days / TRADING_DAYS_PER_YEAR

    # Window-scoped per-ticker metric series.
    pr = period_return(prices, window_days=window_days)
    autocorr = return_autocorr(returns, window_days=window_days)
    up_streak = longest_up_streak(returns, window_days=window_days)
    down_streak = longest_down_streak(returns, window_days=window_days)
    drawup = max_drawup(prices, years)
    mdd = max_drawdown(prices, years)
    sharpe = ann_sharpe(returns, prices, years)
    wr = win_rate(returns, window_days=window_days)
    skew = return_skew(returns, window_days=window_days)
    # Fixed-lookback oscillator (window-toggle-independent).
    macd = macd_histogram(prices)

    def pct(v: float) -> str:
        return f"{v:+.1%}"

    def num2(v: float) -> str:
        return f"{v:.2f}"

    def signed2(v: float) -> str:
        return f"{v:+.2f}"

    # --- performance (asset-class-demeaned z-rank) ---
    perf_desc = (
        "Window price return (last ÷ first − 1); ranked across the catalog by "
        "its asset-class-demeaned z-score."
    )
    board.pick(
        "Best performer",
        pr,
        mode="max",
        fmt=pct,
        sentiment=Sentiment.POSITIVE,
        description=perf_desc,
        rank_by=board.acz(pr),
    )
    board.pick(
        "Worst performer",
        pr,
        mode="min",
        fmt=pct,
        sentiment=Sentiment.NEGATIVE,
        description=perf_desc,
        rank_by=board.acz(pr),
    )
    # --- trend persistence (raw) ---
    autocorr_desc = "Lag-1 Pearson autocorrelation of daily returns over the window."
    board.pick(
        "Most trending",
        autocorr,
        mode="max",
        fmt=signed2,
        sentiment=Sentiment.NEUTRAL,
        description=autocorr_desc,
    )
    board.pick(
        "Most mean-reverting",
        autocorr,
        mode="min",
        fmt=signed2,
        sentiment=Sentiment.NEUTRAL,
        description=autocorr_desc,
    )
    # --- run duration (raw) ---
    board.pick(
        "Longest bull run",
        up_streak,
        mode="max",
        fmt=lambda v: f"{int(v)}d",
        sentiment=Sentiment.POSITIVE,
        description="Most consecutive up days (positive daily returns) in the window.",
    )
    board.pick(
        "Longest bear run",
        down_streak,
        mode="max",
        fmt=lambda v: f"{int(v)}d",
        sentiment=Sentiment.NEGATIVE,
        description="Most consecutive down days (negative daily returns) in the window.",
    )
    # --- MACD extension (asset-class-demeaned z-rank, fixed 12/26/9 lookback) ---
    macd_desc = (
        "MACD histogram (12/26/9 EMAs) divided by the last price; ranked across "
        "the catalog by its asset-class-demeaned z-score."
    )
    board.pick(
        "Most extended up",
        macd,
        mode="max",
        fmt=lambda v: f"{v:+.2%}",
        sentiment=Sentiment.POSITIVE,
        description=macd_desc,
        rank_by=board.acz(macd),
    )
    board.pick(
        "Most extended down",
        macd,
        mode="min",
        fmt=lambda v: f"{v:+.2%}",
        sentiment=Sentiment.NEGATIVE,
        description=macd_desc,
        rank_by=board.acz(macd),
    )
    # --- drawup / drawdown (asset-class-demeaned z-rank) ---
    board.pick(
        "Largest drawup",
        drawup,
        mode="max",
        fmt=pct,
        sentiment=Sentiment.POSITIVE,
        description="Largest run-up from a running low in the window (price ÷ "
        "running-min − 1); ranked by asset-class-demeaned z-score.",
        rank_by=board.acz(drawup),
    )
    board.pick(
        "Deepest drawdown",
        mdd,
        mode="min",
        fmt=pct,
        sentiment=Sentiment.NEGATIVE,
        description="Deepest peak-to-trough drawdown in the window (price ÷ "
        "running-max − 1); ranked by asset-class-demeaned z-score.",
        rank_by=board.acz(mdd),
    )
    # --- risk-adjusted (asset-class-demeaned z-rank) ---
    sharpe_desc = (
        "Annualized Sharpe ratio over the window (return ÷ volatility, "
        "risk-free 0); ranked by asset-class-demeaned z-score."
    )
    board.pick(
        "Best risk-adjusted",
        sharpe,
        mode="max",
        fmt=num2,
        sentiment=Sentiment.POSITIVE,
        description=sharpe_desc,
        rank_by=board.acz(sharpe),
    )
    board.pick(
        "Worst risk-adjusted",
        sharpe,
        mode="min",
        fmt=num2,
        sentiment=Sentiment.NEGATIVE,
        description=sharpe_desc,
        rank_by=board.acz(sharpe),
    )
    # --- win rate (raw) ---
    winrate_desc = "Share of days with a positive daily return over the window."
    board.pick(
        "Highest win rate",
        wr,
        mode="max",
        fmt=lambda v: f"{v:.0%}",
        sentiment=Sentiment.POSITIVE,
        description=winrate_desc,
    )
    board.pick(
        "Lowest win rate",
        wr,
        mode="min",
        fmt=lambda v: f"{v:.0%}",
        sentiment=Sentiment.NEGATIVE,
        description=winrate_desc,
    )
    # --- skewness (raw) ---
    skew_desc = "Skewness of daily returns over the window."
    board.pick(
        "Most positive skew",
        skew,
        mode="max",
        fmt=signed2,
        sentiment=Sentiment.POSITIVE,
        description=skew_desc,
    )
    board.pick(
        "Most negative skew",
        skew,
        mode="min",
        fmt=signed2,
        sentiment=Sentiment.NEGATIVE,
        description=skew_desc,
    )
    return board.cards


def build_launch_cards(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of: date | None = None,
    new_launch_days: int = NEW_LAUNCH_DAYS,
) -> list[LaunchCard]:
    """New-launch cards (newest-first) with metadata for the right panel.

    ``meta`` joins `LAUNCH_CARD_META_FIELDS` with " · "; ``since_return`` is the
    simple cumulative return since the index's live date (not annualized — a
    3-week-old index annualizes to nonsense, and anchoring at the first fetched
    observation would fold in any pre-launch backtest history), or None when the
    fetched window holds too little history to compute one. Returns an empty
    list when no launches fall within ``new_launch_days``.
    """
    as_of = as_of or date.today()
    if meta.empty:
        return []
    cutoff = pd.Timestamp(as_of) - timedelta(days=new_launch_days)
    recent = meta[meta["live_date"] >= cutoff].sort_values("live_date", ascending=False)
    if recent.empty:
        return []

    cards: list[LaunchCard] = []
    for _, row in recent.iterrows():
        ticker = row["ticker"]
        live = pd.Timestamp(row["live_date"])
        days_ago = (pd.Timestamp(as_of) - live).days

        since_return: float | None = None
        if not prices.empty and ticker in prices.columns:
            # Anchor at the launch date: the fetched window predates the index
            # (mock fills the whole range; real BQL carries backtest history),
            # so iloc[0] of the raw series is not the launch level.
            col = prices[ticker].dropna()
            col = col[col.index >= live]
            if len(col) >= 2:
                since_return = float(col.iloc[-1] / col.iloc[0] - 1.0)

        meta_bits = " · ".join(
            str(row.get(k))
            for k in LAUNCH_CARD_META_FIELDS
            if pd.notna(row.get(k)) and str(row.get(k))
        )
        cards.append(
            LaunchCard(
                name=row["name"],
                ticker=ticker,
                meta=meta_bits,
                live_date=live.date(),
                days_ago=int(days_ago),
                since_return=since_return,
            )
        )
    return cards
