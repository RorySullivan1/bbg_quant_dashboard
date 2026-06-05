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
    term_premium,
)
from ..style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR, LINE_PALETTE, Color
from .theme import _chart_layout, _h_ref, _short_ticker, _v_ref


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
    "%{{text}}<br>{ac}<br>Equity β %{{x:.2f}}<br>Term β %{{y:.2f}}<extra></extra>"
)

# Treemap hierarchy separator (asset class → theme), diverging colorscale, and
# the shared per-node hover. The colorscale matches the all-catalog grid's
# red<0 → neutral → green>0 sentiment and is token-driven (no inline hex).
_TREEMAP_SEP = " / "
_TREEMAP_COLORSCALE = [
    [0.0, Color.RED_600.value],
    [0.5, Color.SLATE_500.value],
    [1.0, Color.GREEN_600.value],
]
_TREEMAP_HOVER = (
    "%{label}<br>size z(6M Sharpe) %{customdata:.2f}"
    "<br>color z(1W Sharpe) %{color:.2f}<extra></extra>"
)


def _factor_beta_scatter() -> go.FigureWidget:
    """Factor-beta scatter: x = β to the equity risk premium, y = β to the term
    premium, one marker per strategy (colored by asset class). Built empty;
    `_update_factor_scatter` fills it. Dashed zero crosshair via `layout.shapes`;
    the legend is on (unlike the pane charts, this chart has no grid legend to
    key its asset-class colors)."""
    return go.FigureWidget(
        layout=_chart_layout(
            title="Equity vs term-premium β",
            hovermode="closest",
            showlegend=True,
            legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
            xaxis=dict(title="Equity risk-premium β", zeroline=False),
            yaxis=dict(title="Term-premium β", zeroline=False),
            shapes=[_h_ref(0.0), _v_ref(0.0)],
        )
    )


def _update_factor_scatter(
    fig: go.FigureWidget,
    arp_prices: pd.DataFrame,
    universe_prices: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    years: float,
    title: str,
) -> None:
    """Populate the factor-beta scatter from the cached prices: per-strategy
    betas to the equity-risk-premium and term-premium factor series, one trace
    per asset class (so the colors carry a legend). No BQL — pure compute over
    the already-fetched cache."""
    if arp_prices.empty or universe_prices.empty:
        with fig.batch_update():
            fig.layout.title.text = title
            fig.data = ()
        return

    erp = equity_risk_premium(universe_prices)
    tp = term_premium(universe_prices)
    rets = daily_returns(arp_prices)
    frame = pd.DataFrame(
        {
            "x": factor_beta(rets, erp, years),
            "y": factor_beta(rets, tp, years),
        }
    ).dropna()

    if frame.empty:
        with fig.batch_update():
            fig.layout.title.text = title
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
            go.Scatter(
                mode="markers",
                name=str(ac),
                x=grp["x"].to_numpy(),
                y=grp["y"].to_numpy(),
                marker=dict(
                    size=12,
                    color=color_for[str(ac)],
                    line=dict(width=0),
                ),
                text=[_short_ticker(t) for t in grp.index],
                hovertemplate=_FACTOR_HOVER.format(ac=str(ac)),
            )
        )

    with fig.batch_update():
        fig.layout.title.text = title
        fig.data = ()
        fig.add_traces(traces)


def _treemap() -> go.FigureWidget:
    """Asset-class → theme → ticker treemap, sized by z(6M Sharpe) and colored
    by z(1W Sharpe). Built empty; `_update_treemap` fills it. No in-figure title
    — the "Risk-adjusted strength map" section header stands alone (v0.7.3); the
    diverging colorbar is the color legend."""
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
    lookback: int,
) -> None:
    """Populate the treemap from `platform_treemap_frame`: a 3-level
    asset class → theme → ticker hierarchy. Tiles are sized by a non-negative
    shift of z(6M Sharpe) and colored by raw z(1W Sharpe); parent nodes
    aggregate (size = sum of children, color = mean of leaf z). No BQL — pure
    compute over the already-fetched cache."""
    frame = platform_treemap_frame(prices, meta, lookback=lookback).dropna(
        subset=["size_z", "color_z"]
    )
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
            colorbar=dict(title=dict(text="z(1W Sharpe)")),
        ),
        hovertemplate=_TREEMAP_HOVER,
    )
    with fig.batch_update():
        fig.data = ()
        fig.add_traces([treemap])
