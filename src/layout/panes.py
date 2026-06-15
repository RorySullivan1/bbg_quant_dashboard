from __future__ import annotations

from types import SimpleNamespace

import ipywidgets as W
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from ipydatagrid import DataGrid

from ..config import (
    BENCHMARK_TICKERS,
    DEFAULT_BENCHMARK,
    LOOKBACK_YEARS,
)
from .theme import SHARPE_WINDOW_LABEL, _chart_layout, _h_ref

ANALYSIS_OPTIONS: tuple[str, ...] = (
    "Cumulative Performance",
    "Outperformance",
    "1Y Sharpe-z Line",
    "Correlation Heatmap",
    "Risk / Return",
    "Drawdown",
    "Rolling Correlation",
    "Return Distribution",
    "Rolling Beta",
)


def _make_benchmark_dropdown(
    description: str = "Benchmark", *, default: str = DEFAULT_BENCHMARK
) -> W.Dropdown:
    """A per-pane benchmark selector. Every analysis-pane benchmark dropdown
    (Rolling Correlation / Rolling Beta / Outperformance / Correlation-Heatmap
    regime) is the same widget over `BENCHMARK_TICKERS`, so they share this
    factory."""
    return W.Dropdown(
        options=BENCHMARK_TICKERS,
        value=default,
        description=description,
        style={"description_width": "80px"},
        layout=W.Layout(width="320px"),
    )


def _line_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Cumulative Performance ({LOOKBACK_YEARS}Y)",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Rebased = 100"),
        )
    )


def _outperformance_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Outperformance ({LOOKBACK_YEARS}Y)",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Excess return (pp)"),
            shapes=[_h_ref(0.0)],
        )
    )


def _heatmap() -> go.FigureWidget:
    return go.FigureWidget(
        data=[
            go.Heatmap(
                z=np.zeros((2, 2)),
                x=["", " "],
                y=["", " "],
                colorscale="RdBu",
                reversescale=True,
                zmin=-1,
                zmax=1,
                zmid=0,
                colorbar=dict(title="ρ", tickformat=".1f", thickness=14),
                hovertemplate="%{y} vs %{x}<br>ρ = %{z:.2f}<extra></extra>",
            )
        ],
        layout=_chart_layout(
            title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
            margin=dict(t=40, b=70, l=120, r=20),
            xaxis=dict(tickangle=-75, tickfont=dict(size=10)),
            yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        ),
    )


def _sharpe_line_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"{SHARPE_WINDOW_LABEL} Rolling Sharpe — z-score (last 1Y)",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Sharpe z-score"),
            shapes=[_h_ref(0.0)],
        )
    )


def _scatter_chart() -> go.FigureWidget:
    return go.FigureWidget(
        data=[
            go.Scatter(
                mode="markers",
                x=[],
                y=[],
                marker=dict(size=[], color=[], line=dict(width=0)),
                text=[],
                customdata=[],
                hovertemplate=(
                    "%{text}<br>Vol %{x:.2%}<br>Return %{y:.2%}"
                    "<br>Sharpe %{customdata:.2f}<extra></extra>"
                ),
            )
        ],
        layout=_chart_layout(
            title=f"Risk / Return — {LOOKBACK_YEARS}Y",
            hovermode="closest",
            xaxis=dict(
                title=f"Annualized Volatility ({LOOKBACK_YEARS}Y)",
                tickformat=".0%",
                rangemode="tozero",
            ),
            yaxis=dict(
                title=f"Annualized Return ({LOOKBACK_YEARS}Y)",
                tickformat=".0%",
            ),
        ),
    )


def _drawdown_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Drawdown — {LOOKBACK_YEARS}Y",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Drawdown", tickformat=".0%"),
            shapes=[_h_ref(0.0)],
        )
    )


def _rolling_ref_chart(
    *, title_prefix: str, y_label: str, ref_y: float
) -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"{title_prefix} — {SHARPE_WINDOW_LABEL} rolling",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title=y_label),
            shapes=[_h_ref(ref_y)],
        )
    )


def _return_dist_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Return Distribution — {LOOKBACK_YEARS}Y daily returns",
            barmode="overlay",
            xaxis=dict(title="Daily return", tickformat=".1%"),
            yaxis=dict(title="Frequency"),
        )
    )


def _return_dist_stats_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=92,
        base_row_header_size=180,
        layout=W.Layout(width="100%", height="180px"),
    )
    return grid


