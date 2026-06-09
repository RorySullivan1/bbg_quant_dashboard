from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .config import (
    NEW_LAUNCH_DAYS,
    SUPERLATIVE_WINDOW_DAYS,
    TRADING_DAYS_PER_YEAR,
)
from .stats import (
    _slice_last_years,
    ann_sharpe,
    ann_volatility,
    calmar_ratio,
    corr_matrix,
    historical_var,
    longest_down_streak,
    longest_up_streak,
    ma_spread,
    max_drawdown,
    period_return,
    rsi,
    sortino_ratio,
    trend_strength,
)


def build_superlatives(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    window_days: int = SUPERLATIVE_WINDOW_DAYS,
) -> list[dict]:
    """Whole-catalog "Market Superlatives" over the trailing ~1 month.

    One card per superlative = the single most-extreme index across the
    catalog (argmax/argmin) for that metric, computed over the trailing
    ``window_days`` from the already-fetched prices/returns (no BQL). Names
    with insufficient history surface as NaN and are skipped rather than
    erroring; ties break deterministically by ticker. Each card is
    ``{label, value, name, ticker, sentiment, description}`` (the description is
    a plain-English explanation rendered as the card's hover tooltip).
    """
    if prices.empty or returns.empty:
        return []

    name_lookup = meta.set_index("ticker")["name"].to_dict()

    def name_of(ticker: str) -> str:
        return name_lookup.get(ticker, ticker)

    years = window_days / TRADING_DAYS_PER_YEAR
    m1_prices = _slice_last_years(prices, years)
    m1_rets = _slice_last_years(returns, years)

    # Per-ticker metric series over the trailing window.
    pr = period_return(prices, window_days=window_days)
    ts = trend_strength(prices, window_days=window_days)
    streak = longest_up_streak(returns, window_days=window_days)
    down_streak = longest_down_streak(returns, window_days=window_days)
    sharpe = ann_sharpe(returns, prices, years)
    sortino = sortino_ratio(returns, prices, years)
    calmar = calmar_ratio(prices, years)
    vol = ann_volatility(returns, years)
    var = historical_var(returns, years)
    mdd = max_drawdown(prices, years)
    momentum = rsi(prices)
    mas = ma_spread(prices, window_days=window_days)

    # Best diversifier = lowest average pairwise correlation (self excluded).
    cm = corr_matrix(m1_rets)
    if cm.shape[0] >= 2:
        mean_corr = (cm.sum(axis=1) - 1.0) / (cm.shape[0] - 1)
    else:
        mean_corr = pd.Series(dtype=float)

    # Biggest turnaround = strongest rebound off the window's low.
    if not m1_prices.empty:
        turnaround = m1_prices.ffill().iloc[-1] / m1_prices.min() - 1.0
    else:
        turnaround = pd.Series(dtype=float)

    cards: list[dict] = []

    def add(label, series, *, mode, fmt, sentiment, description=""):
        s = series.dropna()
        if s.empty:
            return
        s = s.sort_index()  # deterministic tie-break by ticker
        ticker = s.idxmax() if mode == "max" else s.idxmin()
        cards.append(
            {
                "label": label,
                "value": fmt(s[ticker]),
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

    # --- performance / trend ---
    add(
        "Top performer",
        pr,
        mode="max",
        fmt=pct,
        sentiment="positive",
        description="Highest simple price return over the selected window.",
    )
    add(
        "Weakest performer",
        pr,
        mode="min",
        fmt=pct,
        sentiment="negative",
        description="Lowest (most negative) price return over the selected window.",
    )
    add(
        "Strongest trend",
        ts,
        mode="max",
        fmt=lambda v: f"{v * 100:+.2f}",
        sentiment="positive",
        description="Cleanest, most persistent uptrend (log-price slope × R²).",
    )
    add(
        "Longest bull run",
        streak,
        mode="max",
        fmt=lambda v: f"{int(v)}d",
        sentiment="positive",
        description="Most consecutive up days within the window.",
    )
    add(
        "Biggest turnaround",
        turnaround,
        mode="max",
        fmt=pct,
        sentiment="positive",
        description="Largest rebound from the window's low to the latest price.",
    )
    add(
        "Most extended",
        mas,
        mode="max",
        fmt=pct,
        sentiment="positive",
        description="Trades furthest above its moving average over the window.",
    )
    # --- risk-adjusted ---
    add(
        "Best risk-adjusted",
        sharpe,
        mode="max",
        fmt=num2,
        sentiment="positive",
        description="Highest annualized Sharpe ratio over the window.",
    )
    add(
        "Best Sortino",
        sortino,
        mode="max",
        fmt=num2,
        sentiment="positive",
        description="Highest Sortino ratio — return per unit of downside risk.",
    )
    add(
        "Highest Calmar",
        calmar,
        mode="max",
        fmt=num2,
        sentiment="positive",
        description="Highest return per unit of maximum drawdown.",
    )
    add(
        "Strongest momentum",
        momentum,
        mode="max",
        fmt=lambda v: f"{v:.0f}",
        sentiment="positive",
        description="Highest 14-day RSI — strongest momentum.",
    )
    # --- stability / resilience ---
    add(
        "Steadiest",
        vol,
        mode="min",
        fmt=lambda v: f"{v:.1%}",
        sentiment="neutral",
        description="Lowest annualized volatility over the window.",
    )
    add(
        "Most resilient",
        mdd,
        mode="max",
        fmt=pct,
        sentiment="positive",
        description="Shallowest peak-to-trough drawdown over the window.",
    )
    add(
        "Lowest tail risk",
        var,
        mode="min",
        fmt=lambda v: f"{v:.1%}",
        sentiment="positive",
        description="Smallest 95% one-day Value-at-Risk over the window.",
    )
    add(
        "Best diversifier",
        mean_corr,
        mode="min",
        fmt=num2,
        sentiment="neutral",
        description="Lowest average correlation to the rest of the catalog.",
    )
    # --- weakness / stress ---
    add(
        "Most volatile",
        vol,
        mode="max",
        fmt=lambda v: f"{v:.1%}",
        sentiment="negative",
        description="Highest annualized volatility — the wildest ride.",
    )
    add(
        "Hardest hit",
        mdd,
        mode="min",
        fmt=pct,
        sentiment="negative",
        description="Deepest peak-to-trough drawdown over the window.",
    )
    add(
        "Longest losing streak",
        down_streak,
        mode="max",
        fmt=lambda v: f"{int(v)}d",
        sentiment="negative",
        description="Most consecutive down days within the window.",
    )
    add(
        "Most oversold",
        momentum,
        mode="min",
        fmt=lambda v: f"{v:.0f}",
        sentiment="negative",
        description="Lowest 14-day RSI — most oversold, a potential rebound.",
    )
    add(
        "Most below trend",
        mas,
        mode="min",
        fmt=pct,
        sentiment="negative",
        description="Trades furthest below its moving average over the window.",
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
