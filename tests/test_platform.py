"""Unit tests for the Platform-tab factor-beta scatter (v0.7.0 Workstream C+D).

`_update_factor_scatter` is exercised against a deterministic price frame
holding the factor proxy tickers plus a couple of strategies; the figure is a
real `go.FigureWidget`, so we assert on its trace data directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from src.config import HALF_YEAR_WINDOW, WEEK_WINDOW
from src.data import load_metadata
from src.layout.platform import (
    _asset_class_colors,
    _factor_beta_scatter,
    _regime_heatmap,
    _regime_scatter,
    _treemap,
    _update_factor_scatter,
    _update_regime_heatmap,
    _update_regime_scatter,
    _update_treemap,
)
from src.layout.theme import _v_ref
from src.style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR


def _universe(n: int = 400) -> pd.DataFrame:
    """Seeded prices: the factor proxy tickers (equity / long / short / trend)
    + two strategies."""
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(3)
    specs = {
        "SPX Index": (0.0004, 0.011),
        "LUTLTRUU Index": (0.0002, 0.005),
        "LD12TRUU Index": (0.00005, 0.0005),
        "BSLXAT Index": (0.0001, 0.006),
        "AAA Index": (0.0003, 0.012),
        "BBB Index": (0.0002, 0.008),
    }
    return pd.DataFrame(
        {
            t: 100.0 * np.cumprod(1.0 + rng.normal(mu, sig, n))
            for t, (mu, sig) in specs.items()
        },
        index=idx,
    )


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index"],
            "asset_class": ["Equity", "Fixed Income"],
        }
    )


def test_v_ref_is_vertical_paper_height_line():
    shape = _v_ref(0.0)
    assert shape["type"] == "line"
    assert shape["xref"] == "x" and shape["x0"] == 0.0 and shape["x1"] == 0.0
    assert shape["yref"] == "paper" and shape["y0"] == 0 and shape["y1"] == 1


def test_update_factor_scatter_one_trace_per_asset_class():
    fig = _factor_beta_scatter()
    universe = _universe()
    arp = universe[["AAA Index", "BBB Index"]]
    _update_factor_scatter(fig, arp, universe, _meta(), years=1)

    # No in-figure title (v0.7.1) — the section header stands alone.
    assert not fig.layout.title.text
    # AAA → Equity, BBB → Fixed Income → one marker trace each (the figure also
    # holds the three Mesh3d zero planes, filtered out here).
    by_name = {tr.name: tr for tr in fig.data if isinstance(tr, go.Scatter3d)}
    assert set(by_name) == {"Equity", "Fixed Income"}
    assert by_name["Equity"].marker.color == ASSET_CLASS_COLORS["Equity"]
    assert by_name["Fixed Income"].marker.color == ASSET_CLASS_COLORS["Fixed Income"]
    # 3D marker traces — one strategy each, finite betas on all three axes.
    for tr in by_name.values():
        assert len(tr.x) == 1 and len(tr.y) == 1 and len(tr.z) == 1
        assert np.isfinite(tr.x[0]) and np.isfinite(tr.y[0]) and np.isfinite(tr.z[0])


def test_factor_scatter_has_three_zero_planes():
    fig = _factor_beta_scatter()
    universe = _universe()
    arp = universe[["AAA Index", "BBB Index"]]
    _update_factor_scatter(fig, arp, universe, _meta(), years=1)

    planes = {tr.name: tr for tr in fig.data if isinstance(tr, go.Mesh3d)}
    assert set(planes) == {"x=0", "y=0", "z=0"}
    # Each plane is a faint, legend-less, non-hovering reference surface.
    for tr in planes.values():
        assert tr.showlegend is False
        assert 0 < tr.opacity < 1

    # Each plane is constant 0 on its own axis...
    assert all(v == 0 for v in planes["x=0"].x)
    assert all(v == 0 for v in planes["y=0"].y)
    assert all(v == 0 for v in planes["z=0"].z)

    # ...and spans (covers) the marker cloud on its other two axes.
    markers = [tr for tr in fig.data if isinstance(tr, go.Scatter3d)]
    xs = [v for tr in markers for v in tr.x]
    ys = [v for tr in markers for v in tr.y]
    zs = [v for tr in markers for v in tr.z]
    assert min(planes["x=0"].y) <= min(ys) and max(planes["x=0"].y) >= max(ys)
    assert min(planes["x=0"].z) <= min(zs) and max(planes["x=0"].z) >= max(zs)
    assert min(planes["y=0"].x) <= min(xs) and max(planes["y=0"].x) >= max(xs)
    assert min(planes["z=0"].x) <= min(xs) and max(planes["z=0"].x) >= max(xs)


def test_catalog_asset_classes_get_distinct_non_fallback_colors():
    """Every distinct AssetClass in the catalog maps to a distinct, non-fallback
    color — guards against the all-grey legend (driven off the loaded metadata,
    so future catalog additions are covered too)."""
    classes = sorted(load_metadata()["asset_class"].dropna().unique())
    colors = _asset_class_colors(classes)
    assert set(colors) == set(classes)
    assert ASSET_CLASS_FALLBACK_COLOR not in colors.values()
    assert len(set(colors.values())) == len(classes)  # all distinct


def test_asset_class_colors_unmapped_class_avoids_fallback():
    """An unmapped class still gets a distinct palette color, not the grey
    fallback, as long as the palette isn't exhausted."""
    colors = _asset_class_colors(["Equity", "Crypto"])
    assert colors["Equity"] == ASSET_CLASS_COLORS["Equity"]
    assert colors["Crypto"] != ASSET_CLASS_FALLBACK_COLOR
    assert colors["Crypto"] != colors["Equity"]


