---
name: ipywidgets
description: Build and maintain the ipywidgets UI for this BQuant dashboard — VBox/HBox layouts, flex sizing, accordions, the pill-button tab bars, checkbox/dropdown filter groups, and ipydatagrid tables. Use this skill whenever the user wants to add, change, or debug a widget, panel, tab, filter control, layout, or grid in the dashboard, or asks why a control isn't sizing/aligning/updating correctly. Trigger on phrases like "add a filter", "the dropdown is the wrong height", "add a tab", "the panels don't line up", "wire up a button", "the grid columns are wrong", "VBox/HBox", "accordion", "ipydatagrid", or any work on the dashboard's controls or layout in src/layout.py. Distinct from chart work — use the plotly skill for FigureWidget/trace changes.
---

# ipywidgets (this dashboard)

Expert ipywidgets work scoped to the `bbg_quant_dashboard` UI. The whole
widget tree is built in `src/layout.py` by `build_app()`; all style
tokens come from `src/style.py`. The goal is changes that fit the
existing layout idioms — not a generic widgets tutorial.

## Read first

- `src/layout.py` — `build_app()` assembles banner → status banner →
  commentary → top-level pill tab bar (Platform / Multi-Strategy
  Analysis) → per-tab content → disclaimers. `_make_analysis_pane(side)`
  is the factory for the two side-by-side analysis panes.
- `src/style.py` — `Color`, `Font`, `FontSize`, `StatusTone`,
  `Sentiment`, `TabButtonTone` enums plus `LINE_PALETTE`. **Never inline
  a hex or font value — extend the enum and reference it.**
- `CLAUDE.md` — the layout contract and conventions are authoritative;
  re-read the "Project purpose" and "Conventions" sections before
  restructuring anything.

## Layout idioms used here

- **Containers:** `VBox` for vertical stacks, `HBox` for side-by-side.
  The two analysis panes and the left-strategies / right-filter split
  are `HBox`es of two children.
- **Equal-height side-by-side panels:** the left strategies picker and
  the right filter panel are stretched to equal height by letting the
  child grow via `layout.flex` (e.g. `flex="1 1 auto"`) while the parent
  `HBox` stretches both. The `ticker_w` dropdown grows this way to match
  the filter panel's height — do not hardcode a pixel height to fake
  alignment; let flex do it.
- **Widths:** prefer `width="100%"` / `flex` over fixed pixels so the
  app fills a ~full-HD width. The perf grids are the exception (see
  ipydatagrid below).
- **Accordion:** the entire filter box lives inside an
  expandable `Accordion` titled "Filters", `selected_index=0`
  (expanded by default).
- **Pill-button tab bars:** both the top-level tabs and the
  filter-dimension header are rows of `Button`s styled via
  `TabButtonTone` (active = navy bg + white text). Switching tabs swaps
  the visible child / `children` of a container — it does **not**
  recompute or fetch. Keep that cosmetic-only contract.

## Filter controls (narrow-only contract)

This is the single most important behavioral rule and easy to break:

- Checkbox filter groups, the search box, the launch-date pickers, the
  currency dropdown, and the Quantitative ratio thresholds **only narrow
  the `ticker_w` strategies dropdown.** They must NOT trigger a recompute
  or a BQL fetch.
- Value getters read each widget's `.value` regardless of which
  filter-type pill is currently visible, so switching pills is purely
  cosmetic state, not data state.
- **Selected tickers stay visible** in the dropdown even when filters or
  the search box would otherwise hide them — preserve selection state
  while the user types/filters.
- Only **Refresh prices** re-fetches and recomputes. When you add a new
  control, decide explicitly: is it a narrow-only filter (no recompute)
  or does it feed a recompute (read at recompute time only)? Match the
  existing pattern; don't add `.observe` callbacks that secretly refetch.

## ipydatagrid (perf grids)

- The all-catalog grid and the selected-strategy grid use **2-level
  MultiIndex columns** (Info / 1Y / 3Y / 5Y supercolumns over leaves).
- Per-column widths use ipydatagrid's `"<level0>,<level1>"` comma-joined
  `column_widths` keys, built by `_build_perf_column_widths`. If
  MultiIndex widths regress/flake, the documented fallback is uniform
  sizing via `base_column_size` (no `column_widths`) — see CLAUDE.md.
- `_perf_renderers` matches on the column **leaf**
  (`col[-1] if isinstance(col, tuple) else col`) so one renderer set
  serves both grids.
- The selected grid's leftmost "Chart Color" column
  (`PERF_COLOR_COLUMN_NAME`) is a `VegaExpr`-rendered swatch using the
  positional `LINE_PALETTE` — it is the universal chart legend, so per
  chart legends are off. Keep grid color and chart color keyed the same
  way (strategy position in the selected set).

## Workflow for a UI change

1. Locate the existing widget/pattern in `src/layout.py` and mimic it —
   matching the codebase beats inventing a new idiom.
2. Pull any new color/font/size from `src/style.py` (extend an enum if
   it doesn't exist yet).
3. Decide the data contract: narrow-only filter vs recompute input vs
   cosmetic. State it in the PR/commit so the contract stays explicit.
4. For a new filter-type pill, add: the pill button (TabButtonTone), the
   value widget(s), a value getter that reads `.value`, wiring into the
   dropdown-narrowing logic, and Clear-section / Clear-all handling.
5. Verify off-terminal with the mock-price fallback (see below).

## Verify (off-terminal)

```python
from src.layout import build_app
build_app()   # renders end-to-end on deterministic mock prices
```

Then walk the relevant checks from CLAUDE.md's "Testing notes": pills
swap value lists, ticking a checkbox narrows the dropdown, selected
tickers stay visible, Clear section / Clear all re-widen but keep
selection, panels are equal height, and no filter change triggers a
fetch.

## Out of scope / pitfalls

- Don't fake equal-height panels with fixed pixel heights — use flex.
- Don't let a filter control trigger a recompute or BQL call.
- Don't inline CSS hex/font values — they belong in `src/style.py`.
- Don't drop selected tickers from the dropdown when filtering.
- Chart/trace edits belong in the **plotly** skill, not here.
