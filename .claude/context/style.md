# Visual design system

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

The whole UI renders on a cohesive **dark technical chrome** (v0.6.5): the
chrome shares the charts' near-black surface, the title is a bold masthead
with an accent rule, buttons/controls/grids are dark-themed, and load
progress shows in a full-screen dimmed loading overlay with a staged progress
bar that dismisses once data is loaded, leaving a slim auto-fading post-load
toast. The post-load toast ("Loaded N indices …") is shown **only on the
initial load** — **Refresh prices** does not re-toast (the overlay already
signals progress); a refresh *failure* still toasts. On Refresh the same overlay
re-shows while the refetch runs on a background worker thread (so the click
handler returns and the frontend can paint the overlay before the kernel
blocks); the worker holds the overlay visible for a short beat
(`_OVERLAY_PAINT_DELAY_S` in `builder.py`) first, so an *instant* refetch
(off-terminal mock or warm cache) can't hide it inside the same frame it was
shown. The scrim (`.bbg-overlay`, `Color.SCRIM`) is a translucent **black** mask
(so it reads clearly darker than the navy chrome, signalling "loading"); both it
**and** the progress *card* (`.bbg-overlay-card`) float with `position: fixed`,
so they cover / centre on the **viewport** — the same mechanism as the
`.bbg-toast`. (An earlier `position: absolute` scrim was anchored to the top of
the long page, so once scrolled the mask sat off-screen and Refresh looked like
a bare dialog with no mask; the overlay blocks interaction while up, so covering
the viewport rather than the below-the-fold page is exactly right.)

- **One color identity per strategy**: every chart inside an
  analysis pane (lines, bars, scatter points) uses positional
  `LINE_PALETTE` colors keyed by the strategy's position in the
  selected ticker set. The selected-strategy perf grid above the
  panes carries a leftmost color-swatch column whose header is
  **deliberately blank** (`PERF_COLOR_COLUMN_NAME = " "`, a single
  space — a nameless legend chip, not a labelled field), rendered with
  `ipydatagrid.VegaExpr` and the same positional palette, so the
  grid acts as the universal legend — each plotly chart's own legend
  is off (`showlegend=False`), with the swatch column serving as the
  shared legend instead.
