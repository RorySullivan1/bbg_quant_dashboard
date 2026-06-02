from __future__ import annotations

import html
import time
import traceback
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as W
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from ipydatagrid import DataGrid, TextRenderer, VegaExpr

from .bql_client import _cache_path, fetch_prices
from .commentary import build_highlights
from .config import (
    ARP_SOLUTION_VALUES,
    BENCHMARK_TICKERS,
    DEFAULT_BENCHMARK,
    LEGAL_DISCLOSURE_PATH,
    LOGO_PATH,
    LOOKBACK_YEARS,
    PERFORMANCE_DISCLAIMER_PATH,
    SHARPE_WINDOW,
    TRADING_DAYS_PER_YEAR,
    WEEKLY_COMMENTARY_PATH,
)
from .data import apply_filters, load_metadata, unique_values
from .stats import (
    ann_beta,
    ann_return,
    ann_sharpe,
    ann_volatility,
    corr_matrix,
    cum_perf,
    daily_returns,
    drawdown_series,
    excess_cum_return,
    jensen_alpha,
    perf_table,
    quant_metrics_table,
    regime_corr_matrix,
    return_distribution_stats,
    rolling_beta,
    rolling_correlation,
    rolling_sharpe_zscore,
    sharpe_zscore,
    treynor_ratio,
    universe_perf,
    zscore_cross_section,
)
from .style import (
    LINE_PALETTE,
    Color,
    Font,
    FontSize,
    Sentiment,
    StatusTone,
    TabButtonTone,
)

# Uniform height for every chart that lives inside an analysis pane.
# `_perf_grid` / `_return_dist_stats_grid` / `_universe_grid` keep their
# own heights — they're tables, not charts.
CHART_HEIGHT = "520px"


ANALYSIS_OPTIONS: tuple[str, ...] = (
    "Cumulative Performance",
    "Outperformance",
    "1Y Sharpe-z Line",
    "Correlation Heatmap",
    "Risk / Return",
    "Drawdown",
    "Rolling Correlation",
    "Return Distribution",
    "Rolling Beta",
)


SHARPE_WINDOW_LABEL = (
    f"{SHARPE_WINDOW // TRADING_DAYS_PER_YEAR}Y"
    if SHARPE_WINDOW % TRADING_DAYS_PER_YEAR == 0
    else f"{SHARPE_WINDOW}d"
)


BANNER_HTML = (
    "<div style='display:flex;align-items:center;gap:16px;"
    f"padding:12px 16px;background:{Color.BRAND_NAVY};color:{Color.WHITE};'>"
    f"<div style='font-size:{FontSize.HERO};font-weight:600;'>"
    "Index Catalog Dashboard</div>"
    f"<div style='font-size:{FontSize.SMALL};opacity:0.75;'>"
    "Metadata · Performance · Risk</div>"
    "</div>"
)


def _banner() -> W.HBox:
    children: list[W.Widget] = []
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            children.append(W.Image(value=f.read(), format="png", width=48, height=48))
    children.append(W.HTML(BANNER_HTML, layout=W.Layout(flex="1 1 auto")))
    return W.HBox(
        children,
        layout=W.Layout(width="100%", align_items="center"),
    )


def _status_banner() -> W.HTML:
    return W.HTML(
        _render_status("Initializing…", tone=StatusTone.INFO),
        layout=W.Layout(width="100%"),
    )


def _render_status(text: str, *, tone: StatusTone) -> str:
    return (
        f"<div style='font-family:{Font.MONO};"
        f"font-size:{FontSize.LABEL};padding:6px 14px;"
        f"background:{tone.bg};border-bottom:1px solid {tone.border};"
        f"color:{tone.fg};'>"
        f"{html.escape(text)}"
        "</div>"
    )


def _checkbox_group(
    options: list[str],
) -> tuple[W.VBox, Callable[[], list[str]], list[W.Checkbox]]:
    """A scrollable list of value checkboxes for one filter dimension.

    Returns `(content_vbox, getter, checkboxes)`. The getter reads each
    checkbox's `.value` regardless of whether the content is currently the
    visible filter-type view, so `_on_filter_change` works the same way it did
    with the old toggle groups. No header — the filter-type pill button above
    the content area is the label now.
    """
    checks = {
        opt: W.Checkbox(
            value=False,
            description=opt,
            indent=False,
            layout=W.Layout(width="100%", margin="1px 0"),
        )
        for opt in options
    }
    content = W.VBox(
        list(checks.values()),
        layout=W.Layout(
            max_height="240px",
            overflow="auto",
            width="100%",
            padding="2px 4px",
        ),
    )
    return (
        content,
        (lambda: [v for v, c in checks.items() if c.value]),
        list(checks.values()),
    )


def _style_tab_button(btn: W.Button, *, active: bool) -> None:
    tone = TabButtonTone.ACTIVE if active else TabButtonTone.INACTIVE
    btn.style.button_color = tone.bg
    btn.style.text_color = tone.fg
    btn.style.font_weight = tone.weight


def _make_tab_button(
    label: str, *, active: bool, width: str = "240px", height: str = "40px"
) -> W.Button:
    btn = W.Button(
        description=label,
        layout=W.Layout(
            width=width,
            height=height,
            margin="0 6px 0 0",
        ),
    )
    _style_tab_button(btn, active=active)
    return btn


def _make_benchmark_dropdown(
    description: str = "Benchmark", *, default: str = DEFAULT_BENCHMARK
) -> W.Dropdown:
    """A per-pane benchmark selector. Every analysis-pane benchmark dropdown
    (Rolling Correlation / Rolling Beta / Outperformance / Correlation-Heatmap
    regime) is the same widget over `BENCHMARK_TICKERS`, so they share this
    factory."""
    return W.Dropdown(
        options=BENCHMARK_TICKERS,
        value=default,
        description=description,
        style={"description_width": "80px"},
        layout=W.Layout(width="320px"),
    )


