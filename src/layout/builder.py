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
from ..commentary import build_launch_cards, build_superlatives
from ..config import (
    BENCHMARK_TICKERS,
    DEFAULT_BENCHMARK,
    FACTOR_TICKERS,
    HALF_YEAR_WINDOW,
    LEGAL_DISCLOSURE_PATH,
    LOOKBACK_YEARS,
    MONTH_WINDOW,
    PERFORMANCE_DISCLAIMER_PATH,
    QUARTER_WINDOW,
    REGIME_SPECS,
    REGIME_TICKERS,
    SUPERLATIVE_WINDOW_DAYS,
    TRADING_DAYS_PER_YEAR,
    UNIVERSE_SOLUTION_VALUES,
    WEEK_WINDOW,
)
from ..data import apply_filters, load_metadata, unique_values
from ..stats import (
    active_columns,
    ann_beta,
    common_window_bounds,
    corr_matrix,
    cum_perf,
    daily_returns,
    drawdown_series,
    excess_cum_return,
    heatmap_corr_matrix,
    jensen_alpha,
    perf_table,
    quant_metrics_table,
    return_distribution_stats,
    rolling_autocorr,
    rolling_beta,
    rolling_correlation,
    rolling_metric_zscore,
    rolling_sharpe_zscore,
    tercile_bounds,
    treynor_ratio,
    universe_perf,
    zscore_cross_section,
)
from ..style import (
    Color,
    StatusTone,
)
from .charts import (
    _update_drawdown,
    _update_heatmap,
    _update_line,
    _update_outperformance,
    _update_return_dist,
    _update_rolling_ref,
    _update_scatter,
    _update_sharpe_line,
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
from .filters import _checkbox_group, _q_row, _section_label, _ticker_options
from .grids import (
    _perf_grid,
    _universe_grid,
    _update_perf_grid,
    _update_universe_grid,
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
from .panes import _make_analysis_pane
from .platform import (
    _factor_beta_scatter,
    _regime_scatter,
    _sunburst,
    _update_factor_scatter,
    _update_regime_scatter,
    _update_sunburst,
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

    asset_content, asset_get, asset_checks = _checkbox_group(
        unique_values(meta, "asset_class")
    )
    cat_content, cat_get, cat_checks = _checkbox_group(unique_values(meta, "category"))
    theme_content, theme_get, theme_checks = _checkbox_group(
        unique_values(meta, "theme")
    )
    ret_content, ret_get, ret_checks = _checkbox_group(
        unique_values(meta, "return_type")
    )

    live_min = W.DatePicker(layout=W.Layout(width="160px"))
    live_max = W.DatePicker(layout=W.Layout(width="160px"))

    # Currency lives under Characteristics; "All" = no currency filter.
    currency_dd = W.Dropdown(
        options=["All"] + unique_values(meta, "currency"),
        value="All",
        description="Currency",
        style={"description_width": "70px"},
        layout=W.Layout(width="240px"),
    )

    def currency_get() -> list[str]:
        return [] if currency_dd.value == "All" else [currency_dd.value]

    # Quantitative filter — each metric row is [label] [≥/≤ dropdown] [value],
    # with an inline parameter dropdown where relevant (Beta → benchmark,
    # Z-Score → base metric). Ratios are computed from the already-fetched
    # prices (no new BQL). Value is a Text box parsed to float, so a blank box
    # means "no filter"; 0 stays a valid threshold.
    q_period = W.Dropdown(
        options=[("1Y", 1), ("3Y", 3), ("5Y", 5)],
        value=1,
        description="Period",
        style={"description_width": "55px"},
        layout=W.Layout(width="150px"),
    )

    def _bench_dd() -> W.Dropdown:
        return W.Dropdown(
            options=BENCHMARK_TICKERS,
            value=DEFAULT_BENCHMARK,
            layout=W.Layout(width="200px"),
        )

    # Each benchmark-based metric gets its own benchmark dropdown.
    q_beta_bench = _bench_dd()
    q_treynor_bench = _bench_dd()
    q_jensen_bench = _bench_dd()
    q_z_metric = W.Dropdown(
        options=[
            "Sharpe",
            "Sortino",
            "Calmar",
            "Beta",
            "Treynor",
            "Jensen",
            "VaR",
            "RSI",
        ],
        value="Sharpe",
        layout=W.Layout(width="120px"),
    )
    # Window the Z-Score's base metric is computed over (independent of the
    # global Period); the metric is then z-scored cross-sectionally.
    q_z_window = W.Dropdown(
        options=[
            ("1W", WEEK_WINDOW),
            ("1M", MONTH_WINDOW),
            ("3M", QUARTER_WINDOW),
            ("6M", HALF_YEAR_WINDOW),
        ],
        value=MONTH_WINDOW,
        layout=W.Layout(width="70px"),
    )

    sharpe_row, sharpe_op, q_sharpe = _q_row("Sharpe")
    sortino_row, sortino_op, q_sortino = _q_row("Sortino")
    calmar_row, calmar_op, q_calmar = _q_row("Calmar")
    beta_row, beta_op, q_beta = _q_row("Beta", trailing=q_beta_bench)
    treynor_row, treynor_op, q_treynor = _q_row("Treynor", trailing=q_treynor_bench)
    jensen_row, jensen_op, q_jensen = _q_row("Jensen α", trailing=q_jensen_bench)
    var_row, var_op, q_var = _q_row("VaR %")
    rsi_row, rsi_op, q_rsi = _q_row("RSI")
    z_row, z_op, q_z = _q_row(
        "Z-Score",
        trailing=W.HBox(
            [W.HTML("<div style='padding:0 6px;'>of</div>"), q_z_metric, q_z_window],
            layout=W.Layout(align_items="center"),
        ),
    )
    quant = SimpleNamespace(
        period_dd=q_period,
        z_metric_dd=q_z_metric,
        z_window_dd=q_z_window,
        # Each benchmark-based metric carries its own benchmark dropdown.
        bench_dd={
            "Beta": q_beta_bench,
            "Treynor": q_treynor_bench,
            "Jensen": q_jensen_bench,
        },
        rows=[
            sharpe_row,
            sortino_row,
            calmar_row,
            beta_row,
            treynor_row,
            jensen_row,
            var_row,
            rsi_row,
            z_row,
        ],
        # metric name -> (operator dropdown, value box)
        specs={
            "Sharpe": (sharpe_op, q_sharpe),
            "Sortino": (sortino_op, q_sortino),
            "Calmar": (calmar_op, q_calmar),
            "Beta": (beta_op, q_beta),
            "Treynor": (treynor_op, q_treynor),
            "Jensen": (jensen_op, q_jensen),
            "VaR": (var_op, q_var),
            "RSI": (rsi_op, q_rsi),
            "Z": (z_op, q_z),
        },
    )

    search_w = W.Text(
        placeholder="Search ticker or name…",
        layout=W.Layout(width="100%"),
    )
    # The SelectMultiple fills 100% of a flex holder (built below) that grows to
    # the bottom of the left panel, which the parent HBox stretches to the
    # filter panel's height. A plain `flex` on the select itself isn't honored,
    # but `height="100%"` inside a grown holder is — so it reaches the bottom.
    ticker_w = W.SelectMultiple(
        options=_ticker_options(meta),
        value=tuple(meta["ticker"].head(5)),
        layout=W.Layout(width="100%", height="100%"),
    )

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
    clear_section_btn = W.Button(
        description="Clear section",
        tooltip="Clear the active filter's selections",
        layout=W.Layout(width="auto"),
    )
    clear_all_btn = W.Button(
        description="Clear all",
        tooltip="Clear all filters and the search box",
        layout=W.Layout(width="auto"),
    )
    # Secondary (outlined/muted) action style with hover/focus — via CSS class.
    clear_section_btn.add_class("bbg-btn-secondary")
    clear_all_btn.add_class("bbg-btn-secondary")
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

    # Left: the strategies picker — search box above the dropdown.
    # Holder grows to fill the left panel's free vertical space; the dropdown
    # fills the holder, so it reaches the bottom of the container regardless of
    # the (stretched) panel height.
    ticker_holder = W.Box(
        [ticker_w],
        layout=W.Layout(
            width="100%",
            flex="1 1 auto",
            min_height="220px",
            display="flex",
        ),
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
        [_section_label("Strategies"), search_w, ticker_holder],
        layout=W.Layout(
            width="38%",
            padding="8px",
            border=f"1px solid {Color.BORDER}",
            display="flex",
            flex_flow="column",
        ),
    )

    # Right: filter panel — Refresh prices on top, then a pill header bar whose
    # buttons swap which filter dimension's values are shown below.
    date_range_row = W.HBox(
        [
            live_min,
            W.HTML("<div style='padding:0 6px;font-size:16px;'>–</div>"),
            live_max,
        ],
        layout=W.Layout(width="100%", align_items="center"),
    )
    characteristics_view = W.VBox(
        [
            _section_label("Launch date"),
            date_range_row,
            _section_label("Currency"),
            currency_dd,
        ],
        layout=W.Layout(width="100%", padding="2px 4px"),
    )

    quant_view = W.VBox(
        [
            W.HBox([q_period], layout=W.Layout(width="100%", align_items="center")),
            *quant.rows,
        ],
        layout=W.Layout(width="100%", padding="2px 4px"),
    )

    filter_views: dict[str, W.Widget] = {
        "Asset Class": asset_content,
        "Category": cat_content,
        "Theme": theme_content,
        "Return Type": ret_content,
        "Characteristics": characteristics_view,
        "Quantitative": quant_view,
    }
    filter_btns = {
        label: _make_tab_button(label, active=(i == 0), width="auto", height="32px")
        for i, label in enumerate(filter_views)
    }
    filter_header_row = W.HBox(
        list(filter_btns.values()),
        layout=W.Layout(
            width="100%",
            flex_flow="row wrap",
            margin="2px 0 6px 0",
        ),
    )
    filter_content = W.Box(
        [filter_views["Asset Class"]],
        layout=W.Layout(width="100%", min_height="250px"),
    )

    # The currently visible filter dimension (on `state`) drives "Clear section".
    def _activate_filter(label: str) -> None:
        state.active_filter = label
        for lbl, btn in filter_btns.items():
            _style_tab_button(btn, active=(lbl == label))
        filter_content.children = (filter_views[label],)

    for label, btn in filter_btns.items():
        btn.on_click(lambda _b, lbl=label: _activate_filter(lbl))

    # Maps each checkbox-based filter dimension to its checkboxes. The
    # Characteristics view clears its date range instead. Clearing a value
    # widget fires its `_on_filter_change` observer, so the dropdown re-narrows
    # automatically — no manual recompute needed.
    filter_checks = {
        "Asset Class": asset_checks,
        "Category": cat_checks,
        "Theme": theme_checks,
        "Return Type": ret_checks,
    }

    def _clear_quant() -> None:
        for op, box in quant.specs.values():
            box.value = ""
            op.value = "≥"

    def _clear_section(_b=None) -> None:
        label = state.active_filter
        if label == "Characteristics":
            live_min.value = None
            live_max.value = None
            currency_dd.value = "All"
        elif label == "Quantitative":
            _clear_quant()
        else:
            for c in filter_checks[label]:
                c.value = False

    def _clear_all(_b=None) -> None:
        for checks in filter_checks.values():
            for c in checks:
                c.value = False
        live_min.value = None
        live_max.value = None
        currency_dd.value = "All"
        _clear_quant()
        search_w.value = ""
        # Snap the analysis date range back to its full overlap span. The bounds
        # themselves re-derive from the selection on the next Refresh prices.
        if state.cur_bound_start is not None and state.cur_bound_end is not None:
            state.sync_guard = True
            try:
                range_min_box.value = state.cur_bound_start
                range_max_box.value = state.cur_bound_end
            finally:
                state.sync_guard = False

    clear_section_btn.on_click(_clear_section)
    clear_all_btn.on_click(_clear_all)

    action_row = W.HBox(
        [apply_btn, clear_section_btn, clear_all_btn],
        layout=W.Layout(width="100%", margin="0 0 6px 0"),
    )

    right_panel = W.VBox(
        [action_row, filter_header_row, filter_content],
        layout=W.Layout(
            width="60%",
            padding="8px",
            border=f"1px solid {Color.BORDER}",
        ),
    )
    filter_box = W.HBox(
        [left_panel, right_panel],
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
        options=[
            ("1W", WEEK_WINDOW),
            ("1M", MONTH_WINDOW),
            ("3M", QUARTER_WINDOW),
            ("6M", HALF_YEAR_WINDOW),
        ],
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
    # (see `_render_universe_grid`). Window / Lookback values are trading-day
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
        options=[
            ("1W", WEEK_WINDOW),
            ("1M", MONTH_WINDOW),
            ("3M", QUARTER_WINDOW),
            ("6M", HALF_YEAR_WINDOW),
        ],
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

    def _regime_bucket_options(regime_type: str) -> list[tuple[str, object]]:
        """Bucket-dropdown options for a regime: ``(label, (low, high))`` for the
        fixed-level mode, ``(label, tercile_key)`` for the tercile modes."""
        spec = REGIME_SPECS[regime_type]
        if spec.get("mode") == "level":
            return [(label, (low, high)) for label, low, high in spec["buckets"]]
        return [(label, key) for label, key in spec["bucket_labels"]]

    regime_type_dd = W.Dropdown(
        options=list(REGIME_SPECS.keys()),
        value="Volatility",
        description="Type",
        style={"description_width": "60px"},
        layout=W.Layout(width="240px"),
    )
    # Conditional indicator-source dropdown — benchmark for Trend, region for
    # Rate-level; hidden (via `_sync_regime_controls`) for regimes with no
    # `selector` (Volatility / Risk regime).
    regime_selector_dd = W.Dropdown(
        options=[("—", "")],
        value="",
        description="Source",
        style={"description_width": "60px"},
        layout=W.Layout(width="240px"),
    )
    _init_buckets = _regime_bucket_options("Volatility")
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

    def _activate_platform_tab(which: str) -> None:
        for key, (pill, _controls, _fig) in _analytics_tabs.items():
            _style_tab_button(pill, active=(key == which))
        _pill, controls, fig = _analytics_tabs[which]
        tab_controls_box.children = (controls,)
        chart_box.children = (fig,)

    sunburst_pill.on_click(lambda _b: _activate_platform_tab("sunburst"))
    regime_pill.on_click(lambda _b: _activate_platform_tab("regime"))
    factor_pill.on_click(lambda _b: _activate_platform_tab("factor"))

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

    def _render_universe_grid(_change=None) -> None:
        """Render the all-catalog grid with the dynamic z-score column from the
        current Metric/Window/Lookback dropdowns. Reads the cached perf table
        (`state.universe_up`) and computes only the z-score column live from the
        already-fetched `arp_universe_prices` — no BQL, no full recompute. The
        dropdown observers and the load/refresh paths both call this."""
        if state.arp_universe_prices.empty:
            return
        try:
            zcol = rolling_metric_zscore(
                state.arp_universe_prices,
                metric=z_metric_dd.value,
                window=z_window_dd.value,
                zscore_window=z_lookback_dd.value,
            )
            zlabel = f"{z_metric_dd.label} {z_window_dd.label}/{z_lookback_dd.label}"
            _update_universe_grid(
                state.universe_grid, meta, state.universe_up, zcol=zcol, zlabel=zlabel
            )
        except Exception:
            state.init_errors.append(
                f"all-catalog grid z-score render failed:\n{traceback.format_exc()}"
            )

    for _dd in (z_metric_dd, z_window_dd, z_lookback_dd):
        _dd.observe(_render_universe_grid, names="value")

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

    def _render_factor_scatter(_change=None) -> None:
        """Render the Platform 3D factor-beta scatter (β to the equity risk
        premium, term premium, and trend factor, per strategy, colored by asset
        class) at the currently-selected lookback. Computes live from the
        fetched cache — the factor series from `universe_prices`, per-strategy
        returns from `arp_universe_prices` — so the lookback toggle re-slices
        only, no BQL. No in-figure title; the "Factor exposures" section header
        stands alone (v0.7.1)."""
        if state.arp_universe_prices.empty or state.universe_prices.empty:
            return
        try:
            _update_factor_scatter(
                factor_scatter_fig,
                state.arp_universe_prices,
                state.universe_prices,
                meta,
                years=lookback_selector.value / TRADING_DAYS_PER_YEAR,
            )
        except Exception:
            state.init_errors.append(
                f"factor-beta scatter render failed:\n{traceback.format_exc()}"
            )

    def _render_sunburst(_change=None) -> None:
        """Render the Platform asset class → theme → ticker sunburst from the
        Metric/Window Z-score controls + the shared lookback: arcs sized by
        gross-|z| share, colored by the level-averaged z. Computes live from the
        ARP-only cache via `platform_sunburst_frame` — the controls re-slice
        only, no BQL. No in-figure title; the active tab labels the chart."""
        if state.arp_universe_prices.empty:
            return
        try:
            _update_sunburst(
                sunburst_fig,
                state.arp_universe_prices,
                meta,
                metric=sb_metric_dd.value,
                window=sb_window_dd.value,
                lookback=lookback_selector.value,
                label=f"{sb_window_dd.label} {sb_metric_dd.label}",
            )
        except Exception:
            state.init_errors.append(
                f"sunburst render failed:\n{traceback.format_exc()}"
            )

    # --- Regime Analysis closures: live re-slice of the cache on the regime /
    # source / bucket dropdowns and the shared lookback toggle — no BQL.
    def _regime_indicator() -> pd.Series | None:
        """The regime indicator series from the cache, per the active regime's
        mode, or None when its ticker(s) are absent from the fetch (→
        unconditioned all-days view):

        - ``level`` — the raw indicator level (Volatility = VIX).
        - ``autocorr_tercile`` — the selected benchmark's rolling return autocorr.
        - ``level_tercile`` — the selected region's rate level.
        """
        spec = REGIME_SPECS.get(regime_type_dd.value, {})
        mode = spec.get("mode")
        prices = state.universe_prices
        if mode == "autocorr_tercile":
            ticker = regime_selector_dd.value
            if not ticker or ticker not in prices.columns:
                return None
            rets = daily_returns(prices[[ticker]])[ticker]
            return rolling_autocorr(rets, window=spec.get("autocorr_window", 21))
        ticker = (
            regime_selector_dd.value if mode == "level_tercile" else spec.get("ticker")
        )
        if not ticker or ticker not in prices.columns:
            return None
        return prices[ticker]

    def _resolve_regime_bucket() -> tuple[float | None, float | None]:
        """The ``(low, high)`` bounds for the active bucket. Fixed-level regimes
        read the tuple straight off the bucket dropdown; tercile regimes derive
        the bounds from the live indicator's 1/3 & 2/3 quantiles over the
        lookback window (`tercile_bounds`). ``(None, None)`` when no indicator is
        available (→ unconditioned all-days view)."""
        spec = REGIME_SPECS.get(regime_type_dd.value, {})
        if spec.get("mode") == "level":
            low, high = regime_bucket_dd.value
            return (low, high)
        indicator = _regime_indicator()
        if indicator is None:
            return (None, None)
        return tercile_bounds(
            indicator.tail(lookback_selector.value), regime_bucket_dd.value
        )

    def _render_regime_scatter(_change=None) -> None:
        """Render the regime risk/return scatter at the current regime / source /
        bucket + lookback, live from the cache (no BQL)."""
        if state.arp_universe_prices.empty:
            return
        try:
            low, high = _resolve_regime_bucket()
            _update_regime_scatter(
                regime_scatter_fig,
                state.arp_universe_prices,
                _regime_indicator(),
                meta,
                low=low,
                high=high,
                lookback=lookback_selector.value,
            )
        except Exception:
            state.init_errors.append(
                f"regime scatter render failed:\n{traceback.format_exc()}"
            )

    def _sync_regime_controls(_change=None) -> None:
        # Repopulate the bucket dropdown for the active regime's mode and show /
        # hide the indicator-source dropdown (only regimes carrying a `selector`).
        spec = REGIME_SPECS.get(regime_type_dd.value, {})
        selector = spec.get("selector", [])
        if selector:
            regime_selector_dd.options = selector
            regime_selector_dd.value = selector[0][1]
            regime_selector_dd.layout.display = ""
        else:
            regime_selector_dd.layout.display = "none"
        options = _regime_bucket_options(regime_type_dd.value)
        regime_bucket_dd.options = options
        regime_bucket_dd.value = options[0][1]

    def _on_regime_type(_change=None) -> None:
        _sync_regime_controls()
        _render_regime_scatter()

    regime_type_dd.observe(_on_regime_type, names="value")
    regime_selector_dd.observe(lambda _c: _render_regime_scatter(), names="value")
    regime_bucket_dd.observe(lambda _c: _render_regime_scatter(), names="value")
    _sync_regime_controls()

    # The shared lookback drives all three analytics tabs (the sunburst now
    # shares it too — its own lookback dropdown was removed in the tab rework).
    for _render in (_render_factor_scatter, _render_regime_scatter, _render_sunburst):
        lookback_selector.observe(_render, names="value")

    # The sunburst's own Metric/Window controls re-render only the sunburst.
    for _dd in (sb_metric_dd, sb_window_dd):
        _dd.observe(_render_sunburst, names="value")

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
            _render_universe_grid()
            _render_factor_scatter()
            _render_sunburst()
            _render_regime_scatter()
            _log(f"universe grid populated in {time.perf_counter() - t_grid:.2f}s")
        except Exception:
            state.init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
        _set_progress(85, "Building catalog…")
    else:
        state.arp_universe_prices = pd.DataFrame()
        state.universe_up = pd.DataFrame()

    def _quant_thresholds() -> dict[str, tuple[str, float]]:
        """Active quant filters as `{metric: (operator, value)}`; blank = off."""
        out: dict[str, tuple[str, float]] = {}
        for name, (op, box) in quant.specs.items():
            raw = (box.value or "").strip()
            if not raw:
                continue
            try:
                out[name] = (op.value, float(raw))
            except ValueError:
                continue
        return out

    def _quant_keep(candidates: pd.Index) -> pd.Index:
        """Tickers (among `candidates`) passing the active ≥/≤ thresholds.

        Metrics are computed from the already-fetched ARP prices — no BQL. If
        the cache is empty or no thresholds are set, every candidate passes.
        """
        thresholds = _quant_thresholds()
        if not thresholds or state.arp_universe_prices.empty:
            return candidates
        prices = state.arp_universe_prices.reindex(columns=candidates).dropna(
            how="all", axis=1
        )
        if prices.shape[1] == 0:
            return candidates
        years = quant.period_dd.value
        # Non-benchmark metrics from the shared table; the benchmark-based ones
        # (Beta / Treynor / Jensen) are recomputed each against its own dropdown.
        # Compute returns once and share them with quant_metrics_table.
        rets = daily_returns(prices)
        qt = quant_metrics_table(prices, None, years, returns=rets)
        qt["Beta"] = ann_beta(
            rets, state.universe_prices.get(quant.bench_dd["Beta"].value), years
        )
        qt["Treynor"] = treynor_ratio(
            rets,
            prices,
            state.universe_prices.get(quant.bench_dd["Treynor"].value),
            years,
        )
        qt["Jensen"] = jensen_alpha(
            rets,
            prices,
            state.universe_prices.get(quant.bench_dd["Jensen"].value),
            years,
        )
        if "Z" in thresholds:
            # Cross-sectional z of the base metric, computed over the Z-Score's
            # own window (independent of the Period); recompute over that window,
            # threading the base metric's benchmark when it's Beta/Treynor/Jensen.
            z_metric = quant.z_metric_dd.value
            z_years = quant.z_window_dd.value / TRADING_DAYS_PER_YEAR
            z_bench = (
                state.universe_prices.get(quant.bench_dd[z_metric].value)
                if z_metric in quant.bench_dd
                else None
            )
            zt = quant_metrics_table(prices, z_bench, z_years, returns=rets)
            qt["Z"] = zscore_cross_section(zt[z_metric])
        keep = qt.index
        for name, (op, value) in thresholds.items():
            col = qt[name]
            mask = col >= value if op == "≥" else col <= value
            keep = keep.intersection(qt.index[mask])
        return keep

    def _on_filter_change(_change=None):
        filtered = apply_filters(
            meta,
            asset_classes=asset_get(),
            categories=cat_get(),
            themes=theme_get(),
            return_types=ret_get(),
            currencies=currency_get(),
            live_date_min=live_min.value,
            live_date_max=live_max.value,
        )
        query = (search_w.value or "").strip().lower()
        if query:
            mask = filtered["ticker"].str.lower().str.contains(
                query, regex=False
            ) | filtered["name"].str.lower().str.contains(query, regex=False)
            visible = filtered.loc[mask]
        else:
            visible = filtered

        quant_keep = _quant_keep(pd.Index(visible["ticker"]))
        visible = visible.loc[visible["ticker"].isin(quant_keep)]

        selected = list(state.ticker_w.value)
        keep_selected = filtered.loc[filtered["ticker"].isin(selected)]
        combined = pd.concat([visible, keep_selected]).drop_duplicates(subset="ticker")
        combined = combined.sort_values("ticker").reset_index(drop=True)
        state.ticker_w.options = _ticker_options(combined)
        state.ticker_w.value = tuple(
            t for t in selected if t in combined["ticker"].values
        )

    for cb in (*asset_checks, *cat_checks, *theme_checks, *ret_checks):
        cb.observe(_on_filter_change, names="value")
    for w in (live_min, live_max, search_w, currency_dd):
        w.observe(_on_filter_change, names="value")
    quant_inputs = [q_period, q_z_metric, q_z_window, *quant.bench_dd.values()]
    for op, box in quant.specs.values():
        quant_inputs += [op, box]
    for w in quant_inputs:
        w.observe(_on_filter_change, names="value")

    def _clear_pane(pane: SimpleNamespace) -> None:
        _update_line(pane.line_fig, pd.DataFrame(), meta)
        _update_outperformance(
            pane.outperf_fig, pd.DataFrame(), meta, benchmark_label=""
        )
        _update_sharpe_line(pane.sharpe_fig, pd.DataFrame(), meta)
        _update_heatmap(pane.heat_fig, pd.DataFrame())
        _update_scatter(pane.scatter_fig, pd.DataFrame(), pd.DataFrame(), meta)
        _update_drawdown(pane.dd_fig, pd.DataFrame(), meta)
        _update_rolling_ref(
            pane.rcorr_fig,
            pd.DataFrame(),
            meta,
            title_prefix="Rolling Correlation",
            benchmark_label="",
        )
        _update_rolling_ref(
            pane.rbeta_fig,
            pd.DataFrame(),
            meta,
            title_prefix="Rolling Beta",
            benchmark_label="",
        )
        _update_return_dist(
            pane.retdist_fig,
            pane.retdist_stats_grid,
            pd.DataFrame(),
            pd.DataFrame(),
            meta,
        )
        # No selection -> no view holds current data; the lazy picker observer
        # no-ops while cur_prep is None, so picks just swap to cleared figures.
        pane.fresh = set()

    # The four benchmark-dependent charts are each rendered by a small helper
    # over the shared `(pane, prep, win_start, win_end, errors)` signature, so
    # the same code serves both the full recompute (`_render_pane`) and the
    # live benchmark/regime observers (`_bind_live_controls`). Each slices its
    # benchmark series from the already-fetched `state.universe_prices` — no
    # BQL fetch.
    def _render_heatmap(
        pane: SimpleNamespace,
        prep: SimpleNamespace,
        win_start: pd.Timestamp,
        win_end: pd.Timestamp,
        errors: list[str],
    ) -> None:
        # Correlation heatmap, three cases (per-pane, so the panes stay
        # independent): Regime on → conditioned on the benchmark-return tail with
        # the benchmark in the matrix; Benchmark on / Regime off → full-sample
        # correlation with the benchmark added (v0.8.9); neither → plain
        # full-sample correlation of the selected strategies (`prep.cm`). The two
        # benchmark cases differ only in (pct, direction, memo key, title); both
        # build the matrix through the single `heatmap_corr_matrix` helper, which
        # always pins the benchmark last, so the left and right panes can never
        # disagree on the row/column order.
        if pane.heat_regime_chk.value:
            hm_bench_ticker = pane.heat_dd.value
            direction = pane.heat_dir.value  # ">" -> "up", "<" -> "down"
            pct_int = pane.heat_pct.value
            memo_key = ("heatmap", hm_bench_ticker, direction, pct_int)
            tail_lbl = "worst" if direction == "down" else "best"
            title = (
                f"Correlation — {hm_bench_ticker} {tail_lbl} "
                f"{pct_int}% days ({LOOKBACK_YEARS}Y)"
            )
        elif pane.heat_benchmark_chk.value:
            # Benchmark on, Regime off: full-sample correlation (pct=100% keeps
            # every day) with the benchmark added as the last row/column.
            hm_bench_ticker = pane.heat_dd.value
            direction = "down"
            pct_int = 100
            memo_key = ("heatmap", hm_bench_ticker, "incl", 100)
            title = f"Correlation — incl {hm_bench_ticker} ({LOOKBACK_YEARS}Y)"
        else:
            _update_heatmap(
                pane.heat_fig,
                prep.cm,
                title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
            )
            return

        try:

            def _compute():
                hm_bench_prices = state.universe_prices.get(hm_bench_ticker)
                if hm_bench_prices is None or hm_bench_prices.dropna().empty:
                    raise ValueError(
                        f"No price data for benchmark {hm_bench_ticker!r}."
                    )
                hm_bench_window = hm_bench_prices.loc[win_start:win_end]
                hm_bench_returns = daily_returns(hm_bench_window.to_frame()).iloc[:, 0]
                return heatmap_corr_matrix(
                    prep.rets,
                    hm_bench_returns,
                    pct=pct_int / 100.0,
                    direction=direction,
                )

            cm = state.memo.get_or_compute(memo_key, _compute)
            _update_heatmap(pane.heat_fig, cm, title=title)
        except Exception:
            errors.append(traceback.format_exc())
            _update_heatmap(pane.heat_fig, pd.DataFrame())

    def _render_rolling_corr(
        pane: SimpleNamespace,
        prep: SimpleNamespace,
        win_start: pd.Timestamp,
        win_end: pd.Timestamp,
        errors: list[str],
    ) -> None:
        rc_bench_ticker = pane.rcorr_dd.value
        try:

            def _compute_rcorr():
                rc_bench_prices = state.universe_prices.get(rc_bench_ticker)
                if rc_bench_prices is None or rc_bench_prices.dropna().empty:
                    raise ValueError(
                        f"No price data for benchmark {rc_bench_ticker!r}."
                    )
                rc_bench_window = rc_bench_prices.loc[win_start:win_end]
                rc_bench_returns = daily_returns(rc_bench_window.to_frame()).iloc[:, 0]
                return rolling_correlation(prep.rets, rc_bench_returns)

            rc = state.memo.get_or_compute(("rcorr", rc_bench_ticker), _compute_rcorr)
            _update_rolling_ref(
                pane.rcorr_fig,
                rc,
                meta,
                title_prefix="Rolling Correlation",
                benchmark_label=rc_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

    def _render_rolling_beta(
        pane: SimpleNamespace,
        prep: SimpleNamespace,
        win_start: pd.Timestamp,
        win_end: pd.Timestamp,
        errors: list[str],
    ) -> None:
        rb_bench_ticker = pane.rbeta_dd.value
        try:

            def _compute_rbeta():
                rb_bench_prices = state.universe_prices.get(rb_bench_ticker)
                if rb_bench_prices is None or rb_bench_prices.dropna().empty:
                    raise ValueError(
                        f"No price data for benchmark {rb_bench_ticker!r}."
                    )
                rb_bench_window = rb_bench_prices.loc[win_start:win_end]
                rb_bench_returns = daily_returns(rb_bench_window.to_frame()).iloc[:, 0]
                return rolling_beta(prep.rets, rb_bench_returns)

            rb = state.memo.get_or_compute(("rbeta", rb_bench_ticker), _compute_rbeta)
            _update_rolling_ref(
                pane.rbeta_fig,
                rb,
                meta,
                title_prefix="Rolling Beta",
                benchmark_label=rb_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

    def _render_outperf(
        pane: SimpleNamespace,
        prep: SimpleNamespace,
        win_start: pd.Timestamp,
        win_end: pd.Timestamp,
        errors: list[str],
    ) -> None:
        # Outperformance: cumulative excess return vs the benchmark (prices,
        # not returns — every strategy series starts at 0).
        op_bench_ticker = pane.outperf_dd.value
        try:

            def _compute_outperf():
                op_bench_prices = state.universe_prices.get(op_bench_ticker)
                if op_bench_prices is None or op_bench_prices.dropna().empty:
                    raise ValueError(
                        f"No price data for benchmark {op_bench_ticker!r}."
                    )
                op_bench_window = op_bench_prices.loc[win_start:win_end]
                return excess_cum_return(prep.sel_window, op_bench_window)

            oc = state.memo.get_or_compute(
                ("outperf", op_bench_ticker), _compute_outperf
            )
            _update_outperformance(
                pane.outperf_fig,
                oc,
                meta,
                benchmark_label=op_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

    def _render_one(
        pane: SimpleNamespace,
        label: str,
        prep: SimpleNamespace,
        win_start: pd.Timestamp,
        win_end: pd.Timestamp,
        errors: list[str],
    ) -> None:
        # Populate the single analysis view named `label` from `prep`. Lazy
        # rendering (Workstream D) calls this for only the mounted view per
        # recompute and builds the others on first pick.
        if label == "Cumulative Performance":
            _update_line(pane.line_fig, prep.perf, meta)
        elif label == "1Y Sharpe-z Line":
            _update_sharpe_line(pane.sharpe_fig, prep.sz_series, meta)
        elif label == "Risk / Return":
            _update_scatter(pane.scatter_fig, prep.sel_window, prep.rets, meta)
        elif label == "Drawdown":
            _update_drawdown(pane.dd_fig, prep.dd, meta)
        elif label == "Return Distribution":
            _update_return_dist(
                pane.retdist_fig,
                pane.retdist_stats_grid,
                prep.rets,
                prep.rd_stats,
                meta,
            )
        elif label == "Correlation Heatmap":
            _render_heatmap(pane, prep, win_start, win_end, errors)
        elif label == "Rolling Correlation":
            _render_rolling_corr(pane, prep, win_start, win_end, errors)
        elif label == "Rolling Beta":
            _render_rolling_beta(pane, prep, win_start, win_end, errors)
        elif label == "Outperformance":
            _render_outperf(pane, prep, win_start, win_end, errors)

    def _render_pane(
        pane: SimpleNamespace,
        prep: SimpleNamespace,
        win_start: pd.Timestamp,
        win_end: pd.Timestamp,
        errors: list[str],
    ) -> None:
        # Lazy (Workstream D): render only the currently-mounted view; the other
        # eight are built on first pick (see _bind_lazy_render) and stay fresh
        # until the next recompute resets `pane.fresh`.
        label = pane.picker.value
        _render_one(pane, label, prep, win_start, win_end, errors)
        pane.fresh = {label}

    def _bind_lazy_render(pane: SimpleNamespace) -> None:
        # On a picker change, build the newly-shown view on demand if it hasn't
        # been rendered for the current slice yet (panes.py already swaps it into
        # view and syncs control visibility). No-op without a valid selection or
        # when the view is already fresh; errors are swallowed like the live
        # benchmark observers (a real failure resurfaces on the next Refresh).
        def _on_pick_render(change):
            label = change["new"]
            if state.cur_prep is None or label in pane.fresh:
                return
            _render_one(
                pane,
                label,
                state.cur_prep,
                state.cur_win_start,
                state.cur_win_end,
                [],
            )
            pane.fresh.add(label)

        pane.picker.observe(_on_pick_render, names="value")

    def _bind_live_controls(pane: SimpleNamespace) -> None:
        # Wire the per-pane benchmark dropdowns and Correlation-Heatmap regime
        # controls so changing one re-renders only its own chart, immediately,
        # from the slice persisted on `state` at the last recompute — no BQL
        # fetch, no full recompute, the other pane untouched. (Refresh prices
        # stays the only path that refetches and re-runs filters/selection.)
        def _make(render_fn):
            def _handler(_change):
                if state.cur_prep is None:
                    return  # no valid selection — nothing to redraw, no fetch
                # A single live chart swallows its errors: the helper's own
                # except-branch leaves the chart in a safe state, and a
                # genuinely broken benchmark still surfaces on the next
                # Refresh prices (where errors flow into the commentary block).
                render_fn(
                    pane,
                    state.cur_prep,
                    state.cur_win_start,
                    state.cur_win_end,
                    [],
                )

            return _handler

        pane.rcorr_dd.observe(_make(_render_rolling_corr), names="value")
        pane.rbeta_dd.observe(_make(_render_rolling_beta), names="value")
        pane.outperf_dd.observe(_make(_render_outperf), names="value")
        # The Benchmark/Regime checkboxes keep their visibility-sync observers
        # (in panes.py); this adds the data re-render on top. Toggling Benchmark
        # off re-renders plain full-sample (it also clears Regime in panes.py).
        for ctrl in (
            pane.heat_benchmark_chk,
            pane.heat_regime_chk,
            pane.heat_dd,
            pane.heat_dir,
            pane.heat_pct,
        ):
            ctrl.observe(_make(_render_heatmap), names="value")

    _WINDOW_LABELS = {
        WEEK_WINDOW: "Past Week",
        MONTH_WINDOW: "Past Month",
        QUARTER_WINDOW: "Past Quarter",
        HALF_YEAR_WINDOW: "Past 6 Months",
    }

    def _render_highlights_panel(window_days):
        """Render the whole-catalog Key Highlights panel at ``window_days``.

        Builds the superlatives (at the chosen window) + new-launch cards from
        the already-fetched ARP cache and writes ``state.highlights_w`` — no
        BQL, no selection. Shared by ``_recompute`` (initial/Refresh) and the
        live window-toggle observer; a compute failure surfaces in-place rather
        than blanking the panel."""
        try:
            window_start = pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)
            universe_window = state.arp_universe_prices.loc[
                state.arp_universe_prices.index >= window_start
            ]
            if universe_window.empty:
                state.highlights_w.value = _render_highlights([], [])
                return
            universe_rets = daily_returns(universe_window)
            superlatives = build_superlatives(
                meta, universe_window, universe_rets, window_days=window_days
            )
            launches = build_launch_cards(meta, state.arp_universe_prices, as_of=today)
            state.highlights_w.value = _render_highlights(
                superlatives,
                launches,
                window_label=_WINDOW_LABELS.get(window_days, "Past Month"),
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
                _clear_pane(state.pane_left)
                _clear_pane(state.pane_right)
            elif state.universe_prices.empty:
                state.last_sel_key = None
                state.cur_prep = None
                _set_date_bounds(None, reset=True)
                pane_errors.append(
                    "Universe price cache is empty — initial BQL fetch returned no rows."
                )
                _update_perf_grid(state.selected_perf_grid, pd.DataFrame(), meta)
                _clear_pane(state.pane_left)
                _clear_pane(state.pane_right)
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
                    _clear_pane(state.pane_left)
                    _clear_pane(state.pane_right)
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
                    _render_pane(state.pane_left, prep, win_start, win_end, pane_errors)
                    _render_pane(
                        state.pane_right, prep, win_start, win_end, pane_errors
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
            _render_universe_grid()
            _render_factor_scatter()
            _render_sunburst()
            _render_regime_scatter()
        except Exception:
            state.init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
        _set_progress(85, "Building catalog…")
        # No post-load toast on Refresh: the loading overlay already signals
        # progress, and the "Loaded N indices …" toast is reserved for the
        # dashboard's *initial* load. (A refresh failure still toasts, above.)
        _recompute()
        _render_single()
        _set_progress(100, "Ready", hidden=True)

    def _render_single(_change=None) -> None:
        """Re-render the Single Strategy tab's Section 1 from the cache. Bound to
        the picker / benchmark controls and called on load + Refresh. Reads the
        current (possibly re-pruned) `meta` and a 5Y window off `today`."""
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
    _bind_live_controls(state.pane_left)
    _bind_live_controls(state.pane_right)
    _bind_lazy_render(state.pane_left)
    _bind_lazy_render(state.pane_right)
    single_strategy.picker.observe(_render_single, names="value")
    single_strategy.bench_dd.observe(_render_single, names="value")
    single_strategy.bench_chk.observe(_render_single, names="value")

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
