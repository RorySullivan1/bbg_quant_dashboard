# CLAUDE.md — bbg_quant_dashboard

Repo memory for future Claude sessions. Read this before editing.

## Project purpose

A Bloomberg BQuant App that lets clients browse an index catalog: filter by
metadata, look up tickers, and view performance, correlation, and a 1-year
rolling Sharpe-ratio z-score over a 5-year lookback. Metadata is stored
locally in `data/indexdb.json`; time-series prices are pulled from BQL at
runtime. The UI is built with `ipywidgets`, `plotly` (interactive charts
via `FigureWidget`), and `ipydatagrid` (tables), and is deployable via
Voila.

The whole UI renders on a cohesive **dark technical chrome** (v0.6.5) and is
organized as: masthead banner → an always-visible **all-catalog commentary
block** (Weekly Commentary + a two-section Key Highlights panel: Market
Superlatives and New Launches) → a **top-level pill-button tab bar** with two
tabs — **Platform** (all-catalog performance grid + a Platform-analytics card
of Sunburst / Regime / Factor-exposure charts) and **Multi-Strategy Analysis**
(a filter accordion, a selected-strategy perf grid, and two side-by-side
analysis panes) → disclaimers. All compute lives in `src/`; the notebook is a
one-liner that calls `build_app()`.

## Current version

`v0.8.11` (see `.meta/VERSION` and the **Branching** section of
`.claude/context/conventions.md`).

## Detailed context

The full reference material is split into focused files under
`.claude/context/`. Read the relevant one before editing that area:

- **`.claude/context/architecture.md`** — the module/architecture map and the
  detailed UI screen-layout walkthrough (Platform + Multi-Strategy tabs).
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
