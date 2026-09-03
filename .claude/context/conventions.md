# Conventions, branching & workflow

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

## Branching

- **Current version**: `v0.9.11`.
- **Branch naming**: every new branch starts with the current version
  followed by a slash-separated descriptor of what's being worked on.
  Format: `v{MAJOR.MINOR.PATCH}/{type}/{short-description}`.
  Examples:
  - `v0.6.0/enhancement/perf-grid-color-swatch`
  - `v0.6.0/bugfix/empty-ticker-traceback`
  - `v0.6.0/refactor/style-tokens`
  - **Caveat:** when the integration branch is named exactly `v{X.Y.Z}` (as
    with `v0.6.0`), git can't also host nested `v{X.Y.Z}/<type>/<desc>` refs,
    so use the flattened `v{X.Y.Z}-<type>-<desc>` form (e.g.
    `v0.6.0-refactor-dashboard-state`).
- When the dashboard bumps to the next version, update this section and
  open new branches under the new prefix. Because the integration branch is
  named exactly `vX.Y.Z`, use the flattened form (see the caveat above) —
  e.g. `v0.9.12-<short-description>`.

## Development workflow

Every roadmap item ships through the same loop. The `/workstream` skill
(`.claude/skills/workstream/SKILL.md`) is the step-by-step playbook; the
`.claude/settings.json` PreToolUse hooks **enforce** the gates below.

1. **Plan first.** Enter plan mode (`Shift+Tab` ×2; there is no auto-default
   plan-mode setting), read the target GitHub issue, explore, design, and get
   the plan approved before editing.
2. **Branch.** Cut one integration branch per version (`vX.Y.Z`, off `main`),
   then a **flat-named sub-branch per workstream** off it
   (`vX.Y.Z-<desc>` — see the "Branching" caveat above). One workstream per
   branch, one issue per branch.
3. **Implement** only that workstream; respect the issue's non-goals; add/adjust
   `tests/`.
4. **Quality gates** — `ruff check src tests`, `black --check src tests`,
   `python -m pytest -q` must all be green. `.claude/hooks/quality-gates.sh`
   re-runs these on every `git commit` and **blocks** the commit on failure.
5. **Commit & push** `-u origin <branch>`. Never push to `main`/`master` —
   `.claude/hooks/block-main-push.sh` blocks it; land changes via PR.
6. **PR into the integration branch** (`vX.Y.Z`, not `main`); close the issue
   with a `Closes #N` keyword. Defer `.meta/VERSION` + release-note edits to
   end-of-cycle.

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
  request at load time (deduped, order-preserving) and caches the result in a
  `universe_prices` closure variable. Every visualization — including the
  all-catalog grid, the commentary, the Rolling Correlation / Rolling Beta
  tabs, the v0.7.0 Platform factor scatter + the v0.8.x sunburst, and the v0.8.5
  Regime Analysis charts — slices from that cache. The `FACTOR_TICKERS` (v0.7.0: a
  long-Treasury + short-rate TR proxy, the equity leg reuses `SPXFP Index`
  (`EQUITY_FACTOR_TICKER`, also a benchmark); v0.7.1 adds
  the `TREND_TICKER` = `BSLXAT Index` cross-asset trend factor for the scatter's
  z-axis) and the `REGIME_TICKERS` (the Regime Analysis indicators: `VIX Index`
  and the regional rates `FEDL01` / `EONIA` / `MUTKCALM`; v0.8.9 dropped
  `NFCIRISK` with the Risk regime) ride this same fetch — *no second BQL call* — and, like the
  benchmarks, are excluded from the ARP-universe views via
  `reindex(columns=meta["ticker"])`.
- **Two-tier price cache (v0.6.9; incremental in v0.9.13 #165)**.
  `fetch_prices` is fronted by an **in-memory session superset** — one growing
  frame `_MEM_SUPERSET` plus the date interval it covers `_MEM_COVER` — checked
  **before** the **on-disk trading-day** parquet
  `data/.cache/prices_{YYYY-MM-DD}.parquet`. Any request whose tickers ⊆ the
  superset's columns **and** whose `[start, end]` ⊆ the covered interval is
  served by *slicing* (`_covers` → `_serve`), no BQL. On a **miss**, only the
  missing rectangle is fetched — new tickers over the needed span, and/or the
  existing columns over the uncovered date extension (`_delta_specs`, non-
  overlapping so cached values are never disturbed) — then merged in
  (`_merge_superset`, fresh wins). So **extending the lookback or adding an
  index costs a delta, not a whole-universe refetch** — the key v0.9.13
  scalability fix. The cover is tracked separately from the data index, so a
  weekend/holiday `end` (no trading row) still counts as covered.
  `use_cache=False` (Refresh) refetches the full request and overwrites the
  overlap. The disk write is **best-effort**: on a read-only filesystem (or any
  write failure) `_cache_write` warns once, sets `_disk_cache_writable = False`,
  and the in-memory superset carries the session — the app never crashes on a
  read-only FS. `_cache_read` is containment-aware (column-pushdown
  `read_parquet(columns=…)`, left-date coverage) and swallows read errors as a
  clean miss; `_cache_write` writes the superset and prunes past-TTL files
  (`_prune_cache_files`). `_clear_caches()` resets both tiers for tests. The
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
  only — that's the user's focus area. The whole-catalog Key Highlights
  panels (`build_superlatives` / `build_launch_cards`) compute over the
  whole catalog (`arp_universe_prices`) in the commentary block, never
  the selection.
- **Per-pane figures are pre-allocated, populated lazily (v0.6.9
  Workstream D)**: each `AnalysisPane` owns one fresh plotly `FigureWidget`
  per analysis type (unique instances, so the two panes never share). The
  `FigureWidget`s are pre-built but **not** all populated on recompute —
  `_render_pane` renders only the **currently-mounted** view per pane and
  records it in `pane.fresh`; the other eight are populated on **first
  pick** by `_bind_lazy_render`'s `pane.picker` observer (then added to
  `pane.fresh`), so a revisit is a free `pane.stack.children` swap. Picker
  changes still never fetch; the swap (in `panes.py` `_on_pick`) is
  unchanged. `pane.fresh` is reset on every recompute (only the mounted
  view is re-rendered) and emptied by `_clear_pane`; the lazy observer
  no-ops while `state.cur_prep is None`.
