"""Shared, fully deterministic fixtures for the test suite.

No Bloomberg session, no network, no file I/O — every frame here is built
in-process so the stats unit tests have known inputs and the smoke test can
run on the mock-price fallback.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _bdays(n: int, start: str = "2021-01-04") -> pd.DatetimeIndex:
    """`n` consecutive business days from `start`."""
    return pd.bdate_range(start=start, periods=n)


@pytest.fixture
def bdays():
    """Factory for a business-day index of a given length."""
    return _bdays


@pytest.fixture
def tiny_prices() -> pd.DataFrame:
    """Hand-checkable 4-row price frame with known drawdown / returns.

    AAA ramps 100 → 121 (a clean +10% per step); BBB dips then recovers so
    its worst peak-to-trough drawdown is exactly -25%.
    """
    idx = _bdays(4)
    return pd.DataFrame(
        {
            "AAA Index": [100.0, 110.0, 121.0, 133.1],
            "BBB Index": [100.0, 120.0, 90.0, 150.0],
        },
        index=idx,
    )


@pytest.fixture
def multiyear_prices() -> pd.DataFrame:
    """~3 years of seeded daily prices for three tickers.

    Built from a fixed RNG so every run is identical — enough history for the
    1Y/3Y windowed metrics (ann_*, quant_metrics_table) to be non-NaN.
    """
    rng = np.random.default_rng(42)
    idx = _bdays(756)  # ~3 trading years
    cols = ["AAA Index", "BBB Index", "CCC Index"]
    drifts = {"AAA Index": 0.0004, "BBB Index": 0.0001, "CCC Index": -0.0002}
    data = {}
    for c in cols:
        rets = rng.normal(loc=drifts[c], scale=0.01, size=len(idx))
        data[c] = 100.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def benchmark(multiyear_prices) -> pd.Series:
    """A benchmark price series aligned to `multiyear_prices`' index."""
    rng = np.random.default_rng(7)
    rets = rng.normal(loc=0.0003, scale=0.009, size=len(multiyear_prices))
    return pd.Series(
        100.0 * np.cumprod(1.0 + rets),
        index=multiyear_prices.index,
        name="SPX Index",
    )
