"""Calendar / resampled-return helpers for the Single-Strategy tab (v0.9.0).

Monthly & weekly return resampling, a year×month calendar return matrix
(absolute / outperformance / vol-adjusted), an OLS fit for the weekly-vs-
benchmark scatter line, and a strategy's per-month correlation to a factor.
All built on the daily primitives already in this package — no new runtime deps.

Resampling uses pandas **offset objects** (``MonthEnd`` / Friday-anchored
``Week``) rather than the string aliases ``"ME"`` / ``"W-FRI"``: those alias
spellings only exist on pandas ≥ 2.2 and raise ``ValueError: Invalid frequency``
on the older pandas the BQuant runtime can ship, whereas the offset objects bin
identically across every supported pandas version.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd

from ._common import daily_returns
from .performance import ann_sharpe
from .rolling import rolling_correlation

# Version-agnostic resample rules (see module docstring): month-end and
# week-ending-Friday, equivalent to the "ME" / "W-FRI" aliases but valid on
# pandas < 2.2 too.
_MONTH_END = pd.offsets.MonthEnd()
_WEEK_FRI = pd.offsets.Week(weekday=4)

_MONTH_COLS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

_CALENDAR_KINDS = ("absolute", "outperformance", "vol_adjusted")


def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Month-end compounded returns from daily prices.

    Daily returns are compounded within each calendar month; a month with no
    valid observations is NaN (``min_count=1``), not a spurious 0.
    """
    if prices.empty:
        return prices
    rets = daily_returns(prices)
    if rets.empty:
        return rets
    return rets.add(1.0).resample(_MONTH_END).prod(min_count=1).sub(1.0)


def weekly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Week-end (Friday) compounded returns from daily prices."""
    if prices.empty:
        return prices
    rets = daily_returns(prices)
    if rets.empty:
        return rets
    return rets.add(1.0).resample(_WEEK_FRI).prod(min_count=1).sub(1.0)


def monthly_realized_vol(returns: pd.DataFrame) -> pd.DataFrame:
    """Within-month standard deviation of daily returns (not annualized).

    The denominator for the vol-adjusted calendar cells, kept at monthly scale
    so the ratio against ``monthly_returns`` is unitless.
    """
    if returns.empty:
        return returns
    return returns.resample(_MONTH_END).std()


def _pivot_year_month(monthly: pd.Series) -> pd.DataFrame:
    """Reshape a month-end-indexed Series into a year×(Jan…Dec) matrix."""
    if monthly.empty:
        return pd.DataFrame(columns=_MONTH_COLS)
    idx = monthly.index
    frame = pd.DataFrame(
        {"year": idx.year, "month": idx.month, "value": monthly.to_numpy()}
    )
    wide = frame.pivot(index="year", columns="month", values="value")
    wide = wide.reindex(columns=range(1, 13))
    wide.columns = _MONTH_COLS
    wide.index.name = None
    return wide


def _annual_compound(monthly: pd.Series) -> pd.Series:
    """Compounded annual return per calendar year from monthly returns."""
    if monthly.empty:
        return pd.Series(dtype=float)
    return monthly.add(1.0).groupby(monthly.index.year).prod(min_count=1).sub(1.0)


def _annual_sharpe(prices: pd.Series) -> pd.Series:
    """Annualized Sharpe per calendar year, reusing ``ann_sharpe`` on each slice."""
    if prices.empty:
        return pd.Series(dtype=float)
    frame = prices.to_frame("strategy")
    out: dict[int, float] = {}
    for year, grp in frame.groupby(frame.index.year):
        # years=100 ≫ the one-year slice, so the whole calendar year is used.
        sharpe = ann_sharpe(daily_returns(grp), grp, years=100.0)
        out[int(year)] = float(sharpe.get("strategy", np.nan))
    return pd.Series(out, dtype=float)


def calendar_return_table(
    prices: pd.Series,
    *,
    kind: str = "absolute",
    benchmark: pd.Series | None = None,
) -> pd.DataFrame:
    """A single strategy's year×month return calendar plus Year + Sharpe columns.

    ``kind`` selects the month-cell transform:

    - ``"absolute"`` — the strategy's compounded monthly return.
    - ``"outperformance"`` — strategy minus benchmark monthly return (needs
      ``benchmark``; returns an empty table if it is missing).
    - ``"vol_adjusted"`` — monthly return ÷ within-month realized vol.

    The ``Year`` column is the compounded annual return (annual outperformance
    for ``"outperformance"``); ``Sharpe`` is always the strategy's annualized
    Sharpe for the calendar year, so it stays comparable across kinds.
    """
    if kind not in _CALENDAR_KINDS:
        raise ValueError(f"unknown kind: {kind!r}")
    cols = [*_MONTH_COLS, "Year", "Sharpe"]
    if prices is None or prices.empty:
        return pd.DataFrame(columns=cols)
    if kind == "outperformance" and (benchmark is None or benchmark.empty):
        return pd.DataFrame(columns=cols)

    strat = prices.to_frame("strategy")
    m_strat = monthly_returns(strat)["strategy"]

    if kind == "absolute":
        cells = m_strat
        year_col = _annual_compound(m_strat)
    elif kind == "outperformance":
        m_bench = monthly_returns(benchmark.to_frame("bench"))["bench"]
        cells = m_strat.sub(m_bench.reindex(m_strat.index))
        year_col = _annual_compound(m_strat).sub(_annual_compound(m_bench))
    else:  # vol_adjusted
        rvol = monthly_realized_vol(daily_returns(strat))["strategy"]
        cells = m_strat.divide(rvol.reindex(m_strat.index).replace(0, np.nan))
        year_col = _annual_compound(m_strat)

    table = _pivot_year_month(cells)
    table["Year"] = year_col
    table["Sharpe"] = _annual_sharpe(prices)
    return table.reindex(columns=cols)


class OLSFit(NamedTuple):
    """Result of a simple ``y = intercept + slope·x`` ordinary-least-squares fit."""

    slope: float
    intercept: float
    r_squared: float


def ols_fit(x, y) -> OLSFit:
    """Slope / intercept / R² of an OLS line through paired ``(x, y)`` points.

    Inputs may be array-likes or pandas Series; non-finite pairs are dropped.
    Fewer than two finite points, or a degenerate (zero-variance) ``x``, yield
    an all-NaN fit.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if x.size < 2 or np.std(x) < 1e-12:
        return OLSFit(np.nan, np.nan, np.nan)
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid**2)) / ss_tot if ss_tot > 0 else 0.0
    return OLSFit(float(slope), float(intercept), float(r2))


def monthly_factor_correlations(
    prices: pd.Series,
    factor_returns: pd.Series,
    *,
    window: int = 63,
) -> pd.Series:
    """A strategy's trailing-window correlation to a factor, sampled month-end.

    Uses a trailing rolling window (default ~one quarter) for stability, then
    takes the last value in each month. Returns a month-end-indexed Series.
    """
    if prices is None or prices.empty or factor_returns is None or factor_returns.empty:
        return pd.Series(dtype=float)
    rets = daily_returns(prices.to_frame("strategy"))
    roll = rolling_correlation(rets, factor_returns, window=window)
    if roll.empty or "strategy" not in roll.columns:
        return pd.Series(dtype=float)
    return roll["strategy"].resample(_MONTH_END).last().rename("factor_corr")
