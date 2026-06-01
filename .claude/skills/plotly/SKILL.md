---
name: plotly
description: Reference for building interactive charts with the Plotly Python package — plotly.express vs graph_objects, the Figure anatomy (traces/layout/frames), Figure vs FigureWidget, updating figures efficiently (batch_update, add_traces, update_layout), layout/styling (templates, axes, hovertemplate, shapes, colorscales), common chart recipes (line, scatter, heatmap, treemap, histogram, subplots), and rendering in Jupyter/Voila. Use whenever working with Plotly — creating or updating a chart, choosing express vs graph_objects, building a live FigureWidget, configuring axes/hover/legends/colors, or debugging why a figure won't update or rescale. Trigger on plotly, go.Figure, FigureWidget, plotly.express / px, add_trace, update_layout, batch_update, treemap/scatter/heatmap, hovertemplate, make_subplots.
---

# Plotly (Python)

Plotly renders interactive, browser-based charts from Python. This is a
reference for the **package**: its two APIs, the figure object, live updates,
styling, and common recipes. Conventions:
`import plotly.graph_objects as go` and `import plotly.express as px`.

## Two APIs

- **`plotly.express` (px)** — high-level; one call builds a whole figure
  from tidy data. Best for quick, standard charts.
  ```python
  fig = px.scatter(df, x="vol", y="ret", color="asset_class",
                   size="sharpe", hover_name="name")
  ```
- **`graph_objects` (go)** — low-level; you assemble traces and layout
  explicitly. Best for fine control, mixed/custom traces, and incremental
  updates. (`px` returns a `go.Figure`, so you can build with `px` then tweak
  with `go` methods.)

## Figure anatomy

A `go.Figure` has three parts: **`data`** (a list of traces), **`layout`**
(axes, title, legend, colors, shapes…), and **`frames`** (animation).

```python
fig = go.Figure(
    data=[go.Scatter(x=x, y=y, mode="lines", name="A")],
    layout=go.Layout(title="Demo", template="plotly_dark"),
)
fig.add_trace(go.Bar(x=x, y=y2))
fig.update_layout(yaxis_title="Return")
fig.update_traces(line_width=2, selector=dict(type="scatter"))
fig.update_xaxes(tickformat=".0%")
```

Common trace types: `Scatter` (lines/markers, `Scattergl` for many points),
`Bar`, `Heatmap`, `Treemap`, `Sunburst`, `Histogram`, `Box`, `Pie`,
`Candlestick`. `make_subplots` (from `plotly.subplots`) builds multi-panel
layouts.

## `Figure` vs `FigureWidget`

- **`go.Figure`** — static; render with `fig.show()` (or auto-display).
- **`go.FigureWidget`** — an **ipywidgets** widget: it renders live in
  Jupyter/Voila, supports **in-place mutation** that updates the existing
  chart, and can register callbacks (`fig.data[0].on_click`,
  `.on_selection`, `.on_hover`). Use it for dashboards / anything that
  updates after first render.

## Updating efficiently

Wrap edits in **`batch_update`** so the frontend renders one atomic frame
(no flicker):

```python
with fig.batch_update():
    fig.data[0].x = new_x
    fig.data[0].y = new_y
    fig.layout.title.text = "Updated"
```

To **replace the set of traces**, clear then add — the `fig.data` setter
only accepts a subset/reordering of *existing* traces, so assigning a brand
new list fails:

```python
with fig.batch_update():
    fig.data = ()                  # clear
    fig.add_traces(new_traces)     # add fresh ones
```

Plotly auto-rescales axes on data change unless you've pinned a range.

## Layout & styling

- **Templates:** `template="plotly_dark"` / `"plotly_white"`; override per
  figure via `update_layout`.
- **Axes:** `tickformat` (`".0%"`, `",.2f"`), `rangemode="tozero"`,
  `type="log"`, `title`.
- **Hover:** `hovermode="x unified"` (all traces at one x) or `"closest"`;
  custom `hovertemplate` with `%{x}`, `%{y}`, `%{customdata[0]}` and a
  trailing `<extra></extra>` to drop the trace-name box.
- **Reference lines / bands:** `layout.shapes` with `xref="paper"` (or
  `yref="paper"`) stay fixed across data updates and empty states.
- **Color:** continuous `colorscale` + `colorbar`; for diverging metrics
  (e.g. z-scores) set `cmid=0` so the midpoint maps to the neutral color.
- **Legend / margins:** `showlegend`, `legend=dict(...)`, `margin`.

## Common recipes

- **Line / area:** `go.Scatter(mode="lines", fill="tozeroy")`.
- **Scatter w/ encoded marker:** `marker=dict(size=…, color=…,
  colorscale=…, showscale=True)`.
- **Heatmap:** `go.Heatmap(z=matrix, x=cols, y=rows, colorscale="RdBu",
  zmid=0)`.
- **Treemap:** `go.Treemap(labels=…, parents=…, values=…,
  marker=dict(colors=…, colorscale=…, cmid=0))`. **`values` must be
  non-negative** — transform a signed metric (shift by its min, or rank)
  for sizing while coloring with the raw value.
- **Histogram overlay:** multiple `go.Histogram` + `barmode="overlay"` +
  `opacity`.
- **Subplots:** `make_subplots(rows, cols, shared_xaxes=True)` then
  `fig.add_trace(trace, row=r, col=c)`.

## Performance & correctness

- Always `batch_update` for multi-attribute edits.
- **Reuse** `FigureWidget` instances and mutate them; don't rebuild a new
  widget per update.
- Use `Scattergl` (WebGL) for large point counts.

## Jupyter / Voila

`FigureWidget` renders under Voila like any ipywidget. Control the toolbar
via `config={"displayModeBar": True, "modeBarButtonsToRemove": [...]}` (on
`show`/renderers). For static `Figure`, the active **renderer**
(`plotly.io.renderers`) decides output.

## Pitfalls

- Mixing `px`- and `go`-constructed objects without converting.
- Assigning a fresh list to `fig.data` (use clear-then-`add_traces`).
- Forgetting `batch_update` → visible flicker / multiple frames.
- Negative `values` in a `Treemap`/`Sunburst`.
- `hovertemplate` without `<extra></extra>` (leftover trace-name box).

## In this repo (brief)

Charts are `go.FigureWidget` instances built and mutated in `src/layout.py`;
the dark theme comes from `_chart_layout()`, and traces are colored
positionally from `LINE_PALETTE` in `src/style.py`. See `CLAUDE.md` for the
chart conventions, and the `ipywidgets` skill for the surrounding UI.
