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
    "LiveDate": "1957-03-04",
    "Description": "S&P 500 — description pending."
  }
}
```

`CATALOG_SCHEMA` in `src/config.py` (v0.9.15) declares each column once — its
internal snake_case key (`name`, `asset_class`, `category`, `theme`,
`solution`, `return_type`, `live_date`, `currency`, `description`), the JSON
keys it accepts, its display label, and its role (`tier` / `attribute` /
`date` / `text`). `src/data.py` resolves the feed against that schema and knows
no column name of its own; `field_label`, `tier_fields` and
`filterable_fields` are the accessors consumers read. `IndexFamilyName` maps to
the internal `category` field — there is no separate "family" dimension yet
(#210 renames the tiers). The metadata DataFrame also has a derived `ticker`
column = `<key> + " Index"`. `Currency` and `Description` are metadata (BQL
only supplies `px_last`, not reference fields); `load_metadata` pads any
missing schema column with `NA`, so records without a `Currency` or
`Description` key still load. A feed using a legacy alias, or carrying a key
the schema does not know, loads with a warning rather than failing.
`Description` (added in v0.9.0) is a free-text per-index blurb surfaced in the
Single Strategy profile card; it is NA-safe when absent.

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
- **Batched fetch (v0.9.13, #164):** the startup fetch is not one whole-universe
  request — `_fetch_via_bql` issues one BQL request per **batch** of
  `BQL_BATCH_SIZE` tickers (default 100) via `_assemble_batches`, so hundreds of
  tickers over a multi-year window don't hit BQL's per-request row / wall-clock
  limits. Each batch is retried with exponential backoff
  (`BQL_MAX_RETRIES` / `BQL_RETRY_BACKOFF_S`, see `_fetch_batch_with_retry`); a
  batch that still fails **degrades to NaN columns** (warned, not fatal) so a few
  unresolvable tickers can't blank the load. Only when *every* batch fails does
  the fetch raise. `_reshape_bql_response` pivots each batch's long-form response
  (casting the ID column to `category` first to shrink the pivot).
