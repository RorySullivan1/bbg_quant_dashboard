"""Factor / Platform-view stats.

Macro-factor return proxies built from the already-fetched price cache —
equity risk premium, term premium, trend, carry and a cross-asset volatility
blend — a thin factor-beta wrapper over ``risk.ann_beta``, and the per-ticker
frame backing the Platform Icicle. Everything here is a pure function over
prices: no BQL, no fetch. Every ticker a factor needs rides the single startup
request (`FACTOR_TICKERS` / `REGIME_TICKERS`), which is what keeps that true.

The five proxies are not built alike, and the difference is not arbitrary:

- **Equity risk / term premium** are short-rate *spreads* — an excess return,
  so a β against them reads as sensitivity to taking that risk.
- **Trend and carry** are indices in their own right, so the β is taken
  against their own returns.
- **Volatility** is neither. It is two *level* series on different scales,
  standardized and averaged — see `volatility_factor`.
"""

from __future__ import annotations

import pandas as pd

from ..config import (
    CARRY_TICKER,
    EQUITY_FACTOR_TICKER,
    LONG_TREASURY_TICKER,
    MOVE_TICKER,
    SHARPE_WINDOW,
    SHORT_RATE_TICKER,
    TREND_TICKER,
    VIX_TICKER,
    analytics_levels,
)
from ._common import daily_returns
from .risk import ann_beta
from .rolling import latest_rolling_metric


def _icicle_columns() -> list[str]:
    """The icicle frame's columns: each configured level, then ``value``.

    A function rather than a module constant so a reconfigured hierarchy is
    picked up without re-importing.
    """
    return [*analytics_levels(), "value"]


def _factor_spread(prices: pd.DataFrame, long_leg: str, short_leg: str) -> pd.Series:
    """Daily return of ``long_leg`` minus daily return of ``short_leg``.

    Returns an empty float Series when either leg is missing from ``prices`` so
    a partial/mock frame never raises.
    """
    if (
        prices.empty
        or long_leg not in prices.columns
        or short_leg not in prices.columns
    ):
        return pd.Series(dtype=float)
    rets = daily_returns(prices[[long_leg, short_leg]])
    return rets[long_leg] - rets[short_leg]


def equity_risk_premium(
    prices: pd.DataFrame,
    *,
    equity: str = EQUITY_FACTOR_TICKER,
    short_rate: str = SHORT_RATE_TICKER,
) -> pd.Series:
    """Daily equity-risk-premium factor return ≈ equity TR − short-rate TR."""
    return _factor_spread(prices, equity, short_rate).rename("equity_risk_premium")


def term_premium(
    prices: pd.DataFrame,
    *,
    long_bond: str = LONG_TREASURY_TICKER,
    short_rate: str = SHORT_RATE_TICKER,
) -> pd.Series:
    """Daily term-premium factor return ≈ long-Treasury TR − short-rate TR."""
    return _factor_spread(prices, long_bond, short_rate).rename("term_premium")


def trend_returns(prices: pd.DataFrame, *, trend: str = TREND_TICKER) -> pd.Series:
    """Daily return series of the cross-asset trend factor.

    Unlike the equity-risk / term premia (short-rate spreads), the trend factor
    β is taken vs the index's own returns, so this is a plain ``daily_returns``
    of the trend column. Returns an empty float Series when the column is
    missing so a partial/mock frame never raises.
    """
    if prices.empty or trend not in prices.columns:
        return pd.Series(dtype=float)
    return daily_returns(prices[[trend]])[trend].rename("trend")


def carry_returns(prices: pd.DataFrame, *, carry: str = CARRY_TICKER) -> pd.Series:
    """Daily return series of the cross-asset carry factor.

    `trend_returns`' sibling, and for the same reason: unlike the equity-risk
    and term premia — which are short-rate *spreads* — a carry β is taken
    against the index's own returns. Returns an empty float Series when the
    column is missing so a partial / mock frame never raises.
    """
    if prices.empty or carry not in prices.columns:
        return pd.Series(dtype=float)
    return daily_returns(prices[[carry]])[carry].rename("carry")


def _standardized_changes(prices: pd.DataFrame, ticker: str) -> pd.Series:
    """Daily **changes** in a volatility index's level, divided by their own
    standard deviation.

    Changes, not returns: VIX and MOVE are already quoted in volatility
    points, and a percentage change of a series that trades between 9 and 60
    is violently skewed — a move from 12 to 15 and one from 40 to 50 are the
    same 25% and nothing like the same event.

    Standardized over the **whole sample handed in**, not a rolling window.
    The factor exists to have a β taken against it over that same sample, so
    the scale is a constant that divides out of the β's units; what the
    division actually buys is the *relative weight* of the two legs, which a
    rolling scale would let drift. It does mean the series is not
    point-in-time and is not claimed to be — nothing trades it.
    """
    if prices.empty or ticker not in prices.columns:
        return pd.Series(dtype=float)
    changes = prices[ticker].astype(float).diff()
    scale = changes.std()
    if not scale or pd.isna(scale):
        return pd.Series(dtype=float)
    return changes.divide(scale)


