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
  the `.bbg-lb-*` leaderboard rules (v0.9.20, below), and the
  `.bbg-rail` / `.bbg-rail-title` / `.bbg-rail-heading` / `.bbg-chip` control
  rails (v0.9.21, below). Widgets opt in via
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

**Both boards in the pane share one shape.** `weekly_commentary.html` used to
carry the *light* palette from before the dark chrome (`{{slate50}}` panel,
`{{navy}}` heading, `{{slate200}}` border) and its own bordered panel, so it
rendered as a white card inside the dark pane. It now matches
`launches_board.html`: a heading row (title plus a muted caption) over a body
capped at `30vh` and scrolling past it, **with no panel of its own** — the
pane's `.bbg-card` is the frame, and a second one nested inside it was the
other half of why the two boards looked unrelated.

**The commentary body is author HTML, so the stylesheet dresses it.** The body
comes from `data/weekly_commentary.html`, written by a person who should not
have to think about the theme, and it arrives with no styling — which means
browser defaults: a default-blue link and near-black `code`, both unreadable on
the navy surface. `.bbg-commentary-body` rules in `app_css.html` give links the
`{{accent2}}` colour, `code` a `{{surface2}}` chip, blockquotes a muted left
rule, and tables and headings the border and text tokens. Scoped to the body, so
the surrounding chrome is untouched. Anything an author can reasonably write
renders legibly without their doing anything.

## Control rails and chips (v0.9.21, epic #276)

The Platform tab's controls sit in two containers of the same chrome, built by
`control_bar` / `control_rail` (`src/layout/rails.py`) rather than assembled at
the call site: a **bar above** the table (Group by + Window) and a **rail down
its left** (Z-Score ranking). They differ by direction and content, not by
code.

- **`.bbg-rail`** — the raised panel: `surface` fill, border, 8px radius, at a
  fixed 210px basis (`RAIL_WIDTH`). It does **not** flex; the table between the
  rails absorbs the remaining width (#280).
- **`.bbg-rail-title`** — the rail's own accent heading, used only when its
  sections are facets of one control (the Z-Score rail's Metric / Window /
  Lookback). Group by / Window stand on their own and pass no title.
- **`.bbg-rail-heading`** — a section heading: uppercase, letterspaced, muted.
- **`.bbg-rail-bar`** — the same rail turned on its side, for the controls
  **above** the table: `.bbg-rail`'s surface and border, sections laid across,
  the title beside them behind a vertical rule, and **no height cap** (a cap
  exists to keep a column level with the table).
- **`.bbg-chip-row`** — chips laid across: they size to their text instead of
  filling a rail's width, and wrap rather than squeeze when the bar runs out.
- **`.bbg-chip`** — a chip, in the `.bbg-pill` family so the base, hover,
  active and focus colours are the tab band's and these rules only refine them:
  full-rail width, left-aligned, with an accent bar down the leading edge when
  active. `text-align` alone does **not** left-align a Jupyter button — the
  widget renders a flex container, so `justify-content` is set with it.

**The rail stands the table's height by stretching, never by a cap.** The row
is `align_items: stretch`, so the rail takes the height the table sets, and
`.bbg-rail` carries `min-height: 0` + `overflow-y: auto` — which is what lets a
stretched flex item scroll rather than grow the row.

Two mistakes here are worth keeping written down, because both shipped and both
looked like styling bugs:

- **Do not size the rail from `CATALOG_SCROLL_MAX_HEIGHT`.** That token bounds
  the table's scroll *cell*; the widget is also carrying the search row above
  it and the row-count readout below, roughly 70px more. A rail capped at the
  cell's height renders visibly **shorter** than the table beside it.
- **Chips must not shrink.** A flex item shrinks before its container scrolls,
  so a rail holding more chips than fit squeezed every chip flat instead of
  showing a scrollbar. `.bbg-chip`, `.bbg-rail-heading` and `.bbg-rail-title`
  are pinned `flex: 0 0 auto`.

**The active state is a class, never inline `.style`.** `_make_chip` /
`_style_chip` (`chrome.py`) toggle `is-active`, exactly as the tab-button pair
does, because an inline button colour outranks the `:hover` / `:focus-visible`
rules and leaves a chip that never lights up.

## Catalog group-header bands (v0.9.21, #284)

The classification tiers are drawn as nested row-group headers in cyan fills
stepping **down** in tint, so the hierarchy reads as bands rather than as a text
colour on the body background. Level 0 is `ACCENT` itself; levels 1–3 are
`Color.GROUP_BAND_1/2/3`.

**The foreground flips partway down the scale**, and that is why the step is not
uniform. On a solid `ACCENT` fill the app's light text measures 2.1:1 —
unreadable — so levels 0 and 1 take **dark** text (as
`.bbg-tabband .bbg-pill.is-active` does) and levels 2 and 3 take the normal
light text on deeper fills. A smooth ramp through the middle would put a band
exactly where neither text colour is legible. Measured contrast: 7.4 / 8.6 /
5.8 / 8.2:1 against the text colour each band actually uses, asserted from the
tokens in `tests/test_catalog_grid.py` rather than written down here alone.

Two selector facts are load-bearing: RowGroup emits a **`th`**, not a `td` (a
td-only rule matches nothing and every level renders in the plain body colour),
and the base `tr.dtrg-group` rule carries the deepest band so a nesting level
past the named ones still renders as a defined band.

## Benchmark selector (#192)

The benchmark selectors are `BenchmarkSelect` composites wrapping a
`W.Combobox`, not `W.Dropdown`s. The input inherits the existing
`.bbg-app input[type="text"]` dark rules, and `.bbg-benchmark-select` keeps the
wrapper from adding spacing of its own. The **datalist popup** a browser renders
for a combobox is not styleable from page CSS — that is a browser limitation,
so the suggestion list appears in the browser's own chrome rather than the dark
theme.
