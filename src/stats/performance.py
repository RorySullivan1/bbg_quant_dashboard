"""Return / performance metrics: cumulative, annualized, and the perf tables."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PERF_TABLE_YEARS, TRADING_DAYS_PER_YEAR
from ._common import _has_enough_history, _slice_last_years, daily_returns, max_drawdown


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
    if isinstance(bench, pd.DataFrame):  # tolerate a 1-column frame
        bench = bench.iloc[:, 0]
    bench = bench.reindex(prices.index).ffill()
    strat_ret = cum_perf(prices).subtract(100)
    bench_ret = cum_perf(bench.to_frame()).iloc[:, 0].subtract(100)
    return strat_ret.subtract(bench_ret, axis=0)


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


def perf_table(
    prices: pd.DataFrame,
    years: tuple[int, ...] = PERF_TABLE_YEARS,
    *,
    returns: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return / Vol / Sharpe / Max DD per ticker across the given year windows.

    Rows: tickers. Columns: MultiIndex (period_label, metric).
    Cells where the ticker lacks enough history are NaN.

    ``returns`` may be passed when the caller already holds
    ``daily_returns(prices)`` (e.g. the selected-set ``prep.rets`` or the
    universe returns), to skip recomputing it here.
    """
    if prices.empty:
        return pd.DataFrame()
    rets = daily_returns(prices) if returns is None else returns
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
    """1Y / 3Y / 5Y window stats, in one MultiIndex frame.

    The Since-Inception block was dropped in v0.7.2 (it added width and its
    full-history window is the least comparable across indices of differing
    ages). ``since_inception_perf`` remains a tested pure util for potential
    reuse, just no longer wired into the all-catalog grid.
    """
    if prices.empty:
        return pd.DataFrame()
    # Compute the universe returns once and thread them into perf_table
    # instead of letting it recompute daily_returns internally.
    rets = daily_returns(prices)
    return perf_table(prices, years=years, returns=rets)