def _make_analysis_pane(side_label: str) -> SimpleNamespace:
    """Build a self-contained analysis pane with all 9 figures pre-allocated.

    Returns a `SimpleNamespace` carrying every plotly `FigureWidget` the
    `_update_*` helpers need, plus the picker widget, the swap container,
    a `views` dict keyed by `ANALYSIS_OPTIONS` labels, and the root VBox.

    Plotly figures are independent widget instances; each pane owns its
    own set so the two panes can render the same analysis side-by-side
    without conflict. The Rolling-Correlation / Rolling-Beta benchmark
    dropdowns live on the same row as the analysis picker and toggle
    visibility based on the active analysis.
    """
    line_fig = _line_chart()
    outperf_fig = _outperformance_chart()
    sharpe_fig = _sharpe_line_chart()
    heat_fig = _heatmap()
    scatter_fig = _scatter_chart()
    dd_fig = _drawdown_chart()
    rcorr_fig = _rolling_ref_chart(
        title_prefix="Rolling Correlation",
        y_label="Correlation",
        ref_y=0.0,
    )
    rbeta_fig = _rolling_ref_chart(
        title_prefix="Rolling Beta",
        y_label="Beta",
        ref_y=1.0,
    )
    retdist_fig = _return_dist_chart()
    retdist_stats_grid = _return_dist_stats_grid()

    rcorr_benchmark_dd = _make_benchmark_dropdown()
    rbeta_benchmark_dd = _make_benchmark_dropdown()
    outperf_benchmark_dd = _make_benchmark_dropdown()

    # Correlation-Heatmap regime controls. The checkbox reveals a benchmark
    # selector, a Down/Up tail direction toggle, and a 0-100% (step 5) tail
    # size. When on, the heatmap is conditioned on the benchmark-return tail
    # and the benchmark is added to the matrix (see `_render_pane`). Read at
    # Refresh-prices time only, like the other per-pane benchmark dropdowns.
    heat_regime_chk = W.Checkbox(
        value=False,
        description="Regime filter",
        indent=False,
        layout=W.Layout(width="140px"),
    )
    heat_benchmark_dd = _make_benchmark_dropdown()
    heat_dir = W.ToggleButtons(
        options=["Down", "Up"],
        value="Down",
        layout=W.Layout(width="auto"),
    )
    heat_pct = W.Dropdown(
        options=[(f"{p}%", p) for p in range(0, 101, 5)],
        value=100,
        description="Tail",
        style={"description_width": "40px"},
        layout=W.Layout(width="160px"),
    )

    view_layout = W.Layout(width="100%", padding="4px")
    views: dict[str, W.Widget] = {
        "Cumulative Performance": W.VBox([line_fig], layout=view_layout),
        "Outperformance": W.VBox([outperf_fig], layout=view_layout),
        "1Y Sharpe-z Line": W.VBox([sharpe_fig], layout=view_layout),
        "Correlation Heatmap": W.VBox([heat_fig], layout=view_layout),
        "Risk / Return": W.VBox([scatter_fig], layout=view_layout),
        "Drawdown": W.VBox([dd_fig], layout=view_layout),
        "Rolling Correlation": W.VBox([rcorr_fig], layout=view_layout),
        "Return Distribution": W.VBox(
            [retdist_fig, retdist_stats_grid], layout=view_layout
        ),
        "Rolling Beta": W.VBox([rbeta_fig], layout=view_layout),
    }

    default_label = (
        "Cumulative Performance" if side_label == "left" else "Correlation Heatmap"
    )
    picker = W.Dropdown(
        options=list(ANALYSIS_OPTIONS),
        value=default_label,
        description="Analysis",
        style={"description_width": "70px"},
        layout=W.Layout(width="360px"),
    )

    def _sync_regime_controls() -> None:
        # The benchmark / direction / tail controls only matter on the
        # Correlation Heatmap view and only when the regime checkbox is on.
        show = picker.value == "Correlation Heatmap" and heat_regime_chk.value
        for w in (heat_benchmark_dd, heat_dir, heat_pct):
            w.layout.display = "" if show else "none"

    def _sync_benchmark_visibility(label: str) -> None:
        rcorr_benchmark_dd.layout.display = (
            "" if label == "Rolling Correlation" else "none"
        )
        rbeta_benchmark_dd.layout.display = "" if label == "Rolling Beta" else "none"
        outperf_benchmark_dd.layout.display = (
            "" if label == "Outperformance" else "none"
        )
        heat_regime_chk.layout.display = (
            "" if label == "Correlation Heatmap" else "none"
        )
        _sync_regime_controls()

    _sync_benchmark_visibility(default_label)
    heat_regime_chk.observe(lambda _c: _sync_regime_controls(), names="value")

    header_row = W.HBox(
        [
            picker,
            rcorr_benchmark_dd,
            rbeta_benchmark_dd,
            outperf_benchmark_dd,
            heat_regime_chk,
            heat_benchmark_dd,
            heat_dir,
            heat_pct,
        ],
        layout=W.Layout(
            width="100%",
            align_items="center",
            margin="0 0 6px 0",
        ),
    )
    stack = W.Box(
        [views[default_label]],
        layout=W.Layout(width="100%"),
    )

    def _on_pick(change):
        label = change["new"]
        _sync_benchmark_visibility(label)
        stack.children = (views[label],)

    picker.observe(_on_pick, names="value")

    root = W.VBox(
        [header_row, stack],
        layout=W.Layout(
            width="50%",
            padding="8px",
            border=f"1px solid {Color.SLATE_200}",
        ),
    )

    return SimpleNamespace(
        root=root,
        picker=picker,
        stack=stack,
        views=views,
        line_fig=line_fig,
        outperf_fig=outperf_fig,
        outperf_dd=outperf_benchmark_dd,
        sharpe_fig=sharpe_fig,
        heat_fig=heat_fig,
        heat_regime_chk=heat_regime_chk,
        heat_dd=heat_benchmark_dd,
        heat_dir=heat_dir,
        heat_pct=heat_pct,
        scatter_fig=scatter_fig,
        dd_fig=dd_fig,
        rcorr_fig=rcorr_fig,
        rcorr_dd=rcorr_benchmark_dd,
        rbeta_fig=rbeta_fig,
        rbeta_dd=rbeta_benchmark_dd,
        retdist_fig=retdist_fig,
        retdist_stats_grid=retdist_stats_grid,
    )


