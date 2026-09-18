# Testing notes

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

Automated tests live in `tests/` and run with **pytest** (a dev-only dep):

```
pytest -q
```

`tests/test_stats.py` unit-tests the pure `src/stats/` metric functions
against small fixed frames (fixtures in `tests/conftest.py`); `tests/test_smoke.py`
is the regression guard — it builds the whole dashboard on the mock-price
fallback and asserts the top-level widget tree. `ruff` + `black` + `pytest`
also run in CI (`.github/workflows/ci.yml`) on **every** pull request
regardless of its base branch, and on pushes to `main` and to epic integration
branches (`v*`). The `pull_request` trigger is deliberately unfiltered — see
the comment in that file and #202.

## The one test that runs JavaScript (#297)

`tests/test_catalog_grid.py` runs the catalog's numeric-filter grammar —
`_JS_NUMBER_PREDICATE`, the function behind `>1`, `1..3` and a bare number — in
**node**, and skips if node is not on PATH (it is on CI's `ubuntu-latest`
runner). Nothing else in the suite leaves Python.

It earns the exception because the grammar is the substance of that filter and
every alternative is a fiction: asserting substrings of the generated JS proves
the text was written, not that `>1` keeps the right rows. That is exactly the
gap #285 fell into. The parser is a module constant rather than a fragment
inlined into `_js_filter_row` so it can be executed with no DOM and no
DataTables around it — the rest of the row still needs the rendered pass below.

## User-benchmark isolation (#194)

`conftest.py` carries a suite-wide **autouse** fixture redirecting
`src.user_benchmarks.USER_BENCHMARKS_PATH` at a `tmp_path`. Every
`build_app()` reads that path at startup and any test that adds a benchmark
writes it, so without the fixture a test run leaves a real
`data/user_benchmarks.json` in the working tree — leaking state into later
tests *and* into the developer's repo. The module binds the path at import, so
the patch targets the module attribute, not `config`.

## Making the mock reject a ticker (#195)

