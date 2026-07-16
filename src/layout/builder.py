from __future__ import annotations

import threading
import time
import traceback
from datetime import date
from types import SimpleNamespace

import ipywidgets as W
import pandas as pd
from IPython import get_ipython
from IPython.display import display

from ..bql_client import _cache_path, fetch_prices
from ..commentary import build_launch_cards, build_superlatives, superlative_returns
from ..config import (
    BENCHMARK_TICKERS,
    FACTOR_TICKERS,
    HALF_YEAR_WINDOW,
    LEGAL_DISCLOSURE_PATH,
    LOOKBACK_YEARS,
    MONTH_WINDOW,
    PERFORMANCE_DISCLAIMER_PATH,
    QUARTER_WINDOW,
    REGIME_SPECS,
    REGIME_TICKERS,
    SHORT_WINDOW_OPTIONS,
    SUPERLATIVE_WINDOW_DAYS,
    TRADING_DAYS_PER_YEAR,
    UNIVERSE_SOLUTION_VALUES,
    WEEK_WINDOW,
    WINDOW_LABELS,
)
from ..data import load_metadata
from ..stats import (
    active_columns,
    common_window_bounds,
    corr_matrix,
    cum_perf,
    daily_returns,
    drawdown_series,
    perf_table,
    return_distribution_stats,
    rolling_metric_zscore,
    rolling_sharpe_zscore,
    universe_perf,
)
from ..style import (
    Color,
    StatusTone,
)
from .chrome import (
    _app_css,
    _banner,
    _loading_overlay,
    _make_tab_button,
    _render_overlay,
    _render_status,
    _status_banner,
    _style_tab_button,
)
from .filter_panel import make_filter_panel
from .filters import (
    CheckboxMultiSelect,
    _section_label,
    _ticker_options,
)
from .grids import (
    _perf_grid,
    _universe_grid,
    _update_perf_grid,
)
from .html import (
    STYLE_CTX,
    _load_disclaimer,
    _load_weekly_commentary,
    _render_error,
    _render_highlights,
    _render_weekly_commentary,
    render_template,
)
from .multi_strategy import (
    bind_lazy_render,
    bind_live_controls,
    clear_pane,
    render_pane,
)
from .panes import _make_analysis_pane
from .platform import (
    _factor_beta_scatter,
    _regime_scatter,
    _sunburst,
    regime_bucket_options,
    render_factor_scatter,
    render_regime_scatter,
    render_sunburst,
    render_universe_grid,
    wire_platform_analytics,
)
from .single_strategy import (
    _CALENDAR_TABS,
    make_single_strategy_panel,
    render_analysis_pane,
    render_calendar,
    render_single_strategy,
    set_calendar_kind,
)
from .state import DashboardState

# Minimum time the Refresh overlay is held visible before the worker thread
# runs the (possibly instant) refetch and flips it hidden. The click handler
# shows the overlay and returns; without this beat, an instant refetch — the
# off-terminal mock path, or a warm cache — hides it again inside the same
# animation frame, so the frontend coalesces show→hide and the overlay never
# paints. A background-thread sleep doesn't block the kernel, so the frontend
# is free to paint the visible overlay during it. (v0.9.0 refresh-overlay fix.)
_OVERLAY_PAINT_DELAY_S = 0.35


