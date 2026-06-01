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

The screen layout is: banner → status banner → all-catalog commentary
block (always visible) → **top-level pill-button tab bar** with two
tabs:

- **Platform** — full-width all-catalog performance grid (every index
  with metadata plus 1Y / 3Y / 5Y / Since-Inception performance).
- **Multi-Strategy Analysis** — full-width filter box split into two
  side-by-side panels: a **left** strategies picker (search box above
  the `ticker_w` dropdown, which stretches via `flex` to match the
  filter panel's height) and a **right** filter panel. The right panel
  has an action row on top — **Refresh prices** (green, via the
  `Color.GREEN_600` token, so the primary action stands out) plus **Clear
  section** (clears the active filter pill's selections, or the date
  range/currency on Characteristics, or the ratio thresholds on
  Quantitative) and **Clear all** (clears every filter checkbox group,
  the launch-date range, the currency, the quant thresholds, and the
  search box; selected tickers are kept) — then a pill header bar (same
  `TabButtonTone` style as the top tabs) whose buttons — Asset Class /
  Category / Theme / Return Type / **Characteristics** /
  **Quantitative** — swap which dimension's value list shows below. The
  first four show checkbox value lists; **Characteristics** shows the
  Launch-date range (two date boxes separated by a hyphen) plus a
  **Currency** dropdown; **Quantitative** filters the universe by
  price-derived ratios — a global Period (1Y/3Y/5Y) dropdown, then one row
  per metric (Sharpe / Sortino / Calmar / Beta / Treynor / Jensen α /
  VaR % / RSI / Z-Score) of
  `[≥ or ≤ dropdown] [value box]`, with an inline parameter dropdown where
  relevant (Beta carries its benchmark dropdown, Z-Score its selectable
  base metric) — all via `quant_metrics_table` / `zscore_cross_section`,
  computed live from the already-fetched prices, no BQL. Below the filter
  box: an
  always-visible selected-strategy performance grid
  (1Y/3Y/5Y per-ticker Return/Vol/Sharpe/Max DD), followed by **two
  side-by-side analysis panes**. Each pane carries its own dropdown
  picker that swaps in any of the 9 analysis types (`Cumulative
  Performance`, `Outperformance`, `1Y Sharpe-z Line`,
  `Correlation Heatmap`, `Risk / Return`, `Drawdown`,
  `Rolling Correlation`, `Return Distribution`, `Rolling Beta`), so
  users can compare any two analyses side-by-side. `Outperformance`,
  Rolling Correlation, and Rolling Beta each carry their own per-pane
  benchmark dropdown that sits on the same row as the analysis picker
  and only appears when the picker is on the relevant analysis.
  (`Outperformance` is the cumulative excess return — strategy minus
  benchmark cumulative % return, in percentage points off a zero
  baseline.) `Correlation Heatmap` additionally carries a per-pane
  **Regime filter** checkbox on that row; ticking it reveals a benchmark
  dropdown, a Down/Up tail-direction toggle, and a 0–100% (step 5) tail
  size, and conditions the matrix on that benchmark-return regime while
  adding the benchmark as a row/column (see `regime_corr_matrix`).
  Every chart inside a pane renders at the same
  `CHART_HEIGHT` (520px) so the two panes always line up.

Below the tab content: performance disclaimer (templated with the data
window) → bottom legal disclosure (justified).

## Run instructions

**On a BBG terminal (BQuant):**
1. Open `dashboard.ipynb` inside BQuant.
2. Run the single cell — `build_app()` returns the rendered VBox.

**Locally (off-terminal, mock prices):**
```
pip install -r requirements.txt
voila dashboard.ipynb
```
`src/bql_client.py` detects whether `bql` is importable. Off-terminal it falls
back to a deterministic synthetic price series keyed by ticker, so the
dashboard always renders end-to-end.

## Architecture map

| Module                | Owns                                                                   |
| --------------------- | ---------------------------------------------------------------------- |
| `src/config.py`       | Constants: lookback, new-launch window, Sharpe windows, file paths.    |
| `src/style.py`        | Centralized style tokens: `Color`, `Font`, `FontSize`, `StatusTone`, `Sentiment`, `AssetClassColor` enums plus `ASSET_CLASS_COLORS` / `LINE_PALETTE`. All inline CSS in `src/layout.py` references these — change hex/font values here, not at call sites. |
| `src/data.py`         | Loads JSON metadata, filters it, lists unique values for dropdowns.    |
| `src/bql_client.py`   | `fetch_prices(tickers, start, end, use_cache=True) -> (df, source)` — BQL when available, mock otherwise. Reads/writes a per-trading-day parquet cache under `data/.cache/prices_{YYYY-MM-DD}.parquet` (TTL `CACHE_TTL_HOURS`) via `_cache_read` / `_cache_write`. |
| `src/stats.py`        | `daily_returns`, `cum_perf`, `corr_matrix`, `rolling_sharpe`, `sharpe_zscore` (scalar, whole-catalog highlights), `rolling_sharpe_zscore` (time series, selected-set chart), `drawdown_series`, `excess_cum_return` (cumulative excess return vs a benchmark, pp), `corr_matrix`, `regime_corr_matrix` (correlation over a benchmark-return tail, benchmark added to the matrix), `rolling_correlation`, `rolling_beta`, `return_distribution_stats`, `ann_return`, `ann_volatility`, `ann_sharpe`, `calmar_ratio`, `ann_beta` (scalar beta vs a benchmark over a window), `treynor_ratio`, `jensen_alpha` (vs a benchmark, rf=0), `downside_deviation`, `sortino_ratio`, `historical_var` (positive daily VaR loss), `rsi` (Wilder RSI), `zscore_cross_section` (cross-sectional z-score of a per-ticker metric), `quant_metrics_table` (per-ticker Sharpe/Sortino/Calmar/Beta/Treynor/Jensen/VaR/RSI table for the Quantitative filter), `perf_table`, `since_inception_perf`, `universe_perf`. |
| `src/commentary.py`   | `build_commentary` — rule-based bullets + recent-launch callout; always called with whole-universe inputs. |
| `src/layout.py`       | `build_app()` — banner + status banner + all-catalog commentary + top-level pill-button tab bar (Platform / Multi-Strategy Analysis) + per-tab content + performance disclaimer + legal disclosure. `_make_analysis_pane(side)` factory builds a self-contained pane (own figure set, own benchmark dropdowns, own picker + swap container); the Multi-Strategy Analysis tab mounts two of them side by side. `_recompute()` preps one data slice and renders both panes from it. |
| `dashboard.ipynb`     | Thin entrypoint that calls `build_app()`.                              |
| `data/performance_disclaimer.html` | Templated disclaimer with `{{start_date}}` / `{{end_date}}` placeholders; rendered immediately below the all-catalog grid. |
| `data/legal_disclosure.html`       | Bulk legal copy, justified, no placeholders; rendered at the bottom of the dashboard. |

## Data contract — `data/indexdb.json`

Orient-`index` JSON: a dict keyed by the **short ticker** (without the
`" Index"` suffix). `src/data.py` appends `" Index"` before any BQL call.

```json
{
  "SPX": {
    "Name": "S&P 500",
    "AssetClass": "Equity",
    "IndexFamilyName": "S&P US Broad",
    "Theme": "Core Beta",
    "Solution": "Beta",
    "ReturnType": "Total",
    "Currency": "USD",
    "LiveDate": "1957-03-04"
  }
}
```

`COLUMN_MAP` in `src/data.py` renames these to internal snake_case
(`name`, `asset_class`, `category`, `theme`, `solution`, `return_type`,
`currency`, `live_date`). `IndexFamilyName` maps to the internal
`category` field — there is no separate "family" dimension. The metadata
DataFrame also has a derived `ticker` column = `<key> + " Index"`.
`Currency` is metadata (BQL only supplies `px_last`, not reference
fields); `load_metadata` pads any missing `COLUMN_MAP` column with `NA`,
so records without a `Currency` key still load.

## BQL contract

`src/bql_client.py` issues a single BQL request:

```python
bq = bql.Service()
px = bq.data.px_last(
    dates=bq.func.range(start.isoformat(), end.isoformat()),
    fill="prev",
)
request = bql.Request(tickers, {"px_last": px})
```

`tickers` must be the full BQL identifiers (i.e. include `" Index"`).
The response DataFrame is reset_indexed and we resolve the ID, DATE, and
value column names case-insensitively via `_pick_column` before pivoting
to wide form (`date` index, one column per ticker). Tickers that BQL
returns no data for show up as all-NaN columns rather than raising.

If you change this query, also update `_mock_prices` so the mock and
live paths return the same shape.

## Branching

- **Current version**: `v0.5.0`.
- **Branch naming**: every new branch starts with the current version
  followed by a slash-separated descriptor of what's being worked on.
  Format: `v{MAJOR.MINOR.PATCH}/{type}/{short-description}`.
  Examples:
  - `v0.5.0/enhancement/perf-grid-color-swatch`
  - `v0.5.0/bugfix/empty-ticker-traceback`
  - `v0.5.0/refactor/style-tokens`
- When the dashboard bumps to the next version, update this section and
  open new branches under the new prefix (e.g. `v0.5.1/...`).

## Conventions

- **One BQL call per session**. `build_app` issues a single
  `fetch_prices(arp_tickers + BENCHMARK_TICKERS, ...)` request at load
  time and caches the result in a `universe_prices` closure variable.
  Every visualization — including the all-catalog grid, the commentary,
  and the Rolling Correlation / Rolling Beta tabs — slices from that
  cache.
- **On-disk trading-day cache**. `fetch_prices` reads/writes
  `data/.cache/prices_{YYYY-MM-DD}.parquet`. On cold start the call
  hits BQL/mock and writes the parquet; subsequent same-day startups
  within `CACHE_TTL_HOURS` read it back without hitting BQL. A stale
  TTL, a missing file, or a cache that doesn't cover every requested
  ticker all fall through to a live fetch. The directory is gitignored.
- **Refresh prices button** (formerly Apply): re-fetches from BQL with
  `use_cache=False`, overwrites the parquet, then recomputes everything.
  Filter-only re-slicing (today the button always refetches) will be
  split back into a separate Apply control in a later PR.
- **Status banner** below the page banner reports load progress —
  `Fetching prices…` during the fetch, `Loaded N indices · M trading
  days · fetched from BQL in X.Ys` / `Loaded from cache (HH:MM · MM-DD)`
  on success, `Load failed — see error below` on error (with the full
  traceback rendered in the commentary block).
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
  only — that's the user's focus area. The whole-catalog scalar
  `sharpe_zscore` still feeds the highlights cards in the commentary
  block.
- **Per-pane figures are pre-allocated**: each `AnalysisPane` owns one
  fresh plotly `FigureWidget` per analysis type. Each FigureWidget is a
  unique widget instance, so the two panes never share. Picker changes
  swap `pane.stack.children` to the relevant pre-built view — no
  recompute, no BQL fetch.
- **Chart updates go through `fig.batch_update()`**: every `_update_*`
  helper mutates the FigureWidget inside a `batch_update()` block so the
  frontend sees a single atomic frame. Trace replacement uses
  `fig.data = ()` (clear) + `fig.add_traces(new_traces)` because plotly's
  `fig.data` setter only accepts a subset of the existing traces.
- **Pane recompute is eager**: every Refresh-prices click preps the
  selected-set data slice once and renders BOTH panes against it. Each
  pane reads its own Rolling Correlation / Rolling Beta benchmark
  dropdown, plus its Correlation-Heatmap Regime-filter checkbox /
  benchmark / direction / tail controls, at recompute time only;
  changing any of these alone does not trigger a recompute — the user
  clicks Refresh prices to refresh. (The heatmap Regime checkbox does
  toggle the visibility of its sub-controls immediately, but the matrix
  itself only updates on the next Refresh prices.) The unchecked default
  uses the shared full-sample `prep.cm`; the regime path is computed
  per-pane so the two panes stay independent.
- **Disclaimers are templated HTML** loaded from `data/`. The performance
  disclaimer's `{{start_date}}` / `{{end_date}}` placeholders are
  substituted at app-build time using `_load_disclaimer` in `src/layout.py`;
  the legal disclosure has no placeholders. Edit the HTML files — not the
  Python — to change the wording.
- **One color identity per strategy**: every chart inside an
  analysis pane (lines, bars, scatter points) uses positional
  `LINE_PALETTE` colors keyed by the strategy's position in the
  selected ticker set. The selected-strategy perf grid above the
  panes carries a leftmost color-swatch column (header **"Chart
  Color"**, `PERF_COLOR_COLUMN_NAME`) rendered with
  `ipydatagrid.VegaExpr` and the same positional palette, so the
  grid acts as the universal legend — every chart's per-strategy
  bqplot legend (`display_legend`) is off. `AssetClassColor` /
  `ASSET_CLASS_COLORS` remain defined in `src/style.py` but are
  currently unused.
- **Selected perf grid uses 2-level MultiIndex columns** (Info / 1Y /
  3Y / 5Y supercolumns over their leaves), matching the all-catalog
  grid. Custom per-column widths are kept via ipydatagrid's
  `"<level0>,<level1>"` comma-joined `column_widths` keys (built by
  `_build_perf_column_widths`), so the grid both shows a two-row
  header and fills a ~full-HD width (~2014px). This grid was flattened
  to single-level strings once (`2a9cc6c`) because MultiIndex widths
  were flaky; if they regress again, the fallback is uniform sizing
  via `base_column_size` (no `column_widths`), like the all-catalog
  grid. `_perf_renderers` matches on the column leaf
  (`col[-1] if isinstance(col, tuple) else col`) so it serves both
  grids.
- **Chart theme is dark (Bloomberg / Barclays blend)**: charts render
  on `Color.CHART_BG` (near-black `#0d1117`) via plotly's
  `plotly_dark` template + custom overrides defined in
  `_chart_layout()` in `src/layout.py`. The `LINE_PALETTE` is a
  high-chroma palette anchored by Bloomberg orange (`#FFA000`) and
  Barclays cyan (`#00B5E2`) so traces pop against the dark
  background. Chart-specific color tokens (`CHART_BG`, `CHART_GRID`,
  `CHART_AXIS`, `CHART_TEXT`, `CHART_TITLE`, `CHART_HOVER_BG`) live
  on the `Color` enum. The rest of the dashboard chrome (page
  banner, status banner, commentary block, perf grid) stays light —
  only the charts are dark.
- **Style tokens live in `src/style.py`**, not inline. Hex colors, font
  stacks, and font sizes used by `src/layout.py` reference the `Color`,
  `Font`, `FontSize`, `StatusTone`, `Sentiment`, `AssetClassColor`,
  and `TabButtonTone` enums. Adding a new color or size: extend the
  enum, don't inline.
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
- **Recompute errors surface in the commentary block** as a styled traceback,
  rather than leaving the charts silently empty. See `_render_error` in
  `src/layout.py`.
- **New top-level files require updating the architecture map above.**

## Testing notes

Off-terminal, the mock-price fallback is deterministic per ticker, so:

```python
from src.layout import build_app
build_app()
```

renders the full dashboard without a Bloomberg session. Verify by:
- Clicking a filter-type pill (Asset Class / Category / Theme / Return
  Type / Characteristics / Quantitative) in the right panel swaps the
  value list shown below; the active pill turns navy. Ticking a value
  checkbox narrows the ticker dropdown to the intersection.
  Characteristics shows the Launch-date range (two date boxes separated
  by a hyphen) and a **Currency** dropdown; setting either narrows the
  dropdown.
- The **Quantitative** pill shows a global Period (1Y/3Y/5Y) dropdown and
  one row per metric (Sharpe / Sortino / Calmar / Beta / Treynor /
  Jensen α / VaR % / RSI / Z-Score), each a `[≥/≤ dropdown] [value box]`;
  Beta's row carries the benchmark dropdown (shared by Treynor and Jensen)
  and Z-Score's carries its base-metric selector. Setting e.g. Sharpe
  `≥ 0.5` (or Sharpe `≤ 0.5`) narrows the dropdown to indices whose metric
  (computed from the already-fetched prices) clears the threshold; a blank
  box is ignored. Changing any operator/period/benchmark/z-metric re-narrows
  live, no BQL.
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
- Cold start (no `data/.cache/`) — status banner reads `Fetching
  prices…` then `Loaded N indices · M trading days · fetched from
  mock prices in X.Ys`; a `prices_<today>.parquet` appears under
  `data/.cache/`.
- Warm start (within `CACHE_TTL_HOURS`) — status banner reads
  `Loaded N indices · M trading days from cache (HH:MM · MM-DD)`; no
  BQL/mock fetch happens.
- Clicking Refresh prices — banner pulses `Fetching prices…` then
  `Loaded … fetched from BQL in X.Ys`; the parquet mtime advances.
- Clicking the top-level **Platform** / **Multi-Strategy Analysis** pill
  buttons toggles the active button to navy + white and swaps the
  content area; commentary stays visible above both.
- Clicking Refresh prices with 2+ tickers — every figure in BOTH
  analysis panes refreshes (the pane's currently mounted view shows
  the new data; the other 8 pre-built views are also populated so
  swapping the picker afterwards is instant — 9 analysis views total).
- Changing a pane's analysis-picker dropdown — only that pane's
  mounted view changes; the other pane is untouched, no recompute.
- Setting both panes' pickers to the same analysis — both render
  independently (separate plotly FigureWidget instances).
- Plotly modebar is visible at the top-right of every chart (zoom,
  pan, autoscale, PNG download). Hovering a line chart with
  `hovermode="x unified"` shows all selected tickers' values at the
  same date in one tooltip.
- Hovering a point on the risk/return scatter shows ticker name,
  annualized vol (%), annualized return (%), and annualized Sharpe (2dp).
- Each pane has its OWN Rolling Correlation / Rolling Beta benchmark
  dropdown — setting the left pane's benchmark to SPX and the right
  pane's to MXWO, then clicking Refresh prices, produces two
  independently-titled charts.
- On the Correlation Heatmap view, ticking **Regime filter** reveals a
  benchmark dropdown, a Down/Up toggle, and a 0–100% tail dropdown;
  clicking Refresh prices recomputes the matrix over the selected
  benchmark-return tail and adds the benchmark as a row/column, with the
  title noting e.g. "SPX Index worst 20% days". Flipping Down→Up or
  changing the % (then Refresh prices) changes the matrix; the other
  pane is unaffected. Unticking reverts to the full-sample correlation.
- The performance disclaimer below the tab content shows the
  app-load date window (e.g. "2021-05-20 to 2026-05-20"); the bottom
  legal block renders justified.
- The commentary block stays the same across filter changes — it
  describes the whole catalog every time.
- The **Platform** tab shows every catalog index with metadata plus
  1Y/3Y/5Y/Since-Inception performance.
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.
