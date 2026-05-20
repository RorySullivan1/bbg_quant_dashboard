from __future__ import annotations

import html
import time
import traceback
from datetime import date
from typing import Callable

import bqplot as bq
import ipywidgets as W
import numpy as np
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer

from .bql_client import default_window, fetch_prices
from .commentary import build_commentary
from .config import LOGO_PATH, LOOKBACK_YEARS, SHARPE_WINDOW, TRADING_DAYS_PER_YEAR
from .data import apply_filters, load_metadata, unique_values
from .stats import (
    corr_matrix,
    cum_perf,
    daily_returns,
    perf_table,
    sharpe_zscore,
    universe_perf,
)


LINE_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]


SHARPE_WINDOW_LABEL = (
    f"{SHARPE_WINDOW // TRADING_DAYS_PER_YEAR}Y"
    if SHARPE_WINDOW % TRADING_DAYS_PER_YEAR == 0
    else f"{SHARPE_WINDOW}d"
)


BANNER_HTML = (
    "<div style='display:flex;align-items:center;gap:16px;"
    "padding:12px 16px;background:#0b1f3a;color:#fff;'>"
    "<div style='font-size:22px;font-weight:600;'>"
    "Index Catalog Dashboard</div>"
    "<div style='font-size:13px;opacity:0.75;'>"
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


def _toggle_group(
    label: str, options: list[str]
) -> tuple[W.VBox, Callable[[], list[str]], list[W.ToggleButton]]:
    toggles = {
        opt: W.ToggleButton(
            value=False,
            description=opt,
            layout=W.Layout(width="100%", min_height="26px", margin="1px 0"),
        )
        for opt in options
    }
    header = W.HTML(
        f"<div style='font-weight:600;font-size:12px;margin:6px 4px 2px 4px;'>{html.escape(label)}</div>"
    )
    toggle_list = W.VBox(
        list(toggles.values()),
        layout=W.Layout(
            max_height="200px",
            overflow="auto",
            width="100%",
            padding="0 2px",
        ),
    )
    box = W.VBox(
        [header, toggle_list],
        layout=W.Layout(
            width="100%",
            padding="4px 6px",
            border="1px solid #e5e7eb",
            margin="0 0 6px 0",
        ),
    )
    return box, (lambda: [v for v, t in toggles.items() if t.value]), list(toggles.values())


def build_app(verbose: bool = True) -> W.VBox:
    t0 = time.perf_counter()
    def _log(msg: str) -> None:
        if verbose:
            print(f"[{time.perf_counter() - t0:6.2f}s] {msg}", flush=True)

    meta = load_metadata()
    _log(f"loaded metadata: {len(meta)} tickers")

    asset_box, asset_get, asset_toggles = _toggle_group("Asset Class", unique_values(meta, "asset_class"))
    cat_box, cat_get, cat_toggles = _toggle_group("Category", unique_values(meta, "category"))
    theme_box, theme_get, theme_toggles = _toggle_group("Theme", unique_values(meta, "theme"))
    sol_box, sol_get, sol_toggles = _toggle_group("Solution", unique_values(meta, "solution"))
    ret_box, ret_get, ret_toggles = _toggle_group("Return Type", unique_values(meta, "return_type"))

    live_min = W.DatePicker(
        description="Live ≥",
        layout=W.Layout(width="100%"),
        style={"description_width": "60px"},
    )
    live_max = W.DatePicker(
        description="Live ≤",
        layout=W.Layout(width="100%"),
        style={"description_width": "60px"},
    )

    search_w = W.Text(
        placeholder="Search ticker or name…",
        layout=W.Layout(width="100%"),
    )
    ticker_w = W.SelectMultiple(
        options=_ticker_options(meta),
        value=tuple(meta["ticker"].head(5)),
        rows=8,
        layout=W.Layout(width="100%"),
    )

    apply_btn = W.Button(
        description="Apply",
        button_style="primary",
        layout=W.Layout(width="100%"),
    )

    ticker_label = W.HTML(
        "<div style='font-weight:600;font-size:12px;margin:6px 4px 2px 4px;'>Tickers</div>"
    )
    filter_box = W.VBox(
        [
            asset_box, cat_box, theme_box, sol_box, ret_box,
            live_min, live_max,
            ticker_label, search_w, ticker_w,
            apply_btn,
        ],
        layout=W.Layout(width="100%", padding="8px"),
    )

    line_fig, line_x, line_y, _ = _line_chart()
    perf_grid = _perf_grid()
    heat_fig, heat_data, heat_x, heat_y = _heatmap()
    bar_fig, bar_x, bar_y, bar_mark = _bar_chart()
    commentary_w = W.HTML(_render_commentary(["Loading universe…"]))
    universe_grid = _universe_grid()

    filter_col = W.Box(
        [filter_box],
        layout=W.Layout(width="30%", border="1px solid #ddd"),
    )
    chart_col = W.VBox(
        [line_fig, perf_grid],
        layout=W.Layout(width="70%", padding="8px"),
    )
    row1 = W.HBox(
        [filter_col, chart_col],
        layout=W.Layout(width="100%", align_items="stretch"),
    )

    row2 = W.HBox(
        [
            W.Box([heat_fig], layout=W.Layout(width="50%", padding="8px")),
            W.Box([bar_fig], layout=W.Layout(width="50%", padding="8px")),
        ],
        layout=W.Layout(width="100%"),
    )

    commentary_box = W.Box(
        [commentary_w],
        layout=W.Layout(width="100%", padding="12px 16px"),
    )

    universe_header = W.HTML(
        "<div style='font-weight:600;font-size:14px;margin:8px 12px 4px 12px;'>"
        "All-catalog performance"
        "</div>"
    )
    universe_row = W.VBox(
        [universe_header, universe_grid],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )

    # Single BQL fetch at app-load time, bounded by LOOKBACK_YEARS. A wider
    # fetch (e.g. back to oldest live date) is too slow on the terminal — the
    # SI column in the all-catalog grid is therefore bounded by this window.
    today = date.today()
    universe_start = (pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)).date()

    universe_prices: pd.DataFrame = pd.DataFrame()
    init_errors: list[str] = []
    _log(f"BQL fetch starting: {len(meta)} tickers, {universe_start} → {today}")
    t_fetch = time.perf_counter()
    try:
        universe_prices = fetch_prices(meta["ticker"].tolist(), universe_start, today)
        _log(
            f"BQL fetch done in {time.perf_counter() - t_fetch:.1f}s — "
            f"shape={universe_prices.shape}"
        )
    except Exception:
        _log(f"BQL fetch FAILED after {time.perf_counter() - t_fetch:.1f}s")
        init_errors.append(
            f"Universe fetch ({universe_start} → {today}) failed:\n"
            f"{traceback.format_exc()}"
        )

    if not universe_prices.empty:
        t_perf = time.perf_counter()
        try:
            up = universe_perf(universe_prices)
            _log(f"universe_perf computed in {time.perf_counter() - t_perf:.2f}s")
            t_grid = time.perf_counter()
            _update_universe_grid(universe_grid, meta, up)
            _log(f"universe grid populated in {time.perf_counter() - t_grid:.2f}s")
        except Exception:
            init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )

    def _on_filter_change(_change=None):
        filtered = apply_filters(
            meta,
            asset_classes=asset_get(),
            categories=cat_get(),
            themes=theme_get(),
            solutions=sol_get(),
            return_types=ret_get(),
            live_date_min=live_min.value,
            live_date_max=live_max.value,
        )
        query = (search_w.value or "").strip().lower()
        if query:
            mask = (
                filtered["ticker"].str.lower().str.contains(query, regex=False)
                | filtered["name"].str.lower().str.contains(query, regex=False)
            )
            visible = filtered.loc[mask]
        else:
            visible = filtered

        selected = list(ticker_w.value)
        keep_selected = filtered.loc[filtered["ticker"].isin(selected)]
        combined = pd.concat([visible, keep_selected]).drop_duplicates(subset="ticker")
        combined = combined.sort_values("ticker").reset_index(drop=True)
        ticker_w.options = _ticker_options(combined)
        ticker_w.value = tuple(t for t in selected if t in combined["ticker"].values)

    for tg in (*asset_toggles, *cat_toggles, *theme_toggles, *sol_toggles, *ret_toggles):
        tg.observe(_on_filter_change, names="value")
    for w in (live_min, live_max, search_w):
        w.observe(_on_filter_change, names="value")

    def _recompute(_btn=None):
        commentary_html = ""
        # Surface any errors from the initial universe fetch so the user can
        # see what actually went wrong, not just the downstream "cache empty".
        for err in init_errors:
            commentary_html += _render_error(err)
        # Commentary is always whole-catalog, regardless of selection.
        universe_window_start = pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)
        try:
            if not universe_prices.empty:
                universe_window = universe_prices.loc[
                    universe_prices.index >= universe_window_start
                ]
                if not universe_window.empty:
                    universe_rets = daily_returns(universe_window)
                    universe_sz = sharpe_zscore(universe_rets)
                    bullets = build_commentary(meta, universe_window, universe_rets, universe_sz)
                    commentary_html += _render_commentary(bullets)
        except Exception:
            commentary_html += _render_error(traceback.format_exc())

        try:
            tickers = list(ticker_w.value)
            if len(tickers) < 1:
                _update_line(line_fig, line_x, line_y, pd.DataFrame(), meta)
                _update_perf_grid(perf_grid, pd.DataFrame(), meta)
                _update_heatmap(heat_fig, heat_data, heat_x, heat_y, pd.DataFrame())
                _update_bar(bar_fig, bar_x, bar_y, bar_mark, pd.Series(dtype=float))
            elif universe_prices.empty:
                commentary_html = commentary_html + _render_error(
                    "Universe price cache is empty — initial BQL fetch returned no rows."
                )
            else:
                sel_full = universe_prices.reindex(columns=tickers)
                sel_window = sel_full.loc[sel_full.index >= universe_window_start]
                if sel_window.dropna(how="all").empty:
                    commentary_html = commentary_html + _render_error(
                        f"No price data in the {LOOKBACK_YEARS}Y window for: {tickers}."
                    )
                else:
                    rets = daily_returns(sel_window)
                    perf = cum_perf(sel_window)
                    sz = sharpe_zscore(rets)
                    cm = corr_matrix(rets)
                    pt = perf_table(sel_window)

                    _update_line(line_fig, line_x, line_y, perf, meta)
                    _update_perf_grid(perf_grid, pt, meta)
                    _update_heatmap(heat_fig, heat_data, heat_x, heat_y, cm)
                    _update_bar(bar_fig, bar_x, bar_y, bar_mark, sz)
        except Exception:
            commentary_html = commentary_html + _render_error(traceback.format_exc())

        commentary_w.value = commentary_html or _render_commentary(["No data."])

    apply_btn.on_click(_recompute)

    app = W.VBox(
        [_banner(), commentary_box, row1, row2, universe_row],
        layout=W.Layout(width="100%"),
    )

    t_initial = time.perf_counter()
    _recompute()
    _log(f"initial recompute (selected viz) in {time.perf_counter() - t_initial:.2f}s")
    _log(f"build_app TOTAL: {time.perf_counter() - t0:.2f}s")
    return app


