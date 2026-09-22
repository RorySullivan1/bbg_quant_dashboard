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


#: The rolling statistics one chart offers, in chip order: the key, its
#: display label, its y-axis label, the reference line it is read against, and
#: whether it needs a benchmark.
#:
#: **Sharpe and Calmar had the stats functions and no chart anywhere** — the
#: Multi tab drew Correlation and Beta as two near-identical `RollingRefChart`s
#: and nothing drew the other two. One chart with a chip is what #368 replaced
#: that with: adding a fifth rolling statistic is a row here, not a figure, a
#: view entry, a picker label and an observer.
ROLLING_STATS: tuple[tuple[str, str, str, float, bool], ...] = (
    ("correlation", "Correlation", "Correlation", 0.0, True),
    ("sharpe", "Sharpe", "Sharpe", 0.0, False),
    ("calmar", "Calmar", "Calmar", 0.0, False),
    ("beta", "Beta", "Beta", 1.0, True),
)

#: Which rolling statistics are measured **against a benchmark**. The pane
#: hides its benchmark control for the rest, the way the Platform bar hides a
#: section its chart does not read (#331 dec. 3) — so switching away and back
#: finds the last benchmark still chosen.
ROLLING_BENCHMARK_STATS: frozenset[str] = frozenset(
    key for key, _l, _y, _r, needs in ROLLING_STATS if needs
)

_ROLLING_SPECS: dict[str, tuple[str, str, float]] = {
    key: (label, y_label, ref) for key, label, y_label, ref, _n in ROLLING_STATS
}


def rolling_stat_chips() -> list[tuple[str, str]]:
    """`(label, key)` pairs for the pane's statistic `ChipGroup`."""
    return [(label, key) for key, label, _y, _r, _n in ROLLING_STATS]


class RollingChart(Chart):
    """One rolling figure whose statistic is a chip.

    Correlation · Sharpe · Calmar · Beta over `SHARPE_WINDOW`, and the title,
    the y-axis label and the **reference line** all follow the chip — 0 for
    correlation, Sharpe and Calmar, **1** for beta, which is where a beta
    stops being interesting rather than where it changes sign.

    It replaced `RollingRefChart`, whose `title_prefix` was fixed at
    construction to close a real bug (#223: the prefix used to be passed to
    the factory *and* to every update, with nothing checking the two agreed).
    That fix survives in a stronger form here: the statistic is one key, and
    the title, axis and reference line are all derived from it, so there is
    nothing left for a caller to get out of step.

    The moving reference line is why this is a restyle rather than a second
    figure: a shape is layout, and a layout change is a `batch_update`, so
    the chip switches the view without rebuilding the widget.
    """

    def __init__(self, *, stat: str = "correlation") -> None:
        self.stat = stat
        super().__init__()

    def _build(self) -> go.FigureWidget:
        label, y_label, ref = _ROLLING_SPECS[self.stat]
        return go.FigureWidget(
            layout=_chart_layout(
                title=self._title(label, ""),
                hovermode="x unified",
                xaxis=dict(title="Date"),
                yaxis=dict(title=y_label),
                shapes=[_h_ref(ref)],
            )
        )

    @staticmethod
    def _title(label: str, benchmark_label: str) -> str:
        suffix = f" — {SHARPE_WINDOW_LABEL} rolling"
        stem = f"Rolling {label}"
        return (
            f"{stem} vs {benchmark_label}{suffix}"
            if benchmark_label
            else (f"{stem}{suffix}")
        )

    def update(
        self, df: pd.DataFrame, *, stat: str | None = None, benchmark_label: str = ""
    ) -> None:
        """Draw `df` as the named statistic, moving the chrome with it.

        `stat` defaults to the one already shown, so a plain redraw of the
        current view needs no argument. A benchmark label is only shown for
        the statistics that read one — a *Rolling Sharpe vs SPTR* title would
        name a series the number does not touch.
        """
        if stat is not None:
            self.stat = stat
        label, y_label, ref = _ROLLING_SPECS[self.stat]
        shown = benchmark_label if self.stat in ROLLING_BENCHMARK_STATS else ""
        with self.fig.batch_update():
            self.fig.layout.yaxis.title.text = y_label
            self.fig.layout.shapes = [_h_ref(ref)]
        _update_line_series(self.fig, df, title=self._title(label, shown))

    def clear(self) -> None:
        self.update(pd.DataFrame())


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


