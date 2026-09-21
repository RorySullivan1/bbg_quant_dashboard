"""Shared low-level helpers for the stats package.

Dependency-free leaf module (only numpy/pandas): the price/return primitives
and slicing helpers that ``performance`` / ``risk`` / ``rolling`` build on.
Kept here — rather than in ``performance`` or ``risk`` — so those two can both
use ``max_drawdown`` without creating a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple daily percentage returns; rows that are entirely NaN are dropped."""
    return prices.pct_change().dropna(how="all")


def pairwise_cov(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Covariance of every column of ``a`` with the vector ``b``, pairwise-complete.

    One pass over the whole matrix rather than a `Series.cov` per column: each
    column uses only the rows where both it and ``b`` are non-NaN, which is what
    `Series.cov` does, and ddof=1 to match it. A column with fewer than two
    paired points is NaN rather than 0.0 — with no spread there is no
    covariance to report, and 0.0 would read as "uncorrelated".

    Shared by `risk.ann_beta` (over a window) and `regime.masked_beta` (over a
    regime's days). Both divide the result by the factor's own variance; the
    only difference between them is which rows they hand in.
    """
    mask = ~np.isnan(a) & ~np.isnan(b)[:, None]
    cnt = mask.sum(axis=0)
    safe = np.where(cnt > 0, cnt, 1)
    mean_a = np.where(mask, a, 0.0).sum(axis=0) / safe
    mean_b = np.where(mask, b[:, None], 0.0).sum(axis=0) / safe
    da = np.where(mask, a - mean_a, 0.0)
    db = np.where(mask, b[:, None] - mean_b, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = (da * db).sum(axis=0) / (cnt - 1)
    return np.where(cnt >= 2, cov, np.nan)


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
    no data in the window are NaN.
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
    a metric, never to display it — a caller shows the raw value. (It ranked
    the v0.8.x superlative cards, retired in v0.9.20 #291; the Platform sunburst
    is the live caller.) ``asset_class`` is a per-ticker Series aligned to
    ``series.index``;
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


@dataclass(frozen=True)
class BasketWindow:
    """The window a basket's analytics run over, and who decided it.

    `binding_start` / `binding_end` name the members that set each edge — the
    strategy with the shortest history, and the one that has gone stale. That
    is the whole reason this exists rather than `common_window_bounds` alone:
    with the date pickers retired (#341 dec. 12) the overlap is not a bound the
    user can argue with, so the app has to say which member is shortening the
    sample. Naming it turns "why is this only 2 years?" into one click.

    `start` / `end` are `None` when the basket is empty or its members share no
    dates; the names are `None` with them.
    """

    start: pd.Timestamp | None
    end: pd.Timestamp | None
    binding_start: str | None = None
    binding_end: str | None = None

    @property
    def years(self) -> float:
        """The span in years, for the readout. Zero when there is no window."""
        if self.start is None or self.end is None:
            return 0.0
        return (self.end - self.start).days / 365.25


def basket_window(prices: pd.DataFrame) -> BasketWindow:
    """`common_window_bounds`, plus the member at each edge.

    The window is the **intersection** of the members' histories: it starts at
    the *latest* first-valid date and ends at the *earliest* last-valid date,
    so every day in it is a day every member traded. (The brief called it a
    union; the computation is the intersection, which is what "only overlap
    counts" means.)

    Ties are broken by column order, which is basket order — with two members
    starting on the same date, the one the user added first is named. Either is
    correct and the choice only has to be stable.
    """
    start, end = common_window_bounds(prices)
    if start is None or end is None:
        return BasketWindow(None, None)
    firsts = _first_valid_index(prices)
    lasts = _last_valid_index(prices)
    at_start = [str(c) for c in firsts.index[firsts == start]]
    at_end = [str(c) for c in lasts.index[lasts == end]]
    return BasketWindow(
        start=start,
        end=end,
        binding_start=at_start[0] if at_start else None,
        binding_end=at_end[0] if at_end else None,
    )


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
