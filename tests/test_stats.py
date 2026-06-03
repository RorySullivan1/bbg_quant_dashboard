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
from src.config import TRADING_DAYS_PER_YEAR

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