- **Chart theme is dark (Bloomberg / Barclays blend)**: charts render on a
  **transparent** `paper_bgcolor`/`plot_bgcolor` (`Color.TRANSPARENT`) via
  plotly's `plotly_dark` template + custom overrides defined in
  `_chart_layout()` in `src/layout/theme.py`, so the themed card / chrome
  behind each chart shows through instead of a painted-in canvas. The
  `LINE_PALETTE` is a high-chroma palette anchored by Bloomberg orange
  (`#FFA000`) and Barclays cyan (`#00B5E2`) so traces pop against the dark
  surface. Chart-specific color tokens (`CHART_BG`, `CHART_GRID`,
  `CHART_AXIS`, `CHART_TEXT`, `CHART_TITLE`, `CHART_HOVER_BG`) live
  on the `Color` enum. As of v0.6.5 the **whole dashboard chrome is dark
  too** (it no longer stays light) — see the next bullet.
  - **FigureWidget backdrop caveat**: plotly's `FigureWidget` gives its own
    wrapper DIV a theme-following (light/dark) default background that
    `paper_bgcolor` does not control, and a Refresh's full trace swap can
    transiently expose it — flashing a chart to the browser default (white in
    light mode, black in dark mode; plotly.py #3811). Separately, revisiting a
    pane view remounts its FigureWidget into its `Stack` (`stack.children = …`),
    so plotly re-runs `newPlot` and can redraw the **paper background rect** with
    the `plotly_dark` template's dark color even though `paper_bgcolor` is
    `rgba(0,0,0,0)` — the "dark background returns on the second view" bug.
    `app_css.html` handles both: it forces the plotly wrapper DIVs **and** the
    `.main-svg` layers `background: transparent`, and forces **every** plotly
    background rect (`.main-svg .bg` — the paper, the subplot plot-area, **and**
    the legend background) `fill: transparent`, so the whole chart *including its
    legend* shows the themed card through on first render and every remount.
    (Scoping the fill to only the paper rect left legend / plot-area backgrounds
    redrawing dark on remount.) **Key rule:** `.main-svg` may only ever be
    `background: transparent` — an *opaque* fill there paints over the stacked
    layers and hides the plotted data entirely.
- **Dark technical chrome via injected CSS (v0.6.5)**. A single global
  stylesheet (`data/templates/app_css.html`, rendered by `_app_css()` and
  mounted as the app VBox's first child; the app gets `add_class("bbg-app")`)
  defines the `.bbg-*` classes the chrome hangs off — base dark surface +
  scrollbars, the `.bbg-masthead`, the loading `.bbg-overlay`/`.bbg-progress`
  + post-load `.bbg-toast`, button states (`.bbg-pill`/`.bbg-pill.is-active`,
  `.bbg-btn`, `.bbg-btn-secondary`), best-effort dark form controls, the
  `.bbg-grid` frame, the `.bbg-card` boxed-grouping card (v0.8.8, used for
  the Platform analytics tab card, the leaderboard and the commentary pane),
  and the `.bbg-lb-*` leaderboard rules (v0.9.20, below). Widgets opt in via
  `widget.add_class(...)` (the ipywidgets `.style` API can't express
  `:hover`/`:focus`). The grids' cell
  colors come from ipydatagrid's `grid_style`/renderer API, not CSS. All
  values flow from `src/style.py` tokens through `STYLE_CTX` — no inline hex.
- **Style tokens live in `src/style.py`**, not inline. Hex colors, font
  stacks, and font sizes used by `src/layout/` and `data/templates/`
  reference the `Color`, `Font`, `FontSize`, `StatusTone`, and `Sentiment`
  enums. Adding a new color or size: extend the enum, don't inline.

## The commentary block (v0.9.20, epic #286)

**The leaderboard's rows are three buttons each, drawn as one strip.** An
ipywidgets `Button` renders its `description` as a single text node, so the
whole label takes one colour — but a row needs three treatments: a dimmed rank,
the ticker in the primary text colour, and a right-aligned value coloured by its
sentiment. So a row is an `HBox` (`.bbg-lb-row`) of three `W.Button`s, each
carrying `.bbg-lb-cell` plus one of `.bbg-lb-rank` / `.bbg-lb-ticker` /
`.bbg-lb-value`. The cells are borderless, radius-free and transparent, so they
read as one continuous strip rather than three buttons.

Two rules follow from that:

- **The hover is on the row, not the cell** (`.bbg-lb-row:hover .bbg-lb-cell`),
  so all three light together and the strip reads as one target. The ticker
  additionally shifts to `{{accent2}}` on hover.
- **Only the value's colour is inline.** The rank and ticker colours are static
  and live in the stylesheet; the value's is *data* (green / red / bright by
  sentiment) and is the single per-row `style.text_color`. `_value_color` in
  `leaderboard.py` maps `Sentiment.NEUTRAL` to the bright chrome text token,
  because the shared neutral is brand navy and illegible on the dark surface.
  (It lived in `html.py` as `_superlative_value_color` until #291 retired the
  cards and the leaderboard became its only caller.)

The value cell uses `font-variant-numeric: tabular-nums` so figures line up
column to column; rank and value cells are fixed-width and the ticker flexes,
so the numbers align vertically regardless of ticker length. A blank slot is
`visibility: hidden`, **not** `display: none`, so a short column keeps its
height instead of pulling the divider up.

**The pane's pill pair follows the tab-band idiom.** *Commentary* | *New
Launches* are ordinary `.bbg-pill`s (the subtle style, not the inverted
`.bbg-tabband` one), toggled by `_style_tab_button` — the active state is the
`is-active` class, never an inline button colour, which would win over the
`:hover` / `:focus-visible` rules.

**Known inconsistency.** `weekly_commentary.html` still uses the *light*
palette (`{{slate50}}` panel, `{{navy}}` heading, `{{slate200}}` border) from
before the dark chrome, so the Weekly Commentary board renders as a white card
inside the dark pane — now directly beside the dark leaderboard. Predates this
epic and is not yet fixed.

## Benchmark selector (#192)

The benchmark selectors are `BenchmarkSelect` composites wrapping a
`W.Combobox`, not `W.Dropdown`s. The input inherits the existing
`.bbg-app input[type="text"]` dark rules, and `.bbg-benchmark-select` keeps the
wrapper from adding spacing of its own. The **datalist popup** a browser renders
for a combobox is not styleable from page CSS — that is a browser limitation,
so the suggestion list appears in the browser's own chrome rather than the dark
theme.