The mock seeds its generator off a digest of the ticker (v0.9.16 #235), so by
default it resolves **any** string — right for rendering the dashboard without
a terminal, wrong for anything that must cope with a ticker a user typed. Two
seams on `MockPriceSource` (`src/price_source.py`) let a test drive the mock
into the live path's two failure modes, which are different and must stay
distinguishable:

| Seam | Meaning | Result |
| --- | --- | --- |
| `unresolvable: set[str]` | a wrong ticker — nothing comes back, ever | all-NaN column, warned; raises only when *nothing* in the request resolves |
| `first_trade: dict[str, date]` | a real security with no history at the start of the window (launched mid-lookback, or stale) | NaN before that date, real data after; the frame keeps its full index |

These seams exist because the alternative had already failed once: with no
way to make the mock say "no", every validation path was untestable
off-terminal, and the test suite runs nowhere else — so the behaviour was
shipped behind a caveat marked "untestable in CI" and then broke in
production. A caveat is not a test.

They are **constructor arguments**, not module state (v0.9.16 #222, was
`_MOCK_UNRESOLVABLE` / `_MOCK_FIRST_TRADE` in `bql_client`). A test that needs
one builds its own source and either calls `.fetch` on it directly or installs
it as the default:

```python
monkeypatch.setattr(bc, "_DEFAULT_SOURCE", MockPriceSource(unresolvable={bad}))
```

`fetch_prices(..., source=...)` takes one per call for the same purpose. Both
default to empty, so app behaviour is unchanged — and because the seams live on
an instance rather than on the module, a test that sets one **cannot leak into
the next**, which under the old module globals depended on remembering a reset.
`tests/test_mock_resolution.py` covers both and pins them apart: reported as
one generic error, a valid-but-no-data ticker reads to the user as a bug.

Off-terminal, the mock-price fallback is deterministic per ticker **and
stable across processes** (v0.9.16 #235), so two runs render identical
numbers and a rendered-HTML diff is a valid before/after check:

```python
from src.layout import build_app
build_app()
```

renders the full dashboard without a Bloomberg session. Verify by:
- Clicking a filter-type pill (Solution / Category / Family / Asset
  Class / Return Type / Characteristics / Quantitative — the first five
  are derived from `CATALOG_SCHEMA`, so this list follows the schema)
  in the right panel swaps the
  value list shown below; the active pill gets the `.is-active` style
  (accent-bordered raised surface). Ticking a value
  checkbox narrows the ticker dropdown to the intersection.
  Characteristics shows the Launch-date range (two date boxes separated
  by a hyphen) and a **Currency** dropdown; setting either narrows the
  dropdown.
- **The three classification tiers are visible everywhere (v0.9.15).** The
  filter accordion carries a **Solution**, **Category** and **Family** pill in
  that order (both tabs); the all-catalog grid shows Solution / Category /
  Family after Asset Class, and the selected-strategy grid shows them plus
  Return Type and **Launch Date** (relabelled from "Live Date" — the label now
  comes from the schema); the Single Strategy **profile card** lists Asset
  Class · Currency · Return Type · Solution · Category · Family · Launch Date,
  rendering `—` for any the record lacks; the **New Launch** cards' meta line
  reads `asset class · category · currency`. Ticking a value in any of the
  three tier pills narrows the picker.
- The **Quantitative** pill shows a global Period (1Y/3Y/5Y) dropdown and
  one row per metric (Sharpe / Sortino / Calmar / Beta / Treynor /
  Jensen α / VaR % / RSI / Z-Score), each a `[≥/≤ dropdown] [value box]`;
  Beta, Treynor, and Jensen each carry their own benchmark dropdown, and
  Z-Score carries its base-metric selector **plus a 1W/1M/3M/6M window
  dropdown** (v0.8.11). Setting e.g. Sharpe
  `≥ 0.5` (or Sharpe `≤ 0.5`) narrows the dropdown to indices whose metric
  (computed from the already-fetched prices) clears the threshold; a blank
  box is ignored. Changing any operator/period/benchmark/z-metric/z-window
  re-narrows live, no BQL.
- Clicking **Clear section** unticks the active pill's checkboxes (or
  clears the launch-date range + currency on Characteristics, or the
  ratio thresholds on Quantitative); **Clear all** clears every filter
  group, the date range, the currency, the quant thresholds, and the
  search box. Both re-widen the ticker dropdown but keep the user's
  selected tickers. They do not recompute or hit BQL.
- The strategies dropdown (left panel) is the same height as the filter
  box (right panel) — it grows via `flex` while the parent HBox stretches
  both panels to equal height.
- Typing in the strategies search box (left panel, above the dropdown)
  — the dropdown narrows to substring matches on ticker or name;
  already-selected tickers stay visible.
- The **selection cap** (v0.9.13 #181): a `Selected Strategies: n/25` count
  sits above the picker and updates live as boxes are ticked (turning red at
  25/25). Ticking a 26th strategy is **rejected** — the checkbox snaps back,
  the count stays 25/25, and a red auto-fading "Maximum 25 strategies" popup
  appears at the top of the viewport. (The bundled mock catalog has only ~4
  indices, so exercising the cap needs a larger catalog / a live terminal.)
- The **Analysis date range** row (full-width, below the two panels):
  select a basket → Refresh prices → the two hyphen-separated date boxes
  span the overlap window. Editing a box enforces `min ≤ max` but does
  **not** redraw; clicking Refresh prices re-slices the perf grid + all
  pane charts to the chosen window. Refreshing the **same** basket
  preserves a narrowed range; changing the basket resets the boxes to the
  new full overlap. Pairing a recently-launched index with SPTR shrinks the
  bounds to the short overlap. `Clear all` snaps the range to full span. A
  single-ticker or non-overlapping basket renders without a traceback.
- Cold start (no `data/.cache/`) — the loading overlay advances through its
  stages then dismisses; the post-load toast reads `Loaded N indices · M
  trading days · fetched from mock prices in X.Ys`; a `prices_<today>.parquet`
  appears under `data/.cache/`.
- Warm start (within `CACHE_TTL_HOURS`) — the toast reads
  `Loaded N indices · M trading days from cache (HH:MM · MM-DD)`; no
  BQL/mock fetch happens.
- Clicking Refresh prices — the overlay re-shows and runs the staged bar,
  then dismisses; the parquet mtime advances. The overlay must actually
  **become visible** even when the refetch is near-instant (off-terminal mock
  or a warm cache): the refetch runs on a worker thread and the overlay is held
  up for a short beat (`_OVERLAY_PAINT_DELAY_S`) first, so it can't be shown and
  hidden inside one frame (which previously made the dialog never appear). The
  overlay's scrim is a translucent **black** mask (clearly darker than the navy
  chrome) that covers the **viewport** — it stays covering the screen even if the
  page is scrolled when Refresh is clicked (both scrim and card use
  `position: fixed`; an `absolute` scrim sat off-screen once scrolled, leaving a
  bare dialog with no mask). **No** `Loaded …` toast fires on Refresh — that
  toast is reserved for the dashboard's initial load; only a refresh *failure*
  toasts.
- Clicking the top-level **Platform** / **Multi-Strategy** / **Single
  Strategy** pill buttons toggles the active button (`.bbg-pill.is-active`)
  and swaps the content area; commentary stays visible across all three.
- The **Single Strategy** tab (v0.9.0): picking a strategy from the
  single-select dropdown populates the profile card + cumulative chart +
  standard-perf table (Section 1); the 3-pill monthly-return calendar
  (Absolute / Outperformance / Vol-adjusted) tab-switches over one DataGrid
  (Section 2); and the two side-by-side analysis panes each swap analyses on
  their own picker + per-pane benchmark dropdown (Section 3) — all computed
  from the cached prices, no BQL.
- The Single Strategy **"Filters" accordion** (v0.9.12): a two-column panel —
  the strategy picker + benchmark selector + "Show benchmark" toggle on the
  **left**, the filter criteria (the schema-derived pills, then
  Characteristics / Quantitative) on the **right**, stretched to equal height.
  Toggling any criteria box narrows the strategy picker **live** — no
  Refresh-prices button. When the currently-picked strategy is filtered out, the
  first still-matching strategy is auto-selected and the whole tab re-renders;
  when nothing matches, the picker empties and the sections clear without a
  traceback. **Clear all** restores the full catalog.
- Clicking Refresh prices with 2+ tickers — every figure in BOTH
  analysis panes refreshes (the pane's currently mounted view shows
  the new data; the other 8 pre-built views are also populated so
  swapping the picker afterwards is instant — 9 analysis views total).
  The chart **traces stay visible** through the refresh — the charts render on
  a transparent backdrop (the themed card shows through), so a blank / empty
  pane means the plotly CSS is painting an *opaque* fill over the `.main-svg`
  layers (they may only ever be `background: transparent` — see `style.md`).
- Changing a pane's analysis-picker dropdown — only that pane's
  mounted view changes; the other pane is untouched, no recompute. Switching
  **away and back** to a view keeps its transparent backdrop — the whole chart,
  **including its legend and plot area**, still shows the themed card through. A
  dark rectangle (or a dark legend box) on the second view means a plotly
  background rect isn't being forced transparent: the remount `newPlot` redrew
  it from the `plotly_dark` template, so `.main-svg .bg` must cover it.
- The loading overlay's progress card sits **centred in the viewport** (not at
  the middle of the long page) and stays there while scrolling, like the
  post-load toast — both use `position: fixed`.
