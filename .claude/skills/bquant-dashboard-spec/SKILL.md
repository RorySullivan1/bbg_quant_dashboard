---
name: bquant-dashboard-spec
description: Portable reference for building Bloomberg BQuant Apps / dashboards — the BQL fetch contract (single-call request shape, ticker suffix normalization, case-insensitive response handling, wide-form pivot), recommended fetch patterns (one-call-per-session, two-tier price cache, off-terminal mock fallback, benchmark / factor ride-along, Refresh-prices control), and the standard BQuant UI stack (single-cell notebook → `build_app()`, `ipywidgets` + plotly `FigureWidget` + `ipydatagrid`, Voila deploy). Use whenever building, designing, debugging, or modifying any BQuant App / dashboard, or anything that touches how / when / what the app fetches from BQL. Trigger on BQuant, BQuant App, BQL, bql.Service, bql.Request, px_last, fetch_prices, bql_client, ticker suffix, " Index" / " Equity", Voila, FigureWidget, ipydatagrid, dashboard, benchmarks, FACTOR_TICKERS, BENCHMARK_TICKERS, mock prices, two-tier cache, parquet cache, Refresh prices.
---

# bquant-dashboard-spec — BQuant App platform reference

A portable reference for building **any** Bloomberg BQuant App. It covers
the BQL fetch contract, recommended fetch / caching patterns, the
off-terminal mock-fallback strategy, and the standard BQuant UI stack.

> **Project-specific layout, theming, and conventions belong in the host
> repo's `CLAUDE.md`, not here.** This skill is the platform; the host repo
> describes the product.

---

## 1. What a BQuant App is

A Bloomberg BQuant App is a Jupyter notebook (typically a single cell that
returns a rendered widget tree) that must run in two environments:

- **On a Bloomberg terminal (BQuant)** — the `bql` package is importable,
  prices come from the live BQL service.
- **Off-terminal (local dev / Voila)** — `bql` is *not* importable, prices
  come from a mock fallback. The dashboard renders end-to-end either way.

The standard stack:

- `ipywidgets` for the UI tree.
- `plotly` via `FigureWidget` for interactive charts.
- `ipydatagrid` for tables.
- Voila for off-terminal deploy / preview.

The notebook should be **one cell** that calls a `build_app()` function
from `src/`. All compute lives in `src/`; the notebook stays a thin
entrypoint so the same code is importable under Voila, pytest, and the
BQuant cell.

---

## 2. The BQL fetch contract

### 2.1 The typical price-only request

```python
import bql

bq = bql.Service()
px = bq.data.px_last(
    dates=bq.func.range(start.isoformat(), end.isoformat()),
    fill="prev",
)
request = bql.Request(tickers, {"px_last": px})
response = bq.execute(request)
```

### 2.2 Rules to follow

- **Tickers must include the security-type suffix** (e.g. `" Index"` for
  indices, `" Equity"` for equities). Most BQuant apps store the
  un-suffixed ticker in metadata and append the suffix immediately before
  the BQL call.
- **Resolve response columns case-insensitively**. The BQL response
  DataFrame's ID / DATE / value column names vary across BQL versions —
  look them up with a case-insensitive helper, then pivot to wide form
  (`date` index, one column per ticker).
- **Missing tickers should produce all-NaN columns, not raise.** A
  delisted or wrong ticker should let the rest of the dashboard render.
- **BQL only returns the fields you query.** `px_last` does *not* bring
  metadata (currency, asset class, sector, etc.). Store that in a
  metadata sidecar (JSON, CSV) and merge in Python.
- **Single-row vs multi-row responses.** When you request a single date
  or a single ticker, BQL may collapse the response. Handle both shapes
  in the parser.

### 2.3 Mock fallback must mirror the live shape

When you extend the query (add fields, change frequency, add custom
calculations), update the mock-fallback path in **lockstep**. Both paths
must return identically-shaped DataFrames so the rest of the app has one
code path.

---

