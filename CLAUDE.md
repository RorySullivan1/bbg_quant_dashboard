# CLAUDE.md — bbg_quant_dashboard

Repo memory for future Claude sessions. Read this before editing.

## Project purpose

A Bloomberg BQuant App that lets clients browse an index catalog: filter by
metadata, look up tickers, and view performance, correlation, and a 1-year
rolling Sharpe-ratio z-score over a 5-year lookback. Metadata is stored
locally in `data/indexdb.json`; time-series prices are pulled from BQL at
runtime. The UI is built with `ipywidgets`, `plotly` (interactive charts
via `FigureWidget`), `ipydatagrid` (the Multi-Strategy perf grid) and
`itables` (every catalog table), and is deployable via Voila. Since v0.9.38
`charts.py` imports no grid at all — every table a chart owns is HTML.

**Nothing regenerable is written into the project folder** (v0.9.41). A BQuant
project has a size limit, and the app was over it by writing two kinds of
throwaway file into itself: the parquet price cache (`data/.cache/`, ~1.4 MB
for the shipped catalog once #361 widened the fetch to fifteen years) and `src`
bytecode (~0.9 MB of `__pycache__`). The cache now lives under the system temp
folder (`config.RUNTIME_DIR`, overridable with `BBG_DASHBOARD_CACHE_DIR`); the
notebook sets `sys.dont_write_bytecode` before importing `src`; and
`build_app` clears what older versions left, once, through
`housekeeping.clear_legacy_artifacts`. **The flag, not
`sys.pycache_prefix`**: a prefix redirects *reads* as well as writes, so every
library imported after it recompiled into temp — 2.3 s and ~19 MB cold —
where the flag leaves libraries reading their own bytecode and costs ~0.7 s of
`src` compilation per launch. The cleanup runs from `build_app` only, never
`DashboardApp`, because tests construct the app and must not delete files from
the checkout. User benchmarks stay in the project: they are configuration, not
cache.

The whole UI renders on a cohesive **dark technical chrome** (v0.6.5) and is
organized as: masthead banner → an always-visible **all-catalog commentary
block** (two sections at 60:40 — a ranked **Leaderboard** of four metric
columns with clickable rows, beside the **QIS Bulletin**, which switches
between authored Commentary notes and New Launches) → a
**top-level pill-button tab bar** with three
tabs — **Platform** (one control bar over a full-width all-catalog performance
grid + a Platform-analytics card: a chart — Icicle / Scatter / Strip — beside
a table of its own points), **Multi-Strategy**
(the same catalog table in multi-select over a **Basket**, a strip of basket
cards, and two side-by-side analysis panes), and **Single Strategy** (the same
table again in single-select, over a profile card + cumulative chart, an HTML
metrics table and monthly calendar, and two analysis panes) → disclaimers. All
compute lives in `src/`; the notebook is a one-liner that calls `build_app()`.

The catalog is described by a **declarative schema** (v0.9.15,
`CATALOG_SCHEMA` in `src/config.py`): every metadata column is declared once —
internal key, the JSON keys it accepts, its **display label**, and its role. So
**labels and column order are configuration, not code**: relabelling a column,
reordering the three classification tiers (`CLASSIFICATION_TIERS` =
Solution → Category → Family), adding a filter pill, or changing which levels
the Platform analytics draw (`ANALYTICS_LEVELS`) is a `config.py` edit, not a
sweep across renderers. Never re-spell a label or a tier order at a call site —
read it through `field_label` / the per-renderer field tuples. See
`.claude/context/data.md`.

Every benchmark selector is user-extensible (v0.9.14): it type-filters the
curated `BENCHMARK_TICKERS` list *and* the catalog indices, and accepts a
ticker that is on neither — fetching it as a delta, reporting an
unresolvable ticker separately from one with no history in the window, and
persisting additions to a gitignored `data/user_benchmarks.json` that
degrades to session-only on a read-only filesystem.

The code is organized **around objects, not bags** (epic #215, v0.9.16–v0.9.17).
What used to be `SimpleNamespace` bundles, module globals and closures over
`build_app`'s locals are now typed classes, each owning its own widgets and
state: `DashboardApp` (`src/layout/app.py`) is the controller the notebook's
`build_app()` one-liner constructs, and `PlatformAnalytics`,
`SingleStrategyPanel`, `RegimeControls`, `PriceCache` and the `PriceSource`
protocol (`BqlPriceSource` / `MockPriceSource`) each own one area. **A figure or a table is an object too (v0.9.17 #223):** each `Chart`
subclass in `charts.py` builds its own `FigureWidget` and updates it
(`pane.heat.update(cm, …)`), and `PerfGrid` / `UniverseGrid` / `CalendarGrid`
each own a `DataGrid` whose single write path re-asserts the dark theme — so
the figure-to-updater pairing and the v0.6.5 theme-refresh invariant are
structural rather than something each call site has to remember. Data that
moves between them is a **frozen dataclass** — `AnalysisPane`,
`SingleAnalysisPane`, `SelectionSlice`, `RenderContext`, `LeaderboardColumn` /
`LeaderboardRow`, `LaunchCard`, `LevelRegime` / `TercileRegime`. Two rules hold across all of
them: **`state` is held on the object** (one mutable object, always current,
annotated `DashboardState` rather than `object`) while **`meta` stays a
per-call argument or a callable provider** — the app re-points `meta` to the
pruned catalog after every load, so an attribute holding it goes stale
silently (#242). Prefer injecting a collaborator over reaching for a module
global.

The catalog table is **grouped, and the user shapes it** (epic #261, v0.9.18).
The all-catalog grid is an `itables` / DataTables `ITable`; `PerfGrid` and
`CalendarGrid` stay on `ipydatagrid`, and the two stacks coexist on purpose —
ipydatagrid's merged row headers render incorrectly in 1.4.0, and only
DataTables' RowGroup draws the classification tiers as **nested group headers**
instead of three body columns repeating the same strings on every row. Which
levels group is the user's choice (`UNIVERSE_GRID_GROUPABLE_FIELDS`, four
chips) but the *nesting order is always the hierarchy's*, never the order
they ticked; the grid shows **one stats window at a time**, chosen in the bar
above it and offering only what `LOOKBACK_YEARS` can serve. Clicking a
row opens that strategy in Single Strategy. Two rules hold underneath: **row
contiguity at every grouping level is a correctness requirement**, because
RowGroup only gathers adjacent rows, and **the performance columns are hidden
rather than dropped** when the window changes, so none of them recomputes —
every window is measured once, up front. What a window change *does* disturb
is the ranking: since v0.9.23 (#324) it is also the window the score is
measured over, so the ranking column is renamed and the frame re-sorted, and
the table is rebuilt the way a grouping change rebuilds it. The selected row
does not survive that, which is inherent — the rows moved.
See `.claude/context/conventions.md`.

The commentary block is **two sections at 60:40** (epic #303, v0.9.22): the
**Leaderboard** and the **QIS Bulletin**, each built from the same
`section_panel` the Platform tab uses — a title, a `control_bar` of chips, then
a boxed body at one shared height (`COMMENTARY_BOX_HEIGHT`). The shares are
tokens (`COMMENTARY_LEADERBOARD_SHARE` / `_BULLETIN_SHARE`) applied as
`flex: 1 1 <share>` with `min-width: 0`, not a pixel basis: the 620px column
this replaced read as 60% at 1030px wide and 43% at 1440px, so the split drifted
with the screen it was measured on.

The **Leaderboard** is four columns — Return, Sharpe, Calmar, Sortino — each
listing the catalog's top three and bottom three as
**`rank · ticker · score (value)`** over the window its Window chips select
(**1D**–**1Y**, `LEADERBOARD_WINDOW_OPTIONS`, a list of its own so a year or a
day does not reach the two controls built from `SHORT_WINDOW_OPTIONS`). The board **opens on 1W** (v0.9.37, #384), and the
default is validated against the chips that offer it — a default outside the
options would light no chip, so the first click on any of them would look like
it had done nothing. **At 1D the board is one column** (v0.9.40): Sharpe,
Calmar and Sortino divide by a volatility, a drawdown or a downside deviation,
and a single return has none of the three — which is why #306 dropped the day
entirely. It is back ranking on **Return alone**, and the other three columns
are **hidden, not blanked**, since three empty columns under their titles read
as a board that failed to load. `leaderboard_metrics(window_days)` in
`config.py` is the one rule: `build_leaderboard` computes only what it names,
and the board shows only what it names. It is passed to the widget apart from
the columns because the two mean different things — a metric a window offers
can still come back with no scorable rows, and that column should stand empty
under its title rather than vanish. **Ranking is by the
score** (#310), which the section title says out loud
(`(Ranked By Normalized 5Y Z-Score)`, built from `SCORE_SAMPLE_YEARS` rather
than spelled) — each metric standardized against its *own* trailing history,
which is why the app **fetches** `score_history_years()` — the longest window
the catalog offers plus the sample standardized behind it, **fifteen years**
since v0.9.34 (#361) — while analytics stay at `LOOKBACK_YEARS = 10`. The
sample and the lookback were one constant while both were 5; #361 widened
the analysis to ten years and *kept the sample at five*, because a ten-year
sample is a different statistic and its half-sample floor would have needed
~22 years of history to rank at all. `SCORE_SAMPLE_YEARS` is what both boards
share now, and every `(nY Z-Score)` label reads it, never the lookback. The raw
value rides behind the score in parentheses so a reader
can see what was standardized, and the sentiment colour sits on the score, which
is what the row is read by. The asset-class-demeaned z-score is a different
figure and stays where it belongs, on the catalog's Z-Score column. **Clicking any row opens that strategy in Single Strategy**, through the
same `_show_in_single_strategy` the catalog grid uses, so the two entry points
cannot diverge.

The **QIS Bulletin** holds one board at a time — Commentary or New Launches —
chosen by chips. Commentary is the authored notes in `data/commentary.json`
(#304), each with its own title and date; its text is **plain text**, escaped
and then split on blank lines into paragraphs, so markup in a note is shown as
typed. This retired the single undated `weekly_commentary.html` blob the app
used to stamp with today.

Three rules hold underneath: **a row is four buttons** because a `Button`'s
description is one text node and a row needs four colours; **`errors_w` is a
sibling of both sections**, never inside one, so no live control can wipe an
init error; and **Refresh invalidates while a chip re-slices** — neither the
window chips nor the board chips issue BQL. This replaced the v0.8.x 16-card
Market Superlatives board (#291); its metrics all live on in `src/stats/`.

The Platform tab is **one composed surface** (epic #276, v0.9.21; finished in
epic #321, v0.9.23). Every control the catalog table has sits in **one
horizontal bar above it** (*Table view*): **Group by · Metric · Window**, in
the order they act in — what the rows are gathered into, what is measured, over
how long. The bar is `control_bar` (`src/layout/rails.py`) carrying `ChipGroup`
chips. A second container — a fixed-width **rail down the table's left side**,
holding the ranking's Metric / Window / Lookback — stood there until #324 fixed
the score's sample and handed the window to the bar, #325 moved the Metric in
after it, and #326 removed the emptied column and the component that built it.
`.bbg-rail` is still the surface a bar is drawn on, which is why the class and
the helper names read as they do; `src/layout/rails.py` carries that history.

The table stands at a fixed `CATALOG_TABLE_HEIGHT` and runs the **full width**.
Its internals fill that box — the search row and the row-count readout take what
they need, the row area scrolls in the remainder — so the height is one number
to tune with nothing to keep in step with it. Chips are pinned `flex: 0 0 auto`:
a flex item shrinks before its container gives way, so a bar with more chips than
fit squeezed them flat instead of wrapping. A chip group is a **widget, not a row
of buttons**: it presents a `W.Dropdown`'s `value` / `label` / `observe` surface,
which is what let the ranking controls change containers twice as restyles rather
than rewrites of everything that reads them, and its multi-select flavour reports
**membership** so a tick order cannot reach the grouping. The table leads with a
top-left search box, draws its tiers as stepped cyan bands, and carries a
**per-column filter row** beneath its header labels — one box per column, and
the stat columns' boxes take a **comparison** (`>1`, `1..3`) rather than a
substring, in the units the cell shows, because those columns are searched on
the raw value a `5.23%` cell stores as `0.0523`. One deliberate exception
lives here: **the filter text is held in the browser, not on `UniverseGrid`**,
because every options change destroys and rebuilds the table and no traitlet
carries typed text to the kernel. See `.claude/context/style.md` and
`conventions.md`.

The table's ranking column is **one honest number** (epic #321, v0.9.23). It is
the selected **Metric** — Return / Sharpe / Calmar / Sortino, the Leaderboard's
own set from `RANKABLE_METRICS`, so a reading carries between the two boards —
over the selected **Window**, standardized against a fixed `SCORE_SAMPLE_DAYS`
of that metric's own rolling history. The header says all four facts:
**`Normalized 1Y Sharpe (5Y Z-Score)`**, with the `5Y` built from
`SCORE_SAMPLE_YEARS` rather than typed. Three rules hold underneath. The column is
**found by the key its builder returned**, never by parsing its header — five
behaviours hang off knowing which column it is (width, ramp, DataTables kind,
number renderer, filter units) and all five failed silently on a relabel (#323).
A sample too short to be a five-year sample **renders a dash** rather than
standardizing against the little it has (`CATALOG_SCORE_MIN_SAMPLE_DAYS`), so
at the `10Y` window an index needs roughly 12.5 years of history to be ranked.
And **Vol is not rankable here**: the ramp and the sort both say *higher is
better*, which volatility is not — it stays on the Quantitative filter, where
nothing claims a direction for it. The analytics card offered it too until
epic #331, which is the "its own issue" #321 named.

The analytics card below the table is **a chart beside its own points** (epic
#331, v0.9.24). Its controls are a second `control_bar` in the same chrome —
*Chart view*: **Chart · Metric · Window · Regime · Solution**, with
**Scope · Level** on the drill strip below it — and
Metric and Window are the table's own option lists, so the two surfaces can be
read at different windows but cannot *offer* different things. Sections the
active chart does not read are **hidden, not rebuilt**, so a chip keeps its
selection across a chart switch.

Three charts, each a `Chart` that also exposes **`points()`** — the frame it
drew, as `path` / `label` / `name` / `value` / `count` / `leaf`. The **Icicle** draws
the hierarchy sized by *strategy count* and coloured by mean metric on a ramp
whose range comes from the data; the **Scatter** is the regime view and the
factor view merged, Y the metric and X / Z the term- and equity-risk-premium
betas over one sample — the Window's days, inside the regime bucket **when a
regime is switched on**. The regime is opt-in (v0.9.33): a *Condition on
regime* checkbox heads the section and the default is off, because every
bucket is a subset of the window — an always-on regime opened the Scatter on
`VIX < 15`, most of the window's days dropped, with nothing on screen saying
the sample had been narrowed and no way to ask for the plain factor view. The
switch is gated in `regime_indicator()`, which returns None while the box is
clear: that is already what an absent indicator returns, so the unconditioned
view is a path both states share rather than a second branch at the render.
Type, Source and Bucket hide while it is off — the bar's hide-don't-rebuild
rule — so ticking it back on finds the last choice still chosen. The
**Strip** is six weekday columns of 1D returns — **T-1 back to T-6**, never
today, whose return is against a price still moving — the only view that can
draw *this week*, **ruled between the days** (v0.9.32): a solid bold line on
each half-integer boundary of its numeric x-axis, with the template's own
gridlines off because those land on the column *centres*, so a line ran down
the middle of each day's cloud while the boundary between two days was
unmarked.

All three **drill**, down **Solution → Asset Class → Category → Family →
Strategy** (v0.9.25). `ANALYTICS_LEVELS` leads with `solution` because that is
how the desk browses the catalog, and **every level is a stop**, so
`drill_levels()` is derived from the hierarchy rather than declared beside it.

Since v0.9.27 the **first level is a filter, not a cell**: a *Solution* chip
group in the bar picks one solution and the card draws that subtree alone,
based at `(solution,)` with the Level chips offering `drill_levels()[1:]` and
the breadcrumb naming the solution as its root. The card used to open on every
solution at once — a row of sibling cells with no way to say which one you
came to look at. The chips are built from the **drawn universe**, not from
`UNIVERSE_SOLUTION_VALUES`: that is what the universe is filtered *by*, and
the catalog's `Beta` solution does not survive it, so a chip for it would draw
an empty chart. Two clamps keep the filter honest — `narrow_to` puts the base
back when a zoom-out would walk off it, and the Icicle's frame is filtered to
the solution so Plotly cannot zoom out past it either. `DRILL_ROOT_LABEL`
(**QIS Strategy**) still names the root in the window between construction and
the first render, before a solution is pinned.

One frozen `Drill(scope, level)` (`src/layout/drill.py`) is written through
**one setter**, and a marker click, an icicle zoom, a Level chip, a breadcrumb
segment and a table row all go through it — so no chart holds a private focus.
A node is a **path**, never a bare label, because *Emerging Markets* sits under
two asset classes in the shipped catalog and a label alone would average two
unrelated groups into one point. A group's value is the **equal-weight mean**
of its members, taken after the regime mask, and colour **keys to the points
shown** — their own level, because a key that stops varying stops informing.

**That rule has one implementation** (`platform_charts.color_values`,
v0.9.31). It had two: the charts keyed off the level's *name*, the palette
builder off the path's *depth*. They agreed only while the card was based at
the root — v0.9.27 based it at a solution, so every point sat at depth 1, the
palette was built for the parent (`ARP`) while the charts looked up the label
(`Equity`), every lookup missed and the Scatter and the Strip each drew a
single grey trace. The curated `ASSET_CLASS_COLORS` had stopped applying for
the same shape of reason: it was keyed on `analytics_levels()[0]`, which
stopped being asset class when `solution` took the lead.

**The Icicle's zoom is the drill, which means it must be re-asserted.** A cell
click zooms Plotly client-side *and* re-renders the trace from the kernel; a
trace built without `level` renders at the root, so the zoom was undone the
instant it happened while the table and the Level chip correctly showed the
narrowed state (v0.9.25). The trace is now built from the scope, and clicking
the cell you are already inside zooms out, as Plotly's own icicle does.

The drill is a **position**, not a setting, so it sits on its own strip below
the bar (`.bbg-drill-bar`), breadcrumb first — "where am I" reads before "how
deep". Scope shows on every chart, the Icicle included; Level hides there,
because a chart drawing every level at once has no single depth to select.

**A group's hover says what it averaged** (v0.9.39, #388). All three charts
route it through one `_members_note`, which reads
`(Average over N Strategies)` and is **empty for a leaf**. It said
`· mean of 3`, which names the wrong noun — beside a number, "mean of 3"
parses first as *the mean is 3* rather than as the mean of three things — and
before that it was the bare integer, which rendered `1Y Sharpe 1.23 3`. The
Icicle was worse and separately wrong: a `hovertemplate` is one string for the
whole trace, so its `%{customdata[0]:.0f} strategies` rendered on **every**
node and read **"1 strategies"** on each leaf — the common case here, where 16
of the shipped catalog's 17 root points are one-member. It carries the note in
`customdata` now, like the other two.

The points table reads `points()` and never a figure's traces, and a row click
routes on the **`leaf` flag**: a group narrows the drill, a strategy opens in
Single Strategy through the same `_show_in_single_strategy` the catalog grid
and the leaderboard use. **Not on `count`** — a one-member *group* has a count
of 1 too, and 16 of the shipped catalog's 17 root points are one-member
categories, so that route clears the user's filters and then hands a category
name to a ticker dropdown. The path cannot disambiguate them either: a family
node and a ticker under it are both three segments deep. The flag is carried
for exactly this reason. Chart and table stand at one fixed `ANALYTICS_HEIGHT`
for `CATALOG_TABLE_HEIGHT`'s reason — stretching lets whichever box holds more
content set the row — **and the figures are built at that height too**
(`ANALYTICS_HEIGHT_PX`, v0.9.27), which the token's comment had claimed since
v0.9.24 without it being true: the charts took the app-wide `CHART_HEIGHT`, 100px
taller than their box, so the card clipped every one it drew. The box is also
the card's **big number** (420 → 504 → **720px**, v0.9.28), because height is
the Icicle's only lever: `tiling.orientation="h"` runs depth left to right, so
the width is split four ways whatever the catalog holds while the *height* is
split among siblings. They split **60:40**
as flex shares with `min-width: 0`,
the `COMMENTARY_*_SHARE` pattern: the 360px basis this replaced squeezed the
table into a strip on a wide screen. Both `ITable`s now wear a shared **`.bbg-itable`**;
`.bbg-catalog` keeps only the group bands and the filter row.

The Multi-Strategy tab is **the catalog table with ticks** (epic #341,
v0.9.29). It was the v0.8 idiom the rest of the app had left behind: a
*Filters* accordion holding a 240px checkbox list of the whole catalog beside
pill-tabs over more checkbox groups, nine `≥ / ≤` threshold rows typed against
numbers that appeared nowhere on screen, two date pickers over a window nothing
explained — and a pick that reached the analytics only through **Refresh
prices**, which refetched a cache already holding the answer. The catalog it
was picking from is the one the Platform tab draws grouped, with performance
columns, one tab away.

Now it is that table: `section_panel` + a *Table view* `control_bar` reading
**Group by · Window · Benchmark**, a **filter row** beneath it pairing the
dimension chips with that dimension's values, the same `ITable` in Select's
`multi` style with a leading **tick column**, then the **Selected Strategies**
strip of `[TICKER] ×` cards, then the two analysis panes.

Terminal use trimmed it hard (v0.9.30). The **second grid went** — an
ipydatagrid of the selected set's performance sat under the itables catalog,
two tables of the same strategies in two stacks, and the catalog already shows
every one of those numbers for every row. The **quant columns went from seven
to four** (Sortino · Calmar · Beta · Treynor): seven across four windows is 28
columns, and VaR, RSI and Jensen α are the ones a reader narrows by least. The
tick became **its own column** rather than a class on the Ticker cell, because
Select draws its checkbox as a pseudo-element and sharing a cell put the two
on top of each other at some widths and beside each other at others. That
pseudo-element is **centred by us, not by the bundle** (v0.9.35, #343): Select
centres it, then its own `table.dataTable.compact` rule re-declares the
centring margin at twice the value, and itables' default `classes` carries
`compact` — so the box drew half a box above centre on every table in the app,
reading as pinned to the top of the row. The cards
lost their names, which were long enough to push the **×** off the end of the
card so it stopped rendering at all; what identifies a card now is its
asset-class colour, a `BASKET_TAG_WIDTH` block down its leading edge (10px
since v0.9.31 — at 3px it read as trim, where the block's whole job is to say
which strategy is which across a wrapping strip). And **Refresh prices went**, with its
overlay: selection never needed it — the startup fetch pulls every catalog
series — so a button whose one effect was a loading overlay taught the user
that picking a strategy costs a round trip. The cost is deliberate: **prices
are now whatever the startup fetch returned** for the life of the session. `CatalogTable` (`src/layout/grids.py`) is the base the Platform's
`UniverseGrid` and the new `BasketGrid` share; what a click *means* is the
subclass's, which is the only reason there are two.

Four rules hold underneath.

**The basket is the source of truth, not the table's selection.** `Basket`
(`src/layout/basket.py`) holds an ordered ticker tuple and the cap, and the
grid, the cards and the analytics are views of it. itables destroys and re-news
the table on every options change, so a row *position* is worthless across a
filter — the basket is what survives, and the grid re-derives its ticks from it
after each rebuild. Every write checks the cap **before** assigning, so a
rejection changes nothing and fires no observer; an over-cap add is rejected
**whole**, because seating the first few in table order would be the app
choosing a subset of what the user asked for. A member the filters hide is
never touched by a table event and keeps its card.

**The kernel never guesses what the browser is showing.** The search text and
the per-column filter row live in the browser by design (#285), so *Select all
shown* and a group-header click run as DataTables actions over the applied
search and come back as positions. `group_member_rows` is the header's walking
rule — data rows until the next header at that level or nearer the root — in
Python, because the browser is not available to a unit test; `_JS_GROUP_SELECT`
transcribes it.

**The window is derived, not chosen.** `basket_window` is the **intersection**
of the members' histories — the latest first-valid date to the earliest
last-valid — and it names the member binding each edge. The two date pickers
are gone: nothing said where their bounds came from, so the control invited
second-guessing a number the tab never explained. The strip's readout says it
instead, and the binding member's card carries a marker, which makes
shortening the sample one click — remove that strategy.

**No BQL from a control.** A chip, a filter, a tick, a header or a card
re-slices the cache on a short debounce (`RESLICE_DEBOUNCE_S`), deferred while
a Refresh is running because both write `state.cur_prep`. *Refresh prices*
means only what it says, and sits on the section's title line rather than among
the settings.

Two more, on the filters: **structure in the bar, text and numbers in the
table.** The filter is **its own bar** (v0.9.32), titled *Filter* and headed
**Dimension · Values**: a `ChipGroup` names a dimension and a `FilterStrip`
beside it shows that dimension's values, the two sharing the bar at **20:80**
(`FILTER_CHIPS_SHARE` / `_VALUES_SHARE`, carried on `RailSection.share` — the
`COMMENTARY_*_SHARE` pattern rather than the 280px column they started as,
because the chip set is always the same seven while a dimension can carry
forty values). Unlabelled it was fourteen identical chips on one row, half of
them choosing *what* was filtered and half choosing *to what*, with nothing
saying which was which or that either was a filter; the rule between them is
`.bbg-rail-block`'s, the same line every other bar draws between two controls.
The headings are **Dimension** and **Values**, not the *group* and *selection*
the behaviour is described by in conversation — *Group by* one row up is the
table's row grouping and *Category* is a classification tier, so either word
would name two things at once. One control per dimension, swapped
by `display`, so switching dimensions keeps every dimension's ticks; a chip
badge counts the active ones, because a hidden selection is otherwise
invisible. And the nine quant
thresholds became **columns** — Sortino · Calmar · Beta · Treynor, named
`"{window} {metric}"` so the Window chip hides them and the comparison filter
row filters them with no new branches. `QuantColumns` is the one place both
tabs read, so the number on screen is the number the threshold compares —
which is how v0.9.30 found two ways those numbers had been wrong: the window
loop divided **years** by `TRADING_DAYS_PER_YEAR` as if they were days, and
every caller of `ann_beta` handed it a benchmark **price** series where it
covaries against returns, so every Beta had been collapsing toward zero and
taking Treynor and Jensen with it. `stats.risk.benchmark_returns` is the
conversion, and `factor_beta` is the one caller that already held returns. Vol and the cross-sectional Z stayed behind: the Platform tab ranks,
this tab narrows.

The Single Strategy tab is **the same table again, in single-select** (epic
#363, v0.9.36). It was the last of the v0.8 idiom, and the last thing the
other two tabs had already left behind: a `W.Dropdown` of ticker strings
inside a *Filters* accordion, beside a 240px checkbox column and nine
`≥ / ≤` threshold rows typed against numbers that appeared nowhere on screen —
while the catalog those rows were narrowing sat one tab away, grouped, with
every one of those numbers in a column. It is now a `section_panel` over the
same two bars the Multi tab picks its basket from, and `filter_panel.py` —
`FilterPanel`, `CategoricalFilter`, `QuantFilter` — is gone entirely.

**The pick is a `Pick`, not a row and not a widget's value.** `Basket`'s
single-ticker sibling: five things write it — a row here, a catalog row, a
Leaderboard row, a points-table row and a basket card — and the grid, the
profile card, the metrics table and both panes are views of it. Two
behaviours fall out and both were bugs before. `StrategyGrid` re-derives its
lit row **by ticker** after every rebuild, because itables destroys and re-news
the table on every options change. And a pick the filters hide **stays
picked**, with the profile card saying why no row is lit — so
`_show_in_single_strategy` no longer clears anyone's filters, a workaround
that existed only because a dropdown could not offer a ticker its options
list had dropped.

**Its numbers are HTML now** (#366). Two `ipydatagrid` canvases stood there —
a `PerfGrid` and the calendar's — each carrying the v0.6.5 theme-refresh
invariant (#223) and a Lumino canvas, for tables that never sort, scroll
sideways or take a click. `strategy_metrics` gives eight metrics over every
`stat_windows()` window plus since-inception, at two decimals, `—` where a
window is not served. **The calendar's heatmap survived; only its grid went** —
it is the one thing on the tab a desk reads at a glance, and the metrics table
is summary statistics rather than the path they came from. Its five steps are
CSS classes on the bands `style.py` now declares for **both** stacks, and its
five pills became a `ChipGroup`, which was the last `_make_tab_button` set in
the app — laid out as a **row** since v0.9.37 (#383), which is what every
other chip group in a bar has always been: a `_ChipStack` is a `VBox` and runs
horizontally only when told to, so these five stacked five high and took a
third of the section's fixed height from the calendar they head. One departure from the grid it replaced: the metrics table measures
the **analytics window**, where `perf_table` was deliberately handed the full
fetched frame (#311) — a `3Y` figure assembled from history the window
excludes is a number under a label that does not describe it, so an unserved
window is a dash whatever the fetch holds.

**And the zoom is a measurement** (v0.9.37, #380). Zooming the cumulative
chart was cosmetic — the line rescaled and nothing else knew the reader had
narrowed to a period. A semi-transparent readout now sits inside the figure,
top-left, carrying `span_metrics` over exactly the x-range on screen and
following every zoom, pan and reset; on a reset it reports the whole window,
so it is never blank while a line is drawn. It is a **Plotly annotation**, not
a widget, because ipywidgets cannot overlay one on a figure — pre-allocated
and retexted in place, the `WeeklyScatterChart` rule. That buys the overlay
and costs the stylesheet: an annotation takes a small HTML subset, and
**exactly four named entities survive it** — `&amp;`, `&lt;`, `&gt;` and
`&nbsp;`, the whole list Plotly's bundled parser carries. Anything else is
printed as typed, which is how the separator written `&middot;` reached the
screen as the literal text `&middot;` (v0.9.38, #386). Separators are literal
characters now, and a test holds the readout to those four. Two things make the
number honest. The span is **clamped to the strategy's own history**, since a
zoom can run past either end of the data and measuring across the empty part
would divide a real return by a span covering dates the index did not exist
for. And **under a year the annualized metrics are dropped, not scaled**:
`ANNUALIZED_METRICS` — Vol, Sharpe, Sortino and Calmar, the last because it is
a ratio *of* an annualized return — leave the panel entirely, Return becomes
the period's cumulative return under its own label, and the panel says which
of the two regimes it is in so a missing Sharpe reads as a decision rather
than as a gap. Max DD, Beta and Correlation stay throughout: none of them
annualizes.

**Return Distribution draws outlines, and its stats are HTML** (v0.9.38,
#386). Filled histograms at `barmode="overlay"` blend where they cross, and
two return distributions cross over almost their whole body — so a strategy
against its benchmark drew a pure colour in each tail and a **third** through
the middle, which reads as a series no legend entry accounts for. A step
outline has nothing to blend: N series are N lines, countable, and the tails
stay readable where a 55%-opacity fill washed them out. One shared bin edge
set, so the heights are comparable rather than only each line against zero.
The per-ticker stats beneath it became an HTML table for `strategy_metrics`'
reason — it never sorts, scrolls sideways or takes a click — which took the
last `ipydatagrid` import out of `charts.py`. It is **tickers down,
statistics across**, the transpose of `.bbg-metrics`, because here the row is
the series and a basket can hold five of them. Both tabs draw it, so it takes
the frame rather than reading a panel's state, and its numbers go through
`_metric_cell`: the two-decimal rule, the dash and *red for negative, no
green* are one implementation across every HTML stats table. **Mean reads in
basis points** (v0.9.39, #388), which is that rule's answer to a statistic
three orders below its neighbours rather than an exception to it: a daily
mean lives around 0.0001–0.0006, so two decimals of a percentage gave it one
significant figure and printed `0.06%` for two strategies a fifth apart.
Basis points move the decimal and keep the decimals; the heading carries the
unit, which is why `RETURN_STAT_UNITS` declares a heading apart from the
column name.

**Every option in the analysis picker draws** (#367). Three of eight were dead
ends: *PCA Analysis* and *Defensive Scoring* were `_StubChart`s drawing
*coming soon*, and *Performance Ranking* drew the same placeholder because
nothing ever passed it scores. Each was retired **into an issue of its own**
(#374, #375, #376) before being deleted, so the intent outlives the
placeholder; `PerfRankingChart`'s radar body survived as `RadarChart`, which
is what the spiderweb is built on. What the picker offers now is Weekly
Scatter · Return Distribution · Factor Scatter · Drawdown · Rolling · Decile ·
Regime Profile · Risk Profile.

Four of those are new or rebuilt, and each replaced something that was either
duplicated or not drawable:

- **Rolling** is one figure whose statistic is a chip — Correlation · Sharpe ·
  Calmar · Beta — and the title, the y-axis and the **reference line** all
  follow it (0, 0, 0, **1**). It replaced two near-identical `RollingRefChart`s
  on the Multi tab while rolling Sharpe and Calmar had their stats functions
  and no chart anywhere; one component serves both tabs now, and the benchmark
  control hides for the two statistics that do not read one.
- **Decile** cuts the **benchmark's weekly** returns into ten buckets and
  draws the strategy's mean return in each beside the benchmark's own, so
  convexity reads left to right — which no summary statistic on the tab shows,
  a β being the average slope and silent about whether the slope is the same
  at both ends. Weekly because a daily decile's tails are single-session noise
  and marking conventions. The benchmark decides the buckets; cutting on the
  strategy's own returns would draw a monotone staircase for any series at all.
- **Regime Profile** draws all three buckets of one regime at once — return vs
  vol per bucket, plus the unconditioned **Full period** point as the anchor so
  the three read as deviations rather than as three unrelated dots, plus the
  benchmark's three. It has **no bucket control**, because all three buckets
  are the chart. The anchor is told apart by its **shape** and not by being
  grey (v0.9.37, #381): colour keys to the *series*, so a strategy's anchor and
  its three buckets are one colour and the benchmark's are another. It keyed
  off the `groupby` position until then, which counts **groups** — four of them
  once a benchmark is on — so a series' anchor and its own cloud came out in
  different colours and pairing them was legend work rather than something the
  eye did.
- **Risk Profile** is five βs on one polar axis — ERP · Term · Volatility ·
  Trend · Carry — and **the axis is a percentile**, which is the whole design:
  a Carry β of 0.3 is large where an ERP β of 0.3 is small, so a polygon on the
  raw numbers says only which factors are quoted in bigger units. The raw β
  rides in the hover. A factor the feed cannot serve is a **missing spoke**,
  not an exception. It retired `FactorScoringChart`, three bars of ERP, Term
  and Trend; *Factor Scatter* stayed, because it is a **history** — one marker
  per month — where the spiderweb is one shape over the whole window.

**Weekly Scatter conditions too** (v0.9.37, #382), and draws **both** clouds:
the full window muted underneath, the weeks inside the bucket over it in
colour with their own quadratic, and the β / convexity / R² panel reporting
the two fits on two lines. A conditioned view that simply replaced the cloud
would show a sample that had quietly shrunk; what a reader wants to see is the
relationship *move*. Its conditioned pair of traces is **pre-allocated** like
the unconditioned one, because a same-count trace replacement can be dropped
by older widget-manager frontends — the repaint bug this chart hit on BQuant.

Three rules hold underneath. **Regime resolution has one implementation**:
`RegimeControls` (`src/layout/regime_controls.py`), which the Platform card
delegates to and both new charts construct their own instance of — the epic
named copying those four methods as the risk, and two tabs each conditioning
their own chart is two selections, not one. **The cross-section is measured
once**: the percentile axis needs every catalog strategy's β to five factors,
so it is cached against the price frame's identity, the `QuantColumns` pattern,
and a Refresh invalidates it by rebinding. And **one new ticker**, `MOVE
Index`, which joins `FACTOR_TICKERS` and rides the single startup fetch — the
Volatility factor is VIX and MOVE **z-scored and then averaged**, because VIX
runs 15–30 and MOVE 80–130 and a raw average is an equal-weight factor in name
and a MOVE series in fact. A missing leg degrades to the other and says so in
the series' name.

Every number in a table reads at **two decimals** (v0.9.32) — `0.00%` or
`0.00`, on both stacks. It is `_STAT_SUFFIXES` that decides, the same tuple the
uniform width, the comparison filter and the Window chip's hiding key off, so a
metric added there is rendered without a branch of its own. Two gaps were
closed to make that true: the itables renderer keyed off `_is_percent_col`, so
the four quant metrics — the only stat suffixes that are neither a percentage
nor Sharpe — matched no branch at all and DataTables printed the stored float
at full precision in an 82px cell; and `_perf_renderers` fell through to its
formatless text renderer for the same columns. The Leaderboard's value came
along with them, from `+1.2%` to `+1.23%`, so a row does not show two
precisions.

## Current version

`v0.9.41` (see `.meta/VERSION` and the **Branching** section of
`.claude/context/conventions.md`).

## Detailed context

The full reference material is split into focused files under
`.claude/context/`. Read the relevant one before editing that area:

- **`.claude/context/architecture.md`** — the module/architecture map and the
  detailed UI screen-layout walkthrough (Platform + Multi-Strategy + Single
  Strategy tabs).
- **`.claude/context/style.md`** — the visual design system: style tokens
  (`src/style.py`), the dark chrome CSS, the dark chart theme, color identity.
- **`.claude/context/run_instructions.md`** — running on a BQuant terminal and
  locally (mock prices).
- **`.claude/context/data.md`** — the `data/indexdb.json` data contract and the
  BQL query contract.
- **`.claude/context/conventions.md`** — data-flow / state / templating
  conventions, plus **Branching** and the **Development workflow**.
- **`.claude/context/code_formatting.md`** — ruff / black / pre-commit.
- **`.claude/context/testing_notes.md`** — `pytest` plus the manual
  verification checklist for the mock-price render.
