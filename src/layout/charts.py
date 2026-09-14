"""Chart objects: each owns its `FigureWidget` and the code that redraws it.

Before #223 every chart was two functions in two files joined only by
convention — a `_*_chart()` factory in `panes.py` and a `_update_*(fig, …)` in
here — with the pane dataclass as the only record of which figure belonged to
which updater. Nothing stopped `_update_heatmap` being handed the drawdown
figure. Now a chart is one object: it builds its own figure in `__init__` and
exposes `update(...)` / `clear()`, so the pairing cannot be got wrong.

Each `update` still mutates the existing figure inside a `fig.batch_update()`
block, so the frontend sees one atomic update instead of a burst per trace, and
still never creates, removes or fetches — charts are handed data. That is what
lets a benchmark or date change redraw a single chart without rebuilding the
widget tree.
"""

from __future__ import annotations

import ipywidgets as W
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from ipydatagrid import DataGrid, TextRenderer

from ..config import LOOKBACK_YEARS, TRADING_DAYS_PER_YEAR
from ..stats import ann_return, ann_sharpe, ann_volatility, poly_fit
from ..style import Color
from .theme import (
    SHARPE_WINDOW_LABEL,
    _chart_layout,
    _h_ref,
    _palette_color,
    _short_ticker,
)

# --- shared drawing helpers ---------------------------------------------------


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


# --- the base ------------------------------------------------------------------