def volatility_factor(
    prices: pd.DataFrame,
    *,
    equity_vol: str = VIX_TICKER,
    bond_vol: str = MOVE_TICKER,
) -> pd.Series:
    """The cross-asset volatility factor: VIX and MOVE, z-scored then averaged.

    **Z-scored first, then averaged** (#363 dec. 9). VIX runs around 15–30 and
    MOVE around 80–130, so the raw average of their daily changes is mostly
    MOVE — an equal-weight blend in name and a single-leg factor in fact.
    Dividing each by its own standard deviation first makes the two legs
    contribute equally, which is what "cross-asset" is supposed to mean here.

    **It degrades to one leg rather than to nothing.** If BQL cannot serve
    `MOVE Index` on the terminal the factor is VIX alone, and the `name` says
    which legs went into it so a caller can tell the reader. Only an empty
    Series means neither leg resolved.
    """
    legs = {
        equity_vol: _standardized_changes(prices, equity_vol),
        bond_vol: _standardized_changes(prices, bond_vol),
    }
    present = {name: leg for name, leg in legs.items() if not leg.empty}
    if not present:
        return pd.Series(dtype=float, name="volatility")
    blend = pd.concat(present.values(), axis=1).mean(axis=1, skipna=True)
    # The name carries which legs are in it, so a chart drawing a degraded
    # factor can say so rather than quietly labelling it "Volatility".
    return blend.rename("volatility:" + "+".join(sorted(present)))


def factor_beta(
    returns: pd.DataFrame, factor_returns: pd.Series, years: float
) -> pd.Series:
    """Beta of each strategy's returns to a factor-return series over ``years``.

    Thin wrapper over ``ann_beta`` — the "benchmark" is a daily factor-return
    series (e.g. from ``equity_risk_premium`` / ``term_premium``) rather than a
    price series, which ``ann_beta`` handles directly (cov/var on daily returns).
    """
    return ann_beta(returns, factor_returns, years)


def factor_beta_panel(
    returns: pd.DataFrame,
    factors: dict[str, pd.Series],
    years: float,
) -> pd.DataFrame:
    """Every ticker's β to every factor: rows tickers, columns factor names.

    The cross-section a percentile needs. Computed for the **whole catalog**
    in one pass per factor rather than per strategy, because the expensive
    part is the covariance over `returns`' columns and it is the same work
    whichever ticker is being read (#363's risk note: measure once per
    window, cache, and the per-pick cost is a lookup).

    A factor that does not resolve — an empty Series, a missing leg — is an
    all-NaN **column**, not a missing one, so the shape does not depend on
    what the feed served and a caller draws a missing spoke rather than a
    different chart.
    """
    if returns.empty:
        return pd.DataFrame(index=returns.columns, columns=list(factors), dtype=float)
    columns = {}
    for name, series in factors.items():
        if series is None or series.empty:
            columns[name] = pd.Series(float("nan"), index=returns.columns)
            continue
        columns[name] = factor_beta(returns, series, years)
    return pd.DataFrame(columns, index=returns.columns)


def cross_section_percentile(panel: pd.DataFrame, ticker: str) -> pd.Series:
    """Where `ticker` sits in each factor's cross-section, in `[0, 1]`.

    **The radial axis a five-β spiderweb needs.** The betas themselves are on
    wildly different scales — a carry β of 0.3 is large where an ERP β of 0.3
    is small — so a polygon drawn on the raw numbers is a shape with no
    meaning: it says only which factors happen to be quoted in bigger units.
    A percentile among the catalog's own betas to that factor is comparable
    across spokes by construction.

    `rank(pct=True)` over the non-NaN values, so a factor the panel could not
    measure stays NaN here too, and a ticker the panel does not hold gives an
    all-NaN Series rather than raising.
    """
    if panel.empty or ticker not in panel.index:
        return pd.Series(float("nan"), index=panel.columns, dtype=float)
    return panel.rank(pct=True, na_option="keep").loc[ticker]


def icicle_frame(
    prices: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    metric: str = "sharpe",
    window: int = SHARPE_WINDOW,
    returns: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per-ticker grouping levels + ``value`` for the Platform Icicle.

    One column per `config.ANALYTICS_LEVELS` entry (outermost grouping first)
    plus ``value`` = `latest_rolling_metric` — the **raw** metric over the
    window, not a z-score, so the cell's colour is the number the table beside
    it shows (#331 decision 2). A level the metadata does not carry comes back
    all-NA, which the renderer buckets as "Other", so a partial feed still
    draws. ``window`` is a trading-day count.

    Pass ``returns`` (e.g. a shared ``universe_rets``) to skip re-deriving
    `daily_returns` here; the result is identical either way.
    """
    columns = _icicle_columns()
    if prices.empty and returns is None:
        return pd.DataFrame(columns=columns)
    value = latest_rolling_metric(prices, metric=metric, window=window, returns=returns)
    frame = pd.DataFrame({"value": value})
    has_ticker = "ticker" in meta.columns
    for level in analytics_levels():
        if has_ticker and level in meta.columns:
            mapping = meta.set_index("ticker")[level]
            frame[level] = frame.index.map(mapping)
        else:
            frame[level] = pd.NA
    return frame[columns]
