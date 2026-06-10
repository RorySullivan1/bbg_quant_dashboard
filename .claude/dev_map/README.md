# Development map

Forward-looking roadmap for `bbg_quant_dashboard`. Each `vX.Y.Z.md` file
in this directory is a stub for a planned release — fill it in as the
scope for that version firms up (goals, scope, status, related PRs). Start a
new stub by copying [`TEMPLATE.md`](TEMPLATE.md) (the reusable section skeleton)
to `vX.Y.Z.md`; `TEMPLATE.md` is not a version, so it's skipped by the list
below.

- **Current shipped version:** see [`.meta/VERSION`](../../.meta/VERSION)
  (`0.8.6`). Keep that file and the "Branching" section of `CLAUDE.md`
  in sync on every bump.

### Roadmap status

Each checkbox tracks **implementation / shipping**, not whether the stub is
drafted — every stub below is already written. Convention:

- `[ ]` — not started.
- `[ ]` + _(in progress)_ — work underway on a `vX.Y.Z` branch.
- `[x]` — shipped (`.meta/VERSION` bumped, stub's PR list filled in).

Within each stub, the **Suggested PR sequencing** and **Acceptance criteria**
sections carry the same checkboxes so progress is visible at a glance; tick
them as PRs land. Keep this list and each stub's `> **Status:**` line in sync.

- [x] `v0.5.0` — feature-complete baseline (shipped; pre-roadmap).
- [x] `v0.6.0` — Refactoring & Optimization (shipped).
- [x] `v0.6.5` — Dashboard Styling: dark technical chrome, bold masthead,
  loading overlay + staged progress bar (shipped).
- [x] `v0.6.9` — Optimization & Responsiveness: in-memory caching (with a
  best-effort, read-only-FS-safe disk cache), memoized derived computations,
  and event-driven benchmark/regime controls that re-render a chart on switch
  instead of on a full refresh (shipped).
- [x] `v0.7.0` — Platform Tab Expansion: conditional-formatted all-catalog
  grid with a dynamic z-score column, a factor-beta scatter (equity risk
  premium vs term premium), and an asset class → theme → ticker treemap
  (shipped).
- [x] `v0.7.1` — Platform scatter: drop the duplicative chart title, expand to a
  **3D** factor scatter (z-axis = β to BSLXAT "Trend Exposure"), and color
  markers by asset class instead of grey (shipped).
- [x] `v0.7.2` — Platform performance table: remove the Since-Inception columns
  (shipped).
- [x] `v0.7.3` — Platform treemap: color tiles by **z(1W Sharpe)** (was 1M),
  size stays z(6M Sharpe), and drop the duplicative chart title (shipped).
- [x] `v0.7.5` — Multi-Strategy tab fixes: Sharpe color-coding in the selected
  perf grid, replace the analysis date slider with two side-by-side date boxes,
  and restructure the correlation Benchmark/Regime controls (>/< dropdown)
  (shipped).
- [x] `v0.8.0` — Key Highlights Rework: two side-by-side panels — a monthly
  statistical-superlatives board (top performer, longest bull run, strongest
  trend, …) and a new-launches board with metadata (shipped).
- [x] `v0.8.4` — Superlatives Redo: rebuild the superlatives board around
  symmetric best/worst, technical/character indicators (return autocorrelation,
  MACD, drawup, recovery speed, win-rate, skew) with cross-asset-neutral
  asset-class-demeaned z-score ranking and calculation-only tooltips (shipped).
- [x] `v0.8.5` — Regime Analysis: a Platform-tab tabbed section (Risk vs Return /
  Correlation) between the factor scatter and the treemap, with a regime-type
  dropdown (volatility / trend / liquidity / rate-level) and conditional buckets
  (e.g. VIX buckets) that condition each chart — volatility wired this cycle, the
  rest scaffolded (shipped).
- [x] `v0.8.6` — Factor Scatter Zero Planes: three translucent zero-reference
  planes (x=0/y=0/z=0) through the Platform 3D factor-beta scatter so the origin
  reads in every dimension (small enhancement; shipped just after v0.8.5).
- [ ] `v0.9.0` — Single Strategy Tab: a third top-level tab with a per-strategy
  profile + cumulative chart, a tabbed monthly-return calendar table, and
  tabbed analytics charts (weekly-vs-benchmark, histogram, factor scatter).
- [ ] `v1.0.0` — Release Hardening: testing, final optimization, documentation,
  compliant legal-disclaimer placement, enhancements, and the 1.0 release
  mechanics.

## How this ties to branching

Branches follow `v{MAJOR.MINOR.PATCH}/{type}/{short-description}` (see
`CLAUDE.md` → "Branching"). When you start work toward a version, open
branches under that version's prefix and record the scope in the matching
stub here.

> **Caveat:** when an integration branch is named exactly `v{X.Y.Z}` (as
> with `v0.6.0`), git cannot also host nested `v{X.Y.Z}/<type>/<desc>` refs
> (a ref can't be both a file and a directory). In that case use the
> flattened `v{X.Y.Z}-<type>-<desc>` form for feature branches.