class Chart:
    """One figure plus its redraw logic.

    Subclasses implement `_build` (called once, from `__init__`), `update`, and
    `clear`. `clear` is always "update with nothing" — it exists as its own
    method because the empty-input shape differs per chart and callers should
    not have to know it.
    """

    def __init__(self) -> None:
        self.fig: go.FigureWidget = self._build()

    def _build(self) -> go.FigureWidget:  # pragma: no cover - abstract
        raise NotImplementedError

    def update(self, *args, **kwargs) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def clear(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class _StubChart(Chart):
    """A chart whose analysis is not wired yet: it draws one centered
    placeholder whatever it is handed. `PLACEHOLDER` is the text."""

    PLACEHOLDER: str = ""

    def update(self, *_args, **_kwargs) -> None:
        _stub_placeholder(self.fig, self.PLACEHOLDER)

    clear = update


# --- the charts ----------------------------------------------------------------


class LineChart(Chart):
    """Cumulative rebased performance, one line per strategy."""

    def _build(self) -> go.FigureWidget:
        """The cumulative-performance figure."""
        return go.FigureWidget(
            layout=_chart_layout(
                title=f"Cumulative Performance ({LOOKBACK_YEARS}Y)",
                hovermode="x unified",
                xaxis=dict(title="Date"),
                yaxis=dict(title="Rebased = 100"),
            )
        )

    def update(self, perf: pd.DataFrame) -> None:
        """Draw one rebased line per column."""
        _update_line_series(self.fig, perf)

    def clear(self) -> None:
        self.update(pd.DataFrame())


class OutperformanceChart(Chart):
    """Cumulative excess return per strategy vs a benchmark, in percentage
    points off a dashed zero baseline."""

    def _build(self) -> go.FigureWidget:
        """The outperformance figure, with its zero reference line."""
        return go.FigureWidget(
            layout=_chart_layout(
                title=f"Outperformance ({LOOKBACK_YEARS}Y)",
                hovermode="x unified",
                xaxis=dict(title="Date"),
                yaxis=dict(title="Excess return (pp)"),
                shapes=[_h_ref(0.0)],
            )
        )

    def update(self, df: pd.DataFrame, *, benchmark_label: str) -> None:
        """Render cumulative excess return per strategy vs the benchmark. Each
        series is in percentage points off a dashed zero baseline."""
        new_title = (
            f"Outperformance vs {benchmark_label} ({LOOKBACK_YEARS}Y)"
            if benchmark_label
            else f"Outperformance ({LOOKBACK_YEARS}Y)"
        )
        _update_line_series(self.fig, df, hover_suffix=" pp", title=new_title)

    def clear(self) -> None:
        self.update(pd.DataFrame(), benchmark_label="")


class CorrHeatmap(Chart):
    """Correlation matrix over daily returns, optionally over a benchmark-return
    tail (the regime view)."""

    def _build(self) -> go.FigureWidget:
        """The correlation heatmap, pre-seeded with a blank 2x2."""
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

    def update(self, cm: pd.DataFrame, title: str | None = None) -> None:
        """Swap in a correlation matrix; below 2 series it blanks to a 2x2."""
        if cm.empty or cm.shape[0] < 2:
            cm = pd.DataFrame(np.zeros((2, 2)), index=["", " "], columns=["", " "])
        tickers = list(cm.columns)
        with self.fig.batch_update():
            self.fig.data[0].z = cm.values
            self.fig.data[0].x = tickers
            self.fig.data[0].y = tickers
            if title is not None:
                self.fig.layout.title.text = title

    def clear(self) -> None:
        self.update(pd.DataFrame())


class SharpeZChart(Chart):
    """Rolling-Sharpe z-score over the trailing year."""

    def _build(self) -> go.FigureWidget:
        """The Sharpe z-score figure, with its zero reference line."""
        return go.FigureWidget(
            layout=_chart_layout(
                title=f"{SHARPE_WINDOW_LABEL} Rolling Sharpe — z-score (last 1Y)",
                hovermode="x unified",
                xaxis=dict(title="Date"),
                yaxis=dict(title="Sharpe z-score"),
                shapes=[_h_ref(0.0)],
            )
        )

    def update(self, zser: pd.DataFrame) -> None:
        """Draw the last year of each column's Sharpe z-score."""
        _update_line_series(self.fig, zser, tail_n=TRADING_DAYS_PER_YEAR)

    def clear(self) -> None:
        self.update(pd.DataFrame())


class ScatterChart(Chart):
    """Risk/return scatter — annualized vol against annualized return, marker
    size and color carrying Sharpe and the shared positional palette."""

    def _build(self) -> go.FigureWidget:
        """The risk/return scatter's single pre-allocated trace."""
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

    def update(
        self, prices: pd.DataFrame, rets: pd.DataFrame, meta: pd.DataFrame
    ) -> None:
        """Recompute vol / return / Sharpe and restyle the single trace."""
        if prices.empty or rets.empty:
            self.clear()
            return
        vol = ann_volatility(rets, LOOKBACK_YEARS)
        ret = ann_return(prices, LOOKBACK_YEARS)
        sharpe = ann_sharpe(rets, prices, LOOKBACK_YEARS)
        frame = pd.DataFrame({"vol": vol, "ret": ret, "sharpe": sharpe}).dropna(
            subset=["vol", "ret"]
        )
        if frame.empty:
            self.clear()
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
        with self.fig.batch_update():
            self.fig.data[0].x = frame["vol"].values
            self.fig.data[0].y = frame["ret"].values
            self.fig.data[0].marker.size = sizes
            self.fig.data[0].marker.color = colors
            self.fig.data[0].text = names
            self.fig.data[0].customdata = frame["sharpe"].values

    def clear(self) -> None:
        """Blank the single trace (no valid data)."""
        with self.fig.batch_update():
            self.fig.data[0].x = []
            self.fig.data[0].y = []
            self.fig.data[0].marker.size = []
            self.fig.data[0].marker.color = []
            self.fig.data[0].text = []
            self.fig.data[0].customdata = []


class DrawdownChart(Chart):
    """Drawdown from running peak, one line per strategy."""

    def _build(self) -> go.FigureWidget:
        """The drawdown figure, with its zero reference line."""
        return go.FigureWidget(
            layout=_chart_layout(
                title=f"Drawdown — {LOOKBACK_YEARS}Y",
                hovermode="x unified",
                xaxis=dict(title="Date"),
                yaxis=dict(title="Drawdown", tickformat=".0%"),
                shapes=[_h_ref(0.0)],
            )
        )

    def update(self, dd: pd.DataFrame) -> None:
        """Draw each column's drawdown series as a percentage."""
        _update_line_series(self.fig, dd, value_format=".2%")

    def clear(self) -> None:
        self.update(pd.DataFrame())


class RollingRefChart(Chart):
    """A rolling statistic against a benchmark — correlation or beta.

    `title_prefix` is fixed at construction. Before #223 it had to be passed
    *twice*, once to `_rolling_ref_chart` and again to every
    `_update_rolling_ref` call, with nothing checking the two agreed: a rolling
    beta figure could be titled "Rolling Correlation" on update. Holding it on
    the object removes that whole class of mismatch.
    """

    def __init__(self, *, title_prefix: str, y_label: str, ref_y: float) -> None:
        self.title_prefix = title_prefix
        self._y_label = y_label
        self._ref_y = ref_y
        super().__init__()

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            layout=_chart_layout(
                title=f"{self.title_prefix} — {SHARPE_WINDOW_LABEL} rolling",
                hovermode="x unified",
                xaxis=dict(title="Date"),
                yaxis=dict(title=self._y_label),
                shapes=[_h_ref(self._ref_y)],
            )
        )

    def update(self, df: pd.DataFrame, *, benchmark_label: str) -> None:
        title_suffix = f" — {SHARPE_WINDOW_LABEL} rolling"
        new_title = (
            f"{self.title_prefix} vs {benchmark_label}{title_suffix}"
            if benchmark_label
            else f"{self.title_prefix}{title_suffix}"
        )
        _update_line_series(self.fig, df, title=new_title)

    def clear(self) -> None:
        self.update(pd.DataFrame(), benchmark_label="")


