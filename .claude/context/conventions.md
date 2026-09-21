# Conventions, branching & workflow

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

## Branching

- **Current version**: `v0.9.25`.
- **`main` is the trunk.** Work branches off `main` and lands back in `main`
  by PR. There is no standing integration branch.
- **Branch naming**: `{MAJOR.MINOR.PATCH}-{short-description}`, prefixed with
  the version the work is going into — e.g. `0.9.14-benchmark-registry`,
  `0.9.15-fix-overlay-flash`. Flat (hyphens, not slashes): git cannot host a
  nested `vX.Y.Z/<desc>` ref while a branch named exactly `vX.Y.Z` exists, and
  the epic branches below are named exactly that.
- **Integration branches are the exception, not the rule.** Cut one — named
  exactly `vX.Y.Z` — only for a **multi-PR epic** whose parts are not
  individually shippable. Sub-branches hang off it, it merges into `main` when
  the epic completes, and it is then deleted. A single-PR change never needs
  one.

> **Why this changed (v0.9.14).** The old model cut one long-lived integration
> branch per version, off `main`. In practice `v0.9.0` absorbed the v0.9.11,
> v0.9.12, v0.9.13 *and* v0.9.14 cycles — a branch named `v0.9.0` carrying
> version `0.9.14` — while `main` sat untouched for three months. Two concrete
> costs: the "staging buffer before `main`" was never once flushed, so it
> bought nothing; and GitHub only fires `Closes #N` when a PR merges into the
> **default** branch, so every closing keyword written against the integration
> branch was silently inert and its issues stayed open after shipping.

## Development workflow

Every roadmap item ships through the same loop. The `/workstream` skill
(`.claude/skills/workstream/SKILL.md`) is the step-by-step playbook; the
`.claude/settings.json` PreToolUse hooks **enforce** the gates below.

1. **Plan first.** Enter plan mode (`Shift+Tab` ×2; there is no auto-default
   plan-mode setting), read the target GitHub issue, explore, design, and get
   the plan approved before editing.
2. **Branch** off `main`, flat-named `X.Y.Z-<desc>` (see "Branching" above).
   One workstream per branch, one issue per branch. Only a multi-PR epic gets
   an integration branch to stack on.
3. **Implement** only that workstream; respect the issue's non-goals; add/adjust
   `tests/`.
4. **Quality gates** — `ruff check src tests`, `black --check src tests`,
   `python -m pytest -q` must all be green. `.claude/hooks/quality-gates.sh`
   re-runs these on every `git commit` and **blocks** the commit on failure.
5. **Commit & push** `-u origin <branch>`. Never push to `main`/`master` —
   `.claude/hooks/block-main-push.sh` blocks it; land changes via PR.
6. **PR into `main`** (or into the epic's integration branch, which itself
   PRs into `main`); close the issue with a `Closes #N` keyword — which only
   actually fires on the merge into `main`. Defer `.meta/VERSION` +
   release-note edits to end-of-cycle.

## Conventions

(Visual/styling conventions — color identity, dark chart theme, dark chrome
CSS, style tokens — live in `style.md`.)

- **BQL fetch contract + recommended patterns** — the
  `.claude/skills/bquant-dashboard-spec/SKILL.md` skill is the platform
  reference for the BQL request shape, single-call-per-session, the two-tier
  price cache, the off-terminal mock fallback, the benchmarks/factors
  ride-along, the Refresh-prices control, and live controls slicing rather
  than fetching. Read it first; the bullets below are *project-specific
  hooks* into the actual code.
- **One BQL call per session**. `build_app` issues a single
  `fetch_prices(arp_tickers + BENCHMARK_TICKERS + FACTOR_TICKERS + REGIME_TICKERS, ...)`
  request at load time (deduped, order-preserving) and caches the result on
  `DashboardState.universe_prices`. Every visualization — including the
  all-catalog grid, the commentary, the Rolling Correlation / Rolling Beta
  tabs, the v0.9.24 Platform charts, and the v0.8.5
  Regime Analysis charts — slices from that cache. The `FACTOR_TICKERS` (v0.7.0: a
  long-Treasury + short-rate TR proxy, the equity leg reuses `SPXFP Index`
  (`EQUITY_FACTOR_TICKER`, also a benchmark); v0.7.1 adds
  the `TREND_TICKER` = `BSLXAT Index` cross-asset trend factor for the scatter's
  z-axis) and the `REGIME_TICKERS` (the Regime Analysis indicators: `VIX Index`
  and the regional rates `FEDL01` / `EONIA` / `MUTKCALM`; v0.8.9 dropped
  `NFCIRISK` with the Risk regime) ride this same fetch — *no second BQL call* — and, like the
  benchmarks, are excluded from the ARP-universe views via
  `reindex(columns=meta["ticker"])`.