def test_update_factor_scatter_empty_clears_traces():
    fig = _factor_beta_scatter()
    _update_factor_scatter(fig, pd.DataFrame(), pd.DataFrame(), _meta(), years=1)
    assert fig.data == ()


def _treemap_meta() -> pd.DataFrame:
    # Two themes under one asset class → a 3-level Equity → theme → ticker tree.
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index"],
            "asset_class": ["Equity", "Equity"],
            "theme": ["Growth", "Value"],
        }
    )


_TREEMAP_KW = dict(
    size_metric="sharpe",
    size_window=HALF_YEAR_WINDOW,
    size_lookback=252,
    color_metric="sharpe",
    color_window=WEEK_WINDOW,
    color_lookback=252,
    size_label="6M Sharpe",
    color_label="1W Sharpe",
)


def test_update_treemap_builds_asset_theme_ticker_hierarchy():
    fig = _treemap()
    universe = _universe()
    arp = universe[["AAA Index", "BBB Index"]]
    _update_treemap(fig, arp, _treemap_meta(), **_TREEMAP_KW)

    # No in-figure title (v0.7.3) — the section header stands alone.
    assert not fig.layout.title.text
    assert len(fig.data) == 1
    tm = fig.data[0]
    nodes = dict(zip(tm.ids, tm.parents, strict=True))
    # asset-class node is a root; theme nodes hang off it; leaves off the themes.
    assert nodes["Equity"] == ""
    assert nodes["Equity / Growth"] == "Equity"
    assert nodes["Equity / Value"] == "Equity"
    assert nodes["AAA Index"] == "Equity / Growth"
    assert nodes["BBB Index"] == "Equity / Value"
    # Sizes are non-negative; one color + customdata per node.
    assert all(v >= 0 for v in tm.values)
    assert len(tm.marker.colors) == len(tm.ids)
    assert len(tm.customdata) == len(tm.ids)
    # Colorbar title reflects the selected color label.
    assert tm.marker.colorbar.title.text == "z(1W Sharpe)"


def test_update_treemap_labels_drive_colorbar_title():
    fig = _treemap()
    arp = _universe()[["AAA Index", "BBB Index"]]
    kw = {**_TREEMAP_KW, "color_metric": "sortino", "color_label": "3M Sortino"}
    _update_treemap(fig, arp, _treemap_meta(), **kw)
    assert fig.data[0].marker.colorbar.title.text == "z(3M Sortino)"


def test_update_treemap_empty_clears_traces():
    fig = _treemap()
    _update_treemap(fig, pd.DataFrame(), _treemap_meta(), **_TREEMAP_KW)
    assert fig.data == ()


# --- v0.8.5 Regime Analysis: regime scatter + heatmap ----------------------


def _regime_universe(n: int = 300):
    """Three strategies + a VIX-like indicator series (levels in ~[15, 40))."""
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(7)
    arp = pd.DataFrame(
        {
            "AAA Index": 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.012, n)),
            "BBB Index": 100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.008, n)),
            "CCC Index": 100.0 * np.cumprod(1.0 + rng.normal(0.0001, 0.010, n)),
        },
        index=idx,
    )
    vix = pd.Series(
        15.0 + 8.0 * np.abs(rng.normal(0, 1, n)), index=idx, name="VIX Index"
    )
    return arp, vix


def _regime_meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "asset_class": ["Equity", "Equity", "Fixed Income"],
            "theme": ["Growth", "Growth", "Carry"],
        }
    )


def test_update_regime_scatter_one_trace_per_asset_class():
    fig = _regime_scatter()
    arp, vix = _regime_universe()
    _update_regime_scatter(
        fig, arp, vix, _regime_meta(), low=15.0, high=25.0, lookback=200
    )
    assert not fig.layout.title.text
    by_name = {tr.name: tr for tr in fig.data}
    assert set(by_name) == {"Equity", "Fixed Income"}
    for tr in fig.data:
        assert isinstance(tr, go.Scatter)
        assert len(tr.x) == len(tr.y) >= 1
        assert all(np.isfinite(v) for v in tr.x)


def test_update_regime_scatter_unconditioned_when_no_indicator():
    # A scaffolded regime passes no indicator / no bucket → all-days view.
    fig = _regime_scatter()
    arp, _ = _regime_universe()
    _update_regime_scatter(
        fig, arp, None, _regime_meta(), low=None, high=None, lookback=200
    )
    assert fig.data  # renders over the full window


def test_update_regime_scatter_empty_clears():
    fig = _regime_scatter()
    _update_regime_scatter(
        fig, pd.DataFrame(), None, _regime_meta(), low=15.0, high=25.0, lookback=200
    )
    assert fig.data == ()


def test_update_regime_heatmap_theme_scoped():
    fig = _regime_heatmap()
    arp, vix = _regime_universe()
    _update_regime_heatmap(
        fig, arp, vix, _regime_meta(), low=15.0, high=25.0, theme="Growth", lookback=200
    )
    assert len(fig.data) == 1
    hm = fig.data[0]
    assert isinstance(hm, go.Heatmap)
    # Growth = AAA + BBB → a 2×2 per-ticker matrix.
    assert len(hm.x) == 2 and len(hm.y) == 2


def test_update_regime_heatmap_single_ticker_theme_clears():
    fig = _regime_heatmap()
    arp, vix = _regime_universe()
    _update_regime_heatmap(
        fig, arp, vix, _regime_meta(), low=15.0, high=25.0, theme="Carry", lookback=200
    )
    assert fig.data == ()  # Carry has only CCC → < 2 columns
