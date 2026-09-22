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
from typing import TYPE_CHECKING

import ipywidgets as W

from ..config import (
    DEFAULT_BENCHMARK,
)
from .benchmarks import BenchmarkRegistry, BenchmarkSelect
from .charts import (
    ROLLING_BENCHMARK_STATS,
    CorrHeatmap,
    DecileChart,
    DrawdownChart,
    FactorCorrChart,
    LineChart,
    OutperformanceChart,
    RegimeProfileChart,
    ReturnDistChart,
    RiskProfileChart,
    RollingChart,
    ScatterChart,
    SharpeZChart,
    WeeklyScatterChart,
    rolling_stat_chips,
)
from .rails import ChipGroup
from .regime_controls import RegimeControls

if TYPE_CHECKING:
    # `state.py` imports this module, so the annotation cannot be a runtime
    # import — the same guard `platform` and `single_strategy` carry.
    from .state import DashboardState

#: The Multi-Strategy analysis-pane options.
#:
#: **One *Rolling* where there were two** (#368). *Rolling Correlation* and
#: *Rolling Beta* were two `RollingRefChart`s and two picker entries, while
#: rolling Sharpe and Calmar had their stats functions and no chart anywhere.
#: The statistic is a chip inside the view now, so both tabs draw all four
#: through one component.
ANALYSIS_OPTIONS: tuple[str, ...] = (
    "Cumulative Performance",
    "Outperformance",
    "1Y Sharpe-z Line",
    "Correlation Heatmap",
    "Risk / Return",
    "Drawdown",
    "Rolling",
    "Return Distribution",
)


