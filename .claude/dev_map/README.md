# Development map

Forward-looking roadmap for `bbg_quant_dashboard`. Each `vX.Y.Z.md` file
in this directory is a stub for a planned release — fill it in as the
scope for that version firms up (goals, scope, status, related PRs).

- **Current shipped version:** see [`.meta/VERSION`](../../.meta/VERSION)
  (`0.5.0`). Keep that file and the "Branching" section of `CLAUDE.md`
  in sync on every bump.
- **Planned roadmaps:**
  - `v0.6.0` — Refactoring & Optimization (written).
  - `v0.6.5` — Dashboard Styling: dark technical chrome, bold masthead,
    loading overlay + staged progress bar (written; a styling point release
    landing after v0.6.0).
  - `v0.7.0` — Platform Tab Expansion: conditional-formatted all-catalog
    grid with a dynamic z-score column, a factor-beta scatter (equity risk
    premium vs term premium), and an asset-class treemap (written).
  - `v0.8.0` → `v1.0.0` — empty stubs, to be filled in.

## How this ties to branching

Branches follow `v{MAJOR.MINOR.PATCH}/{type}/{short-description}` (see
`CLAUDE.md` → "Branching"). When you start work toward a version, open
branches under that version's prefix and record the scope in the matching
stub here.

> **Caveat:** when an integration branch is named exactly `v{X.Y.Z}` (as
> with `v0.6.0`), git cannot also host nested `v{X.Y.Z}/<type>/<desc>` refs
> (a ref can't be both a file and a directory). In that case use the
> flattened `v{X.Y.Z}-<type>-<desc>` form for feature branches.
