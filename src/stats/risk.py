"""Risk & quantitative metrics: correlation, drawdown-based ratios, beta family,
downside risk, VaR, RSI, and the per-ticker quant-filter table."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import RSI_WINDOW, TRADING_DAYS_PER_YEAR, VAR_CONFIDENCE
from ._common import _benchmark_series, _slice_last_years, daily_returns, max_drawdown
from .performance import ann_return, ann_sharpe


def corr_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr()


def regime_corr_matrix(
    returns: pd.DataFrame,
    benchmark: pd.Series,
    pct: float,
    *,
    direction: str = "down",
    include_benchmark: bool = True,
) -> pd.DataFrame:
    """Correlation of ``returns`` restricted to a benchmark-return regime.

    ``pct`` is the tail size in [0, 1]. ``direction="down"`` keeps days where
    the benchmark return is at or below its ``pct`` quantile (worst days);
    ``direction="up"`` keeps days at or above its ``1 - pct`` quantile (best
    days). ``pct >= 1`` keeps all days. When ``include_benchmark``, the
    benchmark is appended as the **last** column so its conditional correlation
    to each strategy (and self = 1) appears in the matrix — its column carries
    the benchmark's name so it lines up with the full-ticker strategy columns
    the heatmap already shows. If the benchmark ticker is also one of the
    selected strategies, its strategy column is dropped first so the benchmark
    appears exactly once (last) rather than overwriting that strategy's returns
    in place. Returns an empty frame when the regime selects fewer than 2 rows
    (caller falls back to a blank heatmap). Prefer :func:`heatmap_corr_matrix`
    as the single entry point for the Correlation-Heatmap panes.
    """
    if returns.empty or benchmark is None or benchmark.empty or pct <= 0:
        return pd.DataFrame()
    bench = benchmark.reindex(returns.index)
    valid = bench.dropna()
    if valid.empty:
        return pd.DataFrame()
    if direction == "up":
        thresh = valid.quantile(1.0 - pct)
        mask = bench >= thresh
    else:
        thresh = valid.quantile(pct)
        mask = bench <= thresh
    mask = mask.fillna(False)
    sub = returns.loc[mask]
    if include_benchmark:
        # Drop any same-named strategy column first so the benchmark is appended
        # last (not overwritten in place, which would also clobber the strategy's
        # own returns with the benchmark's).
        sub = sub.drop(columns=[bench.name], errors="ignore").copy()
        sub[bench.name] = bench.loc[mask]
    if sub.shape[0] < 2:
        return pd.DataFrame()
    return corr_matrix(sub)


def heatmap_corr_matrix(
    returns: pd.DataFrame,
    benchmark: pd.Series | None = None,
    *,
    pct: float = 1.0,
    direction: str = "down",
) -> pd.DataFrame:
    """Single source of truth for the Multi-Strategy Correlation-Heatmap matrix.

    Both analysis panes (left and right) build their heatmap through this one
    function so they can never diverge. With ``benchmark=None`` it returns the
    plain full-sample correlation of ``returns``. With a ``benchmark`` it
    conditions on the benchmark-return regime (``pct``/``direction``; ``pct >= 1``
    keeps every day, i.e. plain full sample) and adds the benchmark as a
    row/column **pinned last and de-duplicated** — strategies keep their existing
    order and the benchmark is always the final column, appearing exactly once
    even when its ticker is also a selected strategy. Returns an empty frame when
    there's no benchmark data or the regime selects fewer than 2 rows (caller
    falls back to a blank heatmap).
    """
    if benchmark is None:
        return corr_matrix(returns)
    cm = regime_corr_matrix(
        returns, benchmark, pct, direction=direction, include_benchmark=True
    )
    if cm.empty:
        return cm
    # Pin the column/row order explicitly rather than relying on pandas'
    # insert-vs-overwrite side effects, so the layout is deterministic and
    # identical across panes: strategies in their original order, benchmark last.
    order = [c for c in returns.columns if c != benchmark.name] + [benchmark.name]
    return cm.reindex(index=order, columns=order)


def return_distribution_stats(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.empty:
        return pd.DataFrame(columns=["Mean", "Std", "Skew", "Kurtosis", "Min", "Max"])
    stats = pd.DataFrame(
        {
            "Mean": returns.mean(),
            "Std": returns.std(),
            "Skew": returns.skew(),
            "Kurtosis": returns.kurtosis(),
            "Min": returns.min(),
            "Max": returns.max(),
        }
    )
    return stats


def return_skew(returns: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Per-ticker skewness of daily returns over the trailing window.

    Positive = a right tail (occasional large gains); negative = a left tail
    (occasional large losses). Columns with fewer than three valid points in
    the window are NaN. Powers the "Most positive / Most negative skew"
    superlatives.
    """
    if returns.empty:
        return pd.Series(dtype=float)
    window = returns.tail(window_days)
    out = window.skew()
    out[window.notna().sum() < 3] = np.nan
    return out.rename("return_skew")


