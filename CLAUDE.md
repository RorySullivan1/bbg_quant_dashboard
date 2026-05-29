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
- **Selected Strategies** — full-width filter box (toggle-button
  filters + searchable ticker box + Refresh-prices button) on top,
  followed by an always-visible selected-strategy performance grid
  (1Y/3Y/5Y per-ticker Return/Vol/Sharpe/Max DD), followed by **two
  side-by-side analysis panes**. Each pane carries its own dropdown
  picker that swaps in any of the 8 analysis types (`Cumulative
  Performance`, `1Y Sharpe-z Line`, `Correlation Heatmap`,
  `Risk / Return`, `Drawdown`, `Rolling Correlation`,
  `Return Distribution`, `Rolling Beta`), so users can compare any
  two analyses side-by-side. Rolling Correlation and Rolling Beta
  each carry their own per-pane benchmark dropdown that sits on the
  same row as the analysis picker and only appears when the picker
  is on the relevant analysis. Every chart inside a pane renders at
  the same `CHART_HEIGHT` (520px) so the two panes always line up.

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
| `src/stats.py`        | `daily_returns`, `cum_perf`, `corr_matrix`, `rolling_sharpe`, `sharpe_zscore` (scalar, whole-catalog highlights), `rolling_sharpe_zscore` (time series, selected-set chart), `drawdown_series`, `rolling_correlation`, `rolling_beta`, `return_distribution_stats`, `ann_return`, `ann_volatility`, `ann_sharpe`, `perf_table`, `since_inception_perf`, `universe_perf`. |
| `src/commentary.py`   | `build_commentary` — rule-based bullets + recent-launch callout; always called with whole-universe inputs. |
| `src/layout.py`       | `build_app()` — banner + status banner + all-catalog commentary + top-level pill-button tab bar (Platform / Selected Strategies) + per-tab content + performance disclaimer + legal disclosure. `_make_analysis_pane(side)` factory builds a self-contained pane (own figure set, own benchmark dropdowns, own picker + swap container); the Selected Strategies tab mounts two of them side by side. `_recompute()` preps one data slice and renders both panes from it. |
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
    "LiveDate": "1957-03-04"
  }
}
```

`COLUMN_MAP` in `src/data.py` renames these to internal snake_case
(`name`, `asset_class`, `category`, `theme`, `solution`, `return_type`,
`live_date`). `IndexFamilyName` maps to the internal `category` field —
there is no separate "family" dimension. The metadata DataFrame also has
a derived `ticker` column = `<key> + " Index"`.

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
- **Toggle groups, search box, and date pickers narrow the ticker
  dropdown only**. They do not trigger any recompute or BQL call.
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
  dropdown at recompute time only; changing a dropdown alone does not
  trigger a recompute — the user clicks Refresh prices to refresh.
- **Disclaimers are templated HTML** loaded from `data/`. The performance
  disclaimer's `{{start_date}}` / `{{end_date}}` placeholders are
  substituted at app-build time using `_load_disclaimer` in `src/layout.py`;
  the legal disclosure has no placeholders. Edit the HTML files — not the
  Python — to change the wording.
- **One color identity per strategy**: every chart inside an
  analysis pane (lines, bars, scatter points) uses positional
  `LINE_PALETTE` colors keyed by the strategy's position in the
  selected ticker set. The selected-strategy perf grid above the
  panes carries a leftmost color-swatch column rendered with
  `ipydatagrid.VegaExpr` and the same positional palette, so the
  grid acts as the universal legend — every chart's per-strategy
  bqplot legend (`display_legend`) is off. `AssetClassColor` /
  `ASSET_CLASS_COLORS` remain defined in `src/style.py` but are
  currently unused.
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
- Toggling a button under any filter group — the ticker dropdown narrows
  to the intersection; an unselected toggle looks like a plain button
  (no empty checkbox square).
- Typing in the ticker search box — the dropdown narrows to substring
  matches on ticker or name; already-selected tickers stay visible.
- Cold start (no `data/.cache/`) — status banner reads `Fetching
  prices…` then `Loaded N indices · M trading days · fetched from
  mock prices in X.Ys`; a `prices_<today>.parquet` appears under
  `data/.cache/`.
- Warm start (within `CACHE_TTL_HOURS`) — status banner reads
  `Loaded N indices · M trading days from cache (HH:MM · MM-DD)`; no
  BQL/mock fetch happens.
- Clicking Refresh prices — banner pulses `Fetching prices…` then
  `Loaded … fetched from BQL in X.Ys`; the parquet mtime advances.
- Clicking the top-level **Platform** / **Selected Strategies** pill
  buttons toggles the active button to navy + white and swaps the
  content area; commentary stays visible above both.
- Clicking Refresh prices with 2+ tickers — every figure in BOTH
  analysis panes refreshes (the pane's currently mounted view shows
  the new data; the other 8 pre-built views are also populated so
  swapping the picker afterwards is instant).
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
- The performance disclaimer below the tab content shows the
  app-load date window (e.g. "2021-05-20 to 2026-05-20"); the bottom
  legal block renders justified.
- The commentary block stays the same across filter changes — it
  describes the whole catalog every time.
- The **Platform** tab shows every catalog index with metadata plus
  1Y/3Y/5Y/Since-Inception performance.
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.
