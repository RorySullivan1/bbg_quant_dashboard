"""Analysis-pane widgets: the figure factories and the pane assembly.

An *analysis pane* is the repeated unit of the Multi-Strategy and Single
Strategy tabs: an analysis picker, an optional per-pane benchmark selector and
its dependent controls, and a stack of figures of which exactly one is mounted.

Each `_*_chart()` factory builds an empty `FigureWidget` with its axes, title,
and theme already set; `charts.py` fills it with data later. Building once and
updating in place is what keeps a benchmark change from rebuilding the widget
tree, so nothing here computes or fetches — the figures start empty by design.

`ANALYSIS_OPTIONS` and `SINGLE_ANALYSIS_OPTIONS` declare which views each tab
offers, and `_SINGLE_BENCHMARK_VIEWS` which of them reveal the benchmark
selector.

Each factory returns a typed pane (`AnalysisPane` / `SingleAnalysisPane`, #216)
rather than a bag of attributes, so a renderer reaching for a field it was never
given fails at construction instead of at render time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ipywidgets as W

from ..config import (
    DEFAULT_BENCHMARK,
)
from .benchmarks import BenchmarkRegistry, BenchmarkSelect
from .charts import (
    CorrHeatmap,
    DefensiveChart,
    DrawdownChart,
    FactorCorrChart,
    FactorScoringChart,
    LineChart,
    OutperformanceChart,
    PcaChart,
    PerfRankingChart,
    ReturnDistChart,
    RollingRefChart,
    ScatterChart,
    SharpeZChart,
    WeeklyScatterChart,
)

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

    With a `registry` the options track the live benchmark set, so a
    benchmark added at runtime reaches every selector, and the catalog indices
    ride along as a second source. Without one the selector starts on
    the curated `BENCHMARK_TICKERS` snapshot.

    The control is a `BenchmarkSelect` — a combobox behind a
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


# Single Strategy analysis-pane options. Drawdown and Factor scoring are
# functional; the trailing four are stubs.
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


@dataclass
class SingleAnalysisPane:
    """One Single-Strategy analysis pane: its widgets and every figure it owns.

    `views` maps a `SINGLE_ANALYSIS_OPTIONS` label to the box `stack` mounts;
    the charts are also held individually because a renderer redraws one chart,
    not a view. Each is a `Chart` (#223) owning its own figure, so a renderer
    calls `pane.weekly.update(...)` and cannot reach the wrong figure.
    """

    root: W.VBox
    picker: W.Dropdown
    bench_dd: BenchmarkSelect
    stack: W.Box
    views: dict[str, W.Widget]
    weekly: WeeklyScatterChart
    retdist: ReturnDistChart
    factor: FactorCorrChart
    dd: DrawdownChart
    ranking: PerfRankingChart
    factor_score: FactorScoringChart
    pca: PcaChart
    defensive: DefensiveChart


@dataclass
class AnalysisPane:
    """One Multi-Strategy analysis pane: its widgets and every figure it owns.

    `fresh` is the set of labels whose chart holds the current slice. The
    controller renders only the mounted view per recompute and adds others on
    first pick, so this is what distinguishes "not drawn yet" from "drawn and
    stale".

    Every chart field is a `Chart` (#223) owning its own figure, so a renderer
    calls `pane.heat.update(cm, …)` rather than pairing a loose figure with a
    loose updater.
    """

    root: W.VBox
    picker: W.Dropdown
    stack: W.Box
    views: dict[str, W.Widget]
    line: LineChart
    outperf: OutperformanceChart
    outperf_dd: BenchmarkSelect
    sharpe: SharpeZChart
    heat: CorrHeatmap
    heat_benchmark_chk: W.Checkbox
    heat_regime_chk: W.Checkbox
    heat_dd: BenchmarkSelect
    heat_dir: W.Dropdown
    heat_pct: W.Dropdown
    scatter: ScatterChart
    dd: DrawdownChart
    rcorr: RollingRefChart
    rcorr_dd: BenchmarkSelect
    rbeta: RollingRefChart
    rbeta_dd: BenchmarkSelect
    retdist: ReturnDistChart
    fresh: set[str] = field(default_factory=set)


def _make_single_analysis_pane(
    side_label: str, *, registry: BenchmarkRegistry | None = None
) -> SingleAnalysisPane:
    """Build one Single-Strategy analysis pane — a self-contained 50%-width
    column with an analysis picker, a per-pane benchmark dropdown (shown only for
    the benchmark-dependent views), and every figure pre-allocated.

    Mirrors `_make_analysis_pane` (Multi-Strategy) so the two single-strategy
    panes render the same option set side-by-side for comparison. The *shared*
    tab-level strategy picker feeds both panes; each pane only chooses which
    analysis and which benchmark to draw, so users can contrast two views of the
    same strategy.
    """
    weekly = WeeklyScatterChart()
    retdist = ReturnDistChart()
    factor = FactorCorrChart()
    dd = DrawdownChart()
    ranking = PerfRankingChart()
    factor_score = FactorScoringChart()
    pca = PcaChart()
    defensive = DefensiveChart()

    bench_dd = _make_benchmark_dropdown(registry=registry)

    view_layout = W.Layout(width="100%", padding="4px")
    views: dict[str, W.Widget] = {
        "Weekly Scatter": W.VBox([weekly.fig], layout=view_layout),
        "Return Distribution": W.VBox(
            [retdist.fig, retdist.stats_grid], layout=view_layout
        ),
        "Factor Scatter": W.VBox([factor.fig], layout=view_layout),
        "Drawdown": W.VBox([dd.fig], layout=view_layout),
        "Performance Ranking": W.VBox([ranking.fig], layout=view_layout),
        "Factor Scoring": W.VBox([factor_score.fig], layout=view_layout),
        "PCA Analysis": W.VBox([pca.fig], layout=view_layout),
        "Defensive Scoring": W.VBox([defensive.fig], layout=view_layout),
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

    return SingleAnalysisPane(
        root=root,
        picker=picker,
        bench_dd=bench_dd,
        stack=stack,
        views=views,
        weekly=weekly,
        retdist=retdist,
        factor=factor,
        dd=dd,
        ranking=ranking,
        factor_score=factor_score,
        pca=pca,
        defensive=defensive,
    )


def _make_analysis_pane(
    side_label: str, *, registry: BenchmarkRegistry | None = None
) -> AnalysisPane:
    """Build a self-contained analysis pane with all 9 figures pre-allocated.

    Returns an `AnalysisPane` carrying every plotly `FigureWidget` the
    `_update_*` helpers need, plus the picker widget, the swap container,
    a `views` dict keyed by `ANALYSIS_OPTIONS` labels, and the root VBox.

    Plotly figures are independent widget instances; each pane owns its
    own set so the two panes can render the same analysis side-by-side
    without conflict. The Rolling-Correlation / Rolling-Beta benchmark
    dropdowns live on the same row as the analysis picker and toggle
    visibility based on the active analysis.
    """
    line = LineChart()
    outperf = OutperformanceChart()
    sharpe = SharpeZChart()
    heat = CorrHeatmap()
    scatter = ScatterChart()
    dd = DrawdownChart()
    rcorr = RollingRefChart(
        title_prefix="Rolling Correlation",
        y_label="Correlation",
        ref_y=0.0,
    )
    rbeta = RollingRefChart(
        title_prefix="Rolling Beta",
        y_label="Beta",
        ref_y=1.0,
    )
    retdist = ReturnDistChart()

    rcorr_benchmark_dd = _make_benchmark_dropdown(registry=registry)
    rbeta_benchmark_dd = _make_benchmark_dropdown(registry=registry)
    outperf_benchmark_dd = _make_benchmark_dropdown(registry=registry)

    # Correlation-Heatmap controls, revealed progressively: "Benchmark" exposes
    # the benchmark dropdown and a nested "Regime" checkbox, which in turn
    # exposes the tail direction and a 0-100% (step 5) tail size. `heat_dir`
    # passes straight to `regime_corr_matrix` (`<` = worst/below-pct,
    # `>` = best). Read at Refresh time, like the other per-pane dropdowns.
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
        "Cumulative Performance": W.VBox([line.fig], layout=view_layout),
        "Outperformance": W.VBox([outperf.fig], layout=view_layout),
        "1Y Sharpe-z Line": W.VBox([sharpe.fig], layout=view_layout),
        "Correlation Heatmap": W.VBox([heat.fig], layout=view_layout),
        "Risk / Return": W.VBox([scatter.fig], layout=view_layout),
        "Drawdown": W.VBox([dd.fig], layout=view_layout),
        "Rolling Correlation": W.VBox([rcorr.fig], layout=view_layout),
        "Return Distribution": W.VBox(
            [retdist.fig, retdist.stats_grid], layout=view_layout
        ),
        "Rolling Beta": W.VBox([rbeta.fig], layout=view_layout),
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

    return AnalysisPane(
        root=root,
        picker=picker,
        stack=stack,
        views=views,
        line=line,
        outperf=outperf,
        outperf_dd=outperf_benchmark_dd,
        sharpe=sharpe,
        heat=heat,
        heat_benchmark_chk=heat_benchmark_chk,
        heat_regime_chk=heat_regime_chk,
        heat_dd=heat_benchmark_dd,
        heat_dir=heat_dir,
        heat_pct=heat_pct,
        scatter=scatter,
        dd=dd,
        rcorr=rcorr,
        rcorr_dd=rcorr_benchmark_dd,
        rbeta=rbeta,
        rbeta_dd=rbeta_benchmark_dd,
        retdist=retdist,
    )
