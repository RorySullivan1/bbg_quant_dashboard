"""Unit tests for the Multi-Strategy pane engine's shared benchmark plumbing
(`_bench_window` / `_bench_returns` / `_render_bench_chart`, v0.9.12-review #157).

The four benchmark-dependent charts (heatmap / rolling-corr / rolling-beta /
outperformance) route their common skeleton — slice a benchmark from the cache,
memoize a compute keyed by `(prefix, ticker)`, swallow a missing-benchmark
failure — through these helpers. These tests exercise that skeleton directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from src.cache import LRUCache
from src.layout.multi_strategy import (
    _bench_returns,
    _bench_window,
    _render_bench_chart,
)


def _prices() -> pd.DataFrame:
    idx = pd.bdate_range("2021-01-04", periods=30)
    return pd.DataFrame(
        {
            "SPX Index": [100.0 + i for i in range(30)],
            "DEAD Index": [float("nan")] * 30,  # present but all-NaN
        },
        index=idx,
    )


def _state() -> SimpleNamespace:
    return SimpleNamespace(universe_prices=_prices(), memo=LRUCache(maxsize=8))


# --- _bench_window / _bench_returns ------------------------------------------


def test_bench_window_slices_to_range():
    win = _bench_window(
        _state(), "SPX Index", pd.Timestamp("2021-01-06"), pd.Timestamp("2021-01-12")
    )
    assert not win.empty
    assert win.index.min() >= pd.Timestamp("2021-01-06")
    assert win.index.max() <= pd.Timestamp("2021-01-12")


def test_bench_window_raises_on_missing_ticker():
    with pytest.raises(ValueError, match="No price data for benchmark"):
        _bench_window(
            _state(),
            "NOPE Index",
            pd.Timestamp("2021-01-04"),
            pd.Timestamp("2021-01-30"),
        )


def test_bench_window_raises_on_all_nan_ticker():
    with pytest.raises(ValueError, match="No price data for benchmark"):
        _bench_window(
            _state(),
            "DEAD Index",
            pd.Timestamp("2021-01-04"),
            pd.Timestamp("2021-01-30"),
        )


def test_bench_returns_is_a_series_of_daily_returns():
    rets = _bench_returns(
        _state(), "SPX Index", pd.Timestamp("2021-01-04"), pd.Timestamp("2021-01-30")
    )
    assert isinstance(rets, pd.Series)
    assert len(rets) >= 1


# --- _render_bench_chart (memoize + update + swallow) -------------------------


def test_render_bench_chart_memoizes_and_updates():
    state = _state()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return "RESULT"

    seen: list[object] = []
    errors: list[str] = []
    key = ("k", "SPX Index")
    _render_bench_chart(state, key, compute, seen.append, errors)
    _render_bench_chart(state, key, compute, seen.append, errors)
    assert seen == ["RESULT", "RESULT"]  # updated both times
    assert calls["n"] == 1  # memoized: compute ran once
    assert errors == []


def test_render_bench_chart_swallows_compute_error_into_errors():
    state = _state()
    updated: list[object] = []
    errors: list[str] = []

    def boom():
        raise ValueError("no benchmark data")

    _render_bench_chart(state, ("k", "X"), boom, updated.append, errors)
    assert updated == []  # update not called on a failed compute
    assert len(errors) == 1
    assert "no benchmark data" in errors[0]
