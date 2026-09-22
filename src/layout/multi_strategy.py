"""The Multi-Strategy tab's analysis-pane render engine.

Extracted from the ``build_app`` monolith so the two-pane render path is
testable in isolation and ``build_app`` shrinks to orchestration. No widgets are
built here (``panes.py`` owns the pane widgets); these functions only render
into an existing pane from a prepared data slice.

Every renderer takes a `RenderContext` (#217): the same four values —
``state``, ``meta``, the `SelectionSlice`, and the error list — used to be
threaded through as five to eight positional parameters, which is why
``_render_heatmap`` carried a ``meta`` argument it never read, purely to keep
the benchmark helpers' signatures uniform. Bundling them makes that uniformity
structural, and the same code still serves both the full recompute
(``render_pane``) and the live per-pane benchmark/regime observers
(``bind_live_controls``).

Each pane swaps among eight analysis views. Every benchmark series is sliced from
the already-fetched ``state.universe_prices`` and memoized on ``state.memo`` —
no BQL fetch.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from ..config import LOOKBACK_YEARS
from ..stats import (
    daily_returns,
    excess_cum_return,
    heatmap_corr_matrix,
    rolling_series,
)
from .panes import AnalysisPane
from .selection import SelectionSlice

if TYPE_CHECKING:
    # No cycle today, but `state.py` is one import away from reaching this
    # module, and the annotation never needs the symbol at runtime. Guarded
    # like `single_strategy`, where the cycle is real.
    from .state import DashboardState


@dataclass(frozen=True)
class RenderContext:
    """What every pane renderer needs, bundled once instead of threaded.

    ``errors`` is a list the renderers append tracebacks to; the full recompute
    surfaces them in the commentary block, while a live single-chart observer
    passes a throwaway (a genuinely broken benchmark resurfaces on the next
    Refresh). ``state`` stays loosely typed until the `DashboardApp` sub-issue.
    """

    state: DashboardState
    meta: pd.DataFrame
    sel: SelectionSlice
    errors: list[str] = field(default_factory=list)

    @classmethod
    def live(cls, state: DashboardState, meta: pd.DataFrame) -> RenderContext | None:
        """A context over the slice persisted at the last recompute.

        ``None`` when there is no valid selection — the live observers no-op
        rather than redraw, and never fetch.
        """
        if state.cur_prep is None:
            return None
        return cls(state=state, meta=meta, sel=state.cur_prep)


def clear_pane(pane: AnalysisPane, meta: pd.DataFrame) -> None:
    """Reset every figure in ``pane`` to empty (no valid selection)."""
    for chart in (
        pane.line,
        pane.outperf,
        pane.sharpe,
        pane.heat,
        pane.scatter,
        pane.dd,
        pane.rolling,
        pane.retdist,
    ):
        chart.clear()
    # No selection -> no view holds current data; the lazy picker observer
    # no-ops while cur_prep is None, so picks just swap to cleared figures.
    pane.fresh = set()


# --- Shared benchmark-chart plumbing -----------------------------------------
# The four benchmark-dependent charts (heatmap / rolling-corr / rolling-beta /
# outperformance) all slice a benchmark from the cache, memoize a compute keyed
# by ``(prefix, ticker)``, and swallow a missing-benchmark failure. These three
# helpers factor out that shared skeleton so each chart is just its own
# compute + update.


def _bench_window(ctx: RenderContext, ticker: str) -> pd.Series:
    """The benchmark's price series sliced to the slice's analysis window.

    Raises ``ValueError`` when the benchmark has no data in the cache — the
    callers swallow that into their error list / a cleared figure."""
    prices = ctx.state.universe_prices.get(ticker)
    if prices is None or prices.dropna().empty:
        raise ValueError(f"No price data for benchmark {ticker!r}.")
    return prices.loc[ctx.sel.win_start : ctx.sel.win_end]


def _bench_returns(ctx: RenderContext, ticker: str) -> pd.Series:
    """Daily returns of the benchmark's windowed price series."""
    return daily_returns(_bench_window(ctx, ticker).to_frame()).iloc[:, 0]