## 3. Recommended fetch patterns

### 3.1 One BQL call per session

Issue **a single `fetch_prices(tickers, start, end)` call at app build
time** covering every ticker the dashboard will ever need — universe +
benchmarks + factors — deduped and order-preserving. Cache the result in
a closure / session-state variable; every visualization slices from that
cache.

Why: BQL calls are expensive (latency + quota). One call per session
amortizes the cost across every chart, grid, and live control.

Anti-pattern: fetching inside chart callbacks, on filter changes, or on
benchmark / regime / lookback dropdown changes. Those are slice-and-recompute
operations, not fetches.

### 3.2 Two-tier price cache

Front `fetch_prices` with two layers:

1. **In-memory session cache** — a dict keyed by
   `(tuple(sorted(tickers)), start, end)`. Checked first; cleared at
   process exit.
2. **On-disk trading-day cache** — a parquet file under e.g.
   `data/.cache/prices_{YYYY-MM-DD}.parquet`. Checked after the
   in-memory miss; written on the first successful fetch of the day.

A request misses both layers and falls through to BQL when:
- The TTL is stale (configurable; e.g. `CACHE_TTL_HOURS`).
- The file is missing or corrupt.
- The cache doesn't cover every requested ticker.

**Disk writes must be best-effort.** Locked-down BQuant environments
frequently expose a read-only filesystem. On any write failure: warn
once, set a `_disk_cache_writable = False` flag, and let the in-memory
layer carry the session. The app must never crash on a read-only FS.

Gitignore the cache directory.

### 3.3 Off-terminal mock fallback

`bql_client.py` should detect whether `bql` is importable. Off-terminal,
fall back to a **deterministic synthetic price series keyed by ticker**
(e.g. a seeded random walk per ticker hash) that:

- Returns the **same shape** as the live BQL path (`date` index, one
  column per ticker, wide form).
- Produces the **same series every run** for the same ticker, so
  off-terminal development is reproducible (tests, screenshots, etc.).
- Spans the requested `[start, end]` window.

This means the full dashboard renders, all charts populate, all
selection/filtering works — off-terminal devs never need a BBG terminal
to work on the UI.

### 3.4 Refresh prices control

Expose a **Refresh prices** button (or equivalent) that re-fetches from
BQL with `use_cache=False`, overwrites the parquet, then recomputes
everything.

Filter-only re-slices should be a *separate* control (or have no control
at all — re-slice live) so users don't pay a BQL round-trip for narrowing
the ticker universe.

### 3.5 Benchmarks and factors ride the single fetch

Benchmarks (e.g. an equity index for relative-perf charts) and factor
tickers (e.g. equity-risk-premium / term-premium / trend proxies) ride
along the **same single fetch** as the universe — *no second BQL call*.

When rendering universe-only views (e.g. an all-catalog grid), scope the
benchmark/factor columns out via:

```python
universe_prices.reindex(columns=universe_tickers)
```

When rendering benchmark-comparison views (rolling correlation, rolling
beta, outperformance, regime-conditioned matrices), access the full
price frame directly.

Constants like `BENCHMARK_TICKERS` and `FACTOR_TICKERS` belong in
`src/config.py`, not inline.

### 3.6 Live controls slice, never fetch

Once `universe_prices` is in hand, every interactive control — benchmark
dropdown, regime tail size, lookback toggle, ticker dropdown, date-range
box — should **re-slice the cache** (and re-render the chart) without
hitting BQL. The only paths that touch BQL are app build and the explicit
Refresh prices button.

A common optimization: memoize benchmark-dependent results (rolling
correlation, rolling beta, regime matrices) on a per-slice basis so
flipping back to a previously-viewed benchmark is a cache hit.

---

## 4. UI stack conventions

### 4.1 Charts via `FigureWidget`

Use plotly `FigureWidget` (not plain `Figure`) so charts can be mutated
in-place from observer callbacks. Wrap mutations in `fig.batch_update()`
so the frontend sees a single atomic frame:

