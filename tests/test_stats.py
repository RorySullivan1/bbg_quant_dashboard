"""Unit tests for the pure functions in ``src.stats``.

These are the regression guard for the metric math: small fixed frames with
hand-computed expectations where possible, and mathematical identities (perfect
correlation, all-gain RSI, zero-vol Sharpe, …) where a closed form is cleaner
than a literal recomputation. Locking this behavior lets the remaining v0.6.0
refactor (the DashboardState extraction) proceed safely.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from src import stats
from src.config import (
    MONTH_WINDOW,
    TRADING_DAYS_PER_YEAR,
    WEEK_WINDOW,
)

# --- basics ----------------------------------------------------------------


def test_daily_returns_drops_leading_nan_row(tiny_prices):
    rets = stats.daily_returns(tiny_prices)
    # pct_change drops the first (all-NaN) row → one fewer row than prices.
    assert len(rets) == len(tiny_prices) - 1
    # AAA ramps +10% every step.
    np.testing.assert_allclose(rets["AAA Index"].to_numpy(), [0.1, 0.1, 0.1])


def test_cum_perf_is_percent_of_first_price(tiny_prices):
    cp = stats.cum_perf(tiny_prices)
    # Series is rebased to 100 at the first observation.
    np.testing.assert_allclose(cp["AAA Index"].to_numpy(), [100.0, 110.0, 121.0, 133.1])
    assert cp["BBB Index"].iloc[0] == pytest.approx(100.0)


def test_cum_perf_empty_passthrough():
    empty = pd.DataFrame()
    assert stats.cum_perf(empty).empty


def test_drawdown_series_peak_to_trough(tiny_prices):
    dd = stats.drawdown_series(tiny_prices)
    # AAA only rises → drawdown is flat zero.
    np.testing.assert_allclose(dd["AAA Index"].to_numpy(), [0.0, 0.0, 0.0, 0.0])
    # BBB: 120 peak → 90 trough = -25%, then a new high → back to 0.
    np.testing.assert_allclose(dd["BBB Index"].to_numpy(), [0.0, 0.0, -0.25, 0.0])


def test_max_drawdown_window(tiny_prices):
    md = stats.max_drawdown(tiny_prices, years=10)  # window covers all rows
    assert md["AAA Index"] == pytest.approx(0.0)
    assert md["BBB Index"] == pytest.approx(-0.25)


# --- annualized metrics ----------------------------------------------------


def test_ann_return_flat_series_is_zero(bdays):
    idx = bdays(300)
    prices = pd.DataFrame({"FLAT Index": np.full(len(idx), 100.0)}, index=idx)
    assert stats.ann_return(prices, years=10)["FLAT Index"] == pytest.approx(0.0)


def test_ann_return_matches_compound_formula(bdays):
    # Price doubles over the window → (last/first)^(1/span_years) - 1.
    idx = bdays(500)
    prices = pd.DataFrame({"AAA Index": np.linspace(100.0, 200.0, len(idx))}, index=idx)
    span_years = (idx.max() - idx.min()).days / 365.25
    expected = 2.0 ** (1.0 / span_years) - 1.0
    assert stats.ann_return(prices, years=10)["AAA Index"] == pytest.approx(expected)


def test_ann_volatility_zero_when_no_variation(bdays):
    idx = bdays(300)
    rets = pd.DataFrame({"FLAT Index": np.zeros(len(idx))}, index=idx)
    assert stats.ann_volatility(rets, years=10)["FLAT Index"] == pytest.approx(0.0)


def test_ann_volatility_annualizes_std(bdays):
    idx = bdays(260)
    # Alternating ±1% returns → known sample std, annualized by sqrt(252).
    vals = np.tile([0.01, -0.01], len(idx) // 2)
    rets = pd.DataFrame({"AAA Index": vals}, index=idx)
    expected = vals.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    assert stats.ann_volatility(rets, years=10)["AAA Index"] == pytest.approx(expected)


def test_ann_sharpe_is_return_over_vol(multiyear_prices):
    rets = stats.daily_returns(multiyear_prices)
    sharpe = stats.ann_sharpe(rets, multiyear_prices, years=1)
    ret = stats.ann_return(multiyear_prices, years=1)
    vol = stats.ann_volatility(rets, years=1)
    np.testing.assert_allclose(sharpe.to_numpy(), (ret / vol).to_numpy(), rtol=1e-9)


# --- correlation -----------------------------------------------------------


def test_corr_matrix_perfect_and_inverse(bdays):
    idx = bdays(50)
    base = np.linspace(-0.02, 0.02, len(idx))
    rets = pd.DataFrame(
        {"UP Index": base, "ALSO_UP Index": 2.0 * base, "DOWN Index": -base},
        index=idx,
    )
    cm = stats.corr_matrix(rets)
    assert cm.loc["UP Index", "ALSO_UP Index"] == pytest.approx(1.0)
    assert cm.loc["UP Index", "DOWN Index"] == pytest.approx(-1.0)
    np.testing.assert_allclose(np.diag(cm.to_numpy()), 1.0)


def test_regime_corr_matrix_appends_benchmark_and_conditions(multiyear_prices):
    rets = stats.daily_returns(multiyear_prices)
    bench = rets["AAA Index"].rename("SPX Index")
    rm = stats.regime_corr_matrix(rets, bench, pct=0.2, direction="down")
    # Benchmark is added as a row/column; self-correlation on the diagonal.
    assert "SPX Index" in rm.columns
    assert rm.shape[0] == rets.shape[1] + 1
    np.testing.assert_allclose(np.diag(rm.to_numpy()), 1.0)


def test_regime_corr_matrix_empty_when_pct_zero(multiyear_prices):
    rets = stats.daily_returns(multiyear_prices)
    bench = rets["AAA Index"].rename("SPX Index")
    assert stats.regime_corr_matrix(rets, bench, pct=0.0).empty


# --- risk / momentum -------------------------------------------------------


def test_historical_var_is_positive_loss_at_quantile(bdays):
    idx = bdays(200)
    rng = np.random.default_rng(1)
    vals = rng.normal(0.0, 0.01, size=len(idx))
    rets = pd.DataFrame({"AAA Index": vals}, index=idx)
    var = stats.historical_var(rets, years=10, confidence=0.95)["AAA Index"]
    # VaR = -(5th percentile of returns), reported as a positive magnitude.
    expected = -pd.Series(vals).quantile(0.05)
    assert var == pytest.approx(expected)
    assert var > 0


def test_rsi_all_gains_is_100(bdays):
    idx = bdays(60)
    prices = pd.DataFrame({"UP Index": np.linspace(100.0, 160.0, len(idx))}, index=idx)
    assert stats.rsi(prices, window=14)["UP Index"] == pytest.approx(100.0)


def test_rsi_all_losses_is_0(bdays):
    idx = bdays(60)
    prices = pd.DataFrame(
        {"DOWN Index": np.linspace(160.0, 100.0, len(idx))}, index=idx
    )
    assert stats.rsi(prices, window=14)["DOWN Index"] == pytest.approx(0.0)


def test_zscore_cross_section_known_values():
    z = stats.zscore_cross_section(pd.Series([1.0, 2.0, 3.0], index=["a", "b", "c"]))
    # mean 2, sample std 1 → (-1, 0, 1).
    np.testing.assert_allclose(z.to_numpy(), [-1.0, 0.0, 1.0])


def test_zscore_cross_section_constant_is_nan():
    z = stats.zscore_cross_section(pd.Series([5.0, 5.0, 5.0]))
    assert z.isna().all()


# --- composite tables ------------------------------------------------------


def test_quant_metrics_table_shape_and_consistency(multiyear_prices, benchmark):
    table = stats.quant_metrics_table(multiyear_prices, benchmark, years=1)
    assert list(table.columns) == [
        "Sharpe",
        "Sortino",
        "Calmar",
        "Beta",
        "Treynor",
        "Jensen",
        "VaR",
        "RSI",
    ]
    assert list(table.index) == list(multiyear_prices.columns)
    # The Sharpe column must agree with the standalone ann_sharpe.
    rets = stats.daily_returns(multiyear_prices)
    expected_sharpe = stats.ann_sharpe(rets, multiyear_prices, years=1)
    np.testing.assert_allclose(
        table["Sharpe"].to_numpy(), expected_sharpe.to_numpy(), rtol=1e-9
    )


def test_quant_metrics_table_empty_input_keeps_columns():
    table = stats.quant_metrics_table(pd.DataFrame(), pd.Series(dtype=float), years=1)
    assert table.empty
    assert "Sharpe" in table.columns


# --- overlap window --------------------------------------------------------


def test_common_window_bounds_ragged_overlap(bdays):
    idx = bdays(5)
    # AAA valid days 0..3, BBB valid days 1..4 → overlap is [day1, day3].
    a = [100.0, 101.0, 102.0, 103.0, np.nan]
    b = [np.nan, 200.0, 201.0, 202.0, 203.0]
    prices = pd.DataFrame({"AAA Index": a, "BBB Index": b}, index=idx)
    start, end = stats.common_window_bounds(prices)
    assert start == idx[1]
    assert end == idx[3]


def test_common_window_bounds_no_overlap_returns_none(bdays):
    idx = bdays(4)
    a = [100.0, 101.0, np.nan, np.nan]
    b = [np.nan, np.nan, 200.0, 201.0]
    prices = pd.DataFrame({"AAA Index": a, "BBB Index": b}, index=idx)
    assert stats.common_window_bounds(prices) == (None, None)


def test_common_window_bounds_empty_returns_none():
    assert stats.common_window_bounds(pd.DataFrame()) == (None, None)


# --- v0.6.9 Workstream D: precomputed-returns threading (equivalence) -------


def test_perf_table_returns_param_matches_internal(multiyear_prices):
    rets = stats.daily_returns(multiyear_prices)
    pd.testing.assert_frame_equal(
        stats.perf_table(multiyear_prices),
        stats.perf_table(multiyear_prices, returns=rets),
    )


def test_universe_perf_is_windows_only_no_since_inception(multiyear_prices):
    # v0.7.2: universe_perf returns only the 1Y/3Y/5Y windowed block (it threads
    # daily_returns once into perf_table); the Since-Inception block is dropped.
    up = stats.universe_perf(multiyear_prices)
    pd.testing.assert_frame_equal(up, stats.perf_table(multiyear_prices))
    assert "SI" not in up.columns.get_level_values(0)


def test_quant_metrics_table_returns_param_matches_internal(
    multiyear_prices, benchmark
):
    rets = stats.daily_returns(multiyear_prices)
    pd.testing.assert_frame_equal(
        stats.quant_metrics_table(multiyear_prices, benchmark, 1),
        stats.quant_metrics_table(multiyear_prices, benchmark, 1, returns=rets),
    )


# --- v0.7.0 Platform stats: rolling helpers / z-score / factors / treemap ---


def _factor_frame(idx) -> pd.DataFrame:
    """Seeded prices including the factor proxy tickers + one strategy."""
    rng = np.random.default_rng(11)
    specs = {
        "SPX Index": (0.0004, 0.011),
        "LUTLTRUU Index": (0.0002, 0.005),
        "LD12TRUU Index": (0.00005, 0.0005),
        "BSLXAT Index": (0.0001, 0.006),
        "AAA Index": (0.0003, 0.012),
    }
    data = {
        t: 100.0 * np.cumprod(1.0 + rng.normal(mu, sig, len(idx)))
        for t, (mu, sig) in specs.items()
    }
    return pd.DataFrame(data, index=idx)


def test_rolling_helpers_shape_and_warmup(multiyear_prices):
    rets = stats.daily_returns(multiyear_prices)
    for fn in (
        stats.rolling_return,
        stats.rolling_volatility,
        stats.rolling_sharpe,
        stats.rolling_sortino,
    ):
        out = fn(rets, window=63)
        assert out.shape == rets.shape
        # The first window-1 rows are an incomplete window → NaN.
        assert out.iloc[:62].isna().all().all()
        assert out.iloc[63:].notna().any().any()


def test_rolling_volatility_constant_return_is_zero(bdays):
    idx = bdays(300)
    # +1% every step → zero rolling volatility.
    prices = pd.DataFrame({"X Index": 100.0 * 1.01 ** np.arange(len(idx))}, index=idx)
    vol = stats.rolling_volatility(stats.daily_returns(prices), window=21)
    assert vol.dropna().abs().to_numpy().max() == pytest.approx(0.0, abs=1e-9)


def test_rolling_metric_zscore_matches_sharpe_zscore(multiyear_prices):
    rets = stats.daily_returns(multiyear_prices)
    generalized = stats.rolling_metric_zscore(
        multiyear_prices, metric="sharpe", window=63, zscore_window=126
    )
    special = stats.sharpe_zscore(rets, window=63, zscore_window=126)
    pd.testing.assert_series_equal(generalized, special, check_names=False)


def test_rolling_metric_zscore_dispatches_each_metric(multiyear_prices):
    for metric in ("sharpe", "sortino", "return", "vol"):
        z = stats.rolling_metric_zscore(
            multiyear_prices, metric=metric, window=63, zscore_window=126
        )
        assert list(z.index) == list(multiyear_prices.columns)
        assert z.name == f"{metric}_zscore"


def test_rolling_metric_zscore_unknown_metric_raises(multiyear_prices):
    with pytest.raises(ValueError):
        stats.rolling_metric_zscore(
            multiyear_prices, metric="bogus", window=21, zscore_window=63
        )


def test_rolling_metric_zscore_positive_for_recent_strength(bdays):
    idx = bdays(400)
    rng = np.random.default_rng(0)
    # Calm noisy history, then a steady low-vol positive run → positive z.
    rets = np.concatenate([rng.normal(0.0, 0.01, 320), np.full(80, 0.004)])
    prices = pd.DataFrame({"X Index": 100.0 * np.cumprod(1.0 + rets)}, index=idx)
    z = stats.rolling_metric_zscore(
        prices, metric="sharpe", window=21, zscore_window=252
    )
    assert z["X Index"] > 0


def test_equity_risk_premium_is_equity_minus_short(bdays):
    prices = _factor_frame(bdays(300))
    erp = stats.equity_risk_premium(prices)
    rets = stats.daily_returns(prices[["SPX Index", "LD12TRUU Index"]])
    expected = rets["SPX Index"] - rets["LD12TRUU Index"]
    pd.testing.assert_series_equal(erp, expected, check_names=False)
    assert erp.name == "equity_risk_premium"


def test_term_premium_is_long_minus_short(bdays):
    prices = _factor_frame(bdays(300))
    tp = stats.term_premium(prices)
    rets = stats.daily_returns(prices[["LUTLTRUU Index", "LD12TRUU Index"]])
    expected = rets["LUTLTRUU Index"] - rets["LD12TRUU Index"]
    pd.testing.assert_series_equal(tp, expected, check_names=False)
    assert tp.name == "term_premium"


def test_factor_builders_missing_columns_return_empty():
    prices = pd.DataFrame({"AAA Index": [100.0, 101.0, 102.0]})
    assert stats.equity_risk_premium(prices).empty
    assert stats.term_premium(prices).empty
    assert stats.trend_returns(prices).empty


def test_trend_returns_is_trend_column_pct_change(bdays):
    prices = _factor_frame(bdays(300))
    tr = stats.trend_returns(prices)
    expected = stats.daily_returns(prices[["BSLXAT Index"]])["BSLXAT Index"]
    pd.testing.assert_series_equal(tr, expected, check_names=False)
    assert tr.name == "trend"


def test_factor_beta_matches_ann_beta(bdays):
    prices = _factor_frame(bdays(400))
    rets = stats.daily_returns(prices[["AAA Index"]])
    erp = stats.equity_risk_premium(prices)
    pd.testing.assert_series_equal(
        stats.factor_beta(rets, erp, years=1),
        stats.ann_beta(rets, erp, years=1),
    )


def test_platform_sunburst_frame_columns_and_join(multiyear_prices):
    meta = pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "theme": ["Growth", "Credit", "Energy"],
        }
    )
    frame = stats.platform_sunburst_frame(multiyear_prices, meta)
    assert list(frame.columns) == ["asset_class", "theme", "z"]
    assert len(frame) == 3
    assert frame.loc["BBB Index", "asset_class"] == "Fixed Income"
    assert frame.loc["BBB Index", "theme"] == "Credit"
    assert frame["z"].notna().any()
    # Default: z(1W Sharpe, 1Y).
    expected = stats.rolling_metric_zscore(
        multiyear_prices, metric="sharpe", window=WEEK_WINDOW, zscore_window=252
    )
    pd.testing.assert_series_equal(
        frame["z"], expected.reindex(frame.index), check_names=False
    )


def test_platform_sunburst_frame_honors_metric_params(multiyear_prices):
    """z honors the selected metric/window/lookback."""
    meta = pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "theme": ["Growth", "Credit", "Energy"],
        }
    )
    frame = stats.platform_sunburst_frame(
        multiyear_prices,
        meta,
        metric="sortino",
        window=MONTH_WINDOW,
        lookback=TRADING_DAYS_PER_YEAR * 3,
    )
    expected = stats.rolling_metric_zscore(
        multiyear_prices,
        metric="sortino",
        window=MONTH_WINDOW,
        zscore_window=TRADING_DAYS_PER_YEAR * 3,
    )
    pd.testing.assert_series_equal(
        frame["z"], expected.reindex(frame.index), check_names=False
    )


def test_platform_sunburst_frame_empty_safe():
    meta = pd.DataFrame({"ticker": [], "asset_class": [], "theme": []})
    out = stats.platform_sunburst_frame(pd.DataFrame(), meta)
    assert list(out.columns) == ["asset_class", "theme", "z"]
    assert out.empty


# --- v0.8.0 superlative helpers: period_return / streak / trend -------------


def test_period_return_simple_cumulative(tiny_prices):
    # window covers the whole 4-row frame: AAA 100→133.1, BBB 100→150.
    pr = stats.period_return(tiny_prices, window_days=21)
    assert pr["AAA Index"] == pytest.approx(0.331)
    assert pr["BBB Index"] == pytest.approx(0.5)


def test_period_return_respects_window(tiny_prices):
    # window_days=2 → tail(3) rows [110, 121, 133.1] for AAA → 133.1/110 - 1.
    pr = stats.period_return(tiny_prices, window_days=2)
    assert pr["AAA Index"] == pytest.approx(133.1 / 110.0 - 1.0)


def test_period_return_empty_passthrough():
    assert stats.period_return(pd.DataFrame(), window_days=21).empty


def test_period_return_insufficient_history_is_nan(bdays):
    idx = bdays(3)
    # Only one valid observation in the window → NaN.
    prices = pd.DataFrame({"X Index": [np.nan, np.nan, 100.0]}, index=idx)
    assert np.isnan(stats.period_return(prices, window_days=21)["X Index"])


def test_longest_up_streak_counts_consecutive_gains(bdays):
    idx = bdays(6)
    rets = pd.DataFrame(
        {
            "UP Index": [0.01, 0.01, 0.01, 0.01, 0.01, 0.01],  # all up → 6
            "MIX Index": [0.01, 0.01, -0.01, 0.01, 0.01, 0.01],  # longest run → 3
            "DOWN Index": [-0.01, -0.01, -0.01, -0.01, -0.01, -0.01],  # never up → 0
        },
        index=idx,
    )
    streak = stats.longest_up_streak(rets, window_days=21)
    assert streak["UP Index"] == 6.0
    assert streak["MIX Index"] == 3.0
    assert streak["DOWN Index"] == 0.0


def test_longest_up_streak_respects_window(bdays):
    idx = bdays(6)
    # First three days up, then flat/down — a 3-day window sees no full streak.
    rets = pd.DataFrame({"X Index": [0.01, 0.01, 0.01, -0.01, 0.0, -0.01]}, index=idx)
    assert stats.longest_up_streak(rets, window_days=3)["X Index"] == 0.0


def test_longest_up_streak_all_nan_is_nan(bdays):
    idx = bdays(4)
    rets = pd.DataFrame({"X Index": [np.nan, np.nan, np.nan, np.nan]}, index=idx)
    assert np.isnan(stats.longest_up_streak(rets, window_days=21)["X Index"])


def test_trend_strength_clean_beats_noisy(bdays):
    idx = bdays(40)
    n = len(idx)
    clean = 100.0 * 1.01 ** np.arange(n)  # perfectly log-linear uptrend → R²≈1
    rng = np.random.default_rng(3)
    noisy = clean * np.exp(rng.normal(0.0, 0.05, n))  # same drift, added noise
    prices = pd.DataFrame({"CLEAN Index": clean, "NOISY Index": noisy}, index=idx)
    ts = stats.trend_strength(prices, window_days=40)
    # A clean persistent uptrend outranks a noisy one of similar slope.
    assert ts["CLEAN Index"] > ts["NOISY Index"]
    # Clean log-linear series: slope·R² ≈ ln(1.01).
    assert ts["CLEAN Index"] == pytest.approx(np.log(1.01), rel=1e-6)


def test_trend_strength_flat_series_is_zero(bdays):
    idx = bdays(30)
    prices = pd.DataFrame({"FLAT Index": np.full(len(idx), 100.0)}, index=idx)
    assert stats.trend_strength(prices, window_days=21)["FLAT Index"] == 0.0


def test_trend_strength_short_history_is_nan(bdays):
    idx = bdays(2)
    prices = pd.DataFrame({"X Index": [100.0, 101.0]}, index=idx)
    assert np.isnan(stats.trend_strength(prices, window_days=21)["X Index"])


# --- v0.8.x superlative helpers: down-streak / ma-spread --------------------


def test_longest_down_streak_counts_consecutive_losses(bdays):
    idx = bdays(6)
    rets = pd.DataFrame(
        {
            "DOWN Index": [-0.01, -0.01, -0.01, -0.01, -0.01, -0.01],  # all down → 6
            "MIX Index": [-0.01, -0.01, 0.01, -0.01, -0.01, -0.01],  # longest run → 3
            "UP Index": [0.01, 0.01, 0.01, 0.01, 0.01, 0.01],  # never down → 0
        },
        index=idx,
    )
    streak = stats.longest_down_streak(rets, window_days=21)
    assert streak["DOWN Index"] == 6.0
    assert streak["MIX Index"] == 3.0
    assert streak["UP Index"] == 0.0


def test_longest_down_streak_all_nan_is_nan(bdays):
    idx = bdays(4)
    rets = pd.DataFrame({"X Index": [np.nan, np.nan, np.nan, np.nan]}, index=idx)
    assert np.isnan(stats.longest_down_streak(rets, window_days=21)["X Index"])


def test_ma_spread_known_value(bdays):
    idx = bdays(5)
    # SMA of [100,102,104,106,108] = 104; last = 108 → 108/104 - 1.
    prices = pd.DataFrame({"X Index": [100.0, 102.0, 104.0, 106.0, 108.0]}, index=idx)
    spread = stats.ma_spread(prices, window_days=5)
    assert spread["X Index"] == pytest.approx(108.0 / 104.0 - 1.0)


def test_ma_spread_flat_series_is_zero(bdays):
    idx = bdays(30)
    prices = pd.DataFrame({"FLAT Index": np.full(len(idx), 100.0)}, index=idx)
    assert stats.ma_spread(prices, window_days=21)["FLAT Index"] == pytest.approx(0.0)


def test_ma_spread_insufficient_history_is_nan(bdays):
    idx = bdays(10)
    # Only 10 rows but a 21-day window requested → not enough → NaN.
    prices = pd.DataFrame({"X Index": np.linspace(100.0, 110.0, len(idx))}, index=idx)
    assert np.isnan(stats.ma_spread(prices, window_days=21)["X Index"])


def test_ma_spread_empty_passthrough():
    assert stats.ma_spread(pd.DataFrame(), window_days=21).empty


# --- v0.8.4 superlative-redo helpers ---------------------------------------


def test_max_drawup_window(tiny_prices):
    du = stats.max_drawup(tiny_prices, years=10)  # window covers all rows
    # AAA only rises → biggest run-up is the whole ramp: 133.1/100 - 1.
    assert du["AAA Index"] == pytest.approx(0.331)
    # BBB: cummin hits 90 → 150/90 - 1 is the largest run-up off the trough.
    assert du["BBB Index"] == pytest.approx(150.0 / 90.0 - 1.0)


def test_max_drawup_empty_safe():
    assert stats.max_drawup(pd.DataFrame(), years=1).empty


def test_asset_class_demeaned_zscore_neutralizes_class_level():
    # Equity sits structurally higher than Bond. The raw winner is an equity
    # name, but after demeaning each class the biggest cohort-relative mover is
    # a bond name → the demeaned-z winner differs from the raw idxmax.
    series = pd.Series(
        {"E1 Index": 10.0, "E2 Index": 12.0, "B1 Index": 1.0, "B2 Index": 5.0}
    )
    asset_class = pd.Series(
        {
            "E1 Index": "Equity",
            "E2 Index": "Equity",
            "B1 Index": "Bond",
            "B2 Index": "Bond",
        }
    )
    z = stats.asset_class_demeaned_zscore(series, asset_class)
    assert series.idxmax() == "E2 Index"  # raw winner is the high-class name
    assert z.idxmax() == "B2 Index"  # cohort-relative winner after demeaning
    assert z["B2 Index"] > z["E2 Index"]


def test_asset_class_demeaned_zscore_empty():
    assert stats.asset_class_demeaned_zscore(
        pd.Series(dtype=float), pd.Series(dtype=float)
    ).empty


def test_return_autocorr_trending_is_positive(bdays):
    idx = bdays(30)
    # Perfectly monotonic returns → lag-1 autocorrelation 1.0 (max persistence).
    rets = pd.DataFrame({"X Index": np.linspace(0.001, 0.030, len(idx))}, index=idx)
    assert stats.return_autocorr(rets, window_days=30)["X Index"] == pytest.approx(1.0)


def test_return_autocorr_alternating_is_negative(bdays):
    idx = bdays(30)
    vals = np.tile([0.01, -0.01], len(idx) // 2)  # perfectly mean-reverting
    rets = pd.DataFrame({"X Index": vals}, index=idx)
    assert stats.return_autocorr(rets, window_days=30)["X Index"] == pytest.approx(-1.0)


def test_return_autocorr_short_history_is_nan(bdays):
    idx = bdays(3)  # 3 points < lag + 3 = 4 → NaN
    rets = pd.DataFrame({"X Index": [0.01, -0.01, 0.01]}, index=idx)
    assert np.isnan(stats.return_autocorr(rets, window_days=21)["X Index"])


def test_return_autocorr_empty_passthrough():
    assert stats.return_autocorr(pd.DataFrame(), window_days=21).empty


def test_macd_histogram_recent_up_positive_recent_down_negative(bdays):
    idx = bdays(80)
    # Flat for 60 days then a sharp recent move — the histogram reflects the
    # latest momentum direction (MACD above/below its signal line).
    up_vals = np.concatenate([np.full(60, 100.0), np.linspace(100.0, 130.0, 20)])
    dn_vals = np.concatenate([np.full(60, 100.0), np.linspace(100.0, 70.0, 20)])
    up = pd.DataFrame({"UP Index": up_vals}, index=idx)
    dn = pd.DataFrame({"DN Index": dn_vals}, index=idx)
    assert stats.macd_histogram(up)["UP Index"] > 0
    assert stats.macd_histogram(dn)["DN Index"] < 0


def test_macd_histogram_short_history_is_nan(bdays):
    idx = bdays(20)  # fewer than slow=26 observations → NaN
    prices = pd.DataFrame({"X Index": np.linspace(100.0, 120.0, len(idx))}, index=idx)
    assert np.isnan(stats.macd_histogram(prices)["X Index"])


def test_macd_histogram_empty_passthrough():
    assert stats.macd_histogram(pd.DataFrame()).empty


def test_recovery_days_counts_trough_to_recovery(bdays):
    idx = bdays(5)
    # peak 110 (day1) → trough 90 (day2) → regains 110 at day4 → 2 days later.
    prices = pd.DataFrame({"X Index": [100.0, 110.0, 90.0, 100.0, 110.0]}, index=idx)
    assert stats.recovery_days(prices, window_days=21)["X Index"] == pytest.approx(2.0)


def test_recovery_days_no_drawdown_is_nan(bdays):
    idx = bdays(5)
    prices = pd.DataFrame({"X Index": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)
    assert np.isnan(stats.recovery_days(prices, window_days=21)["X Index"])


def test_recovery_days_unrecovered_is_nan(bdays):
    idx = bdays(4)
    # Drops to 90 and only claws back to 95 — never regains the 110 peak.
    prices = pd.DataFrame({"X Index": [100.0, 110.0, 90.0, 95.0]}, index=idx)
    assert np.isnan(stats.recovery_days(prices, window_days=21)["X Index"])


def test_return_skew_sign(bdays):
    idx = bdays(10)
    right = pd.DataFrame({"R Index": [-0.01] * 9 + [0.2]}, index=idx)  # right tail
    left = pd.DataFrame({"L Index": [0.01] * 9 + [-0.2]}, index=idx)  # left tail
    assert stats.return_skew(right, window_days=21)["R Index"] > 0
    assert stats.return_skew(left, window_days=21)["L Index"] < 0


def test_return_skew_short_history_is_nan(bdays):
    idx = bdays(2)  # fewer than 3 points → skew undefined → NaN
    rets = pd.DataFrame({"X Index": [0.01, -0.01]}, index=idx)
    assert np.isnan(stats.return_skew(rets, window_days=21)["X Index"])


def test_return_skew_empty_passthrough():
    assert stats.return_skew(pd.DataFrame(), window_days=21).empty


def test_win_rate_fraction_of_up_days(bdays):
    idx = bdays(4)
    rets = pd.DataFrame({"X Index": [0.01, 0.01, -0.01, 0.02]}, index=idx)
    assert stats.win_rate(rets, window_days=21)["X Index"] == pytest.approx(0.75)


def test_win_rate_excludes_nan_days(bdays):
    idx = bdays(4)
    rets = pd.DataFrame({"X Index": [0.01, np.nan, -0.01, 0.02]}, index=idx)
    # valid days = 3, up days = 2 → 2/3.
    assert stats.win_rate(rets, window_days=21)["X Index"] == pytest.approx(2.0 / 3.0)


def test_win_rate_empty_passthrough():
    assert stats.win_rate(pd.DataFrame(), window_days=21).empty


# --- v0.8.5 regime analytics: mask / risk-return / correlation --------------


def test_regime_mask_half_open_and_nan(bdays):
    idx = bdays(6)
    ind = pd.Series([10.0, 15.0, 24.999, 25.0, np.nan, 40.0], index=idx)
    m = stats.regime_mask(ind, 15.0, 25.0)
    # [15, 25): 15.0 in, 24.999 in; 10 below, 25.0 at the (excluded) upper edge,
    # 40 above, NaN excluded.
    assert list(m) == [False, True, True, False, False, False]


def test_regime_mask_open_ends(bdays):
    idx = bdays(3)
    ind = pd.Series([5.0, 14.9, 100.0], index=idx)
    assert list(stats.regime_mask(ind, -np.inf, 15.0)) == [True, True, False]
    assert list(stats.regime_mask(ind, 35.0, np.inf)) == [False, False, True]


def test_regime_mask_empty():
    assert stats.regime_mask(pd.Series(dtype=float), 0.0, 1.0).empty


def test_regime_risk_return_over_masked_days(bdays):
    idx = bdays(10)
    rng = np.random.default_rng(0)
    rets = pd.DataFrame(
        {
            "A Index": rng.normal(0.001, 0.01, 10),
            "B Index": rng.normal(0.0, 0.02, 10),
        },
        index=idx,
    )
    mask = pd.Series([True] * 5 + [False] * 5, index=idx)
    frame = stats.regime_risk_return(rets, mask)
    assert list(frame.columns) == ["vol", "ret", "sharpe"]
    assert list(frame.index) == ["A Index", "B Index"]
    sub = rets.iloc[:5]  # only the masked days
    np.testing.assert_allclose(
        frame["vol"].to_numpy(),
        (sub.std() * np.sqrt(TRADING_DAYS_PER_YEAR)).to_numpy(),
        rtol=1e-9,
    )
    np.testing.assert_allclose(
        frame["ret"].to_numpy(),
        (sub.mean() * TRADING_DAYS_PER_YEAR).to_numpy(),  # mean-based, not CAGR
        rtol=1e-9,
    )


def test_regime_risk_return_too_few_days_is_empty(bdays):
    idx = bdays(5)
    rets = pd.DataFrame({"A Index": [0.01] * 5}, index=idx)
    mask = pd.Series([True] + [False] * 4, index=idx)  # one day → empty
    out = stats.regime_risk_return(rets, mask)
    assert out.empty
    assert list(out.columns) == ["vol", "ret", "sharpe"]


def test_regime_correlation_subset_and_mask(bdays):
    idx = bdays(8)
    base = np.linspace(-0.02, 0.02, 8)
    rets = pd.DataFrame(
        {"A Index": base, "B Index": 2.0 * base, "C Index": -base}, index=idx
    )
    mask = pd.Series([True] * 6 + [False] * 2, index=idx)
    cm = stats.regime_correlation(rets, mask, columns=["A Index", "B Index"])
    # Only the theme's columns; B = 2A → perfectly correlated over masked days.
    assert list(cm.columns) == ["A Index", "B Index"]
    assert cm.loc["A Index", "B Index"] == pytest.approx(1.0)


def test_regime_correlation_degenerate_is_empty(bdays):
    idx = bdays(5)
    rets = pd.DataFrame(
        {
            "A Index": np.linspace(-0.01, 0.01, 5),
            "B Index": np.linspace(0.01, -0.01, 5),
        },
        index=idx,
    )
    mask = pd.Series([True] * 5, index=idx)
    assert stats.regime_correlation(rets, mask, columns=["A Index"]).empty  # <2 cols
    one_day = pd.Series([True] + [False] * 4, index=idx)
    assert stats.regime_correlation(rets, one_day).empty  # <2 days
