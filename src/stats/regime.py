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
