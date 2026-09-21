"""Platform-tab chart factories + updaters.

Standalone visuals for the Platform tab — the factor-beta scatter, the
asset-class sunburst, and the regime views — as distinct from the analysis
panes (`panes.py` / `charts.py`), which belong to the Multi-Strategy tab.

Every figure follows the same two-part shape: a factory builds it once, and an
updater mutates it in place inside a `fig.batch_update()` block. Updaters
compute from the already-fetched price cache, so no chart here issues a BQL
call.

`PlatformAnalytics` (#219) owns the analytics card: the three figures, the tab
pills, their control columns, and the lazy-render state. It used to be a
twenty-field `SimpleNamespace` assembled in `build_app` and handed back to
twelve free functions declared `(state, meta, pa)` — a class with its `self`
passed by hand.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from typing import TYPE_CHECKING

import ipywidgets as W
import pandas as pd
import plotly.graph_objects as go

from ..config import (
    CATALOG_SCORE_MIN_SAMPLE_DAYS,
    DEFAULT_RANKING_METRIC,
    REGIME_SPECS,
    SCORE_SAMPLE_DAYS,
    TRADING_DAYS_PER_YEAR,
    LevelRegime,
    TercileRegime,
    analytics_levels,
    drill_level_label,
    drill_levels,
    rankable_metric_chips,
    stat_window_years,
    stat_windows,
    universe_grid_default_window,
)
from ..stats import (
    daily_returns,
    equity_risk_premium,
    factor_beta,
    icicle_frame,
    regime_mask,
    regime_risk_return,
    rolling_autocorr,
    rolling_metric_zscore,
    tercile_bounds,
    term_premium,
    trend_returns,
)
from ..style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR, LINE_PALETTE, Color
from .drill import Drill
from .grids import zscore_column_name
from .html import STYLE_CTX, render_template
from .rails import Breadcrumb, ChipGroup, RailSection, control_bar
from .theme import _chart_layout, _short_ticker

if TYPE_CHECKING:
    # No cycle today, but `state.py` is one import away from reaching this
    # module, and the annotation never needs the symbol at runtime. Guarded
    # like `filter_panel` / `single_strategy`, where the cycle is real.
    from .state import DashboardState


def _asset_class_colors(classes: Iterable[str]) -> dict[str, str]:
    """Distinct color per asset class for the factor scatter legend.

    Curated `ASSET_CLASS_COLORS` tokens come first; any class not in that map
    is assigned the next unused `LINE_PALETTE` color (so an unmapped class still
    renders distinctly rather than collapsing onto the grey fallback), and only
    falls back to `ASSET_CLASS_FALLBACK_COLOR` once the palette is exhausted.
    Deterministic in the sorted order of the present classes."""
    used = set(ASSET_CLASS_COLORS.values())
    spare = [c for c in LINE_PALETTE if c not in used]
    out: dict[str, str] = {}
    for ac in sorted({str(c) for c in classes}):
        if ac in ASSET_CLASS_COLORS:
            out[ac] = ASSET_CLASS_COLORS[ac]
        elif spare:
            out[ac] = spare.pop(0)
        else:
            out[ac] = ASSET_CLASS_FALLBACK_COLOR
    return out


_FACTOR_HOVER = (
    "%{{text}}<br>{ac}<br>Equity β %{{x:.2f}}<br>Term β %{{y:.2f}}"
    "<br>Trend β %{{z:.2f}}<extra></extra>"
)

# Opacity of the factor scatter's translucent zero-reference planes (x=0, y=0,
# z=0). Faint enough to read the marker cloud through, solid enough to locate 0.
_ZERO_PLANE_OPACITY = 0.20


def _axis_bounds(
    values: pd.Series, *, pad: float = 0.1, fallback: float = 1.0
) -> tuple[float, float]:
    """``(low, high)`` span for one factor axis, always bracketing 0 and padded.

    The span is stretched to include 0 (so a zero plane sits inside it) then
    padded by ``pad`` on each side; a degenerate span (single point / all-equal /
    all-zero betas) falls back to ``±fallback`` so the plane stays visible.
    """
    lo = min(float(values.min()), 0.0)
    hi = max(float(values.max()), 0.0)
    span = hi - lo
    if span <= 0:
        return (-fallback, fallback)
    margin = span * pad
    return (lo - margin, hi + margin)


def _quad_mesh(
    name: str, xs: list[float], ys: list[float], zs: list[float]
) -> go.Mesh3d:
    """A flat 4-vertex quad (two triangles) as a translucent reference plane."""
    return go.Mesh3d(
        name=name,
        x=xs,
        y=ys,
        z=zs,
        i=[0, 0],
        j=[1, 2],
        k=[2, 3],
        color=Color.CHART_AXIS.value,
        opacity=_ZERO_PLANE_OPACITY,
        flatshading=True,
        hoverinfo="skip",
        showlegend=False,
    )


def _zero_planes(frame: pd.DataFrame) -> list[go.Mesh3d]:
    """Three translucent zero-reference planes (x=0, y=0, z=0), sized to the
    point cloud, so the origin is legible in every dimension of the 3D scatter.

    Each plane spans the padded data bounds of its other two axes (see
    ``_axis_bounds``), so it covers the marker cloud and crosses 0.
    """
    xlo, xhi = _axis_bounds(frame["x"])
    ylo, yhi = _axis_bounds(frame["y"])
    zlo, zhi = _axis_bounds(frame["z"])
    return [
        # x = 0: spans y × z
        _quad_mesh("x=0", [0, 0, 0, 0], [ylo, yhi, yhi, ylo], [zlo, zlo, zhi, zhi]),
        # y = 0: spans x × z
        _quad_mesh("y=0", [xlo, xhi, xhi, xlo], [0, 0, 0, 0], [zlo, zlo, zhi, zhi]),
        # z = 0: spans x × y
        _quad_mesh("z=0", [xlo, xhi, xhi, xlo], [ylo, ylo, yhi, yhi], [0, 0, 0, 0]),
    ]


# Sunburst node-id separator (one segment per configured level), diverging
# the per-node hover. The colorscale matches the all-catalog grid's
# red<0 → neutral → green>0 sentiment and is token-driven (no inline hex). The
# hover is a `.format()` template — `metric_label` is user-selected at render
# time (the literal plotly `%{...}` placeholders are doubled to survive
# `.format()`); `percentParent` is the segment's gross-|z| share of its ring.
_SUNBURST_SEP = " / "
_SUNBURST_COLORSCALE = [
    [0.0, Color.RED_600.value],
    [0.5, Color.SLATE_500.value],
    [1.0, Color.GREEN_600.value],
]
_SUNBURST_HOVER = (
    "%{{label}}<br>z({metric_label}) %{{color:.2f}}"
    "<br>%{{percentParent:.0%}} of parent<extra></extra>"
)
# Minimum visible arc, as a fraction of the max |z|, so a near-average (|z|≈0)
# ticker stays visible. Lower = more contrast.
_SUNBURST_SIZE_FLOOR = 0.02


def _sunburst_leaf_sizes(z: pd.Series) -> pd.Series:
    """Per-ticker arc value = |z| (gross magnitude), plus a small floor so a
    near-average (|z|≈0) ticker stays visible. With ``branchvalues="total"`` each
    ring's arc is then its gross-|z| share of its parent, at every level.
    All-zero (or empty) input falls back to uniform arcs."""
    mag = z.abs()
    hi = float(mag.max()) if len(mag) else 0.0
    if hi <= 0:
        return pd.Series(1.0, index=z.index)
    return mag + _SUNBURST_SIZE_FLOOR * hi


def _factor_beta_scatter() -> go.FigureWidget:
    """3D factor-beta scatter: x = β to the equity risk premium, y = β to the
    term premium, z = β to the cross-asset trend factor ("Trend Exposure"), one
    marker per strategy (colored by asset class). Built empty;
    `_update_factor_scatter` fills it — markers plus three translucent
    zero-reference planes (x=0/y=0/z=0) that mark the origin in every
    dimension. No in-figure title — the "Factor exposures" section header stands
    alone. The legend is on (unlike the pane charts, this chart has no
    grid legend to key its asset-class colors); each scene axis also carries a
    zero line on the scene wall (paper shapes don't apply to a 3D scene)."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="",
            showlegend=True,
            legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
            scene=dict(
                xaxis=dict(title="Equity risk-premium β", zeroline=True),
                yaxis=dict(title="Term-premium β", zeroline=True),
                zaxis=dict(title="Trend Exposure", zeroline=True),
            ),
        )
    )


