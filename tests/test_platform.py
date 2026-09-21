"""Unit tests for the Platform-tab factor-beta scatter (v0.7.0 Workstream C+D).

`_update_factor_scatter` is exercised against a deterministic price frame
holding the factor proxy tickers plus a couple of strategies; the figure is a
real `go.FigureWidget`, so we assert on its trace data directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from src.config import (
    REGIME_SPECS,
    REGIME_TICKERS,
    WEEK_WINDOW,
    LevelRegime,
    TercileRegime,
)
from src.data import load_metadata
from src.layout.platform import (
    _SUNBURST_SIZE_FLOOR,
    PlatformAnalytics,
    _asset_class_colors,
    _factor_beta_scatter,
    _regime_scatter,
    _sunburst,
    _sunburst_leaf_sizes,
    _update_factor_scatter,
    _update_regime_scatter,
    _update_sunburst,
    regime_bucket_options,
)
from src.layout.rails import ChipGroup
from src.layout.theme import _v_ref
from src.stats import daily_returns, tercile_bounds
from src.style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR


def _universe(n: int = 400) -> pd.DataFrame:
    """Seeded prices: the factor proxy tickers (equity / long / short / trend)
    + two strategies."""
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(3)
    specs = {
        "SPXFP Index": (0.0004, 0.011),  # equity factor leg (EQUITY_FACTOR_TICKER)
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


def _scatter_xyz(fig) -> dict:
    """{trace name: (x, y, [z])} for the marker traces, for equality checks."""
    out = {}
    for tr in fig.data:
        if isinstance(tr, (go.Scatter, go.Scatter3d)):
            coords = [tuple(tr.x), tuple(tr.y)]
            if isinstance(tr, go.Scatter3d):
                coords.append(tuple(tr.z))
            out[tr.name] = coords
    return out


def test_factor_scatter_returns_arg_matches_recompute():
    # v0.9.13 #166: threading the shared universe_rets must produce a byte-
    # identical scatter to letting the updater re-derive daily_returns.
    universe = _universe()
    arp = universe[["AAA Index", "BBB Index"]]
    fig_a = _factor_beta_scatter()
    _update_factor_scatter(fig_a, arp, universe, _meta(), years=1)
    fig_b = _factor_beta_scatter()
    _update_factor_scatter(
        fig_b, arp, universe, _meta(), years=1, returns=daily_returns(arp)
    )
    assert _scatter_xyz(fig_a) == _scatter_xyz(fig_b)


def test_regime_scatter_returns_arg_matches_recompute():
    # v0.9.13 #166: daily_returns(arp).tail(lookback - 1) is exactly
    # daily_returns(arp.tail(lookback)), so the threaded path matches.
    arp, vix = _regime_universe()
    fig_a = _regime_scatter()
    _update_regime_scatter(
        fig_a, arp, vix, _regime_meta(), low=15.0, high=25.0, lookback=200
    )
    fig_b = _regime_scatter()
    _update_regime_scatter(
        fig_b,
        arp,
        vix,
        _regime_meta(),
        low=15.0,
        high=25.0,
        lookback=200,
        returns=daily_returns(arp),
    )
    assert _scatter_xyz(fig_a) == _scatter_xyz(fig_b)


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
    # Two categories under one asset class → a 3-ring Equity → category → ticker
    # tree under the default levels. The tier columns let the same fixture drive
    # the reconfigured-hierarchy tests (#213) without a second one.
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index"],
            "asset_class": ["Equity", "Equity"],
            "solution": ["ARP", "ARP"],
            "category": ["Growth", "Value"],
            "family": ["Momentum", "Carry"],
        }
    )


_SUNBURST_KW = dict(metric="sharpe", window=WEEK_WINDOW, label="1W Sharpe")


def test_sunburst_leaf_sizes_magnitude_drives_arc():
    # Arc = |z|: equal-magnitude +z/-z get equal arcs; near-zero lands on the
    # floor; bigger |z| -> bigger arc. Sign is for color, not size.
    z = pd.Series({"up": 2.0, "down": -2.0, "flat": 0.0})
    sizes = _sunburst_leaf_sizes(z)
    floor = _SUNBURST_SIZE_FLOOR * 2.0  # max |z| = 2.0
    assert sizes["up"] == sizes["down"] == 2.0 + floor
    assert sizes["flat"] == floor
    assert sizes["up"] > 10 * sizes["flat"]
    assert (sizes >= 0).all()


def test_sunburst_leaf_sizes_all_zero_uniform():
    # No deviation anywhere -> uniform fallback (avoids divide-by-zero floor).
    sizes = _sunburst_leaf_sizes(pd.Series({"a": 0.0, "b": 0.0, "c": 0.0}))
    assert (sizes == 1.0).all()


def test_update_sunburst_builds_the_configured_hierarchy():
    fig = _sunburst()
    universe = _universe()
    arp = universe[["AAA Index", "BBB Index"]]
    _update_sunburst(fig, arp, _treemap_meta(), **_SUNBURST_KW)

    # No in-figure title (v0.7.3) — the section header stands alone.
    assert not fig.layout.title.text
    assert len(fig.data) == 1
    sb = fig.data[0]
    assert isinstance(sb, go.Sunburst)
    assert sb.branchvalues == "total"
    # maxdepth == the number of configured levels, so the ticker ring stays
    # hidden until the user drills into a grouping node. Three since #332,
    # which took `ANALYTICS_LEVELS` down to the family tier.
    assert sb.maxdepth == 3
    nodes = dict(zip(sb.ids, sb.parents, strict=True))
    # asset class is a root; category hangs off it, family off the category,
    # and the ticker leaves off the families.
    assert nodes["Equity"] == ""
    assert nodes["Equity / Growth"] == "Equity"
    assert nodes["Equity / Value"] == "Equity"
    assert nodes["Equity / Growth / Momentum"] == "Equity / Growth"
    assert nodes["AAA Index"] == "Equity / Growth / Momentum"
    assert nodes["BBB Index"] == "Equity / Value / Carry"
    # Arcs are non-negative; one color per node.
    assert all(v >= 0 for v in sb.values)
    assert len(sb.marker.colors) == len(sb.ids)
    # branchvalues="total": the asset-class arc == the sum of its ticker leaves.
    val = dict(zip(sb.ids, sb.values, strict=True))
    assert val["Equity"] == pytest.approx(val["AAA Index"] + val["BBB Index"])
    # Colorbar title reflects the selected metric label.
    # The colorbar names the metric plainly: the cells carry the RAW metric
    # since #332, not a z-score of it (#331 decision 2).
    assert sb.marker.colorbar.title.text == "1W Sharpe"


def test_update_sunburst_follows_a_three_level_config(monkeypatch):
    # #213's acceptance: switching `ANALYTICS_LEVELS` to the framework tiers
    # renders correctly with no code edit — three rings above the leaves, ids
    # spelling the path, and parent value == Σ children at *every* level (what
    # `branchvalues="total"` requires).
    import src.config as cfg

    monkeypatch.setattr(cfg, "ANALYTICS_LEVELS", ("solution", "category", "family"))
    fig = _sunburst()
    arp = _universe()[["AAA Index", "BBB Index"]]
    _update_sunburst(fig, arp, _treemap_meta(), **_SUNBURST_KW)

    sb = fig.data[0]
    assert sb.maxdepth == 3
    nodes = dict(zip(sb.ids, sb.parents, strict=True))
    assert nodes["ARP"] == ""
    assert nodes["ARP / Growth"] == "ARP"
    assert nodes["ARP / Growth / Momentum"] == "ARP / Growth"
    assert nodes["AAA Index"] == "ARP / Growth / Momentum"
    assert nodes["BBB Index"] == "ARP / Value / Carry"

    val = dict(zip(sb.ids, sb.values, strict=True))
    children: dict[str, list[str]] = {}
    for node, parent in nodes.items():
        children.setdefault(parent, []).append(node)
    for node, kids in children.items():
        if node:  # "" is Plotly's root, not a node with a value
            assert val[node] == pytest.approx(sum(val[k] for k in kids))


def test_update_sunburst_buckets_a_missing_level_as_other(monkeypatch):
    # A level absent from the metadata must not break the render.
    import src.config as cfg

    monkeypatch.setattr(cfg, "ANALYTICS_LEVELS", ("asset_class", "return_type"))
    fig = _sunburst()
    arp = _universe()[["AAA Index", "BBB Index"]]
    _update_sunburst(fig, arp, _treemap_meta(), **_SUNBURST_KW)

    nodes = dict(zip(fig.data[0].ids, fig.data[0].parents, strict=True))
    assert nodes["Equity / Other"] == "Equity"
    assert nodes["AAA Index"] == "Equity / Other"


def test_update_sunburst_label_drives_colorbar_title():
    fig = _sunburst()
    arp = _universe()[["AAA Index", "BBB Index"]]
    kw = {**_SUNBURST_KW, "metric": "sortino", "label": "3M Sortino"}
    _update_sunburst(fig, arp, _treemap_meta(), **kw)
    assert fig.data[0].marker.colorbar.title.text == "3M Sortino"


def test_update_sunburst_empty_clears_traces():
    fig = _sunburst()
    _update_sunburst(fig, pd.DataFrame(), _treemap_meta(), **_SUNBURST_KW)
    assert fig.data == ()


# --- Regime specs (#220) -----------------------------------------------------


def test_every_regime_spec_is_a_typed_spec():
    # The whole point of #220: no entry is a bare dict any more, so a consumer
    # can switch on the type instead of re-deriving the shape from a string.
    assert REGIME_SPECS
    for name, spec in REGIME_SPECS.items():
        assert isinstance(spec, (LevelRegime, TercileRegime)), name


def test_level_regime_buckets_partition_the_real_line():
    # A previously implicit assumption: the fixed-level buckets are contiguous
    # half-open [low, high) spans running -inf to +inf, so every indicator value
    # lands in exactly one bucket and the dropdown can offer them verbatim.
    for name, spec in REGIME_SPECS.items():
        if not isinstance(spec, LevelRegime):
            continue
        bounds = [(low, high) for _, low, high in spec.buckets]
        assert bounds[0][0] == float("-inf"), name
        assert bounds[-1][1] == float("inf"), name
        pairs = zip(bounds[:-1], bounds[1:], strict=True)
        for (_, prev_high), (next_low, _) in pairs:
            assert prev_high == next_low, name  # no gap, no overlap


def test_an_autocorr_regime_without_a_window_is_rejected():
    # It has no series to bucket at all; catching it at construction beats a
    # consumer-side fallback quietly inventing a window.
    with pytest.raises(ValueError, match="autocorr_window"):
        TercileRegime(kind="autocorr", bucket_labels=(("Low", "low"),))


def test_regime_tickers_are_derived_from_the_specs():
    # #220 derives the fetch list from the specs, so a new regime cannot be
    # added without its indicator joining the startup fetch.
    derived = list(
        dict.fromkeys(t for spec in REGIME_SPECS.values() for t in spec.tickers())
    )
    assert derived == REGIME_TICKERS
    # The registry-sourced regime contributes nothing — its tickers are
    # benchmarks, which ride the universe fetch already.
    assert REGIME_SPECS["Trend"].tickers() == ()


def test_regime_bucket_options_by_spec_type():
    # Fixed-level buckets carry their (low, high) bounds as the option value;
    # tercile buckets carry a string key resolved against live quantiles.
    vol = regime_bucket_options("Volatility")
    assert [value for _, value in vol] == [
        (float("-inf"), 15.0),
        (15.0, 25.0),
        (25.0, float("inf")),
    ]
    assert [value for _, value in regime_bucket_options("Rate-level")] == [
        "low",
        "mid",
        "high",
    ]


def _analytics() -> PlatformAnalytics:
    """A `PlatformAnalytics` over a stub state — enough for the pure resolvers."""
    # Two options, so a test can actually change the value and fire observers.
    chips = lambda: ChipGroup([("a", 1), ("b", 2)], value=1)  # noqa: E731
    state = SimpleNamespace(
        benchmarks=SimpleNamespace(
            options=lambda labeled=False: [("SPX", "SPX Index")],
            on_change=lambda fn: None,
        ),
        universe_prices=pd.DataFrame(),
    )
    return PlatformAnalytics(
        state,
        z_metric_chips=chips(),
        # The table's own Window, carrying stats-window labels since #324 — the
        # score is measured over whichever window the table is showing.
        window_chips=ChipGroup(["1Y", "3Y"], value="1Y"),
    )


def test_regime_selector_options_by_spec_type():
    # Rate-level carries a literal source list; Trend defers to the live
    # benchmark registry (#190) so a runtime addition shows up in its picker;
    # a fixed-level regime has one ticker and so offers no source at all.
    pa = _analytics()
    pa.regime_type_dd.value = "Volatility"
    assert pa.regime_selector_options() == []
    pa.regime_type_dd.value = "Rate-level"
    assert pa.regime_selector_options() == [
        ("US (FEDL01)", "FEDL01 Index"),
        ("EU (EONIA)", "EONIA Index"),
        ("JP (MUTKCALM)", "MUTKCALM Index"),
    ]
    pa.regime_type_dd.value = "Trend"
    assert pa.regime_selector_options() == [("SPX", "SPX Index")]


def test_regime_selector_options_tolerates_an_unknown_regime():
    # An unknown regime type resolves to None upstream; it must not raise.
    pa = _analytics()
    pa.regime_type_dd.options = [*pa.regime_type_dd.options, "Nope"]
    pa.regime_type_dd.value = "Nope"
    assert pa.regime_selector_options() == []
    assert pa.regime_indicator() is None


# --- Regime Analysis: regime-conditioned risk/return scatter ----------------


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
            "category": ["Growth", "Growth", "Carry"],
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


def test_update_regime_scatter_tercile_bounds_condition_differently():
    # The tercile modes derive (low, high) from the indicator's quantiles; the
    # low and high thirds of the VIX-like series condition on disjoint day sets,
    # so the scatter coordinates differ.
    arp, vix = _regime_universe()
    lo_low, lo_high = tercile_bounds(vix.tail(200), "low")
    hi_low, hi_high = tercile_bounds(vix.tail(200), "high")

    fig_low = _regime_scatter()
    _update_regime_scatter(
        fig_low, arp, vix, _regime_meta(), low=lo_low, high=lo_high, lookback=200
    )
    fig_high = _regime_scatter()
    _update_regime_scatter(
        fig_high, arp, vix, _regime_meta(), low=hi_low, high=hi_high, lookback=200
    )
    assert fig_low.data and fig_high.data
    low_xy = [tuple(tr.x) for tr in fig_low.data]
    high_xy = [tuple(tr.x) for tr in fig_high.data]
    assert low_xy != high_xy


# --- Platform-analytics orchestration (v0.9.12-review #156) -------------------
# The render/wire logic was extracted from build_app into platform.py; these
# guard that build_app still wires it correctly end-to-end.


def _walk(w):
    yield w
    for c in getattr(w, "children", ()) or ():
        yield from _walk(c)


def test_platform_regime_controls_resync_on_type_change():
    """The regime Type dropdown is wired (platform.wire_platform_analytics ->
    _sync_regime_controls) to repopulate the Source / Bucket dropdowns: a
    tercile regime (Trend) shows the Source dropdown and Low/Middle/High
    buckets; Volatility hides the Source and uses fixed VIX-level buckets."""
    import ipywidgets as W
    from src.layout import build_app

    app = build_app(verbose=False)
    panel = app.children[5].children[0]  # Platform is the default tab
    # Mount the Regime analytics tab so its controls are in the widget tree.
    next(
        b
        for b in _walk(app)
        if isinstance(b, W.Button) and b.description == "Regime analysis"
    ).click()
    type_dd = next(
        w for w in _walk(panel) if isinstance(w, W.Dropdown) and w.description == "Type"
    )
    source_dd = next(
        w
        for w in _walk(panel)
        if isinstance(w, W.Dropdown) and w.description == "Source"
    )
    bucket_dd = next(
        w
        for w in _walk(panel)
        if isinstance(w, W.Dropdown) and w.description == "Bucket"
    )

    assert type_dd.value == "Volatility"
    assert source_dd.layout.display == "none"  # no source for Volatility
    vix_buckets = [o[0] for o in bucket_dd.options]

    type_dd.value = "Trend"  # tercile regime — wired observer re-syncs
    assert source_dd.layout.display != "none"
    assert len(source_dd.options) > 0
    assert [o[0] for o in bucket_dd.options] != vix_buckets

    type_dd.value = "Volatility"  # back to fixed buckets, source hidden
    assert source_dd.layout.display == "none"
    assert [o[0] for o in bucket_dd.options] == vix_buckets


def test_platform_analytics_tab_swap():
    """Clicking the analytics pills swaps the chart shown in the card
    (platform.activate_platform_tab, wired by build_app)."""
    import ipywidgets as W
    from src.layout import build_app

    app = build_app(verbose=False)
    panel = app.children[5].children[0]
    analytics_card = panel.children[
        -1
    ]  # the card is last; #279 removed the row above the table
    chart_box = analytics_card.children[2].children[1]  # analytics_body -> chart_box
    pills = {b.description: b for b in _walk(analytics_card) if isinstance(b, W.Button)}
    first = chart_box.children[0]
    pills["Factor exposures"].click()
    assert chart_box.children[0] is not first  # swapped to the factor scatter
    pills["Sunburst"].click()
    assert chart_box.children[0] is first  # back to the sunburst


def test_platform_analytics_render_is_lazy(monkeypatch):
    """v0.9.13 #168: only the visible (Sunburst) analytics tab renders on load;
    Regime / Factor render on their pill's first activation and not again while
    fresh."""
    import ipywidgets as W
    from src.layout import build_app

    calls = {"sunburst": 0, "regime": 0, "factor": 0}
    # #219: the renderers are methods now, so spy on the class rather than on a
    # module-level dispatch dict.
    methods = {
        "sunburst": "render_sunburst",
        "regime": "render_regime_scatter",
        "factor": "render_factor_scatter",
    }

    def _spy(name, real):
        def render(self, meta):
            calls[name] += 1
            return real(self, meta)

        return render

    for name, attr in methods.items():
        monkeypatch.setattr(
            PlatformAnalytics, attr, _spy(name, getattr(PlatformAnalytics, attr))
        )

    app = build_app(verbose=False)
    # On load only the visible Sunburst tab is computed.
    assert calls == {"sunburst": 1, "regime": 0, "factor": 0}

    analytics_card = app.children[5].children[0].children[-1]
    pills = {b.description: b for b in _walk(analytics_card) if isinstance(b, W.Button)}

    pills["Factor exposures"].click()  # first activation → render once
    assert calls["factor"] == 1
    pills["Sunburst"].click()  # already fresh → no re-render
    pills["Factor exposures"].click()  # still fresh → no re-render
    assert calls["factor"] == 1
    assert calls["sunburst"] == 1
    assert calls["regime"] == 0  # never activated → never rendered


def test_platform_analytics_owns_its_card_and_lazy_state():
    # #219: the twenty-field `pa` namespace is now an object that builds its own
    # widgets, so `build_app` mounts `.card` instead of assembling them.
    import ipywidgets as W

    pa = _analytics()
    assert isinstance(pa.card, W.VBox)
    assert "bbg-card" in pa.card._dom_classes
    assert set(pa.analytics_tabs) == {"sunburst", "regime", "factor"}
    for key, (pill, controls, fig) in pa.analytics_tabs.items():
        assert isinstance(pill, W.Button), key
        assert isinstance(controls, W.Widget), key
        assert isinstance(fig, go.FigureWidget), key
    # Opens on Sunburst with nothing drawn yet — the lazy contract's start state.
    assert pa.active_analytics == "sunburst"
    assert pa.fresh == set()
    assert pa.chart_box.children == (pa.sunburst_fig,)


def test_platform_analytics_instances_do_not_share_state():
    # `fresh` is a per-instance set, not a class attribute — the mutable-default
    # trap on a field `activate` / `invalidate` mutate constantly.
    a, b = _analytics(), _analytics()
    a.fresh.add("regime")
    a.active_analytics = "regime"
    assert b.fresh == set()
    assert b.active_analytics == "sunburst"
    assert a.sunburst_fig is not b.sunburst_fig


def test_activate_swaps_controls_and_chart():
    # The pill click's visible effect, independent of any rendering: the left
    # column and the chart box follow the active tab.
    pa = _analytics()
    pa.fresh.update({"sunburst", "regime", "factor"})  # skip the lazy render
    pa.activate(pd.DataFrame(), "regime")
    assert pa.active_analytics == "regime"
    assert pa.chart_box.children == (pa.regime_scatter_fig,)
    assert pa.tab_controls_box.children == (pa.analytics_tabs["regime"][1],)
    pa.activate(pd.DataFrame(), "factor")
    assert pa.chart_box.children == (pa.factor_scatter_fig,)


def test_invalidate_marks_every_tab_stale():
    # A data or lookback change stales all three; only the visible one redraws
    # (the redraw itself no-ops here — the stub state has no prices).
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()
    pa.fresh.update({"sunburst", "regime", "factor"})
    pa.invalidate(pd.DataFrame())
    # `render_active` re-adds only the visible tab; the hidden two stay stale.
    assert pa.fresh == {"sunburst"}


def test_observers_render_against_the_current_catalog_not_the_wired_one():
    """#242: `wire` takes a callable, so a re-pointed catalog reaches the
    observers.

    `build_app` rebinds its `meta` to the recent-performance-pruned catalog
    after every load. An observer that captured the frame it was wired with
    redrew from the *pre-prune* catalog, putting the stale indices the prune
    removed back into the grid. Off-terminal the prune is a no-op (every mock
    ticker moves), so nothing else in the suite can catch this — the two frames
    have to be made to differ deliberately.
    """
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()  # renders are no-ops
    seen: list[pd.DataFrame] = []
    pa.render_universe_grid = seen.append  # type: ignore[method-assign]

    holder = {"meta": pd.DataFrame({"ticker": ["A", "B", "C"]})}  # pre-prune
    pa.wire(lambda: holder["meta"])

    holder["meta"] = pd.DataFrame({"ticker": ["A"]})  # what the prune leaves
    pa.z_metric_chips.value = pa.z_metric_chips.options[-1][1]

    assert seen, "the z-score chips should have driven a grid render"
    assert list(seen[-1]["ticker"]) == ["A"]  # the pruned catalog, not the wired one
