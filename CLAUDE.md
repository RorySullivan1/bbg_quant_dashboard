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
tabs — **Platform** (a control bar over the all-catalog performance grid and a
ranking rail down its left + a Platform-analytics card of Sunburst / Regime /
Factor-exposure charts), **Multi-Strategy**
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
Solution → Category → Family), adding a filter pill, or changing which rings
the Platform sunburst draws (`SUNBURST_LEVELS`) is a `config.py` edit, not a
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
they ticked; the grid shows **one stats window at a time**, chosen in the left
rail and offering only what `LOOKBACK_YEARS` can serve. Clicking a
row opens that strategy in Single Strategy. Two rules hold underneath: **row
contiguity at every grouping level is a correctness requirement**, because
RowGroup only gathers adjacent rows, and **changing the window hides columns
rather than dropping them**, so it cannot disturb the grouping or the
selection. See `.claude/context/conventions.md`.

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
which is why the app fetches `SCORE_HISTORY_YEARS = 6` while analytics stay at
`LOOKBACK_YEARS = 5`; the raw value rides behind it in parentheses so a reader
can see what was standardized, and the sentiment colour sits on the score, which
is what the row is read by. The asset-class-demeaned z-score is a different
figure and stays where it belongs, on the Platform sunburst and the Z-Score
column. **Clicking any row opens that strategy in Single Strategy**, through the
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

The Platform tab is **one composed surface** (epic #276, v0.9.21). Its controls
sit in two containers of the same chrome, differing only in direction: a
**horizontal bar above the table** (*Table view* — Group by + Window, the two
controls that shape the rows) and a **rail down its left side** (*Z-Score
ranking* — Metric / Window / Lookback). Both are built from one component
(`control_bar` / `control_rail`, `src/layout/rails.py`) and carry `ChipGroup`
chips. The table's box and the rail are **one fixed height** (`CATALOG_TABLE_HEIGHT`),
set from the same token. Stretching was tried first and is wrong here: it makes
whichever box holds more content set the row, so the table grew to the rail on a
small catalog and the rail to the table on a large one. The table's internals
fill that box — the search row and the row-count readout take what they need,
the row area scrolls in the remainder — so the height is one number to tune with
nothing to keep in step with it. Chips are pinned `flex: 0 0 auto`: a flex item
shrinks before its container scrolls, so a rail with more chips than fit squeezed
them flat instead of scrolling. A chip group is a **widget, not a row of buttons**: it presents a
`W.Dropdown`'s `value` / `label` / `observe` surface, which is what let the
z-score controls move into a rail as a restyle rather than a rewrite of
everything that reads them, and its multi-select flavour reports **membership**
so a tick order cannot reach the grouping. The table beside the rail takes
the remaining width (`flex: 1 1 0%` **and** `min-width: 0`, or a wide column
set pushes the rail off instead of scrolling inside the table), leads with a
top-left search box, draws its tiers as stepped cyan bands, and carries a
**per-column filter row** beneath its header labels — one box per column, and
the stat columns' boxes take a **comparison** (`>1`, `1..3`) rather than a
substring, in the units the cell shows, because those columns are searched on
the raw value a `5.23%` cell stores as `0.0523`. One deliberate exception
lives here: **the filter text is held in the browser, not on `UniverseGrid`**,
because every options change destroys and rebuilds the table and no traitlet
carries typed text to the kernel. See `.claude/context/style.md` and
`conventions.md`.

## Current version

`v0.9.22` (see `.meta/VERSION` and the **Branching** section of
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