def build_app(verbose: bool = True) -> W.VBox:
    t0 = time.perf_counter()

    def _log(msg: str) -> None:
        if verbose:
            print(f"[{time.perf_counter() - t0:6.2f}s] {msg}", flush=True)

    meta = load_metadata()
    meta = meta[
        meta["solution"].astype(str).str.lower().isin(ARP_SOLUTION_VALUES)
    ].reset_index(drop=True)
    _log(f"loaded metadata: {len(meta)} tickers")

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

    def _q_row(label: str, *, trailing: W.Widget | None = None):
        op = W.Dropdown(options=["≥", "≤"], value="≥", layout=W.Layout(width="60px"))
        box = W.Text(placeholder="value", layout=W.Layout(width="100px"))
        children = [
            W.HTML(
                f"<div style='width:84px;font-size:{FontSize.LABEL};'>{html.escape(label)}</div>"
            ),
            op,
            box,
        ]
        if trailing is not None:
            children.append(trailing)
        row = W.HBox(
            children,
            layout=W.Layout(width="100%", align_items="center", margin="1px 0"),
        )
        return row, op, box

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
            [W.HTML("<div style='padding:0 6px;'>of</div>"), q_z_metric],
            layout=W.Layout(align_items="center"),
        ),
    )
    quant = SimpleNamespace(
        period_dd=q_period,
        z_metric_dd=q_z_metric,
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

    apply_btn = W.Button(
        description="Refresh prices",
        layout=W.Layout(flex="1 1 auto"),
    )
    # Green so the primary refresh action stands out from the secondary clear
    # buttons. Colour comes from the centralized style token, not button_style.
    apply_btn.style.button_color = Color.GREEN_600
    apply_btn.style.text_color = Color.WHITE
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
    status_w = _status_banner()

    def _set_status(text: str, tone: StatusTone = StatusTone.INFO) -> None:
        status_w.value = _render_status(text, tone=tone)

    def _format_loaded(
        df: pd.DataFrame, source: str, elapsed: float
    ) -> tuple[str, StatusTone]:
        n_tickers = df.shape[1]
        n_days = df.shape[0]
        if source == "cache":
            mtime = _cache_path(today).stat().st_mtime
            stamp = time.strftime("%H:%M · %m-%d", time.localtime(mtime))
            return (
                f"Loaded {n_tickers} indices · {n_days} trading days from cache ({stamp})",
                StatusTone.SUCCESS,
            )
        src_label = "BQL" if source == "bql" else "mock prices"
        return (
            f"Loaded {n_tickers} indices · {n_days} trading days · "
            f"fetched from {src_label} in {elapsed:.1f}s",
            StatusTone.SUCCESS,
        )

    def _section_label(text: str) -> W.HTML:
        return W.HTML(
            f"<div style='font-weight:600;font-size:{FontSize.LABEL};"
            f"margin:6px 4px 2px 4px;'>{html.escape(text)}</div>"
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
    left_panel = W.VBox(
        [_section_label("Strategies"), search_w, ticker_holder],
        layout=W.Layout(
            width="38%",
            padding="8px",
            border=f"1px solid {Color.SLATE_200}",
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

    # The currently visible filter dimension — drives "Clear section".
    active_filter = ["Asset Class"]

    def _activate_filter(label: str) -> None:
        active_filter[0] = label
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
        label = active_filter[0]
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
            border=f"1px solid {Color.SLATE_200}",
        ),
    )
    filter_box = W.HBox(
        [left_panel, right_panel],
        layout=W.Layout(width="100%", align_items="stretch"),
    )
    # The whole filter UI — the Strategies multi-select on the left and the
    # filter options on the right — collapses under a "Filters" accordion,
    # expanded by default.
    filters_accordion = W.Accordion(
        children=[filter_box],
        titles=("Filters",),
        selected_index=0,
        layout=W.Layout(width="100%"),
    )

    weekly_w = W.HTML(
        _render_weekly_commentary(_load_weekly_commentary(), date.today())
    )
    highlights_w = W.HTML(_render_highlights([]))
    universe_grid = _universe_grid()

    pane_left = _make_analysis_pane("left")
    pane_right = _make_analysis_pane("right")
    analysis_pane_row = W.HBox(
        [pane_left.root, pane_right.root],
        layout=W.Layout(width="100%", align_items="stretch"),
    )

    selected_perf_grid = _perf_grid()
    selected_perf_header = W.HTML(
        f"<div style='font-weight:600;font-size:{FontSize.BODY};"
        "margin:8px 12px 4px 12px;'>"
        "Selected-strategy performance"
        "</div>"
    )
    selected_perf_section = W.VBox(
        [selected_perf_header, selected_perf_grid],
        layout=W.Layout(width="100%", padding="4px 0 8px 0"),
    )

    commentary_box = W.VBox(
        [weekly_w, highlights_w],
        layout=W.Layout(width="100%", padding="12px 16px"),
    )

    universe_header = W.HTML(
        f"<div style='font-weight:600;font-size:{FontSize.BODY};"
        "margin:8px 12px 4px 12px;'>"
        "All-catalog performance"
        "</div>"
    )
    platform_panel = W.VBox(
        [universe_header, universe_grid],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )
    selected_panel = W.VBox(
        [filters_accordion, selected_perf_section, analysis_pane_row],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )

    platform_btn = _make_tab_button("Platform", active=True)
    selected_btn = _make_tab_button("Multi-Strategy Analysis", active=False)
    top_tab_bar = W.HBox(
        [platform_btn, selected_btn],
        layout=W.Layout(
            width="100%",
            padding="10px 16px 4px 16px",
            border_bottom=f"1px solid {Color.SLATE_200}",
        ),
    )
    top_tab_content = W.Box(
        [platform_panel],
        layout=W.Layout(width="100%"),
    )

    def _activate_tab(which: str) -> None:
        is_platform = which == "platform"
        _style_tab_button(platform_btn, active=is_platform)
        _style_tab_button(selected_btn, active=not is_platform)
        top_tab_content.children = (platform_panel if is_platform else selected_panel,)

    platform_btn.on_click(lambda _b: _activate_tab("platform"))
    selected_btn.on_click(lambda _b: _activate_tab("selected"))

    # Single BQL fetch at app-load time, bounded by LOOKBACK_YEARS. A wider
    # fetch (e.g. back to oldest live date) is too slow on the terminal — the
    # SI column in the all-catalog grid is therefore bounded by this window.
    today = date.today()
    universe_start = (pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)).date()

    universe_prices: pd.DataFrame = pd.DataFrame()
    init_errors: list[str] = []
    # Benchmarks ride along on the single startup fetch so the Rolling
    # Correlation / Rolling Beta tabs can slice them from the same cache.
    # They are excluded from the ARP-universe grid and the highlights cards
    # via reindex(columns=meta["ticker"]).
    fetch_tickers = list(meta["ticker"]) + list(BENCHMARK_TICKERS)
    _set_status(
        f"Fetching prices for {len(fetch_tickers)} indices ({universe_start} → {today})…",
        tone=StatusTone.INFO,
    )
    t_fetch = time.perf_counter()
    try:
        universe_prices, fetch_source = fetch_prices(
            fetch_tickers, universe_start, today
        )
        fetch_elapsed = time.perf_counter() - t_fetch
        text, tone = _format_loaded(universe_prices, fetch_source, fetch_elapsed)
        _set_status(text, tone=tone)
    except Exception:
        _set_status("Load failed — see error below", tone=StatusTone.ERROR)
        init_errors.append(
            f"Universe fetch ({universe_start} → {today}) failed:\n"
            f"{traceback.format_exc()}"
        )

    if not universe_prices.empty:
        # ARP universe view of the cache — used for the all-catalog grid and
        # the whole-catalog highlights so benchmark columns never leak in.
        arp_universe_prices = universe_prices.reindex(columns=meta["ticker"])
        t_perf = time.perf_counter()
        try:
            up = universe_perf(arp_universe_prices)
            _log(f"universe_perf computed in {time.perf_counter() - t_perf:.2f}s")
            t_grid = time.perf_counter()
            _update_universe_grid(universe_grid, meta, up)
            _log(f"universe grid populated in {time.perf_counter() - t_grid:.2f}s")
        except Exception:
            init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
    else:
        arp_universe_prices = pd.DataFrame()

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
        if not thresholds or arp_universe_prices.empty:
            return candidates
        prices = arp_universe_prices.reindex(columns=candidates).dropna(
            how="all", axis=1
        )
        if prices.shape[1] == 0:
            return candidates
        years = quant.period_dd.value
        # Non-benchmark metrics from the shared table; the benchmark-based ones
        # (Beta / Treynor / Jensen) are recomputed each against its own dropdown.
        qt = quant_metrics_table(prices, None, years)
        rets = daily_returns(prices)
        qt["Beta"] = ann_beta(
            rets, universe_prices.get(quant.bench_dd["Beta"].value), years
        )
        qt["Treynor"] = treynor_ratio(
            rets, prices, universe_prices.get(quant.bench_dd["Treynor"].value), years
        )
        qt["Jensen"] = jensen_alpha(
            rets, prices, universe_prices.get(quant.bench_dd["Jensen"].value), years
        )
        if "Z" in thresholds:
            qt["Z"] = zscore_cross_section(qt[quant.z_metric_dd.value])
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

        selected = list(ticker_w.value)
        keep_selected = filtered.loc[filtered["ticker"].isin(selected)]
        combined = pd.concat([visible, keep_selected]).drop_duplicates(subset="ticker")
        combined = combined.sort_values("ticker").reset_index(drop=True)
        ticker_w.options = _ticker_options(combined)
        ticker_w.value = tuple(t for t in selected if t in combined["ticker"].values)

    for cb in (*asset_checks, *cat_checks, *theme_checks, *ret_checks):
        cb.observe(_on_filter_change, names="value")
    for w in (live_min, live_max, search_w, currency_dd):
        w.observe(_on_filter_change, names="value")
    quant_inputs = [q_period, q_z_metric, *quant.bench_dd.values()]
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

    def _render_pane(
        pane: SimpleNamespace,
        prep: SimpleNamespace,
        universe_window_start: pd.Timestamp,
        errors: list[str],
    ) -> None:
        _update_line(pane.line_fig, prep.perf, meta)
        _update_sharpe_line(pane.sharpe_fig, prep.sz_series, meta)
        _update_scatter(pane.scatter_fig, prep.sel_window, prep.rets, meta)
        _update_drawdown(pane.dd_fig, prep.dd, meta)
        _update_return_dist(
            pane.retdist_fig,
            pane.retdist_stats_grid,
            prep.rets,
            prep.rd_stats,
            meta,
        )

        # Correlation heatmap: optionally conditioned on a benchmark-return
        # regime, with the benchmark added to the matrix. Computed per-pane so
        # the two panes stay independent (like the rolling-corr/beta blocks).
        if pane.heat_regime_chk.value:
            hm_bench_ticker = pane.heat_dd.value
            try:
                hm_bench_prices = universe_prices.get(hm_bench_ticker)
                if hm_bench_prices is None or hm_bench_prices.dropna().empty:
                    raise ValueError(
                        f"No price data for benchmark {hm_bench_ticker!r}."
                    )
                hm_bench_window = hm_bench_prices.loc[
                    hm_bench_prices.index >= universe_window_start
                ]
                hm_bench_returns = daily_returns(hm_bench_window.to_frame()).iloc[:, 0]
                direction = "up" if pane.heat_dir.value == "Up" else "down"
                pct = pane.heat_pct.value / 100.0
                cm = regime_corr_matrix(
                    prep.rets,
                    hm_bench_returns,
                    pct,
                    direction=direction,
                    include_benchmark=True,
                )
                tail_lbl = "worst" if direction == "down" else "best"
                title = (
                    f"Correlation — {hm_bench_ticker} {tail_lbl} "
                    f"{pane.heat_pct.value}% days ({LOOKBACK_YEARS}Y)"
                )
                _update_heatmap(pane.heat_fig, cm, title=title)
            except Exception:
                errors.append(traceback.format_exc())
                _update_heatmap(pane.heat_fig, pd.DataFrame())
        else:
            _update_heatmap(
                pane.heat_fig,
                prep.cm,
                title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
            )

        rc_bench_ticker = pane.rcorr_dd.value
        try:
            rc_bench_prices = universe_prices.get(rc_bench_ticker)
            if rc_bench_prices is None or rc_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {rc_bench_ticker!r}.")
            rc_bench_window = rc_bench_prices.loc[
                rc_bench_prices.index >= universe_window_start
            ]
            rc_bench_returns = daily_returns(rc_bench_window.to_frame()).iloc[:, 0]
            rc = rolling_correlation(prep.rets, rc_bench_returns)
            _update_rolling_ref(
                pane.rcorr_fig,
                rc,
                meta,
                title_prefix="Rolling Correlation",
                benchmark_label=rc_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

        rb_bench_ticker = pane.rbeta_dd.value
        try:
            rb_bench_prices = universe_prices.get(rb_bench_ticker)
            if rb_bench_prices is None or rb_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {rb_bench_ticker!r}.")
            rb_bench_window = rb_bench_prices.loc[
                rb_bench_prices.index >= universe_window_start
            ]
            rb_bench_returns = daily_returns(rb_bench_window.to_frame()).iloc[:, 0]
            rb = rolling_beta(prep.rets, rb_bench_returns)
            _update_rolling_ref(
                pane.rbeta_fig,
                rb,
                meta,
                title_prefix="Rolling Beta",
                benchmark_label=rb_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

        # Outperformance: cumulative excess return vs the benchmark (prices,
        # not returns — every strategy series starts at 0).
        op_bench_ticker = pane.outperf_dd.value
        try:
            op_bench_prices = universe_prices.get(op_bench_ticker)
            if op_bench_prices is None or op_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {op_bench_ticker!r}.")
            op_bench_window = op_bench_prices.loc[
                op_bench_prices.index >= universe_window_start
            ]
            oc = excess_cum_return(prep.sel_window, op_bench_window)
            _update_outperformance(
                pane.outperf_fig,
                oc,
                meta,
                benchmark_label=op_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

    def _recompute(_btn=None):
        highlights_html = ""
        # Surface any errors from the initial universe fetch so the user can
        # see what actually went wrong, not just the downstream "cache empty".
        for err in init_errors:
            highlights_html += _render_error(err)
        # Highlights are always whole-catalog (ARP only), regardless of selection.
        universe_window_start = pd.Timestamp(today) - pd.DateOffset(
            years=LOOKBACK_YEARS
        )
        try:
            if not arp_universe_prices.empty:
                universe_window = arp_universe_prices.loc[
                    arp_universe_prices.index >= universe_window_start
                ]
                if not universe_window.empty:
                    universe_rets = daily_returns(universe_window)
                    universe_sz = sharpe_zscore(universe_rets)
                    cards = build_highlights(
                        meta, universe_window, universe_rets, universe_sz
                    )
                    highlights_html += _render_highlights(cards)
        except Exception:
            highlights_html += _render_error(traceback.format_exc())

        pane_errors: list[str] = []
        try:
            tickers = list(ticker_w.value)
            if len(tickers) < 1:
                _update_perf_grid(selected_perf_grid, pd.DataFrame(), meta)
                _clear_pane(pane_left)
                _clear_pane(pane_right)
            elif universe_prices.empty:
                pane_errors.append(
                    "Universe price cache is empty — initial BQL fetch returned no rows."
                )
                _update_perf_grid(selected_perf_grid, pd.DataFrame(), meta)
                _clear_pane(pane_left)
                _clear_pane(pane_right)
            else:
                sel_full = universe_prices.reindex(columns=tickers)
                sel_window = sel_full.loc[sel_full.index >= universe_window_start]
                if sel_window.dropna(how="all").empty:
                    pane_errors.append(
                        f"No price data in the {LOOKBACK_YEARS}Y window for: {tickers}."
                    )
                    _update_perf_grid(selected_perf_grid, pd.DataFrame(), meta)
                    _clear_pane(pane_left)
                    _clear_pane(pane_right)
                else:
                    prep = SimpleNamespace(
                        sel_window=sel_window,
                        rets=daily_returns(sel_window),
                        perf=cum_perf(sel_window),
                        pt=perf_table(sel_window),
                        dd=drawdown_series(sel_window),
                    )
                    prep.sz_series = rolling_sharpe_zscore(prep.rets)
                    prep.cm = corr_matrix(prep.rets)
                    prep.rd_stats = return_distribution_stats(prep.rets)
                    _update_perf_grid(selected_perf_grid, prep.pt, meta)
                    _render_pane(pane_left, prep, universe_window_start, pane_errors)
                    _render_pane(pane_right, prep, universe_window_start, pane_errors)
        except Exception:
            pane_errors.append(traceback.format_exc())

        for err in pane_errors:
            highlights_html += _render_error(err)

        highlights_w.value = highlights_html or _render_highlights([])

    def _refresh_prices(_btn=None):
        nonlocal universe_prices, arp_universe_prices
        _set_status(
            f"Fetching prices for {len(fetch_tickers)} indices ({universe_start} → {today})…",
            tone=StatusTone.INFO,
        )
        t_refresh = time.perf_counter()
        try:
            universe_prices, source = fetch_prices(
                fetch_tickers, universe_start, today, use_cache=False
            )
        except Exception:
            _set_status("Load failed — see error below", tone=StatusTone.ERROR)
            init_errors.append(
                f"Universe refresh ({universe_start} → {today}) failed:\n"
                f"{traceback.format_exc()}"
            )
            _recompute()
            return
        elapsed = time.perf_counter() - t_refresh
        arp_universe_prices = universe_prices.reindex(columns=meta["ticker"])
        try:
            _update_universe_grid(
                universe_grid, meta, universe_perf(arp_universe_prices)
            )
        except Exception:
            init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
        text, tone = _format_loaded(universe_prices, source, elapsed)
        _set_status(text, tone=tone)
        _recompute()

    apply_btn.on_click(_refresh_prices)

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
            _banner(),
            status_w,
            commentary_box,
            top_tab_bar,
            top_tab_content,
            perf_disclaimer_w,
            legal_w,
        ],
        layout=W.Layout(width="100%"),
    )

    t_initial = time.perf_counter()
    _recompute()
    _log(f"initial recompute (selected viz) in {time.perf_counter() - t_initial:.2f}s")
    _log(f"build_app TOTAL: {time.perf_counter() - t0:.2f}s")
    return app


def _ticker_options(df: pd.DataFrame) -> list[tuple[str, str]]:
    return [(f"{r['ticker']} — {r['name']}", r["ticker"]) for _, r in df.iterrows()]


_CHART_HEIGHT_PX: int = int(CHART_HEIGHT.removesuffix("px"))


def _chart_layout(*, title: str, **overrides) -> dict:
    """Shared plotly Layout kwargs — Bloomberg/Barclays dark theme.

    Charts render on a near-black background (`Color.CHART_BG`) with
    white titles and light slate text. Axis grid/tick styling inherits
    from the `plotly_dark` template; we override only background, title,
    font color, and hover styling.

    Pass `xaxis`, `yaxis`, `hovermode`, `barmode`, `shapes`, `margin`,
    etc. via `overrides`.
    """
    base = dict(
        template="plotly_dark",
        paper_bgcolor=Color.CHART_BG.value,
        plot_bgcolor=Color.CHART_BG.value,
        height=_CHART_HEIGHT_PX,
        margin=dict(t=44, b=50, l=60, r=20),
        title=dict(
            text=title,
            font=dict(size=14, color=Color.CHART_TITLE.value),
            x=0.02,
            xanchor="left",
        ),
        showlegend=False,
        font=dict(family=Font.SANS.value, color=Color.CHART_TEXT.value, size=12),
        hoverlabel=dict(
            font_family=Font.SANS.value,
            bgcolor=Color.CHART_HOVER_BG.value,
            font_color=Color.CHART_TEXT.value,
            bordercolor=Color.CHART_AXIS.value,
        ),
    )
    base.update(overrides)
    return base


def _h_ref(y: float) -> dict:
    """Dashed horizontal reference line spanning the chart's full width."""
    return dict(
        type="line",
        xref="paper",
        x0=0,
        x1=1,
        yref="y",
        y0=y,
        y1=y,
        line=dict(color=Color.CHART_AXIS.value, dash="dash", width=1),
    )


def _line_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Cumulative Performance ({LOOKBACK_YEARS}Y)",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Rebased = 100"),
        )
    )


