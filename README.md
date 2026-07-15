# bbg_quant_dashboard

A Bloomberg BQuant App that lets clients browse an index catalog: filter by
metadata, look up tickers, and view performance, correlation, and a 1-year
rolling Sharpe-ratio z-score over a 5-year lookback. Index metadata is stored
locally in `data/indexdb.json`; time-series prices are pulled from BQL at
runtime (with a deterministic mock-price fallback off-terminal). The UI is built
with `ipywidgets`, `plotly` (`FigureWidget`), and `ipydatagrid`, and is
deployable via Voila.

## Layout

1. **Banner** — logo and title.
2. **Loading overlay** — a full-screen dimmed overlay with a staged progress
   bar covers the dashboard on first load and on every **Refresh prices**, then
   dismisses to a slim, auto-fading post-load toast reporting the source (BQL,
   cache, or mock) and timing. On Refresh the refetch runs on a background
   worker thread so the overlay reliably paints before the fetch blocks.
3. **All-catalog commentary** — automated highlight cards (top/bottom
   performers, Sharpe extremes, recently launched indices), always
   whole-catalog.
4. **Top-level tab bar** with three tabs:
   - **Platform** — a full-width all-catalog performance grid (every index with
     metadata plus 1Y / 3Y / 5Y / Since-Inception performance), above a boxed
     **Platform analytics** card of inner pill-tabs (Sunburst / Regime analysis
     / Factor exposures).
   - **Multi-Strategy** — a "Filters" accordion (strategies picker +
     filter panel: Asset Class / Category / Theme / Return Type /
     Characteristics / Quantitative) and an analysis date-range row (two date
     boxes), above a selected-strategy performance grid and **two side-by-side
     analysis panes**. Each pane swaps among 9 analysis types (Cumulative
     Performance, Outperformance, 1Y Sharpe-z, Correlation Heatmap, Risk/Return,
     Drawdown, Rolling Correlation, Return Distribution, Rolling Beta).
   - **Single Strategy** — a per-strategy deep-dive: a **"Filters" accordion**
     (same dimensions as Multi-Strategy — Asset Class / Category / Theme /
     Return Type / Characteristics / Quantitative) that narrows a single-select
     strategy picker **live** as boxes are toggled (no Refresh-prices button),
     a shared benchmark selector + overlay toggle, a metadata **profile card**
     with a cumulative chart and standard-perf table, a 3-mode monthly-return
     **calendar** (Absolute / Outperformance / Vol-adjusted), and **two
     side-by-side analysis panes** mirroring the Multi-Strategy tab. All views
     compute from the cached prices (no extra BQL call).
5. **Disclaimers** — performance disclaimer (templated with the data window) and
   the bottom legal disclosure.

## Running

**On a BBG terminal (BQuant):** open `dashboard.ipynb` and run the single cell —
`build_app()` returns the rendered VBox.

**Locally** (uses a deterministic mock-price fallback when `bql` is not
available, so the dashboard renders end-to-end without a Bloomberg session):

```
pip install -r requirements.txt
voila dashboard.ipynb
```

## Developing

```
ruff check src tests      # lint
black src tests           # format (88-char)
pytest -q                 # unit + smoke tests
pre-commit install        # optional: run ruff/black on commit, pytest on push
```

## Project structure

```
bbg_quant_dashboard/
├── CLAUDE.md                  # repo memory / architecture notes
├── README.md
├── dashboard.ipynb            # entrypoint — calls src.layout.build_app
├── pyproject.toml             # ruff / black / pytest config (tooling only)
├── requirements.txt
├── .meta/VERSION              # canonical shipped version
├── environment.yml            # conda entrypoint (pins python=3.11; deps via pip)
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml   # ruff + black + pytest on push/PR
├── assets/logo.png            # banner logo (placeholder)
├── data/
│   ├── indexdb.json           # index metadata catalog
│   ├── templates/             # component HTML templates ({{placeholder}})
│   ├── performance_disclaimer.html
│   └── legal_disclosure.html
├── src/
│   ├── config.py              # constants and paths
│   ├── data.py                # metadata loading + filtering
│   ├── bql_client.py          # BQL fetch + off-terminal mock + parquet cache
│   ├── style.py               # centralized style tokens (Color/Font/…)
│   ├── commentary.py          # rule-based highlight cards
│   ├── stats/                 # metrics package: _common / performance / risk /
│   │                          #   rolling / factors / regime / calendar
│   └── layout/                # UI package: builder + theme/chrome/filters/panes/
│                              #   platform/filter_panel/single_strategy/charts/grids/html/state
│                              #   (build_app re-exported)
└── tests/                     # pytest suite (unit + smoke): conftest + stats/data/
                               #   cache/commentary/grids/platform/single_strategy/
                               #   live-controls/lazy-views/state/smoke tests
```

See `CLAUDE.md` for the data contract, BQL query shape, architecture map, and
conventions.
