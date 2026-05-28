# CLAUDE.md — bbg_quant_dashboard

Repo memory for future Claude sessions. Read this before editing.

## Project purpose

A Bloomberg BQuant App that lets clients browse an index catalog: filter by
metadata, look up tickers, and view performance, correlation, and a 1-year
rolling Sharpe-ratio z-score over a 5-year lookback. Metadata is stored
locally in `data/indexdb.json`; time-series prices are pulled from BQL at
runtime. The UI is built with `ipywidgets`, `bqplot`, and `ipydatagrid`, and
is deployable via Voila.

The screen layout is: banner → all-catalog commentary block → 30/70 row
(toggle-button filters + searchable ticker box on the left; line chart +
selected-set performance datagrid + 1Y Sharpe-z-score line chart, stacked,
on the right) → full-width **analysis Tab widget** (six tabs:
Correlation heatmap · Risk / Return scatter · Drawdown · Rolling Correlation
vs benchmark · Return Distribution · Rolling Beta vs benchmark) →
full-width **all-catalog performance grid** showing every index in the
catalog with metadata plus 1Y/3Y/5Y/Since-Inception performance →
performance disclaimer (templated with the data window) → bottom legal
disclosure (justified).

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
| `src/data.py`         | Loads JSON metadata, filters it, lists unique values for dropdowns.    |
| `src/bql_client.py`   | `fetch_prices(tickers, start, end)` — BQL when available, mock otherwise. |
| `src/stats.py`        | `daily_returns`, `cum_perf`, `corr_matrix`, `rolling_sharpe`, `sharpe_zscore` (scalar, whole-catalog highlights), `rolling_sharpe_zscore` (time series, selected-set chart), `drawdown_series`, `rolling_correlation`, `rolling_beta`, `return_distribution_stats`, `ann_return`, `ann_volatility`, `ann_sharpe`, `perf_table`, `since_inception_perf`, `universe_perf`. |
| `src/commentary.py`   | `build_commentary` — rule-based bullets + recent-launch callout; always called with whole-universe inputs. |
| `src/layout.py`       | `build_app()` — banner + all-catalog commentary + 30/70 row (filters + line chart + selected-set perf grid + 1Y Sharpe-z line chart) + analysis Tab widget (correlation heatmap · risk/return scatter · drawdown · rolling correlation · return distribution · rolling beta) + all-catalog perf grid + performance disclaimer + legal disclosure. |
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

## Conventions

- **One BQL call per session**. `build_app` issues a single
  `fetch_prices(arp_tickers + BENCHMARK_TICKERS, ...)` request at load
  time and caches the result in a `universe_prices` closure variable.
  Every visualization — including the all-catalog grid, the commentary,
  and the Rolling Correlation / Rolling Beta tabs — slices from that
  cache. The Apply button only re-slices and recomputes; it does not
  re-fetch from BQL.
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
- **Selected-set charts (cumulative-perf line, perf grid, 1Y Sharpe-z line,
  and every tab in the analysis Tab widget — heatmap, scatter, drawdown,
  rolling correlation, return distribution, rolling beta)** are over the
  currently selected tickers only — that's the user's focus area. The
  whole-catalog scalar `sharpe_zscore` still feeds the highlights cards
  in the commentary block.
- **Tab widget recompute is eager**: every Apply click refreshes all six
  analysis tabs. Per-tab benchmark dropdowns (Rolling Correlation /
  Rolling Beta) are read at recompute time only; changing the dropdown
  alone does not trigger a recompute — the user clicks Apply to refresh.
- **Disclaimers are templated HTML** loaded from `data/`. The performance
  disclaimer's `{{start_date}}` / `{{end_date}}` placeholders are
  substituted at app-build time using `_load_disclaimer` in `src/layout.py`;
  the legal disclosure has no placeholders. Edit the HTML files — not the
  Python — to change the wording.
- **Scatter palette**: asset-class colors are defined by
  `ASSET_CLASS_COLORS` in `src/layout.py`; unknown classes fall back to
  `UNKNOWN_ASSET_CLASS_COLOR`. The legend is rendered as a sibling HTML
  block under the figure because `bq.Scatter` has no built-in categorical
  legend.
- **Lookback is fixed** at `LOOKBACK_YEARS = 5` in `src/config.py`. The
  rolling-Sharpe window is `SHARPE_WINDOW = 252` (1Y); the perf grid uses
  `PERF_TABLE_YEARS = (1, 3, 5)`. No UI date picker for the chart range.
- **Y-axis refit on every recompute**: `_update_line` explicitly resets
  `y_sc.min` / `y_sc.max` (and the x-scale) after replacing marks, because
  bqplot otherwise keeps the prior scale bounds.
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
- Clicking Apply with 2+ tickers — cumulative-perf line chart (legend
  labels read "Name (TICKER Index)"), selected-set perf grid, 1Y
  Sharpe-z-score line chart (one line per ticker plus a dashed zero
  reference), and all six analysis tabs (heatmap, scatter, drawdown,
  rolling correlation vs benchmark, return distribution + per-ticker
  stats grid, rolling beta vs benchmark) all refresh together; the
  line charts' y-axes rescale to the new data range.
- Hovering a point on the risk/return scatter shows ticker name,
  annualized vol (%), annualized return (%), and annualized Sharpe (2dp).
- Switching the benchmark dropdown inside the Rolling Correlation or
  Rolling Beta tab and clicking Apply updates the chart title to show
  the new benchmark and rebuilds the lines against it. The other tab's
  benchmark is independent.
- The performance disclaimer below the all-catalog grid shows the
  app-load date window (e.g. "2021-05-20 to 2026-05-20"); the bottom
  legal block renders justified.
- The commentary block stays the same across filter changes — it
  describes the whole catalog every time.
- The bottom all-catalog grid shows every catalog index with metadata
  plus 1Y/3Y/5Y/Since-Inception performance.
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.