def _update_factor_scatter(
    fig: go.FigureWidget,
    arp_prices: pd.DataFrame,
    universe_prices: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    years: float,
    returns: pd.DataFrame | None = None,
) -> None:
    """Populate the 3D factor-beta scatter from the cached prices: per-strategy
    betas to the equity-risk-premium (x), term-premium (y), and trend (z) factor
    series, one trace per asset class (so the colors carry a legend), over three
    translucent zero-reference planes (x=0/y=0/z=0) that mark the origin in every
    dimension. No BQL — pure compute over the already-fetched cache."""
    if arp_prices.empty or universe_prices.empty:
        with fig.batch_update():
            fig.data = ()
        return

    erp = equity_risk_premium(universe_prices)
    tp = term_premium(universe_prices)
    trend = trend_returns(universe_prices)
    rets = daily_returns(arp_prices) if returns is None else returns
    frame = pd.DataFrame(
        {
            "x": factor_beta(rets, erp, years),
            "y": factor_beta(rets, tp, years),
            "z": factor_beta(rets, trend, years),
        }
    ).dropna()

    if frame.empty:
        with fig.batch_update():
            fig.data = ()
        return

    ac_map = meta.set_index("ticker")["asset_class"] if "ticker" in meta else None
    frame["ac"] = [
        (ac_map.get(t, "Other") if ac_map is not None else "Other") for t in frame.index
    ]

    color_for = _asset_class_colors(frame["ac"])
    traces = []
    for ac, grp in frame.groupby("ac"):
        traces.append(
            go.Scatter3d(
                mode="markers",
                name=str(ac),
                x=grp["x"].to_numpy(),
                y=grp["y"].to_numpy(),
                z=grp["z"].to_numpy(),
                marker=dict(
                    size=5,
                    color=color_for[str(ac)],
                    line=dict(width=0),
                ),
                text=[_short_ticker(t) for t in grp.index],
                hovertemplate=_FACTOR_HOVER.format(ac=str(ac)),
            )
        )

    with fig.batch_update():
        fig.data = ()
        # Planes first so the markers render over them.
        fig.add_traces([*_zero_planes(frame), *traces])


