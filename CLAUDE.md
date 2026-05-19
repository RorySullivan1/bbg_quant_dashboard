# CLAUDE.md — bbg_quant_dashboard

Repo memory for future Claude sessions. Read this before editing.

## Project purpose

A Bloomberg BQuant App that lets clients browse an index catalog: filter by
metadata, look up tickers, and view performance, correlation, and a rolling
Sharpe-ratio z-score over a 3-year lookback. Metadata is stored locally in
`data/indices.json`; time-series prices are pulled from BQL at runtime. The UI
is built with `ipywidgets` + `bqplot` and is deployable via Voila.

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
| `src/stats.py`        | `daily_returns`, `cum_perf`, `corr_matrix`, `rolling_sharpe`, `sharpe_zscore`. |
| `src/commentary.py`   | `build_commentary` — rule-based bullets + recent-launch callout.       |
| `src/layout.py`       | `build_app()` — banner + 30/70 row + 50/50 row + commentary block.     |
| `dashboard.ipynb`     | Thin entrypoint that calls `build_app()`.                              |

## Data contract — `data/indices.json`

List of objects with these fields. All required, `live_date` is ISO-8601.

```json
{
  "ticker": "SPX Index",
  "name": "S&P 500",
  "asset_class": "Equity",
  "category": "Broad Market",
  "family": "S&P",
  "theme": "Core Beta",
  "live_date": "1957-03-04"
}
```

`ticker` is the BQL identifier. `name` is the human-readable label shown in
the dropdown and commentary.

## BQL contract

`src/bql_client.py` issues a single BQL request:

```python
bq = bql.Service()
px = bq.data.px_last(
    dates=bq.func.range(start, end),
    fill="prev",
)
request = bql.Request(tickers, {"px_last": px})
```

The response is pivoted into a wide DataFrame (`date` index, one column per
ticker). If you change this query, also update `_mock_prices` so the mock and
live paths return the same shape.

## Conventions

- **Recompute only on "Apply"**. Metadata filter widgets just narrow the
  ticker dropdown; they do not fetch prices. Only the Apply button calls BQL.
- **All compute lives in `src/`**; the notebook stays a one-liner.
- **Stats are over the currently selected tickers** (the multi-select), not
  the full filter set.
- **Lookback is fixed** at `LOOKBACK_YEARS` in `src/config.py`. There's no UI
  date picker for the chart range.
- **New top-level files require updating the architecture map above.**

## Testing notes

Off-terminal, the mock-price fallback is deterministic per ticker, so:

```python
from src.layout import build_app
build_app()
```

renders the full dashboard without a Bloomberg session. Verify by:
- Toggling the metadata `SelectMultiple` widgets — the ticker dropdown should
  shrink to the intersection.
- Clicking Apply with 2+ tickers — line chart, heatmap, bar chart, and
  commentary should all refresh together.
- The "Recently launched" bullet should fire for any index whose `live_date`
  is within `NEW_LAUNCH_DAYS` of today.
