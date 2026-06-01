from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    PERF_TABLE_YEARS,
    SHARPE_WINDOW,
    SHARPE_ZSCORE_WINDOW,
    TRADING_DAYS_PER_YEAR,
)


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().dropna(how="all")


def cum_perf(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices
    first = prices.bfill().iloc[0]
    return prices.divide(first).multiply(100)


def total_return(prices: pd.DataFrame) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    first = prices.bfill().iloc[0]
    last = prices.ffill().iloc[-1]
    return (last / first - 1).rename("total_return")


def weekly_change(prices: pd.DataFrame) -> pd.Series:
    if prices.empty or len(prices) < 6:
        return pd.Series(dtype=float)
    last = prices.ffill().iloc[-1]
    prior = prices.ffill().iloc[-6]
    return (last / prior - 1).rename("weekly_change")


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
    benchmark is appended as a column so its conditional correlation to each
    strategy (and self = 1) appears in the matrix — its column carries the
    benchmark's name so it lines up with the full-ticker strategy columns the
    heatmap already shows. Returns an empty frame when the regime selects fewer
    than 2 rows (caller falls back to a blank heatmap).
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
        sub = sub.copy()
        sub[bench.name] = bench.loc[mask]
    if sub.shape[0] < 2:
        return pd.DataFrame()
    return corr_matrix(sub)


def drawdown_series(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices
    return prices.divide(prices.cummax()).subtract(1.0)


def excess_cum_return(prices: pd.DataFrame, benchmark: pd.Series) -> pd.DataFrame:
    """Cumulative excess return vs a benchmark, in percentage points.

    Each column is the strategy's cumulative % return minus the benchmark's
    cumulative % return over the same window, so every series starts at 0 and
    a value above 0 means the strategy has outperformed the benchmark since
    the window start. Same shape as ``prices``.
    """
    if prices.empty or benchmark.empty:
        return pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    bench = benchmark
    if isinstance(bench, pd.DataFrame):   # tolerate a 1-column frame
        bench = bench.iloc[:, 0]
    bench = bench.reindex(prices.index).ffill()
    strat_ret = cum_perf(prices).subtract(100)
    bench_ret = cum_perf(bench.to_frame()).iloc[:, 0].subtract(100)
    return strat_ret.subtract(bench_ret, axis=0)


def rolling_correlation(
    returns: pd.DataFrame,
    benchmark: pd.Series,
    window: int = SHARPE_WINDOW,
) -> pd.DataFrame:
    if returns.empty or benchmark.empty:
        return pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    bench = benchmark.reindex(returns.index)
    return returns.rolling(window).corr(bench)


def rolling_beta(
    returns: pd.DataFrame,
    benchmark: pd.Series,
    window: int = SHARPE_WINDOW,
) -> pd.DataFrame:
    if returns.empty or benchmark.empty:
        return pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    bench = benchmark.reindex(returns.index)
    cov = returns.rolling(window).cov(bench)
    var = bench.rolling(window).var().replace(0, np.nan)
    return cov.divide(var, axis=0)


def return_distribution_stats(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.empty:
        return pd.DataFrame(
            columns=["Mean", "Std", "Skew", "Kurtosis", "Min", "Max"]
        )
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


def rolling_sharpe(
    returns: pd.DataFrame, window: int = SHARPE_WINDOW
) -> pd.DataFrame:
    mean = returns.rolling(window).mean() * TRADING_DAYS_PER_YEAR
    std = returns.rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    return mean.divide(std.replace(0, np.nan))


def sharpe_zscore(
    returns: pd.DataFrame,
    window: int = SHARPE_WINDOW,
    zscore_window: int = SHARPE_ZSCORE_WINDOW,
) -> pd.Series:
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
    sharpe = rolling_sharpe(returns, window=window)
    rolling_mean = sharpe.rolling(zscore_window).mean()
    rolling_std = sharpe.rolling(zscore_window).std().replace(0, np.nan)
    return (sharpe - rolling_mean) / rolling_std


def _slice_last_years(df: pd.DataFrame, years: float) -> pd.DataFrame:
    if df.empty:
        return df
    end = df.index.max()
    start = end - pd.Timedelta(days=int(years * 365.25))
    sliced = df.loc[df.index >= start]
    return sliced


def _has_enough_history(prices: pd.DataFrame, years: float) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=bool)
    end = prices.index.max()
    required = end - pd.Timedelta(days=int(years * 365.25))
    first_valid = prices.apply(lambda s: s.first_valid_index())
    return first_valid.notna() & (first_valid <= required)


def ann_return(prices: pd.DataFrame, years: float) -> pd.Series:
    sliced = _slice_last_years(prices, years)
    if sliced.empty:
        return pd.Series(np.nan, index=prices.columns)
    first = sliced.bfill().iloc[0]
    last = sliced.ffill().iloc[-1]
    total = last / first
    span_years = (sliced.index.max() - sliced.index.min()).days / 365.25
    if span_years <= 0:
        return pd.Series(np.nan, index=prices.columns)
    return total ** (1.0 / span_years) - 1.0


def ann_volatility(returns: pd.DataFrame, years: float) -> pd.Series:
    sliced = _slice_last_years(returns, years)
    if sliced.empty:
        return pd.Series(np.nan, index=returns.columns)
    return sliced.std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def ann_sharpe(returns: pd.DataFrame, prices: pd.DataFrame, years: float) -> pd.Series:
    vol = ann_volatility(returns, years)
    ret = ann_return(prices, years)
    return ret.divide(vol.replace(0, np.nan))


def max_drawdown(prices: pd.DataFrame, years: float) -> pd.Series:
    sliced = _slice_last_years(prices, years)
    if sliced.empty:
        return pd.Series(np.nan, index=prices.columns)
    running_max = sliced.cummax()
    drawdowns = sliced / running_max - 1.0
    return drawdowns.min()


def perf_table(
    prices: pd.DataFrame,
    years: tuple[int, ...] = PERF_TABLE_YEARS,
) -> pd.DataFrame:
    """Return / Vol / Sharpe / Max DD per ticker across the given year windows.

    Rows: tickers. Columns: MultiIndex (period_label, metric).
    Cells where the ticker lacks enough history are NaN.
    """
    if prices.empty:
        return pd.DataFrame()
    rets = daily_returns(prices)
    blocks: list[pd.DataFrame] = []
    for y in years:
        ret = ann_return(prices, y)
        vol = ann_volatility(rets, y)
        sharpe = ret.divide(vol.replace(0, np.nan))
        dd = max_drawdown(prices, y)
        enough = _has_enough_history(prices, y)
        block = pd.DataFrame(
            {"Return": ret, "Vol": vol, "Sharpe": sharpe, "Max DD": dd}
        )
        block.loc[~enough] = np.nan
        block.columns = pd.MultiIndex.from_product([[f"{y}Y"], block.columns])
        blocks.append(block)
    return pd.concat(blocks, axis=1)


def since_inception_perf(prices: pd.DataFrame) -> pd.DataFrame:
    """Return / Vol / Sharpe / Max DD per ticker over each ticker's full
    valid history (first-non-NaN to last-non-NaN). MultiIndex columns of
    the form ("SI", metric). Fully vectorized — no per-ticker Python loop.
    """
    if prices.empty:
        return pd.DataFrame()

    first_valid = prices.apply(pd.Series.first_valid_index)
    last_valid = prices.apply(pd.Series.last_valid_index)
    span_days = (last_valid - first_valid).dt.total_seconds() / 86_400.0
    span_years = span_days / 365.25
    valid = span_years > 0

    first_vals = prices.bfill().iloc[0]
    last_vals = prices.ffill().iloc[-1]
    total = last_vals / first_vals

    ann_ret = pd.Series(np.nan, index=prices.columns)
    ann_ret[valid] = total[valid] ** (1.0 / span_years[valid]) - 1.0

    vol = prices.pct_change().std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = ann_ret.divide(vol.replace(0, np.nan))

    running_max = prices.cummax()
    max_dd = (prices / running_max - 1.0).min()

    frame = pd.DataFrame(
        {"Return": ann_ret, "Vol": vol, "Sharpe": sharpe, "Max DD": max_dd}
    )
    frame.columns = pd.MultiIndex.from_product([["SI"], frame.columns])
    return frame


def universe_perf(
    prices: pd.DataFrame,
    years: tuple[int, ...] = PERF_TABLE_YEARS,
) -> pd.DataFrame:
    """1Y / 3Y / 5Y window stats plus Since-Inception, in one MultiIndex frame."""
    if prices.empty:
        return pd.DataFrame()
    return pd.concat([perf_table(prices, years=years), since_inception_perf(prices)], axis=1)