def _sunburst() -> go.FigureWidget:
    """The `config.ANALYTICS_LEVELS` hierarchy down to ticker leaves (inside
    out), arcs sized by each ring's gross-|z| share and colored by the
    (level-averaged) metric z-score.
    Built empty; `_update_sunburst` fills it. No in-figure title — the
    "Risk-adjusted strength map" section header stands alone; the
    diverging colorbar is the color legend."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="",
            margin=dict(t=44, b=10, l=10, r=10),
        )
    )


def _update_sunburst(
    fig: go.FigureWidget,
    prices: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    metric: str,
    window: int,
    label: str,
) -> None:
    """Populate the sunburst from `icicle_frame`: one ring per
    `config.ANALYTICS_LEVELS` entry over the ticker leaves, so reconfiguring the
    hierarchy — two levels today, the three framework tiers if that is what the
    catalog should show — needs no edit here. Each arc is sized by |z| (so with
    `branchvalues="total"` a ring's arc is its gross-|z| share of its parent) and
    colored by the metric z-score, averaged up each level (parent color = mean of
    its descendant tickers' z). `maxdepth` shows the grouping rings up front; the
    ticker ring appears when the user clicks into one (client-side drill-down).
    `label` (e.g. "1W Sharpe") titles the colorbar + hover. No BQL — pure compute
    over the already-fetched cache."""
    frame = icicle_frame(prices, meta, metric=metric, window=window).dropna(
        subset=["value"]
    )
    if frame.empty:
        with fig.batch_update():
            fig.data = ()
        return

    levels = list(analytics_levels())
    frame = frame.copy()
    for level in levels:
        frame[level] = frame[level].fillna("Other").astype(str)
    # Arc value = |z| (gross magnitude) + floor; parents sum to the gross-|z|
    # share at each ring. Color is the signed z (below), averaged up each level.
    frame["size"] = _sunburst_leaf_sizes(frame["value"])

    ids: list[str] = []
    labels: list[str] = []
    parents: list[str] = []
    values: list[float] = []
    colors: list[float] = []

    def _emit(group: pd.DataFrame, depth: int, parent_id: str) -> float:
        """Emit one subtree's nodes, returning its total arc value.

        Depth-first and bottom-up: a node's value is the sum its children
        actually reported, not a second aggregation of the same rows, so
        ``branchvalues="total"`` holds exactly at every ring however many there
        are. ``parent_id`` is "" at the top, which is Plotly's root.
        """
        if depth == len(levels):
            for ticker, row in group.iterrows():
                ids.append(ticker)
                labels.append(_short_ticker(ticker))
                parents.append(parent_id)
                values.append(float(row["size"]))
                colors.append(float(row["value"]))
            return float(group["size"].sum())

        total = 0.0
        for value, sub in group.groupby(levels[depth]):
            # Ids are the path, so the same leaf label under two different
            # parents stays two nodes.
            node_id = f"{parent_id}{_SUNBURST_SEP}{value}" if parent_id else str(value)
            subtotal = _emit(sub, depth + 1, node_id)
            ids.append(node_id)
            labels.append(str(value))
            parents.append(parent_id)
            values.append(subtotal)
            colors.append(float(sub["value"].mean()))
            total += subtotal
        return total

    _emit(frame, 0, "")

    sunburst = go.Sunburst(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        branchvalues="total",
        # Show one ring per configured level from the current center, so the
        # ticker ring stays hidden until the user clicks into a grouping node to
        # drill in (client-side zoom, no recompute).
        maxdepth=len(levels),
        insidetextorientation="radial",
        marker=dict(
            colors=colors,
            colorscale=_SUNBURST_COLORSCALE,
            cmid=0,
            cmin=-2,
            cmax=2,
            line=dict(width=1, color=Color.CHART_BG.value),
            showscale=True,
            colorbar=dict(title=dict(text=label)),
        ),
        hovertemplate=_SUNBURST_HOVER.format(metric_label=label),
    )
    with fig.batch_update():
        fig.data = ()
        fig.add_traces([sunburst])


# --- Regime Analysis: regime-conditioned risk/return scatter ----------------

_REGIME_RR_HOVER = (
    "%{{text}}<br>{ac}<br>Vol %{{x:.1%}}<br>Return %{{y:.1%}}"
    "<br>Sharpe %{{customdata:.2f}}<extra></extra>"
)


def _regime_window_mask(
    indicator: pd.Series | None,
    index: pd.Index,
    low: float | None,
    high: float | None,
) -> pd.Series:
    """Boolean mask over ``index``: the regime bucket, or all-True when there's
    no indicator / no bucket (a scaffolded regime → unconditioned all-days view).
    """
    if indicator is None or indicator.empty or low is None or high is None:
        return pd.Series(True, index=index)
    return regime_mask(indicator.reindex(index), low, high)


def _regime_scatter() -> go.FigureWidget:
    """Regime-conditioned risk/return scatter — annualized vol (x) vs return (y)
    over only the selected regime bucket's days, one marker per strategy colored
    by asset class. Built empty; `_update_regime_scatter` fills it. No in-figure
    title — the section header + regime controls stand alone."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="",
            showlegend=True,
            legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
            hovermode="closest",
            xaxis=dict(
                title="Annualized volatility", tickformat=".0%", rangemode="tozero"
            ),
            yaxis=dict(title="Annualized return", tickformat=".0%"),
        )
    )


