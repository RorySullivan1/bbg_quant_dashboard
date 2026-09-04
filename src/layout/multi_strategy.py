"""The Multi-Strategy tab's analysis-pane render engine.

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
from collections.abc import Callable
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
    _update_line(pane.line_fig, pd.DataFrame())
    _update_outperformance(pane.outperf_fig, pd.DataFrame(), benchmark_label="")
    _update_sharpe_line(pane.sharpe_fig, pd.DataFrame())
    _update_heatmap(pane.heat_fig, pd.DataFrame())
    _update_scatter(pane.scatter_fig, pd.DataFrame(), pd.DataFrame(), meta)
    _update_drawdown(pane.dd_fig, pd.DataFrame())
    _update_rolling_ref(
        pane.rcorr_fig,
        pd.DataFrame(),
        title_prefix="Rolling Correlation",
        benchmark_label="",
    )
    _update_rolling_ref(
        pane.rbeta_fig,
        pd.DataFrame(),
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


# --- Shared benchmark-chart plumbing -----------------------------------------
# The four benchmark-dependent charts (heatmap / rolling-corr / rolling-beta /
# outperformance) all slice a benchmark from the cache, memoize a compute keyed
# by ``(prefix, ticker)``, and swallow a missing-benchmark failure. These three
# helpers factor out that shared skeleton so each chart is just its own
# compute + update.


def _bench_window(
    state: object, ticker: str, win_start: pd.Timestamp, win_end: pd.Timestamp
) -> pd.Series:
    """The benchmark's price series sliced to ``[win_start, win_end]``.

    Raises ``ValueError`` when the benchmark has no data in the cache — the
    callers swallow that into their error list / a cleared figure."""
    prices = state.universe_prices.get(ticker)
    if prices is None or prices.dropna().empty:
        raise ValueError(f"No price data for benchmark {ticker!r}.")
    return prices.loc[win_start:win_end]


def _bench_returns(
    state: object, ticker: str, win_start: pd.Timestamp, win_end: pd.Timestamp
) -> pd.Series:
    """Daily returns of the benchmark's windowed price series."""
    window = _bench_window(state, ticker, win_start, win_end)
    return daily_returns(window.to_frame()).iloc[:, 0]


def _render_bench_chart(
    state: object,
    memo_key: tuple,
    compute: Callable[[], object],
    update: Callable[[object], None],
    errors: list[str],
) -> None:
    """Memoize ``compute`` under ``memo_key`` and hand the result to ``update``,
    swallowing a failed compute (missing benchmark data) into ``errors`` — the
    shared driver for the per-pane benchmark charts."""
    try:
        update(state.memo.get_or_compute(memo_key, compute))
    except Exception:
        errors.append(traceback.format_exc())


def _render_heatmap(
    state: object,
    meta: pd.DataFrame,  # unused — kept for a uniform benchmark-helper signature
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    # Three per-pane cases: Regime on → conditioned on the benchmark-return
    # tail; Benchmark only → full-sample with the benchmark added; neither →
    # `prep.cm`. The benchmark cases differ only in (pct, direction, memo key,
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
        _update_heatmap(
            pane.heat_fig,
            prep.cm,
            title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
        )
        return

    try:

        def _compute():
            return heatmap_corr_matrix(
                prep.rets,
                _bench_returns(state, hm_bench_ticker, win_start, win_end),
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
    ticker = pane.rcorr_dd.value
    _render_bench_chart(
        state,
        ("rcorr", ticker),
        lambda: rolling_correlation(
            prep.rets, _bench_returns(state, ticker, win_start, win_end)
        ),
        lambda rc: _update_rolling_ref(
            pane.rcorr_fig,
            rc,
            title_prefix="Rolling Correlation",
            benchmark_label=ticker,
        ),
        errors,
    )


def _render_rolling_beta(
    state: object,
    meta: pd.DataFrame,
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    ticker = pane.rbeta_dd.value
    _render_bench_chart(
        state,
        ("rbeta", ticker),
        lambda: rolling_beta(
            prep.rets, _bench_returns(state, ticker, win_start, win_end)
        ),
        lambda rb: _update_rolling_ref(
            pane.rbeta_fig,
            rb,
            title_prefix="Rolling Beta",
            benchmark_label=ticker,
        ),
        errors,
    )


def _render_outperf(
    state: object,
    meta: pd.DataFrame,
    pane: SimpleNamespace,
    prep: SimpleNamespace,
    win_start: pd.Timestamp,
    win_end: pd.Timestamp,
    errors: list[str],
) -> None:
    # Outperformance uses the benchmark's price window (not returns) — every
    # strategy series starts at 0 (cumulative excess return).
    ticker = pane.outperf_dd.value
    _render_bench_chart(
        state,
        ("outperf", ticker),
        lambda: excess_cum_return(
            prep.sel_window, _bench_window(state, ticker, win_start, win_end)
        ),
        lambda oc: _update_outperformance(pane.outperf_fig, oc, benchmark_label=ticker),
        errors,
    )


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
    # rendering calls this for only the mounted view per
    # recompute and builds the others on first pick.
    if label == "Cumulative Performance":
        _update_line(pane.line_fig, prep.perf)
    elif label == "1Y Sharpe-z Line":
        _update_sharpe_line(pane.sharpe_fig, prep.sz_series)
    elif label == "Risk / Return":
        _update_scatter(pane.scatter_fig, prep.sel_window, prep.rets, meta)
    elif label == "Drawdown":
        _update_drawdown(pane.dd_fig, prep.dd)
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
    # Lazy: render only the currently-mounted view; the other
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
