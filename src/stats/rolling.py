"""Rolling time-series metrics: rolling return / volatility / Sharpe / Sortino /
Calmar (+ a generalized rolling-metric z-score), correlation, and beta."""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

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


def _rolling_max_drawdown(
    returns: pd.DataFrame, window: int = SHARPE_WINDOW
) -> pd.DataFrame:
    """Largest peak-to-trough loss **within** each trailing window, non-positive.

    The peak is measured inside the window, not from an all-time running high.
    That is what the scalar `max_drawdown` does — it slices to the window and
    only then takes `cummax` — and it is what keeps `rolling_metric_zscore`'s
    tail slicing honest: a value here depends only on the last ``window``
    returns, so feeding the function a tail cannot change it. A drawdown
    measured from a peak outside the window would depend on history that the
    tail has already dropped.

    Derived from returns rather than prices because the `_ROLLING_METRICS`
    contract is `(returns, window)` and `calmar_ratio` is the one metric in the
    family built on prices. The reconstructed path's absolute level does not
    matter: a drawdown is a ratio, so the price path and the returns path give
    the same answer from different starting levels.

    Vectorized per column over a strided view rather than `.rolling().apply()`,
    which would run a Python callable once per window — the whole-catalog board
    recomputes this on every window change. Measured at 60 tickers × 1512 rows
    with a 252-day window: ~0.14s.
    """
    if returns.empty or window <= 0 or window > len(returns):
        return pd.DataFrame(
            np.nan, index=returns.index, columns=returns.columns, dtype=float
        )
    # A missing day is carried flat. Windows that actually contain a NaN are
    # blanked anyway by the numerator in `rolling_calmar`, which is NaN there.
    #
    # The path is prefixed with the level the window opens at — 1.0, before its
    # first return. `w` returns span `w + 1` levels, and the opening one is a
    # peak candidate: without it a window whose high is its first day measures
    # a shallower drawdown than `max_drawdown` does over the same prices.
    grown = (1.0 + returns.fillna(0.0)).cumprod().to_numpy(dtype=float)
    path = np.vstack([np.ones((1, grown.shape[1])), grown])
    out = np.full(grown.shape, np.nan)
    for position in range(path.shape[1]):
        windows = sliding_window_view(path[:, position], window + 1)
        peak = np.maximum.accumulate(windows, axis=1)
        out[window - 1 :, position] = (windows / peak - 1.0).min(axis=1)
    return pd.DataFrame(out, index=returns.index, columns=returns.columns)


def rolling_calmar(returns: pd.DataFrame, window: int = SHARPE_WINDOW) -> pd.DataFrame:
    """Rolling Calmar: rolling annualized return ÷ the window's own max drawdown.

    Mirrors the scalar `risk.calmar_ratio` — same numerator shape, same
    `|drawdown|` denominator, and the same refusal to divide by a zero
    drawdown, so a series that only rose scores NaN rather than infinity.

    The warmup and missing-data behaviour comes from the numerator for free:
    `rolling_return` is NaN for any window holding a NaN (pandas requires a
    full window by default), so the division inherits it without a second mask.
    """
    ann_ret = rolling_return(returns, window)
    drawdown = _rolling_max_drawdown(returns, window).abs().replace(0, np.nan)
    return ann_ret.divide(drawdown)


# Metric dispatch for ``rolling_metric_zscore``. Each maps a name → a rolling
# frame factory taking ``(returns, window)``.
_ROLLING_METRICS = {
    "sharpe": rolling_sharpe,
    "sortino": rolling_sortino,
    "return": rolling_return,
    "vol": rolling_volatility,
    "calmar": rolling_calmar,
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
