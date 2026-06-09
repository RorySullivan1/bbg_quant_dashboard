from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .config import (
    NEW_LAUNCH_DAYS,
    SUPERLATIVE_WINDOW_DAYS,
    TRADING_DAYS_PER_YEAR,
)
from .stats import (
    ann_sharpe,
    asset_class_demeaned_zscore,
    historical_var,
    longest_down_streak,
    longest_up_streak,
    macd_histogram,
    max_drawdown,
    max_drawup,
    period_return,
    recovery_days,
    return_autocorr,
    return_skew,
    rsi,
    win_rate,
)


def build_superlatives(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    window_days: int = SUPERLATIVE_WINDOW_DAYS,
) -> list[dict]:
    """Whole-catalog "Market Superlatives" over the trailing window.

    A board of **symmetric best/worst** pairs plus two singles, built from
    technical / character-based indicators (persistence, momentum, recovery,
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
    drop a few cards); ties break deterministically by ticker. Each card is
    ``{label, value, name, ticker, sentiment, description}`` where ``description``
    states **only how the metric is calculated** (the card's hover tooltip).
    """
    if prices.empty or returns.empty:
        return []

    name_lookup = meta.set_index("ticker")["name"].to_dict()

    def name_of(ticker: str) -> str:
        return name_lookup.get(ticker, ticker)

    # Per-ticker asset class for the cross-asset-neutral z-ranking. Tickers with
    # no mapped class share one cohort so the demeaned z-rank stays defined.
    if "asset_class" in meta.columns:
        asset_class = meta.set_index("ticker")["asset_class"]
    else:
        asset_class = pd.Series(dtype=object)
    asset_class = asset_class.reindex(prices.columns).fillna("Unclassified")

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
    var = historical_var(returns, years)
    recovery = recovery_days(prices, window_days=window_days)
    # Fixed-lookback oscillators (window-toggle-independent).
    momentum = rsi(prices)
    macd = macd_histogram(prices)

    def acz(metric: pd.Series) -> pd.Series:
        return asset_class_demeaned_zscore(metric, asset_class)

    cards: list[dict] = []

    def add(label, series, *, mode, fmt, sentiment, description="", rank_by=None):
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
        cards.append(
            {
                "label": label,
                "value": fmt(s[ticker]),  # always the raw metric value
                "name": name_of(ticker),
                "ticker": ticker,
                "sentiment": sentiment,
                "description": description,
            }
        )

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
    add(
        "Best performer",
        pr,
        mode="max",
        fmt=pct,
        sentiment="positive",
        description=perf_desc,
        rank_by=acz(pr),
    )
    add(
        "Worst performer",
        pr,
        mode="min",
        fmt=pct,
        sentiment="negative",
        description=perf_desc,
        rank_by=acz(pr),
    )
    # --- trend persistence (raw) ---
    autocorr_desc = "Lag-1 Pearson autocorrelation of daily returns over the window."
    add(
        "Most trending",
        autocorr,
        mode="max",
        fmt=signed2,
        sentiment="neutral",
        description=autocorr_desc,
    )
    add(
        "Most mean-reverting",
        autocorr,
        mode="min",
        fmt=signed2,
        sentiment="neutral",
        description=autocorr_desc,
    )
    # --- run duration (raw) ---
    add(
        "Longest bull run",
        up_streak,
        mode="max",
        fmt=lambda v: f"{int(v)}d",
        sentiment="positive",
        description="Most consecutive up days (positive daily returns) in the window.",
    )
    add(
        "Longest bear run",
        down_streak,
        mode="max",
        fmt=lambda v: f"{int(v)}d",
        sentiment="negative",
        description="Most consecutive down days (negative daily returns) in the window.",
    )
    # --- RSI (raw, fixed 14d lookback) ---
    rsi_desc = "14-day Wilder RSI of daily closing levels."
    add(
        "Most overbought",
        momentum,
        mode="max",
        fmt=lambda v: f"{v:.0f}",
        sentiment="neutral",
        description=rsi_desc,
    )
    add(
        "Most oversold",
        momentum,
        mode="min",
        fmt=lambda v: f"{v:.0f}",
        sentiment="neutral",
        description=rsi_desc,
    )
    # --- MACD extension (asset-class-demeaned z-rank, fixed 12/26/9 lookback) ---
    macd_desc = (
        "MACD histogram (12/26/9 EMAs) divided by the last price; ranked across "
        "the catalog by its asset-class-demeaned z-score."
    )
    add(
        "Most extended up",
        macd,
        mode="max",
        fmt=lambda v: f"{v:+.2%}",
        sentiment="positive",
        description=macd_desc,
        rank_by=acz(macd),
    )
    add(
        "Most extended down",
        macd,
        mode="min",
        fmt=lambda v: f"{v:+.2%}",
        sentiment="negative",
        description=macd_desc,
        rank_by=acz(macd),
    )
    # --- drawup / drawdown (asset-class-demeaned z-rank) ---
    add(
        "Largest drawup",
        drawup,
        mode="max",
        fmt=pct,
        sentiment="positive",
        description="Largest run-up from a running low in the window (price ÷ "
        "running-min − 1); ranked by asset-class-demeaned z-score.",
        rank_by=acz(drawup),
    )
    add(
        "Deepest drawdown",
        mdd,
        mode="min",
        fmt=pct,
        sentiment="negative",
        description="Deepest peak-to-trough drawdown in the window (price ÷ "
        "running-max − 1); ranked by asset-class-demeaned z-score.",
        rank_by=acz(mdd),
    )
    # --- risk-adjusted (asset-class-demeaned z-rank) ---
    sharpe_desc = (
        "Annualized Sharpe ratio over the window (return ÷ volatility, "
        "risk-free 0); ranked by asset-class-demeaned z-score."
    )
    add(
        "Best risk-adjusted",
        sharpe,
        mode="max",
        fmt=num2,
        sentiment="positive",
        description=sharpe_desc,
        rank_by=acz(sharpe),
    )
    add(
        "Worst risk-adjusted",
        sharpe,
        mode="min",
        fmt=num2,
        sentiment="negative",
        description=sharpe_desc,
        rank_by=acz(sharpe),
    )
    # --- win rate (raw) ---
    winrate_desc = "Share of days with a positive daily return over the window."
    add(
        "Highest win rate",
        wr,
        mode="max",
        fmt=lambda v: f"{v:.0%}",
        sentiment="positive",
        description=winrate_desc,
    )
    add(
        "Lowest win rate",
        wr,
        mode="min",
        fmt=lambda v: f"{v:.0%}",
        sentiment="negative",
        description=winrate_desc,
    )
    # --- skewness (raw) ---
    skew_desc = "Skewness of daily returns over the window."
    add(
        "Most positive skew",
        skew,
        mode="max",
        fmt=signed2,
        sentiment="positive",
        description=skew_desc,
    )
    add(
        "Most negative skew",
        skew,
        mode="min",
        fmt=signed2,
        sentiment="negative",
        description=skew_desc,
    )
    # --- singles ---
    add(
        "Lowest VaR",
        var,
        mode="min",
        fmt=lambda v: f"{v:.1%}",
        sentiment="positive",
        description="5th-percentile of daily returns over the window (historical "
        "95% one-day VaR); ranked by asset-class-demeaned z-score.",
        rank_by=acz(var),
    )
    add(
        "Fastest recovery",
        recovery,
        mode="min",
        fmt=lambda v: f"{int(v)}d",
        sentiment="positive",
        description="Days from the largest drawdown's trough until price regains "
        "its prior peak.",
    )
    return cards