def _ticker_options(df: pd.DataFrame) -> list[tuple[str, str]]:
    return [(f"{r['ticker']} — {r['name']}", r["ticker"]) for _, r in df.iterrows()]


def _line_chart():
    x_sc = bq.DateScale()
    y_sc = bq.LinearScale()
    ax_x = bq.Axis(scale=x_sc, label="Date")
    ax_y = bq.Axis(scale=y_sc, orientation="vertical", label="Rebased = 100")
    fig = bq.Figure(
        axes=[ax_x, ax_y],
        marks=[],
        title=f"Cumulative Performance ({LOOKBACK_YEARS}Y)",
        legend_location="top-left",
        layout=W.Layout(width="100%", height="380px"),
        fig_margin={"top": 40, "bottom": 50, "left": 60, "right": 20},
    )
    return fig, x_sc, y_sc, fig


def _update_line(fig, x_sc, y_sc, perf: pd.DataFrame, meta: pd.DataFrame):
    if perf.empty:
        fig.marks = []
        return
    name_lookup = meta.set_index("ticker")["name"].to_dict()
    marks = []
    for i, col in enumerate(perf.columns):
        series = perf[col].dropna()
        if series.empty:
            continue
        name = name_lookup.get(col)
        label = f"{name} ({col})" if name else col
        marks.append(
            bq.Lines(
                x=series.index.values,
                y=series.values,
                scales={"x": x_sc, "y": y_sc},
                colors=[LINE_COLORS[i % len(LINE_COLORS)]],
                labels=[label],
                display_legend=True,
            )
        )
    fig.marks = marks
    if not perf.dropna(how="all").empty:
        y_min = float(np.nanmin(perf.values))
        y_max = float(np.nanmax(perf.values))
        pad = (y_max - y_min) * 0.02 or 1.0
        y_sc.min = y_min - pad
        y_sc.max = y_max + pad
        x_sc.min = perf.index.min().to_pydatetime()
        x_sc.max = perf.index.max().to_pydatetime()