class RadarChart(Chart):
    """A closed-loop radar over a labelled Series — the body a spiderweb needs.

    What this was is `PerfRankingChart`, whose `update` drew exactly this
    whenever it was handed scores and a *coming soon* placeholder otherwise.
    Nothing ever passed it scores, so the placeholder was the only branch
    anyone saw, and a picker offering a view that cannot be drawn is a promise
    the app does not keep (#367). The intent is recorded on #376; the body
    stays, because a polar plot over standardized values is what #372's
    five-β risk profile is.

    With nothing to draw it **clears**, like every other chart here. That is
    the substantive change: an empty figure says "no data for this
    selection", where the placeholder said "not built yet" about a view that
    was.
    """

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            data=[go.Scatterpolar(r=[], theta=[], fill="toself")],
            layout=_chart_layout(
                title="Risk profile",
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            ),
        )

    def update(self, scores: pd.Series | None = None) -> None:
        """Draw `scores` — a Series of axis label → value — as a closed loop.

        The loop is closed by repeating the first point, which is what makes
        a polygon rather than an open path. None / all-NaN clears.
        """
        if scores is None or scores.dropna().empty:
            self.clear()
            return
        s = scores.dropna()
        theta = [*s.index, s.index[0]]  # close the loop back to the first axis
        r = [*s.values, s.values[0]]
        with self.fig.batch_update():
            self.fig.data = ()
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
        with self.fig.batch_update():
            self.fig.data = ()


#: The five factors the risk profile draws, in spoke order. Two premia, two
#: index factors and the volatility blend — see `stats.factors` for why the
#: three kinds are built differently.
RISK_PROFILE_FACTORS: tuple[str, ...] = (
    "ERP",
    "Term",
    "Volatility",
    "Trend",
    "Carry",
)


class RiskProfileChart(RadarChart):
    """The five-β spiderweb, on a cross-sectional percentile radial axis.

    **The axis is a percentile, and that is the whole design.** Betas to
    these five are on wildly different scales — a Carry β of 0.3 is large
    where an ERP β of 0.3 is small — so a polygon drawn on the raw numbers
    says only which factors happen to be quoted in bigger units. Each spoke
    is where the strategy sits among the catalog's own betas to that factor;
    the **raw β rides in the hover**, because the percentile is what the
    shape means and the β is what a reader will want to check it against.

    A factor the feed could not serve is a **missing spoke**, not an
    exception: `stats.factor_beta_panel` returns an all-NaN column for it and
    `dropna` takes it out of the loop, so the web draws with four points
    rather than failing.

    It replaced `FactorScoringChart`, three bars of ERP / Term / Trend — no
    Carry, no Volatility, and no way to tell a large β from a small one.
    """

    def _build(self) -> go.FigureWidget:
        fig = super()._build()
        fig.layout.title.text = f"Risk profile — {LOOKBACK_YEARS}Y factor betas"
        fig.layout.polar.radialaxis.tickformat = ".0%"
        return fig

    def update(
        self,
        percentiles: pd.Series | None = None,
        betas: pd.Series | None = None,
    ) -> None:
        """Draw the percentiles, with the raw betas in the hover.

        Both are Series indexed by factor label. `betas` is optional so the
        chart still draws from a percentile alone; where it is given, the
        two are aligned by label rather than by position, so a missing spoke
        cannot shift the hover onto the wrong factor.
        """
        if percentiles is None or percentiles.dropna().empty:
            self.clear()
            return
        shown = percentiles.dropna()
        raw = (
            betas.reindex(shown.index)
            if betas is not None
            else pd.Series(float("nan"), index=shown.index)
        )
        theta = [*shown.index, shown.index[0]]  # close the loop
        r = [*shown.values, shown.values[0]]
        hover = [*raw.values, raw.values[0]]
        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.add_traces(
                [
                    go.Scatterpolar(
                        r=r,
                        theta=theta,
                        fill="toself",
                        line=dict(color=_palette_color(0)),
                        customdata=hover,
                        hovertemplate=(
                            "%{theta}<br>%{r:.0%} of the catalog"
                            "<br>β = %{customdata:.2f}<extra></extra>"
                        ),
                    )
                ]
            )


