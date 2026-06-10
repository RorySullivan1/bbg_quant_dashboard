"""Platform-tab chart factories + updaters (v0.7.0).

Standalone visuals for the Platform tab — distinct from the analysis panes
(`panes.py` / `charts.py`), which are the Multi-Strategy tab. Workstream C+D
adds the factor-beta scatter; the asset-class treemap (Workstream E) will join
it here. Every figure is built once (factory) and mutated in place inside a
`fig.batch_update()` block (updater), computing live from the already-fetched
price cache — no BQL.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import plotly.graph_objects as go

from ..stats import (
    daily_returns,
    equity_risk_premium,
    factor_beta,
    platform_treemap_frame,
    regime_correlation,
    regime_mask,
    regime_risk_return,
    term_premium,
    trend_returns,
)
from ..style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR, LINE_PALETTE, Color
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


# Treemap hierarchy separator (asset class → theme), diverging colorscale, and
# the per-node hover. The colorscale matches the all-catalog grid's
# red<0 → neutral → green>0 sentiment and is token-driven (no inline hex). The
# hover is a `.format()` template — the size/color labels are user-selected at
# render time (the literal plotly `%{...}` placeholders are doubled to survive
# `.format()`).
_TREEMAP_SEP = " / "
_TREEMAP_COLORSCALE = [
    [0.0, Color.RED_600.value],
    [0.5, Color.SLATE_500.value],
    [1.0, Color.GREEN_600.value],
]
_TREEMAP_HOVER = (
    "%{{label}}<br>size z({size_label}) %{{customdata:.2f}}"
    "<br>color z({color_label}) %{{color:.2f}}<extra></extra>"
)


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


def _treemap() -> go.FigureWidget:
    """Asset-class → theme → ticker treemap, sized + colored by user-selected
    z-scores (defaults z(6M Sharpe) size / z(1W Sharpe) color). Built empty;
    `_update_treemap` fills it. No in-figure title — the "Risk-adjusted strength
    map" section header stands alone (v0.7.3); the diverging colorbar is the
    color legend."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="",
            margin=dict(t=44, b=10, l=10, r=10),
        )
    )


def _update_treemap(
    fig: go.FigureWidget,
    prices: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    size_metric: str,
    size_window: int,
    size_lookback: int,
    color_metric: str,
    color_window: int,
    color_lookback: int,
    size_label: str,
    color_label: str,
) -> None:
    """Populate the treemap from `platform_treemap_frame`: a 3-level
    asset class → theme → ticker hierarchy. Tiles are sized by a non-negative
    shift of the size z-score and colored by the raw color z-score (both
    user-selected via metric/window/lookback); parent nodes aggregate
    (size = sum of children, color = mean of leaf z). The `*_label` strings
    (e.g. "6M Sharpe") title the colorbar + hover. No BQL — pure compute over
    the already-fetched cache."""
    frame = platform_treemap_frame(
        prices,
        meta,
        size_metric=size_metric,
        size_window=size_window,
        size_lookback=size_lookback,
        color_metric=color_metric,
        color_window=color_window,
        color_lookback=color_lookback,
    ).dropna(subset=["size_z", "color_z"])
    if frame.empty:
        with fig.batch_update():
            fig.data = ()
        return

    frame = frame.copy()
    frame["asset_class"] = frame["asset_class"].fillna("Other").astype(str)
    frame["theme"] = frame["theme"].fillna("Other").astype(str)

    # Treemap values must be non-negative; z-scores can be negative. Shift to
    # [0.1·range, 1.1·range] so the smallest tile stays visible (not zero-area)
    # while preserving the relative ordering. Color uses the raw z (below).
    s = frame["size_z"]
    rng = float(s.max() - s.min())
    frame["size"] = 1.0 if rng <= 0 else (s - s.min()) + 0.10 * rng

    ids: list[str] = []
    labels: list[str] = []
    parents: list[str] = []
    values: list[float] = []
    colors: list[float] = []
    customdata: list[float] = []

    for ac, ac_grp in frame.groupby("asset_class"):
        ac_total = 0.0
        for theme, th_grp in ac_grp.groupby("theme"):
            tid = f"{ac}{_TREEMAP_SEP}{theme}"
            leaves = [
                (t, float(row["size"]), float(row["color_z"]), float(row["size_z"]))
                for t, row in th_grp.iterrows()
            ]
            th_total = sum(v for _, v, _, _ in leaves)
            ac_total += th_total
            # theme node, then its ticker leaves (parent value == Σ children,
            # so branchvalues="total" is exact).
            ids.append(tid)
            labels.append(str(theme))
            parents.append(str(ac))
            values.append(th_total)
            colors.append(float(th_grp["color_z"].mean()))
            customdata.append(float(th_grp["size_z"].mean()))
            for t, size, color_z, size_z in leaves:
                ids.append(t)
                labels.append(_short_ticker(t))
                parents.append(tid)
                values.append(size)
                colors.append(color_z)
                customdata.append(size_z)
        ids.append(str(ac))
        labels.append(str(ac))
        parents.append("")
        values.append(ac_total)
        colors.append(float(ac_grp["color_z"].mean()))
        customdata.append(float(ac_grp["size_z"].mean()))

    treemap = go.Treemap(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        customdata=customdata,
        branchvalues="total",
        marker=dict(
            colors=colors,
            colorscale=_TREEMAP_COLORSCALE,
            cmid=0,
            cmin=-2,
            cmax=2,
            line=dict(width=1, color=Color.CHART_BG.value),
            showscale=True,
            colorbar=dict(title=dict(text=f"z({color_label})")),
        ),
        hovertemplate=_TREEMAP_HOVER.format(
            size_label=size_label, color_label=color_label
        ),
    )
    with fig.batch_update():
        fig.data = ()
        fig.add_traces([treemap])