def _update_line_series(
    fig: go.FigureWidget,
    df: pd.DataFrame,
    *,
    value_format: str = ".2f",
    hover_suffix: str = "",
    tail_n: int | None = None,
    title: str | None = None,
) -> None:
    """Shared engine for every per-strategy line chart — cumulative
    performance, outperformance, Sharpe-z, drawdown, and rolling
    correlation/beta.

    Builds one `go.Scatter` per non-empty column using the positional
    `LINE_PALETTE`, then atomically swaps the figure's traces inside a
    `batch_update`. `value_format` / `hover_suffix` shape the hover y-value
    (".2%" for drawdown, a " pp" suffix for outperformance); `tail_n` keeps
    only the last N rows (the Sharpe-z 1Y window); `title`, when given, is
    written to the figure title (used by the benchmark-aware charts whose
    title depends on the selected benchmark, so it stays correct even on the
    empty-data path)."""
    cleaned = df.dropna(how="all") if not df.empty else df
    if tail_n is not None and not cleaned.empty:
        cleaned = cleaned.tail(tail_n)
    traces: list[go.Scatter] = []
    for i, col in enumerate(cleaned.columns):
        series = cleaned[col].dropna()
        if series.empty:
            continue
        label = _short_ticker(col)
        traces.append(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                name=label,
                line=dict(color=_palette_color(i), width=1.5),
                hovertemplate=(
                    f"{label}<br>%{{x|%Y-%m-%d}}<br>"
                    f"%{{y:{value_format}}}{hover_suffix}<extra></extra>"
                ),
            )
        )
    with fig.batch_update():
        fig.data = ()
        if traces:
            fig.add_traces(traces)
        if title is not None:
            fig.layout.title.text = title