class RegimeProfileChart(Chart):
    """One strategy's return/vol under **all three** buckets of one regime.

    The Platform Scatter conditions a whole catalog on one bucket at a time.
    Nothing showed how *one* strategy moves **across** a regime's buckets —
    which is the question a desk asks of a single strategy, and the reason
    this chart has no bucket control: all three buckets are the chart.

    The **unconditioned point is drawn muted, as the anchor**, so the three
    read as deviations from the strategy's own whole-window profile rather
    than as three unrelated dots. Without it a reader has no scale for "the
    high-vol bucket is over there".

    The benchmark's three are drawn too when it is given, so the strategy's
    regime sensitivity reads against something. A bucket with too few days to
    measure is simply absent — `regime_risk_return` returns an empty frame
    below two, and a point invented from one day would be the worst kind of
    wrong here.
    """

    #: The muted anchor and the three buckets, in bucket order. The buckets
    #: take the shared positional palette so a bucket's colour matches the
    #: legend entry beside it and nothing else on the tab.
    ANCHOR_LABEL: str = "Whole window"

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            layout=_chart_layout(
                title="Regime profile",
                hovermode="closest",
                xaxis=dict(
                    title="Annualized Volatility",
                    tickformat=".0%",
                    rangemode="tozero",
                ),
                yaxis=dict(title="Annualized Return", tickformat=".0%"),
                showlegend=True,
            )
        )

    def update(
        self,
        points: pd.DataFrame,
        *,
        regime_label: str = "",
        benchmark_label: str = "",
    ) -> None:
        """Draw the points.

        `points` is indexed by bucket label with `vol` / `ret` columns and a
        `series` column naming which line each belongs to — the strategy, the
        benchmark, or `ANCHOR_LABEL`. One frame rather than three arguments
        because every point is drawn the same way and only its grouping
        differs; building it is `single_strategy`'s, which is where the masks
        and the cache live.
        """
        if points is None or points.empty:
            self.clear()
            return
        frame = points.dropna(subset=["vol", "ret"])
        if frame.empty:
            self.clear()
            return
        traces: list[go.Scatter] = []
        for position, (name, block) in enumerate(frame.groupby("series", sort=False)):
            anchor = bool(block["anchor"].iloc[0]) if "anchor" in block else False
            traces.append(
                go.Scatter(
                    x=block["vol"].to_numpy(),
                    y=block["ret"].to_numpy(),
                    mode="markers+text",
                    name=str(name),
                    text=[str(i) for i in block.index],
                    textposition="top center",
                    textfont=dict(
                        color=(
                            Color.TEXT_MUTED.value if anchor else Color.CHART_TEXT.value
                        ),
                        size=10,
                    ),
                    marker=dict(
                        size=18 if anchor else 13,
                        color=(
                            Color.TEXT_MUTED.value
                            if anchor
                            else _palette_color(position)
                        ),
                        symbol="diamond-open" if anchor else "circle",
                        line=dict(width=2 if anchor else 0),
                    ),
                    hovertemplate=(
                        f"{name} — %{{text}}"
                        "<br>Vol %{x:.2%}<br>Return %{y:.2%}<extra></extra>"
                    ),
                )
            )
        stem = f"Regime profile — {regime_label}" if regime_label else "Regime profile"
        title = f"{stem} vs {benchmark_label}" if benchmark_label else stem
        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.add_traces(traces)
            self.fig.layout.title.text = title

    def clear(self) -> None:
        with self.fig.batch_update():
            self.fig.data = ()


class DecileChart(Chart):
    """The strategy's mean return per benchmark-return decile, beside the
    benchmark's own — ten column pairs, worst decile on the left.

    **Convexity, read left to right.** A strategy that keeps its upside and
    cushions its downside draws a smile against the benchmark's straight
    line; one that is short volatility draws a frown. No summary statistic on
    this tab shows that: a β is the average slope and says nothing about
    whether the slope is the same at both ends.

    **Weekly, not daily** (#363 dec. 7 left the call to the terminal). A
    daily decile's tails are dominated by single-session noise and by when a
    series marks, which is a question about plumbing rather than about the
    strategy; a week is the shortest horizon at which "how does this behave
    when the market falls" is a real reading. The axis title says so, because
    the same chart at a different horizon is a different chart.

    The **benchmark decides the buckets** and the strategy is measured inside
    them — cutting on the strategy's own returns would draw a monotone
    staircase for any series at all.
    """

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            layout=_chart_layout(
                title="Return by benchmark decile",
                barmode="group",
                hovermode="x unified",
                xaxis=dict(
                    title="Benchmark weekly-return decile (worst → best)",
                    dtick=1,
                ),
                yaxis=dict(title="Mean weekly return", tickformat=".1%"),
                shapes=[_h_ref(0.0)],
                showlegend=True,
            )
        )

    def update(
        self,
        profile: pd.DataFrame,
        *,
        strategy_label: str = "Strategy",
        benchmark_label: str = "Benchmark",
        regime_label: str = "",
    ) -> None:
        """Draw a `stats.decile_profile` frame as paired columns.

        `regime_label` names the bucket the periods were restricted to, and
        goes in the **title** rather than a caption: every bucket is a subset
        of the window, so a conditioned chart that does not say so is a
        narrowed sample the reader cannot see (v0.9.33's reason).
        """
        if profile is None or profile.empty:
            self.clear()
            return
        deciles = list(profile.index)
        traces = [
            go.Bar(
                x=deciles,
                y=profile[column].to_numpy(),
                name=name,
                marker=dict(color=_palette_color(position)),
                hovertemplate=f"{name} %{{y:.2%}}<extra></extra>",
            )
            for position, (column, name) in enumerate(
                (("strategy", strategy_label), ("benchmark", benchmark_label))
            )
        ]
        title = "Return by benchmark decile"
        if regime_label:
            title = f"{title} — {regime_label}"
        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.add_traces(traces)
            self.fig.layout.title.text = title

    def clear(self) -> None:
        with self.fig.batch_update():
            self.fig.data = ()
