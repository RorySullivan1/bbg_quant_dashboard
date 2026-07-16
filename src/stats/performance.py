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


def period_return(prices: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Simple cumulative return over the trailing ``window_days`` rows.

    The intuitive "past-month return" used by the superlative cards — a plain
    last/first - 1 over the window, **not** annualized. Columns with fewer than
    two valid observations in the window are NaN.
    """
    if prices.empty:
        return pd.Series(dtype=float)
    tail = prices.tail(window_days + 1)
    first = tail.bfill().iloc[0]
    last = tail.ffill().iloc[-1]
    out = last / first - 1.0
    out[tail.notna().sum() < 2] = np.nan
    return out.rename("period_return")


def _longest_streak(window: pd.DataFrame, *, positive: bool) -> pd.Series:
    """Longest run of consecutive strictly-signed days per column, vectorized.

    NaN/zero days break the run. Columns with no valid data are NaN; the rest
    are non-negative integer-valued floats. Loops over the (short) window rows
    doing whole-row numpy ops, so cost scales with the window length rather than
    the ticker count — no per-column Python loop.
    """
    arr = window.to_numpy(dtype=float)
    hit = arr > 0 if positive else arr < 0  # NaN compares False for both signs
    cur = np.zeros(arr.shape[1])
    best = np.zeros(arr.shape[1])
    for row in hit:
        cur = np.where(row, cur + 1.0, 0.0)
        best = np.maximum(best, cur)
    best[np.isnan(arr).all(axis=0)] = np.nan  # all-NaN column → NaN
    return pd.Series(best, index=window.columns, dtype=float)


def longest_up_streak(returns: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Per-ticker longest run of consecutive positive daily returns in the window.

    Slices ``returns`` to the trailing ``window_days`` and counts the longest
    streak of strictly-positive days per ticker (NaN/zero days break the run).
    Columns with no valid data in the window are NaN; the rest are non-negative
    integer-valued floats. Powers the "Longest bull run" superlative.
    """
    if returns.empty:
        return pd.Series(dtype=float)
    window = returns.tail(window_days)
    return _longest_streak(window, positive=True).rename("longest_up_streak")


def longest_down_streak(returns: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Per-ticker longest run of consecutive negative daily returns in the window.

    Mirror of ``longest_up_streak`` for strictly-negative days (NaN/zero days
    break the run). Columns with no valid data in the window are NaN; the rest
    are non-negative integer-valued floats. Powers the "Longest losing streak"
    superlative.
    """
    if returns.empty:
        return pd.Series(dtype=float)
    window = returns.tail(window_days)
    return _longest_streak(window, positive=False).rename("longest_down_streak")


def ma_spread(prices: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Per-ticker spread of the last price vs its trailing moving average.

    ``last_price / SMA(window_days) - 1`` (a percentage), where the SMA is the
    simple mean of the last ``window_days`` observations. A large positive value
    means the index trades well above its recent average ("most extended"); a
    large negative value means it trades well below ("most below trend").
    Columns with fewer than ``window_days`` valid observations are NaN.
    """
    if prices.empty:
        return pd.Series(dtype=float)
    window = prices.tail(window_days)
    sma = window.mean()
    last = window.ffill().iloc[-1]
    out = last / sma - 1.0
    out[window.notna().sum() < window_days] = np.nan
    return out.rename("ma_spread")


def trend_strength(prices: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Per-ticker trend quality over the trailing window.

    OLS slope of log price vs time, scaled by the fit's R² (slope·R²), so a
    clean, persistent uptrend ranks above a noisy one of the same average
    slope. Columns with fewer than three valid points are NaN; a perfectly
    flat series is 0. Powers the "Strongest trend" superlative.
    """
    if prices.empty:
        return pd.Series(dtype=float)
    window = prices.tail(window_days)
    out: dict[str, float] = {}
    for col in window.columns:
        series = window[col].dropna()
        if len(series) < 3:
            out[col] = np.nan
            continue
        y = np.log(series.to_numpy())
        if np.std(y) < 1e-12:  # flat (no trend) — guard fp noise, not just ==0
            out[col] = 0.0
            continue
        x = np.arange(len(y), dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        resid = y - (slope * x + intercept)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1.0 - np.sum(resid**2) / ss_tot if ss_tot > 0 else 0.0
        out[col] = float(slope * r2)
    return pd.Series(out, dtype=float).rename("trend_strength")


def return_autocorr(
    returns: pd.DataFrame, *, window_days: int = 21, lag: int = 1
) -> pd.Series:
    """Per-ticker lag-``lag`` autocorrelation of daily returns over the window.

    Pearson correlation between each ticker's daily returns and their own
    ``lag``-shifted copy over the trailing ``window_days``. A positive value
    means returns persist (trending); a negative value means they reverse
    (mean-reverting). Columns with fewer than ``lag + 3`` valid points — or
    zero return variance — are NaN. Powers the "Most trending / Most
    mean-reverting" superlatives.
    """
    if returns.empty:
        return pd.Series(dtype=float)
    window = returns.tail(window_days)
    arr = window.to_numpy(dtype=float)
    if arr.shape[0] <= lag:
        out = np.full(arr.shape[1], np.nan)
        return pd.Series(out, index=window.columns, dtype=float).rename(
            "return_autocorr"
        )
    # Vectorized lag-``lag`` Pearson autocorrelation across all columns at once.
    # This pipeline's series are gap-free once they start (prices are
    # forward-filled, so a late-launching ticker only carries *leading* NaNs),
    # so masking to pairs where both the value and its lagged copy are valid
    # correlates exactly the same consecutive points a per-column
    # ``dropna().autocorr(lag)`` would — no interior gaps to bridge.
    cur = arr[lag:]
    lagged = arr[:-lag]
    both = ~np.isnan(cur) & ~np.isnan(lagged)
    count = both.sum(axis=0)
    cur = np.where(both, cur, 0.0)
    lagged = np.where(both, lagged, 0.0)
    sum_c, sum_l = cur.sum(axis=0), lagged.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = (cur * lagged).sum(axis=0) - sum_c * sum_l / count
        var_c = (cur * cur).sum(axis=0) - sum_c * sum_c / count
        var_l = (lagged * lagged).sum(axis=0) - sum_l * sum_l / count
        corr = cov / np.sqrt(var_c * var_l)
    # Match the old guard: fewer than ``lag + 3`` valid points → NaN. With
    # contiguous validity, valid points = both-valid pairs + lag, so the
    # threshold on the pair count is a constant 3.
    corr[count < 3] = np.nan
    return pd.Series(corr, index=window.columns, dtype=float).rename("return_autocorr")


def macd_histogram(
    prices: pd.DataFrame, *, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.Series:
    """Per-ticker MACD histogram (latest value, normalized by price).

    MACD line = ``EMA(fast) - EMA(slow)``; signal = ``EMA(signal)`` of the MACD
    line; histogram = ``MACD - signal``, divided by the last price so the value
    is comparable across tickers of different price levels. Returns the latest
    value per ticker over the **full history** — a fixed-lookback oscillator
    (12/26/9) that is **independent of the window toggle**. Columns with fewer
    than ``slow`` valid observations are NaN. Powers the "Most extended up /
    down" superlatives.
    """
    if prices.empty:
        return pd.Series(dtype=float)
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = (macd_line - signal_line).ffill().iloc[-1]
    last = prices.ffill().iloc[-1]
    out = hist.divide(last.replace(0, np.nan))
    out[prices.notna().sum() < slow] = np.nan
    return out.rename("macd_histogram")


def win_rate(returns: pd.DataFrame, *, window_days: int = 21) -> pd.Series:
    """Per-ticker fraction of up days over the trailing window.

    ``mean(returns > 0)`` over the last ``window_days`` (strictly-positive days
    divided by the count of valid days; NaN days are excluded from both). In
    [0, 1]; columns with no valid data in the window are NaN. Powers the
    "Highest / Lowest win rate" superlatives.
    """
    if returns.empty:
        return pd.Series(dtype=float)
    window = returns.tail(window_days)
    valid = window.notna().sum()
    wins = (window > 0).sum()
    out = wins.divide(valid.replace(0, np.nan))
    return out.rename("win_rate")


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