def _update_regime_scatter(
    fig: go.FigureWidget,
    arp_prices: pd.DataFrame,
    indicator: pd.Series | None,
    meta: pd.DataFrame,
    *,
    low: float | None,
    high: float | None,
    lookback: int,
    returns: pd.DataFrame | None = None,
) -> None:
    """Populate the regime risk/return scatter: per-strategy vol/return/Sharpe
    over the lookback window restricted to the regime-bucket days (mean-based
    annualization via `regime_risk_return`), one trace per asset class. No BQL.

    ``returns`` (the shared ``universe_rets``) avoids re-deriving daily returns:
    ``daily_returns(arp).tail(lookback - 1)`` is exactly ``daily_returns(arp.tail(
    lookback))`` — a ``lookback``-row price slice yields ``lookback - 1`` returns,
    the same trailing rows as slicing the full-history returns."""
    if arp_prices.empty:
        with fig.batch_update():
            fig.data = ()
        return
    if returns is None:
        rets = daily_returns(arp_prices.tail(lookback))
    else:
        rets = returns.tail(lookback - 1)
    mask = _regime_window_mask(indicator, rets.index, low, high)
    frame = regime_risk_return(rets, mask).dropna(subset=["vol", "ret"])
    if frame.empty:
        with fig.batch_update():
            fig.data = ()
        return

    ac_map = meta.set_index("ticker")["asset_class"] if "ticker" in meta else None
    frame = frame.copy()
    frame["ac"] = [
        (ac_map.get(t, "Other") if ac_map is not None else "Other") for t in frame.index
    ]
    color_for = _asset_class_colors(frame["ac"])
    traces = []
    for ac, grp in frame.groupby("ac"):
        traces.append(
            go.Scatter(
                mode="markers",
                name=str(ac),
                x=grp["vol"].to_numpy(),
                y=grp["ret"].to_numpy(),
                marker=dict(size=8, color=color_for[str(ac)], line=dict(width=0)),
                text=[_short_ticker(t) for t in grp.index],
                customdata=grp["sharpe"].to_numpy(),
                hovertemplate=_REGIME_RR_HOVER.format(ac=str(ac)),
            )
        )
    with fig.batch_update():
        fig.data = ()
        fig.add_traces(traces)


# --- Platform-analytics orchestration -----------------------------------------
# ``DashboardApp`` constructs one ``PlatformAnalytics``, calls ``wire`` with a
# catalog provider, and mounts ``.card``. Every render reads the cache on
# ``state``.


@contextmanager
def _guard_render(state: DashboardState, label: str):
    """Route any exception raised in the block into ``state.init_errors`` labeled
    with ``label`` — the shared error handling for the Platform render functions
    (a failed chart records its traceback in the commentary block rather than
    breaking the whole render)."""
    try:
        yield
    except Exception:
        state.init_errors.append(f"{label} failed:\n{traceback.format_exc()}")


def regime_bucket_options(regime_type: str) -> list[tuple[str, object]]:
    """Bucket-dropdown options for a regime: ``(label, (low, high))`` for the
    fixed-level mode, ``(label, tercile_key)`` for the tercile modes."""
    spec = REGIME_SPECS[regime_type]
    if isinstance(spec, LevelRegime):
        return [(label, (low, high)) for label, low, high in spec.buckets]
    return [(label, key) for label, key in spec.bucket_labels]


