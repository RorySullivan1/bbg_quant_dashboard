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


def _update_line(fig: go.FigureWidget, perf: pd.DataFrame) -> None:
    _update_line_series(fig, perf)


def _update_outperformance(
    fig: go.FigureWidget,
    df: pd.DataFrame,
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


def _update_sharpe_line(fig: go.FigureWidget, zser: pd.DataFrame) -> None:
    _update_line_series(fig, zser, tail_n=TRADING_DAYS_PER_YEAR)


def _clear_scatter(fig: go.FigureWidget) -> None:
    """Blank the risk/return scatter's single trace (no valid data)."""
    with fig.batch_update():
        fig.data[0].x = []
        fig.data[0].y = []
        fig.data[0].marker.size = []
        fig.data[0].marker.color = []
        fig.data[0].text = []
        fig.data[0].customdata = []


def _update_scatter(
    fig: go.FigureWidget,
    prices: pd.DataFrame,
    rets: pd.DataFrame,
    meta: pd.DataFrame,
) -> None:
    if prices.empty or rets.empty:
        _clear_scatter(fig)
        return
    vol = ann_volatility(rets, LOOKBACK_YEARS)
    ret = ann_return(prices, LOOKBACK_YEARS)
    sharpe = ann_sharpe(rets, prices, LOOKBACK_YEARS)
    frame = pd.DataFrame({"vol": vol, "ret": ret, "sharpe": sharpe}).dropna(
        subset=["vol", "ret"]
    )
    if frame.empty:
        _clear_scatter(fig)
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


def _update_drawdown(fig: go.FigureWidget, dd: pd.DataFrame) -> None:
    _update_line_series(fig, dd, value_format=".2%")


def _update_rolling_ref(
    fig: go.FigureWidget,
    df: pd.DataFrame,
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
    # Mutate the pre-allocated traces + annotation in place (see
    # `_weekly_scatter_chart`): a same-count trace *replacement* can fail to
    # repaint on older widget-manager frontends, an in-place restyle does not.
    marker, fit_line = fig.data[0], fig.data[1]
    annotation = fig.layout.annotations[0]
    if len(frame) < 2:
        with fig.batch_update():
            marker.x, marker.y = (), ()
            fit_line.x, fit_line.y = (), ()
            annotation.visible = False
        return
    fit = poly_fit(frame["x"], frame["y"], degree=2)
    has_fit = not np.isnan(fit.convexity)
    with fig.batch_update():
        marker.x = frame["x"].to_numpy()
        marker.y = frame["y"].to_numpy()
        if has_fit:
            # Dense x grid so the quadratic renders as a smooth curve, sorted so
            # the connected line never doubles back on itself.
            xs = np.linspace(frame["x"].min(), frame["x"].max(), 100)
            fit_line.x = xs
            fit_line.y = np.polyval(fit.coeffs, xs)
            annotation.text = (
                f"β={fit.slope:.2f}  convexity={fit.convexity:+.1f}"
                f"  R²={fit.r_squared:.2f}"
            )
            annotation.visible = True
        else:
            fit_line.x, fit_line.y = (), ()
            annotation.visible = False


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


def _update_factor_scoring(fig: go.FigureWidget, betas: pd.Series | None) -> None:
    """Bar chart of a strategy's β to each macro-factor proxy (equity risk
    premium / term premium / trend). `betas` is a Series indexed by factor label;
    bars are green when positive, red when negative. None / all-NaN clears."""
    if betas is None or betas.dropna().empty:
        with fig.batch_update():
            fig.data[0].x = []
            fig.data[0].y = []
            fig.data[0].marker.color = []
        return
    s = betas.dropna()
    colors = [
        Color.GREEN_600.value if v >= 0 else Color.RED_600.value for v in s.values
    ]
    with fig.batch_update():
        fig.data[0].x = list(s.index)
        fig.data[0].y = s.values
        fig.data[0].marker.color = colors


def _stub_placeholder(fig: go.FigureWidget, text: str) -> None:
    """Clear a figure and show one centered muted placeholder annotation — the
    shared body of the not-yet-implemented analysis stubs."""
    with fig.batch_update():
        fig.data = ()
        fig.layout.annotations = ()
        fig.add_annotation(
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            text=text,
            font=dict(color=Color.TEXT_MUTED.value, size=13),
        )


def _update_perf_ranking(fig: go.FigureWidget, scores: pd.Series | None = None) -> None:
    """Radar/spider ranking of the strategy across performance metrics. Metrics
    are wired in a later pass; with no scores the figure shows a placeholder.
    When given, `scores` is a Series of metric→value plotted as a closed loop."""
    if scores is None or scores.dropna().empty:
        _stub_placeholder(fig, "Performance metrics coming soon")
        return
    s = scores.dropna()
    theta = [*s.index, s.index[0]]  # close the loop back to the first axis
    r = [*s.values, s.values[0]]
    with fig.batch_update():
        fig.data = ()
        fig.layout.annotations = ()
        fig.add_traces(
            [
                go.Scatterpolar(
                    r=r,
                    theta=theta,
                    fill="toself",
                    line=dict(color=_palette_color(0)),
                )
            ]
        )


def _update_pca(fig: go.FigureWidget, *_args, **_kwargs) -> None:
    """PCA scree (stub): explained-variance bars + a cumulative line. Wired in a
    later pass; for now it shows a placeholder."""
    _stub_placeholder(fig, "PCA analysis — coming soon")


def _update_defensive(fig: go.FigureWidget, *_args, **_kwargs) -> None:
    """Defensive scoring (stub). Wired in a later pass; shows a placeholder."""
    _stub_placeholder(fig, "Defensive scoring — coming soon")
