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
- **There is no filter accordion left in the app** (#345, #365). Both picking
  tabs filter from a *Filter* bar — a **Dimension** chip row beside that
  dimension's **Values** — and every number that used to be a `≥ / ≤`
  threshold is a **column** of the table with a comparison filter under its
  header. Nothing on any tab should show a pill-tab bar, a 240px checkbox
  list, an operator dropdown or a "Clear section" button.
- Picking a Dimension chip swaps which values are shown; ticking values
  narrows the table live, with no BQL. **Switching dimensions keeps every
  dimension's ticks**, and a dimension with active values carries a count
  badge (*Family · 2*) — which is the only place an off-screen filter is
  visible from.
- **The three classification tiers are visible everywhere (v0.9.15).** The
  Filter bar's dimension chips carry **Solution**, **Category** and **Family**
  in that order (both tabs); the catalog table draws them as nested group
  headers; the Single Strategy **profile card** lists Asset Class · Currency ·
  Return Type · Solution · Category · Family · Launch Date, rendering `—` for
  any the record lacks; the **New Launch** cards' meta line reads
  `asset class · category · currency`.
- The **selection cap** (v0.9.13 #181): the Multi tab's `n / 25 selected`
  count updates live as rows are ticked. Ticking past the cap is **rejected
  whole** — the ticks snap back to what the basket holds and a red auto-fading
  "Maximum 25 strategies" popup appears. (The bundled mock catalog is 18 rows,
  so exercising the cap needs a larger catalog / a live terminal.)
- **No analysis date range and no Refresh prices.** The window is the
  selection's overlap (v0.9.29) and nothing refetches (v0.9.30); the Selected
  Strategies strip's readout says the window and names the member that binds
  its start. Pairing a recently-launched index with a long-history one shortens
  it; removing that member lengthens it again, live.
- Cold start (no cache under `<tmp>/bbg_quant_dashboard/prices/`) — the
  loading overlay advances through its stages then dismisses; the post-load
  toast reads `Loaded N indices · M trading days · fetched from mock prices in
  X.Ys`; a `prices_<today>.parquet` appears **in that temp folder, not in the
  project** (v0.9.41).
- **Nothing regenerable is left in the project folder** after a launch from
  the notebook: no `data/.cache/`, and no `__pycache__` under `src/`. A
  project upgraded from v0.9.40 or earlier loses both on its first launch —
  that is `housekeeping.clear_legacy_artifacts`, and it is what took the
  project back under its size limit.
- Warm start (within `CACHE_TTL_HOURS`) — the toast reads
  `Loaded N indices · M trading days from cache (HH:MM · MM-DD)`; no
  BQL/mock fetch happens.
- **Nothing re-shows the overlay.** It runs once, on the initial load, and
  dismisses. If it appears again during a session, something still fetches —
  which nothing should since v0.9.30.
- Clicking the top-level **Platform** / **Multi-Strategy** / **Single
  Strategy** pill buttons toggles the active button (`.bbg-pill.is-active`)
  and swaps the content area; commentary stays visible across all three.
- The **Single Strategy** tab (v0.9.36, epic #363) — the picker is the
  catalog table again, in single-select, under a *Table view* bar
  (**Group by · Window · Benchmark**) and a *Filter* bar (**Dimension ·
  Values**), at the same height as the other two tabs' tables. There is **no
  accordion, no pill-tabs, no threshold rows and no strategy dropdown**
  anywhere on the tab.
- **Clicking a row** picks that strategy: the profile card, the cumulative
  chart, the metrics table, the calendar and both panes all redraw, live, off
  the cache. Changing Group by, Window, a Dimension chip or a value chip
  rebuilds the table and **the picked row stays lit** if it is still shown.
- **A pick the filters hide stays picked.** Narrow the filters until the
  picked strategy has no row: nothing clears, every section keeps drawing it,
  no row is lit, and the profile card reads `… · not shown by the current
  filters` beside the ticker. This is the behaviour that replaced clearing the
  user's filters, so also check the other direction — clicking a **catalog**
  row on the Platform tab, a **Leaderboard** row, a **points-table** row or a
  **basket card** opens this tab on that strategy and **leaves the filters
  alone**, with no status message about clearing anything.
- **The metrics table** is HTML in the app's type: eight rows (Return · Vol ·
  Sharpe · Sortino · Calmar · Max DD · Beta · Correlation) across every window
  the fetch serves plus **SI**, which is set off by a left rule. Every number
  is at **two decimals**; an unserved window is an em dash, not a blank and not
  `NaN`. Negatives are red and **nothing is green**. Changing the bar's
  Benchmark moves the Beta and Correlation rows and nothing else.
- **The calendar** is HTML too, and still a heatmap: years down, Jan…Dec
  across, the annual summary set off at the right, cells shaded red→green on
  the same bands the Platform grid uses. Its five modes are **chips**
  (Absolute / Outperformance / Vol-adjusted / Beta / Correlation), not pills;
  switching one repaints the cells and the summary columns change with the
  mode. Vol, where it appears, carries **no shading**.
- **Every analysis option draws.** Step the pane picker through all eight —
  Weekly Scatter · Return Distribution · Factor Scatter · Drawdown · Rolling ·
  Decile · Regime Profile · Risk Profile — and none of them shows a *coming
  soon* placeholder.
- **Weekly Scatter** opens unconditioned and looks exactly as it did: one
  cloud in colour, one dashed quadratic, a one-line β / convexity / R² panel.
  Tick *Condition on regime* and a **second** cloud draws over it in colour
  with its own solid fit while the full window steps back to grey; the panel
  grows to two lines, `all:` over the bucket's own, and the two β figures
  should differ. Untick it and the chart returns to exactly its opening state.
  Pick a bucket almost nothing falls in: the few points still draw and the
  panel says *too few to fit* rather than going blank.
- **The cumulative chart's zoom readout** (#380). On load, a semi-transparent
  panel sits at the chart's top-left naming the window, its length in days,
  *annualized*, and eight metrics. Drag a zoom over **more** than a year: the
  dates and every number change, and it still says *annualized*. Zoom to
  **less** than a year: Vol, Sharpe, Sortino and Calmar **disappear**, Return
  becomes *Return (cumulative)*, and the header says *cumulative, < 1Y*. Max
  DD, Beta and Correlation survive both. Pan, and it follows. Double-click to
  reset, and it reports the whole window again — it is never blank while a
  line is drawn. Toggling the benchmark adds or drops the Beta and Correlation
  rows. None of this shows the loading overlay: no zoom fetches. **Read the
  header text**: the separators must be middle dots, not the literal
  `&middot;` — a Plotly annotation renders only four named HTML entities
  (#386).
- **Return Distribution** draws **one line per series and no filled bars** —
  count the lines against the legend, and on Single Strategy with a benchmark
  on there should be exactly **two**. (Filled overlays used to blend into a
  third band through the middle, which read as a series the legend never
  named, #386.) Beneath it the per-ticker stats are an **HTML table**, tickers
  down and Mean · Std · Min · Max · Skew · Kurtosis across, every number at
  two decimals with negatives red and nothing green. **Mean is headed
  `Mean (bp)`** and reads in basis points (#388) — a daily mean is three
  orders below the other percentages, and at `0.06%` two strategies a fifth
  apart printed the same number. Check two rows actually differ. On Multi-Strategy the
  table has one row per basket member.
- **Rolling** is one figure with a Correlation · Sharpe · Calmar · Beta chip.
  Stepping the chip moves the **title, the y-axis label and the reference
  line** together (0, 0, 0, then **1** for Beta), and the benchmark dropdown
  **disappears** for Sharpe and Calmar and comes back with the same benchmark
  still selected. The Multi-Strategy tab now has **one** *Rolling* entry where
  it had two.
- **Decile** draws ten column pairs, strategy beside benchmark, rising left to
  right on the benchmark's own bars. Tick *Condition on regime*: the bucket
  chips appear, the columns **change** (they are re-cut inside the bucket, not
  re-sliced), and the regime and bucket are named **in the title**. Untick it
  and the title loses the suffix. Switching the regime **type** repopulates
  the buckets before the redraw, so the title never names a bucket from the
  regime you just left.
- **Regime Profile** draws, per series, an open-diamond anchor labelled *Full
  period* plus one labelled marker per bucket — three for Volatility and
  Rate-level. With a benchmark on there are two anchors and two sets of three,
  and **each anchor is the colour of its own cloud** (#381), so the pairing
  reads without consulting the legend — two colours on screen, not three or
  four. There is **no bucket control** on this view. Unticking *Condition on
  regime* leaves only the anchors.
- **Risk Profile** is a five-spoke polygon — ERP · Term · Volatility · Trend ·
  Carry — on a radial axis in **percent**, and every hover reads
  `<factor> · N% of the catalog · β = x.xx`. On the mock cache Volatility
  resolves (VIX and MOVE are both fetched); drop `MOVE Index` from the request
  and it should still draw with the VIX leg alone rather than vanishing.
- The two panes are independent: set them to different analyses, or to the
  same analysis with different benchmarks or different regime buckets, and
  neither disturbs the other.
- Selecting 2+ strategies — every figure in BOTH
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
- Each pane has its OWN Rolling benchmark dropdown — setting the left pane's
  to SPTR and the right pane's to MXWO produces two independently-titled
  charts.
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
  group headers rather than body columns, under one control bar (v0.9.23).
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.

### Manual checklist — the Platform analytics card (v0.9.28, epic #331)

The card below the catalog table. Three charts, a drill and a points table —
and almost none of it is something a widget-tree assertion can see, which is
the #255 lesson. **Read the mock catalog as shapes, not as findings:** 18
indices, and 14 of its 16 categories and families are singletons, so a drill
often narrows to one point. That is the data, not the feature; the terminal
catalog is the real test of how the charts read.

**The bar and the drill strip**

- One `control_bar` titled *Chart view*, in the same chrome as the table's bar
  above it, reading **Chart · Metric · Window · Regime · Solution** — settings
  only. No native toggle buttons anywhere on the card.
- **Solution** offers only the solutions the drawn universe holds — on the
  terminal catalog *ARP*, *Alternative Risk Premia* and *Smart Beta*, and
  **no `Beta` chip** (that solution is filtered out of the analytics universe,
  and a chip for it would draw an empty chart). One is selected on load.
- Pick another Solution: all three charts redraw inside it, the breadcrumb's
  root **renames to that solution**, and the Level chips reset to *Asset
  Class*. No fetch, no overlay.
- Beneath it, a **subordinate strip** carrying **Scope** (the breadcrumb) then
  **Level**. Level offers **Asset Class · Category · Family · Strategy** —
  *Solution* is not among them: it is the base the Solution chips pin, not a
  stop to drill to. It should read as a different kind of thing from the bar above:
  no box of its own, lighter, tighter. At a narrow terminal width it **wraps**
  rather than scrolling sideways.
- Select **Icicle**: Level disappears, **Scope stays** (its zoom is the drill). Select **Strip**: Metric and
  Window disappear. Select **Scatter**: Regime appears. Change Metric on the
  Scatter, switch to the Strip and back — **the metric is still selected**.
  (Hidden, not rebuilt: a rebuilt bar resets every chip.)
- Changing any chip re-renders **only the visible chart**, with no fetch and
  no overlay. Nothing on the page reloads prices (v0.9.30) — a reload of the
  app is the only way to fetch again.

**The Icicle**

- The chart fills a box **taller than the catalog table above it**
  (`ANALYTICS_HEIGHT` 720px), and the figure is **the same height as its box**
  — no clipped bottom row, no inner scrollbar. Check the Scatter and the Strip
  too; all three are built at the token, and the points table beside them takes
  it as well.
- The cells in the **last column are tall enough to carry their labels**. That
  column holds one cell per sibling, so it is what the height buys — if the
  labels are still clipped or rotated, this token is the lever, not the width.
- **No grey ancestor bar** above the cells. Plotly's `pathbar` is off — the
  Scope breadcrumb is the only thing saying where you are.
- The **top row is the pinned Solution alone**, not one cell per solution, and
  the row below it is that solution's **asset classes**.
- Cells span the width in proportion to **how many strategies** they hold, not
  to any metric — a category with four indices is twice the width of one with
  two, at every level.
- Colour is the mean metric, red through neutral to green, and the colorbar is
  titled for the Metric and Window chips (e.g. `1Y Sharpe`). Hover shows the
  label and the value, then *(Average over N Strategies)* **only on a group**
  (#388) — a leaf says nothing, where it used to read "1 strategies". On this
  catalog most root cells are one-member, so that is the case to look at.
- Set Metric to **Return**: the numbers read as percentages, not 2dp ratios.
- **Click a cell and it stays zoomed.** The chart, the breadcrumb and the
  points table all move together. If the chart snaps back to the whole catalog
  while the table and breadcrumb show the narrowed view, the trace is being
  rebuilt without its `level` — that was the v0.9.24 bug (fixed in v0.9.25),
  and it is the first thing to check if it ever returns.
- **Click the cell you are already inside**: it zooms out one level, as
  Plotly's own icicle does, and the breadcrumb loses a segment. From the
  Solution row it **stays put** — the base is as far out as the filter goes.

**The Scatter**

- **Every point is coloured, and the colours differ** — no all-grey cloud, and
  no single legend entry. Drill a level and check again: colour keys to the
  points' own level at every depth. At the asset-class level the hues are the
  curated identity ones (Equity's blue, and so on), not palette order.
- **Hover reads left-aligned and is not truncated**, on this and on every
  other chart in the app including the Multi-Strategy panes — one treatment,
  in the theme.
- One marker per **asset class** of the pinned solution at the root, coloured
  by asset class with a legend (v0.9.27 — the drill is based at the Solution
  chips' choice). Y is the metric, X the term-premium β, Z the
  equity-risk-premium β, and the axis titles say so.
- Hover is **three lines** and small enough to see the cloud past it; a group
  says *(Average over N Strategies)* and a strategy says nothing (#388). There
  is no way to anchor it beside the marker in a 3D scene, so if it still hides
  too much the fix is fewer characters.
- **No translucent planes.** Each axis's zero line and wall edge are visible
  at the default camera, and the box is a cube so a β of 0.2 is the same
  length on all three axes. Orbit the camera and check the zero lines still
  read — this is what the planes were there for.
- Walk the whole path: an asset-class marker narrows to its **categories**,
  then **families**, then **strategies**, each level in its own colours and
  the breadcrumb growing a segment each time. Click a
  strategy: nothing happens (the table row is the way into Single Strategy).
- Change the Regime bucket: the markers move, with no fetch. A regime whose
  indicator is missing from the cache draws the unconditioned all-days view
  rather than an empty chart.

**The Strip**

- **Six** date columns, oldest left, labelled `DD Mon`, with a dashed zero
  line. Markers are **spread within** each column rather than stacked on one
  line.
- The newest column is **T-1**, not today, and there are **no weekend
  columns** — check this on a Monday, when T-1 is the previous Friday.
- Switch away and back: the cloud is in the **same arrangement**. A reshuffle
  would read as movement in the data.
- Hover reads name, date and return, and says *(Average over N Strategies)* on
  a group — never a bare number after the value, and nothing at all on a
  strategy (#388).

**The drill and the points table**

- The table sits to the right of every chart at roughly **60:40**, both boxes
  the **same height**, borders lining up top and bottom, and the table's rows
  scrolling inside it. Widen the window: the split **holds** — the table must
  not shrink to a strip.
- Its first column is headed for the current **Level** (*Asset Class* /
  *Category* / *Family* / *Strategy*) and its last for the chart's own value (`1Y Sharpe`, or
  `5D Return` on the Strip). A **Count** column appears above the strategy
  level and not at it.
- Sorted by value **descending**, blanks last.
- Click a **group** row → the drill narrows, exactly as clicking its marker
  does. Click a **strategy** row → Single Strategy opens on it, with the
  filters cleared, the same as clicking a catalog row.
- Walk all the way down and back: marker → Level chip → breadcrumb segment →
  the root, which is **named for the pinned Solution**. The chart, the
  breadcrumb, the Level chips and the table agree at every step, and clicking
  the root never escapes the Solution filter.
- At the default BQuant viewport there is **no page-level horizontal
  scrollbar** with the Scatter active — it has the widest legend.

### Manual checklist — the Multi-Strategy selection tab (v0.9.30, epic #341)

The tab is the catalog table with ticks. Almost none of this is something a
widget-tree assertion can see — the group-header click, *Select all shown* and
the tick column all live in the browser — which is why they are here.

**Read the mock catalog as shapes, not as findings:** the pruned mock leaves
~7 rows, so *Select all shown* is comfortably under the cap of 25 and the
rejection path cannot be reached from the UI here. The terminal catalog is the
real test of it.

**The shell**

- Top to bottom: *Strategy selection*; a *Table view* bar reading **Group by ·
  Window · Benchmark**; the **filter row** (dimension chips left, that
  dimension's values scrolling right, on ONE line); the table; the **Selected
  Strategies** strip; the two panes.
- **No Refresh prices button and no second grid** (v0.9.30). Nothing on this
  tab shows a loading overlay — if one appears, something still fetches.
- **No accordion, no pill-tab bar, no 240px checkbox list, no analysis date
  pickers.** The only date pickers on the tab are the strip's *Launch date* —
  a characteristic of a strategy, not the analysis range.
- The bar and the table read as the Platform tab's: same chrome, same chips,
  same search box top-left, same per-column filter row.

**The table**

- The tick column draws, and clicking **anywhere on a row** toggles it — the
  tick is the affordance, not the only hit area.
- Group headers show a **pointer and an accent hover**. Clicking a category
  header ticks every row under it; clicking it again unticks them. A family
  header inside it takes only that family. A **Solution** header takes
  everything nested under it, at every depth.
- Type in the search box, then click a group header: it takes **only the rows
  still shown**, not the ones the search removed.
- ***Select all shown*** selects every row the search and the filter row leave.
  ***Select none*** empties the visible members only — a basket member the
  filters are hiding keeps its card.
- Over the cap — from a row, a header or Select all — **nothing changes**, the
  ticks snap back to what the basket holds, and the popup names the count
  (*32 selected — the cap is 25*).
- Change Group by, Window, Benchmark or a filter value: the table rebuilds and
  **the ticked rows that survive are still ticked**. This is the one to watch —
  it is re-derived from tickers, so a rebuild that loses ticks means the push
  is racing the widget's own re-send.
- The **filter row is one line at 20:80** — dimension chips left, that
  dimension's values right, the values scrolling when there are many. Narrow
  the window: the split holds and neither side pushes the other off.
- **Four** quant columns for the visible window — Sortino · Calmar · Beta ·
  Treynor — each with a comparison box in the filter row. Type `>1` under
  **1Y Sortino**: it filters in the units shown.
- **Every one of them carries a number, not N/A**, at every window. Two bugs
  made them wrong before v0.9.30 and both were silent: the window loop treated
  `stat_windows()`' years as days (so 1Y measured one day), and `ann_beta` was
  handed benchmark *prices* where it covaries against returns (so every Beta
  sat near zero and Treynor exploded). Sanity-check a Beta against a benchmark
  you know — a broad equity index should not read 0.00 for everything.
- The **tick is its own column**, narrow, at the left edge, and **never
  overlaps the ticker text at any window width**. Resize the browser and check
  again — sharing a cell is exactly what broke before.
- Change **Benchmark**: Beta and Treynor move; nothing else does. (Jensen α
  is still computed but is not a column — v0.9.30 dropped it with VaR and RSI.)

**The filters**

- The bar's *Filter* chip picks a dimension and the strip below shows its
  values. Tick two Family values, switch to Asset Class, switch back —
  **the two are still ticked**.
- A dimension with active values carries a count badge (*Family · 2*), which
  is the only evidence of a filter whose chips are off screen.

**The basket**

- One card per member, in the order they were added: **`[TICKER] ×`** and
  nothing else. The asset-class colour is the card's left border and the
  binding member's is the accent on the other three sides; the strategy's name
  is the ticker's tooltip. **The colour block should be obvious at a glance
  across the strip** — if it reads as trim, `BASKET_TAG_WIDTH` is the lever.
  **The × renders on every card** — it was the name spilling that pushed it off
  the end before v0.9.30.
- **×** removes the card and unticks the row if it is shown. Clicking the
  **ticker** opens that strategy in Single Strategy — the filters are left
  alone since #363, a hidden pick simply staying picked —
  the same as clicking a catalog row.
- *Clear all* empties it; the note reads `n / 25 selected` and tracks every
  change. An empty basket shows a placeholder line and the strip **does not
  collapse**.
- The **Analysis window** readout reads `start → end · N.NY · start set by
  XYZ`, and that member's card carries a small marker. Remove it: the start
  moves **earlier** and the readout follows. A basket whose members share no
  dates reads *No overlapping history*.

**Live analytics**

- Tick a row: the perf grid and both panes re-render within a moment, **with
  no overlay and no fetch**. This is the headline change — it used to need
  Refresh.
- *Select all shown* is **one** recompute, not one per row.
- There is **nothing to press**. Prices are the startup fetch's for the life of
  the session (v0.9.30) — to get fresh ones, reload the app.
- Single Strategy has its own table, bars and filters (#363) — narrowing one
  tab's filters must not move the other's.

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
- The board **opens on `1W`** (#384), with that chip lit — not `1M`. Clicking
  any other Window chip re-ranks it from the cache with no loading overlay.
- **`1D` is the first chip**, and selecting it collapses the board to **one
  column, Return** (v0.9.40): Sharpe, Calmar and Sortino disappear rather than
  standing empty under their titles. The rows are yesterday's return, ranked by
  its z-score against five years of daily returns. Pick `1W` again and all four
  columns come back with the week's rows.
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
  score or the value, not just the ticker. A strategy the Single Strategy
  filters exclude opens all the same — since #363 the pick does not depend on
  a row being shown, so nothing clears and there is no status toast.
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
- The **Window** chips swap the window's stat columns; the grouping, the row order
  and any selected row are undisturbed.
- Only windows the price history supports are offered (6M/1Y/3Y/5Y/10Y at
  `LOOKBACK_YEARS = 10`, v0.9.34); no column of dashes. At **10Y** the three
  BSLX strategies (launched 2016-06-30) carry values and BCLEAN / BAITHM show
  the dash; the ranking column still reads `(5Y Z-Score)`, not `10Y`.
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

The control bar (v0.9.23: there is no longer a rail beside the table):

- A **bar above the table** carries TABLE VIEW, then **Group by · Metric ·
  Window** laid **across**, chips sized to their text. It is one line of chips
  tall per section, not a rail lying down.
- **Nothing stands beside the table.** It runs the full width of the panel, and
  must not grow past `CATALOG_TABLE_HEIGHT`: the rows scroll inside the box,
  with the search row and the row-count readout still visible above and below
  them. Check at a short catalog and a long one.
- **No chip is squeezed.** Every chip is the same height whatever the bar's
  content adds up to.
- Narrow the window until the bar runs out of room: the chips **wrap** onto a
  second line rather than squeezing or clipping.
- The chips read like the top tab band, not like native checkboxes and radios:
  hover lights them, the selected one carries the accent bar, and keyboard
  focus draws a visible ring.
- With 210px more width than before, look at the **column widths**: the
  content-fit descriptive columns and the per-column filter row have more room,
  and `CATALOG_TABLE_HEIGHT` is worth re-reading at a terminal's fonts now that
  the table is wider.

The ranking column (epic #321):

- The header reads **`Normalized <window> <metric> (5Y Z-Score)`** — e.g.
  `Normalized 1Y Sharpe (5Y Z-Score)` — and follows **both** chips.
- Click each **Metric**: Return / Sharpe / Calmar / Sortino, and no Vol. The
  column re-scores, re-sorts and renames with no visible reload and **no BQL**
  (the toast does not reappear).
- Click each **Window**: the performance columns swap to that window **and**
  the ranking re-scores over it. The grouping stays intact — every tier is one
  contiguous run, not repeated headers — and the table re-sorts.
- At the **5Y** window, young indices legitimately show a **dash** rather than
  a score and sink to the bottom. Expected (`CATALOG_SCORE_MIN_SAMPLE_DAYS`),
  not a bug — but count them: if nearly the whole catalog blanks, the floor is
  set wrong for this data.
- The column keeps its red→green ramp, its two-decimal numbers, and a filter
  box that takes a **comparison** (`>1`, `1..3`) rather than a substring.

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