def build_app(verbose: bool = False) -> W.VBox:
    t0 = time.perf_counter()

    def _log(msg: str) -> None:
        if verbose:
            print(f"[{time.perf_counter() - t0:6.2f}s] {msg}", flush=True)

    # Loading overlay (v0.6.5 Workstream C). `build_app` is synchronous, so we
    # display() the overlay first and push staged progress as each load step
    # completes, then mount the dashboard (which also contains `overlay_w`) and
    # dismiss it. On the initial load this shows because display() mounts a
    # *new* overlay view that is born visible and painted before the long
    # synchronous build runs. Refresh has no such fresh mount, so it offloads
    # its blocking work to a worker thread instead (see `_refresh_prices`) — the
    # background-thread load the original caveat here flagged as the real fix.
    overlay_w = _loading_overlay()

    def _set_progress(
        pct: int, label: str, *, error: bool = False, hidden: bool = False
    ) -> None:
        overlay_w.value = _render_overlay(pct, label, error=error, hidden=hidden)

    if get_ipython() is not None:
        display(overlay_w)
    _set_progress(0, "Initializing…")

    # `meta_all` is the full in-universe catalog (by solution); the displayed
    # `meta` is later narrowed to indices with recent price movement (post-fetch,
    # via `_prune_stale`). `meta_all` drives the fetch so a ticker that resumes
    # trading can be re-admitted on a later Refresh.
    meta_all = load_metadata()
    meta_all = meta_all[
        meta_all["solution"].astype(str).str.lower().isin(UNIVERSE_SOLUTION_VALUES)
    ].reset_index(drop=True)
    meta = meta_all
    _log(f"loaded metadata: {len(meta)} tickers")
    _set_progress(25, f"Loaded {len(meta)} indices")

    search_w = W.Text(
        placeholder="Search ticker or name…",
        layout=W.Layout(flex="1 1 auto"),
    )
    # A "Clear" button to the right of the search box wipes the strategy
    # *selection* (distinct from "Clear all", which resets the filters/search
    # but deliberately keeps the picked strategies).
    clear_sel_btn = W.Button(
        description="Clear",
        tooltip="Clear the strategy selection",
        layout=W.Layout(width="auto", margin="0 0 0 6px"),
    )
    clear_sel_btn.add_class("bbg-btn-secondary")
    search_row = W.HBox([search_w, clear_sel_btn], layout=W.Layout(width="100%"))
    # The picker is a scrollable checkbox list (CheckboxMultiSelect), capped at
    # the same 240px as the categorical filter groups on the right
    # (`_checkbox_group`) so the two panels match; longer catalogs scroll inside
    # the box (`overflow="auto"`) rather than growing to fill the panel.
    ticker_w = CheckboxMultiSelect(
        options=_ticker_options(meta),
        value=tuple(meta["ticker"].head(5)),
        layout=W.Layout(width="100%", max_height="240px", overflow="auto"),
    )
    clear_sel_btn.on_click(lambda _b: setattr(ticker_w, "value", ()))

    # Analysis date range — a slider flanked by two date boxes, two-way
    # linked. Its bounds are rebuilt at recompute time to the overlap window
    # of the selected strategies; the selected sub-range scopes the
    # selected-set charts and perf grid (re-slice only, no BQL).
    # `state.sync_guard` suppresses the bidirectional observers during
    # programmatic updates.
    range_min_box = W.DatePicker(layout=W.Layout(width="160px"))
    range_max_box = W.DatePicker(layout=W.Layout(width="160px"))
    # `state.sync_guard` suppresses the bidirectional observers during
    # programmatic updates; `state.last_sel_key` tracks the ticker set rendered
    # on the last recompute — when it changes the box bounds + values reset to
    # the new overlap, when it's unchanged (same basket, user only narrowed the
    # range) the range is preserved. Both live on `DashboardState` (built below).

    apply_btn = W.Button(
        description="Refresh prices",
        layout=W.Layout(flex="1 1 auto"),
    )
    # Green primary action (`.bbg-btn`, GREEN_600) with hover/active/focus
    # states — styled via CSS class, not inline `.style`, so `:hover` works.
    apply_btn.add_class("bbg-btn")

    # The Multi-Strategy filter UI is the reusable `make_filter_panel` (shared
    # with the Single Strategy tab, v0.9.12-review #155): the pill bar over the
    # categorical / Characteristics / Quantitative views, the Clear buttons, and
    # the `apply_categorical` / `quant_keep` / `matching` reducers. Multi-Strategy
    # composes it with its own left Strategies picker + Refresh button + analysis
    # date-range row, so it passes the Refresh button as a leading action, its own
    # 60%/bordered right-panel layout, and `build_root=False` (it wraps the pieces
    # in its own "Filters" accordion below).
    filter_panel = make_filter_panel(
        meta,
        leading_actions=(apply_btn,),
        right_panel_layout=W.Layout(
            width="60%", padding="8px", border=f"1px solid {Color.BORDER}"
        ),
        build_root=False,
    )

    def _clear_all_extra(_b=None) -> None:
        # `make_filter_panel`'s Clear all resets the filter widgets (and fires the
        # observers); Multi-Strategy additionally wipes the search box and snaps
        # the analysis date range back to its full overlap span.
        search_w.value = ""
        if state.cur_bound_start is not None and state.cur_bound_end is not None:
            state.sync_guard = True
            try:
                range_min_box.value = state.cur_bound_start
                range_max_box.value = state.cur_bound_end
            finally:
                state.sync_guard = False

    filter_panel.clear_all_btn.on_click(_clear_all_extra)

    status_w = _status_banner()

    def _set_status(text: str, tone: StatusTone = StatusTone.INFO) -> None:
        state.status_w.value = _render_status(text, tone=tone)

    def _format_loaded(
        df: pd.DataFrame, source: str, elapsed: float
    ) -> tuple[str, StatusTone]:
        n_tickers = df.shape[1]
        n_days = df.shape[0]
        if source == "cache":
            # An in-memory cache hit can report "cache" with no parquet on disk
            # (e.g. a read-only filesystem), so the mtime stamp is best-effort.
            try:
                mtime = _cache_path(today).stat().st_mtime
                stamp = time.strftime("%H:%M · %m-%d", time.localtime(mtime))
                suffix = f" ({stamp})"
            except OSError:
                suffix = ""
            return (
                f"Loaded {n_tickers} indices · {n_days} trading days "
                f"from cache{suffix}",
                StatusTone.SUCCESS,
            )
        src_label = "BQL" if source == "bql" else "mock prices"
        return (
            f"Loaded {n_tickers} indices · {n_days} trading days · "
            f"fetched from {src_label} in {elapsed:.1f}s",
            StatusTone.SUCCESS,
        )

    # --- Analysis date-range box plumbing --------------------------------
    def _set_date_bounds(index, reset: bool, *, keep=None) -> None:
        """Set the two date boxes to the selection's overlap window. On
        ``reset`` (or a missing/degenerate ``keep``) the range snaps to the full
        span; otherwise the prior ``keep`` range is clamped into the window.
        Guarded so the min ≤ max observers stay quiet. ``keep`` is a
        ``(min, max)`` pair of ``datetime.date`` / ``None`` (the boxes' values).
        """
        state.sync_guard = True
        try:
            if index is None or len(index) == 0:
                state.cur_bound_start = None
                state.cur_bound_end = None
                range_min_box.value = None
                range_max_box.value = None
                return
            lo_b = pd.Timestamp(index[0]).date()
            hi_b = pd.Timestamp(index[-1]).date()
            state.cur_bound_start = lo_b
            state.cur_bound_end = hi_b

            def _clamp(d):
                return min(max(d, lo_b), hi_b)

            degenerate = keep is None or any(k is None or pd.isna(k) for k in keep)
            if reset or degenerate:
                lo, hi = lo_b, hi_b
            else:
                lo = _clamp(pd.Timestamp(keep[0]).date())
                hi = _clamp(pd.Timestamp(keep[1]).date())
                if lo > hi:
                    lo, hi = lo_b, hi_b
            range_min_box.value = lo
            range_max_box.value = hi
        finally:
            state.sync_guard = False

    def _on_range_box(change, *, is_min: bool) -> None:
        # Keep min ≤ max: editing one box past the other drags the other to it.
        # (DatePicker.min/max traits aren't relied on — the overlap window is
        # enforced by `_set_date_bounds` on Refresh and by the `.loc` slice.)
        if state.sync_guard or change["new"] is None:
            return
        lo = range_min_box.value
        hi = range_max_box.value
        if lo is None or hi is None or lo <= hi:
            return
        state.sync_guard = True
        try:
            if is_min:
                range_max_box.value = lo
            else:
                range_min_box.value = hi
        finally:
            state.sync_guard = False

    range_min_box.observe(lambda c: _on_range_box(c, is_min=True), names="value")
    range_max_box.observe(lambda c: _on_range_box(c, is_min=False), names="value")

    left_panel = W.VBox(
        [_section_label("Strategies"), search_row, ticker_w],
        layout=W.Layout(
            width="38%",
            padding="8px",
            border=f"1px solid {Color.BORDER}",
            display="flex",
            flex_flow="column",
        ),
    )

    filter_box = W.HBox(
        [left_panel, filter_panel.right_panel],
        layout=W.Layout(width="100%", align_items="stretch"),
    )
    # Full-width analysis date-range row below the two panels: slider flanked
    # by the two linked date boxes. Bounds fit the selected set's overlap
    # window; the range scopes the selected-set charts + perf grid on the
    # next Refresh prices.
    date_range_filter_row = W.VBox(
        [
            _section_label("Analysis date range"),
            W.HBox(
                [
                    range_min_box,
                    W.HTML("<div style='padding:0 6px;font-size:16px;'>–</div>"),
                    range_max_box,
                ],
                layout=W.Layout(width="100%", align_items="center"),
            ),
        ],
        layout=W.Layout(
            width="100%",
            padding="8px",
            margin="6px 0 0 0",
            border=f"1px solid {Color.BORDER}",
        ),
    )
    # The whole filter UI — the Strategies multi-select on the left, the
    # filter options on the right, and the analysis date range below —
    # collapses under a "Filters" accordion, expanded by default.
    filters_inner = W.VBox(
        [filter_box, date_range_filter_row],
        layout=W.Layout(width="100%"),
    )
    filters_accordion = W.Accordion(
        children=[filters_inner],
        titles=("Filters",),
        selected_index=0,
        layout=W.Layout(width="100%"),
    )

    weekly_w = W.HTML(
        _render_weekly_commentary(_load_weekly_commentary(), date.today())
    )
    highlights_w = W.HTML(_render_highlights([], []))
    errors_w = W.HTML("")  # init/pane-error boxes (kept out of highlights_w)
    # Live window for the Market Superlatives board — recomputes the panel from
    # the cache on change (no BQL), like the Platform lookback toggle.
    superlative_window = W.ToggleButtons(
        options=SHORT_WINDOW_OPTIONS,
        value=SUPERLATIVE_WINDOW_DAYS,
        layout=W.Layout(width="auto"),
    )
    superlative_window_row = W.HBox(
        [_section_label("Superlatives window"), superlative_window],
        layout=W.Layout(width="100%", align_items="center", padding="2px 0"),
    )
    universe_grid = _universe_grid()

    # Platform all-catalog grid z-score controls (v0.7.0 Workstream A). They
    # narrow nothing and never fetch — changing one recomputes only the grid's
    # dynamic z-score column from the cached prices and re-sorts the grid by it
    # (see `platform.render_universe_grid`). Window / Lookback values are trading-day
    # counts; the `.label` of each (e.g. "Sharpe" / "1M" / "1Y") builds the
    # column header. Default: z(1M Sharpe, 1Y).
    z_metric_dd = W.Dropdown(
        options=[
            ("Sharpe", "sharpe"),
            ("Sortino", "sortino"),
            ("Return", "return"),
            ("Vol", "vol"),
        ],
        value="sharpe",
        description="Metric",
        style={"description_width": "55px"},
        layout=W.Layout(width="175px"),
    )
    z_window_dd = W.Dropdown(
        options=[
            ("1M", MONTH_WINDOW),
            ("3M", QUARTER_WINDOW),
            ("6M", HALF_YEAR_WINDOW),
        ],
        value=MONTH_WINDOW,
        description="Window",
        style={"description_width": "60px"},
        layout=W.Layout(width="165px"),
    )
    z_lookback_dd = W.Dropdown(
        options=[
            ("1Y", TRADING_DAYS_PER_YEAR),
            ("3Y", TRADING_DAYS_PER_YEAR * 3),
            ("5Y", TRADING_DAYS_PER_YEAR * 5),
        ],
        value=TRADING_DAYS_PER_YEAR,
        description="Lookback",
        style={"description_width": "70px"},
        layout=W.Layout(width="180px"),
    )
    z_controls_row = W.HBox(
        [_section_label("Z-Score ranking"), z_metric_dd, z_window_dd, z_lookback_dd],
        layout=W.Layout(width="100%", align_items="center", padding="2px 0"),
    )

    # Shared 6M/1Y/3Y/5Y lookback selector — drives all three Platform analytics
    # tabs (factor scatter, regime scatter, and the sunburst). Value is a
    # trading-day count, like z_lookback_dd; the factor scatter converts it to
    # years. Re-slices the cache only (no BQL).
    lookback_selector = W.ToggleButtons(
        options=[
            ("6M", HALF_YEAR_WINDOW),
            ("1Y", TRADING_DAYS_PER_YEAR),
            ("3Y", TRADING_DAYS_PER_YEAR * 3),
            ("5Y", TRADING_DAYS_PER_YEAR * 5),
        ],
        value=TRADING_DAYS_PER_YEAR,
        layout=W.Layout(width="auto"),
    )
    factor_scatter_fig = _factor_beta_scatter()
    sunburst_fig = _sunburst()

    # Sunburst Z-score controls (Metric · Window; the lookback is the shared
    # toggle above). The chosen z colors the arcs (averaged up each level) and its
    # |z| drives each ring's gross-% sizing. Re-slice the cache only (no BQL);
    # `.value`s feed `rolling_metric_zscore`, the `.label`s the colorbar/hover.
    sb_metric_dd = W.Dropdown(
        options=[
            ("Sharpe", "sharpe"),
            ("Sortino", "sortino"),
            ("Return", "return"),
            ("Vol", "vol"),
        ],
        value="sharpe",
        description="Metric",
        style={"description_width": "60px"},
        layout=W.Layout(width="230px"),
    )
    sb_window_dd = W.Dropdown(
        options=SHORT_WINDOW_OPTIONS,
        value=WEEK_WINDOW,
        description="Window",
        style={"description_width": "60px"},
        layout=W.Layout(width="230px"),
    )

    # --- Regime Analysis: the all-catalog risk/return scatter conditioned on a
    # market-regime bucket. Volatility uses fixed VIX-level buckets; Trend /
    # Rate-level / Risk regime split a live-computed indicator into low/mid/high
    # terciles. Trend / Rate-level carry a conditional indicator-source dropdown
    # (benchmark / region). All conditioning is a live re-slice of the cache. The
    # controls stack in the Regime tab's left column (built below).
    regime_scatter_fig = _regime_scatter()

    regime_type_dd = W.Dropdown(
        options=list(REGIME_SPECS.keys()),
        value="Volatility",
        description="Type",
        style={"description_width": "60px"},
        layout=W.Layout(width="240px"),
    )
    # Conditional indicator-source dropdown — benchmark for Trend, region for
    # Rate-level; hidden (via `platform._sync_regime_controls`) for regimes with no
    # `selector` (Volatility / Risk regime).
    regime_selector_dd = W.Dropdown(
        options=[("—", "")],
        value="",
        description="Source",
        style={"description_width": "60px"},
        layout=W.Layout(width="240px"),
    )
    _init_buckets = regime_bucket_options("Volatility")
    regime_bucket_dd = W.Dropdown(
        options=_init_buckets,
        value=_init_buckets[0][1],
        description="Bucket",
        style={"description_width": "60px"},
        layout=W.Layout(width="240px"),
    )

    pane_left = _make_analysis_pane("left")
    pane_right = _make_analysis_pane("right")
    analysis_pane_row = W.HBox(
        [pane_left.root, pane_right.root],
        layout=W.Layout(width="100%", align_items="stretch"),
    )

    selected_perf_grid = _perf_grid()

    # All session state the orchestration closures read/write lives here, so
    # the data flow is explicit (no nonlocal, no list-as-cell hacks). The
    # closures stay nested and reference `state.<field>`; mutating an attribute
    # never rebinds a name, so `nonlocal` is unnecessary.
    state = DashboardState(
        ticker_w=ticker_w,
        status_w=status_w,
        overlay_w=overlay_w,
        universe_grid=universe_grid,
        selected_perf_grid=selected_perf_grid,
        pane_left=pane_left,
        pane_right=pane_right,
        highlights_w=highlights_w,
        errors_w=errors_w,
    )

    selected_perf_header = W.HTML(
        render_template(
            "grid_header", **STYLE_CTX, text="Selected-strategy performance"
        )
    )
    selected_perf_section = W.VBox(
        [selected_perf_header, selected_perf_grid],
        layout=W.Layout(width="100%", padding="4px 0 8px 0"),
    )

    commentary_box = W.VBox(
        [weekly_w, errors_w, superlative_window_row, highlights_w],
        layout=W.Layout(width="100%", padding="12px 16px"),
    )

    universe_header = W.HTML(
        render_template("grid_header", **STYLE_CTX, text="All-catalog performance")
    )

    # --- Platform analytics card: the three charts (sunburst / regime / factor
    # scatter) as inner pill-tabs sharing one lookback. The layout is a fixed
    # left control column beside a flex-grow chart: the shared lookback sits on
    # top of the column, then the active tab's own selection boxes swap in below
    # it (`tab_controls_box`); the chart swaps in `chart_box`. Factor exposures
    # has no extra controls, so its column is just the lookback. The card is a
    # bordered box (`.bbg-card`) so the grouping reads at a glance.
    sunburst_controls = W.VBox(
        [_section_label("Z-score"), sb_metric_dd, sb_window_dd],
        layout=W.Layout(width="100%"),
    )
    regime_controls = W.VBox(
        [
            _section_label("Regime"),
            regime_type_dd,
            regime_selector_dd,
            regime_bucket_dd,
        ],
        layout=W.Layout(width="100%"),
    )
    factor_controls = W.VBox([], layout=W.Layout(width="100%"))

    sunburst_pill = _make_tab_button(
        "Sunburst", active=True, width="190px", height="34px"
    )
    regime_pill = _make_tab_button(
        "Regime analysis", active=False, width="190px", height="34px"
    )
    factor_pill = _make_tab_button(
        "Factor exposures", active=False, width="190px", height="34px"
    )
    analytics_tab_bar = W.HBox(
        [sunburst_pill, regime_pill, factor_pill],
        layout=W.Layout(width="100%", padding="2px 0 6px 0"),
    )

    # Shared lookback stacked on top of the active tab's controls (left column).
    tab_controls_box = W.Box([sunburst_controls], layout=W.Layout(width="100%"))
    analytics_left_col = W.VBox(
        [_section_label("Lookback"), lookback_selector, tab_controls_box],
        layout=W.Layout(flex="0 0 260px", width="260px", padding="2px 8px 2px 0"),
    )
    chart_box = W.Box([sunburst_fig], layout=W.Layout(flex="1 1 0%", width="100%"))
    analytics_body = W.HBox(
        [analytics_left_col, chart_box],
        layout=W.Layout(width="100%", align_items="stretch"),
    )

    _analytics_tabs = {
        "sunburst": (sunburst_pill, sunburst_controls, sunburst_fig),
        "regime": (regime_pill, regime_controls, regime_scatter_fig),
        "factor": (factor_pill, factor_controls, factor_scatter_fig),
    }

    analytics_card = W.VBox(
        [
            W.HTML(
                render_template("grid_header", **STYLE_CTX, text="Platform analytics")
            ),
            analytics_tab_bar,
            analytics_body,
        ],
        layout=W.Layout(width="100%"),
    )
    analytics_card.add_class("bbg-card")

    # Bundle the Platform-analytics widget handles and hand the orchestration to
    # `platform.py` (v0.9.12-review #156): `wire_platform_analytics` wires the
    # z-score-column controls, the three tab pills, the regime dropdowns, the
    # shared lookback, and the sunburst controls; the `render_*` functions
    # (called on load / Refresh below) redraw each chart live from the cache.
    pa = SimpleNamespace(
        z_metric_dd=z_metric_dd,
        z_window_dd=z_window_dd,
        z_lookback_dd=z_lookback_dd,
        lookback_selector=lookback_selector,
        factor_scatter_fig=factor_scatter_fig,
        sunburst_fig=sunburst_fig,
        regime_scatter_fig=regime_scatter_fig,
        sb_metric_dd=sb_metric_dd,
        sb_window_dd=sb_window_dd,
        regime_type_dd=regime_type_dd,
        regime_selector_dd=regime_selector_dd,
        regime_bucket_dd=regime_bucket_dd,
        sunburst_pill=sunburst_pill,
        regime_pill=regime_pill,
        factor_pill=factor_pill,
        analytics_tabs=_analytics_tabs,
        tab_controls_box=tab_controls_box,
        chart_box=chart_box,
    )
    wire_platform_analytics(state, meta, pa)

    platform_panel = W.VBox(
        [
            universe_header,
            z_controls_row,
            universe_grid,
            analytics_card,
        ],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )
    selected_panel = W.VBox(
        [filters_accordion, selected_perf_section, analysis_pane_row],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )

    # The third top-level tab (v0.9.0): a per-strategy deep-dive. Built here so
    # the tab wiring below can swap it in; its picker options are rebuilt against
    # the pruned `meta` once the cache loads (alongside `ticker_w`).
    single_strategy = make_single_strategy_panel(meta)
    state.single_strategy = single_strategy
    single_panel = single_strategy.root

    platform_btn = _make_tab_button("Platform", active=True)
    selected_btn = _make_tab_button("Multi-Strategy", active=False)
    single_btn = _make_tab_button("Single Strategy", active=False)
    top_tab_bar = W.HBox(
        [platform_btn, selected_btn, single_btn],
        layout=W.Layout(width="100%"),
    )
    # Stylize the band as the section header (distinct bg + accent underline +
    # inverted active tab); padding/border/background live on `.bbg-tabband`
    # in app_css.html so they stay token-driven.
    top_tab_bar.add_class("bbg-tabband")
    top_tab_content = W.Box(
        [platform_panel],
        layout=W.Layout(width="100%"),
    )

    _top_panels = {
        "platform": platform_panel,
        "selected": selected_panel,
        "single": single_panel,
    }

    def _activate_tab(which: str) -> None:
        _style_tab_button(platform_btn, active=which == "platform")
        _style_tab_button(selected_btn, active=which == "selected")
        _style_tab_button(single_btn, active=which == "single")
        top_tab_content.children = (_top_panels[which],)

    platform_btn.on_click(lambda _b: _activate_tab("platform"))
    selected_btn.on_click(lambda _b: _activate_tab("selected"))
    single_btn.on_click(lambda _b: _activate_tab("single"))

    def _default_selection() -> tuple[str, ...]:
        """The startup strategy selection: the 5 indices with the highest
        z-score of (1W Sharpe, 1Y) over the fetched cache, so the Multi-Strategy
        views load populated. Falls back to the first available tickers when the
        z-score is unavailable/degenerate."""
        opt = [o[1] if isinstance(o, tuple) else o for o in state.ticker_w.options]
        if not opt:
            return ()
        if not state.arp_universe_prices.empty:
            try:
                z = rolling_metric_zscore(
                    state.arp_universe_prices,
                    metric="sharpe",
                    window=WEEK_WINDOW,
                    zscore_window=TRADING_DAYS_PER_YEAR,
                ).dropna()
                top = [t for t in z.nlargest(5).index if t in opt]
                if top:
                    return tuple(top)
            except Exception:
                pass
        return tuple(opt[:5])

    # Single BQL fetch at app-load time, bounded by LOOKBACK_YEARS. A wider
    # fetch (e.g. back to oldest live date) is too slow on the terminal, so the
    # all-catalog grid's windows are likewise bounded by this lookback.
    today = date.today()
    universe_start = (pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)).date()

    # `state.universe_prices` / `state.init_errors` default to empty (see
    # DashboardState); the startup fetch below populates them.
    # Benchmarks and v0.7.0 Platform factor proxies ride along on the single
    # startup fetch so the Rolling Correlation / Rolling Beta tabs and the
    # Platform factor scatter/sunburst can slice them from the same cache. Both
    # are excluded from the ARP-universe grid and the highlights cards via
    # reindex(columns=meta["ticker"]). dict.fromkeys dedupes any overlap (the
    # equity factor proxy is also a benchmark) while preserving order.
    fetch_tickers = list(
        dict.fromkeys(
            list(meta["ticker"])
            + list(BENCHMARK_TICKERS)
            + list(FACTOR_TICKERS)
            + list(REGIME_TICKERS)
        )
    )
    _set_progress(60, f"Fetching prices for {len(fetch_tickers)} indices…")
    t_fetch = time.perf_counter()
    try:
        state.universe_prices, fetch_source = fetch_prices(
            fetch_tickers, universe_start, today
        )
        fetch_elapsed = time.perf_counter() - t_fetch
        text, tone = _format_loaded(state.universe_prices, fetch_source, fetch_elapsed)
        _set_status(text, tone=tone)
    except Exception:
        _set_progress(60, "Load failed — see error below", error=True)
        _set_status("Load failed — see error below", tone=StatusTone.ERROR)
        state.init_errors.append(
            f"Universe fetch ({universe_start} → {today}) failed:\n"
            f"{traceback.format_exc()}"
        )

    if not state.universe_prices.empty:
        # Drop indices with no recent price movement (stale / delisted / all-NaN)
        # from the displayed `meta`; `meta_all` (everything fetched) is kept so a
        # resumed ticker can be re-admitted on a later Refresh. Then refresh the
        # strategies dropdown so the dropped tickers leave it too.
        live = set(
            active_columns(state.universe_prices.reindex(columns=meta_all["ticker"]))
        )
        meta = meta_all[meta_all["ticker"].isin(live)].reset_index(drop=True)
        # Resetting the options clears `ticker_w.value`; reselect below once the
        # cache (and so the z-score ranking) is available.
        state.ticker_w.options = _ticker_options(meta)
        # The single-strategy picker mirrors the pruned catalog (all live
        # strategies, unfiltered); resetting its options auto-selects the first.
        single_strategy.picker.options = _ticker_options(meta)
        _log(f"pruned to {len(meta)} indices with recent performance")
        # ARP universe view of the cache — used for the all-catalog grid and
        # the whole-catalog highlights so benchmark columns never leak in.
        state.arp_universe_prices = state.universe_prices.reindex(
            columns=meta["ticker"]
        )
        # Startup selection: the top 5 indices by z(1W Sharpe, 1Y) so the
        # Multi-Strategy views render populated on load (the initial _recompute
        # below reads this selection).
        state.ticker_w.value = _default_selection()
        t_perf = time.perf_counter()
        try:
            state.universe_up = universe_perf(state.arp_universe_prices)
            _log(f"universe_perf computed in {time.perf_counter() - t_perf:.2f}s")
            t_grid = time.perf_counter()
            render_universe_grid(state, meta, pa)
            render_factor_scatter(state, meta, pa)
            render_sunburst(state, meta, pa)
            render_regime_scatter(state, meta, pa)
            _log(f"universe grid populated in {time.perf_counter() - t_grid:.2f}s")
        except Exception:
            state.init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
        _set_progress(85, "Building catalog…")
    else:
        state.arp_universe_prices = pd.DataFrame()
        state.universe_up = pd.DataFrame()

    def _on_filter_change(_change=None):
        # Categorical + Characteristics via the shared panel; then the search
        # substring; then the quant thresholds. Currently-selected tickers that
        # still pass the categorical filter are unioned back so a live filter
        # toggle never drops a picked strategy from the option list.
        filtered = filter_panel.apply_categorical(meta)
        query = (search_w.value or "").strip().lower()
        if query:
            mask = filtered["ticker"].str.lower().str.contains(
                query, regex=False
            ) | filtered["name"].str.lower().str.contains(query, regex=False)
            visible = filtered.loc[mask]
        else:
            visible = filtered

        quant_keep = filter_panel.quant_keep(pd.Index(visible["ticker"]), state)
        visible = visible.loc[visible["ticker"].isin(quant_keep)]

        selected = list(state.ticker_w.value)
        keep_selected = filtered.loc[filtered["ticker"].isin(selected)]
        combined = pd.concat([visible, keep_selected]).drop_duplicates(subset="ticker")
        combined = combined.sort_values("ticker").reset_index(drop=True)
        state.ticker_w.options = _ticker_options(combined)
        state.ticker_w.value = tuple(
            t for t in selected if t in combined["ticker"].values
        )

    # Every filter input narrows the picker live (the panel exposes them all);
    # the search box is the Multi-Strategy tab's own, wired alongside.
    for w in filter_panel.inputs:
        w.observe(_on_filter_change, names="value")
    search_w.observe(_on_filter_change, names="value")

    # Whole-catalog Key Highlights are independent of the selection and change
    # only when prices are refetched, so memoize them: the superlatives per
    # window (the toggle offers four) and the window-independent launch cards
    # once. `_recompute` — the single data-load / Refresh point — clears this,
    # so a re-toggle among the four windows is a cache hit rather than a full
    # whole-catalog recompute.
    highlights_cache: dict = {}

    def _render_highlights_panel(window_days):
        """Render the whole-catalog Key Highlights panel at ``window_days``.

        Builds the superlatives (at the chosen window) + new-launch cards from
        the already-fetched ARP cache and writes ``state.highlights_w`` — no
        BQL, no selection. Shared by ``_recompute`` (initial/Refresh) and the
        live window-toggle observer; a compute failure surfaces in-place rather
        than blanking the panel."""
        try:
            universe = state.arp_universe_prices
            if universe.empty:
                state.highlights_w.value = _render_highlights([], [])
                return
            if "launches" not in highlights_cache:
                highlights_cache["launches"] = build_launch_cards(
                    meta, universe, as_of=today
                )
            superlatives = highlights_cache.get(window_days)
            if superlatives is None:
                window_start = pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)
                universe_window = universe.loc[universe.index >= window_start]
                if universe_window.empty:
                    state.highlights_w.value = _render_highlights([], [])
                    return
                # Only the trailing window feeds the returns-based metrics (MACD,
                # a fixed-lookback oscillator, reads the full price history
                # itself), so derive daily_returns over just the span they need
                # — not the whole 5-year slice.
                window_rets = superlative_returns(
                    universe_window, window_days=window_days
                )
                superlatives = build_superlatives(
                    meta, universe_window, window_rets, window_days=window_days
                )
                highlights_cache[window_days] = superlatives
            state.highlights_w.value = _render_highlights(
                superlatives,
                highlights_cache["launches"],
                window_label=WINDOW_LABELS.get(window_days, "Past Month"),
            )
        except Exception:
            state.highlights_w.value = _render_error(traceback.format_exc())

    superlative_window.observe(
        lambda c: _render_highlights_panel(c["new"]), names="value"
    )

    def _recompute(_btn=None):
        # A recompute rebuilds the selection slice (`cur_prep`), so every
        # memoized benchmark-dependent result is stale — drop them all. This is
        # the single invalidation point (covers Refresh, initial load, and the
        # no-selection guard branches below). Benchmark flips don't call
        # _recompute, so the memo survives across them within a stable slice.
        state.memo.clear()
        # The highlights are whole-catalog; a fresh fetch invalidates them.
        highlights_cache.clear()
        error_html = ""
        # Surface any errors from the initial universe fetch so the user can
        # see what actually went wrong, not just the downstream "cache empty".
        for err in state.init_errors:
            error_html += _render_error(err)
        # Highlights are always whole-catalog (ARP only), regardless of
        # selection. Render the panel at the currently-selected window; the
        # toggle re-renders it live (no BQL) via the same closure.
        _render_highlights_panel(superlative_window.value)

        # 5Y bound for the selected-set slice below.
        universe_window_start = pd.Timestamp(today) - pd.DateOffset(
            years=LOOKBACK_YEARS
        )
        pane_errors: list[str] = []
        try:
            tickers = list(state.ticker_w.value)
            if len(tickers) < 1:
                state.last_sel_key = None
                state.cur_prep = None
                _set_date_bounds(None, reset=True)
                _update_perf_grid(state.selected_perf_grid, pd.DataFrame(), meta)
                clear_pane(state.pane_left, meta)
                clear_pane(state.pane_right, meta)
            elif state.universe_prices.empty:
                state.last_sel_key = None
                state.cur_prep = None
                _set_date_bounds(None, reset=True)
                pane_errors.append(
                    "Universe price cache is empty — initial BQL fetch returned no rows."
                )
                _update_perf_grid(state.selected_perf_grid, pd.DataFrame(), meta)
                clear_pane(state.pane_left, meta)
                clear_pane(state.pane_right, meta)
            else:
                sel_full = state.universe_prices.reindex(columns=tickers)
                sel_5y = sel_full.loc[sel_full.index >= universe_window_start]
                if sel_5y.dropna(how="all").empty:
                    state.last_sel_key = None
                    state.cur_prep = None
                    _set_date_bounds(None, reset=True)
                    pane_errors.append(
                        f"No price data in the {LOOKBACK_YEARS}Y window for: {tickers}."
                    )
                    _update_perf_grid(state.selected_perf_grid, pd.DataFrame(), meta)
                    clear_pane(state.pane_left, meta)
                    clear_pane(state.pane_right, meta)
                else:
                    # Bounds = overlap window of the selected set; fall back to
                    # the full 5Y span if the series don't overlap at all.
                    bound_start, bound_end = common_window_bounds(sel_5y)
                    if bound_start is None:
                        bound_start, bound_end = sel_5y.index.min(), sel_5y.index.max()
                    window_index = sel_5y.loc[bound_start:bound_end].index
                    sel_key = tuple(tickers)
                    _set_date_bounds(
                        window_index,
                        reset=(sel_key != state.last_sel_key),
                        keep=(range_min_box.value, range_max_box.value),
                    )
                    state.last_sel_key = sel_key
                    win_start = pd.Timestamp(range_min_box.value)
                    win_end = pd.Timestamp(range_max_box.value)
                    sel_window = sel_5y.loc[win_start:win_end]
                    # Compute the selected-set returns once and thread them into
                    # the dependents (perf_table, sz_series, cm, rd_stats) rather
                    # than letting each recompute daily_returns.
                    t_prep = time.perf_counter()
                    sel_rets = daily_returns(sel_window)
                    prep = SimpleNamespace(
                        sel_window=sel_window,
                        rets=sel_rets,
                        perf=cum_perf(sel_window),
                        pt=perf_table(sel_window, returns=sel_rets),
                        dd=drawdown_series(sel_window),
                    )
                    prep.sz_series = rolling_sharpe_zscore(prep.rets)
                    prep.cm = corr_matrix(prep.rets)
                    prep.rd_stats = return_distribution_stats(prep.rets)
                    # Persist the slice so the live benchmark/regime observers
                    # can re-render a single chart without a refetch.
                    state.cur_prep = prep
                    state.cur_win_start = win_start
                    state.cur_win_end = win_end
                    _log(f"selected prep built in {time.perf_counter() - t_prep:.2f}s")
                    _update_perf_grid(state.selected_perf_grid, prep.pt, meta)
                    t_panes = time.perf_counter()
                    render_pane(
                        state,
                        meta,
                        state.pane_left,
                        prep,
                        win_start,
                        win_end,
                        pane_errors,
                    )
                    render_pane(
                        state,
                        meta,
                        state.pane_right,
                        prep,
                        win_start,
                        win_end,
                        pane_errors,
                    )
                    _log(
                        "panes rendered (mounted views only) in "
                        f"{time.perf_counter() - t_panes:.2f}s"
                    )
        except Exception:
            pane_errors.append(traceback.format_exc())

        for err in pane_errors:
            error_html += _render_error(err)

        state.errors_w.value = error_html

    def _run_refresh():
        """The Refresh-prices blocking work: refetch, re-prune, recompute.

        Split out of ``_refresh_prices`` so a live frontend can run it on a
        worker thread (see ``_refresh_prices``). Drives the overlay's staged
        progress from 60% (fetch) through dismissal at 100%."""
        nonlocal meta
        try:
            state.universe_prices, _ = fetch_prices(
                fetch_tickers, universe_start, today, use_cache=False
            )
        except Exception:
            _set_progress(60, "Load failed — see error below", error=True)
            _set_status("Load failed — see error below", tone=StatusTone.ERROR)
            state.init_errors.append(
                f"Universe refresh ({universe_start} → {today}) failed:\n"
                f"{traceback.format_exc()}"
            )
            _recompute()
            return
        # Re-prune stale indices from the full catalog against the fresh cache
        # (a resumed ticker can return), then refresh the strategies dropdown.
        if not state.universe_prices.empty:
            live = set(
                active_columns(
                    state.universe_prices.reindex(columns=meta_all["ticker"])
                )
            )
            meta = meta_all[meta_all["ticker"].isin(live)].reset_index(drop=True)
            _on_filter_change()
            single_strategy.picker.options = _ticker_options(meta)
        state.arp_universe_prices = state.universe_prices.reindex(
            columns=meta["ticker"]
        )
        try:
            state.universe_up = universe_perf(state.arp_universe_prices)
            render_universe_grid(state, meta, pa)
            render_factor_scatter(state, meta, pa)
            render_sunburst(state, meta, pa)
            render_regime_scatter(state, meta, pa)
        except Exception:
            state.init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
        _set_progress(85, "Building catalog…")
        # No post-load toast on Refresh: the loading overlay already signals
        # progress, and the "Loaded N indices …" toast is reserved for the
        # dashboard's *initial* load. (A refresh failure still toasts, above.)
        _recompute()
        # Re-apply the Single Strategy filters against the fresh cache (arp is
        # updated above) so its picker stays consistent with any active filter;
        # this renders the tab once. (`_on_single_filter_change` is defined
        # below but only ever called at runtime, like `_render_single`.)
        _on_single_filter_change()
        _set_progress(100, "Ready", hidden=True)

    def _render_single(_change=None) -> None:
        """Re-render the Single Strategy tab's Section 1 from the cache. Bound to
        the picker / benchmark controls and called on load + Refresh. Reads the
        current (possibly re-pruned) `meta` and a 5Y window off `today`."""
        # `_on_single_filter_change` sets the picker options+value in one shot;
        # suppress the intermediate picker-observer renders and render once at
        # the end there instead.
        if getattr(single_strategy, "_suspend", False):
            return
        window_start = pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)
        render_single_strategy(single_strategy, state, meta, window_start)

    def _refresh_prices(_btn=None):
        # Re-show the overlay (it's already in the tree — just re-render its
        # value visible) and re-run the staged bar.
        #
        # The overlay only becomes visible once the frontend gets a paint
        # cycle. On the initial load that happens naturally: `display(overlay_w)`
        # mounts a *new* view that is born visible and painted before the long
        # synchronous build runs. On Refresh the overlay view already exists
        # (hidden), so flipping it visible→…→hidden all inside one synchronous
        # click handler keeps the kernel busy the whole time; the frontend
        # coalesces those comm updates and only ever paints the final hidden
        # state, so the overlay never appears. This is the "background-thread
        # load" the v0.6.5 Workstream C caveat flagged as the real fix: show the
        # overlay, then hand the blocking fetch/recompute to a worker thread so
        # the click handler returns and the frontend can paint the visible
        # overlay before the kernel blocks on BQL.
        _set_progress(0, "Refreshing…")
        _set_progress(60, f"Fetching prices for {len(fetch_tickers)} indices…")

        if get_ipython() is None:
            # Headless / pytest: run synchronously so callers observe the
            # refetch immediately after `.click()` (no frontend to paint for).
            _run_refresh()
            return

        if refresh_inflight["running"]:
            return  # a refresh is already running; ignore re-clicks
        refresh_inflight["running"] = True
        apply_btn.disabled = True

        def _worker():
            try:
                # Hold the just-shown overlay visible for a beat so the frontend
                # actually paints it before an instant refetch (mock / warm
                # cache) flips it hidden — otherwise show→hide coalesce into one
                # frame and the overlay never appears. Harmless on a slow BQL
                # fetch (it's already visible for far longer). Runs on this
                # worker thread, so the kernel stays free to flush the paint.
                time.sleep(_OVERLAY_PAINT_DELAY_S)
                _run_refresh()
            finally:
                refresh_inflight["running"] = False
                apply_btn.disabled = False

        threading.Thread(target=_worker, name="bbg-refresh", daemon=True).start()

    # Guards against a second Refresh being launched while a worker thread is
    # still fetching/recomputing (the button is also disabled for the duration).
    refresh_inflight = {"running": False}
    apply_btn.on_click(_refresh_prices)
    bind_live_controls(state, meta, state.pane_left)
    bind_live_controls(state, meta, state.pane_right)
    bind_lazy_render(state, meta, state.pane_left)
    bind_lazy_render(state, meta, state.pane_right)
    single_strategy.picker.observe(_render_single, names="value")
    single_strategy.bench_dd.observe(_render_single, names="value")
    single_strategy.bench_chk.observe(_render_single, names="value")

    def _on_single_filter_change(_change=None) -> None:
        """Narrow the Single Strategy picker to the filter matches and re-render.

        Live handler for the v0.9.12 "Filters" accordion: on any filter input
        change, recompute the matching tickers from the cache, reset the picker
        options, keep the current pick when it still matches (else auto-select
        the first match, or clear when nothing matches), then render once.
        """
        matches = single_strategy.filters.matching(meta, state)
        sub = meta.loc[meta["ticker"].isin(matches)]
        options = _ticker_options(sub)
        cur = single_strategy.picker.value
        # Set options + value atomically without triggering the picker-observer
        # render mid-flight (resetting options fires an intermediate value=None).
        single_strategy._suspend = True
        try:
            single_strategy.picker.options = options
            if cur in set(sub["ticker"]):
                single_strategy.picker.value = cur
            elif options:
                single_strategy.picker.value = options[0][1]
            else:
                single_strategy.picker.value = None
        finally:
            single_strategy._suspend = False
        _render_single()

    for _w in single_strategy.filters.inputs:
        _w.observe(_on_single_filter_change, names="value")

    def _make_cal_kind_handler(which: str):
        def _handler(_b=None) -> None:
            set_calendar_kind(single_strategy, which)
            render_calendar(single_strategy, state)

        return _handler

    for pill, (_label, kind) in zip(
        single_strategy.cal_pills, _CALENDAR_TABS, strict=True
    ):
        pill.on_click(_make_cal_kind_handler(kind))

    # Section 3 two-pane analysis: each pane re-renders its mounted view when its
    # analysis picker or benchmark dropdown changes (panes.py already swapped the
    # stack + benchmark visibility on the pick). The shared strategy / window
    # come from `single_strategy.picker` and `today`; no BQL, the other pane
    # untouched.
    def _make_pane_render_handler(pane: SimpleNamespace):
        def _handler(_change=None) -> None:
            window_start = pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)
            render_analysis_pane(single_strategy, pane, state, meta, window_start)

        return _handler

    for pane in (single_strategy.pane_left, single_strategy.pane_right):
        handler = _make_pane_render_handler(pane)
        pane.picker.observe(handler, names="value")
        pane.bench_dd.observe(handler, names="value")

    perf_disclaimer_w = W.HTML(
        _load_disclaimer(
            PERFORMANCE_DISCLAIMER_PATH,
            start_date=universe_start.isoformat(),
            end_date=today.isoformat(),
        ),
        layout=W.Layout(width="100%", padding="0 16px"),
    )
    legal_w = W.HTML(
        _load_disclaimer(LEGAL_DISCLOSURE_PATH),
        layout=W.Layout(width="100%", padding="0 16px 16px 16px"),
    )

    app = W.VBox(
        [
            _app_css(),  # global stylesheet, injected once (v0.6.5 Workstream A)
            _banner(),
            status_w,
            commentary_box,
            top_tab_bar,
            top_tab_content,
            perf_disclaimer_w,
            legal_w,
            overlay_w,  # fixed-position loading overlay (v0.6.5 Workstream C)
        ],
        layout=W.Layout(width="100%"),
    )
    # Opt the app container into the injected dark-chrome class.
    app.add_class("bbg-app")

    t_initial = time.perf_counter()
    _recompute()
    _render_single()
    _log(f"initial recompute (selected viz) in {time.perf_counter() - t_initial:.2f}s")
    _log(f"build_app TOTAL: {time.perf_counter() - t0:.2f}s")
    # Dismiss the overlay once data is loaded; on a fatal fetch failure leave
    # the error overlay up (the traceback also renders in the commentary block).
    if not state.universe_prices.empty:
        _set_progress(100, "Ready", hidden=True)
    return app
