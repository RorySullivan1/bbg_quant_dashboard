from __future__ import annotations

import html
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
from .stats import corr_matrix, cum_perf, daily_returns, perf_table, sharpe_zscore


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


def _checkbox_group(
    label: str, options: list[str]
) -> tuple[W.VBox, Callable[[], list[str]], list[W.Checkbox]]:
    checks = {
        opt: W.Checkbox(
            value=False,
            description=opt,
            indent=False,
            layout=W.Layout(width="100%", margin="0"),
        )
        for opt in options
    }
    header = W.HTML(
        f"<div style='font-weight:600;font-size:12px;margin:6px 4px 2px 4px;'>{html.escape(label)}</div>"
    )
    box = W.VBox(
        [header, *checks.values()],
        layout=W.Layout(
            width="100%",
            padding="4px 6px",
            border="1px solid #e5e7eb",
            margin="0 0 6px 0",
        ),
    )
    return box, (lambda: [v for v, cb in checks.items() if cb.value]), list(checks.values())


def build_app() -> W.VBox:
    meta = load_metadata()

    asset_box, asset_get, asset_checks = _checkbox_group("Asset Class", unique_values(meta, "asset_class"))
    cat_box, cat_get, cat_checks = _checkbox_group("Category", unique_values(meta, "category"))
    theme_box, theme_get, theme_checks = _checkbox_group("Theme", unique_values(meta, "theme"))
    sol_box, sol_get, sol_checks = _checkbox_group("Solution", unique_values(meta, "solution"))
    ret_box, ret_get, ret_checks = _checkbox_group("Return Type", unique_values(meta, "return_type"))

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
    commentary_w = W.HTML(_render_commentary(["Click Apply to load."]))

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
        # Keep selected tickers in the option list so the user doesn't lose
        # them while typing or narrowing filters.
        keep_selected = filtered.loc[filtered["ticker"].isin(selected)]
        combined = pd.concat([visible, keep_selected]).drop_duplicates(subset="ticker")
        combined = combined.sort_values("ticker").reset_index(drop=True)
        ticker_w.options = _ticker_options(combined)
        ticker_w.value = tuple(t for t in selected if t in combined["ticker"].values)

    for cb in (*asset_checks, *cat_checks, *theme_checks, *sol_checks, *ret_checks):
        cb.observe(_on_filter_change, names="value")
    for w in (live_min, live_max, search_w):
        w.observe(_on_filter_change, names="value")

    def _recompute(_btn=None):
        tickers = list(ticker_w.value)
        if len(tickers) < 1:
            commentary_w.value = _render_commentary(
                ["Select at least one ticker."]
            )
            return
        try:
            start, end = default_window(LOOKBACK_YEARS)
            prices = fetch_prices(tickers, start, end)
            if prices.empty or prices.dropna(how="all").empty:
                commentary_w.value = _render_error(
                    f"BQL returned no price data for the selected tickers: {tickers}."
                )
                return
            rets = daily_returns(prices)
            perf = cum_perf(prices)
            sz = sharpe_zscore(rets)
            cm = corr_matrix(rets)
            pt = perf_table(prices)

            _update_line(line_fig, line_x, line_y, perf)
            _update_perf_grid(perf_grid, pt)
            _update_heatmap(heat_fig, heat_data, heat_x, heat_y, cm)
            _update_bar(bar_fig, bar_x, bar_y, bar_mark, sz)

            sub_meta = meta[meta["ticker"].isin(tickers)]
            bullets = build_commentary(sub_meta, prices, rets, sz)
            commentary_w.value = _render_commentary(bullets)
        except Exception:
            commentary_w.value = _render_error(traceback.format_exc())

    apply_btn.on_click(_recompute)

    app = W.VBox(
        [_banner(), commentary_box, row1, row2],
        layout=W.Layout(width="100%"),
    )

    _recompute()
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


def _update_line(fig, x_sc, y_sc, perf: pd.DataFrame):
    if perf.empty:
        fig.marks = []
        return
    marks = []
    for i, col in enumerate(perf.columns):
        series = perf[col].dropna()
        marks.append(
            bq.Lines(
                x=series.index.values,
                y=series.values,
                scales={"x": x_sc, "y": y_sc},
                colors=[LINE_COLORS[i % len(LINE_COLORS)]],
                labels=[col],
                display_legend=True,
            )
        )
    fig.marks = marks
    # bqplot retains the prior scale bounds when marks are wholesale replaced,
    # so refit the axes to the new visible range with a small padding.
    y_min = float(np.nanmin(perf.values))
    y_max = float(np.nanmax(perf.values))
    pad = (y_max - y_min) * 0.02 or 1.0
    y_sc.min = y_min - pad
    y_sc.max = y_max + pad
    x_sc.min = perf.index.min().to_pydatetime()
    x_sc.max = perf.index.max().to_pydatetime()


def _perf_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=82,
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="220px"),
        default_renderer=TextRenderer(format=".2%"),
    )
    return grid


def _update_perf_grid(grid: DataGrid, pt: pd.DataFrame) -> None:
    if pt.empty:
        grid.data = pd.DataFrame()
        return
    display = pt.copy()
    # ipydatagrid wants string-only labels for MultiIndex columns
    display.columns = pd.MultiIndex.from_tuples(
        [(str(a), str(b)) for a, b in display.columns]
    )
    display.index.name = "Ticker"
    grid.data = display


def _heatmap():
    col_sc = bq.ColorScale(scheme="RdYlBu", min=-1, max=1, reverse=True)
    x_sc = bq.OrdinalScale()
    y_sc = bq.OrdinalScale(reverse=True)
    ax_x = bq.Axis(scale=x_sc, tick_rotate=-45, tick_style={"font-size": "10px"})
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
        layout=W.Layout(width="100%", height="360px"),
        fig_margin={"top": 40, "bottom": 70, "left": 90, "right": 70},
    )
    return fig, data, x_sc, y_sc


def _update_heatmap(fig, data, _x_sc, _y_sc, cm: pd.DataFrame):
    if cm.empty:
        cm = pd.DataFrame(np.zeros((2, 2)), index=["", " "], columns=["", " "])
    tickers = list(cm.columns)
    data.color = cm.values
    data.row = tickers
    data.column = tickers


def _bar_chart():
    x_sc = bq.OrdinalScale()
    y_sc = bq.LinearScale()
    ax_x = bq.Axis(scale=x_sc, tick_rotate=-45, tick_style={"font-size": "10px"})
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
        layout=W.Layout(width="100%", height="360px"),
        fig_margin={"top": 40, "bottom": 70, "left": 60, "right": 20},
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


def _render_commentary(bullets: list[str]) -> str:
    items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
    return (
        "<div style='font-family:system-ui,sans-serif;font-size:14px;"
        "line-height:1.5;'>"
        "<h3 style='margin:0 0 8px 0;'>Commentary</h3>"
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
