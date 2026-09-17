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
block** (Weekly Commentary + a two-section Key Highlights panel: Market
Superlatives and New Launches) → a **top-level pill-button tab bar** with three
tabs — **Platform** (all-catalog performance grid + a Platform-analytics card
of Sunburst / Regime / Factor-exposure charts), **Multi-Strategy**
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
`SingleAnalysisPane`, `SelectionSlice`, `RenderContext`, `SuperlativeCard`,
`LaunchCard`, `LevelRegime` / `TercileRegime`. Two rules hold across all of
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
checkboxes) but the *nesting order is always the hierarchy's*, never the order
they ticked; the grid shows **one stats window at a time**, chosen from a radio
beside the table and offering only what `LOOKBACK_YEARS` can serve. Clicking a
row opens that strategy in Single Strategy. Two rules hold underneath: **row
contiguity at every grouping level is a correctness requirement**, because
RowGroup only gathers adjacent rows, and **changing the window hides columns
rather than dropping them**, so it cannot disturb the grouping or the
selection. See `.claude/context/conventions.md`.

## Current version

`v0.9.18` (see `.meta/VERSION` and the **Branching** section of
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