class ReturnDistChart(Chart):
    """Overlaid daily-return histograms plus the per-ticker stats grid beneath.

    The grid is part of this chart, not a sibling widget: `update` writes both
    from the same inputs, and every early-return path has to blank both. Keeping
    them in one object is what makes "figure drawn, stats stale" unrepresentable.
    """

    def __init__(self) -> None:
        super().__init__()
        self.stats_grid: DataGrid = DataGrid(
            pd.DataFrame(),
            base_row_size=28,
            base_column_size=92,
            base_row_header_size=180,
            layout=W.Layout(width="100%", height="180px"),
        )

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            layout=_chart_layout(
                title=f"Return Distribution — {LOOKBACK_YEARS}Y daily returns",
                barmode="overlay",
                xaxis=dict(title="Daily return", tickformat=".1%"),
                yaxis=dict(title="Frequency"),
            )
        )

    def update(
        self, rets: pd.DataFrame, stats_df: pd.DataFrame, meta: pd.DataFrame
    ) -> None:
        if rets.empty:
            with self.fig.batch_update():
                self.fig.data = ()
            self.stats_grid.data = pd.DataFrame()
            return
        cleaned = rets.dropna(how="all")
        if cleaned.empty:
            with self.fig.batch_update():
                self.fig.data = ()
            self.stats_grid.data = pd.DataFrame()
            return
        all_vals = cleaned.values[np.isfinite(cleaned.values)]
        if all_vals.size == 0:
            with self.fig.batch_update():
                self.fig.data = ()
            self.stats_grid.data = pd.DataFrame()
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
        with self.fig.batch_update():
            self.fig.data = ()
            if traces:
                self.fig.add_traces(traces)
            self.fig.layout.xaxis.range = [lo - bin_size, hi + bin_size]

        if stats_df.empty:
            self.stats_grid.data = pd.DataFrame()
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
        self.stats_grid.data = display
        self.stats_grid.renderers = renderers

    def clear(self) -> None:
        self.update(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())


