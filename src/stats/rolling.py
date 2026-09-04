"""Rolling time-series metrics: rolling return / volatility / Sharpe / Sortino
(+ a generalized rolling-metric z-score), correlation, and beta."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import SHARPE_WINDOW, SHARPE_ZSCORE_WINDOW, TRADING_DAYS_PER_YEAR
from ._common import daily_returns


def rolling_correlation(
    returns: pd.DataFrame,
    benchmark: pd.Series,
    window: int = SHARPE_WINDOW,
) -> pd.DataFrame:
    """Rolling correlation of each return column to the benchmark."""
    if returns.empty or benchmark.empty:
        return pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    bench = benchmark.reindex(returns.index)
    return returns.rolling(window).corr(bench)


def rolling_beta(
    returns: pd.DataFrame,
    benchmark: pd.Series,
    window: int = SHARPE_WINDOW,
) -> pd.DataFrame:
    """Rolling beta of each return column to the benchmark (cov ÷ benchmark var)."""
    if returns.empty or benchmark.empty:
        return pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    bench = benchmark.reindex(returns.index)
    cov = returns.rolling(window).cov(bench)
    var = bench.rolling(window).var().replace(0, np.nan)
    return cov.divide(var, axis=0)


def rolling_return(returns: pd.DataFrame, window: int = SHARPE_WINDOW) -> pd.DataFrame:
    """Rolling annualized return over a ``window``-day window."""
    return returns.rolling(window).mean() * TRADING_DAYS_PER_YEAR


def rolling_volatility(
    returns: pd.DataFrame, window: int = SHARPE_WINDOW
) -> pd.DataFrame:
    """Rolling annualized volatility over a ``window``-day window."""
    return returns.rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def rolling_sharpe(returns: pd.DataFrame, window: int = SHARPE_WINDOW) -> pd.DataFrame:
    """Rolling annualized Sharpe: rolling annualized return ÷ rolling annualized vol."""
    mean = rolling_return(returns, window)
    std = rolling_volatility(returns, window)
    return mean.divide(std.replace(0, np.nan))


def rolling_sortino(returns: pd.DataFrame, window: int = SHARPE_WINDOW) -> pd.DataFrame:
    """Rolling annualized Sortino: rolling annualized return ÷ rolling annualized
    downside deviation (RMS of sub-zero returns), mirroring the scalar
    ``risk.sortino_ratio`` / ``risk.downside_deviation`` math."""
    ann_ret = rolling_return(returns, window)
    downside = returns.where(returns < 0.0, 0.0)
    dd = np.sqrt((downside**2).rolling(window).mean()) * np.sqrt(TRADING_DAYS_PER_YEAR)
    return ann_ret.divide(dd.replace(0, np.nan))


# Metric dispatch for ``rolling_metric_zscore``. Each maps a name → a rolling
# frame factory taking ``(returns, window)``.
_ROLLING_METRICS = {
    "sharpe": rolling_sharpe,
    "sortino": rolling_sortino,
    "return": rolling_return,
    "vol": rolling_volatility,
}


def rolling_metric_zscore(
    prices: pd.DataFrame,
    *,
    metric: str = "sharpe",
    window: int = SHARPE_WINDOW,
    zscore_window: int = SHARPE_ZSCORE_WINDOW,
    returns: pd.DataFrame | None = None,
) -> pd.Series:
    """Scalar z-score per ticker of the latest rolling ``metric`` vs its trailing
    ``zscore_window`` history. Generalizes ``sharpe_zscore`` across the metrics
    in ``_ROLLING_METRICS`` (``sharpe`` / ``sortino`` / ``return`` / ``vol``);
    ``metric="sharpe"`` reproduces ``sharpe_zscore(daily_returns(prices), …)``.

    The z-score is a scalar over only the trailing ``zscore_window`` of the
    rolling series, so only the last ``window + zscore_window`` observations
    matter — the input is sliced to that tail before the (potentially
    multi-year) rolling compute, which the whole-catalog Platform controls
    trigger on every change. Pass ``returns`` (e.g. a shared ``universe_rets``)
    to skip re-deriving ``daily_returns`` here; the result is identical either
    way, since the tail of the rolling series depends only on the tail of the
    returns.
    """
    try:
        metric_fn = _ROLLING_METRICS[metric]
    except KeyError:
        raise ValueError(
            f"unknown metric {metric!r}; choose from {sorted(_ROLLING_METRICS)}"
        ) from None
    need = window + zscore_window
    if returns is None:
        rets = daily_returns(prices.tail(need + 2))  # +1 for the pct_change drop
    else:
        rets = returns.tail(need + 1)
    series = metric_fn(rets, window)
    tail = series.tail(zscore_window)
    mean = tail.mean()
    std = tail.std().replace(0, np.nan)
    current = series.ffill().iloc[-1]
    return ((current - mean) / std).rename(f"{metric}_zscore")


def sharpe_zscore(
    returns: pd.DataFrame,
    window: int = SHARPE_WINDOW,
    zscore_window: int = SHARPE_ZSCORE_WINDOW,
) -> pd.Series:
    """Per-ticker z-score of the *latest* rolling Sharpe against its own recent tail."""
    sharpe = rolling_sharpe(returns, window=window)
    tail = sharpe.tail(zscore_window)
    mean = tail.mean()
    std = tail.std().replace(0, np.nan)
    current = sharpe.ffill().iloc[-1]
    return ((current - mean) / std).rename("sharpe_zscore")


def rolling_sharpe_zscore(
    returns: pd.DataFrame,
    window: int = SHARPE_WINDOW,
    zscore_window: int = SHARPE_ZSCORE_WINDOW,
) -> pd.DataFrame:
    """Full history of the rolling-Sharpe z-score, as a series per ticker."""
    sharpe = rolling_sharpe(returns, window=window)
    rolling_mean = sharpe.rolling(zscore_window).mean()
    rolling_std = sharpe.rolling(zscore_window).std().replace(0, np.nan)
    return (sharpe - rolling_mean) / rolling_std
