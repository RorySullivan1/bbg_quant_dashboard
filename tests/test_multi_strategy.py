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
    RenderContext,
    _bench_returns,
    _bench_window,
    _render_bench_chart,
)
from src.layout.selection import SelectionSlice


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


def _ctx(
    start: str = "2021-01-04",
    end: str = "2021-01-30",
    *,
    errors: list[str] | None = None,
) -> RenderContext:
    """A context over a minimal slice — #217 bundles state/meta/slice/errors.

    The benchmark helpers only read the window bounds off the slice, so the
    frame behind it can be the same two-column fixture.
    """
    sel = SelectionSlice.build(
        _prices()[["SPX Index"]], pd.Timestamp(start), pd.Timestamp(end)
    )
    return RenderContext(
        state=_state(),
        meta=pd.DataFrame(),
        sel=sel,
        errors=[] if errors is None else errors,
    )


# --- _bench_window / _bench_returns ------------------------------------------


def test_bench_window_slices_to_range():
    win = _bench_window(_ctx("2021-01-06", "2021-01-12"), "SPX Index")
    assert not win.empty
    assert win.index.min() >= pd.Timestamp("2021-01-06")
    assert win.index.max() <= pd.Timestamp("2021-01-12")


def test_bench_window_raises_on_missing_ticker():
    with pytest.raises(ValueError, match="No price data for benchmark"):
        _bench_window(_ctx(), "NOPE Index")


def test_bench_window_raises_on_all_nan_ticker():
    with pytest.raises(ValueError, match="No price data for benchmark"):
        _bench_window(_ctx(), "DEAD Index")


def test_bench_returns_is_a_series_of_daily_returns():
    rets = _bench_returns(_ctx(), "SPX Index")
    assert isinstance(rets, pd.Series)
    assert len(rets) >= 1


# --- _render_bench_chart (memoize + update + swallow) -------------------------


def test_render_bench_chart_memoizes_and_updates():
    ctx = _ctx()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return "RESULT"

    seen: list[object] = []
    key = ("k", "SPX Index")
    _render_bench_chart(ctx, key, compute, seen.append)
    _render_bench_chart(ctx, key, compute, seen.append)
    assert seen == ["RESULT", "RESULT"]  # updated both times
    assert calls["n"] == 1  # memoized: compute ran once
    assert ctx.errors == []


def test_render_bench_chart_swallows_compute_error_into_errors():
    ctx = _ctx()
    updated: list[object] = []

    def boom():
        raise ValueError("no benchmark data")

    _render_bench_chart(ctx, ("k", "X"), boom, updated.append)
    assert updated == []  # update not called on a failed compute
    assert len(ctx.errors) == 1
    assert "no benchmark data" in ctx.errors[0]


# --- SelectionSlice (#217) ---------------------------------------------------


def test_selection_slice_build_matches_the_stats_functions():
    # The three fields that used to be bolted on after construction are now
    # computed inside `build`. This guards the classmethod against drifting
    # from what the call site used to do.
    from src.stats import (
        corr_matrix,
        cum_perf,
        daily_returns,
        drawdown_series,
        perf_table,
        return_distribution_stats,
        rolling_sharpe_zscore,
    )

    window = _prices()[["SPX Index"]]
    start, end = pd.Timestamp("2021-01-04"), pd.Timestamp("2021-02-12")
    sel = SelectionSlice.build(window, start, end)

    rets = daily_returns(window)
    pd.testing.assert_frame_equal(sel.rets, rets)
    pd.testing.assert_frame_equal(sel.perf, cum_perf(window))
    pd.testing.assert_frame_equal(sel.pt, perf_table(window, returns=rets))
    pd.testing.assert_frame_equal(sel.dd, drawdown_series(window))
    pd.testing.assert_frame_equal(sel.sz_series, rolling_sharpe_zscore(rets))
    pd.testing.assert_frame_equal(sel.cm, corr_matrix(rets))
    pd.testing.assert_frame_equal(sel.rd_stats, return_distribution_stats(rets))
    # The bounds are carried, not re-derived: they come from the date boxes and
    # can fall outside the traded days, and benchmarks are sliced against them.
    assert (sel.win_start, sel.win_end) == (start, end)


def test_selection_slice_is_complete_at_construction():
    # The old `SimpleNamespace` was briefly missing sz_series / cm / rd_stats,
    # and nothing stopped a later assignment from reshaping it.
    import dataclasses

    sel = SelectionSlice.build(
        _prices()[["SPX Index"]], pd.Timestamp("2021-01-04"), pd.Timestamp("2021-02-12")
    )
    for f in dataclasses.fields(sel):
        assert getattr(sel, f.name) is not None, f.name
    with pytest.raises(dataclasses.FrozenInstanceError):
        sel.cm = pd.DataFrame()


def test_render_context_live_is_none_without_a_selection():
    # What the live observers check before redrawing — no selection means no
    # redraw and, critically, no fetch.
    state = _state()
    state.cur_prep = None
    assert RenderContext.live(state, pd.DataFrame()) is None

    state.cur_prep = SelectionSlice.build(
        _prices()[["SPX Index"]], pd.Timestamp("2021-01-04"), pd.Timestamp("2021-02-12")
    )
    ctx = RenderContext.live(state, pd.DataFrame())
    assert ctx is not None
    assert ctx.sel is state.cur_prep
    assert ctx.errors == []  # a throwaway list; live charts swallow their errors
