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
from .performance import ann_sharpe, ann_volatility
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

_CALENDAR_KINDS = ("absolute", "outperformance", "vol_adjusted", "beta", "correlation")

# Per-kind trailing summary columns (rendered after Jan…Dec), in display order.
# Each kind surfaces the calendar-year aggregates that make sense for its month
# cells; see `calendar_return_table` for how each column is computed.
#   absolute        — annual return / vol / Sharpe of the strategy.
#   outperformance  — strategy & benchmark annual return, their difference, and
#                     both annual Sharpes.
#   vol_adjusted    — annual Sharpe only (the annual return/vol analogue of the
#                     monthly return÷vol cells).
#   beta / corr     — the single annual beta / correlation to the benchmark.
_CALENDAR_SUMMARY_COLS_BY_KIND: dict[str, tuple[str, ...]] = {
    "absolute": ("Return", "Vol", "Sharpe"),
    "outperformance": ("Return", "Bench", "Excess", "Sharpe", "Bench Sharpe"),
    "vol_adjusted": ("Sharpe",),
    "beta": ("Beta",),
    "correlation": ("Correlation",),
}


def calendar_summary_columns(kind: str) -> tuple[str, ...]:
    """The trailing summary column names for a calendar `kind` (after Jan…Dec)."""
    if kind not in _CALENDAR_SUMMARY_COLS_BY_KIND:
        raise ValueError(f"unknown kind: {kind!r}")
    return _CALENDAR_SUMMARY_COLS_BY_KIND[kind]


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


def _annual_vol(prices: pd.Series) -> pd.Series:
    """Annualized volatility per calendar year, reusing ``ann_volatility``."""
    if prices.empty:
        return pd.Series(dtype=float)
    frame = prices.to_frame("strategy")
    out: dict[int, float] = {}
    for year, grp in frame.groupby(frame.index.year):
        # years=100 ≫ the one-year slice, so the whole calendar year is used.
        vol = ann_volatility(daily_returns(grp), years=100.0)
        out[int(year)] = float(vol.get("strategy", np.nan))
    return pd.Series(out, dtype=float)


def _beta(s: np.ndarray, b: np.ndarray) -> float:
    """OLS beta of ``s`` on ``b`` (cov / var of the benchmark)."""
    var = float(np.var(b))
    return float(np.cov(s, b, ddof=0)[0, 1] / var) if var > 0 else np.nan


