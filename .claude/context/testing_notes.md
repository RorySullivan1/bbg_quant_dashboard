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

## User-benchmark isolation (#194)

`conftest.py` carries a suite-wide **autouse** fixture redirecting
`src.user_benchmarks.USER_BENCHMARKS_PATH` at a `tmp_path`. Every
`build_app()` reads that path at startup and any test that adds a benchmark
writes it, so without the fixture a test run leaves a real
`data/user_benchmarks.json` in the working tree — leaking state into later
tests *and* into the developer's repo. The module binds the path at import, so
the patch targets the module attribute, not `config`.

## Making the mock reject a ticker (#195)

The mock seeds its generator off `hash(ticker)`, so by default it resolves
**any** string — right for rendering the dashboard without a terminal, wrong
for anything that must cope with a ticker a user typed. Two module-level seams
in `src/bql_client.py` let a test drive the mock into the live path's two
failure modes, which are different and must stay distinguishable:

| Seam | Meaning | Result |
| --- | --- | --- |
| `_MOCK_UNRESOLVABLE: set[str]` | a wrong ticker — nothing comes back, ever | all-NaN column, warned; raises only when *nothing* in the request resolves |
| `_MOCK_FIRST_TRADE: dict[str, date]` | a real security with no history at the start of the window (launched mid-lookback, or stale) | NaN before that date, real data after; the frame keeps its full index |

These seams exist because the alternative had already failed once: with no
way to make the mock say "no", every validation path was untestable
off-terminal, and the test suite runs nowhere else — so the behaviour was
shipped behind a caveat marked "untestable in CI" and then broke in
production. A caveat is not a test.

Both are empty by default, so app behaviour is unchanged. `_clear_caches()`
resets them — they are mutable module state, so a test that sets one without
that reset would leak into every test after it. `tests/test_mock_resolution.py`
covers both, and pins them apart: reported as one generic error, a
valid-but-no-data ticker reads to the user as a bug.

Off-terminal, the mock-price fallback is deterministic per ticker, so:

```python
from src.layout import build_app
build_app()
```

renders the full dashboard without a Bloomberg session. Verify by:
- Clicking a filter-type pill (Asset Class / Category / Theme / Return
  Type / Characteristics / Quantitative) in the right panel swaps the
  value list shown below; the active pill gets the `.is-active` style
  (accent-bordered raised surface). Ticking a value
  checkbox narrows the ticker dropdown to the intersection.
  Characteristics shows the Launch-date range (two date boxes separated
  by a hyphen) and a **Currency** dropdown; setting either narrows the
  dropdown.
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
  **left**, the filter criteria (Asset Class / Category / Theme / Return Type /
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
- The **Platform** tab shows every catalog index with metadata plus
  1Y/3Y/5Y performance.
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.
