# Architecture & UI layout

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

## Architecture map

| Module                | Owns                                                                   |
| --------------------- | ---------------------------------------------------------------------- |
| `src/config.py`       | Constants: lookback, new-launch window, Sharpe windows, file paths, `UNIVERSE_SOLUTION_VALUES` (in-universe solutions), `REGIME_SPECS`/`REGIME_TICKERS`/`LEVEL_INDICATOR_MOCK`, benchmark/factor tickers. |
| `src/style.py`        | Centralized style tokens: `Color`, `Font`, `FontSize`, `StatusTone`, `Sentiment` enums plus `LINE_PALETTE`. `Color` carries the dark-chrome group (`CHROME_BG`, `SURFACE`, `SURFACE_2`, `BORDER`, `TEXT`, `TEXT_MUTED`, `ACCENT`, `ACCENT_2`, `SCRIM`) and `FontSize.TITLE` (masthead). All inline CSS / `data/templates/` reference these — change hex/font values here, not at call sites. (v0.6.5 moved tab/filter-pill state to the `.bbg-pill.is-active` CSS class, so the old `TabButtonTone` enum was retired.) |
| `src/data.py`         | Loads JSON metadata, filters it, lists unique values for dropdowns.    |
| `src/bql_client.py`   | `fetch_prices(tickers, start, end, use_cache=True) -> (df, source)` — BQL when available, mock otherwise. Two-tier cache (v0.6.9): an in-memory `_MEM_CACHE` checked before a per-trading-day parquet under `data/.cache/prices_{YYYY-MM-DD}.parquet` (TTL `CACHE_TTL_HOURS`) via `_cache_read` / `_cache_write`. Disk writes are best-effort (`_disk_cache_writable` tri-state; warns once and degrades to in-memory on a read-only FS). `_clear_caches()` resets both tiers for tests. |
| `src/stats/`          | Metrics **package** (was a single `stats.py`; split in v0.6.0 G stretch into `_common` / `performance` / `risk` / `rolling` — plus `factors` (v0.7.0) and `regime` (v0.8.5) — with a flat re-exporting `__init__.py`, so `from src.stats import X` / `stats.X` is unchanged). **v0.8.5 `regime`:** `regime_mask` (half-open `[low, high)` indicator-bucket membership, NaN-safe, ±inf open ends), `regime_risk_return` (per-ticker vol/ret/sharpe over the masked days, *mean-based* annualization since regime days are non-contiguous), `rolling_autocorr` (rolling lag-1 return autocorrelation series — drives the Trend regime), `tercile_bounds` (the `(low, high)` of an indicator's low/middle/high third by its 1/3 & 2/3 quantiles — drives the Trend / Rate-level terciles; degenerate → all-days) — the regime-conditioning generalization of `regime_corr_matrix`. (v0.8.7 dropped `regime_correlation` with the Platform Correlation sub-tab.) `daily_returns`, `cum_perf`, `corr_matrix`, `rolling_sharpe`, `sharpe_zscore` (scalar, whole-catalog highlights), `rolling_sharpe_zscore` (time series, selected-set chart), `drawdown_series`, `excess_cum_return` (cumulative excess return vs a benchmark, pp), `corr_matrix`, `regime_corr_matrix` (correlation over a benchmark-return tail, benchmark added to the matrix), `rolling_correlation`, `rolling_beta`, `return_distribution_stats`, `ann_return`, `ann_volatility`, `ann_sharpe`, `calmar_ratio`, `ann_beta` (scalar beta vs a benchmark over a window), `treynor_ratio`, `jensen_alpha` (vs a benchmark, rf=0), `downside_deviation`, `sortino_ratio`, `historical_var` (positive daily VaR loss), `rsi` (Wilder RSI), `zscore_cross_section` (cross-sectional z-score of a per-ticker metric), `quant_metrics_table` (per-ticker Sharpe/Sortino/Calmar/Beta/Treynor/Jensen/VaR/RSI table for the Quantitative filter), `common_window_bounds` (overlap window across columns — max first-valid / min last-valid date — drives the Multi-Strategy date-range box bounds), `active_columns` (columns that moved over the trailing ~21 trading days — drives the v0.8.9 stale-index prune), `perf_table`, `since_inception_perf` (pure util; **unwired from the grid in v0.7.2** but kept + tested), `universe_perf` (1Y / 3Y / 5Y windows only — Since-Inception dropped in v0.7.2). **v0.7.0 Platform additions:** `rolling_return` / `rolling_volatility` / `rolling_sortino` (alongside `rolling_sharpe`), `rolling_metric_zscore` (generalizes `sharpe_zscore` over metric/window/lookback) in `rolling`; and in `factors` — `equity_risk_premium` / `term_premium` (daily factor-return proxies from the fetched factor tickers, return spreads since BQL is `px_last`-only), `trend_returns` (v0.7.1: daily returns of the `TREND_TICKER` — the trend β is taken vs the index's own returns, not a spread), `factor_beta` (thin `ann_beta` wrapper vs a factor-return series), and `platform_sunburst_frame` (per-ticker `asset_class` + `theme` + a single `z` over a selectable metric/window/lookback — default z(1W Sharpe, 1Y); v0.8.x sunburst, replacing the two-metric `platform_treemap_frame`). |
| `src/cache.py`        | `LRUCache` — a tiny bounded LRU (`OrderedDict`-backed, stdlib only) with `get_or_compute(key, fn)` / `clear()`. Leaf module (no project imports). Memoizes the benchmark-dependent chart results (v0.6.9 Workstream B); reusable for future live controls. |
| `src/commentary.py`   | The two whole-catalog Key Highlights builders (v0.8.0, replacing the old mixed `build_highlights`): `build_superlatives(meta, prices, returns, *, window_days)` — one card per superlative = the single most-extreme catalog index over the trailing `window_days` (v0.8.9: **16 cards** — 8 symmetric best/worst pairs, from technical/character indicators: Best/Worst performer (`period_return`), Most trending/mean-reverting (`return_autocorr`), Longest bull/bear run (`longest_up`/`down_streak`), Most extended up/down (`macd_histogram`), Largest drawup/Deepest drawdown (`max_drawup`/`max_drawdown`), Best/Worst risk-adjusted (`ann_sharpe`), Highest/Lowest win rate (`win_rate`), Most positive/negative skew (`return_skew`); v0.8.9 dropped the Most overbought/oversold (`rsi`) and Lowest VaR (`historical_var`) cards. Scale-dependent metrics (performer, MACD, drawup/drawdown, Sharpe) pick the winner by the metric's **asset-class-demeaned z-score** (`asset_class_demeaned_zscore`) — cross-asset-neutral — while the card shows the **raw** value; the `add()` helper takes a `rank_by=` z-series, falling back to the raw metric when the z-rank is degenerate. MACD is fixed-lookback (12-26-9), toggle-independent; the rest re-scope on `window_days`. Each `description` states only how the metric is calculated (hover tooltip); NaN winners skipped, ties broken by ticker) — and `build_launch_cards` — newest-first new-launch cards (`asset_class · theme · currency`, launch date, days-since-launch, simple since-launch return). Both compute from the already-fetched prices, no BQL; the `window_days` lets the Platform-style live toggle re-scope the board. |
| `src/layout/`         | UI **package** (was a single `layout.py`; split in v0.6.0 #4). `__init__.py` re-exports `build_app`, so `from src.layout import build_app` is unchanged. Submodules (see below). |
| `src/layout/__init__.py` | `from .builder import build_app` re-export only — the package's public surface. |
| `src/layout/theme.py` | Chart-theme primitives: `_chart_layout`, `_h_ref` (horizontal ref line), `_v_ref` (vertical ref line, v0.7.0), `_palette_color`, `_short_ticker`, `_sentiment_color`; consts `CHART_HEIGHT`, `_CHART_HEIGHT_PX`, `SHARPE_WINDOW_LABEL`. Leaf module (only `..config`/`..style`). |
| `src/layout/chrome.py` | Page chrome: `_app_css` (mounts the global `app_css.html` stylesheet once), `_banner` (dark masthead, adds `.bbg-masthead`), `_loading_overlay`/`_render_overlay` (the staged loading overlay, v0.6.5), `_status_banner`/`_render_status` (now the post-load `.bbg-toast`), `_make_tab_button`/`_style_tab_button` (pills via the `.bbg-pill`/`is-active` CSS class). HTML via `render_template`. |
| `src/layout/filters.py` | Filter widget factories: `_checkbox_group`, `_section_label`, `_q_row`, `_ticker_options`. |
| `src/layout/panes.py` | `ANALYSIS_OPTIONS`, `_make_benchmark_dropdown`, the 9 chart/grid factories (`_line_chart` … `_return_dist_stats_grid`), and `_make_analysis_pane(side)` — a self-contained pane (own figure set, own benchmark dropdowns, own picker + swap container). Imports `theme`. |
| `src/layout/platform.py` | Platform-tab standalone visuals (v0.7.0, distinct from the Multi-Strategy panes). `_factor_beta_scatter`/`_update_factor_scatter` — the **3D** factor-beta scatter (`go.Scatter3d`: x = β to the equity risk premium, y = β to the term premium, z = β to the trend factor / "Trend Exposure"; one marker per strategy, one trace + legend entry per asset class colored via `_asset_class_colors` — curated `ASSET_CLASS_COLORS` then unused `LINE_PALETTE` for unmapped classes; no in-figure title, per-`scene`-axis zerolines; v0.7.1). v0.8.6 adds three translucent `go.Mesh3d` **zero-reference planes** (x=0/y=0/z=0) via `_zero_planes`/`_quad_mesh`/`_axis_bounds` (sized to the padded data bounds, `Color.CHART_AXIS` at `_ZERO_PLANE_OPACITY`, legend-less + `hoverinfo="skip"`, added before the markers in the same `batch_update`). `_sunburst`/`_update_sunburst` — a 3-level **asset class → theme → ticker** `go.Sunburst` (inside out; arc value = |z| via `_sunburst_leaf_sizes` + `_SUNBURST_SIZE_FLOOR`, so with `branchvalues="total"` each ring's arc is its gross-|z| share of its parent; colored by the metric z averaged up each level — parent color = mean of descendant tickers' z — metric/window user-selected via the builder left-column Z-score controls + the shared lookback (v0.8.8; was a single builder Z-score row), default z(1W Sharpe, 1Y); `label` re-titles the colorbar + the `_SUNBURST_HOVER` `.format()` template, whose `percentParent` shows the arc's % of parent — on a token-driven diverging colorscale + colorbar; `maxdepth=2` so only the asset-class + theme rings show until the user clicks to drill into the ticker ring; no in-figure title, the active tab labels it). Both compute live from the fetched cache (`equity_risk_premium`/`term_premium`/`factor_beta`, `platform_sunburst_frame`), no BQL. **Regime Analysis (v0.8.5, reworked v0.8.7):** `_regime_scatter`/`_update_regime_scatter` — a 2D `go.Scatter` of annualized vol vs return over the regime-bucket days (per asset-class trace, via `regime_risk_return`), taking an optional indicator series + `(low, high)` bucket via the `_regime_window_mask` helper (no indicator/bucket → unconditioned all-days view), `lookback`-windowed, no BQL. The Correlation heatmap was removed (v0.8.7). The section's regime-type / indicator-source / bucket dropdowns + live-render closures (`_regime_indicator` builds the per-mode indicator series; `_resolve_regime_bucket` derives tercile bounds via `tercile_bounds`) live in `builder.py`. Imports `theme` + `..stats` + `..style`. |
| `src/layout/charts.py` | The `_update_*` chart updaters over one shared `_update_line_series` engine. Imports `theme` (+ `..stats`). |
| `src/layout/grids.py` | `_perf_grid`/`_update_perf_grid`, `_universe_grid`/`_update_universe_grid` (thin wrapper over the pure `_build_universe_frame`, which inserts the v0.7.0 `ZSCORE_SUPERCOL` z-score column after the Info block and sorts by it), `_build_info_block`, `_perf_renderers`/`_apply_grid_styling` (both take a `sharpe_heatmap` flag — color-grades the Sharpe + Z-Score columns via `_diverging_bg_renderer`; **both** grids pass it as of v0.7.5, so the selected grid's Sharpe cells are color-graded too — the selected grid has no Z-Score column so that branch no-ops), `_build_perf_column_widths`, `PERF_*` consts, plus the v0.6.5 dark theme `_dark_grid_style`/`_dark_grid_kwargs` (token-driven `grid_style` + bright header/corner/default renderers; both grids `add_class("bbg-grid")`). Imports `theme` + `..style.Color`. |
| `src/layout/html.py` | HTML templating: `render_template(name, /, **ctx)` (substitutes `{{key}}` in `data/templates/<name>.html`, cached read) + the `STYLE_CTX` style-token bundle; loaders/renderers `_load_disclaimer`, `_load_weekly_commentary`, `_render_weekly_commentary`, `_render_highlights(superlatives, launches, *, window_label)` (v0.8.0: two-section — `_render_superlative_cards` + `_render_launch_cards` wrapped in `highlights_two_col`; `_superlative_value_color` remaps neutral to bright chrome text for the dark cards; v0.8.x: cards carry a `description` → `title` hover tooltip and `window_label` titles the board to match the live window toggle), `_render_error` are thin callers. Imports `theme` `_sentiment_color`. |
| `src/layout/builder.py` | `build_app()` — injected `app_css` stylesheet + dark masthead banner + all-catalog commentary + top-level pill-button tab bar (Platform / Multi-Strategy Analysis) + per-tab content + disclaimers + the loading `overlay_w` (last child). The Platform panel's three analytics charts are a boxed **Platform analytics** card (`.bbg-card`) of inner pill-tabs — Sunburst / Regime analysis / Factor exposures. A fixed left column holds the shared `lookback_selector` on top of a swappable `tab_controls_box`; `_activate_platform_tab` swaps that box + the `chart_box` figure per tab (v0.8.8). Builds one `DashboardState` (below) and owns the orchestration closures that read/write it (`_recompute` preps one data slice and renders both panes; `_render_highlights_panel(window_days)` rebuilds the whole-catalog Key Highlights board from the cache at the selected window — called by `_recompute` and the `superlative_window` `1W/1M/3M/6M` ToggleButtons observer, no BQL; `_set_progress` drives the staged overlay through the load, `_render_pane`, `_refresh_prices`, `_on_filter_change`, the clear-filter handlers). Guards a transient `display(overlay_w)` on `get_ipython()` so the overlay shows during the synchronous load. Imports every sibling module. |
| `src/layout/state.py` | `DashboardState` `@dataclass` — the explicit session state `build_app`'s closures share: key widget handles (`ticker_w`, `status_w` (post-load toast), `overlay_w` (loading overlay), the two grids, the two panes, `highlights_w`, `errors_w` (init/pane-error boxes, kept out of `highlights_w` so the live superlatives-window toggle never wipes them; v0.8.x)) plus mutable data (`universe_prices`, `arp_universe_prices`, `init_errors`, `active_filter`, `last_sel_key`, `sync_guard`, and the v0.6.9 live-render slice `cur_prep` / `cur_win_start` / `cur_win_end`, plus the `memo` `LRUCache` for benchmark-dependent results). Replaces the old `nonlocal` + list-as-cell hacks (v0.6.0 #6). |
| `dashboard.ipynb`     | Thin entrypoint that calls `build_app()`.                              |
| `data/templates/` | Component HTML templates rendered by `render_template` (`app_css` — the global `<style>` injected once, carrying the dark-chrome `.bbg-*` classes; `loading_overlay`; banner masthead; status — now the toast; section_label, quant_row_label, the v0.8.0 dark Key-Highlights set `superlative_card` / `launch_card` / `launch_empty` / `highlights_two_col` (replacing the old `highlight_card` / `highlights_wrapper`), error_box, weekly_commentary[_fallback], grid_header). `{{placeholders}}` for both style tokens (from `STYLE_CTX`) and `html.escape`'d dynamic data — **no hardcoded hex/fonts**. |
| `data/performance_disclaimer.html` | Templated disclaimer with `{{start_date}}` / `{{end_date}}` placeholders; rendered immediately below the all-catalog grid. |
| `data/legal_disclosure.html`       | Bulk legal copy, justified, no placeholders; rendered at the bottom of the dashboard. |
| `.claude/context/`                 | Split-out `CLAUDE.md` reference docs — this file plus `style.md`, `run_instructions.md`, `data.md`, `conventions.md`, `code_formatting.md`, `testing_notes.md`. `CLAUDE.md` stays brief and indexes them. |
| `.claude/skills/<name>/SKILL.md`   | Reusable agent skills (folder-per-skill, auto-discovered by Claude Code). Python lifecycle + doc-drafting skills pulled from `RorySullivan1/claude-skills-library`, plus project-authored `ipywidgets` / `plotly` / `bquant-dashboard-spec` skills grounded in this repo's conventions. `bquant-dashboard-spec` is the portable platform reference for the BQL fetch contract + recommended fetch patterns + standard BQuant UI stack — load it first when touching anything that fetches from BQL or designs the dashboard. |
| `.claude/dev_map/`                 | Forward roadmap: `README.md` index + filled-in `vX.Y.Z.md` stubs (`v0.6.0`→`v1.0.0`), each refined as scope firms up, plus a reusable `TEMPLATE.md` stub skeleton new versions copy from. |
| `.claude/hooks/`                   | PreToolUse(Bash) enforcement scripts wired in `.claude/settings.json`: `quality-gates.sh` (blocks `git commit` unless ruff/black/pytest pass) + `block-main-push.sh` (blocks pushes to `main`/`master`). `README.md` documents both and points at the portable templates. |
| `.claude/templates/`               | Portable, repo-agnostic copies of the agent-config layer for lifting into other repos (parameterized `hooks/` + generic `skills/workstream/` + portable `skills/bquant-dashboard-spec/`). Not auto-loaded — the active hooks/skills are the ones under `.claude/hooks/` and `.claude/skills/`. |
| `.meta/VERSION`                    | Canonical current shipped version (`0.8.11`). Keep in sync with the "Branching" section (`conventions.md`) on every bump. |
| `tests/`                           | `pytest` suite: `conftest.py` (deterministic price fixtures), `test_stats.py` (pure `src/stats.py` metric units), `test_state.py` (`DashboardState` defaults/isolation), `test_smoke.py` (end-to-end `build_app()` render guard on mock prices). Run `pytest -q`. |
| `.github/workflows/ci.yml`         | GitHub Actions CI: `ruff check` + `black --check` + `pytest -q` over `src`/`tests` on push/PR to `v0.7.5`. |

## UI layout

The screen layout is: masthead banner → all-catalog commentary
block (always visible; Weekly Commentary, then an error strip, then a
**Superlatives window** `1W/1M/3M/6M` toggle above a **two-section Key
Highlights** panel — left **Market Superlatives** board (v0.8.9: **16 cards** —
8 symmetric best/worst pairs of technical/character indicators (v0.8.9 dropped
the overbought/oversold and Lowest-VaR cards), scale-dependent metrics ranked
**cross-asset-neutrally** by an
asset-class-demeaned z-score while showing the raw value, each with a
calculation-only `description` as a hover tooltip; the window toggle re-renders
the board live from the cache, no BQL), right **New Launches** board; the panel
is **2:1** superlatives:launches; v0.8.x) → **top-level pill-button tab bar**
with two tabs:

- **Platform** — full-width all-catalog performance grid (every index
  with metadata plus 1Y / 3Y / 5Y performance). The
  Sharpe cells are **conditional-formatted** (diverging red→neutral→green),
  and a **dynamic z-score column** sits right after the Info block: a
  **Z-Score ranking** control row above the grid (Metric: Sharpe/Sortino/
  Return/Vol · Window: 1M/3M/6M · Lookback: 1Y/3Y/5Y; default *z(1M Sharpe,
  1Y)*) recomputes that column live from the already-fetched cache (via
  `rolling_metric_zscore`, no BQL) and the grid is **sorted by it**
  descending (v0.7.0 Workstream A). Below the grid, the three analytics charts
  live in one **boxed "Platform analytics" card** (`.bbg-card`, v0.8.8) as
  **inner pill-tabs** the user cycles through — ordered **Sunburst → Regime
  analysis → Factor exposures**. A **left-hand control column** (beside the
  flex-grow chart) holds the **shared 6M / 1Y / 3Y / 5Y lookback** `ToggleButtons`
  **stacked on top** (driving all three tabs), with each tab's own extra
  selection boxes swapped in **below** it (v0.8.8; Factor exposures has none, so
  its column is just the lookback). The **Factor exposures** tab is a **3D factor-beta scatter**:
  per-strategy β to the equity risk premium (x) vs β to the term premium (y) vs
  β to the cross-asset trend factor (z, "Trend Exposure"), colored + legended by
  asset class, over three **translucent zero-reference planes** (x=0/y=0/z=0)
  that mark the origin in every dimension (v0.8.6) — computed live from the
  fetched cache, no BQL (v0.7.0 Workstream C+D; promoted to 3D + de-titled in
  v0.7.1). The **Regime analysis** tab (v0.8.5; reworked v0.8.7) is a
  single **regime-conditioned risk/return scatter** (2D per-strategy annualized
  vol-vs-return, colored by asset class) — the Correlation heatmap was removed
  (correlation stays in the Multi-Strategy tab). Controls are a **regime-type**
  dropdown (Volatility / Trend / Rate-level; v0.8.9 dropped the Risk regime), a
  **conditional indicator-source** dropdown (benchmark for Trend / region for
  Rate-level; hidden otherwise), and a **bucket** dropdown. **Volatility** uses
  fixed VIX-level buckets (`VIX < 15` / `15 ≤ VIX < 25` / `VIX ≥ 25`); **Trend**
  and **Rate-level** split a live-computed indicator into
  **low / middle / high terciles** (1/3 & 2/3 quantiles over the lookback
  window, via `tercile_bounds`): Trend = the selected benchmark's 21-day return
  autocorrelation (`rolling_autocorr`), Rate-level = the selected regional
  risk-free rate level (`FEDL01` / `EONIA` / `MUTKCALM`). The scatter conditions on only the days in
  the selected bucket via `regime_mask` / `regime_risk_return`, computed live
  from the cache — all indicators ride the single startup fetch via
  `REGIME_TICKERS`, no BQL. The **Sunburst** tab is a nested **asset class → theme → ticker**
  sunburst (inside out), driven by a left-column **Metric**
  (Sharpe/Sortino/Return/Vol) + **Window** (1W/1M/3M/6M) Z-score pair plus the
  shared lookback; default **z(1W Sharpe, 1Y)** (v0.8.x, replacing the v0.7–v0.8
  treemap). Each ring's arc is **sized by its
  gross-|z| share** of its parent (leaf arc = |z|, `branchvalues="total"` so an
  asset class = Σ|z| share and a theme = Σ|z| within the class) and **colored by
  the metric z, averaged up each level** (parent color = mean of its descendant
  tickers' z) on a diverging colorscale + colorbar; the colorbar + hover re-title
  to the chosen metric/window, and the hover shows the arc's % of parent.
  `maxdepth=2` shows only the asset-class + theme rings up front — the ticker
  ring appears when the user clicks into an asset class or theme (client-side
  drill-down). All three tabs **re-render live on the shared lookback toggle**
  (the sunburst now shares it too — v0.8.8 dropped its own lookback dropdown);
  the sunburst additionally re-renders on its Metric/Window controls and the
  regime tab on its Type/Source/Bucket dropdowns — all no BQL. Switching tabs is
  a free `.children` swap (the off-tab figures still update in place).
- **Multi-Strategy Analysis** — the whole filter UI lives inside an
  expandable **"Filters"** accordion (expanded by default): a full-width
  filter box split into two side-by-side panels — a **left** strategies
  picker (search box above the `ticker_w` dropdown, which stretches via
  `flex` to match the filter panel's height) and a **right** filter
  panel. The right panel
  has an action row on top — **Refresh prices** (green, via the
  `Color.GREEN_600` token, so the primary action stands out) plus **Clear
  section** (clears the active filter pill's selections, or the date
  range/currency on Characteristics, or the ratio thresholds on
  Quantitative) and **Clear all** (clears every filter checkbox group,
  the launch-date range, the currency, the quant thresholds, and the
  search box; selected tickers are kept) — then a pill header bar (same
  `.bbg-pill` style as the top tabs) whose buttons — Asset Class /
  Category / Theme / Return Type / **Characteristics** /
  **Quantitative** — swap which dimension's value list shows below. The
  first four show checkbox value lists; **Characteristics** shows the
  Launch-date range (two date boxes separated by a hyphen) plus a
  **Currency** dropdown; **Quantitative** filters the universe by
  price-derived ratios — a global Period (1Y/3Y/5Y) dropdown, then one row
  per metric (Sharpe / Sortino / Calmar / Beta / Treynor / Jensen α /
  VaR % / RSI / Z-Score) of
  `[≥ or ≤ dropdown] [value box]`, with an inline parameter dropdown where
  relevant (Beta / Treynor / Jensen each carry their own benchmark
  dropdown, Z-Score its selectable base metric **plus a window dropdown**
  (1W/1M/3M/6M, default 1M; v0.8.11) that sets the lookback the base metric
  is computed over before the cross-sectional z, independent of the Period) — all via
  `quant_metrics_table` / `zscore_cross_section`,
  computed live from the already-fetched prices, no BQL. Below the two
  panels, still inside the Filters accordion, a full-width **"Analysis
  date range"** row holds two hyphen-separated `DatePicker` boxes (the
  `SelectionRangeSlider` was dropped in v0.7.5, leaving just the two boxes,
  min ≤ max linked). Its bounds fit the
  **overlap window of the selected strategies** — `bound_start = max(each
  ticker's first-valid date)`, `bound_end = min(each ticker's last-valid
  date)` via `common_window_bounds` — and the selected sub-range scopes
  the whole selected set (perf grid **and** all pane charts/benchmarks) on
  the next Refresh prices. Below the filter
  box: an
  always-visible selected-strategy performance grid
  (1Y/3Y/5Y per-ticker Return/Vol/Sharpe/Max DD), followed by **two
  side-by-side analysis panes**. Each pane carries its own dropdown
  picker that swaps in any of the 9 analysis types (`Cumulative
  Performance`, `Outperformance`, `1Y Sharpe-z Line`,
  `Correlation Heatmap`, `Risk / Return`, `Drawdown`,
  `Rolling Correlation`, `Return Distribution`, `Rolling Beta`), so
  users can compare any two analyses side-by-side. `Outperformance`,
  Rolling Correlation, and Rolling Beta each carry their own per-pane
  benchmark dropdown that sits on the same row as the analysis picker
  and only appears when the picker is on the relevant analysis.
  (`Outperformance` is the cumulative excess return — strategy minus
  benchmark cumulative % return, in percentage points off a zero
  baseline.) `Correlation Heatmap` additionally carries a per-pane
  **Benchmark** checkbox on that row; ticking it reveals a benchmark
  dropdown and **adds the benchmark as a row/column** to the full-sample matrix
  (v0.8.9), plus a nested **Regime** checkbox; ticking **Regime** reveals a
  **`>` / `<`** tail-direction dropdown (`<` = worst / below-pct tail,
  `>` = best) beside a 0–100% (step 5) tail size, and **additionally** conditions
  the matrix on that benchmark-return regime (the benchmark stays in the matrix)
  (see `regime_corr_matrix`; v0.7.5 restructured these controls, v0.8.9 added the
  benchmark on the Benchmark check).
  Every chart inside a pane renders at the same
  `CHART_HEIGHT` (520px) so the two panes always line up.

Below the tab content: performance disclaimer (templated with the data
window) → bottom legal disclosure (justified).