class WeeklyScatterChart(Chart):
    """Paired weekly returns (x = benchmark, y = strategy) with a quadratic fit,
    so a curved line reveals convexity rather than a single straight beta."""

    def _build(self) -> go.FigureWidget:
        """Single Strategy Section 3: weekly returns vs the benchmark, with
        a quadratic fit line (β + convexity) drawn by `update`.

        The two traces (markers + fit line) and the β/convexity annotation are
        **pre-allocated here** so ``update`` mutates them in place
        (`.x` / `.y` / `.text`) rather than replacing the trace tuple. An in-place
        restyle repaints reliably across ipywidgets/plotly widget-manager versions,
        whereas a *same-count* delete-then-re-add (this chart always has exactly two
        traces) can be dropped by older frontends — the repaint bug this chart hit
        on BQuant."""
        fig = go.FigureWidget(
            layout=_chart_layout(
                title="Weekly returns vs benchmark",
                hovermode="closest",
                xaxis=dict(
                    title="Benchmark weekly return", tickformat=".1%", zeroline=True
                ),
                yaxis=dict(
                    title="Strategy weekly return", tickformat=".1%", zeroline=True
                ),
            )
        )
        # Trace 0 = weekly-return markers; trace 1 = the quadratic fit line. Both
        # start empty and are filled in place on update.
        fig.add_trace(
            go.Scatter(
                x=[],
                y=[],
                mode="markers",
                marker=dict(size=6, color=_palette_color(0), line=dict(width=0)),
                name="weekly",
                hovertemplate="bench %{x:.2%}<br>strat %{y:.2%}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[],
                y=[],
                mode="lines",
                line=dict(color=Color.CHART_AXIS.value, dash="dash", width=1.5),
                name="quadratic fit",
                hoverinfo="skip",
            )
        )
        # Pre-allocated β/convexity/R² annotation, toggled + retexted in place.
        fig.add_annotation(
            x=0.02,
            y=0.98,
            xref="paper",
            yref="paper",
            showarrow=False,
            align="left",
            text="",
            font=dict(color=Color.CHART_TEXT.value, size=11),
            visible=False,
        )
        return fig

    def update(self, x: pd.Series, y: pd.Series) -> None:
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
        marker, fit_line = self.fig.data[0], self.fig.data[1]
        annotation = self.fig.layout.annotations[0]
        if len(frame) < 2:
            with self.fig.batch_update():
                marker.x, marker.y = (), ()
                fit_line.x, fit_line.y = (), ()
                annotation.visible = False
            return
        fit = poly_fit(frame["x"], frame["y"], degree=2)
        has_fit = not np.isnan(fit.convexity)
        with self.fig.batch_update():
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

    def clear(self) -> None:
        self.update(None, None)


class FactorCorrChart(Chart):
    """Monthly factor-correlation scatter, one marker per month."""

    def _build(self) -> go.FigureWidget:
        """Single Strategy Section 3: the strategy's monthly correlation to
        the equity-risk-premium (x) and term-premium (y) factors, colored by each
        month's risk-adjusted return. Axes fixed to the correlation range."""
        return go.FigureWidget(
            layout=_chart_layout(
                title="Monthly factor correlation",
                hovermode="closest",
                xaxis=dict(
                    title="Corr to equity risk premium", range=[-1, 1], zeroline=True
                ),
                yaxis=dict(title="Corr to term premium", range=[-1, 1], zeroline=True),
            )
        )

    def update(self, x: pd.Series, y: pd.Series, color: pd.Series) -> None:
        """Monthly factor-correlation scatter: x = corr to the equity risk premium,
        y = corr to the term premium, one marker per month colored / sized by that
        month's risk-adjusted return (diverging RdYlGn around 0). Empty → cleared."""
        if x is None or y is None:
            with self.fig.batch_update():
                self.fig.data = ()
            return
        frame = pd.DataFrame({"x": x, "y": y, "c": color}).dropna(subset=["x", "y"])
        if frame.empty:
            with self.fig.batch_update():
                self.fig.data = ()
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
        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.add_traces([trace])

    def clear(self) -> None:
        self.update(None, None, None)


