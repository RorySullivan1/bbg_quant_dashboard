"""Platform-tab chart factories + updaters (v0.7.0).

Standalone visuals for the Platform tab — distinct from the analysis panes
(`panes.py` / `charts.py`), which are the Multi-Strategy tab. Workstream C+D
adds the factor-beta scatter; the asset-class sunburst (Workstream E) joins
it here. Every figure is built once (factory) and mutated in place inside a
`fig.batch_update()` block (updater), computing live from the already-fetched
price cache — no BQL.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable
from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go

from ..config import REGIME_SPECS, TRADING_DAYS_PER_YEAR
from ..stats import (
    daily_returns,
    equity_risk_premium,
    factor_beta,
    platform_sunburst_frame,
    regime_mask,
    regime_risk_return,
    rolling_autocorr,
    rolling_metric_zscore,
    tercile_bounds,
    term_premium,
    trend_returns,
)
from ..style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR, LINE_PALETTE, Color
from .chrome import _style_tab_button
from .grids import _update_universe_grid
from .theme import _chart_layout, _short_ticker


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


# Sunburst hierarchy separator (asset class → theme), diverging colorscale, and
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
    ring's arc is then its gross-|z| share of its parent (asset class = Σ|z|
    share, theme = Σ|z| within the class). All-zero (or empty) input falls back
    to uniform arcs."""
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
    zero-reference planes (x=0/y=0/z=0, v0.8.6) that mark the origin in every
    dimension. No in-figure title — the "Factor exposures" section header stands
    alone (v0.7.1). The legend is on (unlike the pane charts, this chart has no
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
    rets = daily_returns(arp_prices)
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
    """Asset class → theme → ticker sunburst (inside out), arcs sized by each
    ring's gross-|z| share and colored by the (level-averaged) metric z-score.
    Built empty; `_update_sunburst` fills it. No in-figure title — the
    "Risk-adjusted strength map" section header stands alone (v0.7.3); the
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
    lookback: int,
    label: str,
) -> None:
    """Populate the sunburst from `platform_sunburst_frame`: a 3-level
    asset class → theme → ticker hierarchy. Each arc is sized by |z| (so with
    `branchvalues="total"` a ring's arc is its gross-|z| share of its parent) and
    colored by the metric z-score, averaged up each level (parent color = mean of
    its descendant tickers' z). `maxdepth=2` shows only the asset-class + theme
    rings up front; the ticker ring appears when the user clicks into an asset
    class or theme (client-side drill-down). `label` (e.g. "1W Sharpe") titles
    the colorbar + hover. No BQL — pure compute over the already-fetched cache."""
    frame = platform_sunburst_frame(
        prices, meta, metric=metric, window=window, lookback=lookback
    ).dropna(subset=["z"])
    if frame.empty:
        with fig.batch_update():
            fig.data = ()
        return

    frame = frame.copy()
    frame["asset_class"] = frame["asset_class"].fillna("Other").astype(str)
    frame["theme"] = frame["theme"].fillna("Other").astype(str)
    # Arc value = |z| (gross magnitude) + floor; parents sum to the gross-|z|
    # share at each ring. Color is the signed z (below), averaged up each level.
    frame["size"] = _sunburst_leaf_sizes(frame["z"])

    ids: list[str] = []
    labels: list[str] = []
    parents: list[str] = []
    values: list[float] = []
    colors: list[float] = []

    for ac, ac_grp in frame.groupby("asset_class"):
        ac_total = 0.0
        for theme, th_grp in ac_grp.groupby("theme"):
            tid = f"{ac}{_SUNBURST_SEP}{theme}"
            leaves = [
                (t, float(row["size"]), float(row["z"])) for t, row in th_grp.iterrows()
            ]
            th_total = sum(v for _, v, _ in leaves)
            ac_total += th_total
            # theme node, then its ticker leaves (parent value == Σ children,
            # so branchvalues="total" is exact).
            ids.append(tid)
            labels.append(str(theme))
            parents.append(str(ac))
            values.append(th_total)
            colors.append(float(th_grp["z"].mean()))
            for t, size, z in leaves:
                ids.append(t)
                labels.append(_short_ticker(t))
                parents.append(tid)
                values.append(size)
                colors.append(z)
        ids.append(str(ac))
        labels.append(str(ac))
        parents.append("")
        values.append(ac_total)
        colors.append(float(ac_grp["z"].mean()))

    sunburst = go.Sunburst(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        branchvalues="total",
        # Show only 2 rings from the current center (asset class + theme), so the
        # ticker ring stays hidden until the user clicks into an asset class or
        # theme to drill in (client-side zoom, no recompute).
        maxdepth=2,
        insidetextorientation="radial",
        marker=dict(
            colors=colors,
            colorscale=_SUNBURST_COLORSCALE,
            cmid=0,
            cmin=-2,
            cmax=2,
            line=dict(width=1, color=Color.CHART_BG.value),
            showscale=True,
            colorbar=dict(title=dict(text=f"z({label})")),
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
) -> None:
    """Populate the regime risk/return scatter: per-strategy vol/return/Sharpe
    over the lookback window restricted to the regime-bucket days (mean-based
    annualization via `regime_risk_return`), one trace per asset class. No BQL."""
    if arp_prices.empty:
        with fig.batch_update():
            fig.data = ()
        return
    rets = daily_returns(arp_prices.tail(lookback))
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


# --- Platform-analytics orchestration (v0.9.12-review #156) -------------------
# Extracted from the ``build_app`` monolith. ``build_app`` builds the analytics
# widgets, bundles their handles into a ``pa`` namespace, then calls
# ``wire_platform_analytics(state, meta, pa)`` (observers + tab pills) and the
# ``render_*`` functions on load / Refresh. Every render reads the already
# fetched cache on ``state`` — no BQL.


@contextmanager
def _guard_render(state: object, label: str):
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
    if spec.get("mode") == "level":
        return [(label, (low, high)) for label, low, high in spec["buckets"]]
    return [(label, key) for label, key in spec["bucket_labels"]]


def activate_platform_tab(pa: SimpleNamespace, which: str) -> None:
    """Swap the analytics card to tab ``which`` — restyle the pills, swap the
    left-column controls (``tab_controls_box``) and the chart (``chart_box``)."""
    for key, (pill, _controls, _fig) in pa.analytics_tabs.items():
        _style_tab_button(pill, active=(key == which))
    _pill, controls, fig = pa.analytics_tabs[which]
    pa.tab_controls_box.children = (controls,)
    pa.chart_box.children = (fig,)


def render_universe_grid(
    state: object, meta: pd.DataFrame, pa: SimpleNamespace
) -> None:
    """Render the all-catalog grid with the dynamic z-score column from the
    current Metric/Window/Lookback dropdowns. Reads the cached perf table
    (``state.universe_up``) and computes only the z-score column live from the
    already-fetched ``arp_universe_prices`` — no BQL, no full recompute."""
    if state.arp_universe_prices.empty:
        return
    with _guard_render(state, "all-catalog grid z-score render"):
        zcol = rolling_metric_zscore(
            state.arp_universe_prices,
            metric=pa.z_metric_dd.value,
            window=pa.z_window_dd.value,
            zscore_window=pa.z_lookback_dd.value,
        )
        zlabel = (
            f"{pa.z_metric_dd.label} {pa.z_window_dd.label}/{pa.z_lookback_dd.label}"
        )
        _update_universe_grid(
            state.universe_grid, meta, state.universe_up, zcol=zcol, zlabel=zlabel
        )


def render_factor_scatter(
    state: object, meta: pd.DataFrame, pa: SimpleNamespace
) -> None:
    """Render the Platform 3D factor-beta scatter at the selected lookback,
    live from the fetched cache (no BQL)."""
    if state.arp_universe_prices.empty or state.universe_prices.empty:
        return
    with _guard_render(state, "factor-beta scatter render"):
        _update_factor_scatter(
            pa.factor_scatter_fig,
            state.arp_universe_prices,
            state.universe_prices,
            meta,
            years=pa.lookback_selector.value / TRADING_DAYS_PER_YEAR,
        )


def render_sunburst(state: object, meta: pd.DataFrame, pa: SimpleNamespace) -> None:
    """Render the asset class → theme → ticker sunburst from the Metric/Window
    Z-score controls + the shared lookback, live from the ARP-only cache."""
    if state.arp_universe_prices.empty:
        return
    with _guard_render(state, "sunburst render"):
        _update_sunburst(
            pa.sunburst_fig,
            state.arp_universe_prices,
            meta,
            metric=pa.sb_metric_dd.value,
            window=pa.sb_window_dd.value,
            lookback=pa.lookback_selector.value,
            label=f"{pa.sb_window_dd.label} {pa.sb_metric_dd.label}",
        )


def _regime_indicator(state: object, pa: SimpleNamespace) -> pd.Series | None:
    """The regime indicator series from the cache, per the active regime's mode,
    or None when its ticker(s) are absent (→ unconditioned all-days view)."""
    spec = REGIME_SPECS.get(pa.regime_type_dd.value, {})
    mode = spec.get("mode")
    prices = state.universe_prices
    if mode == "autocorr_tercile":
        ticker = pa.regime_selector_dd.value
        if not ticker or ticker not in prices.columns:
            return None
        rets = daily_returns(prices[[ticker]])[ticker]
        return rolling_autocorr(rets, window=spec.get("autocorr_window", 21))
    ticker = (
        pa.regime_selector_dd.value if mode == "level_tercile" else spec.get("ticker")
    )
    if not ticker or ticker not in prices.columns:
        return None
    return prices[ticker]


def _resolve_regime_bucket(
    state: object, pa: SimpleNamespace
) -> tuple[float | None, float | None]:
    """The ``(low, high)`` bounds for the active bucket. Fixed-level regimes read
    the tuple off the bucket dropdown; tercile regimes derive it from the live
    indicator's 1/3 & 2/3 quantiles over the lookback window. ``(None, None)``
    when no indicator is available (→ unconditioned all-days view)."""
    spec = REGIME_SPECS.get(pa.regime_type_dd.value, {})
    if spec.get("mode") == "level":
        low, high = pa.regime_bucket_dd.value
        return (low, high)
    indicator = _regime_indicator(state, pa)
    if indicator is None:
        return (None, None)
    return tercile_bounds(
        indicator.tail(pa.lookback_selector.value), pa.regime_bucket_dd.value
    )


def render_regime_scatter(
    state: object, meta: pd.DataFrame, pa: SimpleNamespace
) -> None:
    """Render the regime risk/return scatter at the current regime / source /
    bucket + lookback, live from the cache (no BQL)."""
    if state.arp_universe_prices.empty:
        return
    with _guard_render(state, "regime scatter render"):
        low, high = _resolve_regime_bucket(state, pa)
        _update_regime_scatter(
            pa.regime_scatter_fig,
            state.arp_universe_prices,
            _regime_indicator(state, pa),
            meta,
            low=low,
            high=high,
            lookback=pa.lookback_selector.value,
        )


def _sync_regime_controls(pa: SimpleNamespace) -> None:
    """Repopulate the bucket dropdown for the active regime's mode and show /
    hide the indicator-source dropdown (only regimes carrying a ``selector``)."""
    spec = REGIME_SPECS.get(pa.regime_type_dd.value, {})
    selector = spec.get("selector", [])
    if selector:
        pa.regime_selector_dd.options = selector
        pa.regime_selector_dd.value = selector[0][1]
        pa.regime_selector_dd.layout.display = ""
    else:
        pa.regime_selector_dd.layout.display = "none"
    options = regime_bucket_options(pa.regime_type_dd.value)
    pa.regime_bucket_dd.options = options
    pa.regime_bucket_dd.value = options[0][1]


def wire_platform_analytics(
    state: object, meta: pd.DataFrame, pa: SimpleNamespace
) -> None:
    """Wire every Platform-analytics observer: the z-score-column controls, the
    three tab pills, the regime dropdowns, the shared lookback, and the
    sunburst's own controls. Each re-renders live from the cache, no BQL."""
    for _dd in (pa.z_metric_dd, pa.z_window_dd, pa.z_lookback_dd):
        _dd.observe(lambda _c: render_universe_grid(state, meta, pa), names="value")

    pa.sunburst_pill.on_click(lambda _b: activate_platform_tab(pa, "sunburst"))
    pa.regime_pill.on_click(lambda _b: activate_platform_tab(pa, "regime"))
    pa.factor_pill.on_click(lambda _b: activate_platform_tab(pa, "factor"))

    def _on_regime_type(_change=None):
        _sync_regime_controls(pa)
        render_regime_scatter(state, meta, pa)

    pa.regime_type_dd.observe(_on_regime_type, names="value")
    pa.regime_selector_dd.observe(
        lambda _c: render_regime_scatter(state, meta, pa), names="value"
    )
    pa.regime_bucket_dd.observe(
        lambda _c: render_regime_scatter(state, meta, pa), names="value"
    )

    # The shared lookback drives all three analytics tabs.
    for _render in (render_factor_scatter, render_regime_scatter, render_sunburst):
        pa.lookback_selector.observe(
            lambda _c, r=_render: r(state, meta, pa), names="value"
        )

    # The sunburst's own Metric/Window controls re-render only the sunburst.
    for _dd in (pa.sb_metric_dd, pa.sb_window_dd):
        _dd.observe(lambda _c: render_sunburst(state, meta, pa), names="value")

    _sync_regime_controls(pa)