def _update_line(fig: go.FigureWidget, perf: pd.DataFrame, meta: pd.DataFrame) -> None:
    _update_line_series(fig, perf)


def _outperformance_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Outperformance ({LOOKBACK_YEARS}Y)",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Excess return (pp)"),
            shapes=[_h_ref(0.0)],
        )
    )


def _update_outperformance(
    fig: go.FigureWidget,
    df: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    benchmark_label: str,
) -> None:
    """Render cumulative excess return per strategy vs the benchmark. Each
    series is in percentage points off a dashed zero baseline."""
    new_title = (
        f"Outperformance vs {benchmark_label} ({LOOKBACK_YEARS}Y)"
        if benchmark_label
        else f"Outperformance ({LOOKBACK_YEARS}Y)"
    )
    _update_line_series(fig, df, hover_suffix=" pp", title=new_title)


# ---- Perf grid (selected set) ---------------------------------------------


def _perf_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=80,  # default for numeric metric cols
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="240px"),
    )
    return grid


PERF_COLOR_COLUMN_NAME: str = "Chart Color"

# Column widths in pixels, keyed by the column's *leaf* label. The grid uses
# 2-level MultiIndex columns (Info / 1Y / 3Y / 5Y supercolumns over their
# leaves); `_build_perf_column_widths` emits ipydatagrid's "<level0>,<level1>"
# comma-joined keys from these. The descriptive text columns carry the slack
# that makes the grid fill a wide dashboard — ipydatagrid has no responsive
# stretch-to-container mode, so widths are set by hand to sum to ~full-HD
# width (~2014px incl. the 120px row header + metric columns).
_PERF_INFO_WIDTHS: dict[str, int] = {
    PERF_COLOR_COLUMN_NAME: 90,  # color swatch — wide enough to show header
    "Name": 360,
    "Asset Class": 180,
    "Theme": 280,
}
_PERF_METRIC_WIDTHS: dict[str, int] = {
    "Return": 88,
    "Vol": 76,
    "Sharpe": 72,
    "Max DD": 92,
}
_PERF_INFO_TEXT_COLS: frozenset[str] = frozenset({"Name", "Asset Class", "Theme"})


