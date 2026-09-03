from __future__ import annotations

from types import SimpleNamespace

import ipywidgets as W
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from ipydatagrid import DataGrid

from ..config import (
    DEFAULT_BENCHMARK,
    LOOKBACK_YEARS,
)
from ..style import Color
from .benchmarks import BenchmarkRegistry, BenchmarkSelect
from .theme import SHARPE_WINDOW_LABEL, _chart_layout, _h_ref, _palette_color

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
    description: str = "Benchmark",
    *,
    default: str = DEFAULT_BENCHMARK,
    width: str = "320px",
    registry: BenchmarkRegistry | None = None,
) -> W.Dropdown:
    """A benchmark selector. Every analysis-pane benchmark dropdown (Rolling
    Correlation / Rolling Beta / Outperformance / Correlation-Heatmap regime)
    and the Quantitative-filter benchmark rows use this one factory. A blank
    `description` leaves no label gap.

    With a `registry` (#190) the options track the live benchmark set, so a
    benchmark added at runtime reaches every selector, and the catalog indices
    ride along as a second source (#191). Without one the selector starts on
    the curated `BENCHMARK_TICKERS` snapshot.

    The control is a `BenchmarkSelect` (#192) — a combobox behind a
    Dropdown-shaped surface, so it type-filters the list *and* accepts a ticker
    that is not on it, while `.value` stays a resolved ticker for every
    existing caller."""
    dd = BenchmarkSelect(
        description=description,
        default=default,
        width=width,
    )
    if registry is not None:
        registry.register(dd, include_catalog=True)
    return dd


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
    a quadratic fit line (β + convexity) drawn by `_update_weekly_scatter`.

    The two traces (markers + fit line) and the β/convexity annotation are
    **pre-allocated here** so ``_update_weekly_scatter`` mutates them in place
    (`.x` / `.y` / `.text`) rather than replacing the trace tuple. An in-place
    restyle repaints reliably across ipywidgets/plotly widget-manager versions,
    whereas a *same-count* delete-then-re-add (this chart always has exactly two
    traces) can be dropped by older frontends — the repaint bug this chart hit
    on BQuant."""
    fig = go.FigureWidget(
        layout=_chart_layout(
            title="Weekly returns vs benchmark",
            hovermode="closest",
            xaxis=dict(
                title="Benchmark weekly return", tickformat=".1%", zeroline=True
            ),
            yaxis=dict(title="Strategy weekly return", tickformat=".1%", zeroline=True),
        )
    )
    # Trace 0 = weekly-return markers; trace 1 = the quadratic fit line. Both
    # start empty and are filled in place on update.
    fig.add_trace(
        go.Scatter(
            x=[],
            y=[],
            mode="markers",
            marker=dict(size=6, color=_palette_color(0), line=dict(width=0)),
            name="weekly",
            hovertemplate="bench %{x:.2%}<br>strat %{y:.2%}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[],
            y=[],
            mode="lines",
            line=dict(color=Color.CHART_AXIS.value, dash="dash", width=1.5),
            name="quadratic fit",
            hoverinfo="skip",
        )
    )
    # Pre-allocated β/convexity/R² annotation, toggled + retexted in place.
    fig.add_annotation(
        x=0.02,
        y=0.98,
        xref="paper",
        yref="paper",
        showarrow=False,
        align="left",
        text="",
        font=dict(color=Color.CHART_TEXT.value, size=11),
        visible=False,
    )
    return fig


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


def _factor_scoring_chart() -> go.FigureWidget:
    """Single Strategy analysis (v0.9.0): a bar chart of the strategy's β to the
    macro-factor proxies (equity risk premium / term premium / trend), filled by
    `_update_factor_scoring`."""
    return go.FigureWidget(
        data=[
            go.Bar(
                x=[],
                y=[],
                marker=dict(color=[]),
                hovertemplate="%{x}<br>β %{y:.2f}<extra></extra>",
            )
        ],
        layout=_chart_layout(
            title=f"Factor scoring — β to macro factors ({LOOKBACK_YEARS}Y)",
            xaxis=dict(title="Factor"),
            yaxis=dict(title="Beta", zeroline=True),
            shapes=[_h_ref(0.0)],
        ),
    )


def _perf_ranking_chart() -> go.FigureWidget:
    """Single Strategy analysis (v0.9.0): a radar/spider chart ranking the
    strategy across performance metrics. Metrics are wired in a later pass;
    `_update_perf_ranking` shows a placeholder until then."""
    return go.FigureWidget(
        data=[go.Scatterpolar(r=[], theta=[], fill="toself")],
        layout=_chart_layout(
            title="Performance ranking",
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        ),
    )


def _pca_chart() -> go.FigureWidget:
    """Single Strategy analysis (v0.9.0, stub): a PCA scree chart — per-component
    explained-variance bars with a cumulative line on a secondary axis."""
    return go.FigureWidget(
        data=[
            go.Bar(x=[], y=[], name="Explained"),
            go.Scatter(x=[], y=[], mode="lines+markers", name="Cumulative", yaxis="y2"),
        ],
        layout=_chart_layout(
            title="PCA analysis",
            xaxis=dict(title="Principal component"),
            yaxis=dict(title="Explained variance", tickformat=".0%"),
            yaxis2=dict(
                title="Cumulative",
                overlaying="y",
                side="right",
                tickformat=".0%",
                range=[0, 1],
            ),
        ),
    )


def _defensive_chart() -> go.FigureWidget:
    """Single Strategy analysis (v0.9.0, stub): a defensive-scoring bar chart."""
    return go.FigureWidget(
        data=[go.Bar(x=[], y=[])],
        layout=_chart_layout(
            title="Defensive scoring",
            xaxis=dict(title="Metric"),
            yaxis=dict(title="Score"),
        ),
    )


# Single Strategy analysis-pane options (v0.9.0). The first three are the
# original Section 3 analytics; the rest are added per the v0.9.0 deep-dive
# (Drawdown + Factor scoring are functional, the others are stubs).
SINGLE_ANALYSIS_OPTIONS: tuple[str, ...] = (
    "Weekly Scatter",
    "Return Distribution",
    "Factor Scatter",
    "Drawdown",
    "Performance Ranking",
    "Factor Scoring",
    "PCA Analysis",
    "Defensive Scoring",
)

# Single-strategy analyses whose figure depends on the per-pane benchmark.
_SINGLE_BENCHMARK_VIEWS: frozenset[str] = frozenset(
    {"Weekly Scatter", "Return Distribution", "Drawdown"}
)


def _make_single_analysis_pane(
    side_label: str, *, registry: BenchmarkRegistry | None = None
) -> SimpleNamespace:
    """Build one Single-Strategy analysis pane — a self-contained 50%-width
    column with an analysis picker, a per-pane benchmark dropdown (shown only for
    the benchmark-dependent views), and every figure pre-allocated.

    Mirrors `_make_analysis_pane` (Multi-Strategy) so the two single-strategy
    panes render the same option set side-by-side for comparison. The *shared*
    tab-level strategy picker feeds both panes; each pane only chooses which
    analysis and which benchmark to draw, so users can contrast two views of the
    same strategy.
    """
    weekly_fig = _weekly_scatter_chart()
    retdist_fig = _return_dist_chart()
    retdist_stats_grid = _return_dist_stats_grid()
    factor_fig = _factor_corr_chart()
    dd_fig = _drawdown_chart()
    ranking_fig = _perf_ranking_chart()
    factor_score_fig = _factor_scoring_chart()
    pca_fig = _pca_chart()
    defensive_fig = _defensive_chart()

    bench_dd = _make_benchmark_dropdown(registry=registry)

    view_layout = W.Layout(width="100%", padding="4px")
    views: dict[str, W.Widget] = {
        "Weekly Scatter": W.VBox([weekly_fig], layout=view_layout),
        "Return Distribution": W.VBox(
            [retdist_fig, retdist_stats_grid], layout=view_layout
        ),
        "Factor Scatter": W.VBox([factor_fig], layout=view_layout),
        "Drawdown": W.VBox([dd_fig], layout=view_layout),
        "Performance Ranking": W.VBox([ranking_fig], layout=view_layout),
        "Factor Scoring": W.VBox([factor_score_fig], layout=view_layout),
        "PCA Analysis": W.VBox([pca_fig], layout=view_layout),
        "Defensive Scoring": W.VBox([defensive_fig], layout=view_layout),
    }

    default_label = "Weekly Scatter" if side_label == "left" else "Factor Scatter"
    picker = W.Dropdown(
        options=list(SINGLE_ANALYSIS_OPTIONS),
        value=default_label,
        description="Analysis",
        style={"description_width": "70px"},
        layout=W.Layout(width="360px"),
    )

    def _sync_benchmark_visibility(label: str) -> None:
        bench_dd.layout.display = "" if label in _SINGLE_BENCHMARK_VIEWS else "none"

    _sync_benchmark_visibility(default_label)

    header_row = W.HBox(
        [picker, bench_dd],
        layout=W.Layout(width="100%", align_items="center", margin="0 0 6px 0"),
    )
    stack = W.Box([views[default_label]], layout=W.Layout(width="100%"))

    def _on_pick(change):
        label = change["new"]
        _sync_benchmark_visibility(label)
        stack.children = (views[label],)

    picker.observe(_on_pick, names="value")

    root = W.VBox([header_row, stack], layout=W.Layout(width="50%"))
    root.add_class("bbg-card")

    return SimpleNamespace(
        root=root,
        picker=picker,
        bench_dd=bench_dd,
        stack=stack,
        views=views,
        weekly_fig=weekly_fig,
        retdist_fig=retdist_fig,
        retdist_stats_grid=retdist_stats_grid,
        factor_fig=factor_fig,
        dd_fig=dd_fig,
        ranking_fig=ranking_fig,
        factor_score_fig=factor_score_fig,
        pca_fig=pca_fig,
        defensive_fig=defensive_fig,
    )


def _make_analysis_pane(
    side_label: str, *, registry: BenchmarkRegistry | None = None
) -> SimpleNamespace:
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

    rcorr_benchmark_dd = _make_benchmark_dropdown(registry=registry)
    rbeta_benchmark_dd = _make_benchmark_dropdown(registry=registry)
    outperf_benchmark_dd = _make_benchmark_dropdown(registry=registry)

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
    heat_benchmark_dd = _make_benchmark_dropdown(registry=registry)
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
