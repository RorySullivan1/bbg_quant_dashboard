"""Shared low-level helpers for the stats package.

Dependency-free leaf module (only numpy/pandas): the price/return primitives
and slicing helpers that ``performance`` / ``risk`` / ``rolling`` build on.
Kept here — rather than in ``performance`` or ``risk`` — so those two can both
use ``max_drawdown`` without creating a circular import.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple daily percentage returns; rows that are entirely NaN are dropped."""
    return prices.pct_change().dropna(how="all")


def drawdown_series(prices: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker drawdown from the running peak, as a non-positive fraction."""
    if prices.empty:
        return prices
    return prices.divide(prices.cummax()).subtract(1.0)


def _slice_last_years(df: pd.DataFrame, years: float) -> pd.DataFrame:
    """The trailing ``years`` of rows, measured back from the last index label."""
    if df.empty:
        return df
    end = df.index.max()
    start = end - pd.Timedelta(days=int(years * 365.25))
    sliced = df.loc[df.index >= start]
    return sliced


def _first_valid_index(prices: pd.DataFrame) -> pd.Series:
    """Per-column first non-NaN index label (NaT for all-NaN columns), vectorized.

    ``notna().idxmax()`` gives the first ``True`` per column but returns the
    first index even for an all-NaN column, so mask those to NaT.
    """
    mask = prices.notna()
    return mask.idxmax().where(mask.any())


def _last_valid_index(prices: pd.DataFrame) -> pd.Series:
    """Per-column last non-NaN index label (NaT for all-NaN columns), vectorized."""
    mask = prices.notna()
    return mask[::-1].idxmax().where(mask.any())


def _has_enough_history(prices: pd.DataFrame, years: float) -> pd.Series:
    """Per-ticker: does the column have data covering the whole trailing window?"""
    if prices.empty:
        return pd.Series(dtype=bool)
    end = prices.index.max()
    required = end - pd.Timedelta(days=int(years * 365.25))
    first_valid = _first_valid_index(prices)
    return first_valid.notna() & (first_valid <= required)


def max_drawdown(prices: pd.DataFrame, years: float) -> pd.Series:
    """Largest peak-to-trough loss over the window, per ticker (non-positive)."""
    sliced = _slice_last_years(prices, years)
    if sliced.empty:
        return pd.Series(np.nan, index=prices.columns)
    running_max = sliced.cummax()
    drawdowns = sliced / running_max - 1.0
    return drawdowns.min()


def max_drawup(prices: pd.DataFrame, years: float) -> pd.Series:
    """Largest run-up off a trough over the window, per ticker (mirror of
    ``max_drawdown``).

    The max over the window of ``price / running-min - 1`` — the biggest gain
    from a running low to a subsequent high. Always non-negative; columns with
    no data in the window are NaN. Powers the "Largest drawup" superlative.
    """
    sliced = _slice_last_years(prices, years)
    if sliced.empty:
        return pd.Series(np.nan, index=prices.columns)
    running_min = sliced.cummin()
    drawups = sliced / running_min - 1.0
    return drawups.max()


def _benchmark_series(benchmark: pd.Series | pd.DataFrame | None) -> pd.Series | None:
    """Coerce a benchmark Series/1-column DataFrame to a Series, or None if empty."""
    if benchmark is None:
        return None
    bench = benchmark.iloc[:, 0] if isinstance(benchmark, pd.DataFrame) else benchmark
    return bench if not bench.empty else None


def zscore_cross_section(series: pd.Series) -> pd.Series:
    """Cross-sectional z-score of a per-ticker metric: (x - mean) / std."""
    std = series.std()
    if not std or np.isnan(std):
        return pd.Series(np.nan, index=series.index)
    return (series - series.mean()) / std


def asset_class_demeaned_zscore(series: pd.Series, asset_class: pd.Series) -> pd.Series:
    """Asset-class-demeaned cross-sectional z-score of a per-ticker metric.

    Subtract each asset class's own mean from ``series`` (grouping tickers by
    their ``asset_class``), then ``zscore_cross_section`` the demeaned values
    across the whole catalog. This makes a metric **cross-asset-neutral**: an
    index scores high for being extreme *relative to its asset-class cohort*,
    not because its whole class is structurally high/low. Used **only to rank**
    the cross-asset-neutral superlative cards (the card still shows the raw
    metric). ``asset_class`` is a per-ticker Series aligned to ``series.index``;
    tickers with no mapped class (NaN key) demean to NaN and drop out of the
    ranking. Returns an empty Series for empty input.
    """
    if series.empty:
        return pd.Series(dtype=float)
    classes = asset_class.reindex(series.index)
    group_mean = series.groupby(classes).transform("mean")
    return zscore_cross_section(series - group_mean)


def common_window_bounds(
    prices: pd.DataFrame,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Overlap window across all columns of ``prices``.

    Returns ``(start, end)`` where ``start`` is the latest per-column
    first-valid date ("highest min date") and ``end`` is the earliest
    per-column last-valid date ("lowest common max date") — i.e. the span
    over which every column has data. Returns ``(None, None)`` if there's
    no data or no overlap (``start > end``).
    """
    if prices.empty or prices.shape[1] == 0:
        return (None, None)
    start = _first_valid_index(prices).max()
    end = _last_valid_index(prices).min()
    if pd.isna(start) or pd.isna(end) or start > end:
        return (None, None)
    return (start, end)


def active_columns(prices: pd.DataFrame, *, window_days: int = 21) -> list[str]:
    """Columns whose price actually *moved* over the trailing ``window_days``.

    Keeps a column only when its last ``window_days`` rows carry at least two
    distinct non-NaN values (i.e. the series isn't empty or flat). This drops
    indices with no recent performance — delisted/stale series, including ones
    BQL ``fill="prev"`` carried forward as a flat line, and all-NaN columns.
    Returns the kept column names in their original order.
    """
    if prices.empty or prices.shape[1] == 0:
        return []
    tail = prices.tail(window_days)
    # Vectorized over columns (no per-column Python loop): at least two non-NaN
    # values AND at least two distinct ones. ``nunique() > 1`` already implies
    # ``notna().sum() >= 2``, but both are kept to mirror the original predicate.
    keep = (tail.notna().sum() >= 2) & (tail.nunique() > 1)
    return [col for col in prices.columns if bool(keep[col])]