def _build_perf_column_widths(columns: pd.Index) -> dict[str, int]:
    """Map each MultiIndex column to a pixel width, keyed by ipydatagrid's
    "<level0>,<level1>" comma-joined field name (e.g. "Info,Name",
    "1Y,Return"). Info leaves take fixed widths; metric leaves
    (Return/Vol/Sharpe/Max DD) take one width each so 1Y/3Y/5Y stay aligned."""
    widths: dict[str, int] = {}
    for col in columns:
        leaf = col[-1] if isinstance(col, tuple) else col
        key = ",".join(str(p) for p in col) if isinstance(col, tuple) else str(col)
        if leaf in _PERF_INFO_WIDTHS:
            widths[key] = _PERF_INFO_WIDTHS[leaf]
        elif leaf in _PERF_METRIC_WIDTHS:
            widths[key] = _PERF_METRIC_WIDTHS[leaf]
    return widths


def _palette_color(i: int) -> str:
    return LINE_PALETTE[i % len(LINE_PALETTE)]


def _short_ticker(ticker: str) -> str:
    """Drop the BBG ' Index' suffix, leaving the core ticker (e.g. 'SPX')."""
    return ticker.removesuffix(" Index")


def _update_perf_grid(grid: DataGrid, pt: pd.DataFrame, meta: pd.DataFrame) -> None:
    if pt.empty:
        grid.data = pd.DataFrame()
        return
    info_block = _build_info_block(
        meta,
        pt.index,
        ["name", "asset_class", "theme"],
        {"name": "Name", "asset_class": "Asset Class", "theme": "Theme"},
    )
    # Per-row color swatch: each cell carries the hex string; the renderer
    # paints background + text the same color so it shows as a solid block —
    # the universal legend for every chart in the panes. It leads the Info
    # supercolumn so the grid acts as the legend left-to-right.
    info_block.insert(
        0, PERF_COLOR_COLUMN_NAME, [_palette_color(i) for i in range(len(pt))]
    )
    info_block.columns = pd.MultiIndex.from_product([["Info"], info_block.columns])
    perf = pt.copy()
    perf.columns = pd.MultiIndex.from_tuples(
        [(str(period), str(metric)) for period, metric in pt.columns]
    )
    combined = pd.concat([info_block, perf], axis=1)
    combined.index.name = "Ticker"
    grid.data = combined
    _apply_grid_styling(grid, combined.columns, widths=True)