def _make_benchmark_dropdown(
    description: str = "Benchmark",
    *,
    default: str = DEFAULT_BENCHMARK,
    width: str = "320px",
    registry: BenchmarkRegistry | None = None,
) -> W.Dropdown:
    """A benchmark selector. Every analysis-pane benchmark dropdown (Rolling /
    Outperformance / Correlation-Heatmap regime) and both picking tabs'
    *Table view* bars use this one factory. A blank
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


#: Single Strategy analysis-pane options. **Every one of these draws.**
#:
#: It was eight, three of which were dead ends: *PCA Analysis* and *Defensive
#: Scoring* were `_StubChart`s drawing *coming soon*, and *Performance
#: Ranking* drew the same placeholder because nothing ever passed it scores.
#: #367 retired all three — each into an issue of its own (#374, #375, #376),
#: so the intent outlives the placeholder — on the rule that a picker offering
#: a view the app cannot draw is a promise it does not keep.
SINGLE_ANALYSIS_OPTIONS: tuple[str, ...] = (
    "Weekly Scatter",
    "Return Distribution",
    "Factor Scatter",
    "Drawdown",
    "Rolling",
    "Decile",
    "Regime Profile",
    "Risk Profile",
)

#: Single-strategy analyses whose figure depends on the per-pane benchmark.
#:
#: *Rolling* is here **conditionally** — Correlation and Beta read a
#: benchmark, Sharpe and Calmar do not — so the visibility sync asks the
#: chip as well as the picker (#368).
_SINGLE_BENCHMARK_VIEWS: frozenset[str] = frozenset(
    {
        "Weekly Scatter",
        "Return Distribution",
        "Drawdown",
        # The decile view **cannot draw without one** — the benchmark is what
        # decides the buckets — and the regime profile draws the benchmark's
        # own three points beside the strategy's, so its regime sensitivity
        # reads against something.
        "Decile",
        "Regime Profile",
    }
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
    weekly_regime: RegimeControls
    retdist: ReturnDistChart
    factor: FactorCorrChart
    dd: DrawdownChart
    rolling: RollingChart
    rolling_chips: ChipGroup
    decile: DecileChart
    decile_regime: RegimeControls
    regime_profile: RegimeProfileChart
    regime: RegimeControls
    risk_profile: RiskProfileChart


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
    rolling: RollingChart
    rolling_chips: ChipGroup
    rolling_dd: BenchmarkSelect
    retdist: ReturnDistChart
    fresh: set[str] = field(default_factory=set)


def _make_single_analysis_pane(
    side_label: str,
    *,
    registry: BenchmarkRegistry | None = None,
    state: DashboardState | None = None,
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
    rolling = RollingChart()
    rolling_chips = ChipGroup(rolling_stat_chips(), value=rolling.stat, row=True)
    decile = DecileChart()
    # The decile view conditions on **one** bucket, so it keeps the bucket
    # chips the regime-profile view has no use for. Its own instance, because
    # two charts in one pane conditioning on one shared selection would make
    # a chip on a hidden view move a visible one.
    decile_regime = RegimeControls(state)
    regime_profile = RegimeProfileChart()
    # The Weekly Scatter's own regime (#382), with buckets: unlike the profile
    # below, it conditions on **one** bucket at a time, and it draws the
    # unconditioned cloud underneath rather than replacing it. Its own
    # instance for the same reason `decile_regime` is — two views each
    # conditioning their own chart is two selections, not one.
    weekly_regime = RegimeControls(state)

    # **No bucket control** (#363 dec. 8): all three buckets are the chart, so
    # there is nothing for a bucket chip to select. The *type* and *source*
    # are the Platform card's own controls, from the module both tabs import.
    regime = RegimeControls(state, buckets=False)
    risk_profile = RiskProfileChart()

    bench_dd = _make_benchmark_dropdown(registry=registry)

    view_layout = W.Layout(width="100%", padding="4px")
    views: dict[str, W.Widget] = {
        "Weekly Scatter": W.VBox(
            [
                weekly_regime.on,
                weekly_regime.types,
                weekly_regime.source,
                weekly_regime.buckets,
                weekly.fig,
            ],
            layout=view_layout,
        ),
        "Return Distribution": W.VBox(
            [retdist.fig, retdist.stats_grid], layout=view_layout
        ),
        "Factor Scatter": W.VBox([factor.fig], layout=view_layout),
        "Drawdown": W.VBox([dd.fig], layout=view_layout),
        "Rolling": W.VBox([rolling_chips, rolling.fig], layout=view_layout),
        "Decile": W.VBox(
            (
                [
                    decile_regime.on,
                    decile_regime.types,
                    decile_regime.source,
                    decile_regime.buckets,
                    decile.fig,
                ]
                if decile_regime is not None
                else [decile.fig]
            ),
            layout=view_layout,
        ),
        "Regime Profile": W.VBox(
            (
                [regime.on, regime.types, regime.source, regime_profile.fig]
                if regime is not None
                else [regime_profile.fig]
            ),
            layout=view_layout,
        ),
        "Risk Profile": W.VBox([risk_profile.fig], layout=view_layout),
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
        # *Rolling* reads a benchmark for two of its four statistics, so the
        # selector follows the chip as well as the picker. Hidden rather than
        # rebuilt, so switching Sharpe → Correlation finds the last benchmark
        # still chosen (#331 dec. 3, #368).
        shown = label in _SINGLE_BENCHMARK_VIEWS or (
            label == "Rolling" and rolling_chips.value in ROLLING_BENCHMARK_STATS
        )
        bench_dd.layout.display = "" if shown else "none"

    _sync_benchmark_visibility(default_label)
    rolling_chips.observe(
        lambda _c: _sync_benchmark_visibility(picker.value), names="value"
    )

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
        weekly_regime=weekly_regime,
        retdist=retdist,
        factor=factor,
        dd=dd,
        rolling=rolling,
        rolling_chips=rolling_chips,
        decile=decile,
        decile_regime=decile_regime,
        regime_profile=regime_profile,
        regime=regime,
        risk_profile=risk_profile,
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
    without conflict. The Rolling and Outperformance benchmark dropdowns live
    on the same row as the analysis picker and toggle visibility based on the
    active analysis — and, for Rolling, on which statistic its chip has
    selected (#368: Sharpe and Calmar do not read a benchmark).
    """
    line = LineChart()
    outperf = OutperformanceChart()
    sharpe = SharpeZChart()
    heat = CorrHeatmap()
    scatter = ScatterChart()
    dd = DrawdownChart()
    rolling = RollingChart()
    retdist = ReturnDistChart()

    # The statistic, as a chip group in the view itself rather than a fourth
    # entry in the analysis picker: *which rolling statistic* is a different
    # question from *which analysis*, and folding it into the picker is what
    # gave the tab two rolling entries and no home for the other two.
    rolling_chips = ChipGroup(rolling_stat_chips(), value=rolling.stat, row=True)
    rolling_benchmark_dd = _make_benchmark_dropdown(registry=registry)
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
        "Rolling": W.VBox([rolling_chips, rolling.fig], layout=view_layout),
        "Return Distribution": W.VBox(
            [retdist.fig, retdist.stats_grid], layout=view_layout
        ),
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
        # Rolling shows its benchmark only for the statistics that read one —
        # a *Rolling Sharpe vs SPTR* control would name a series the number
        # does not touch. Hidden, not rebuilt, so switching back to
        # Correlation finds the last benchmark still chosen (#331 dec. 3).
        rolling_benchmark_dd.layout.display = (
            ""
            if label == "Rolling" and rolling_chips.value in ROLLING_BENCHMARK_STATS
            else "none"
        )
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
    rolling_chips.observe(
        lambda _c: _sync_benchmark_visibility(picker.value), names="value"
    )
    heat_benchmark_chk.observe(_on_benchmark_chk, names="value")
    heat_regime_chk.observe(lambda _c: _sync_regime_controls(), names="value")

    header_row = W.HBox(
        [
            picker,
            rolling_benchmark_dd,
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
        rolling=rolling,
        rolling_chips=rolling_chips,
        rolling_dd=rolling_benchmark_dd,
        retdist=retdist,
    )