def _render_bench_chart(
    ctx: RenderContext,
    memo_key: tuple,
    compute: Callable[[], object],
    update: Callable[[object], None],
) -> None:
    """Memoize ``compute`` under ``memo_key`` and hand the result to ``update``,
    swallowing a failed compute (missing benchmark data) into ``ctx.errors`` —
    the shared driver for the per-pane benchmark charts."""
    try:
        update(ctx.state.memo.get_or_compute(memo_key, compute))
    except Exception:
        ctx.errors.append(traceback.format_exc())


def _render_heatmap(ctx: RenderContext, pane: AnalysisPane) -> None:
    # Three per-pane cases: Regime on → conditioned on the benchmark-return
    # tail; Benchmark only → full-sample with the benchmark added; neither →
    # `ctx.sel.cm`. The benchmark cases differ only in (pct, direction, memo key,
    # title) and both go through `heatmap_corr_matrix`, which pins the benchmark
    # last so the two panes can never disagree on row/column order.
    if pane.heat_regime_chk.value:
        hm_bench_ticker = pane.heat_dd.value
        direction = pane.heat_dir.value  # ">" -> "up", "<" -> "down"
        pct_int = pane.heat_pct.value
        memo_key = ("heatmap", hm_bench_ticker, direction, pct_int)
        tail_lbl = "worst" if direction == "down" else "best"
        title = (
            f"Correlation — {hm_bench_ticker} {tail_lbl} "
            f"{pct_int}% days ({LOOKBACK_YEARS}Y)"
        )
    elif pane.heat_benchmark_chk.value:
        # Benchmark on, Regime off: full-sample correlation (pct=100% keeps
        # every day) with the benchmark added as the last row/column.
        hm_bench_ticker = pane.heat_dd.value
        direction = "down"
        pct_int = 100
        memo_key = ("heatmap", hm_bench_ticker, "incl", 100)
        title = f"Correlation — incl {hm_bench_ticker} ({LOOKBACK_YEARS}Y)"
    else:
        pane.heat.update(
            ctx.sel.cm,
            title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
        )
        return

    try:

        def _compute():
            return heatmap_corr_matrix(
                ctx.sel.rets,
                _bench_returns(ctx, hm_bench_ticker),
                pct=pct_int / 100.0,
                direction=direction,
            )

        cm = ctx.state.memo.get_or_compute(memo_key, _compute)
        pane.heat.update(cm, title=title)
    except Exception:
        ctx.errors.append(traceback.format_exc())
        pane.heat.clear()


def _render_rolling(ctx: RenderContext, pane: AnalysisPane) -> None:
    """The one rolling view, at whatever statistic its chip has selected.

    Two near-identical renderers stood here until #368, one per figure. The
    benchmark is read for every statistic and ignored by the two that do not
    take one — `rolling_series` decides that, and it is also what keys the
    memo, so switching Sharpe → Calmar → Sharpe is a cache hit rather than a
    recompute.
    """
    stat = pane.rolling_chips.value
    ticker = pane.rolling_dd.value
    _render_bench_chart(
        ctx,
        ("rolling", stat, ticker),
        lambda: rolling_series(
            ctx.sel.rets, stat, benchmark=_bench_returns(ctx, ticker)
        ),
        lambda df: pane.rolling.update(df, stat=stat, benchmark_label=ticker),
    )


def _render_outperf(ctx: RenderContext, pane: AnalysisPane) -> None:
    # Outperformance uses the benchmark's price window (not returns) — every
    # strategy series starts at 0 (cumulative excess return).
    ticker = pane.outperf_dd.value
    _render_bench_chart(
        ctx,
        ("outperf", ticker),
        lambda: excess_cum_return(ctx.sel.window, _bench_window(ctx, ticker)),
        lambda oc: pane.outperf.update(oc, benchmark_label=ticker),
    )