def _window_days(label: str) -> int:
    """A stats-window label (`"6M"`, `"1Y"`) as a trading-day count.

    The table's Window chips carry labels, because that is what decides which
    performance columns are visible; the scorer wants a count of rows. One
    conversion, here, rather than the same product spelled at the call site and
    again in whatever reads it next — and `stat_window_years` is what keeps
    `"6M"` half a year instead of six (#324).
    """
    return round(stat_window_years(label) * TRADING_DAYS_PER_YEAR)


class PlatformAnalytics:
    """The Platform tab's analytics card: three charts behind three pill-tabs.

    Owns its widgets (figures, pills, per-tab control columns, the shared
    lookback) and its **lazy-render state** — `active_analytics` is the visible
    tab, `fresh` the set already drawn against current data. Only the visible
    chart is computed on load or Refresh; the hidden two draw on first
    activation, and a data or lookback change marks all three stale and
    re-draws only the visible one (v0.9.13 #168).

    **`meta` stays a per-call argument rather than an attribute.** `build_app`
    re-points its `meta` to the recent-performance-pruned catalog after each
    load, so an attribute set at construction would go stale — silently, since
    a stale catalog still renders, just with the pruned indices back. Passing it
    makes that impossible. (The observers wired in `wire` do capture the `meta`
    they were given, which is the pre-existing behaviour tracked in #242.)

    `state` *is* held: it is one mutable object whose contents change in place,
    so a reference is always current.
    """

    def __init__(
        self,
        state: DashboardState,
        *,
        z_metric_chips: ChipGroup,
        window_chips: ChipGroup,
    ) -> None:
        self.state = state
        # The all-catalog grid's ranking controls live with the table, not in
        # the card, but drive `render_universe_grid` — so they are passed in,
        # not built. The injection has survived two restyles unchanged
        # (dropdowns → chips in #279, rail → table bar in #325), because
        # `ChipGroup` carries the same `.value` / `.label` / `.observe` surface
        # a dropdown does — `.label` in particular, which names the z column.
        #
        # `window_chips` is the **table's** Window, the one that also decides
        # which performance columns are visible. Since #324 there is no second
        # window and no lookback: the score is measured over the period the row
        # is being read at, against a fixed `SCORE_SAMPLE_DAYS` sample.
        self.z_metric_chips = z_metric_chips
        self.window_chips = window_chips
        #: Resolved at fire time, never captured (#242). `wire` sets it.
        self._current_meta: Callable[[], pd.DataFrame] | None = None

        self.sunburst_fig = _sunburst()
        self.regime_scatter_fig = _regime_scatter()
        self.factor_scatter_fig = _factor_beta_scatter()
        # A placeholder until #336 builds the chart. The Chart chip's three
        # keys are final from here, so the bar and its wiring do not change
        # again when the figure arrives.
        self.strip_placeholder = W.HTML(
            render_template(
                "empty_card",
                **STYLE_CTX,
                message="The Strip chart arrives in #336.",
            )
        )

        # --- the Chart view bar (#333) ---------------------------------------
        #
        # The card's own chips over the table's own option lists: the two
        # surfaces can be read at different windows but cannot OFFER different
        # things (#331 decision 1). Nothing here spells a label — Metric comes
        # from `RANKABLE_METRICS`, Window from `stat_windows()`, Level from
        # `drill_levels()` — so a relabelling reaches the card for free.
        self.chart_chips = ChipGroup(
            [("Icicle", "icicle"), ("Scatter", "scatter"), ("Strip", "strip")],
            value="icicle",
            row=True,
        )
        self.metric_chips = ChipGroup(
            rankable_metric_chips(), value=DEFAULT_RANKING_METRIC, row=True
        )
        self.card_window_chips = ChipGroup(
            [label for label, _ in stat_windows()],
            value=universe_grid_default_window(),
            row=True,
        )

        self.regime_type_chips = ChipGroup(list(REGIME_SPECS.keys()), row=True)
        # Source stays a dropdown: its options are the live benchmark registry
        # or a region list, and a dropdown is the right control for a long list
        # (#331 decision 13, #302's reasoning).
        self.regime_selector_dd = W.Dropdown(
            options=[("\u2014", "")],
            value="",
            description="Source",
            style={"description_width": "60px"},
            layout=W.Layout(width="240px"),
        )
        _init_buckets = regime_bucket_options(self.regime_type_chips.value)
        self.regime_bucket_chips = ChipGroup(
            _init_buckets, value=_init_buckets[0][1], row=True
        )
        regime_controls = W.VBox(
            [self.regime_type_chips, self.regime_selector_dd, self.regime_bucket_chips],
            layout=W.Layout(width="auto"),
        )

        self.level_chips = ChipGroup(
            [(drill_level_label(key), key) for key in drill_levels()],
            value=drill_levels()[0],
            row=True,
        )
        self.breadcrumb = Breadcrumb(on_pick=self._on_breadcrumb)

        self.bar = control_bar(
            RailSection("Chart", self.chart_chips),
            RailSection("Metric", self.metric_chips),
            RailSection("Window", self.card_window_chips),
            RailSection("Regime", regime_controls),
            RailSection("Level", self.level_chips),
            RailSection("Scope", self.breadcrumb),
            title="Chart view",
        )

        #: Chart key -> the figure (or placeholder) it mounts.
        self.analytics_tabs = {
            "icicle": self.sunburst_fig,
            "scatter": self.regime_scatter_fig,
            "strip": self.strip_placeholder,
        }

        self.chart_box = W.Box(
            [self.sunburst_fig], layout=W.Layout(flex="1 1 0%", width="100%")
        )
        analytics_body = W.HBox(
            [self.chart_box],
            layout=W.Layout(width="100%", align_items="stretch"),
        )

        self.card = W.VBox(
            [
                W.HTML(
                    render_template(
                        "grid_header", **STYLE_CTX, text="Platform analytics"
                    )
                ),
                self.bar,
                analytics_body,
            ],
            layout=W.Layout(width="100%"),
        )
        self.card.add_class("bbg-card")
        # A back-reference so a test (and a future sibling panel) can reach the
        # controller from the widget tree without counting child indices, which
        # move whenever the card is restyled.
        self.card._analytics = self

        #: Where the user is. One object, replaced wholesale through
        #: `set_drill`, read by every chart and (from #337) the points table.
        self.drill = Drill()
        #: Set while `set_drill` repaints the Level chips and the breadcrumb,
        #: so their own observers do not re-enter it and render twice.
        self._syncing_drill = False

        #: Lazy-render state: the visible chart, and those drawn against the
        #: current data.
        self.active_analytics: str = "icicle"
        self.fresh: set[str] = set()
        self._sync_sections()

    # --- the drill ------------------------------------------------------------

    def set_drill(self, scope: tuple[str, ...], level: str) -> None:
        """The one writer of `self.drill`.

        Every entry point — a Level chip, a breadcrumb segment, and from
        #334-#337 a marker click, an icicle zoom and a table row — lands here,
        so no chart can hold a private focus (#331 decision 15). Repaints the
        two controls that display the state with their observers suppressed,
        then re-renders the visible chart once.
        """
        self.drill = Drill(scope=tuple(scope), level=level)
        self._syncing_drill = True
        try:
            self.level_chips.value = self.drill.level
            self.breadcrumb.set_path(self.drill.scope)
        finally:
            self._syncing_drill = False

    def narrow_to(self, path: tuple[str, ...]) -> None:
        """Move into ``path`` and show its children — what a click means."""
        moved = self.drill.narrowed_to(tuple(path))
        self.set_drill(moved.scope, moved.level)

    def _on_breadcrumb(self, prefix: tuple[str, ...]) -> None:
        """A breadcrumb segment: back to that prefix, at the stop below it."""
        if self._syncing_drill:
            return
        self.narrow_to(prefix)
        self._render_current()

    def _on_level_chip(self, _change=None) -> None:
        """A Level chip sets the depth within the current scope."""
        if self._syncing_drill:
            return
        self.set_drill(self.drill.scope, self.level_chips.value)
        self._render_current()

    def _render_current(self) -> None:
        """Re-render the visible chart from whatever `_current_meta` resolves to.

        Set by `wire`; before that the card has not been wired to a catalog and
        a drill change has nothing to draw.
        """
        if self._current_meta is not None:
            self._render_tab(self._current_meta(), self.active_analytics)

    # --- conditional sections -------------------------------------------------

    def _sync_sections(self) -> None:
        """Show only the sections the active chart reads (#331 decision 3).

        Hiding rather than rebuilding, so a chip keeps its selection across a
        chart switch: the Strip does not read Metric, but coming back to the
        Scatter should find the metric the user last chose still chosen.
        """
        # Keyed to `active_analytics`, not to the chip: the chip drives
        # `activate`, which sets it, so they agree in the app — and a direct
        # `activate` call stays self-consistent instead of syncing the sections
        # against whatever the chip happened to hold.
        chart = self.active_analytics
        self.bar.show("Regime", chart == "scatter")
        self.bar.show("Metric", chart != "strip")
        self.bar.show("Window", chart != "strip")
        self.bar.show("Level", chart != "icicle")
        self.bar.show("Scope", chart != "icicle")

    # --- per-chart renders ----------------------------------------------------

    def render_universe_grid(self, meta: pd.DataFrame) -> None:
        """Render the all-catalog grid with the ranking column the current
        Metric and Window chips describe.

        The score is the selected metric over the selected window, standardized
        against `SCORE_SAMPLE_DAYS` of that metric's own rolling history — a
        fixed sample, so the column is comparable to itself across windows and
        to the Leaderboard beside it (#324). A ticker that cannot supply
        `CATALOG_SCORE_MIN_SAMPLE_DAYS` of that sample scores NaN and renders a
        dash rather than being standardized against the little it has.

        Reads the cached perf table (``state.universe_up``) and computes only
        the ranking column live from the already-fetched
        ``arp_universe_prices`` — no BQL, no recompute.
        """
        state = self.state
        if state.arp_universe_prices.empty:
            return
        with _guard_render(state, "all-catalog grid z-score render"):
            window_label = self.window_chips.value
            zcol = rolling_metric_zscore(
                state.arp_universe_prices,
                metric=self.z_metric_chips.value,
                window=_window_days(window_label),
                zscore_window=SCORE_SAMPLE_DAYS,
                min_sample=CATALOG_SCORE_MIN_SAMPLE_DAYS,
                returns=state.universe_rets,
            )
            state.universe_grid.update(
                meta,
                state.universe_up,
                zcol=zcol,
                zname=zscore_column_name(self.z_metric_chips.label, window_label),
            )

    def render_factor_scatter(self, meta: pd.DataFrame) -> None:
        """Render the 3D factor-beta scatter at the selected lookback, live from
        the fetched cache (no BQL)."""
        state = self.state
        if state.arp_universe_prices.empty or state.universe_prices.empty:
            return
        with _guard_render(state, "factor-beta scatter render"):
            _update_factor_scatter(
                self.factor_scatter_fig,
                state.arp_universe_prices,
                state.universe_prices,
                meta,
                years=stat_window_years(self.card_window_chips.value),
                returns=state.universe_rets,
            )

    def render_sunburst(self, meta: pd.DataFrame) -> None:
        """Render the `ANALYTICS_LEVELS` -> ticker sunburst from the Metric/Window
        Z-score controls + the shared lookback, live from the ARP-only cache."""
        state = self.state
        if state.arp_universe_prices.empty:
            return
        with _guard_render(state, "sunburst render"):
            _update_sunburst(
                self.sunburst_fig,
                state.arp_universe_prices,
                meta,
                metric=self.metric_chips.value,
                window=_window_days(self.card_window_chips.value),
                label=f"{self.card_window_chips.label} {self.metric_chips.label}",
            )

    def render_regime_scatter(self, meta: pd.DataFrame) -> None:
        """Render the regime risk/return scatter at the current regime / source /
        bucket + lookback, live from the cache (no BQL)."""
        state = self.state
        if state.arp_universe_prices.empty:
            return
        with _guard_render(state, "regime scatter render"):
            low, high = self.resolve_regime_bucket()
            _update_regime_scatter(
                self.regime_scatter_fig,
                state.arp_universe_prices,
                self.regime_indicator(),
                meta,
                low=low,
                high=high,
                lookback=_window_days(self.card_window_chips.value),
                returns=state.universe_rets,
            )

    # --- regime resolution ----------------------------------------------------

    def regime_indicator(self) -> pd.Series | None:
        """The regime indicator series from the cache, per the active regime's
        shape, or None when its ticker(s) are absent (-> unconditioned view)."""
        spec = REGIME_SPECS.get(self.regime_type_chips.value)
        if spec is None:
            return None
        prices = self.state.universe_prices
        if isinstance(spec, TercileRegime) and spec.kind == "autocorr":
            ticker = self.regime_selector_dd.value
            if not ticker or ticker not in prices.columns:
                return None
            rets = daily_returns(prices[[ticker]])[ticker]
            return rolling_autocorr(rets, window=spec.autocorr_window)
        # Both remaining shapes read a raw level; only the ticker's source
        # differs — a tercile regime's comes from its dropdown, a level
        # regime's is fixed.
        ticker = (
            spec.ticker
            if isinstance(spec, LevelRegime)
            else self.regime_selector_dd.value
        )
        if not ticker or ticker not in prices.columns:
            return None
        return prices[ticker]

    def resolve_regime_bucket(self) -> tuple[float | None, float | None]:
        """The ``(low, high)`` bounds for the active bucket. Fixed-level regimes
        read the tuple off the bucket dropdown; tercile regimes derive it from
        the live indicator's 1/3 & 2/3 quantiles over the lookback.
        ``(None, None)`` when no indicator is available."""
        spec = REGIME_SPECS.get(self.regime_type_chips.value)
        if isinstance(spec, LevelRegime):
            low, high = self.regime_bucket_chips.value
            return (low, high)
        indicator = self.regime_indicator()
        if indicator is None:
            return (None, None)
        return tercile_bounds(
            indicator.tail(_window_days(self.card_window_chips.value)),
            self.regime_bucket_chips.value,
        )

    def regime_selector_options(self) -> list[tuple[str, object]]:
        """The indicator-source options for the active regime, ``(label, ticker)``.

        Trend sources its list from the **live** benchmark registry rather than
        one frozen into `REGIME_SPECS` at import, so a benchmark added at
        runtime is offered here too. Rate-level carries a literal `selector`;
        a fixed-level regime has one ticker and so offers no source at all."""
        spec = REGIME_SPECS.get(self.regime_type_chips.value)
        if not isinstance(spec, TercileRegime):
            return []
        if spec.selector_source == "benchmarks":
            return self.state.benchmarks.options(labeled=True)
        return list(spec.selector)

    def sync_regime_controls(self) -> None:
        """Repopulate the bucket dropdown for the active regime and show / hide
        the indicator-source dropdown.

        Also re-run on a benchmark-registry change, so this keeps the current
        source **selected** whenever it survives into the new option list.
        Switching regime type still falls back to the first option, since the
        old value belongs to a different domain (a benchmark ticker is not a
        rate region)."""
        selector = self.regime_selector_options()
        if selector:
            previous = self.regime_selector_dd.value
            values = [value for _, value in selector]
            self.regime_selector_dd.options = selector
            self.regime_selector_dd.value = (
                previous if previous in values else selector[0][1]
            )
            self.regime_selector_dd.layout.display = ""
        else:
            self.regime_selector_dd.layout.display = "none"
        options = regime_bucket_options(self.regime_type_chips.value)
        # Preserve the active bucket across a registry change for the same reason.
        prev_bucket = self.regime_bucket_chips.value
        bucket_values = [value for _, value in options]
        self.regime_bucket_chips.set_options(
            options,
            value=prev_bucket if prev_bucket in bucket_values else options[0][1],
        )

    # --- lazy tab rendering ---------------------------------------------------

    def _render_tab(self, meta: pd.DataFrame, which: str) -> None:
        """Render one analytics tab and mark it fresh."""
        renderer = {
            "icicle": self.render_sunburst,
            "scatter": self.render_regime_scatter,
            "strip": lambda _meta: None,  # #336 builds it
        }[which]
        renderer(meta)
        self.fresh.add(which)

    def render_active(self, meta: pd.DataFrame) -> None:
        """Render whichever tab is shown — called on load and Refresh so only
        the visible chart is computed, not all three."""
        self._render_tab(meta, self.active_analytics)

    def invalidate(self, meta: pd.DataFrame) -> None:
        """Mark every tab stale (the data or shared lookback changed) and
        re-render only the visible one; the hidden two re-render lazily when
        next activated."""
        self.fresh.clear()
        self.render_active(meta)

    def activate(self, meta: pd.DataFrame, which: str) -> None:
        """Switch to chart ``which``: render it first if it isn't fresh (lazy
        first-view), show the sections it reads, and swap the figure.

        The Chart chips paint their own active state, so unlike the pill row
        they replace there is nothing to restyle here."""
        self.active_analytics = which
        if which not in self.fresh:
            self._render_tab(meta, which)
        self._sync_sections()
        self.chart_box.children = (self.analytics_tabs[which],)

    # --- wiring ---------------------------------------------------------------

    def wire(self, current_meta: Callable[[], pd.DataFrame]) -> None:
        """Wire every observer: the table's ranking Metric, and the card's own
        Chart / Metric / Window / Regime / Level controls. Each re-renders live
        from the cache, no BQL.

        Takes a **callable**, not a frame (#242). `build_app` re-points its
        `meta` to the recent-performance-pruned catalog after every load, so an
        observer that captured the frame it was wired with would redraw from the
        *pre-prune* catalog — putting the stale indices the prune removed back
        into the grid. Resolving it at fire time makes that impossible, and
        needs nothing remembered at the prune sites.
        """
        self._current_meta = current_meta

        # Only the Metric is wired here. The Window has a second job — which
        # performance columns are visible — so `DashboardApp._on_window_change`
        # owns it and does both, the way it owns the grouping chips (#324).
        self.z_metric_chips.observe(
            lambda _c: self.render_universe_grid(current_meta()), names="value"
        )

        self.chart_chips.observe(
            lambda c: self.activate(current_meta(), c["new"]), names="value"
        )

        def _on_regime_type(_change=None):
            self.sync_regime_controls()
            self._render_tab(current_meta(), "scatter")

        self.regime_type_chips.observe(_on_regime_type, names="value")
        self.regime_selector_dd.observe(
            lambda _c: self._render_tab(current_meta(), "scatter"), names="value"
        )
        self.regime_bucket_chips.observe(
            lambda _c: self._render_tab(current_meta(), "scatter"), names="value"
        )

        # Metric and Window re-render only the VISIBLE chart. They are not a
        # data change, so `invalidate` would be wrong: it would mark the hidden
        # two stale and buy nothing, since they redraw on activation anyway.
        for chips in (self.metric_chips, self.card_window_chips):
            chips.observe(
                lambda _c: self._render_tab(current_meta(), self.active_analytics),
                names="value",
            )

        self.level_chips.observe(self._on_level_chip, names="value")

        self.sync_regime_controls()

        # A benchmark added at runtime has to reach the Trend regime's source
        # dropdown too. That widget can't `register` with the registry: it is
        # shared with the Rate-level regime, whose options are regions, so the
        # registry would overwrite them whenever Rate-level was the active
        # regime. Re-syncing instead repopulates it only while Trend is active,
        # and preserves the current selection.
        self.state.benchmarks.on_change(self.sync_regime_controls)