def _build_info_block(
    meta: pd.DataFrame,
    tickers: pd.Index | None,
    columns: list[str],
    rename: dict[str, str],
    *,
    date_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Build a grid 'Info' block from metadata: index by ticker, optionally
    `reindex` to `tickers` (selected-set order), select `columns`, ISO-format
    any `date_cols`, then `rename` to display headers. Shared by the
    selected-strategy grid (3 cols, reindexed to the current selection) and
    the all-catalog grid (6 cols incl. a formatted live_date, all tickers)."""
    info = meta.set_index("ticker")
    if tickers is not None:
        info = info.reindex(tickers)
    info = info[columns].copy()
    for col in date_cols:
        info[col] = info[col].dt.strftime("%Y-%m-%d")
    return info.rename(columns=rename)


def _perf_renderers(columns: pd.Index) -> dict:
    text = TextRenderer()
    pct = TextRenderer(format=".2%")
    f2 = TextRenderer(format=".2f")
    color_swatch = TextRenderer(
        background_color=VegaExpr("cell.value"),
        text_color=VegaExpr("cell.value"),
    )
    renderers: dict = {}
    for col in columns:
        # Columns are flat strings in the selected-strategy grid
        # (e.g. "1Y Sharpe") but MultiIndex tuples in the all-catalog grid
        # (e.g. ("1Y", "Sharpe")). Match on the metric leaf either way so
        # `.endswith` is only ever called on a string.
        leaf = col[-1] if isinstance(col, tuple) else col
        if leaf == PERF_COLOR_COLUMN_NAME:
            renderers[col] = color_swatch
        elif leaf in _PERF_INFO_TEXT_COLS:
            renderers[col] = text
        elif leaf == "Sharpe" or leaf.endswith(" Sharpe"):
            renderers[col] = f2
        elif leaf in ("Return", "Vol", "Max DD") or leaf.endswith(
            (" Return", " Vol", " Max DD")
        ):
            renderers[col] = pct
        else:
            renderers[col] = text
    return renderers


def _apply_grid_styling(
    grid: DataGrid, columns: pd.Index, *, widths: bool = False
) -> None:
    """Wire the shared per-column renderers (text / pct / 2dp / color-swatch)
    onto a grid, and — for the selected-strategy grid — the hand-tuned
    MultiIndex column widths. The all-catalog grid uses uniform
    `base_column_size`, so it leaves `widths` off."""
    grid.renderers = _perf_renderers(columns)
    if widths:
        grid.column_widths = _build_perf_column_widths(columns)


# ---- Universe grid (full catalog) -----------------------------------------


def _universe_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=92,
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="360px"),
    )
    return grid


def _update_universe_grid(grid: DataGrid, meta: pd.DataFrame, up: pd.DataFrame) -> None:
    if meta.empty:
        grid.data = pd.DataFrame()
        return
    info = _build_info_block(
        meta,
        None,
        ["name", "asset_class", "category", "theme", "return_type", "live_date"],
        {
            "name": "Name",
            "asset_class": "Asset Class",
            "category": "Category",
            "theme": "Theme",
            "return_type": "Return Type",
            "live_date": "Live Date",
        },
        date_cols=("live_date",),
    )
    info.columns = pd.MultiIndex.from_product([["Info"], info.columns])

    if up.empty:
        combined = info
    else:
        up_norm = up.copy()
        up_norm.columns = pd.MultiIndex.from_tuples(
            [(str(a), str(b)) for a, b in up_norm.columns]
        )
        # Order: Info block first, then 1Y, 3Y, 5Y, SI.
        period_order = ["1Y", "3Y", "5Y", "SI"]
        present = [p for p in period_order if p in up_norm.columns.get_level_values(0)]
        up_norm = up_norm.reindex(columns=present, level=0)
        combined = info.join(up_norm.reindex(info.index))

    combined.index.name = "Ticker"
    grid.data = combined
    _apply_grid_styling(grid, combined.columns)


# ---- Heatmap --------------------------------------------------------------


def _heatmap() -> go.FigureWidget:
    return go.FigureWidget(
        data=[
            go.Heatmap(
                z=np.zeros((2, 2)),
                x=["", " "],
                y=["", " "],
                colorscale="RdBu",
                reversescale=True,
                zmin=-1,
                zmax=1,
                zmid=0,
                colorbar=dict(title="ρ", tickformat=".1f", thickness=14),
                hovertemplate="%{y} vs %{x}<br>ρ = %{z:.2f}<extra></extra>",
            )
        ],
        layout=_chart_layout(
            title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
            margin=dict(t=40, b=70, l=120, r=20),
            xaxis=dict(tickangle=-75, tickfont=dict(size=10)),
            yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        ),
    )


def _update_heatmap(
    fig: go.FigureWidget, cm: pd.DataFrame, title: str | None = None
) -> None:
    # Correlation needs at least 2 series; below that, fall back to a
    # blank 2x2 placeholder so the heatmap still renders.
    if cm.empty or cm.shape[0] < 2:
        cm = pd.DataFrame(np.zeros((2, 2)), index=["", " "], columns=["", " "])
    tickers = list(cm.columns)
    with fig.batch_update():
        fig.data[0].z = cm.values
        fig.data[0].x = tickers
        fig.data[0].y = tickers
        if title is not None:
            fig.layout.title.text = title


# ---- Sharpe z-score line chart (selected set, 1Y evolution) ----------------


def _sharpe_line_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"{SHARPE_WINDOW_LABEL} Rolling Sharpe — z-score (last 1Y)",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Sharpe z-score"),
            shapes=[_h_ref(0.0)],
        )
    )


def _update_sharpe_line(
    fig: go.FigureWidget, zser: pd.DataFrame, meta: pd.DataFrame
) -> None:
    _update_line_series(fig, zser, tail_n=TRADING_DAYS_PER_YEAR)


# ---- Risk / Return scatter (selected set) ----------------------------------


def _scatter_chart() -> go.FigureWidget:
    return go.FigureWidget(
        data=[
            go.Scatter(
                mode="markers",
                x=[],
                y=[],
                marker=dict(size=[], color=[], line=dict(width=0)),
                text=[],
                customdata=[],
                hovertemplate=(
                    "%{text}<br>Vol %{x:.2%}<br>Return %{y:.2%}"
                    "<br>Sharpe %{customdata:.2f}<extra></extra>"
                ),
            )
        ],
        layout=_chart_layout(
            title=f"Risk / Return — {LOOKBACK_YEARS}Y",
            hovermode="closest",
            xaxis=dict(
                title=f"Annualized Volatility ({LOOKBACK_YEARS}Y)",
                tickformat=".0%",
                rangemode="tozero",
            ),
            yaxis=dict(
                title=f"Annualized Return ({LOOKBACK_YEARS}Y)",
                tickformat=".0%",
            ),
        ),
    )


def _update_scatter(
    fig: go.FigureWidget,
    prices: pd.DataFrame,
    rets: pd.DataFrame,
    meta: pd.DataFrame,
) -> None:
    if prices.empty or rets.empty:
        with fig.batch_update():
            fig.data[0].x = []
            fig.data[0].y = []
            fig.data[0].marker.size = []
            fig.data[0].marker.color = []
            fig.data[0].text = []
            fig.data[0].customdata = []
        return
    vol = ann_volatility(rets, LOOKBACK_YEARS)
    ret = ann_return(prices, LOOKBACK_YEARS)
    sharpe = ann_sharpe(rets, prices, LOOKBACK_YEARS)
    frame = pd.DataFrame({"vol": vol, "ret": ret, "sharpe": sharpe}).dropna(
        subset=["vol", "ret"]
    )
    if frame.empty:
        with fig.batch_update():
            fig.data[0].x = []
            fig.data[0].y = []
            fig.data[0].marker.size = []
            fig.data[0].marker.color = []
            fig.data[0].text = []
            fig.data[0].customdata = []
        return
    s_clipped = frame["sharpe"].fillna(0).clip(lower=0)
    if s_clipped.max() > 0:
        sizes = (8 + 32 * (s_clipped / s_clipped.max())).tolist()
    else:
        sizes = [12] * len(frame)
    # Positional palette so each ticker shares one color across every
    # chart inside an analysis pane and the perf-grid color swatch.
    colors = [_palette_color(i) for i in range(len(frame))]
    names = [_short_ticker(t) for t in frame.index]
    with fig.batch_update():
        fig.data[0].x = frame["vol"].values
        fig.data[0].y = frame["ret"].values
        fig.data[0].marker.size = sizes
        fig.data[0].marker.color = colors
        fig.data[0].text = names
        fig.data[0].customdata = frame["sharpe"].values


# ---- Drawdown chart (selected set) -----------------------------------------


def _drawdown_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Drawdown — {LOOKBACK_YEARS}Y",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Drawdown", tickformat=".0%"),
            shapes=[_h_ref(0.0)],
        )
    )


def _update_drawdown(
    fig: go.FigureWidget, dd: pd.DataFrame, meta: pd.DataFrame
) -> None:
    _update_line_series(fig, dd, value_format=".2%")


# ---- Rolling-reference line chart (correlation / beta) ---------------------


def _rolling_ref_chart(
    *, title_prefix: str, y_label: str, ref_y: float
) -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"{title_prefix} — {SHARPE_WINDOW_LABEL} rolling",
            hovermode="x unified",
            xaxis=dict(title="Date"),
            yaxis=dict(title=y_label),
            shapes=[_h_ref(ref_y)],
        )
    )


def _update_rolling_ref(
    fig: go.FigureWidget,
    df: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    title_prefix: str,
    benchmark_label: str,
) -> None:
    title_suffix = f" — {SHARPE_WINDOW_LABEL} rolling"
    new_title = (
        f"{title_prefix} vs {benchmark_label}{title_suffix}"
        if benchmark_label
        else f"{title_prefix}{title_suffix}"
    )
    _update_line_series(fig, df, title=new_title)


# ---- Return distribution histogram (selected set) --------------------------


def _return_dist_chart() -> go.FigureWidget:
    return go.FigureWidget(
        layout=_chart_layout(
            title=f"Return Distribution — {LOOKBACK_YEARS}Y daily returns",
            barmode="overlay",
            xaxis=dict(title="Daily return", tickformat=".1%"),
            yaxis=dict(title="Frequency"),
        )
    )


def _return_dist_stats_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=92,
        base_row_header_size=180,
        layout=W.Layout(width="100%", height="180px"),
    )
    return grid


def _update_return_dist(
    fig: go.FigureWidget,
    stats_grid: DataGrid,
    rets: pd.DataFrame,
    stats_df: pd.DataFrame,
    meta: pd.DataFrame,
) -> None:
    if rets.empty:
        with fig.batch_update():
            fig.data = ()
        stats_grid.data = pd.DataFrame()
        return
    cleaned = rets.dropna(how="all")
    if cleaned.empty:
        with fig.batch_update():
            fig.data = ()
        stats_grid.data = pd.DataFrame()
        return
    all_vals = cleaned.values[np.isfinite(cleaned.values)]
    if all_vals.size == 0:
        with fig.batch_update():
            fig.data = ()
        stats_grid.data = pd.DataFrame()
        return
    lo, hi = float(np.nanpercentile(all_vals, 0.5)), float(
        np.nanpercentile(all_vals, 99.5)
    )
    if lo == hi:
        lo, hi = lo - 0.01, hi + 0.01
    bin_size = (hi - lo) / 80.0
    traces: list[go.Histogram] = []
    for i, col in enumerate(cleaned.columns):
        series = cleaned[col].dropna().values
        if series.size == 0:
            continue
        label = _short_ticker(col)
        traces.append(
            go.Histogram(
                x=series,
                xbins=dict(start=lo, end=hi, size=bin_size),
                marker=dict(color=_palette_color(i)),
                opacity=0.55,
                name=label,
                hovertemplate=f"{label}<br>bin %{{x:.2%}}<br>count %{{y}}<extra></extra>",
            )
        )
    with fig.batch_update():
        fig.data = ()
        if traces:
            fig.add_traces(traces)
        fig.layout.xaxis.range = [lo - bin_size, hi + bin_size]

    if stats_df.empty:
        stats_grid.data = pd.DataFrame()
        return
    info = meta.set_index("ticker").reindex(stats_df.index)["name"]
    display = stats_df.copy()
    display.insert(0, "Name", info.values)
    display.index.name = "Ticker"
    pct = TextRenderer(format=".2%")
    f2 = TextRenderer(format=".2f")
    text = TextRenderer()
    renderers: dict = {"Name": text}
    for col in ("Mean", "Std", "Min", "Max"):
        if col in display.columns:
            renderers[col] = pct
    for col in ("Skew", "Kurtosis"):
        if col in display.columns:
            renderers[col] = f2
    stats_grid.data = display
    stats_grid.renderers = renderers


# ---- Commentary rendering -------------------------------------------------


def _sentiment_color(name: str) -> str:
    try:
        return Sentiment[name.upper()].value
    except KeyError:
        return Sentiment.NEUTRAL.value


def _load_weekly_commentary() -> str:
    if not WEEKLY_COMMENTARY_PATH.exists():
        return (
            f"<p style='color:{Color.SLATE_500};margin:0;'>"
            "No weekly commentary yet — create <code>data/weekly_commentary.html</code> "
            "to populate this section."
            "</p>"
        )
    return WEEKLY_COMMENTARY_PATH.read_text(encoding="utf-8")


def _load_disclaimer(path: Path, **placeholders: str) -> str:
    if not path.exists():
        return ""
    body = path.read_text(encoding="utf-8")
    for key, val in placeholders.items():
        body = body.replace("{{" + key + "}}", val)
    return body


def _render_weekly_commentary(body_html: str, as_of: date) -> str:
    return (
        f"<div style='font-family:{Font.SANS};font-size:{FontSize.BODY};"
        f"line-height:1.5;border:1px solid {Color.SLATE_200};border-radius:6px;"
        f"padding:14px 16px;background:{Color.SLATE_50};'>"
        "<div style='display:flex;align-items:baseline;gap:10px;margin-bottom:6px;'>"
        f"<h3 style='margin:0;font-size:{FontSize.H3};color:{Color.BRAND_NAVY};'>"
        "Weekly Commentary</h3>"
        f"<span style='font-size:{FontSize.CAPTION};color:{Color.SLATE_500};'>"
        f"as of {as_of.isoformat()}</span>"
        "</div>"
        f"<div>{body_html}</div>"
        "</div>"
    )


def _render_highlights(cards: list[dict]) -> str:
    if not cards:
        return ""
    tiles = []
    for c in cards:
        color = _sentiment_color(c.get("sentiment", "neutral"))
        label = html.escape(c["label"])
        value = html.escape(c["value"])
        ticker = html.escape(c["ticker"])
        name = html.escape(c.get("name", ""))
        tiles.append(
            f"<div style='border:1px solid {Color.SLATE_200};border-radius:6px;"
            f"padding:10px 12px;background:{Color.WHITE};'>"
            f"<div style='font-size:{FontSize.MICRO};font-weight:600;"
            "letter-spacing:0.05em;text-transform:uppercase;"
            f"color:{Color.SLATE_500};margin-bottom:4px;'>{label}</div>"
            f"<div style='font-size:{FontSize.DISPLAY};font-weight:600;"
            f"color:{color};line-height:1.1;'>{value}</div>"
            f"<div style='font-size:{FontSize.LABEL};color:{Color.BRAND_NAVY};"
            f"margin-top:4px;'>{name}</div>"
            f"<div style='font-size:{FontSize.CAPTION};color:{Color.SLATE_500};"
            f"font-family:{Font.MONO};'>{ticker}</div>"
            "</div>"
        )
    return (
        f"<div style='font-family:{Font.SANS};'>"
        f"<h3 style='margin:14px 0 8px 0;font-size:{FontSize.H3};"
        f"color:{Color.BRAND_NAVY};'>"
        f"Key Highlights <span style='font-weight:400;font-size:{FontSize.CAPTION};"
        f"color:{Color.SLATE_500};'>(all-catalog)</span>"
        "</h3>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;'>"
        + "".join(tiles)
        + "</div></div>"
    )


def _render_error(message: str) -> str:
    return (
        f"<div style='font-family:{Font.SANS};font-size:{FontSize.SMALL};"
        f"background:{StatusTone.ERROR.bg};border:1px solid {StatusTone.ERROR.border};"
        f"color:{StatusTone.ERROR.fg};padding:12px 16px;border-radius:4px;'>"
        "<h3 style='margin:0 0 8px 0;'>Recompute failed</h3>"
        f"<pre style='white-space:pre-wrap;margin:0;'>{html.escape(message)}</pre>"
        "</div>"
    )
