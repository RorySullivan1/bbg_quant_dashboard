# CLAUDE.md — bbg_quant_dashboard

Repo memory for future Claude sessions. Read this before editing.

## Project purpose

A Bloomberg BQuant App that lets clients browse an index catalog: filter by
metadata, look up tickers, and view performance, correlation, and a 1-year
rolling Sharpe-ratio z-score over a 5-year lookback. Metadata is stored
locally in `data/indexdb.json`; time-series prices are pulled from BQL at
runtime. The UI is built with `ipywidgets`, `plotly` (interactive charts
via `FigureWidget`), `ipydatagrid` (the per-strategy tables) and `itables`
(the grouped all-catalog table), and is deployable via Voila.

The whole UI renders on a cohesive **dark technical chrome** (v0.6.5) and is
organized as: masthead banner → an always-visible **all-catalog commentary
block** (two sections at 60:40 — a ranked **Leaderboard** of four metric
columns with clickable rows, beside the **QIS Bulletin**, which switches
between authored Commentary notes and New Launches) → a
**top-level pill-button tab bar** with three
tabs — **Platform** (one control bar over a full-width all-catalog performance
grid + a Platform-analytics card: a chart — Icicle / Scatter / Strip — beside
a table of its own points), **Multi-Strategy**
(a filter accordion, a selected-strategy perf grid, and two side-by-side
analysis panes), and **Single Strategy** (a per-strategy deep-dive: a
live-narrowing filter accordion, a profile card + cumulative chart, a
monthly-return calendar, and two analysis panes) → disclaimers. All compute
lives in `src/`; the notebook is a one-liner that calls `build_app()`.

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
`build_app()` one-liner constructs, and `PlatformAnalytics`, `FilterPanel` /
`CategoricalFilter` / `QuantFilter`, `SingleStrategyPanel`, `PriceCache` and
the `PriceSource` protocol (`BqlPriceSource` / `MockPriceSource`) each own one
area. **A figure or a table is an object too (v0.9.17 #223):** each `Chart`
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
(1W–**1Y**, `LEADERBOARD_WINDOW_OPTIONS`, a list of its own so a year does not
reach the two controls built from `SHORT_WINDOW_OPTIONS`). **Ranking is by the
score** (#310), which the section title says out loud
(`(Ranked By Normalized 5Y Z-Score)`, built from `LOOKBACK_YEARS` rather than
spelled) — each metric standardized against its *own* trailing history,
which is why the app **fetches** `score_history_years()` — the longest window
the catalog offers plus the sample standardized behind it, ten years today —
while analytics stay at `LOOKBACK_YEARS = 5`; the raw value rides behind it in
parentheses so a reader
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
`LOOKBACK_YEARS` rather than typed. Three rules hold underneath. The column is
**found by the key its builder returned**, never by parsing its header — five
behaviours hang off knowing which column it is (width, ramp, DataTables kind,
number renderer, filter units) and all five failed silently on a relabel (#323).
A sample too short to be a five-year sample **renders a dash** rather than
standardizing against the little it has (`CATALOG_SCORE_MIN_SAMPLE_DAYS`), so
at the `5Y` window an index needs roughly 7.5 years of history to be ranked.
And **Vol is not rankable here**: the ramp and the sort both say *higher is
better*, which volatility is not — it stays on the Quantitative filter, where
nothing claims a direction for it. The analytics card offered it too until
epic #331, which is the "its own issue" #321 named.

The analytics card below the table is **a chart beside its own points** (epic
#331, v0.9.24). Its controls are a second `control_bar` in the same chrome —
*Chart view*: **Chart · Metric · Window · Regime · Level · Scope** — and
Metric and Window are the table's own option lists, so the two surfaces can be
read at different windows but cannot *offer* different things. Sections the
active chart does not read are **hidden, not rebuilt**, so a chip keeps its
selection across a chart switch.

Three charts, each a `Chart` that also exposes **`points()`** — the frame it
drew, as `path` / `label` / `name` / `value` / `count` / `leaf`. The **Icicle** draws
the hierarchy sized by *strategy count* and coloured by mean metric on a ramp
whose range comes from the data; the **Scatter** is the regime view and the
factor view merged, Y the metric and X / Z the term- and equity-risk-premium
betas over one sample — the Window's days inside the regime bucket; the
**Strip** is five dates of 1D returns, the only view that can draw *this week*.

All three **drill**. One frozen `Drill(scope, level)` (`src/layout/drill.py`)
is written through **one setter**, and a marker click, an icicle zoom, a Level
chip, a breadcrumb segment and a table row all go through it — so no chart
holds a private focus. A node is a **path**, never a bare label, because
*Emerging Markets* sits under two asset classes in the shipped catalog and a
label alone would average two unrelated groups into one point. A group's value
is the **equal-weight mean** of its members, taken after the regime mask, and
colour **keys to the points shown**: asset class at the root, the points' own
level below it, because a key that stops varying stops informing.

The points table reads `points()` and never a figure's traces, and a row click
routes on the **`leaf` flag**: a group narrows the drill, a strategy opens in
Single Strategy through the same `_show_in_single_strategy` the catalog grid
and the leaderboard use. **Not on `count`** — a one-member *group* has a count
of 1 too, and 16 of the shipped catalog's 17 root points are one-member
categories, so that route clears the user's filters and then hands a category
name to a ticker dropdown. The path cannot disambiguate them either: a family
node and a ticker under it are both three segments deep. The flag is carried
for exactly this reason. Chart and table stand at one fixed `ANALYTICS_HEIGHT` for
`CATALOG_TABLE_HEIGHT`'s reason — stretching lets whichever box holds more
content set the row. Both `ITable`s now wear a shared **`.bbg-itable`**;
`.bbg-catalog` keeps only the group bands and the filter row.

## Current version

`v0.9.24` (see `.meta/VERSION` and the **Branching** section of
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
