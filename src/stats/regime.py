"""Regime-conditioned analytics for the Platform Regime Analysis section.

Generalizes the benchmark-tail mask in ``regime_corr_matrix`` (``risk.py``) to an
explicit indicator **bucket**, and characterizes the catalog over only the days
in that bucket as a per-strategy risk/return frame. The bucket is either a fixed
indicator level (Volatility) or a *tercile* of a live-computed indicator series
(Trend autocorrelation / Rate level / Risk Δ) — see ``tercile_bounds``. Pure
compute over the already-fetched cache — no BQL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import TRADING_DAYS_PER_YEAR
from ._common import pairwise_cov

_INF = float("inf")


def regime_mask(indicator: pd.Series, low: float, high: float) -> pd.Series:
    """Boolean membership mask for a half-open ``[low, high)`` indicator bucket.

    NaN indicator values are excluded (``False``); ``±inf`` bounds give an open
    end. The result is indexed like ``indicator``.
    """
    if indicator is None or indicator.empty:
        return pd.Series(dtype=bool)
    return ((indicator >= low) & (indicator < high)).fillna(False)


def rolling_autocorr(series: pd.Series, *, window: int = 21, lag: int = 1) -> pd.Series:
    """Rolling lag-``lag`` autocorrelation of a return series over ``window``.

    A per-day series (indexed like ``series``) of the Pearson correlation between
    the trailing ``window`` returns and their own ``lag``-shifted copy: positive
    = returns persist (trending), negative = they reverse (mean-reverting). The
    leading ``window``-sized warmup and any zero-variance window are NaN. Mirrors
    the windowed scalar ``return_autocorr`` (``performance.py``) but as a series,
    so its terciles can define a per-day Trend regime.
    """
    if series is None or series.empty:
        return pd.Series(dtype=float)
    s = series.astype(float)
    return s.rolling(window).corr(s.shift(lag))


def tercile_bounds(series: pd.Series, which: str) -> tuple[float, float]:
    """``(low, high)`` half-open bounds for the low / middle / high third.

    Splits ``series`` at its 1/3 and 2/3 quantiles: ``"low"`` →
    ``(-inf, q⅓)``, ``"mid"`` → ``(q⅓, q⅔)``, ``"high"`` → ``(q⅔, +inf)``. NaNs
    are ignored. A degenerate series (empty / all-NaN / no spread between the
    quantiles) returns ``(-inf, +inf)`` so the bucket selects every day rather
    than nothing. The bounds feed straight into :func:`regime_mask`.
    """
    clean = series.dropna() if series is not None else pd.Series(dtype=float)
    if clean.empty:
        return (-_INF, _INF)
    q1, q2 = clean.quantile(1 / 3), clean.quantile(2 / 3)
    if not np.isfinite(q1) or not np.isfinite(q2) or q1 >= q2:
        return (-_INF, _INF)
    if which == "low":
        return (-_INF, float(q1))
    if which == "high":
        return (float(q2), _INF)
    return (float(q1), float(q2))


def regime_risk_return(returns: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    """Per-ticker annualized vol / return / Sharpe over only the masked days.

    Columns ``vol`` / ``ret`` / ``sharpe`` indexed by ticker. Because regime days
    are **non-contiguous**, the return is the *mean-based* annualization
    (mean daily return × 252), not a CAGR; ``vol`` is std × √252;
    ``sharpe = ret / vol`` (risk-free 0). ``mask`` is aligned to ``returns``'s
    index. Returns an empty frame (with the columns) when the bucket selects
    fewer than 2 days.
    """
    cols = ["vol", "ret", "sharpe"]
    if returns.empty or mask is None or mask.empty:
        return pd.DataFrame(columns=cols)
    sub = returns.loc[mask.reindex(returns.index, fill_value=False)]
    if sub.shape[0] < 2:
        return pd.DataFrame(columns=cols)
    vol = sub.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    ret = sub.mean() * TRADING_DAYS_PER_YEAR
    sharpe = ret.divide(vol.replace(0, np.nan))
    return pd.DataFrame({"vol": vol, "ret": ret, "sharpe": sharpe})


def _masked(frame: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    """``frame``'s rows where ``mask`` is True, aligned to ``frame``'s index."""
    return frame.loc[mask.reindex(frame.index, fill_value=False)]


def masked_beta(returns: pd.DataFrame, factor: pd.Series, mask: pd.Series) -> pd.Series:
    """Per-ticker beta to ``factor`` over only the masked days.

    The regime twin of `risk.ann_beta`: same cov/var on daily returns, same
    pairwise-complete treatment through the shared `pairwise_cov`, taking a
    day **mask** where `ann_beta` takes a number of years. Not a rolling beta —
    regime days are non-contiguous, so there is no window to roll over; the
    whole masked sample is the estimate.

    NaN for every ticker when the factor has no variance over those days, or
    when the bucket selects fewer than two.
    """
    if returns.empty or factor is None or factor.empty:
        return pd.Series(np.nan, index=returns.columns)
    sub = _masked(returns, mask)
    leg = factor.reindex(sub.index)
    if sub.shape[0] < 2:
        return pd.Series(np.nan, index=returns.columns)
    var = leg.var()
    if not var or np.isnan(var):
        return pd.Series(np.nan, index=returns.columns)
    cov = pairwise_cov(sub.to_numpy(dtype=float), leg.to_numpy(dtype=float))
    return pd.Series(cov / var, index=returns.columns)


def regime_metric(returns: pd.DataFrame, mask: pd.Series, metric: str) -> pd.Series:
    """Per-ticker ``metric`` over only the masked days (#331 decision 10).

    Extends `regime_risk_return`'s treatment rather than repeating it: that
    function's mean-based annualization is the numerator for every ratio here,
    because regime days are **non-contiguous** and a CAGR over them would claim
    a compounding that never happened.

    - ``return`` — the annualized mean (`regime_risk_return`'s ``ret``).
    - ``sharpe`` — its ``sharpe``, i.e. ret ÷ annualized std.
    - ``sortino`` — ret ÷ annualized downside deviation, the RMS of the
      sub-zero masked returns, mirroring `risk.downside_deviation`.
    - ``calmar`` — ret ÷ the max drawdown of the masked returns **compounded as
      if contiguous**. A drawdown needs an ordered path and the regime supplies
      only a set of days, so the days are strung together in date order and the
      worst peak-to-trough of that synthetic path is used. It is a real number
      about the regime, not about any tradeable series; the chart's hover says
      *over regime days* for exactly this reason.

    Raises `ValueError` on an unknown metric, like `latest_rolling_metric`, so
    the two share one vocabulary. Empty Series when the bucket selects fewer
    than two days.
    """
    known = ("return", "sharpe", "sortino", "calmar")
    if metric not in known:
        raise ValueError(f"unknown metric {metric!r}; choose from {sorted(known)}")
    if returns.empty or mask is None or mask.empty:
        return pd.Series(dtype=float)
    sub = _masked(returns, mask)
    if sub.shape[0] < 2:
        return pd.Series(dtype=float)
    ret = sub.mean() * TRADING_DAYS_PER_YEAR
    if metric == "return":
        return ret.rename(metric)
    if metric == "sharpe":
        vol = sub.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        return ret.divide(vol.replace(0, np.nan)).rename(metric)
    if metric == "sortino":
        downside = sub.where(sub < 0.0, 0.0)
        dd = np.sqrt((downside**2).mean()) * np.sqrt(TRADING_DAYS_PER_YEAR)
        return ret.divide(dd.replace(0, np.nan)).rename(metric)
    # The level the path opens at is a peak candidate, as in
    # `rolling._rolling_max_drawdown`: without it a path whose high is its
    # first day measures a shallower drawdown than it should.
    opening = pd.DataFrame([[1.0] * sub.shape[1]], columns=sub.columns)
    path = pd.concat([opening, (1.0 + sub.fillna(0.0)).cumprod()], ignore_index=True)
    drawdown = (path / path.cummax() - 1.0).min().abs().replace(0, np.nan)
    return ret.divide(drawdown).rename(metric)


def regime_factor_frame(
    returns: pd.DataFrame,
    mask: pd.Series,
    erp: pd.Series,
    tp: pd.Series,
    *,
    metric: str = "sharpe",
) -> pd.DataFrame:
    """The Platform Scatter's leaves: ``value`` / ``x`` / ``z`` per ticker.

    One sample for all three axes (#331 decision 10) — the regime's days inside
    the caller's window, which the caller has already narrowed ``returns`` to:

    - ``value`` — ``metric`` over those days, via `regime_metric`.
    - ``x`` — beta to the **term premium**, via `masked_beta`.
    - ``z`` — beta to the **equity risk premium**, likewise.

    The mask is applied here, to the leaves, before any grouping: a category's
    point is the mean of its members' *bucket* values, not the bucket value of
    their mean (#331 decision 18).

    An empty frame with the columns when the bucket selects fewer than two days.
    """
    cols = ["value", "x", "z"]
    if returns.empty or mask is None or mask.empty:
        return pd.DataFrame(columns=cols)
    if _masked(returns, mask).shape[0] < 2:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(
        {
            "value": regime_metric(returns, mask, metric),
            "x": masked_beta(returns, tp, mask),
            "z": masked_beta(returns, erp, mask),
        }
    )[cols]