def _weekly_scatter_chart() -> go.FigureWidget:
    """Single Strategy Section 3 (v0.9.0): weekly returns vs the benchmark, with
    an OLS β line drawn by `_update_weekly_scatter`."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="Weekly returns vs benchmark",
            hovermode="closest",
            xaxis=dict(
                title="Benchmark weekly return", tickformat=".1%", zeroline=True
            ),
            yaxis=dict(title="Strategy weekly return", tickformat=".1%", zeroline=True),
        )
    )


def _factor_corr_chart() -> go.FigureWidget:
    """Single Strategy Section 3 (v0.9.0): the strategy's monthly correlation to
    the equity-risk-premium (x) and term-premium (y) factors, colored by each
    month's risk-adjusted return. Axes fixed to the correlation range."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="Monthly factor correlation",
            hovermode="closest",
            xaxis=dict(
                title="Corr to equity risk premium", range=[-1, 1], zeroline=True
            ),
            yaxis=dict(title="Corr to term premium", range=[-1, 1], zeroline=True),
        )
    )


def _make_analysis_pane(side_label: str) -> SimpleNamespace:
    """Build a self-contained analysis pane with all 9 figures pre-allocated.

    Returns a `SimpleNamespace` carrying every plotly `FigureWidget` the
    `_update_*` helpers need, plus the picker widget, the swap container,
    a `views` dict keyed by `ANALYSIS_OPTIONS` labels, and the root VBox.

    Plotly figures are independent widget instances; each pane owns its
    own set so the two panes can render the same analysis side-by-side
    without conflict. The Rolling-Correlation / Rolling-Beta benchmark
    dropdowns live on the same row as the analysis picker and toggle
    visibility based on the active analysis.
    """
    line_fig = _line_chart()
    outperf_fig = _outperformance_chart()
    sharpe_fig = _sharpe_line_chart()
    heat_fig = _heatmap()
    scatter_fig = _scatter_chart()
    dd_fig = _drawdown_chart()
    rcorr_fig = _rolling_ref_chart(
        title_prefix="Rolling Correlation",
        y_label="Correlation",
        ref_y=0.0,
    )
    rbeta_fig = _rolling_ref_chart(
        title_prefix="Rolling Beta",
        y_label="Beta",
        ref_y=1.0,
    )
    retdist_fig = _return_dist_chart()
    retdist_stats_grid = _return_dist_stats_grid()

    rcorr_benchmark_dd = _make_benchmark_dropdown()
    rbeta_benchmark_dd = _make_benchmark_dropdown()
    outperf_benchmark_dd = _make_benchmark_dropdown()

    # Correlation-Heatmap regime controls. The checkbox reveals a benchmark
    # selector, a Down/Up tail direction toggle, and a 0-100% (step 5) tail
    # size. When on, the heatmap is conditioned on the benchmark-return tail
    # and the benchmark is added to the matrix (see `_render_pane`). Read at
    # Refresh-prices time only, like the other per-pane benchmark dropdowns.
    # v0.7.5: a "Benchmark" checkbox reveals the benchmark dropdown + a nested
    # "Regime" checkbox; ticking "Regime" reveals the >/< tail-direction
    # dropdown + the tail size. `heat_dir` value is the direction string passed
    # straight to `regime_corr_matrix` (`<` = worst/below-pct, `>` = best).
    heat_benchmark_chk = W.Checkbox(
        value=False,
        description="Benchmark",
        indent=False,
        layout=W.Layout(width="120px"),
    )
    heat_benchmark_dd = _make_benchmark_dropdown()
    heat_regime_chk = W.Checkbox(
        value=False,
        description="Regime",
        indent=False,
        layout=W.Layout(width="110px"),
    )
    heat_dir = W.Dropdown(
        options=[("<", "down"), (">", "up")],
        value="down",
        layout=W.Layout(width="70px"),
    )
    heat_pct = W.Dropdown(
        options=[(f"{p}%", p) for p in range(0, 101, 5)],
        value=100,
        description="Tail",
        style={"description_width": "40px"},
        layout=W.Layout(width="160px"),
    )

    view_layout = W.Layout(width="100%", padding="4px")
    views: dict[str, W.Widget] = {
        "Cumulative Performance": W.VBox([line_fig], layout=view_layout),
        "Outperformance": W.VBox([outperf_fig], layout=view_layout),
        "1Y Sharpe-z Line": W.VBox([sharpe_fig], layout=view_layout),
        "Correlation Heatmap": W.VBox([heat_fig], layout=view_layout),
        "Risk / Return": W.VBox([scatter_fig], layout=view_layout),
        "Drawdown": W.VBox([dd_fig], layout=view_layout),
        "Rolling Correlation": W.VBox([rcorr_fig], layout=view_layout),
        "Return Distribution": W.VBox(
            [retdist_fig, retdist_stats_grid], layout=view_layout
        ),
        "Rolling Beta": W.VBox([rbeta_fig], layout=view_layout),
    }

    default_label = (
        "Cumulative Performance" if side_label == "left" else "Correlation Heatmap"
    )
    picker = W.Dropdown(
        options=list(ANALYSIS_OPTIONS),
        value=default_label,
        description="Analysis",
        style={"description_width": "70px"},
        layout=W.Layout(width="360px"),
    )

    def _sync_regime_controls() -> None:
        # Cascade (Correlation Heatmap only): Benchmark on → show the benchmark
        # dropdown + the nested Regime checkbox; Regime on → show the >/< tail
        # dropdown + the tail size.
        is_heat = picker.value == "Correlation Heatmap"
        bench_on = is_heat and heat_benchmark_chk.value
        regime_on = bench_on and heat_regime_chk.value
        for w in (heat_benchmark_dd, heat_regime_chk):
            w.layout.display = "" if bench_on else "none"
        for w in (heat_dir, heat_pct):
            w.layout.display = "" if regime_on else "none"

    def _sync_benchmark_visibility(label: str) -> None:
        rcorr_benchmark_dd.layout.display = (
            "" if label == "Rolling Correlation" else "none"
        )
        rbeta_benchmark_dd.layout.display = "" if label == "Rolling Beta" else "none"
        outperf_benchmark_dd.layout.display = (
            "" if label == "Outperformance" else "none"
        )
        heat_benchmark_chk.layout.display = (
            "" if label == "Correlation Heatmap" else "none"
        )
        _sync_regime_controls()

    def _on_benchmark_chk(_c) -> None:
        # Unticking Benchmark also clears Regime so the chart reverts to plain
        # full-sample correlation (the nested control can't outlive its parent).
        if not heat_benchmark_chk.value and heat_regime_chk.value:
            heat_regime_chk.value = False
        _sync_regime_controls()

    _sync_benchmark_visibility(default_label)
    heat_benchmark_chk.observe(_on_benchmark_chk, names="value")
    heat_regime_chk.observe(lambda _c: _sync_regime_controls(), names="value")

    header_row = W.HBox(
        [
            picker,
            rcorr_benchmark_dd,
            rbeta_benchmark_dd,
            outperf_benchmark_dd,
            heat_benchmark_chk,
            heat_benchmark_dd,
            heat_regime_chk,
            heat_dir,
            heat_pct,
        ],
        layout=W.Layout(
            width="100%",
            align_items="center",
            margin="0 0 6px 0",
        ),
    )
    stack = W.Box(
        [views[default_label]],
        layout=W.Layout(width="100%"),
    )

    def _on_pick(change):
        label = change["new"]
        _sync_benchmark_visibility(label)
        stack.children = (views[label],)

    picker.observe(_on_pick, names="value")

    root = W.VBox(
        [header_row, stack],
        layout=W.Layout(width="50%"),
    )
    root.add_class("bbg-card")

    return SimpleNamespace(
        root=root,
        picker=picker,
        stack=stack,
        views=views,
        # Labels whose figure is populated for the current slice (Workstream D
        # lazy rendering). The builder renders only the mounted view per
        # recompute and adds others here on first pick.
        fresh=set(),
        line_fig=line_fig,
        outperf_fig=outperf_fig,
        outperf_dd=outperf_benchmark_dd,
        sharpe_fig=sharpe_fig,
        heat_fig=heat_fig,
        heat_benchmark_chk=heat_benchmark_chk,
        heat_regime_chk=heat_regime_chk,
        heat_dd=heat_benchmark_dd,
        heat_dir=heat_dir,
        heat_pct=heat_pct,
        scatter_fig=scatter_fig,
        dd_fig=dd_fig,
        rcorr_fig=rcorr_fig,
        rcorr_dd=rcorr_benchmark_dd,
        rbeta_fig=rbeta_fig,
        rbeta_dd=rbeta_benchmark_dd,
        retdist_fig=retdist_fig,
        retdist_stats_grid=retdist_stats_grid,
    )
