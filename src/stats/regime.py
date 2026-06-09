"""Regime-conditioned analytics for the v0.8.5 Platform Regime Analysis section.

Generalizes the benchmark-tail mask in ``regime_corr_matrix`` (``risk.py``) to an
explicit indicator **bucket**, and characterizes the catalog over only the days
in that bucket: a per-strategy risk/return frame and a (theme-scoped)
correlation matrix. Pure compute over the already-fetched cache — no BQL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import TRADING_DAYS_PER_YEAR
from .risk import corr_matrix


def regime_mask(indicator: pd.Series, low: float, high: float) -> pd.Series:
    """Boolean membership mask for a half-open ``[low, high)`` indicator bucket.

    NaN indicator values are excluded (``False``); ``±inf`` bounds give an open
    end. The result is indexed like ``indicator``.
    """
    if indicator is None or indicator.empty:
        return pd.Series(dtype=bool)
    return ((indicator >= low) & (indicator < high)).fillna(False)


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


def regime_correlation(
    returns: pd.DataFrame, mask: pd.Series, *, columns: list[str] | None = None
) -> pd.DataFrame:
    """Correlation matrix over the masked days, optionally scoped to ``columns``.

    ``columns`` (e.g. one theme's tickers) restricts the matrix to those columns
    present in ``returns`` — keeping a per-ticker matrix small and readable.
    ``mask`` is aligned to ``returns``'s index. Returns an empty frame when fewer
    than 2 columns remain or the bucket selects fewer than 2 days.
    """
    if returns.empty or mask is None or mask.empty:
        return pd.DataFrame()
    sub = returns
    if columns is not None:
        keep = [c for c in columns if c in returns.columns]
        if len(keep) < 2:
            return pd.DataFrame()
        sub = returns[keep]
    sub = sub.loc[mask.reindex(returns.index, fill_value=False)]
    if sub.shape[0] < 2 or sub.shape[1] < 2:
        return pd.DataFrame()
    return corr_matrix(sub)
