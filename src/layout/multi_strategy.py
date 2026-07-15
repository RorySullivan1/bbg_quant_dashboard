"""The Multi-Strategy tab's analysis-pane render engine (v0.9.12-review #156).

Extracted from the ``build_app`` monolith into free functions taking
``(state, meta, pane, …)`` — mirroring the ``single_strategy.py`` pattern — so
the two-pane render path is testable in isolation and ``build_app`` shrinks to
orchestration. No widgets are built here (``panes.py`` owns the pane widgets);
these functions only render into an existing pane from a prepared data slice.

Each pane swaps among nine analysis views. The four benchmark-dependent charts
(Correlation Heatmap, Rolling Correlation, Rolling Beta, Outperformance) share a
``(pane, prep, win_start, win_end, errors)`` signature so the same code serves
both the full recompute (``render_pane``) and the live per-pane
benchmark/regime observers (``bind_live_controls``). Every benchmark series is
sliced from the already-fetched ``state.universe_prices`` and memoized on
``state.memo`` — no BQL fetch.
"""

from __future__ import annotations

import traceback
from types import SimpleNamespace

import pandas as pd

from ..config import LOOKBACK_YEARS
from ..stats import (
    daily_returns,
    excess_cum_return,
    heatmap_corr_matrix,
    rolling_beta,
    rolling_correlation,
)
from .charts import (
    _update_drawdown,
    _update_heatmap,
    _update_line,
    _update_outperformance,
    _update_return_dist,
    _update_rolling_ref,
    _update_scatter,
    _update_sharpe_line,
)


def clear_pane(pane: SimpleNamespace, meta: pd.DataFrame) -> None:
    """Reset every figure in ``pane`` to empty (no valid selection)."""
    _update_line(pane.line_fig, pd.DataFrame(), meta)
    _update_outperformance(pane.outperf_fig, pd.DataFrame(), meta, benchmark_label="")
    _update_sharpe_line(pane.sharpe_fig, pd.DataFrame(), meta)
    _update_heatmap(pane.heat_fig, pd.DataFrame())
    _update_scatter(pane.scatter_fig, pd.DataFrame(), pd.DataFrame(), meta)
    _update_drawdown(pane.dd_fig, pd.DataFrame(), meta)
    _update_rolling_ref(
        pane.rcorr_fig,
        pd.DataFrame(),
        meta,
        title_prefix="Rolling Correlation",
        benchmark_label="",
    )
    _update_rolling_ref(
        pane.rbeta_fig,
        pd.DataFrame(),
        meta,
        title_prefix="Rolling Beta",
        benchmark_label="",
    )
    _update_return_dist(
        pane.retdist_fig,
        pane.retdist_stats_grid,
        pd.DataFrame(),
        pd.DataFrame(),
        meta,
    )
    # No selection -> no view holds current data; the lazy picker observer
    # no-ops while cur_prep is None, so picks just swap to cleared figures.
    pane.fresh = set()


