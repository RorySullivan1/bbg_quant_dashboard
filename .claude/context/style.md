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
  `.bbg-grid` frame, the `.bbg-card` boxed-grouping card (v0.8.8 — the
  Platform analytics tab card; the commentary block's two sections wear
  `.bbg-section-box` instead since v0.9.22, and dropped their cards so the
  section shell is the only frame), the `.bbg-section-box` boxed section body
  (v0.9.22 #305), the `.bbg-lb-*` leaderboard rules and `.bbg-note-body`
  (v0.9.20 / v0.9.22, below), and the
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

## The commentary block (v0.9.22, epic #303)

**Both sections are one component.** The Leaderboard and the QIS Bulletin are
each a `section_panel` (`rails.py`): a title line in the `grid_header`
treatment — optionally followed on the same baseline by a **muted caption**,
lighter and smaller so it qualifies the heading rather than competing with it
— the section's `control_bar` of chips, then a `.bbg-section-box` —
the same `{{chrome_bg}}` surface, 1px border and 6px radius the Platform
table's box wears — at a fixed `COMMENTARY_BOX_HEIGHT` (300px), scrolling its
body inside that height rather than growing the row. The height is a **token
and not a literal** precisely so it is one edit to tune once it has been seen
at a terminal's fonts, which is where it should be tuned.

**The split is shares, not pixels.** `COMMENTARY_LEADERBOARD_SHARE` (60%) and
`COMMENTARY_BULLETIN_SHARE` (40%), applied as `flex: 1 1 <share>` with
`min-width: 0` on both columns. The `flex: 0 0 620px` basis this replaced was a
width that *happened* to read as 60% at 1030px wide and 43% at 1440px, so the
ratio drifted with the screen it was measured on. `min-width: 0` is
load-bearing, not tidiness: a flex item's automatic minimum is its content, so
without it the leaderboard's four columns refuse to narrow and push the
Bulletin off the row instead of both shrinking — the same pairing the catalog
table needs beside its rail.

Neither section's contents frame or title themselves. The `Leaderboard` board
and the Bulletin's container both dropped their `.bbg-card` in #306 / #307:
`section_panel`'s box is the frame, and two bordered surfaces nested draw two.
Both boards likewise lost their in-HTML `<h3>`s and their `max-height: 30vh` —
the section title, the lit chip and the box own all three.

**The leaderboard's rows are four buttons each, drawn as one strip.** An
ipywidgets `Button` renders its `description` as a single text node, so the
whole label takes one colour — but a row needs four treatments: a dimmed rank,
the ticker in the primary text colour, the **score** coloured by its sentiment,
and the raw value behind it in parentheses, muted. So a row is an `HBox`
(`.bbg-lb-row`) of four `W.Button`s, each carrying `.bbg-lb-cell` plus one of
`.bbg-lb-rank` / `.bbg-lb-ticker` / `.bbg-lb-score` / `.bbg-lb-value`. The
cells are borderless, radius-free and transparent, so they read as one
continuous strip rather than four buttons.

Two rules follow from that:

- **The hover is on the row, not the cell** (`.bbg-lb-row:hover .bbg-lb-cell`),
  so all four light together and the strip reads as one target; the ticker
  additionally shifts to `{{accent2}}`. Both rules carry `!important` (#306),
  for the reason the rest of this stylesheet uses it: the widget framework
  injects its own `:hover` background per button at runtime, and without it the
  cell under the cursor paints differently from its siblings — which reads as
  the *pieces* of a row highlighting rather than the row. `:focus-visible`
  stays a separate, visible state: a keyboard user needs to see which cell they
  are on.
- **Only the score's colour is inline.** The rank, ticker and value colours are
  static and live in the stylesheet; the score's is *data* (green / red /
  bright by sentiment) and is the single per-row `style.text_color`. It sits on
  the score rather than the value because #310 made the score what the row is
  ranked and read by. `_value_color` in `leaderboard.py` maps
  `Sentiment.NEUTRAL` to the bright chrome text token, because the shared
  neutral is brand navy and illegible on the dark surface. (It lived in
  `html.py` as `_superlative_value_color` until #291 retired the cards and the
  leaderboard became its only caller.)

The score and value cells use `font-variant-numeric: tabular-nums` so figures
line up column to column; rank, score and value are fixed-width and the ticker
flexes, so the numbers align vertically regardless of ticker length. Column
titles are centred (#306). A blank slot is `visibility: hidden`, **not**
`display: none`, so a short column keeps its height instead of pulling the
divider up.

**The Bulletin's board control is a `ChipGroup`**, not the `.bbg-pill` pair it
was through v0.9.20 — the block reads as the Platform tab's idiom rather than
as a third one, and the chips are painted by the same `_style_chip` with the
selected state a CSS class rather than an inline colour.

**A note's body is plain text, so the stylesheet only sets its rhythm.**
`_render_note_paragraphs` escapes the text and splits it into `<p>`s, so the
`.bbg-note-body p` rules are the whole of it: a 5px top margin between
paragraphs, none on the first or last, so the text sits against the card's own
padding rather than inside a second, invisible one. The browser's default `1em`
would open a gap as tall as a line inside a card only a few lines high.

*(Through v0.9.20 the Commentary board was author-written HTML from
`data/weekly_commentary.html`, and a `.bbg-commentary-body` block dressed
arbitrary author markup — links, `code`, headings, blockquotes, `hr`, tables —
so it stayed legible on the navy surface without the author thinking about the
theme. #308 retired the blob, and the block with it: none of that markup can
arise from plain text split into paragraphs.)*

## Control bars and chips (v0.9.21, epic #276; v0.9.23, epic #321)

Every bar in the app is the same chrome, built by `control_bar`
(`src/layout/rails.py`) rather than assembled at the call site: the catalog's
**Table view** (Group by · Metric · Window), the Leaderboard's Window, and the
QIS Bulletin's board switch.

*The class names say `rail` because these were rails first — fixed-width
columns of stacked sections, with the bar added as the same panel turned on its
side. The catalog's rail lost its contents in #324/#325 and was removed with its
builder in #326; the surface it defined is what stayed.*

- **`.bbg-rail`** — the raised panel: `surface` fill, border, 8px radius. Every
  consumer now carries `.bbg-rail-bar` with it. (The stacked-column rules lived
  here and went in #326: a `min-height: 0` / `overflow-y: auto` pair that let a
  stretched column scroll instead of growing its row, and a first-child heading
  reset that could only ever match a heading *directly* inside a rail — a bar's
  sit inside `.bbg-rail-block`.)
- **`.bbg-rail-title`** — the bar's own accent heading, used when its sections
  are facets of one thing (the catalog's Group by / Metric / Window are three
  facets of the table view). The Leaderboard's Window and the Bulletin's board
  switch stand on their own and pass no title.
- **`.bbg-rail-heading`** — a section heading: uppercase, letterspaced, muted.
- **`.bbg-rail-bar`** — the bar proper: `.bbg-rail`'s surface and border,
  sections laid across, the title beside them behind a vertical rule.
- **`.bbg-chip-row`** — chips laid across: they size to their text instead of
  filling their container's width, and wrap rather than squeeze when the bar
  runs out. Every chip group in the app is one.
- **`.bbg-chip`** — a chip, in the `.bbg-pill` family so the base, hover,
  active and focus colours are the tab band's and these rules only refine them:
  full-width and left-aligned by default, with an accent bar down the leading
  edge when active. `text-align` alone does **not** left-align a Jupyter
  button — the widget renders a flex container, so `justify-content` is set
  with it. (The full-width default is the stacked shape; `.bbg-chip-row`
  overrides it, and `ChipGroup(row=False)` is still a supported widget shape.)

**The table stands at a fixed `CATALOG_TABLE_HEIGHT` and takes the full width.**
It was the number the table and the rail beside it *shared*, until #326 left
only one box reading it. The table's internals then fill that box: the
`.bbg-catalog` flex chain passes the height down DataTables' wrappers so the
search row and the row-count readout take what they need and the row area
scrolls in the remainder. `min-height: 0` appears at every level of that chain —
without it a flex child refuses to shrink below its content, and the body pushes
the box open instead of scrolling inside it.

Three things were tried here that did not work, all of which rendered as
plausible-looking layout bugs:

- **A cell cap instead of a box height.** Capping the table's scroll cell
  leaves the widget taller than the cap by its search row and readout (~70px),
  so anything sized to the cap stands short beside it.
- **Stretching two boxes to level them.** `align-items: stretch` makes
  whichever box holds more content set the row — the table grew to the rail on
  a small catalog, the rail to the table on a large one. Fixing both to one
  number was the only arrangement where neither pushed the other. (Moot since
  #326 removed the second box, and recorded because the next pair of boxes
  meant to stand level will meet it again.)
- **Letting chips shrink.** A flex item shrinks before its container gives way,
  so a container holding more chips than fit squeezed every chip flat instead
  of wrapping. `.bbg-chip`, `.bbg-rail-heading` and `.bbg-rail-title` are
  pinned `flex: 0 0 auto`.

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


## The Platform analytics card (v0.9.24, epic #331)

**`.bbg-itable` vs `.bbg-catalog`.** There are two `ITable`s now — the catalog
and the chart's points — so the dark-table chrome is `.bbg-itable`, which both
wear. `.bbg-catalog` keeps only what belongs to the catalog alone: the nested
group bands RowGroup draws, and the per-column filter row. A test fails if a
rule that is not about either ends up back on `.bbg-catalog`.

**Two new chart tokens**, `CHART_ZERO_LINE` and `CHART_AXIS_LINE`. A 3D scene
takes no paper shapes, which is why the factor scatter marked its origin with
translucent `Mesh3d` planes — and why those planes dimmed the markers behind
them, the thing the chart is for. The scene's own axes carry it instead: the
zero line bright enough to read against `TRANSPARENT` at the default camera,
the wall edge a step below it so the box reads as a frame rather than as three
more zero lines.

**The Icicle's ramp is symmetric and data-derived.** Same red → neutral →
green diverging scale, `cmid=0`, but `cmin` / `cmax` are ± a high percentile
(95th) of |value| over the leaves rather than the fixed ±2 that a z-score
justified. Symmetric because the ramp's midpoint means "average": an
asymmetric range would put zero off-centre and colour a flat strategy as
though it were good or bad. Clipped because one outlier otherwise flattens
every other cell to the middle of the scale.

**The Strip is `go.Scatter` with a computed jitter**, not the hidden-box
construction a strip plot usually uses: a drillable marker needs a point index
and `customdata` the kernel controls. Its X axis is **numeric wearing the
dates as tick labels**, because a categorical axis puts every marker of a
column on one line and the jitter would have nowhere to move to. The jitter is
spread evenly across the column and derived from the point's position, never
drawn at random — a redraw must not reshuffle the cloud and read as movement
in the data.

**`group_colors` and the colour rule.** The drill re-keys the colours at every
depth, so the palette has to serve families and tickers, not just asset
classes. `group_colors(keys, curated=…)` takes the curated map first — which
is how asset classes keep their identity colours at the root, and why a family
called "Momentum" has no claim on Equity's blue — then `LINE_PALETTE` in
sorted order, **cycling** rather than collapsing to the grey fallback once the
palette runs out: a family larger than the palette should still draw
distinguishable neighbours, and the legend and hover name every point whatever
the hue. The rule for *which* level the colours key to lives once, in
`stats.drill.color_key`: the hierarchy's first level at the root, the points'
own level below it.

**One height, and a 60:40 width.** `ANALYTICS_HEIGHT` sets the chart's box,
the table's, and — **since v0.9.27, in fact rather than only in this
paragraph** — the figures' own `height`, through `ANALYTICS_HEIGHT_PX` passed
to each `_chart_layout`. Left to its default, `_chart_layout` takes the
app-wide `CHART_HEIGHT` (520px), which was *taller* than the 420px box, so the
card clipped every chart it drew. The box is fixed rather than stretched for
`CATALOG_TABLE_HEIGHT`'s reason: stretching lets whichever box holds more
content set the row.

**Height is the Icicle's only lever**, which is why this token has moved three
times — 420px (v0.9.24) → 504px (v0.9.27) → **720px** (v0.9.28), each raise
from the same terminal reading: the cells were still too short to carry their
labels. `tiling.orientation="h"` runs *depth* left to right, one column per
level, so the chart's **width** is divided four ways whatever the catalog
holds, and its **height** is divided among **siblings** — every strategy in
the pinned solution stacked in the last column. Widening the card does nothing
for that; only this does. The `pathbar` was taking a band off the top too,
which is why it is now off (see `architecture.md`).

At 720px the card stands *above* `CATALOG_TABLE_HEIGHT` rather than a little
under it, inverting the original "a chart as tall as the catalog pushes the
page" sizing. Deliberately: the table's height is a **scroll viewport** onto
rows that keep their size whatever it is, while the chart's height **is** the
drawing. The width is `ANALYTICS_CHART_SHARE` /
`ANALYTICS_TABLE_SHARE` as flex bases, the `COMMENTARY_*_SHARE` pattern
(v0.9.25). The 360px basis this replaced held the table at one width whatever
the screen, so it read as a squeezed strip on anything wide. Both boxes carry
`min-width: 0` — the #280 pair — so a long strategy name wraps inside its
column instead of widening it.

**The drill has its own strip** (`.bbg-drill-bar`, v0.9.25), below the *Chart
view* bar and subordinate to it: no border box of its own, a rule above
instead, tighter vertical rhythm, and the accent left to the bar's title. The
bar above carries **settings**; this carries a **position** the charts
themselves write back to, and two different kinds of control should not read
as one row of equals. Its blocks lay the heading *beside* the control rather
than above it, so the strip is one line of "Scope: … Level: …", and it wraps
rather than scrolling — a full path is five segments plus the Level chips.


## Hover labels on the analytics card (v0.9.25)

**Nothing anchors a hover label.** There is no property that puts the box on
a chosen side of the marker, in a 3D scene or anywhere else, so the label's
**footprint** is the only lever on how much of the cloud it hides. What the
card's charts set is `_HOVER_LABEL` — `align` and `namelength`, shared so one
chart cannot drift from the others, and held to properties old enough for the
terminal's plotly (`showarrow` was not, and took the app down: see
`run_instructions.md`). The Scatter's hover is therefore three short lines —
name, the metric, then both betas side by side — where it was five.

**A group's hover says "mean of N", never a bare count.** It rendered
`%{customdata[1]}` against the raw number, so a three-member category read
`1Y Sharpe 1.23 3`. The value on these charts is an equal-weight mean of the
node's members and the hover has to say so, or the number reads as the node's
own. A leaf says nothing at all: "mean of 1" is true and useless.