def build_launch_cards(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of: date | None = None,
    new_launch_days: int = NEW_LAUNCH_DAYS,
) -> list[dict]:
    """New-launch cards (newest-first) with metadata for the right panel.

    Each entry: ``{name, ticker, meta, live_date, days_ago, since_return}``
    where ``meta`` is ``asset_class · theme · currency`` and ``since_return``
    is the simple cumulative return since the index's first valid observation
    (not annualized — a 3-week-old index annualizes to nonsense). Returns an
    empty list when no launches fall within ``new_launch_days``.
    """
    as_of = as_of or date.today()
    if meta.empty:
        return []
    cutoff = pd.Timestamp(as_of) - timedelta(days=new_launch_days)
    recent = meta[meta["live_date"] >= cutoff].sort_values("live_date", ascending=False)
    if recent.empty:
        return []

    cards: list[dict] = []
    for _, row in recent.iterrows():
        ticker = row["ticker"]
        live = pd.Timestamp(row["live_date"])
        days_ago = (pd.Timestamp(as_of) - live).days

        since_return = "—"
        if not prices.empty and ticker in prices.columns:
            col = prices[ticker].dropna()
            if len(col) >= 2:
                since_return = f"{col.iloc[-1] / col.iloc[0] - 1.0:+.1%}"

        meta_bits = " · ".join(
            str(row.get(k))
            for k in ("asset_class", "theme", "currency")
            if pd.notna(row.get(k)) and str(row.get(k))
        )
        cards.append(
            {
                "name": row["name"],
                "ticker": ticker,
                "meta": meta_bits,
                "live_date": live.date().isoformat(),
                "days_ago": int(days_ago),
                "since_return": since_return,
            }
        )
    return cards
