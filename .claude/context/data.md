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
    "Solution": "Beta",
    "Category": "Core Beta",
    "Family": "S&P US Broad",
    "ReturnType": "Total",
    "Currency": "USD",
    "LiveDate": "1957-03-04",
    "Description": "S&P 500 — description pending."
  }
}
```

### The schema is the contract

`CATALOG_SCHEMA` in `src/config.py` (v0.9.15) declares each column once — its
internal snake_case key (`name`, `asset_class`, `family`, `category`,
`solution`, `return_type`, `live_date`, `currency`, `description`), the JSON
keys it accepts, its **display label**, and its role (`tier` / `attribute` /
`date` / `text`). `src/data.py` resolves the feed against that schema and knows
no column name of its own.

Labels are configuration, not code: relabelling a column is a `CATALOG_SCHEMA`
edit and nothing else. Every renderer reads `field_label`, and which fields it
shows comes from a field-key tuple in `config.py` —
`CATALOG_GRID_FIELDS` (the all-catalog table — **without** `return_type` since
#282: near-constant across the catalog, and a column on every row of a browse
grid for it; the field itself stays in the schema, on the profile card and as a
filter pill) / `PERF_GRID_FIELDS` (the shared `PerfGrid`; each tuple is named
for the grid it feeds, #282),
`PROFILE_CARD_FIELDS` (the Single Strategy profile card),
`LAUNCH_CARD_META_FIELDS` (the New-Launch cards' meta line). The filter pills
come from `filter_dimensions()` and the Platform sunburst's rings from
`SUNBURST_LEVELS`. `catalog_field`, `field_label`, `tier_fields`,
`filterable_fields`, `filter_dimensions` and `sunburst_levels` are the
accessors consumers read — nobody indexes the schema tuple by hand, and nobody
respells a label.

### The classification tiers

`CLASSIFICATION_TIERS` is `("solution", "category", "family")` — **top tier →
leaf**, and that order is what every consumer displays. The framework names
these tiers **Class | Category | Family**; the top tier is fed by the feed's
`Solution` column, which is also what `UNIVERSE_SOLUTION_VALUES` filters on, so
the internal key stays `solution`. **A feed that arrives keyed `Class` instead
is one extra alias on that field, not a rename.**

### Old-shape feeds

Each field resolves to the first of its `sources` aliases actually present, so
a stale feed still loads. Two aliases exist today, both for the v0.9.15 re-key:
`IndexFamilyName` → `family` and `Theme` → `category`. Note these two are a
**swap trap**, not a straight rename: the pre-v0.9.15 code called the *family*
`category`, so re-keying the JSON without the internal rename (or either alone)
would transpose two dimensions silently — which is why #210 landed both
atomically. A feed using a legacy alias, or carrying a key the schema does not
know, loads with a warning rather than failing.

### Derived and optional columns

The metadata DataFrame also has a derived `ticker` column = `<key> + " Index"`.
`Currency` and `Description` are metadata (BQL only supplies `px_last`, not
reference fields); `load_metadata` pads any missing schema column with `NA`, so
records without a `Currency` or `Description` key still load. `Description`
(added in v0.9.0) is a free-text per-index blurb surfaced in the Single
Strategy profile card; it is NA-safe when absent.

**Universe membership (v0.8.9):** `build_app` keeps only records whose
`solution` is in `UNIVERSE_SOLUTION_VALUES` (`src/config.py`) — **ARP**,
**Smart Beta**, and **Risk Management** (case-insensitive; plain `Beta` is
excluded) — as `meta_all`, then **prunes indices with no recent price movement**
(stale / delisted / all-NaN over the trailing ~21 trading days, via
`stats.active_columns`) into the displayed `meta`. `meta_all` still drives the
single fetch, so a resumed ticker can re-enter on a later Refresh.

## Data contract — `data/commentary.json` (v0.9.22 #304)

The QIS Bulletin's authored notes: a JSON **list**, one object per note, read by
`load_commentary_notes` (`src/commentary.py`). It replaced the single
`weekly_commentary.html` blob, whose "as of" date came from the app rather than
from the content — so a note written last week was dated today, and there could
only ever be one.

```json
[
  {
    "title": "Rates carry leads the week",
    "date": "2026-09-15",
    "text": "Carry strategies added 1.2%.\n\nMomentum lagged on the reversal."
  }
]
```

- **`text` is plain text, not HTML.** The loader carries it verbatim and the
  renderer (`_render_note_paragraphs`, v0.9.22 #307) escapes it **first** and
  then splits it, so a `<` or an `&` in a note shows as typed. A blank line
  starts a paragraph — a single newline does not, so a wrapped sentence stays
  one paragraph — and that is the whole formatting vocabulary.
- **A note dates itself.** Notes render **newest first** by `date`; two notes on
  one day keep file order (the sort is stable).
- **Unknown keys are ignored**, so a field added later cannot break an older
  build reading a newer file.
- **Nothing here may raise** — the loader runs while the app is being built. A
  **missing file is silent** (a catalog with no commentary yet is an ordinary
  state, and a warning on every build is how a real warning gets tuned out).
  Anything else **warns and degrades**: an unreadable file, invalid JSON or a
  non-list payload yield no notes, and a single malformed note is **skipped by
  its position in the file** rather than voiding the file — one typo in an old
  note must not take today's note off the screen, and the warning names the
  index so it can be found. Same shape as `UserBenchmarkStore.load`, which
  likewise filters bad members out of a good list.

## BQL contract

The BQL request shape, ticker-suffix rules, case-insensitive column
resolution, and wide-form pivot are documented in
**`.claude/skills/bquant-dashboard-spec/SKILL.md` §2** (the platform reference).
Project-specific hooks:

  Both paths live in `src/price_source.py` since v0.9.16 #222 — `BqlPriceSource`
  and `MockPriceSource`, two implementations of the `PriceSource` protocol —
  and `bql_client.fetch_prices` only orchestrates between one of them and a
  `PriceCache`.

- **The request spans `score_history_years()`** — ten years today, derived as
  `LOOKBACK_YEARS + the longest window stat_windows() offers` (v0.9.23 #322,
  widening #311's six). It is longer than the app **analyses** on purpose: both
  boards score a metric against `SCORE_SAMPLE_DAYS` of its own rolling history,
  so the deepest case needs the longest window plus that sample.
  `DashboardApp._analytics_window_start()` is the single boundary, and every
  consumer but the two scorers slices to it. A cost worth knowing before
  widening the window set again: the span is per-ticker rows out of BQL, and
  the first load after a widening fetches the whole extension (later runs pay
  only the delta — see the two-tier cache in `conventions.md`).
- The case-insensitive column resolver is `_pick_column`.
- The mock path is `MockPriceSource.fetch`. If you change the BQL query, update
  it in lockstep so live and mock paths return the same shape.
- **Batched fetch (v0.9.13, #164):** the startup fetch is not one whole-universe
  request — `BqlPriceSource.fetch` issues one BQL request per **batch** of
  `batch_size` tickers (default `BQL_BATCH_SIZE` = 100) via `assemble_batches`,
  so hundreds of
  tickers over a multi-year window don't hit BQL's per-request row / wall-clock
  limits. Each batch is retried with exponential backoff
  (`max_retries` / `backoff_s`, defaulting to `BQL_MAX_RETRIES` /
  `BQL_RETRY_BACKOFF_S`, see `fetch_batch_with_retry`); a
  batch that still fails **degrades to NaN columns** (warned, not fatal) so a few
  unresolvable tickers can't blank the load. Only when *every* batch fails does
  the fetch raise. `_reshape_bql_response` pivots each batch's long-form response
  (casting the ID column to `category` first to shrink the pivot).