def _render_heatmap(
    state: object,
    meta: pd.DataFrame,  # unused — kept for a uniform benchmark-helper signature
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    # Correlation heatmap, three cases (per-pane, so the panes stay
    # independent): Regime on → conditioned on the benchmark-return tail with
    # the benchmark in the matrix; Benchmark on / Regime off → full-sample
    # correlation with the benchmark added (v0.8.9); neither → plain
    # full-sample correlation of the selected strategies (`prep.cm`). The two
    # benchmark cases differ only in (pct, direction, memo key, title); both
    # build the matrix through the single `heatmap_corr_matrix` helper, which
    # always pins the benchmark last, so the left and right panes can never
    # disagree on the row/column order.
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
        _update_heatmap(
            pane.heat_fig,
            prep.cm,
            title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
        )
        return

    try:

        def _compute():
            hm_bench_prices = state.universe_prices.get(hm_bench_ticker)
            if hm_bench_prices is None or hm_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {hm_bench_ticker!r}.")
            hm_bench_window = hm_bench_prices.loc[win_start:win_end]
            hm_bench_returns = daily_returns(hm_bench_window.to_frame()).iloc[:, 0]
            return heatmap_corr_matrix(
                prep.rets,
                hm_bench_returns,
                pct=pct_int / 100.0,
                direction=direction,
            )

        cm = state.memo.get_or_compute(memo_key, _compute)
        _update_heatmap(pane.heat_fig, cm, title=title)
    except Exception:
        errors.append(traceback.format_exc())
        _update_heatmap(pane.heat_fig, pd.DataFrame())


def _render_rolling_corr(
    state: object,
    meta: pd.DataFrame,
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    rc_bench_ticker = pane.rcorr_dd.value
    try:

        def _compute_rcorr():
            rc_bench_prices = state.universe_prices.get(rc_bench_ticker)
            if rc_bench_prices is None or rc_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {rc_bench_ticker!r}.")
            rc_bench_window = rc_bench_prices.loc[win_start:win_end]
            rc_bench_returns = daily_returns(rc_bench_window.to_frame()).iloc[:, 0]
            return rolling_correlation(prep.rets, rc_bench_returns)

        rc = state.memo.get_or_compute(("rcorr", rc_bench_ticker), _compute_rcorr)
        _update_rolling_ref(
            pane.rcorr_fig,
            rc,
            meta,
            title_prefix="Rolling Correlation",
            benchmark_label=rc_bench_ticker,
        )
    except Exception:
        errors.append(traceback.format_exc())


def _render_rolling_beta(
    state: object,
    meta: pd.DataFrame,
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    rb_bench_ticker = pane.rbeta_dd.value
    try:

        def _compute_rbeta():
            rb_bench_prices = state.universe_prices.get(rb_bench_ticker)
            if rb_bench_prices is None or rb_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {rb_bench_ticker!r}.")
            rb_bench_window = rb_bench_prices.loc[win_start:win_end]
            rb_bench_returns = daily_returns(rb_bench_window.to_frame()).iloc[:, 0]
            return rolling_beta(prep.rets, rb_bench_returns)

        rb = state.memo.get_or_compute(("rbeta", rb_bench_ticker), _compute_rbeta)
        _update_rolling_ref(
            pane.rbeta_fig,
            rb,
            meta,
            title_prefix="Rolling Beta",
            benchmark_label=rb_bench_ticker,
        )
    except Exception:
        errors.append(traceback.format_exc())


def _render_outperf(
    state: object,
    meta: pd.DataFrame,
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    # Outperformance: cumulative excess return vs the benchmark (prices,
    # not returns — every strategy series starts at 0).
    op_bench_ticker = pane.outperf_dd.value
    try:

        def _compute_outperf():
            op_bench_prices = state.universe_prices.get(op_bench_ticker)
            if op_bench_prices is None or op_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {op_bench_ticker!r}.")
            op_bench_window = op_bench_prices.loc[win_start:win_end]
            return excess_cum_return(prep.sel_window, op_bench_window)

        oc = state.memo.get_or_compute(("outperf", op_bench_ticker), _compute_outperf)
        _update_outperformance(
            pane.outperf_fig,
            oc,
            meta,
            benchmark_label=op_bench_ticker,
        )
    except Exception:
        errors.append(traceback.format_exc())


def render_one(
    state: object,
    meta: pd.DataFrame,
    pane: SimpleNamespace,
    label: str,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    # Populate the single analysis view named `label` from `prep`. Lazy
    # rendering (Workstream D) calls this for only the mounted view per
    # recompute and builds the others on first pick.
    if label == "Cumulative Performance":
        _update_line(pane.line_fig, prep.perf, meta)
    elif label == "1Y Sharpe-z Line":
        _update_sharpe_line(pane.sharpe_fig, prep.sz_series, meta)
    elif label == "Risk / Return":
        _update_scatter(pane.scatter_fig, prep.sel_window, prep.rets, meta)
    elif label == "Drawdown":
        _update_drawdown(pane.dd_fig, prep.dd, meta)
    elif label == "Return Distribution":
        _update_return_dist(
            pane.retdist_fig,
            pane.retdist_stats_grid,
            prep.rets,
            prep.rd_stats,
            meta,
        )
    elif label == "Correlation Heatmap":
        _render_heatmap(state, meta, pane, prep, win_start, win_end, errors)
    elif label == "Rolling Correlation":
        _render_rolling_corr(state, meta, pane, prep, win_start, win_end, errors)
    elif label == "Rolling Beta":
        _render_rolling_beta(state, meta, pane, prep, win_start, win_end, errors)
    elif label == "Outperformance":
        _render_outperf(state, meta, pane, prep, win_start, win_end, errors)


def render_pane(
    state: object,
    meta: pd.DataFrame,
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    # Lazy (Workstream D): render only the currently-mounted view; the other
    # eight are built on first pick (see bind_lazy_render) and stay fresh
    # until the next recompute resets `pane.fresh`.
    label = pane.picker.value
    render_one(state, meta, pane, label, prep, win_start, win_end, errors)
    pane.fresh = {label}


def bind_lazy_render(state: object, meta: pd.DataFrame, pane: SimpleNamespace) -> None:
    # On a picker change, build the newly-shown view on demand if it hasn't
    # been rendered for the current slice yet (panes.py already swaps it into
    # view and syncs control visibility). No-op without a valid selection or
    # when the view is already fresh; errors are swallowed like the live
    # benchmark observers (a real failure resurfaces on the next Refresh).
    def _on_pick_render(change):
        label = change["new"]
        if state.cur_prep is None or label in pane.fresh:
            return
        render_one(
            state,
            meta,
            pane,
            label,
            state.cur_prep,
            state.cur_win_start,
            state.cur_win_end,
            [],
        )
        pane.fresh.add(label)

    pane.picker.observe(_on_pick_render, names="value")


def bind_live_controls(
    state: object, meta: pd.DataFrame, pane: SimpleNamespace
) -> None:
    # Wire the per-pane benchmark dropdowns and Correlation-Heatmap regime
    # controls so changing one re-renders only its own chart, immediately,
    # from the slice persisted on `state` at the last recompute — no BQL
    # fetch, no full recompute, the other pane untouched. (Refresh prices
    # stays the only path that refetches and re-runs filters/selection.)
    def _make(render_fn):
        def _handler(_change):
            if state.cur_prep is None:
                return  # no valid selection — nothing to redraw, no fetch
            # A single live chart swallows its errors: the helper's own
            # except-branch leaves the chart in a safe state, and a
            # genuinely broken benchmark still surfaces on the next
            # Refresh prices (where errors flow into the commentary block).
            render_fn(
                state,
                meta,
                pane,
                state.cur_prep,
                state.cur_win_start,
                state.cur_win_end,
                [],
            )

        return _handler

    pane.rcorr_dd.observe(_make(_render_rolling_corr), names="value")
    pane.rbeta_dd.observe(_make(_render_rolling_beta), names="value")
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
