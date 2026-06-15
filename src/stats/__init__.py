"""Statistics package — performance, risk, and rolling metrics.

Split out of the former single ``src/stats.py`` (v0.6.0 Workstream G stretch)
into ``_common`` (price/return primitives) + ``performance`` / ``risk`` /
``rolling``. The public surface is flat and unchanged: every name a caller used
via ``from ..stats import X`` / ``stats.X`` is re-exported here, so consumers
(``layout/builder.py``, ``layout/charts.py``, ``commentary.py``, the tests) need
no edits.
"""

from __future__ import annotations

from ._common import (
    _benchmark_series,
    _has_enough_history,
    _slice_last_years,
    active_columns,
    asset_class_demeaned_zscore,
    common_window_bounds,
    daily_returns,
    drawdown_series,
    max_drawdown,
    max_drawup,
    zscore_cross_section,
)
from .calendar import (
    OLSFit,
    PolyFit,
    calendar_return_table,
    calendar_summary_columns,
    monthly_beta,
    monthly_correlation,
    monthly_factor_correlations,
    monthly_realized_vol,
    monthly_returns,
    ols_fit,
    poly_fit,
    weekly_returns,
)
from .factors import (
    equity_risk_premium,
    factor_beta,
    platform_sunburst_frame,
    term_premium,
    trend_returns,
)
from .performance import (
    ann_return,
    ann_sharpe,
    ann_volatility,
    cum_perf,
    excess_cum_return,
    longest_down_streak,
    longest_up_streak,
    ma_spread,
    macd_histogram,
    perf_table,
    period_return,
    return_autocorr,
    since_inception_perf,
    total_return,
    trend_strength,
    universe_perf,
    weekly_change,
    win_rate,
)
from .regime import (
    regime_mask,
    regime_risk_return,
    rolling_autocorr,
    tercile_bounds,
)
from .risk import (
    ann_beta,
    calmar_ratio,
    corr_matrix,
    downside_deviation,
    heatmap_corr_matrix,
    historical_var,
    jensen_alpha,
    quant_metrics_table,
    recovery_days,
    regime_corr_matrix,
    return_distribution_stats,
    return_skew,
    rsi,
    sortino_ratio,
    treynor_ratio,
)
from .rolling import (
    rolling_beta,
    rolling_correlation,
    rolling_metric_zscore,
    rolling_return,
    rolling_sharpe,
    rolling_sharpe_zscore,
    rolling_sortino,
    rolling_volatility,
    sharpe_zscore,
)

__all__ = [
    # _common
    "daily_returns",
    "drawdown_series",
    "max_drawdown",
    "max_drawup",
    "zscore_cross_section",
    "asset_class_demeaned_zscore",
    "common_window_bounds",
    "active_columns",
    "_slice_last_years",
    "_has_enough_history",
    "_benchmark_series",
    # performance
    "cum_perf",
    "total_return",
    "weekly_change",
    "period_return",
    "longest_up_streak",
    "longest_down_streak",
    "ma_spread",
    "trend_strength",
    "return_autocorr",
    "macd_histogram",
    "win_rate",
    "excess_cum_return",
    "ann_return",
    "ann_volatility",
    "ann_sharpe",
    "perf_table",
    "since_inception_perf",
    "universe_perf",
    # risk
    "corr_matrix",
    "regime_corr_matrix",
    "heatmap_corr_matrix",
    "return_distribution_stats",
    "return_skew",
    "recovery_days",
    "ann_beta",
    "calmar_ratio",
    "treynor_ratio",
    "jensen_alpha",
    "downside_deviation",
    "sortino_ratio",
    "historical_var",
    "rsi",
    "quant_metrics_table",
    # regime
    "regime_mask",
    "regime_risk_return",
    "rolling_autocorr",
    "tercile_bounds",
    # rolling
    "rolling_return",
    "rolling_volatility",
    "rolling_sharpe",
    "rolling_sortino",
    "rolling_metric_zscore",
    "sharpe_zscore",
    "rolling_sharpe_zscore",
    "rolling_correlation",
    "rolling_beta",
    # factors / platform
    "equity_risk_premium",
    "term_premium",
    "trend_returns",
    "factor_beta",
    "platform_sunburst_frame",
    # calendar
    "monthly_returns",
    "weekly_returns",
    "monthly_realized_vol",
    "calendar_return_table",
    "calendar_summary_columns",
    "monthly_beta",
    "monthly_correlation",
    "ols_fit",
    "OLSFit",
    "poly_fit",
    "PolyFit",
    "monthly_factor_correlations",
]