- Setting both panes' pickers to the same analysis — both render
  independently (separate plotly FigureWidget instances).
- Plotly modebar is visible at the top-right of every chart (zoom,
  pan, autoscale, PNG download). Hovering a line chart with
  `hovermode="x unified"` shows all selected tickers' values at the
  same date in one tooltip.
- Hovering a point on the risk/return scatter shows ticker name,
  annualized vol (%), annualized return (%), and annualized Sharpe (2dp).
- Each pane has its OWN Rolling Correlation / Rolling Beta benchmark
  dropdown — setting the left pane's benchmark to SPTR and the right
  pane's to MXWO, then clicking Refresh prices, produces two
  independently-titled charts.
- On the Correlation Heatmap view, ticking **Benchmark** reveals a
  benchmark dropdown and a nested **Regime** checkbox; ticking **Regime**
  reveals a **`>` / `<`** dropdown and a 0–100% tail dropdown and
  **immediately** recomputes the matrix over the selected benchmark-return
  tail (v0.6.9 live control — no Refresh needed), adding the benchmark as a
  row/column, with the title noting e.g. "SPTR Index worst 20% days".
  Flipping `<`→`>` or changing the % re-renders that one heatmap live; the
  other pane is unaffected. Unticking **Regime** (or **Benchmark**) reverts
  to the full-sample correlation. (Each per-pane benchmark dropdown — Rolling Correlation /
  Rolling Beta / Outperformance — likewise re-titles and re-renders its
  chart live on change, with no BQL fetch.)
