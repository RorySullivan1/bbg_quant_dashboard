# Visual design system

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

The whole UI renders on a cohesive **dark technical chrome** (v0.6.5): the
chrome shares the charts' near-black surface, the title is a bold masthead
with an accent rule, buttons/controls/grids are dark-themed, and load
progress shows in a full-screen dimmed loading overlay with a staged progress
bar that dismisses once data is loaded, leaving a slim auto-fading post-load
toast.

- **One color identity per strategy**: every chart inside an
  analysis pane (lines, bars, scatter points) uses positional
  `LINE_PALETTE` colors keyed by the strategy's position in the
  selected ticker set. The selected-strategy perf grid above the
  panes carries a leftmost color-swatch column (header **"Chart
  Color"**, `PERF_COLOR_COLUMN_NAME`) rendered with
  `ipydatagrid.VegaExpr` and the same positional palette, so the
  grid acts as the universal legend — every chart's per-strategy
  bqplot legend (`display_legend`) is off.
- **Chart theme is dark (Bloomberg / Barclays blend)**: charts render
  on `Color.CHART_BG` (near-black `#0d1117`) via plotly's
  `plotly_dark` template + custom overrides defined in
  `_chart_layout()` in `src/layout/theme.py`. The `LINE_PALETTE` is a
  high-chroma palette anchored by Bloomberg orange (`#FFA000`) and
  Barclays cyan (`#00B5E2`) so traces pop against the dark
  background. Chart-specific color tokens (`CHART_BG`, `CHART_GRID`,
  `CHART_AXIS`, `CHART_TEXT`, `CHART_TITLE`, `CHART_HOVER_BG`) live
  on the `Color` enum. As of v0.6.5 the **whole dashboard chrome is dark
  too** (it no longer stays light) — see the next bullet.
- **Dark technical chrome via injected CSS (v0.6.5)**. A single global
  stylesheet (`data/templates/app_css.html`, rendered by `_app_css()` and
  mounted as the app VBox's first child; the app gets `add_class("bbg-app")`)
  defines the `.bbg-*` classes the chrome hangs off — base dark surface +
  scrollbars, the `.bbg-masthead`, the loading `.bbg-overlay`/`.bbg-progress`
  + post-load `.bbg-toast`, button states (`.bbg-pill`/`.bbg-pill.is-active`,
  `.bbg-btn`, `.bbg-btn-secondary`), best-effort dark form controls, the
  `.bbg-grid` frame, and the `.bbg-card` boxed-grouping card (v0.8.8, used for
  the Platform analytics tab card). Widgets opt in via `widget.add_class(...)` (the
  ipywidgets `.style` API can't express `:hover`/`:focus`). The grids' cell
  colors come from ipydatagrid's `grid_style`/renderer API, not CSS. All
  values flow from `src/style.py` tokens through `STYLE_CTX` — no inline hex.
- **Style tokens live in `src/style.py`**, not inline. Hex colors, font
  stacks, and font sizes used by `src/layout/` and `data/templates/`
  reference the `Color`, `Font`, `FontSize`, `StatusTone`, and `Sentiment`
  enums. Adding a new color or size: extend the enum, don't inline.
