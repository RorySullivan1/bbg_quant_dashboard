---
name: plotly
description: Build and maintain the Plotly charts in this BQuant dashboard — FigureWidget views inside the analysis panes, atomic updates via batch_update, trace replacement, the dark plotly_dark theme, positional LINE_PALETTE coloring, and paper-referenced reference lines. Use this skill whenever the user wants to add, change, or debug a chart, trace, axis, hover, color, legend, or chart-update behavior in the dashboard, or asks why a chart isn't updating, rescaling, or coloring correctly. Trigger on phrases like "add an analysis type", "the chart won't update", "fix the hover", "change the line colors", "the y-axis doesn't rescale", "add a reference line", "FigureWidget", "batch_update", "the two panes share data", or any work on the dashboard's charts in src/layout.py. Distinct from widget/layout work — use the ipywidgets skill for controls, panels, tabs, and grids.
---

# plotly (this dashboard)

Expert Plotly work scoped to the `bbg_quant_dashboard` charts. All charts
are interactive `FigureWidget`s built and updated in `src/layout.py`;
colors and the dark theme come from `src/style.py`. Goal: changes that
respect the pre-allocated-figure / atomic-update model already in place.

## Read first

- `src/layout.py` — `_make_analysis_pane(side)` builds a self-contained
  `AnalysisPane`; `_chart_layout()` defines the dark theme overrides; the
  `_update_*` helpers mutate each FigureWidget. `_recompute()` preps one
  data slice and renders BOTH panes from it.
- `src/style.py` — `LINE_PALETTE` (high-chroma, anchored by Bloomberg
  orange `#FFA000` + Barclays cyan `#00B5E2`) and the chart color tokens
  on `Color`: `CHART_BG`, `CHART_GRID`, `CHART_AXIS`, `CHART_TEXT`,
  `CHART_TITLE`, `CHART_HOVER_BG`.
- `src/config.py` — `CHART_HEIGHT` (520px), `SHARPE_WINDOW`,
  `LOOKBACK_YEARS`.
- `src/stats.py` — every series feeding a chart (cum_perf, drawdown,
  rolling_*, corr/regime matrices, distributions, etc.). Charts render
  what stats computes; don't compute analytics inside `_update_*`.

## Non-negotiable update model

- **One FigureWidget per analysis type per pane, pre-allocated.** Each
  of the 9 analysis types owns a fresh `FigureWidget` instance per pane,
  so the two panes never share a figure. A picker change swaps
  `pane.stack.children` to the relevant pre-built view — **no recompute,
  no fetch.**
- **Every mutation goes through `fig.batch_update()`** so the frontend
  sees a single atomic frame. Wrap all layout/trace edits in one
  `with fig.batch_update():` block.
- **Replace traces with `fig.data = ()` then `fig.add_traces(...)`.**
  Plotly's `fig.data` setter only accepts a subset of existing traces,
  so clear-then-add is the correct idiom — do not assign a new list of
  fresh traces directly to `fig.data`.
- **Recompute is eager:** every Refresh-prices click preps the
  selected-set slice once and renders all 9 views in both panes, so
  swapping the picker afterward is instant. Per-pane benchmark dropdowns,
  the heatmap Regime checkbox/benchmark/direction/tail, etc. are read at
  recompute time only — changing them alone does not refresh (Refresh
  prices does).

## Theme & color

- Charts are **dark** (`plotly_dark` template + `_chart_layout()`
  overrides on `Color.CHART_BG` near-black `#0d1117`); the rest of the
  chrome stays light. Only charts are dark.
- **One color identity per strategy:** every trace (line, bar, scatter
  point) uses a positional `LINE_PALETTE` color keyed by the strategy's
  index in the selected ticker set — the same key the perf grid's "Chart
  Color" swatch uses. Per-chart legends are **off** (`display_legend`
  false) because the grid is the universal legend. Don't re-enable
  per-trace legends; don't color by anything other than position.
- All charts render at the same `CHART_HEIGHT` so the two panes line up.

## Axes, hover, reference lines

- **Plotly auto-fits the y-axis** on data replacement — no manual
  scale-rebinding needed (that was the bqplot era).
- Line / drawdown / sharpe-z / rolling-ref charts draw a dashed
  reference line via `layout.shapes` with `xref="paper"` so it stays put
  across data updates and empty states. Use the same pattern for new
  reference lines rather than a constant-y scatter trace.
- Line charts use `hovermode="x unified"` (all selected tickers at one
  date in a single tooltip). The risk/return scatter hover shows ticker
  name, ann. vol %, ann. return %, ann. Sharpe (2dp). Keep hover
  templates consistent when adding traces.
- The Plotly modebar (zoom/pan/autoscale/PNG) stays visible top-right.

## Adding a new analysis type

1. Add the option to the pane's analysis picker and allocate a fresh
   `FigureWidget` for it in `_make_analysis_pane`.
2. Add an `_update_<name>(fig, prep, ...)` helper that does all mutation
   inside `batch_update()` using the clear-then-`add_traces` idiom and
   positional `LINE_PALETTE` colors.
3. Compute the underlying series in `src/stats.py`, not in the updater.
4. If it needs a benchmark / extra control, add a per-pane dropdown on
   the picker row (visible only for this analysis), read at recompute
   time — mirror Outperformance / Rolling Correlation / Rolling Beta.
5. Call the updater from `_recompute()` for both panes.

## Verify (off-terminal)

```python
from src.layout import build_app
build_app()   # deterministic mock prices, full render
```

Then: pick 2+ tickers, click Refresh prices — both panes' mounted views
update and all 9 pre-built views populate; swapping a pane's picker
changes only that pane; setting both pickers to the same analysis renders
two independent figures; the modebar is present; `x unified` hover shows
all tickers; the dashed reference line holds across updates.

## Out of scope / pitfalls

- Don't recompute or fetch on a picker change — swap the pre-built view.
- Don't assign a fresh list to `fig.data` — clear with `()` then
  `add_traces`.
- Don't mutate a figure outside `batch_update()`.
- Don't share a FigureWidget between panes.
- Don't color by asset class or re-enable per-chart legends — the grid
  is the legend, color is positional.
- Widget/layout/grid changes belong in the **ipywidgets** skill.