- The performance disclaimer below the tab content shows the
  app-load date window (e.g. "2021-05-20 to 2026-05-20"); the bottom
  legal block renders justified.
- The commentary block stays the same across filter changes — it
  describes the whole catalog every time.
- The "Recently launched" indices appear on the QIS Bulletin's **New
  Launches** board, reachable by its chip.
- The **Platform** tab shows every catalog index with metadata plus **one
  stats window** (1Y by default), the classification tiers drawn as nested
  group headers rather than body columns, between a control rail on each side
  (v0.9.21).
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.

### Manual checklist — the commentary block (v0.9.22, epic #303)

The block above the tab bar, on every tab. This is the part no unit test
reaches: the suite can prove `flex` reads `1 1 60%` and that a chip re-ranks,
but not that the two sections *look* like one pair at a terminal's fonts.

**The two sections**

- Two sections side by side, **Leaderboard left at ~60%, QIS Bulletin right at
  ~40%**, each with a title line, a row of chips, and a bordered box beneath.
  The two boxes are the **same height** and their borders line up top and
  bottom.
- Narrow the window. The ratio **holds** — the leaderboard's four columns get
  narrower rather than the Bulletin being pushed off the row, and the page
  never scrolls sideways.
- Each box **scrolls internally** when its content overflows; neither grows the
  block or pushes the tab bar down. `COMMENTARY_BOX_HEIGHT` is the one number
  to tune here, and a terminal is where to judge it.
- Exactly **one border** around each section's content — the boxes are the only
  frames, with no second card nested inside them.

**The Leaderboard**

- The section title reads `Leaderboard (Ranked By Normalized 5Y Z-Score)`, the
  caption muted and smaller so it reads as a qualifier rather than a second
  heading, and on the same baseline as the title rather than wrapping under it
  at a narrow width.
- Four columns — **Return / Sharpe / Calmar / Sortino** — each with a top block
  and a bottom block separated by a divider, and **centred** column titles.
- Every row reads `rank · ticker · score (value)`: the score carries the
  colour (green positive, red negative) and the raw value follows it in
  parentheses, muted. The numbers line up column to column.
- Ranks in the bottom block are the **true catalog positions** (52 / 53 / 54 on
  a 54-index catalog), not 1 / 2 / 3.