- **Chart updates go through `fig.batch_update()`**: every `_update_*`
  helper mutates the FigureWidget inside a `batch_update()` block so the
  frontend sees a single atomic frame. Trace replacement uses
  `fig.data = ()` (clear) + `fig.add_traces(new_traces)` because plotly's
  `fig.data` setter only accepts a subset of the existing traces.
  The five per-strategy line updaters (`_update_line`,
  `_update_outperformance`, `_update_sharpe_line`, `_update_drawdown`,
  `_update_rolling_ref`) are thin wrappers over one shared
  `_update_line_series` engine — they only supply the per-chart hover
  format/suffix, an optional `tail_n` (Sharpe-z 1Y window), and an
  optional dynamic title; reference lines stay baked into each figure's
  `layout.shapes` at factory time. The four analysis-pane benchmark
  dropdowns come from `_make_benchmark_dropdown`, and both grid updaters
  share `_build_info_block` + `_apply_grid_styling`.
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
  `_render_rolling_beta` / `_render_outperf` closures, called by both
  `_render_pane` (full recompute) and `_bind_live_controls` (the live
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
  Refresh: a `last_sel_key` closure tracks the rendered ticker set, so a
  **changed** basket resets the boxes to the new full overlap, while an
  **unchanged** basket preserves the user's narrowed range (clamped to
  current bounds). The overlap window's ends are persisted on
  `DashboardState.cur_bound_start` / `cur_bound_end`; `Clear all` snaps the
  boxes back to that full span; `Clear section` leaves them untouched (it
  is not a filter pill). All of this lives in `build_app`'s closures in
  `src/layout/builder.py` (`_set_date_bounds`, `_on_range_box`).
- **Inline HTML lives in `data/templates/`, not Python.** Every HTML
  snippet the UI builds (banner, status banner, section labels, quant-row
  labels, the two-section Key-Highlights cards/wrapper (`superlative_card`,
  `launch_card`, `launch_empty`, `highlights_two_col`), error box,
  weekly-commentary wrapper + fallback, grid headers) is a `*.html` file
  rendered via
  `render_template(name, /, **ctx)` in `src/layout/html.py`. Templates carry
  `{{placeholders}}` for **both** style tokens (spread from the shared
  `STYLE_CTX` — `{{navy}}`, `{{label_size}}`, …, so a `src/style.py` token
  change still propagates) and dynamic data (`html.escape`'d by the caller
  before substitution; `body_html` from the weekly file stays raw). Size
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
- **Lookback is fixed** at `LOOKBACK_YEARS = 5` in `src/config.py`. The
  rolling-Sharpe window is `SHARPE_WINDOW = 252` (1Y); the perf grid uses
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
  issue tracker is the single source of truth. The PreToolUse enforcement
  scripts live in `.claude/hooks/` (documented in `.claude/hooks/README.md`),
  and `.claude/templates/` holds portable, repo-agnostic copies of the hooks +
  `workstream` skill for lifting into other repos (not auto-loaded — the active
  ones stay under `.claude/hooks/` and `.claude/skills/`). The canonical
  shipped version is `.meta/VERSION` — bump it together with the
  "Branching" section above.
- **Session state lives on `DashboardState`** (`src/layout/state.py`), built
  once in `build_app` and shared by the orchestration closures. They mutate
  attributes (`state.universe_prices = …`, `state.active_filter = …`), which
  never rebinds a name — so there is **no `nonlocal`** and no list-as-mutable-cell
  hack. The closures stay nested in `build_app`; add new shared session state as
  a `DashboardState` field, not a fresh closure variable.
- **New top-level files require updating the architecture map** (in
  `architecture.md`).
