from __future__ import annotations

import html
import traceback
from datetime import date

import bqplot as bq
import ipywidgets as W
import numpy as np
import pandas as pd

from .bql_client import default_window, fetch_prices
from .commentary import build_commentary
from .config import LOGO_PATH, LOOKBACK_YEARS
from .data import apply_filters, load_metadata, unique_values
from .stats import corr_matrix, cum_perf, daily_returns, sharpe_zscore


LINE_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]


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


def _multi(label: str, options: list[str]) -> W.SelectMultiple:
    return W.SelectMultiple(
        options=options,
        description=label,
        rows=4,
        layout=W.Layout(width="100%"),
        style={"description_width": "90px"},
    )


def build_app() -> W.VBox:
    meta = load_metadata()

    asset_w = _multi("Asset Class", unique_values(meta, "asset_class"))
    cat_w = _multi("Category", unique_values(meta, "category"))
    theme_w = _multi("Theme", unique_values(meta, "theme"))
    sol_w = _multi("Solution", unique_values(meta, "solution"))
    ret_w = _multi("Return Type", unique_values(meta, "return_type"))

    live_min = W.DatePicker(
        description="Live ≥",
        layout=W.Layout(width="100%"),
        style={"description_width": "90px"},
    )
    live_max = W.DatePicker(
        description="Live ≤",
        layout=W.Layout(width="100%"),
        style={"description_width": "90px"},
    )

    ticker_w = W.SelectMultiple(
        options=_ticker_options(meta),
        value=tuple(meta["ticker"].head(5)),
        description="Tickers",
        rows=8,
        layout=W.Layout(width="100%"),
        style={"description_width": "90px"},
    )

    apply_btn = W.Button(
        description="Apply",
        button_style="primary",
        layout=W.Layout(width="100%"),
    )

    filter_box = W.VBox(
        [
            asset_w, cat_w, theme_w, sol_w, ret_w,
            live_min, live_max, ticker_w, apply_btn,
        ],
        layout=W.Layout(width="100%", padding="8px"),
    )

    line_fig, line_x, line_y, line_marks_container = _line_chart()
    heat_fig, heat_data, heat_x, heat_y = _heatmap()
    bar_fig, bar_x, bar_y, bar_mark = _bar_chart()
    commentary_w = W.HTML(_render_commentary(["Click Apply to load."]))

    filter_col = W.Box(
        [filter_box],
        layout=W.Layout(width="30%", border="1px solid #ddd"),
    )
    chart_col = W.Box(
        [line_fig],
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
            asset_classes=list(asset_w.value),
            categories=list(cat_w.value),
            themes=list(theme_w.value),
            solutions=list(sol_w.value),
            return_types=list(ret_w.value),
            live_date_min=live_min.value,
            live_date_max=live_max.value,
        )
        ticker_w.options = _ticker_options(filtered)
        keep = tuple(t for t in ticker_w.value if t in filtered["ticker"].values)
        ticker_w.value = keep

    for w in (asset_w, cat_w, theme_w, sol_w, ret_w, live_min, live_max):
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

            _update_line(line_fig, line_x, line_y, line_marks_container, perf)
            _update_heatmap(heat_fig, heat_data, heat_x, heat_y, cm)
            _update_bar(bar_fig, bar_x, bar_y, bar_mark, sz)

            sub_meta = meta[meta["ticker"].isin(tickers)]
            bullets = build_commentary(sub_meta, prices, rets, sz)
            commentary_w.value = _render_commentary(bullets)
        except Exception:
            commentary_w.value = _render_error(traceback.format_exc())

    apply_btn.on_click(_recompute)

    app = W.VBox(
        [_banner(), row1, row2, commentary_box],
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
        title="Cumulative Performance",
        legend_location="top-left",
        layout=W.Layout(width="100%", height="380px"),
        fig_margin={"top": 40, "bottom": 50, "left": 60, "right": 20},
    )
    return fig, x_sc, y_sc, fig


def _update_line(fig, x_sc, y_sc, _container, perf: pd.DataFrame):
    if perf.empty:
        fig.marks = []
        return
    colors = LINE_COLORS
    marks = []
    for i, col in enumerate(perf.columns):
        series = perf[col].dropna()
        marks.append(
            bq.Lines(
                x=series.index.values,
                y=series.values,
                scales={"x": x_sc, "y": y_sc},
                colors=[colors[i % len(colors)]],
                labels=[col],
                display_legend=True,
            )
        )
    fig.marks = marks


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
        title="Correlation",
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
        title="Rolling Sharpe (z-score vs own history)",
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
