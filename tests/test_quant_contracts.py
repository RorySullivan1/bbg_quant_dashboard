"""The two contracts the quant columns got wrong (v0.9.30).

Both were **silent**: they produced numbers, not errors, and the numbers only
became visible when the metrics moved from threshold boxes nobody could see
into columns on screen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import TRADING_DAYS_PER_YEAR, stat_windows
from src.stats import ann_beta, benchmark_returns, daily_returns


def _series(n: int = 800, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    bench = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    # An asset built to have a known beta of 2 against the benchmark.
    bench_ret = np.diff(np.log(bench), prepend=np.log(bench[0]))
    asset = 100 * np.exp(np.cumsum(2 * bench_ret + rng.normal(0, 1e-6, n)))
    return pd.DataFrame({"BENCH": bench, "ASSET": asset}, index=idx)


def test_stat_windows_yields_years_not_days():
    """The bug: `years=days / TRADING_DAYS_PER_YEAR` turned 1Y into one day,
    so the short windows read N/A and the long ones were measured over three
    days. The second element **is** the year count."""
    windows = dict(stat_windows())
    assert windows["1Y"] == 1.0
    assert windows["5Y"] == 5.0
    assert windows["6M"] == 0.5
    assert windows["1Y"] != TRADING_DAYS_PER_YEAR


def test_ann_beta_needs_benchmark_returns_not_prices():
    """`ann_beta` covaries against whatever it is handed. Passing an index
    *level* series makes `var(benchmark)` enormous, so every beta collapses
    toward zero — which is what shipped until v0.9.30."""
    prices = _series()
    rets = daily_returns(prices)

    correct = ann_beta(rets[["ASSET"]], benchmark_returns(prices["BENCH"]), 3.0)
    wrong = ann_beta(rets[["ASSET"]], prices["BENCH"], 3.0)

    assert abs(correct["ASSET"] - 2.0) < 0.05, "a beta-2 asset must measure ~2"
    assert abs(wrong["ASSET"]) < 0.01, "prices-as-benchmark collapses toward 0"


def test_benchmark_returns_handles_the_empty_and_missing_cases():
    assert benchmark_returns(None) is None
    assert benchmark_returns(pd.Series(dtype=float)) is None


def test_benchmark_returns_matches_a_hand_computed_pct_change():
    prices = _series(n=50)["BENCH"]
    got = benchmark_returns(prices)
    expected = prices.pct_change()
    pd.testing.assert_series_equal(
        got.dropna(), expected.dropna(), check_names=False, rtol=1e-9
    )
