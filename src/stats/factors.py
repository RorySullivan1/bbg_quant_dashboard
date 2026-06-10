"""Factor / Platform-view stats (v0.7.0 Workstream B).

Macro-factor return proxies built from the already-fetched price cache
(equity risk premium, term premium), a thin factor-beta wrapper over
``risk.ann_beta``, and the per-ticker frame backing the Platform asset-class
treemap. Everything here is a pure function over prices — no BQL, no fetch.
"""

from __future__ import annotations

import pandas as pd

from ..config import (
    EQUITY_FACTOR_TICKER,
    HALF_YEAR_WINDOW,
    LONG_TREASURY_TICKER,
    SHARPE_ZSCORE_WINDOW,
    SHORT_RATE_TICKER,
    TREND_TICKER,
    WEEK_WINDOW,
)
from ._common import daily_returns
from .risk import ann_beta
from .rolling import rolling_metric_zscore

_TREEMAP_COLUMNS = ["asset_class", "theme", "size_z", "color_z"]


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


def platform_treemap_frame(
    prices: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    size_metric: str = "sharpe",
    size_window: int = HALF_YEAR_WINDOW,
    size_lookback: int = SHARPE_ZSCORE_WINDOW,
    color_metric: str = "sharpe",
    color_window: int = WEEK_WINDOW,
    color_lookback: int = SHARPE_ZSCORE_WINDOW,
) -> pd.DataFrame:
    """Per-ticker ``asset_class`` + ``theme`` + ``size_z`` + ``color_z`` for the
    Platform treemap. ``size_z`` = z(``size_metric`` over ``size_window``,
    ``size_lookback``); ``color_z`` likewise — both **raw** z-scores (can be
    negative). The metric/window/lookback of each are user-selectable (defaults
    reproduce the historical z(6M Sharpe, 1Y) size + z(1W Sharpe, 1Y) color).
    The non-negative size transform for ``go.Treemap.values`` is the renderer's
    concern, not this frame's. ``asset_class`` and ``theme`` give the treemap's
    two grouping levels (asset class → theme → ticker). The ``*_window`` /
    ``*_lookback`` args are trading-day counts.
    """
    if prices.empty:
        return pd.DataFrame(columns=_TREEMAP_COLUMNS)
    size_z = rolling_metric_zscore(
        prices, metric=size_metric, window=size_window, zscore_window=size_lookback
    )
    color_z = rolling_metric_zscore(
        prices, metric=color_metric, window=color_window, zscore_window=color_lookback
    )
    frame = pd.DataFrame({"size_z": size_z, "color_z": color_z})
    has_ticker = "ticker" in meta.columns
    for level in ("asset_class", "theme"):
        if has_ticker and level in meta.columns:
            mapping = meta.set_index("ticker")[level]
            frame[level] = frame.index.map(mapping)
        else:
            frame[level] = pd.NA
    return frame[_TREEMAP_COLUMNS]
