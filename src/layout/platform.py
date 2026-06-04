"""Platform-tab chart factories + updaters (v0.7.0).

Standalone visuals for the Platform tab — distinct from the analysis panes
(`panes.py` / `charts.py`), which are the Multi-Strategy tab. Workstream C+D
adds the factor-beta scatter; the asset-class treemap (Workstream E) will join
it here. Every figure is built once (factory) and mutated in place inside a
`fig.batch_update()` block (updater), computing live from the already-fetched
price cache — no BQL.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ..stats import daily_returns, equity_risk_premium, factor_beta, term_premium
from ..style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR
from .theme import _chart_layout, _h_ref, _short_ticker, _v_ref

_FACTOR_HOVER = (
    "%{{text}}<br>{ac}<br>Equity β %{{x:.2f}}<br>Term β %{{y:.2f}}<extra></extra>"
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
                    color=ASSET_CLASS_COLORS.get(ac, ASSET_CLASS_FALLBACK_COLOR),
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
