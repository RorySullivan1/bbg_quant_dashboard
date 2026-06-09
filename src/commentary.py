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
    corr_matrix,
    longest_up_streak,
    max_drawdown,
    period_return,
    rsi,
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
    ``{label, value, name, ticker, sentiment, detail}``.
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
    sharpe = ann_sharpe(returns, prices, years)
    vol = ann_volatility(returns, years)
    mdd = max_drawdown(prices, years)
    momentum = rsi(prices)

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

    def add(label, series, *, mode, fmt, sentiment, detail=""):
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
                "detail": detail,
            }
        )

    def pct(v: float) -> str:
        return f"{v:+.1%}"

    add(
        "Top performer",
        pr,
        mode="max",
        fmt=pct,
        sentiment="positive",
        detail="1M return",
    )
    add(
        "Weakest performer",
        pr,
        mode="min",
        fmt=pct,
        sentiment="negative",
        detail="1M return",
    )
    add(
        "Strongest trend",
        ts,
        mode="max",
        fmt=lambda v: f"{v * 100:+.2f}",
        sentiment="positive",
        detail="Trend score",
    )
    add(
        "Longest bull run",
        streak,
        mode="max",
        fmt=lambda v: f"{int(v)}d",
        sentiment="positive",
        detail="Consecutive up days",
    )
    add(
        "Best risk-adjusted",
        sharpe,
        mode="max",
        fmt=lambda v: f"{v:.2f}",
        sentiment="positive",
        detail="Sharpe (1M)",
    )
    add(
        "Steadiest",
        vol,
        mode="min",
        fmt=lambda v: f"{v:.1%}",
        sentiment="neutral",
        detail="Ann. vol (1M)",
    )
    add(
        "Most resilient",
        mdd,
        mode="max",
        fmt=pct,
        sentiment="positive",
        detail="Shallowest drawdown",
    )
    add(
        "Strongest momentum",
        momentum,
        mode="max",
        fmt=lambda v: f"{v:.0f}",
        sentiment="positive",
        detail="RSI",
    )
    add(
        "Best diversifier",
        mean_corr,
        mode="min",
        fmt=lambda v: f"{v:.2f}",
        sentiment="neutral",
        detail="Avg correlation",
    )
    add(
        "Biggest turnaround",
        turnaround,
        mode="max",
        fmt=pct,
        sentiment="positive",
        detail="Rebound off low",
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
