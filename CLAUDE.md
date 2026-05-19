# CLAUDE.md — bbg_quant_dashboard

Repo memory for future Claude sessions. Read this before editing.

## Project purpose

A Bloomberg BQuant App that lets clients browse an index catalog: filter by
metadata, look up tickers, and view performance, correlation, and a 1-year
rolling Sharpe-ratio z-score over a 5-year lookback. Metadata is stored
locally in `data/indexdb.json`; time-series prices are pulled from BQL at
runtime. The UI is built with `ipywidgets`, `bqplot`, and `ipydatagrid`, and
is deployable via Voila.

The screen layout is: banner → commentary block → 30/70 row (filters + line
chart with performance datagrid underneath) → 50/50 row (correlation heatmap
+ Sharpe z-score bar chart).

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
| `src/stats.py`        | `daily_returns`, `cum_perf`, `corr_matrix`, `rolling_sharpe`, `sharpe_zscore`, `perf_table` (1/3/5Y return, vol, Sharpe, max DD). |
| `src/commentary.py`   | `build_commentary` — rule-based bullets + recent-launch callout.       |
| `src/layout.py`       | `build_app()` — banner + commentary + 30/70 row (checkbox filters + searchable ticker box + line chart + perf grid) + 50/50 row (heatmap + bar chart). |
| `dashboard.ipynb`     | Thin entrypoint that calls `build_app()`.                              |

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

- **Recompute only on "Apply"**. Metadata checkbox groups, the ticker search
  box, and the date pickers all only narrow the ticker dropdown; they do not
  fetch prices. Only the Apply button calls BQL.
- **All compute lives in `src/`**; the notebook stays a one-liner.
- **Stats are over the currently selected tickers** (the multi-select), not
  the full filter set.
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
- Ticking a checkbox under any filter group — the ticker dropdown shrinks to
  the intersection.
- Typing in the ticker search box — the dropdown narrows to substring
  matches on ticker or name; already-selected tickers stay visible.
- Clicking Apply with 2+ tickers — line chart, perf grid, heatmap, bar
  chart, and commentary should all refresh together; the line chart's
  y-axis should rescale to the new data range.
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.