- Hovering a row lights **all four cells at once** and shows the strategy name;
  the row reads as one strip, not four buttons. **Watch for the cell under the
  cursor looking brighter than its neighbours** — that is the framework's own
  button `:hover` winning, which the `!important` in `.bbg-lb-row:hover` is
  there to prevent (#306). Keyboard focus is a separate, visible outline on one
  cell, which is correct.
- **Clicking any leaderboard row opens that strategy in the Single Strategy
  tab**, exactly as a catalog-grid row does — including clicking the rank, the
  score or the value, not just the ticker. If the Single Strategy filters had
  excluded it, they clear and the status toast says so.
- Changing the **Window** chips (1W / 1M / 3M / 6M / **1Y**) genuinely
  **reorders** the rows — with no fetch and no visible pause. Returning to a
  window already seen is instant. Nothing on screen still says "Past Week": the
  section title and the lit chip are the only things naming the window.

**The QIS Bulletin**

- The **Commentary** / **New Launches** chips swap the board and move the lit
  chip; Commentary is what is showing on load. Switching issues no fetch.
- Commentary shows **one card per note** from `data/commentary.json`, newest
  first, each with its own title and its own date — no single "as of" header
  over the lot. Blank lines in a note render as paragraph breaks.
- Put a `<b>` or an `&` in a note's `text` and confirm it is **shown as typed**,
  not interpreted.
- Empty `data/commentary.json` (or delete it) → the dashed "No commentary yet"
  box, not a blank pane. Same for New Launches with no recent launches.
- A **Refresh** while the New Launches board is open leaves it open — it must
  not snap back to Commentary.

**The error strip**

- An error in the block renders in the strip **above both sections** and
  survives a window change, a board switch and a Refresh.

## The catalog grid renders — and a unit test cannot tell you (v0.9.18)

A table's *rendering* is not unit-testable, and this is not a theoretical
caveat: spike #255 returned a **go** verdict on `ipydatagrid` merged row
headers while every frame-level assertion passed against a grid that drew its
columns wrong. The verdict was reversed only after a minimal control test.
Three more defects since have had the same shape — invisible to `pytest`, and
two of them invisible to a screenshot as well:

| Defect | What a unit test saw |
|---|---|
| Group-header CSS selected `td`; RowGroup emits `th` | Rules present and correct |
| Heat ramp computed, then overpainted by the chrome's `!important` | Colour present in the inline style |
| `rowGroup` omitted rather than disabled, so the grid grouped by ticker | `"rowGroup" not in options` — true |

So: **assert the behaviour, not the presence of a setting**, and confirm a grid
change by reading *computed* styles and element counts in a browser, not by
looking at a picture. A green panel above a blank space is a fail.

Two controls that help, both used across #263–#273:

- **A density control.** The shipped sample catalog is 18 rows in which nearly
  every ticker is its own family, so one group header per row there is the
  data, not a bug. Render the same catalog cloned x3: if grouping works the
  header counts stay flat while the row count triples.
- **A mutation.** Break the feature and confirm the test fails. Every
  guarantee in `test_catalog_grid.py` was checked this way.

### Manual checklist — the catalog grid

Run alongside the mock-price checklist above:

- Tier columns are **absent from the body**; Solution / Category / Family
  appear as three indented header levels instead.
- Ticking the **Asset Class** chip adds a fourth level *above* Solution — the
  hierarchy order, whatever order the chips were ticked in.
- Unticking every chip leaves a **flat table with no group headers at all** —
  not one header per row.
- The **Window** chips swap all four stat columns; the grouping, the row order
  and any selected row are undisturbed.
- Only windows the price history supports are offered (6M/1Y/3Y/5Y at
  `LOOKBACK_YEARS = 5`); no column of dashes.
- Column headers sit **on** their columns at first paint, with no click needed.
- Scrolling the grid keeps the header row pinned.
- Clicking a row opens that strategy in the **Single Strategy** tab (the same
  route a leaderboard row takes).
- The best index by z-score is still the first row.

### Manual checklist — the Platform rails and table surface (v0.9.21, epic #276)

**Read this section before running it.** Most of it was built in a container
with no display and has never been rendered. The **filter row is the
exception** — and the reason to distrust the rest. Its DOM decisions were
derived by reading the bundled `widget.js`, every Python-side assertion passed,
and the row still rendered blank on a terminal, because itables empties an
untitled `thead th` a tick after the callback creates it (#285, and see
`conventions.md`). It was then driven in a headless Chromium against the real
widget bundle, the real `_dt_args` and the app's own CSS: the row, the two-row
sticky header, per-column filtering, composition with the global search, the
window switch and the click-through were all confirmed there — and again for
the numeric boxes in #297, including the percent scaling, the invalid-input
outline, and the filters surviving a window switch. What that harness
cannot judge is anything about *fit* — real fonts, the rails, the viewport —
so the width items below are still unrendered, and reading the bundle is still
not evidence that something draws.

The control bar and the ranking rail:

- A **bar above the table** carries TABLE VIEW, then Group by and Window laid
  **across**, chips sized to their text. It is one line of chips tall, not a
  rail lying down.
- The **ranking rail** runs down the **left** of the table, stacked, titled
  Z-SCORE RANKING, and its top and bottom line up with the table's — check at a
  short catalog (table shorter than the rail) and a long one (table scrolling),
  since the two are level for different reasons in each case. Both boxes are a
  fixed `CATALOG_TABLE_HEIGHT`, so this should hold at **any** catalog size —
  and the table must not grow past it: the rows scroll inside the box, with the
  search row and the row-count readout still visible above and below them.
- **No chip is squeezed.** Every chip is the same height in the rail as in the
  bar, whatever the rail's content adds up to. A rail too full to fit scrolls;
  it must not compress its chips to make them fit.
- Both containers wear the same surface, border and radius; only the direction
  differs.
- Narrow the window until the bar runs out of room: the chips **wrap** onto a
  second line rather than squeezing or clipping.
- The chips read like the top tab band, not like native checkboxes and radios:
  hover lights them, the selected one carries the accent bar, and keyboard
  focus draws a visible ring.
- The rail holds its 210px width as the window is resized; it must not shrink
  to let the table grow.

The table surface:

- A **filter row sits directly beneath the header labels**, and the labels are
  still there. **Every** visible column has an input (#297); a column hidden by
  the Window chips leaves **no** orphaned input. (Verified in the harness;
  re-check it on the terminal, because this is the item that passed every
  Python assertion while rendering blank.)
- The stat and Z-Score boxes are the **numeric** kind: mono, right-aligned,
  placeholder `>0`, and a tooltip spelling the grammar out. They take `>1`,
  `<=2`, `1..3` or a bare number — and a percent column takes the number **as
  shown**, so `>10` on a Return column means 10%, not the stored 10.0. A
  half-typed `>` outlines the box in red and leaves the rows alone. Verified in
  the harness; what it cannot judge is whether a box that narrow still reads as
  an input at the terminal's fonts.
- The **sticky header pins both rows** as the body scrolls, with the filter row
  sitting clear of the labels rather than over them. The offset is a hard-coded
  `CATALOG_HEADER_ROW_HEIGHT`, so this is where a font or padding change would
  show up first — and the terminal's fonts are not the harness's.
- Type a filter, then **switch the stats window**: the filter text, the
  grouping and the selected row all survive. This is the destroy-and-rebuild
  path — the table is torn down and rebuilt on every options change, and only
  the browser-side store puts the filters back.
- Typing in a column input filters that column alone; the global search still
  filters across all of them; a text box, a numeric box and the global search
  all compose. Clicking into an input does **not** re-sort, and sorting still
  works from the label row.
- A numeric filter **drops the dash rows**: a blank cell is not a number and
  matches no comparison.
- Clicking a **filtered** row still opens the right strategy in Single
  Strategy — the row indices are data indices, not display positions.
- The search box renders **top-left**, in the dark chrome, with its placeholder
  visible and no "Search:" label.
- Each nesting level is a distinct cyan band, legible at every level; a fourth
  level (tick all four Group by chips) is styled rather than falling through to
  the body colour.
- No Return Type column. Launch Date is still there; Return Type is still on
  the Single Strategy profile card and still a filter pill.
- **No page-level horizontal scrollbar** at the default single-window column
  set on a standard BQuant viewport, and the table fills the space the ranking
  rail leaves rather than leaving dead space to its right.
- Widen the column set until it cannot fit: it scrolls **inside** the table,
  with both rails still in place and fully visible.
- Resize the viewport: the header stays on its columns. This is the event class
  that exposed the `scrollY` drift recorded in `grids.py` — header and body are
  one table here so there is nothing to drift by construction, which is the
  claim being checked.

## Terminal verification (v0.9.16)

The whole app has been **loaded and driven on a real BQuant terminal** — the
v0.9.16 object rework landed there successfully, retiring the standing "never
run against live BQL" caveat that every prior version carried. Treat the
terminal as reachable, not hypothetical: when a change touches the live path,
it can be confirmed rather than reasoned about.

That matters because the suite runs **only** off-terminal, and two classes of
behaviour are invisible there:

- **The stale-index prune is a no-op on mock prices.** Every mock ticker moves
  over the trailing window, so `active_columns` drops nothing and the pruned
  and unpruned catalogs are identical frames. #242 — Platform-analytics
  observers redrawing from the *pre-prune* catalog — survived precisely because
  of this, and its regression test has to build the divergence by hand. **On a
  terminal the check is real:** load the app, change the **Z-Score Metric**
  dropdown, and the all-catalog grid's row count must not jump.
- **BQL's own contract** — batching behaviour, which tickers resolve, what a
  delisted security returns. `MockPriceSource` encodes our *belief* about it;
  only a terminal tests the belief.

When a fix is only observable on a terminal, say so in the PR and name the
click-path that confirms it, the way #242 did.