# --- v0.8.5 Regime Analysis: regime-conditioned scatter + heatmap ----------

_REGIME_RR_HOVER = (
    "%{{text}}<br>{ac}<br>Vol %{{x:.1%}}<br>Return %{{y:.1%}}"
    "<br>Sharpe %{{customdata:.2f}}<extra></extra>"
)
# Correlation heatmap diverging scale: reuse the treemap's red<0 → neutral →
# green>0 sentiment, mapped over ρ ∈ [-1, 1] (zmid=0).
_REGIME_CORR_COLORSCALE = _TREEMAP_COLORSCALE


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
    title — the section header + sub-tab pills stand alone."""
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


def _regime_heatmap() -> go.FigureWidget:
    """Regime-conditioned correlation heatmap — per-ticker correlation within a
    selected theme over only the regime bucket's days. Built empty;
    `_update_regime_heatmap` fills it. No in-figure title."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="",
            xaxis=dict(showgrid=False, side="bottom"),
            yaxis=dict(showgrid=False, autorange="reversed"),
        )
    )


def _update_regime_heatmap(
    fig: go.FigureWidget,
    arp_prices: pd.DataFrame,
    indicator: pd.Series | None,
    meta: pd.DataFrame,
    *,
    low: float | None,
    high: float | None,
    theme: str | None,
    lookback: int,
) -> None:
    """Populate the regime correlation heatmap: `regime_correlation` over the
    lookback window's regime-bucket days, scoped to the selected theme's tickers
    (so the per-ticker matrix stays small). No BQL."""
    if arp_prices.empty:
        with fig.batch_update():
            fig.data = ()
        return
    rets = daily_returns(arp_prices.tail(lookback))
    mask = _regime_window_mask(indicator, rets.index, low, high)
    theme_tickers = None
    if theme is not None and "theme" in meta:
        theme_tickers = meta.loc[meta["theme"] == theme, "ticker"].tolist()
    cm = regime_correlation(rets, mask, columns=theme_tickers)
    if cm.empty:
        with fig.batch_update():
            fig.data = ()
        return
    labels = [_short_ticker(t) for t in cm.columns]
    heat = go.Heatmap(
        z=cm.to_numpy(),
        x=labels,
        y=labels,
        zmin=-1.0,
        zmax=1.0,
        zmid=0.0,
        colorscale=_REGIME_CORR_COLORSCALE,
        colorbar=dict(title=dict(text="ρ")),
        hovertemplate="%{y} · %{x}<br>ρ %{z:.2f}<extra></extra>",
    )
    with fig.batch_update():
        fig.data = ()
        fig.add_traces([heat])