def _corr(s: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation of ``s`` and ``b`` (NaN if either is constant)."""
    if np.std(s) == 0 or np.std(b) == 0:
        return np.nan
    return float(np.corrcoef(s, b)[0, 1])


def _pairwise_daily(prices: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """Aligned daily returns of ``prices`` (``s``) and ``benchmark`` (``b``)."""
    if prices is None or prices.empty or benchmark is None or benchmark.empty:
        return pd.DataFrame(columns=["s", "b"], dtype=float)
    s = daily_returns(prices.to_frame("s"))["s"]
    b = daily_returns(benchmark.to_frame("b"))["b"]
    return pd.concat([s, b], axis=1).dropna()


def _within_month_pairwise(prices, benchmark, fn, *, min_obs: int = 2) -> pd.Series:
    """Apply ``fn(strat_daily, bench_daily)`` within each calendar month.

    Returns a month-end-indexed Series; a month with fewer than ``min_obs``
    aligned daily pairs is NaN.
    """
    pair = _pairwise_daily(prices, benchmark)
    if pair.empty:
        return pd.Series(dtype=float)
    out: dict[pd.Timestamp, float] = {}
    for period, grp in pair.groupby(pair.index.to_period("M")):
        ts = period.to_timestamp(how="end").normalize()
        out[ts] = (
            fn(grp["s"].to_numpy(), grp["b"].to_numpy())
            if len(grp) >= min_obs
            else np.nan
        )
    return pd.Series(out, dtype=float)


def _annual_pairwise(prices, benchmark, fn, *, min_obs: int = 2) -> pd.Series:
    """Apply ``fn`` over each calendar year's aligned daily pairs (year-indexed)."""
    pair = _pairwise_daily(prices, benchmark)
    if pair.empty:
        return pd.Series(dtype=float)
    out: dict[int, float] = {}
    for year, grp in pair.groupby(pair.index.year):
        out[int(year)] = (
            fn(grp["s"].to_numpy(), grp["b"].to_numpy())
            if len(grp) >= min_obs
            else np.nan
        )
    return pd.Series(out, dtype=float)


def monthly_beta(prices: pd.Series, benchmark: pd.Series) -> pd.Series:
    """Within-month OLS beta of the strategy to the benchmark (month-end index)."""
    return _within_month_pairwise(prices, benchmark, _beta)


def monthly_correlation(prices: pd.Series, benchmark: pd.Series) -> pd.Series:
    """Within-month correlation of the strategy to the benchmark (month-end index)."""
    return _within_month_pairwise(prices, benchmark, _corr)


def calendar_return_table(
    prices: pd.Series,
    *,
    kind: str = "absolute",
    benchmark: pd.Series | None = None,
) -> pd.DataFrame:
    """A single strategy's year×month return calendar plus kind-specific summary
    columns.

    ``kind`` selects the month-cell transform *and* the trailing summary columns
    (see `_CALENDAR_SUMMARY_COLS_BY_KIND`):

    - ``"absolute"`` — compounded monthly return; summary ``Return`` / ``Vol`` /
      ``Sharpe`` (annual return, annualized vol, annualized Sharpe).
    - ``"outperformance"`` — strategy minus benchmark monthly return; summary
      ``Return`` / ``Bench`` / ``Excess`` (annual strategy & benchmark returns and
      their difference) plus ``Sharpe`` / ``Bench Sharpe``. Needs ``benchmark``.
    - ``"vol_adjusted"`` — monthly return ÷ within-month realized vol; summary
      ``Sharpe`` only (the annual return/vol analogue of the cells).
    - ``"beta"`` / ``"correlation"`` — the strategy's within-month OLS beta /
      correlation to the benchmark; summary is the single annual ``Beta`` /
      ``Correlation``. Both need ``benchmark``.

    All annual aggregates are per calendar year, computed from the same data the
    month cells use, so each kind's summary reconciles with its grid.
    """
    if kind not in _CALENDAR_KINDS:
        raise ValueError(f"unknown kind: {kind!r}")
    cols = [*_MONTH_COLS, *_CALENDAR_SUMMARY_COLS_BY_KIND[kind]]
    if prices is None or prices.empty:
        return pd.DataFrame(columns=cols)
    needs_benchmark = kind in ("outperformance", "beta", "correlation")
    if needs_benchmark and (benchmark is None or benchmark.empty):
        return pd.DataFrame(columns=cols)

    strat = prices.to_frame("strategy")
    m_strat = monthly_returns(strat)["strategy"]

    if kind == "absolute":
        cells = m_strat
        summary = {
            "Return": _annual_compound(m_strat),
            "Vol": _annual_vol(prices),
            "Sharpe": _annual_sharpe(prices),
        }
    elif kind == "outperformance":
        m_bench = monthly_returns(benchmark.to_frame("bench"))["bench"]
        cells = m_strat.sub(m_bench.reindex(m_strat.index))
        strat_ret = _annual_compound(m_strat)
        bench_ret = _annual_compound(m_bench)
        summary = {
            "Return": strat_ret,
            "Bench": bench_ret,
            "Excess": strat_ret.sub(bench_ret),
            "Sharpe": _annual_sharpe(prices),
            "Bench Sharpe": _annual_sharpe(benchmark),
        }
    elif kind in ("beta", "correlation"):
        fn = _beta if kind == "beta" else _corr
        cells = _within_month_pairwise(prices, benchmark, fn)
        label = "Beta" if kind == "beta" else "Correlation"
        summary = {label: _annual_pairwise(prices, benchmark, fn)}
    else:  # vol_adjusted
        rvol = monthly_realized_vol(daily_returns(strat))["strategy"]
        cells = m_strat.divide(rvol.reindex(m_strat.index).replace(0, np.nan))
        summary = {"Sharpe": _annual_sharpe(prices)}

    table = _pivot_year_month(cells)
    for name, series in summary.items():
        table[name] = series
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


class PolyFit(NamedTuple):
    """Result of a least-squares polynomial fit ``y = Σ coeffs[i]·x**(deg-i)``.

    `coeffs` are highest-order first (NumPy ``polyfit`` order). For the default
    quadratic, `convexity` is the leading ``x²`` coefficient — positive bends the
    curve into a smile (convex payoff), negative into a frown (concave) — and
    `slope` is the linear term (the central sensitivity, ≈ β at x = 0).
    """

    coeffs: tuple[float, ...]
    slope: float
    convexity: float
    r_squared: float


def poly_fit(x, y, degree: int = 2) -> PolyFit:
    """Least-squares polynomial fit of ``y`` on ``x`` (default quadratic).

    Inputs may be array-likes or pandas Series; non-finite pairs are dropped.
    Fewer than ``degree + 1`` finite points, or a degenerate (zero-variance)
    ``x``, yield an all-NaN fit. `slope` is the linear coefficient and
    `convexity` the quadratic one (NaN when `degree` is too low to define them).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if x.size < degree + 1 or np.std(x) < 1e-12:
        return PolyFit((np.nan,) * (degree + 1), np.nan, np.nan, np.nan)
    coeffs = np.polyfit(x, y, degree)
    resid = y - np.polyval(coeffs, x)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid**2)) / ss_tot if ss_tot > 0 else 0.0
    # Index from the low-order end so the readouts are degree-agnostic:
    # coeffs[-2] is the linear term, coeffs[-3] the quadratic.
    slope = float(coeffs[-2]) if degree >= 1 else float("nan")
    convexity = float(coeffs[-3]) if degree >= 2 else float("nan")
    return PolyFit(tuple(float(c) for c in coeffs), slope, convexity, float(r2))


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