```python
with fig.batch_update():
    fig.data = ()
    fig.add_traces(new_traces)
    fig.layout.title.text = f"{ticker} since {start}"
```

`fig.data = ()` is required to fully clear traces — plotly's `fig.data`
setter only accepts a subset of the existing traces, so direct
replacement otherwise raises.

### 4.2 Grids via `ipydatagrid`

`ipydatagrid` is the standard table widget for BQuant dashboards. It
supports:

- Custom cell renderers (`TextRenderer`, `BarRenderer`).
- `VegaExpr`-driven conditional formatting (color heatmaps, bars,
  thresholds).
- MultiIndex columns for two-level headers (`("Info", "Name")`,
  `("1Y", "Return")`, …). Custom per-column widths require the
  `"<level0>,<level1>"` comma-joined key form.

### 4.3 Off-terminal deploy via Voila

```
pip install -r requirements.txt
voila dashboard.ipynb
```

Voila renders the notebook as a stateful web app. The same `build_app()`
that runs in BQuant runs under Voila — guard any BQuant-specific code
paths on **`bql` importability**, not on a runtime env flag.

---

## 5. Suggested project layout

A typical BQuant App repo:

```
project/
├── dashboard.ipynb         # one-cell notebook that calls build_app()
├── src/
│   ├── config.py           # constants: lookback, TTL, BENCHMARK_TICKERS, FACTOR_TICKERS, paths
│   ├── data.py             # metadata load + filter helpers
│   ├── bql_client.py       # fetch_prices + mock fallback + two-tier cache
│   ├── stats/              # pure compute (returns, vol, sharpe, drawdown, beta, ...)
│   └── layout/             # UI: build_app + chart factories + grid factories + state
├── data/
│   ├── <metadata>.json     # the index / security catalog
│   ├── templates/          # HTML snippets rendered into the UI
│   └── .cache/             # gitignored parquet cache
└── tests/                  # pytest; smoke test that build_app() renders on mock prices
```

Module names will vary across repos; the **responsibilities** are the
constants. When dropping into a new BQuant App, these are the load-bearing
entry points:

| Concern | Typical module |
|---|---|
| Single-cell entrypoint | `dashboard.ipynb` |
| Universe / benchmark / factor constants | `src/config.py` |
| BQL fetch + mock fallback + cache | `src/bql_client.py` |
| Single-fetch orchestration + Refresh wiring | `src/layout/builder.py` (or equivalent) |
| Per-chart factories and updaters | `src/layout/charts.py`, `panes.py`, etc. |

---

## 6. Checklist for a new BQuant dashboard

Use this as a sanity pass when starting a new app or reviewing an existing
one:

- [ ] Notebook is a single cell that calls `build_app()`.
- [ ] All compute lives in `src/`; no business logic in the notebook.
- [ ] **Exactly one BQL call** at app build time covers universe +
  benchmarks + factors.
- [ ] In-memory cache fronts an on-disk per-trading-day parquet cache.
- [ ] Disk write is best-effort; the app survives a read-only FS.
- [ ] Off-terminal path returns the **same shape** as the live BQL path,
  deterministically per ticker.
- [ ] Tickers carry their security-type suffix (`" Index"` / `" Equity"`)
  before any BQL call.
- [ ] Response columns are resolved case-insensitively; missing tickers
  surface as all-NaN, not exceptions.
- [ ] **Refresh prices** is the only UI control that re-hits BQL.
- [ ] Live controls (benchmark, regime, lookback, filters) re-slice the
  cache; they do not fetch.
- [ ] Benchmark / factor columns are `reindex`-scoped out of
  universe-only views.
- [ ] Charts use `FigureWidget` + `fig.batch_update()`.
- [ ] Tables use `ipydatagrid` with explicit renderers.
- [ ] Cache directory is gitignored.
- [ ] A pytest smoke test renders `build_app()` end-to-end on the mock
  path.