# ---- Perf grid (selected set) ---------------------------------------------


def _perf_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=82,
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="240px"),
    )
    return grid


def _update_perf_grid(grid: DataGrid, pt: pd.DataFrame, meta: pd.DataFrame) -> None:
    if pt.empty:
        grid.data = pd.DataFrame()
        return
    info_block = _info_block(pt.index, meta)
    pt_norm = pt.copy()
    pt_norm.columns = pd.MultiIndex.from_tuples(
        [(str(a), str(b)) for a, b in pt_norm.columns]
    )
    combined = pd.concat([info_block, pt_norm], axis=1)
    combined.index.name = "Ticker"
    grid.data = combined
    grid.renderers = _perf_renderers(combined.columns)


def _info_block(tickers: pd.Index, meta: pd.DataFrame) -> pd.DataFrame:
    info = meta.set_index("ticker").reindex(tickers)[["name", "asset_class", "theme"]]
    info = info.rename(
        columns={"name": "Name", "asset_class": "Asset Class", "theme": "Theme"}
    )
    info.columns = pd.MultiIndex.from_product([["Info"], info.columns])
    return info


def _perf_renderers(columns: pd.MultiIndex) -> dict:
    text = TextRenderer()
    pct = TextRenderer(format=".2%")
    f2 = TextRenderer(format=".2f")
    renderers: dict = {}
    for col in columns:
        period, metric = col
        if period == "Info":
            renderers[col] = text
        elif metric == "Sharpe":
            renderers[col] = f2
        elif metric in ("Return", "Vol", "Max DD"):
            renderers[col] = pct
        else:
            renderers[col] = text
    return renderers


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
    info_cols = ["name", "asset_class", "category", "theme", "solution", "return_type", "live_date"]
    info = meta.set_index("ticker")[info_cols].copy()
    info["live_date"] = info["live_date"].dt.strftime("%Y-%m-%d")
    info = info.rename(
        columns={
            "name": "Name",
            "asset_class": "Asset Class",
            "category": "Category",
            "theme": "Theme",
            "solution": "Solution",
            "return_type": "Return Type",
            "live_date": "Live Date",
        }
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
    grid.renderers = _perf_renderers(combined.columns)


# ---- Heatmap --------------------------------------------------------------


def _heatmap():
    col_sc = bq.ColorScale(scheme="RdYlBu", min=-1, max=1, reverse=True)
    x_sc = bq.OrdinalScale()
    y_sc = bq.OrdinalScale(reverse=True)
    ax_x = bq.Axis(scale=x_sc, tick_rotate=-75, tick_style={"font-size": "10px"})
    ax_y = bq.Axis(scale=y_sc, orientation="vertical", tick_style={"font-size": "10px"})
    ax_c = bq.ColorAxis(scale=col_sc, orientation="vertical", side="right")
    data = bq.GridHeatMap(
        color=np.zeros((2, 2)),
        row=["", " "],
        column=["", " "],
        scales={"color": col_sc, "row": y_sc, "column": x_sc},
        stroke="white",
    )
    fig = bq.Figure(
        marks=[data],
        axes=[ax_x, ax_y, ax_c],
        title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
        layout=W.Layout(width="100%", height="400px"),
        fig_margin={"top": 40, "bottom": 120, "left": 90, "right": 70},
    )
    return fig, data, x_sc, y_sc


def _update_heatmap(fig, data, _x_sc, _y_sc, cm: pd.DataFrame):
    # Correlation needs at least 2 series; below that, fall back to a
    # blank 2x2 placeholder so the GridHeatMap validator doesn't complain.
    if cm.empty or cm.shape[0] < 2:
        cm = pd.DataFrame(np.zeros((2, 2)), index=["", " "], columns=["", " "])
    tickers = list(cm.columns)
    data.color = cm.values
    data.row = tickers
    data.column = tickers


# ---- Bar chart ------------------------------------------------------------


def _bar_chart():
    x_sc = bq.OrdinalScale()
    y_sc = bq.LinearScale()
    ax_x = bq.Axis(scale=x_sc, tick_rotate=-75, tick_style={"font-size": "10px"})
    ax_y = bq.Axis(scale=y_sc, orientation="vertical", label="Sharpe z-score")
    bar = bq.Bars(
        x=[""],
        y=[0],
        scales={"x": x_sc, "y": y_sc},
        colors=["#3b82f6"],
    )
    fig = bq.Figure(
        marks=[bar],
        axes=[ax_x, ax_y],
        title=f"{SHARPE_WINDOW_LABEL} Rolling Sharpe — z-score vs prior {SHARPE_WINDOW_LABEL}",
        layout=W.Layout(width="100%", height="400px"),
        fig_margin={"top": 40, "bottom": 120, "left": 60, "right": 20},
    )
    return fig, x_sc, y_sc, bar


def _update_bar(_fig, _x_sc, _y_sc, bar, sz: pd.Series):
    sz = sz.dropna()
    if sz.empty:
        bar.x = [""]
        bar.y = [0]
        bar.colors = ["#3b82f6"]
        return
    bar.x = list(sz.index)
    bar.y = sz.values.tolist()
    bar.colors = ["#16a34a" if v >= 0 else "#dc2626" for v in sz.values]


# ---- Commentary rendering -------------------------------------------------


def _render_commentary(bullets: list[str]) -> str:
    items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
    return (
        "<div style='font-family:system-ui,sans-serif;font-size:14px;"
        "line-height:1.5;'>"
        "<h3 style='margin:0 0 8px 0;'>Commentary <span style='font-weight:400;font-size:12px;color:#64748b;'>(all-catalog)</span></h3>"
        f"<ul style='margin:0;padding-left:20px;'>{items}</ul>"
        "</div>"
    )


def _render_error(message: str) -> str:
    return (
        "<div style='font-family:system-ui,sans-serif;font-size:13px;"
        "background:#fef2f2;border:1px solid #fecaca;color:#7f1d1d;"
        "padding:12px 16px;border-radius:4px;'>"
        "<h3 style='margin:0 0 8px 0;'>Recompute failed</h3>"
        f"<pre style='white-space:pre-wrap;margin:0;'>{html.escape(message)}</pre>"
        "</div>"
    )
