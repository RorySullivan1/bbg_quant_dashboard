# bbg_quant_dashboard

A Bloomberg BQuant App that lets clients explore an index catalog: filter by
metadata, look up tickers, and review performance, correlation, and a rolling
Sharpe-ratio z-score over a 3-year window.

## Layout

1. **Banner** — logo and title.
2. **Filters (30%) + cumulative performance chart (70%)**.
3. **Correlation heatmap (50%) + Sharpe-ratio z-score bar chart (50%)**.
4. **Commentary** — automated bullets on top/bottom performers, weekly moves,
   Sharpe extremes, correlation extremes, and recently launched indices.

## Running

**On a BBG terminal (BQuant):** open `dashboard.ipynb` and run the cell.

**Locally (uses a deterministic mock-price fallback when `bql` is not
available):**

```
pip install -r requirements.txt
voila dashboard.ipynb
```

## Project structure

```
bbg_quant_dashboard/
├── CLAUDE.md            # repo memory / architecture notes
├── dashboard.ipynb      # entrypoint — calls src.layout.build_app
├── data/indices.json    # metadata catalog
├── assets/logo.png      # banner logo (placeholder)
├── requirements.txt
└── src/
    ├── config.py        # constants and paths
    ├── data.py          # metadata loading + filtering
    ├── bql_client.py    # BQL fetch + off-terminal mock
    ├── stats.py         # returns, correlation, rolling Sharpe, z-score
    ├── commentary.py    # rule-based commentary bullets
    └── layout.py        # widget tree + recompute wiring
```

See `CLAUDE.md` for the data contract, BQL query shape, and conventions.
Fix launch date parsing
