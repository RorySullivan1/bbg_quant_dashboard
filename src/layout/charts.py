from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from ipydatagrid import DataGrid, TextRenderer

from ..config import LOOKBACK_YEARS, TRADING_DAYS_PER_YEAR
from ..stats import ann_return, ann_sharpe, ann_volatility, poly_fit
from ..style import Color
from .theme import SHARPE_WINDOW_LABEL, _palette_color, _short_ticker


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


def _update_sharpe_line(
    fig: go.FigureWidget, zser: pd.DataFrame, meta: pd.DataFrame
) -> None:
    _update_line_series(fig, zser, tail_n=TRADING_DAYS_PER_YEAR)


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


def _update_drawdown(
    fig: go.FigureWidget, dd: pd.DataFrame, meta: pd.DataFrame
) -> None:
    _update_line_series(fig, dd, value_format=".2%")


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


def _update_weekly_scatter(fig: go.FigureWidget, x: pd.Series, y: pd.Series) -> None:
    """Scatter of paired weekly returns (x = benchmark, y = strategy) with a
    quadratic least-squares fit, so a curved line reveals convexity (a smile =
    the strategy outperforms in big up *and* down weeks) rather than a single
    straight β. The annotation reports the central β (linear term), the convexity
    (x² term, signed) and R². Fewer than three aligned points clears the fit
    line (markers still draw); fewer than two clears the figure."""
    frame = (
        pd.DataFrame({"x": x, "y": y}).dropna()
        if x is not None and y is not None
        else pd.DataFrame(columns=["x", "y"])
    )
    if len(frame) < 2:
        with fig.batch_update():
            fig.data = ()
            fig.layout.annotations = ()
        return
    fit = poly_fit(frame["x"], frame["y"], degree=2)
    traces = [
        go.Scatter(
            x=frame["x"].to_numpy(),
            y=frame["y"].to_numpy(),
            mode="markers",
            marker=dict(size=6, color=_palette_color(0), line=dict(width=0)),
            name="weekly",
            hovertemplate="bench %{x:.2%}<br>strat %{y:.2%}<extra></extra>",
        )
    ]
    has_fit = not np.isnan(fit.convexity)
    if has_fit:
        # Dense x grid so the quadratic renders as a smooth curve, sorted so the
        # connected line never doubles back on itself.
        xs = np.linspace(frame["x"].min(), frame["x"].max(), 100)
        traces.append(
            go.Scatter(
                x=xs,
                y=np.polyval(fit.coeffs, xs),
                mode="lines",
                line=dict(color=Color.CHART_AXIS.value, dash="dash", width=1.5),
                name="quadratic fit",
                hoverinfo="skip",
            )
        )
    with fig.batch_update():
        fig.data = ()
        fig.add_traces(traces)
        fig.layout.annotations = ()
        if has_fit:
            fig.add_annotation(
                x=0.02,
                y=0.98,
                xref="paper",
                yref="paper",
                showarrow=False,
                align="left",
                text=(
                    f"β={fit.slope:.2f}  convexity={fit.convexity:+.1f}"
                    f"  R²={fit.r_squared:.2f}"
                ),
                font=dict(color=Color.CHART_TEXT.value, size=11),
            )


def _update_factor_corr_scatter(
    fig: go.FigureWidget, x: pd.Series, y: pd.Series, color: pd.Series
) -> None:
    """Monthly factor-correlation scatter: x = corr to the equity risk premium,
    y = corr to the term premium, one marker per month colored / sized by that
    month's risk-adjusted return (diverging RdYlGn around 0). Empty → cleared."""
    if x is None or y is None:
        with fig.batch_update():
            fig.data = ()
        return
    frame = pd.DataFrame({"x": x, "y": y, "c": color}).dropna(subset=["x", "y"])
    if frame.empty:
        with fig.batch_update():
            fig.data = ()
        return
    c = frame["c"].fillna(0.0)
    cmax = max(0.5, float(c.abs().max()))
    denom = float(c.abs().max()) or 1.0
    sizes = (8 + 14 * (c.abs() / denom)).tolist()
    trace = go.Scatter(
        x=frame["x"].to_numpy(),
        y=frame["y"].to_numpy(),
        mode="markers",
        marker=dict(
            size=sizes,
            color=c.tolist(),
            colorscale="RdYlGn",
            cmid=0,
            cmin=-cmax,
            cmax=cmax,
            showscale=True,
            colorbar=dict(title=dict(text="Risk-adj"), thickness=10),
            line=dict(width=0.5, color=Color.CHART_BG.value),
        ),
        text=[d.strftime("%Y-%m") for d in frame.index],
        hovertemplate=(
            "%{text}<br>ERP corr %{x:.2f}<br>Term corr %{y:.2f}<extra></extra>"
        ),
    )
    with fig.batch_update():
        fig.data = ()
        fig.add_traces([trace])