class FactorScoringChart(Chart):
    """Bar chart of a strategy's beta to each macro-factor proxy."""

    def _build(self) -> go.FigureWidget:
        """Single Strategy analysis: a bar chart of the strategy's β to the
        macro-factor proxies (equity risk premium / term premium / trend), filled by
        `update`."""
        return go.FigureWidget(
            data=[
                go.Bar(
                    x=[],
                    y=[],
                    marker=dict(color=[]),
                    hovertemplate="%{x}<br>β %{y:.2f}<extra></extra>",
                )
            ],
            layout=_chart_layout(
                title=f"Factor scoring — β to macro factors ({LOOKBACK_YEARS}Y)",
                xaxis=dict(title="Factor"),
                yaxis=dict(title="Beta", zeroline=True),
                shapes=[_h_ref(0.0)],
            ),
        )

    def update(self, betas: pd.Series | None) -> None:
        """Bar chart of a strategy's β to each macro-factor proxy (equity risk
        premium / term premium / trend). `betas` is a Series indexed by factor label;
        bars are green when positive, red when negative. None / all-NaN clears."""
        if betas is None or betas.dropna().empty:
            with self.fig.batch_update():
                self.fig.data[0].x = []
                self.fig.data[0].y = []
                self.fig.data[0].marker.color = []
            return
        s = betas.dropna()
        colors = [
            Color.GREEN_600.value if v >= 0 else Color.RED_600.value for v in s.values
        ]
        with self.fig.batch_update():
            self.fig.data[0].x = list(s.index)
            self.fig.data[0].y = s.values
            self.fig.data[0].marker.color = colors

    def clear(self) -> None:
        self.update(None)


class PerfRankingChart(Chart):
    """Radar ranking of a strategy across performance metrics. Metrics are wired
    in a later pass; with no scores it shows a placeholder."""

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            data=[go.Scatterpolar(r=[], theta=[], fill="toself")],
            layout=_chart_layout(
                title="Performance ranking",
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            ),
        )

    def update(self, scores: pd.Series | None = None) -> None:
        """Radar/spider ranking of the strategy across performance metrics. Metrics
        are wired in a later pass; with no scores the figure shows a placeholder.
        When given, `scores` is a Series of metric→value plotted as a closed loop."""
        if scores is None or scores.dropna().empty:
            _stub_placeholder(self.fig, "Performance metrics coming soon")
            return
        s = scores.dropna()
        theta = [*s.index, s.index[0]]  # close the loop back to the first axis
        r = [*s.values, s.values[0]]
        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.layout.annotations = ()
            self.fig.add_traces(
                [
                    go.Scatterpolar(
                        r=r,
                        theta=theta,
                        fill="toself",
                        line=dict(color=_palette_color(0)),
                    )
                ]
            )

    def clear(self) -> None:
        self.update(None)


class PcaChart(_StubChart):
    """PCA scree (stub): explained-variance bars plus a cumulative line."""

    PLACEHOLDER = "PCA analysis — coming soon"

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            data=[
                go.Bar(x=[], y=[], name="Explained"),
                go.Scatter(
                    x=[], y=[], mode="lines+markers", name="Cumulative", yaxis="y2"
                ),
            ],
            layout=_chart_layout(
                title="PCA analysis",
                xaxis=dict(title="Principal component"),
                yaxis=dict(title="Explained variance", tickformat=".0%"),
                yaxis2=dict(
                    title="Cumulative",
                    overlaying="y",
                    side="right",
                    tickformat=".0%",
                    range=[0, 1],
                ),
            ),
        )


class DefensiveChart(_StubChart):
    """Defensive scoring (stub)."""

    PLACEHOLDER = "Defensive scoring — coming soon"

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            data=[go.Bar(x=[], y=[])],
            layout=_chart_layout(
                title="Defensive scoring",
                xaxis=dict(title="Metric"),
                yaxis=dict(title="Score"),
            ),
        )
