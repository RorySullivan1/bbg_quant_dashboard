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
    return prices.pct_change().dropna(how="all")


def drawdown_series(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices
    return prices.divide(prices.cummax()).subtract(1.0)


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


def max_drawdown(prices: pd.DataFrame, years: float) -> pd.Series:
    sliced = _slice_last_years(prices, years)
    if sliced.empty:
        return pd.Series(np.nan, index=prices.columns)
    running_max = sliced.cummax()
    drawdowns = sliced / running_max - 1.0
    return drawdowns.min()


def _benchmark_series(benchmark: pd.Series | pd.DataFrame | None) -> pd.Series | None:
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
    first_valid = prices.apply(pd.Series.first_valid_index)
    last_valid = prices.apply(pd.Series.last_valid_index)
    start = first_valid.max()
    end = last_valid.min()
    if pd.isna(start) or pd.isna(end) or start > end:
        return (None, None)
    return (start, end)