- **Two-tier price cache (v0.6.9; incremental in v0.9.13 #165; a `PriceCache`
  object since v0.9.16 #221)**. `fetch_prices` is fronted by a `PriceCache`
  (`src/price_cache.py`) holding an **in-memory session superset** — one
  growing frame plus the date interval it covers — checked **before** the
  **on-disk trading-day** parquet
  `data/.cache/prices_{YYYY-MM-DD}.parquet`. Any request whose tickers ⊆ the
  superset's columns **and** whose `[start, end]` ⊆ the covered interval is
  served by *slicing* (`covers` → `serve`), no BQL. On a **miss**, only the
  missing rectangle is fetched — new tickers over the needed span, and/or the
  existing columns over the uncovered date extension (`delta_specs`, non-
  overlapping so cached values are never disturbed) — then merged in
  (`merge`, fresh wins). So **extending the lookback or adding an
  index costs a delta, not a whole-universe refetch** — the key v0.9.13
  scalability fix. The cover is tracked separately from the data index, so a
  weekend/holiday `end` (no trading row) still counts as covered.
  `use_cache=False` (Refresh) refetches the full request and overwrites the
  overlap. The disk write is **best-effort**: on a read-only filesystem (or any
  write failure) `write_disk` warns once, sets `disk_writable = False`,
  and the in-memory superset carries the session — the app never crashes on a
  read-only FS. `read_disk` is containment-aware (column-pushdown
  `read_parquet(columns=…)`, left-date coverage) and swallows read errors as a
  clean miss; `write_disk` writes the superset and prunes past-TTL files
  (`prune`). `clear()` resets both tiers for tests. `bql_client` holds one
  `_DEFAULT_CACHE` instance and `fetch_prices(..., cache=...)` takes another,
  so a test gets a hermetic cache by constructing one rather than by resetting
  module globals. The
  directory is gitignored. *(Not yet done: a pyarrow dataset partitioned by
  ticker for per-ticker on-disk append — the disk tier still writes one whole-
  superset parquet per `end` day.)*
- **Refresh prices button** (formerly Apply): re-fetches from BQL with
  `use_cache=False`, overwrites the parquet, then recomputes everything.
  Filter-only re-slicing (today the button always refetches) will be
  split back into a separate Apply control in a later PR.
- **Loading overlay + toast** report load progress (v0.6.5, replacing the
  old permanent status banner). A full-screen dimmed `.bbg-overlay` with a
  staged progress bar advances through the load (`_set_progress`: 0
  Initializing → 25 metadata → 60 fetching → 85 building catalog → 100
  Ready) then dismisses; **Refresh prices** re-shows it. On a fatal fetch
  error the overlay stays visible in a red `is-error` state and the full
  traceback also renders in the commentary block. The post-load summary
  (`Loaded N indices · M trading days · fetched from BQL in X.Ys` /
  `… from cache (HH:MM · MM-DD)`) folds into a slim auto-fading
  `.bbg-toast` (`status_w`). `build_app` is synchronous, so it `display()`s
  the overlay first (guarded on `get_ipython()`) and pushes stage updates as
  each step completes — best-effort in Voila (intermediate frames may
  collapse); the overlay always appears and dismisses.
- **Benchmarks ride along the single BQL fetch** but are explicitly
  scoped to the Rolling Correlation / Rolling Beta tabs. The
  all-catalog grid and the whole-catalog highlights consume
  `arp_universe_prices = universe_prices.reindex(columns=meta["ticker"])`
  so benchmark columns never leak into ARP-universe views.
  `BENCHMARK_TICKERS` / `DEFAULT_BENCHMARK` live in `src/config.py`.
- **Checkbox filter groups, search box, date pickers, the currency
  dropdown, and the Quantitative ratio thresholds narrow the ticker
  dropdown only**. They do not trigger any recompute or BQL call. Their
  value getters read each widget's `.value` regardless of which
  filter-type pill is currently visible, so switching pills is purely
  cosmetic. The Quantitative filter slices the already-fetched
  `arp_universe_prices` (benchmark prices from `universe_prices`) to
  compute its per-ticker ratios live, still without a BQL call.
- **All compute lives in `src/`**; the notebook stays a one-liner.
- **Commentary is always whole-catalog**, never the selected subset, so
  the user sees market-wide context regardless of what they're inspecting.
- **Selected-set analyses** (the 9 analysis options available in each
  Selected-Strategies pane) are over the currently selected tickers
  only — that's the user's focus area. The commentary block's builders
  (`build_leaderboard` / `build_launch_cards`) compute over the
  whole catalog (`arp_universe_prices`), never the selection.
- **Refresh invalidates; a chip re-slices (v0.9.20 #290).** The commentary
  block's `highlights_cache` on `DashboardApp` is keyed by window, with one
  extra `"launches"` entry. `_recompute` clears it — a fresh fetch makes every
  ranking stale — while the Leaderboard's Window chips and the Bulletin's
  Commentary / New Launches chips only *read* it, so neither issues a BQL call.
  A window already computed is returned by identity, which is what makes the
  chips feel live. The corollary: anything that changes the underlying prices
  must go through `_recompute`, because nothing else drops the cache.
- **A section's shell is a component, not a shape three places copy
  (v0.9.22 #305).** The Platform table, the Leaderboard and the QIS Bulletin
  are all title → control bar → boxed body, so `section_panel(title, bar, body,
  *, height)` in `rails.py` is that arrangement named once. `height` is
  **required**: the component owns the shape and the caller owns the size, and
  a default sized for one caller quietly imposes that number on the next.
- **A split is shares with `min-width: 0`, never a pixel basis (v0.9.22
  #308).** The commentary block's 60:40 is `flex: 1 1 <share>` on both columns
  from the `COMMENTARY_*_SHARE` tokens. A `0 0 620px` basis is not a ratio: it
  read as 60% at 1030px wide and 43% at 1440px. And `min-width: 0` is
  load-bearing rather than tidiness — a flex item's automatic minimum is its
  content, so without it the wider section refuses to narrow and pushes its
  neighbour off the row instead of both shrinking.
- **Only one thing on screen names a thing (v0.9.22 #306, #307).** When a
  `section_panel` heads a section and a lit chip names the view, the widget
  inside must not also title itself. This is why `Leaderboard` lost `title_w`
  and both bulletin boards lost their in-HTML `<h3>`s — and why neither caps
  its own height, since the box already does. The same reasoning retires a
  constant: `WINDOW_LABELS` existed only to caption the board, and a day → label
  map nothing reads is one more thing to keep in step with a window list.
- **A shared option list is shared; widen a copy, not the original (v0.9.22
  #306).** The leaderboard's windows gained `1Y` as a new
  `LEADERBOARD_WINDOW_OPTIONS` built *from* `SHORT_WINDOW_OPTIONS`, because
  that constant also drives the
  Quantitative Z-Score window — neither of which asked for a year. A test pins
  both at four options, so the one-line edit to the shared list is caught.
- **Rank by the number you show (v0.9.22 #310).** The leaderboard ranks by the
  **score** and displays `score (value)`, with the sentiment colour on the
  score. The invariant is that a row's position and the figure it is read by
  agree; when they were the raw metric that was automatic, and now it is the
  score, the display had to follow. Note that this z-score is against an
  index's **own** trailing history — a different figure from the
  **asset-class-demeaned** z-score on the catalog
  column, which compares an index to its peers.
- **Authored data is data, so render it as data (v0.9.22 #307).** A note's
  `text` is escaped *and then* split into paragraphs. Escaping first makes it
  impossible to later add a branch that forgets, and a board that renders
  authored content as markup is a board that renders whatever that content
  says.
- **Retire a name with a grep, not a sweep (v0.9.22 #308).** What a
  half-retirement leaves behind is a name nothing calls, which importing the
  survivors would never notice. `test_commentary_pane.py` greps `src/`,
  `tests/` and `data/` for the five retired weekly-commentary names and asserts
  the file is gone from disk. It caught two doc-comments still spelling the
  dead filename in prose on its first run.
- **One control component (v0.9.21; one direction since v0.9.23 #326).** Every
  bar in the app — the catalog's *Table view*, the Leaderboard's Window, the
  Bulletin's board switch — is the same `.bbg-rail` chrome through
  `control_bar`. There was a column flavour too, for the rail beside the
  catalog table, and it went when the rail did. A second container idiom is the
  duplication the component exists to prevent: reach for the existing one and
  give it sections, rather than assembling a near-identical box at the call
  site.
- **A control is a widget, not a row of buttons (v0.9.21 #277).** `ChipGroup`
  presents a `W.Dropdown`'s surface — `value`, `label`,
  `observe(..., names="value")` — so a call site reading a dropdown does not
  care that the widget underneath is `.bbg-pill` buttons. That is what let the
  ranking controls change containers twice — dropdowns into a rail (#279), then
  the rail's contents into the bar (#324, #325) — as *restyles*:
  `PlatformAnalytics` takes them by constructor injection and reads `.value` to
  compute, **`.label`** to name the ranking column and `.observe` to re-render,
  and `.label` is a Dropdown API a bare `W.Button` row does not have. Build a control the app *reads* on
  this primitive rather than on loose buttons, or the read sites get rewritten
  to match the widget.
- **A multi-select reports membership, never click order (v0.9.21 #278).**
  `MultiChipGroup` normalizes its `value` into options order on every write, so
  "ticked A then C" and "ticked C then A" are one state. The catalog nests by
  the hierarchy and never by tick order (#273); making the widget incapable of
  carrying an order is stronger than every reader remembering to ignore one.
- **The catalog's filter text lives in the browser — deliberately (v0.9.21
  #285).** It is the one piece of state that is *not* on its object, and the
  reason is mechanical: any options change destroys and rebuilds the whole
  DataTable, `selected_rows` is the only state itables re-sends across that
  rebuild, and **no traitlet carries typed filter text to the kernel**. So
  `UniverseGrid` cannot hold it without forking the widget. It is stashed on
  `window.__bbgCatalogFilters`, keyed by table id and column index, and
  re-applied by the same `drawCallback` after every rebuild — which is what
  makes a window switch preserve the filters instead of silently clearing them.
  Treat this as an exception with a reason, not a pattern to copy.
- **A JS hook has to be one the widget actually forwards (v0.9.21 #285).** The
  itables widget destructures `initComplete` out of the options and calls it
  only from inside its own wrapper, which it installs only when
  `column_filters` or `text_in_header_can_be_selected` is set — so a bare
  `initComplete` is dropped without an error. `drawCallback` is documented,
  forwarded untouched, and registered in `keys_to_be_evaluated`. Assert both
  when adding a callback: "it never ran" and "it ran and did nothing" look
  identical from Python.
- **A catalog control re-slices and re-ranks; it never fetches (v0.9.23 #324).**
  Both chips on the *Table view* bar recompute the ranking column from
  `state.arp_universe_prices` — the already-fetched cache — through
  `rolling_metric_zscore`. Nothing else recomputes: the performance table is
  measured once at load for **every** window, and a window change hides the
  columns it is not showing rather than dropping them. Only **Refresh**
  invalidates the prices. The trap the window opens is the opposite one: it is
  also the window the score is measured over, so it must go through
  `render_universe_grid` (a rebuild) rather than `set_window` alone (a
  re-send of options) — the column's name and the row order both move with it,
  and `set_window` is a recorder like `set_group_fields`, not a redraw.
- **A compute failure keeps the last good board.** `_render_leaderboard`
  appends its traceback to `errors_w` rather than writing it over the board. A
  board that is merely stale beats no board at all, and the chip that caused
  the failure is one click from a window that works. `errors_w` is a sibling of
  the block's two sections, never inside one, so no live control can wipe it.
- **Per-pane charts are pre-allocated, populated lazily (v0.6.9
  Workstream D)**: each `AnalysisPane` owns one fresh `Chart` per analysis type
  (unique instances, so the two panes never share a figure). Each chart builds
  its figure in `__init__` but is **not** populated on recompute —
  `render_pane` renders only the **currently-mounted** view per pane and
  records it in `pane.fresh`; the other eight are populated on **first
  pick** by `bind_lazy_render`'s `pane.picker` observer (then added to
  `pane.fresh`), so a revisit is a free `pane.stack.children` swap. Picker
  changes still never fetch; the swap (in `panes.py` `_on_pick`) is
  unchanged. `pane.fresh` is reset on every recompute (only the mounted
  view is re-rendered) and emptied by `clear_pane`; the lazy observer
  no-ops while `state.cur_prep is None`.
- **The all-catalog grid is a grouped table, and its row order is load-bearing
  (v0.9.18 #263, #273)**. `UniverseGrid` is an `itables` `ITable`; the other two
  grids stay on `ipydatagrid`. Four things about it are easy to break by
  accident:

  - **Contiguity is correctness, not presentation.** DataTables' RowGroup opens
    a new header whenever a group value changes between *adjacent* rows — it
    never gathers scattered rows. A frame sorted by z-score alone fragments
    into one header per row. `_group_ordered` therefore ranks **every** level
    (a solution by its best member, a category by its best within that
    solution, and so on) with the level's own label as a tiebreaker, so two
    groups sharing a best member still cannot interleave. Ranking by the
    deepest level only is the obvious implementation and it is wrong: it leaves
    outer levels interleaved.
  - **Nesting order is the hierarchy's, never the user's.**
    `UNIVERSE_GRID_GROUPABLE_FIELDS` declares all four groupable fields in
    nesting order (asset class above the three tiers); the Group by chips pick
    which appear, and `universe_grid_group_fields` normalises the selection
    back into that order. Ticking order must stay meaningless — and since
    v0.9.21 `MultiChipGroup` cannot report one, so the guarantee no longer
    rests on every reader remembering to discard it.
  - **There is no column sorting, and that is deliberate.** Header sort is
    inert while RowGroup is active, and sorting by a stat column fights the
    contiguity above — the two want the row order for different things. The
    user drives row order through the grouping instead (#264, closed
    not-planned). Filtering is the top-left global search box plus the
    per-column filter row beneath the header labels (v0.9.21 #283, #285) —
    one box per column since #297, the numeric ones taking a comparison.
  - **Changing the window hides columns; it never drops them.** Every stats
    window stays in the frame and all but one are hidden through `columnDefs`,
    so switching is a visibility change: the grouping, the row order and the
    selected row all survive, and nothing recomputes. Dropping columns rebuilds
    the table and resets all three — including the row-position-to-ticker map
    that routes a click.

- **`ITable.update` merges its options (v0.9.18 #273)**: an option you leave
  out keeps its previous value. It is not a full replacement. Omitting
  `rowGroup` when the user unchecks every grouping box left the old `dataSrc`
  in place, pointing at whatever column 0 had become — one group header per
  row, each named after a ticker. Send the option explicitly (`False` to
  disable) rather than omitting it, and note that a unit test asserting
  `"rowGroup" not in options` passes throughout.

- **The itables chrome needs the right selector and `!important`
  (v0.9.18 #263)**: the container class is **`itables_anywidget`**, not
  `itables`, and rules must outrank DataTables' bundled stylesheet —
  `div.itables_anywidget table.dataTable … !important`. With the wrong
  selector the table renders stock-light, which reads as "itables cannot be
  themed". Two consequences that cost real time: RowGroup emits
  `<tr class="dtrg-group"><th>`, a **th** not a td, so a `td`-only rule styles
  nothing while looking correct; and because the body-cell background is
  `!important`, the diverging heat ramp must be written with
  `setProperty(..., 'important')` — a plain inline style loses to it, and the
  cells carry the right colour while painting flat navy.

- **The per-column filter row is built from `td`, not `th` (v0.9.21 #285)**:
  itables leaves `text_in_header_can_be_selected` on by default, and the
  wrapper that option installs walks `$("thead th", …)` in `initComplete` —
  which runs *after* the first draw, so after the `drawCallback` that builds
  the row — and `.empty()`s every cell whose `span.dt-column-title` is missing
  or blank. A filter cell is exactly that: an input and no title. The first cut
  of the row used `th` and every input was wiped a tick after it was created,
  leaving a `<tr>` with the right number of cells and nothing inside it — which
  is indistinguishable from a callback that never ran, and is why the row
  looked like it was not rendering at all. A `td` is outside that selector's
  reach; the price is that the cells inherit none of the `thead th` chrome and
  carry their own pin and opaque background in `app_css.html`. The callback's
  built-once guard counts inputs rather than testing for the row, so a future
  version of that pass degrades to a rebuild on the next draw rather than to a
  blank row that never comes back.

- **A number column filters by comparison, not by substring (v0.9.21 #297)**:
  every column in the catalog table carries a filter box, but the stat and
  Z-Score columns take `>1`, `<=2`, `1..3` or a bare number rather than text.
  This is not a refinement of a substring filter — a substring filter over
  them is *wrong*. `_js_number_render` returns the raw value for every
  non-display request, so DataTables searches a Return column that reads
  "5.23%" as `0.0523`: typing what is on the screen matches nothing. The
  comparison is registered with `column.search.fixed()`, DataTables' own
  per-column predicate hook (the same one its ColumnControl extension filters
  numbers with), and `_filter_kinds` marks the percent columns so the browser
  compares in the units the cell shows. One consequence worth keeping: the
  renderer's ×100 and the filter's ×100 read the **same** `_is_percent_col`,
  because a column rendered as a percentage and filtered as a fraction answers
  `>1` with the whole catalog. A bare number matches at the precision typed
  ("1.2" is [1.15, 1.25]), and text that is not a comparison — the `>` that
  every `>1` passes through — leaves the column unfiltered and marks the box,
  rather than emptying the table under the user's hands mid-keystroke.

- **The catalog scrolls in CSS, not through `scrollY` (v0.9.18 #272)**:
  DataTables' `scrollY` renders the header in a second table and sizes both
  once, at init. When the container settles to its real width afterwards — or
  when this app's `!important` font rules land after DataTables measured — the
  two end up different widths and the header sits off its columns until a
  redraw. That was the "headers need one click to snap into place" report from
  a BQuant terminal, measured at 169px of drift across 18 columns. The scroll
  lives on `.dt-layout-cell` (**not** the `.dt-layout-row` around it —
  DataTables already gives the cell `overflow: auto`, so the cell is the
  header's nearest scrolling ancestor and a sticky `th` sticks to it).

- **A chart is one object (v0.9.17 #223)**: `charts.py` holds a `Chart` class
  per chart family, each owning its `FigureWidget` and exposing
  `update(...)` / `clear()`. **New charts are a `Chart` subclass** — not a
  factory here and an updater there, which is what let a figure be paired with
  the wrong updater. Anything a chart needs for the life of the figure (a title
  prefix, a companion grid) belongs on the object, not re-passed per update.
- **Chart updates go through `fig.batch_update()`**: every `update`
  mutates the FigureWidget inside a `batch_update()` block so the
  frontend sees a single atomic frame. Trace replacement uses
  `fig.data = ()` (clear) + `fig.add_traces(new_traces)` because plotly's
  `fig.data` setter only accepts a subset of the existing traces.
  The five per-strategy line charts (`LineChart`, `OutperformanceChart`,
  `SharpeZChart`, `DrawdownChart`, `RollingRefChart`) are thin callers of one
  shared `_update_line_series` engine — they only supply the per-chart hover
  format/suffix, an optional `tail_n` (Sharpe-z 1Y window), and an
  optional dynamic title; reference lines stay baked into each figure's
  `layout.shapes` at build time. The four analysis-pane benchmark
  dropdowns come from `_make_benchmark_dropdown`, and the grid classes
  share `_build_info_block` + `_apply_grid_styling`.
- **Grids re-assert their theme by construction (v0.9.17 #223)**: `PerfGrid` /
  `UniverseGrid` / `CalendarGrid` subclass `_Grid`, whose `_set_data` is the one
  place `grid.data` is assigned and which re-applies the dark theme on every
  write. Never assign `grid.data` from a caller — a raw assignment silently
  reverts the frontend to ipydatagrid's white background (the v0.6.5 bug), and
  that used to depend on every update path remembering `_reassert_dark_theme`.
- **Pane recompute preps once, renders the mounted views**: every
  Refresh-prices click preps the selected-set data slice once
  (`prep`, with `daily_returns` computed a single time and threaded into
  `perf_table`/`sz_series`/`cm`/`rd_stats` — v0.6.9 Workstream D) and
  renders the **currently-mounted** view of each pane against it; the
  off-screen views build lazily on first pick (see the pre-allocated/lazy
  bullet above).
- **Benchmark / regime controls re-render live (v0.6.9 Workstream C)**:
  each per-pane benchmark dropdown (Rolling Correlation / Rolling Beta /
  Outperformance) plus the Correlation-Heatmap Benchmark / Regime checkboxes
  (v0.7.5) / benchmark / `>`/`<` direction / tail controls re-render **only their own chart,
  immediately**, from the selected-set slice persisted on
  `DashboardState` at the last recompute (`state.cur_prep` /
  `cur_win_start` / `cur_win_end`) — no BQL fetch, no full recompute, the
  other pane untouched. The four benchmark-dependent chart blocks live in
  the shared `_render_heatmap` / `_render_rolling_corr` /
  `_render_rolling_beta` / `_render_outperf` module functions in
  `multi_strategy.py` — each taking `(ctx, pane)` since v0.9.16 #217 — called by
  both `render_pane` (full recompute) and `bind_live_controls` (the live
  `.observe` handlers). Live observers no-op when `state.cur_prep is None`
  (no valid selection) and swallow per-chart errors (the chart's own
  except-branch leaves it safe; a broken benchmark still surfaces on the
  next Refresh prices, where errors flow into the commentary block). The
  heatmap Benchmark / Regime checkboxes keep their separate visibility-sync
  observers (in `panes.py`, with the cascade Benchmark → benchmark dd +
  Regime → `>`/`<` + tail); the data re-render is added on top. The unchecked default
  uses the shared full-sample `prep.cm`; the regime path is computed
  per-pane so the two panes stay independent. **Refresh prices remains the
  only path that hits BQL and the only path that re-runs filters /
  multi-strategy selection / the analysis-date-range re-slice.**
- **Benchmark-dependent results are memoized (v0.6.9 Workstream B)**. The
  four heavy computes behind the live charts — `rolling_correlation`,
  `rolling_beta`, `excess_cum_return`, and the regime `regime_corr_matrix`
  — route through `state.memo` (a `src/cache.py` `LRUCache`) via
  `get_or_compute`, keyed by `("rcorr"|"rbeta"|"outperf", benchmark)` or
  `("heatmap", benchmark, direction, pct)`. The result depends only on
  `cur_prep` (the selection slice) + benchmark, **not** the pane, so the
  memo is **shared across both panes** (a second pane on the same benchmark
  is a hit) and flipping **back** to a previously-viewed benchmark is an
  instant hit — no recompute. The memo is **invalidated at the top of
  `_recompute`** (the single point that rebuilds `cur_prep`: Refresh /
  initial load / the no-selection guards), so it only ever holds
  current-slice results; benchmark flips don't call `_recompute`, so the
  memo survives across them. The non-regime heatmap stays on the
  already-computed `prep.cm` (no memo). Validation (benchmark-has-data)
  lives inside the memoized `compute` so a real miss still raises into the
  chart's `except`; a hit skips both the slice and the compute.
- **Analysis date range scopes the selected set, on Refresh prices.**
  Unlike the metadata filters (which only narrow the ticker dropdown),
  the date-range **boxes** re-slice the already-fetched `universe_prices`
  (still no BQL) and feed the narrowed `sel_window` into both the perf
  grid and every pane chart, with benchmark series sliced to the **same**
  `[win_start, win_end]`. Editing a date box only enforces `min ≤ max`
  (v0.7.5: the `SelectionRangeSlider` was removed) — the re-slice happens
  on the next Refresh prices. Bounds re-derive from the selection on every
  Refresh: `DashboardState.last_sel_key` tracks the rendered ticker set, so a
  **changed** basket resets the boxes to the new full overlap, while an
  **unchanged** basket preserves the user's narrowed range (clamped to
  current bounds). The overlap window's ends are persisted on
  `DashboardState.cur_bound_start` / `cur_bound_end`; `Clear all` snaps the
  boxes back to that full span; `Clear section` leaves them untouched (it
  is not a filter pill). All of this lives on `DashboardApp`
  (`src/layout/app.py`: `_set_date_bounds`, `_on_range_box`).
- **Inline HTML lives in `data/templates/`, not Python.** Every HTML
  snippet the UI builds (banner, status banner, section labels, quant-row
  labels, the commentary block's cards and boards (`launch_card` /
  `launches_board`, `commentary_card` / `notes_board`, the shared `empty_card`
  both boards fall back to, `leaderboard_column_title`), error box,
  grid headers) is a `*.html` file
  rendered via
  `render_template(name, /, **ctx)` in `src/layout/html.py`. Templates carry
  `{{placeholders}}` for **both** style tokens (spread from the shared
  `STYLE_CTX` — `{{navy}}`, `{{label_size}}`, …, so a `src/style.py` token
  change still propagates) and dynamic data — **`html.escape`'d by the caller
  before substitution, with no exception.** There was one until v0.9.22 #308:
  the weekly-commentary wrapper took its `body_html` raw, because that board
  was an author-written HTML file. Authored content is now *plain text*
  (`data/commentary.json`), and `_render_note_paragraphs` escapes it **and
  then** splits it into paragraphs — the inverse invariant, and the safer one,
  since a renderer that never passes raw markup cannot later grow a branch
  that forgets. Size
  placeholders end in `_size` so they never collide with a dynamic key like a
  card's `{{label}}`. Substitution is one pass per key in insertion order
  (style first, dynamic last) so escaped text is never re-scanned. Edit the
  `.html` files — not the Python — to change markup. The two 1-char
  separators in `builder.py` (the Z-Score row's "of", the date-range "–")
  stay inline as trivial exceptions.
- **Disclaimers are templated HTML** loaded from `data/`. The performance
  disclaimer's `{{start_date}}` / `{{end_date}}` placeholders are
  substituted at app-build time using `_load_disclaimer` in `src/layout/html.py`
  (a thin caller of the same `{{key}}` substitution as `render_template`);
  the legal disclosure has no placeholders. Edit the HTML files — not the
  Python — to change the wording.
- **Both perf grids use flat single-index string columns (v0.9.11).**
  The selected-strategy grid and the all-catalog grid both flatten the
  (period, metric) column tuples to single-index labels (e.g.
  `("1Y", "Return") -> "1Y Return"`) via `_flatten_perf_columns`, and
  render under a **single-row header** (`base_column_header_size=26`).
  Per-column pixel widths come from `_perf_column_widths` (a tiny
  color-swatch column, uniform stat columns, and content-fit
  descriptive / z-score columns fit to the header + actual cell
  strings). Autofit is done in Python — a deterministic content-fit
  (`_content_px`), not ipydatagrid's frontend `auto_fit_columns`, so
  the color / stat columns stay pinned while only the descriptive
  columns re-fit. `_perf_renderers` matches on the flat string name
  (e.g. `name.endswith(" Sharpe")`) so it serves both grids. (This
  replaced the earlier 2-level MultiIndex layout with comma-joined
  `"<level0>,<level1>"` width keys and a two-row header — flattened in
  v0.9.11.)
- **Fetching and analysing are two horizons (v0.9.22 #311, widened v0.9.23
  #322).** The app **analyses** `LOOKBACK_YEARS = 5` back — every chart window,
  every `5Y` label — but **fetches** `score_history_years()`, which is
  **derived**, not typed: `LOOKBACK_YEARS + the longest window stat_windows()
  offers`, ten years today. Both boards score a metric against
  `SCORE_SAMPLE_DAYS` of its own rolling history, so the deepest case needs the
  longest window *plus* that sample — `5Y + 5Y` for the catalog table, `1Y + 5Y`
  for the leaderboard. #311 wrote the leaderboard's case as the literal `6`,
  which nothing checked against the windows on offer; deriving it means widening
  `LOOKBACK_YEARS`, or adding a window within it, carries the fetch along
  instead of leaving a quietly truncated sample behind. The boundary is
  `DashboardApp._analytics_window_start()`, and **every consumer goes through
  it**: with the two numbers equal a missed slice was harmless, and now it is a
  ten-year figure under a `5Y` label. The two scorers are the documented
  exceptions that read the unsliced frame. Three consumers had never sliced at
  all — `since_inception_perf`, `calendar_return_table` and the benchmark
  short-history caveat — because until #311 they never had to.
  The rolling-Sharpe window is `SHARPE_WINDOW = 252` (1Y); the perf grid uses
  `PERF_TABLE_YEARS = (1, 3, 5)`. No UI date picker for the chart range.
- **Plotly auto-fits y-axis** on data replacement, so the bqplot-era
  manual scale-rebinding is no longer needed. Line / drawdown / sharpe-z
  / rolling-ref charts use `layout.shapes` with `xref="paper"` to draw
  a dashed reference line that stays in place across data updates and
  empty states.
- **Selected tickers stay visible** in the dropdown even when the metadata
  filters or search box would otherwise hide them — so the user doesn't lose
  selection state while typing.
- **Startup selection (v0.8.10)**: the Multi-Strategy strategies picker opens
  pre-seeded with the **top 5 indices by z(1W Sharpe, 1Y)** (the highest-ranked
  over the fetched cache, capped at the universe size) via `_default_selection`,
  set right after the post-fetch prune resets `ticker_w.options` (which would
  otherwise clear the constructor default). The initial `_recompute()` then
  renders the selected-strategy grid + both panes populated, so the tab isn't
  empty on load. Refresh keeps the user's own selection (it isn't reseeded).
- **Recompute errors surface in the commentary block** as a styled traceback,
  rather than leaving the charts silently empty. See `_render_error` in
  `src/layout/html.py`.
- **Agent context lives in `.claude/` and `.meta/`.** Reusable skills
  are folder-per-skill under `.claude/skills/<name>/SKILL.md` (Claude
  Code auto-discovers them) — the Python lifecycle + doc-drafting skills
  came from `RorySullivan1/claude-skills-library`; `ipywidgets`,
  `plotly`, and `bquant-dashboard-spec` are project-authored against the
  conventions in this file (prefer them for UI/chart work;
  `bquant-dashboard-spec` is the portable platform reference for the BQL
  fetch contract + recommended fetch patterns + standard BQuant UI stack —
  load it first when touching anything that fetches from BQL or designs the
  dashboard). Forward scope is tracked in **GitHub issues**, labelled per
  version cycle (e.g. `v0.9.13-perf`) rather than in an in-repo roadmap —
  in-repo stubs drifted out of date against the shipped branches, so the
  issue tracker is the single source of truth. The enforcement and advisory hook
  scripts live in `.claude/hooks/` (documented in `.claude/hooks/README.md`),
  and `.claude/templates/` holds portable, repo-agnostic copies of the hooks +
  `workstream` skill for lifting into other repos (not auto-loaded — the active
  ones stay under `.claude/hooks/` and `.claude/skills/`). The canonical
  shipped version is `.meta/VERSION` — bump it together with the
  "Branching" section above.
- **Shared `.claude/` assets are synced from `RorySullivan1/claudebrain`**
  (`example-project/.claude/` is the canonical copy; last synced 2026-09-04).
  The Python / quant / docs / GitHub / operational skills and the objective
  agents are pulled verbatim; `finance-quantitative-developer`,
  `python-developer`, `goal-auditor`, `workstream`, the two bash gates, and
  `settings.json` are **specialised to this repo** and are not overwritten on
  a sync (they read `src/stats/`, GitHub issues, `quality-gates.sh`, …).
  Upstream's roadmap/version flow (`.meta/roadmap/`, `/version-set`,
  `roadmap_guard`) is deliberately **not** adopted — forward scope lives in
  GitHub issues here. Upstream's *skill-wins* rule applies: a brief that
  restates a skill is dead weight, which is why the echoed
  `python-project-instructions` skill was retired. Three assets from the
  sync matter beyond the skill text: **`claim-grounding` +
  `.claude/workflows/verify-claims.md`** are the truth gate to run over the
  project-authored `bquant-dashboard-spec` / `ipywidgets` / `plotly` skills
  (they assert facts about BQL, ipywidgets and plotly that have never been
  grounded); the advisory **`prose_budget.py`** hook + `prose-auditor` agent
  + `/prose-review` command audit comment/docstring length per scope against
  `.claude/prose-budget.json` (pre-existing overruns grandfathered in
  `.claude/prose-baseline.json`); and **`post_bash_filter.py`** trims long
  command output before it reaches the context. Details in
  `.claude/hooks/README.md`.
- **Session state lives on `DashboardState`** (`src/layout/state.py`), built
  once by `DashboardApp` and shared by every orchestration method. They mutate
  attributes (`state.universe_prices = …`, `state.active_filter = …`), which
  never rebinds a name — so there is **no `nonlocal`** and no list-as-mutable-cell
  hack.
- **Annotate `state` as `DashboardState`, never `object`.** `state.py` imports
  `panes` / `selection` / `single_strategy` (and through the last of those,
  `filter_panel`), so those modules cannot import `DashboardState` back at
  module level — a runtime `from .state import DashboardState` there raises
  ImportError on a partially initialized module. Use a `TYPE_CHECKING` guard
  instead; every layout module has `from __future__ import annotations`, so the
  annotation is a string and the symbol is never needed at runtime. `platform`
  and `multi_strategy` have no cycle today but are guarded the same way, so the
  one annotation reads identically everywhere. This matters more than it looks:
  with `state: object` a checker rejects *every* attribute access, so the
  annotation bought nothing — typed, `state.universe_prices` resolves and a
  misspelled field is an error.
- **Behaviour lives on `DashboardApp`** (`src/layout/app.py`, v0.9.16 #225;
  `builder.py` is now just the `build_app` entry point).
  The old rule here was "the closures stay nested in `build_app`" — right when
  the alternative was `nonlocal`, wrong once the state became a dataclass. So:
  **new shared session state is a `DashboardState` field; new behaviour is a
  `DashboardApp` method** — not a fresh closure. `build_app()` stays the public
  entry point the notebook calls, and returns `DashboardApp(...).root`.
  **Startup stays synchronous** and runs from `__init__`, for the Voila reason
  in `architecture.md` (#179); Refresh stays threaded.
- **New top-level files require updating the architecture map** (in
  `architecture.md`).


## The Platform card's two rules (v0.9.24, epic #331)

**A chart owns its figure *and* its points.** Every `Chart` on the analytics
card exposes `points()` — the frame it drew, as `path` / `label` / `name` /
`value` / `count` — plus the label and format its value column should carry.
The points table reads that and never reaches into a figure's traces, so the
chart-to-table pairing is structural rather than something a call site has to
remember. It is the same argument as the #223 figure-updater rule one block
up: the thing that knows is the thing that is asked.

Its corollary: **one number, three places.** A point's value is computed once,
and the axis position, the cell colour and the table cell are all that one
number. A renderer that recomputes it is the defect, because the two readings
can then disagree by a rounding or by a window.

**One `Drill`, read everywhere, written in one place.** `Drill(scope, level)`
is frozen and replaced wholesale through `PlatformAnalytics.set_drill`. A
marker click, an icicle zoom, a Level chip, a breadcrumb segment and a points
row all go through that one setter, so no chart can hold a private focus. The
setter repaints the two controls that *display* the state — the Level chips
and the breadcrumb — with their observers suppressed; without that guard a
drill change renders twice, and a breadcrumb click takes its level from the
chip it has just repainted rather than from the prefix that was clicked.
