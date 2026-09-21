"""Factor / Platform-view stats.

Macro-factor return proxies built from the already-fetched price cache
(equity risk premium, term premium), a thin factor-beta wrapper over
``risk.ann_beta``, and the per-ticker frame backing the Platform Icicle.
Everything here is a pure function over prices — no BQL, no fetch.
"""

from __future__ import annotations

import pandas as pd

from ..config import (
    EQUITY_FACTOR_TICKER,
    LONG_TREASURY_TICKER,
    SHARPE_WINDOW,
    SHORT_RATE_TICKER,
    TREND_TICKER,
    analytics_levels,
)
from ._common import daily_returns
from .risk import ann_beta
from .rolling import latest_rolling_metric


def _icicle_columns() -> list[str]:
    """The icicle frame's columns: each configured level, then ``value``.

    A function rather than a module constant so a reconfigured hierarchy is
    picked up without re-importing.
    """
    return [*analytics_levels(), "value"]


def _factor_spread(prices: pd.DataFrame, long_leg: str, short_leg: str) -> pd.Series:
    """Daily return of ``long_leg`` minus daily return of ``short_leg``.

    Returns an empty float Series when either leg is missing from ``prices`` so
    a partial/mock frame never raises.
    """
    if (
        prices.empty
        or long_leg not in prices.columns
        or short_leg not in prices.columns
    ):
        return pd.Series(dtype=float)
    rets = daily_returns(prices[[long_leg, short_leg]])
    return rets[long_leg] - rets[short_leg]


def equity_risk_premium(
    prices: pd.DataFrame,
    *,
    equity: str = EQUITY_FACTOR_TICKER,
    short_rate: str = SHORT_RATE_TICKER,
) -> pd.Series:
    """Daily equity-risk-premium factor return ≈ equity TR − short-rate TR."""
    return _factor_spread(prices, equity, short_rate).rename("equity_risk_premium")


def term_premium(
    prices: pd.DataFrame,
    *,
    long_bond: str = LONG_TREASURY_TICKER,
    short_rate: str = SHORT_RATE_TICKER,
) -> pd.Series:
    """Daily term-premium factor return ≈ long-Treasury TR − short-rate TR."""
    return _factor_spread(prices, long_bond, short_rate).rename("term_premium")


def trend_returns(prices: pd.DataFrame, *, trend: str = TREND_TICKER) -> pd.Series:
    """Daily return series of the cross-asset trend factor.

    Unlike the equity-risk / term premia (short-rate spreads), the trend factor
    β is taken vs the index's own returns, so this is a plain ``daily_returns``
    of the trend column. Returns an empty float Series when the column is
    missing so a partial/mock frame never raises.
    """
    if prices.empty or trend not in prices.columns:
        return pd.Series(dtype=float)
    return daily_returns(prices[[trend]])[trend].rename("trend")


def factor_beta(
    returns: pd.DataFrame, factor_returns: pd.Series, years: float
) -> pd.Series:
    """Beta of each strategy's returns to a factor-return series over ``years``.

    Thin wrapper over ``ann_beta`` — the "benchmark" is a daily factor-return
    series (e.g. from ``equity_risk_premium`` / ``term_premium``) rather than a
    price series, which ``ann_beta`` handles directly (cov/var on daily returns).
    """
    return ann_beta(returns, factor_returns, years)


def icicle_frame(
    prices: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    metric: str = "sharpe",
    window: int = SHARPE_WINDOW,
    returns: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per-ticker grouping levels + ``value`` for the Platform Icicle.

    One column per `config.ANALYTICS_LEVELS` entry (outermost grouping first)
    plus ``value`` = `latest_rolling_metric` — the **raw** metric over the
    window, not a z-score, so the cell's colour is the number the table beside
    it shows (#331 decision 2). A level the metadata does not carry comes back
    all-NA, which the renderer buckets as "Other", so a partial feed still
    draws. ``window`` is a trading-day count.

    Pass ``returns`` (e.g. a shared ``universe_rets``) to skip re-deriving
    `daily_returns` here; the result is identical either way.
    """
    columns = _icicle_columns()
    if prices.empty and returns is None:
        return pd.DataFrame(columns=columns)
    value = latest_rolling_metric(prices, metric=metric, window=window, returns=returns)
    frame = pd.DataFrame({"value": value})
    has_ticker = "ticker" in meta.columns
    for level in analytics_levels():
        if has_ticker and level in meta.columns:
            mapping = meta.set_index("ticker")[level]
            frame[level] = frame.index.map(mapping)
        else:
            frame[level] = pd.NA
    return frame[columns]
