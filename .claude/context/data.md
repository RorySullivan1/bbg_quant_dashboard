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
come from `filter_dimensions()` and the Platform analytics' levels from
`ANALYTICS_LEVELS`. `catalog_field`, `field_label`, `tier_fields`,
`filterable_fields`, `filter_dimensions`, `analytics_levels` and `drill_levels` are the
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


## The analytics hierarchy and the drill (v0.9.24, epic #331)

`ANALYTICS_LEVELS` is the one tree the Platform card draws: the Icicle's
levels, what the Scatter and the Strip aggregate over, and what the drill
walks. `drill_levels()` is that tree plus the ticker leaf, whose label lives
in `DRILL_LEAF_LABEL` because `ticker` is derived from the catalog's keys and
is not a schema field `field_label` could name.

**`solution` leads the hierarchy** (v0.9.25). Epic #331 shipped without it and
called a solution stop a non-goal; the desk's reading is the other way — the
catalog is browsed *by solution first*, so that is where a drill should start.
The measurement recorded when it was left out is what made the change safe:
**no category in the shipped catalog spans more than one solution**, so
inserting the level only nests and cannot break the row contiguity RowGroup
needs.

With that, **every level is a stop** and `drill_levels()` is derived from
`ANALYTICS_LEVELS` rather than declared beside it. The separate `DRILL_LEVELS`
tuple existed to be a suffix *after* the first element, because the first
level served as the root's colour key rather than somewhere to stand — the
root drew categories and coloured them by asset class. The root draws
solutions now, so that special case is gone from `next_stop` and `color_key`
alike, and a second tuple could only disagree with this one.

One data wart this makes prominent: `Solution` carries both `"ARP"` and
`"Alternative Risk Premia"` — two labels for one concept. Since v0.9.27 they
are two *chips* in the card's Solution filter rather than two sibling cells at
the root, which makes the duplication more prominent still: the user is asked
to choose between them. It is a fix in `indexdb.json`, not in code.

**The card bases the drill at one solution** (v0.9.27). The schema is
unchanged — `solution` still leads the hierarchy and `drill_levels()` still
starts there — but `PlatformAnalytics` treats that first level as the
universe **filter**: chips pick one solution, the scope is based at
`(solution,)`, and the Level chips offer `drill_levels()[1:]`. That is a
layout decision about how the card is browsed, not a statement about the tree,
which is why it lives in `src/layout/platform.py` and not here. `stats.drill`
and `icicle_frame` still work over whatever frame they are handed — the card
hands them one solution's rows.

**A node is a path, never a bare label.** *Emerging Markets* sits under two
asset classes in the shipped catalog and *S&P US Sector* under two categories,
so a label alone would merge two unrelated groups into one point and average
across them. `stats.drill.node_paths` gives every ticker a full path, bucketing
a missing level as `"Other"` so a path is never ragged — which is what lets
`drill_points` group on a fixed-width prefix.

One thing the shipped catalog **cannot** test: grouped to family it yields 18
nodes for 18 tickers, so every family is a singleton and a "mean" there is a
mean of one. The drill's aggregation tests therefore use synthetic fixtures,
and a test fails the day a family grows a second member — so the day the real
data can carry those tests is noticed rather than missed.

`STRIP_DAYS` (5) is read by the Strip's stats function, its chart and its
column header rather than typed at three sites.

## The quant columns' naming (v0.9.29, #345)

The Multi-Strategy tab's nine `≥ / ≤` thresholds became **columns** of the
selection table. **Four** survive — Sortino · Calmar · Beta · Treynor (VaR,
RSI and Jensen α were dropped in v0.9.30: seven metrics across four windows is
28 columns, and those three are the ones a reader narrows by least) — each
named **`"{window} {metric}"`**, exactly as the
performance columns are (`"1Y Sharpe"`).

That is not cosmetic. Four behaviours key off the `"<window> "` prefix and the
metric suffix, and naming the columns this way buys all four with no new
branches anywhere: `_window_of` puts them under the Window chip (so switching
windows hides them rather than recomputing), `_is_stat_col` gives them a
**comparison** filter instead of a substring one, `_is_percent_col` has nothing to do for them
(the two stored as fractions, VaR and Jensen α, are the ones that were
dropped), and the numeric renderer formats them.

**Two units bugs lived here and both were silent** (v0.9.30). `stat_windows()`
yields `(label, years)` — `0.5, 1, 3, 5` — and the column builder divided by
`TRADING_DAYS_PER_YEAR` as though they were days, so `1Y` asked for a
**single day**: the short windows rendered N/A and the long ones returned
numbers measured over three days. And `ann_beta` covaries its returns frame
against whatever it is handed, while every quant caller held benchmark
**prices**; `cov(returns, index levels) / var(index levels)` put every Beta
near zero, Treynor (return / beta) in the thousands and Jensen at the asset's
own return. `stats.risk.benchmark_returns` is the conversion, and `factor_beta`
is the one caller that already held returns and does not need it.

Two deliberate absences. **Vol** is not here and not rankable on the Platform
tab either: the ramp and the sort both say *higher is better*, which volatility
is not. And the cross-sectional **Z threshold** is gone outright — a z-score is
a ranking, and the Platform tab's ranking column is where a ranking belongs.
`QuantFilter` keeps both for Single Strategy, where nothing claims a direction.