def render_one(ctx: RenderContext, pane: AnalysisPane, label: str) -> None:
    # Populate the single analysis view named `label` from `ctx.sel`. Lazy
    # rendering calls this for only the mounted view per
    # recompute and builds the others on first pick.
    sel = ctx.sel
    if label == "Cumulative Performance":
        pane.line.update(sel.perf)
    elif label == "1Y Sharpe-z Line":
        pane.sharpe.update(sel.sz_series)
    elif label == "Risk / Return":
        pane.scatter.update(sel.window, sel.rets, ctx.meta)
    elif label == "Drawdown":
        pane.dd.update(sel.dd)
    elif label == "Return Distribution":
        pane.retdist.update(sel.rets, sel.rd_stats, ctx.meta)
    elif label == "Correlation Heatmap":
        _render_heatmap(ctx, pane)
    elif label == "Rolling":
        _render_rolling(ctx, pane)
    elif label == "Outperformance":
        _render_outperf(ctx, pane)


def render_pane(ctx: RenderContext, pane: AnalysisPane) -> None:
    # Lazy: render only the currently-mounted view; the other
    # eight are built on first pick (see bind_lazy_render) and stay fresh
    # until the next recompute resets `pane.fresh`.
    label = pane.picker.value
    render_one(ctx, pane, label)
    pane.fresh = {label}


def bind_lazy_render(
    state: DashboardState, meta: pd.DataFrame, pane: AnalysisPane
) -> None:
    # On a picker change, build the newly-shown view on demand if it hasn't
    # been rendered for the current slice yet (panes.py already swaps it into
    # view and syncs control visibility). No-op without a valid selection or
    # when the view is already fresh; errors are swallowed like the live
    # benchmark observers (a real failure resurfaces on the next Refresh).
    def _on_pick_render(change):
        label = change["new"]
        ctx = RenderContext.live(state, meta)
        if ctx is None or label in pane.fresh:
            return
        render_one(ctx, pane, label)
        pane.fresh.add(label)

    pane.picker.observe(_on_pick_render, names="value")


def bind_live_controls(
    state: DashboardState, meta: pd.DataFrame, pane: AnalysisPane
) -> None:
    # Wire the per-pane benchmark dropdowns and Correlation-Heatmap regime
    # controls so changing one re-renders only its own chart, immediately,
    # from the slice persisted on `state` at the last recompute — no BQL
    # fetch, no full recompute, the other pane untouched. (Refresh prices
    # stays the only path that refetches and re-runs filters/selection.)
    def _make(render_fn):
        def _handler(_change):
            ctx = RenderContext.live(state, meta)
            if ctx is None:
                return  # no valid selection — nothing to redraw, no fetch
            # A single live chart swallows its errors: `ctx.errors` is a fresh
            # list nobody reads, the helper's own except-branch leaves the chart
            # in a safe state, and a genuinely broken benchmark still surfaces
            # on the next Refresh prices (where errors reach the commentary).
            render_fn(ctx, pane)

        return _handler

    # The statistic chip is a live control like the benchmark beside it: it
    # re-slices the cache, it never fetches.
    pane.rolling_chips.observe(_make(_render_rolling), names="value")
    pane.rolling_dd.observe(_make(_render_rolling), names="value")
    pane.outperf_dd.observe(_make(_render_outperf), names="value")
    # The Benchmark/Regime checkboxes keep their visibility-sync observers
    # (in panes.py); this adds the data re-render on top. Toggling Benchmark
    # off re-renders plain full-sample (it also clears Regime in panes.py).
    for ctrl in (
        pane.heat_benchmark_chk,
        pane.heat_regime_chk,
        pane.heat_dd,
        pane.heat_dir,
        pane.heat_pct,
    ):
        ctrl.observe(_make(_render_heatmap), names="value")