def recovery_days(prices: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Per-ticker days to recover from the window's largest drawdown.

    For each ticker, finds the deepest peak-to-trough drawdown in the trailing
    ``window_days`` and counts the trading days from that trough until price
    first regains the pre-drawdown peak. NaN when there is no drawdown in the
    window or the drawdown has not recovered by the window's end. "Fastest
    recovery" = the minimum across the catalog.
    """
    if prices.empty:
        return pd.Series(dtype=float)
    window = prices.tail(window_days)
    out: dict[str, float] = {}
    for col in window.columns:
        series = window[col].dropna()
        if len(series) < 2:
            out[col] = np.nan
            continue
        running_max = series.cummax()
        dd = series / running_max - 1.0
        if dd.min() >= -1e-12:  # no meaningful drawdown
            out[col] = np.nan
            continue
        trough_pos = int(dd.to_numpy().argmin())
        peak_val = running_max.iloc[trough_pos]
        after = series.iloc[trough_pos:].to_numpy()
        recovered = np.flatnonzero(after >= peak_val)
        recovered = recovered[recovered > 0]  # strictly after the trough
        out[col] = float(recovered[0]) if recovered.size else np.nan
    return pd.Series(out, dtype=float).rename("recovery_days")


# ---- Quantitative filter metrics (per-ticker scalars) ---------------------


def calmar_ratio(prices: pd.DataFrame, years: float) -> pd.Series:
    """Annualized return divided by the absolute max drawdown over `years`."""
    ret = ann_return(prices, years)
    dd = max_drawdown(prices, years).abs().replace(0, np.nan)
    return ret.divide(dd)


def ann_beta(returns: pd.DataFrame, benchmark: pd.Series, years: float) -> pd.Series:
    """Scalar beta of each column vs `benchmark` over the last `years`.

    beta = cov(asset, benchmark) / var(benchmark), computed on the sliced
    daily-return window (not rolling). Returns a Series indexed by ticker.
    """
    if returns.empty or benchmark is None or benchmark.empty:
        return pd.Series(np.nan, index=returns.columns)
    bench = benchmark
    if isinstance(bench, pd.DataFrame):  # tolerate a 1-column frame
        bench = bench.iloc[:, 0]
    sliced = _slice_last_years(returns, years)
    bench = bench.reindex(sliced.index)
    var = bench.var()
    if not var or np.isnan(var):
        return pd.Series(np.nan, index=returns.columns)
    cov = sliced.apply(lambda col: col.cov(bench))
    return cov.divide(var)


def treynor_ratio(
    returns: pd.DataFrame, prices: pd.DataFrame, benchmark: pd.Series, years: float
) -> pd.Series:
    """Annualized return divided by beta vs `benchmark` (risk-free = 0)."""
    ret = ann_return(prices, years)
    beta = ann_beta(returns, benchmark, years).replace(0, np.nan)
    return ret.divide(beta)


def jensen_alpha(
    returns: pd.DataFrame, prices: pd.DataFrame, benchmark: pd.Series, years: float
) -> pd.Series:
    """Jensen's alpha (risk-free = 0): asset return − beta · benchmark return.

    All annualized over the trailing `years` window. Returns a Series per ticker.
    """
    bench = _benchmark_series(benchmark)
    if bench is None:
        return pd.Series(np.nan, index=prices.columns)
    bench_ret = ann_return(bench.to_frame(), years).iloc[0]
    beta = ann_beta(returns, benchmark, years)
    return ann_return(prices, years) - beta * bench_ret


def downside_deviation(
    returns: pd.DataFrame, years: float, target: float = 0.0
) -> pd.Series:
    """Annualized downside deviation: RMS of returns below `target` over `years`."""
    sliced = _slice_last_years(returns, years)
    if sliced.empty:
        return pd.Series(np.nan, index=returns.columns)
    downside = sliced.where(sliced < target, 0.0)
    return np.sqrt((downside**2).mean()) * np.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(
    returns: pd.DataFrame, prices: pd.DataFrame, years: float, target: float = 0.0
) -> pd.Series:
    """Annualized return divided by downside deviation (risk-free = 0)."""
    ret = ann_return(prices, years)
    dd = downside_deviation(returns, years, target).replace(0, np.nan)
    return ret.divide(dd)


def historical_var(
    returns: pd.DataFrame, years: float, confidence: float = VAR_CONFIDENCE
) -> pd.Series:
    """Historical daily VaR per ticker as a positive loss magnitude.

    The `(1 - confidence)` quantile of daily returns (a negative number) is
    negated, so e.g. 0.025 means a 2.5% worst-case daily loss at the given
    confidence. Higher = riskier.
    """
    sliced = _slice_last_years(returns, years)
    if sliced.empty:
        return pd.Series(np.nan, index=returns.columns)
    return -sliced.quantile(1.0 - confidence)


def rsi(prices: pd.DataFrame, window: int = RSI_WINDOW) -> pd.Series:
    """Latest Wilder RSI (0–100) per ticker over `window` trading days."""
    if prices.empty:
        return pd.Series(np.nan, index=prices.columns)
    delta = prices.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window).mean()
    rs = avg_gain.divide(avg_loss.replace(0, np.nan))
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    # All-gain windows (avg_loss == 0) are maximally overbought.
    rsi_series = rsi_series.where(avg_loss != 0, 100.0)
    return rsi_series.ffill().iloc[-1]


def quant_metrics_table(
    prices: pd.DataFrame,
    benchmark: pd.Series,
    years: float,
    *,
    var_confidence: float = VAR_CONFIDENCE,
    rsi_window: int = RSI_WINDOW,
    returns: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per-ticker quant-filter metrics table.

    Columns: Sharpe / Sortino / Calmar / Beta / Treynor / Jensen / VaR / RSI.
    Rows: tickers (columns of `prices`). One scalar per metric over the
    trailing `years` window (RSI uses its own `rsi_window`); Beta / Treynor /
    Jensen are measured vs `benchmark`. The cross-sectional Z-Score is derived
    on demand by the caller via `zscore_cross_section`.

    ``returns`` may be passed when the caller already holds
    ``daily_returns(prices)``, to skip recomputing it here.
    """
    columns = [
        "Sharpe",
        "Sortino",
        "Calmar",
        "Beta",
        "Treynor",
        "Jensen",
        "VaR",
        "RSI",
    ]
    if prices.empty:
        return pd.DataFrame(columns=columns)
    rets = daily_returns(prices) if returns is None else returns
    return pd.DataFrame(
        {
            "Sharpe": ann_sharpe(rets, prices, years),
            "Sortino": sortino_ratio(rets, prices, years),
            "Calmar": calmar_ratio(prices, years),
            "Beta": ann_beta(rets, benchmark, years),
            "Treynor": treynor_ratio(rets, prices, benchmark, years),
            "Jensen": jensen_alpha(rets, prices, benchmark, years),
            "VaR": historical_var(rets, years, var_confidence),
            "RSI": rsi(prices, rsi_window),
        }
    )
