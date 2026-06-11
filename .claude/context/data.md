# Data & BQL contracts

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

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

**Universe membership (v0.8.9):** `build_app` keeps only records whose
`solution` is in `UNIVERSE_SOLUTION_VALUES` (`src/config.py`) — **ARP**,
**Smart Beta**, and **Risk Management** (case-insensitive; plain `Beta` is
excluded) — as `meta_all`, then **prunes indices with no recent price movement**
(stale / delisted / all-NaN over the trailing ~21 trading days, via
`stats.active_columns`) into the displayed `meta`. `meta_all` still drives the
single fetch, so a resumed ticker can re-enter on a later Refresh.

## BQL contract

The BQL request shape, ticker-suffix rules, case-insensitive column
resolution, and wide-form pivot are documented in
**`.claude/skills/bquant-dashboard-spec/SKILL.md` §2** (the platform reference).
Project-specific hooks:

- `src/bql_client.py`'s case-insensitive column resolver is `_pick_column`.
- The mock path is `_mock_prices`. If you change the BQL query, update
  `_mock_prices` in lockstep so live and mock paths return the same shape.
