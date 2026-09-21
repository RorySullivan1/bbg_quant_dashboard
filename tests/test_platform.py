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
    PlatformAnalytics,
    _asset_class_colors,
    _factor_beta_scatter,
    _regime_scatter,
    _update_factor_scatter,
    _update_regime_scatter,
    regime_bucket_options,
)
from src.layout.platform_charts import IcicleChart
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


_ICICLE_KW = dict(metric="sharpe", metric_label="1W Sharpe")


def _icicle_frame(meta=None):
    """`icicle_frame` over the seeded universe, restricted to the strategies."""
    from src.stats import icicle_frame

    meta = _treemap_meta() if meta is None else meta
    arp = _universe()[["AAA Index", "BBB Index"]]
    return icicle_frame(arp, meta, metric="sharpe", window=WEEK_WINDOW)


def test_the_icicle_sizes_every_cell_by_its_strategy_count():
    """#331 decision 8 — the change of meaning, not just of chart type.

    The sunburst sized arcs by |z|: the gross magnitude of the very quantity
    colour already encoded, so a ring's shares read as nothing. Counting makes
    a cell's width its share of strategies, which is a question the catalog
    does not otherwise answer visually.
    """
    chart = IcicleChart()
    chart.update(_icicle_frame(), **_ICICLE_KW)

    (trace,) = chart.fig.data
    assert isinstance(trace, go.Icicle)
    assert trace.branchvalues == "total"
    value = dict(zip(trace.ids, trace.values, strict=True))
    # Two strategies, one asset class, two categories under it.
    assert value["Equity"] == 2
    assert value["Equity / Growth"] == 1
    assert value["Equity / Growth / Momentum"] == 1
    # Every leaf is exactly 1, whatever its metric says.
    leaves = [v for node, v in value.items() if node.endswith(" Index")]
    assert leaves == [1, 1]


def test_the_icicle_colours_a_parent_by_the_mean_of_its_leaves():
    chart = IcicleChart()
    frame = _icicle_frame()
    chart.update(frame, **_ICICLE_KW)

    (trace,) = chart.fig.data
    colour = dict(zip(trace.ids, trace.marker.colors, strict=True))
    assert colour["Equity"] == pytest.approx(frame["value"].mean())


def test_the_icicle_s_colour_range_is_symmetric_and_taken_from_the_data():
    """The fixed ±2 it replaces was a z-score's range; a raw Sharpe has no
    reason to share it, and an outlier must not flatten everything else."""
    chart = IcicleChart()
    frame = _icicle_frame()
    frame.loc["AAA Index", "value"] = 40.0  # one wild outlier
    chart.update(frame, **_ICICLE_KW)

    marker = chart.fig.data[0].marker
    assert marker.cmid == 0
    assert marker.cmin == pytest.approx(-marker.cmax)
    assert marker.cmax < 40.0, "the 95th percentile clips the outlier"


def test_the_icicle_s_ids_are_paths_so_a_click_round_trips():
    """A cell's id IS the path, so a click becomes a `Drill.scope` without
    parsing anything the renderer invented."""
    got: list[tuple[str, ...]] = []
    chart = IcicleChart(on_drill=got.append)
    chart.update(_icicle_frame(), **_ICICLE_KW)

    trace = chart.fig.data[0]
    index = list(trace.ids).index("Equity / Growth")
    chart._clicked(trace, SimpleNamespace(point_inds=[index]), None)
    assert got == [("Equity", "Growth")]


def test_the_icicle_s_ids_keep_a_repeated_label_as_two_cells():
    # The sample catalog's real case: one category under two asset classes.
    meta = pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index"],
            "asset_class": ["Equity", "Fixed Income"],
            "solution": ["ARP", "ARP"],
            "category": ["Emerging Markets", "Emerging Markets"],
            "family": ["MSCI", "Bloomberg"],
        }
    )
    chart = IcicleChart()
    chart.update(_icicle_frame(meta), **_ICICLE_KW)

    ids = set(chart.fig.data[0].ids)
    assert "Equity / Emerging Markets" in ids
    assert "Fixed Income / Emerging Markets" in ids


def test_the_icicle_s_points_are_its_leaves_under_the_scope():
    chart = IcicleChart()
    chart.update(_icicle_frame(), **_ICICLE_KW, scope=("Equity", "Growth"))

    points = chart.points()
    assert list(points.columns) == ["path", "label", "name", "value", "count"]
    assert list(points["label"]) == ["AAA Index"]
    assert (points["count"] == 1).all()
    assert points.loc["AAA Index", "path"] == ("Equity", "Growth", "Momentum")


def test_the_icicle_follows_a_reconfigured_hierarchy(monkeypatch):
    # #213's acceptance, carried over: the chart walks `ANALYTICS_LEVELS`
    # rather than naming its levels, so the tiers are a config flip.
    import src.config as cfg

    monkeypatch.setattr(cfg, "ANALYTICS_LEVELS", ("solution", "category", "family"))
    chart = IcicleChart()
    chart.update(_icicle_frame(), **_ICICLE_KW)

    trace = chart.fig.data[0]
    assert trace.maxdepth == 3
    nodes = dict(zip(trace.ids, trace.parents, strict=True))
    assert nodes["ARP"] == ""
    assert nodes["ARP / Growth"] == "ARP"
    assert nodes["ARP / Growth / Momentum"] == "ARP / Growth"


def test_the_icicle_buckets_a_missing_level_as_other(monkeypatch):
    import src.config as cfg

    monkeypatch.setattr(cfg, "ANALYTICS_LEVELS", ("asset_class", "return_type"))
    chart = IcicleChart()
    chart.update(_icicle_frame(), **_ICICLE_KW)

    nodes = dict(zip(chart.fig.data[0].ids, chart.fig.data[0].parents, strict=True))
    assert nodes["Equity / Other"] == "Equity"


def test_the_icicle_label_drives_the_colorbar_and_the_value_label():
    chart = IcicleChart()
    chart.update(_icicle_frame(), metric="sortino", metric_label="3M Sortino")
    assert chart.fig.data[0].marker.colorbar.title.text == "3M Sortino"
    # #337's table reads this rather than spelling a label of its own.
    assert chart.value_label == "3M Sortino"
    assert chart.value_format == ".2f"


def test_the_icicle_formats_a_return_as_a_percentage():
    chart = IcicleChart()
    chart.update(_icicle_frame(), metric="return", metric_label="1Y Return")
    assert chart.value_format == ".2%"


def test_the_icicle_empty_clears_traces_and_points():
    chart = IcicleChart()
    chart.update(_icicle_frame(), **_ICICLE_KW)
    chart.update(
        pd.DataFrame(columns=["asset_class", "category", "family", "value"]),
        **_ICICLE_KW,
    )
    assert chart.fig.data == ()
    assert chart.points().empty


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


def _analytics_of(app) -> PlatformAnalytics:
    """The live `PlatformAnalytics` inside a built app.

    Reached through the card's own widgets rather than a child index, so a
    layout change moves the test's footing once, here.
    """
    card = app.children[5].children[0].children[-1]
    return next(
        w._analytics for w in _walk(card) if getattr(w, "_analytics", None) is not None
    )


def test_regime_selector_options_by_spec_type():
    # Rate-level carries a literal source list; Trend defers to the live
    # benchmark registry (#190) so a runtime addition shows up in its picker;
    # a fixed-level regime has one ticker and so offers no source at all.
    pa = _analytics()
    pa.regime_type_chips.value = "Volatility"
    assert pa.regime_selector_options() == []
    pa.regime_type_chips.value = "Rate-level"
    assert pa.regime_selector_options() == [
        ("US (FEDL01)", "FEDL01 Index"),
        ("EU (EONIA)", "EONIA Index"),
        ("JP (MUTKCALM)", "MUTKCALM Index"),
    ]
    pa.regime_type_chips.value = "Trend"
    assert pa.regime_selector_options() == [("SPX", "SPX Index")]


def test_regime_selector_options_tolerates_an_unknown_regime():
    # An unknown regime type resolves to None upstream; it must not raise.
    pa = _analytics()
    pa.regime_type_chips.set_options(
        [*pa.regime_type_chips.options, ("Nope", "Nope")], value="Nope"
    )
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


def _chart_chip(card, label: str):
    """The Chart section's chip named ``label`` (#333 retired the pill row)."""
    import ipywidgets as W

    return next(
        b for b in _walk(card) if isinstance(b, W.Button) and b.description == label
    )


def test_platform_regime_controls_resync_on_type_change():
    """The regime Type chips repopulate the Source dropdown and Bucket chips.

    A tercile regime (Trend) shows the Source dropdown and Low/Middle/High
    buckets; Volatility hides the Source and uses fixed VIX-level buckets.
    Type and Bucket are `ChipGroup`s since #333; Source stays a dropdown
    because its options are a long live list (#331 decision 13).
    """
    import ipywidgets as W
    from src.layout import build_app

    app = build_app(verbose=False)
    panel = app.children[5].children[0]  # Platform is the default tab
    card = panel.children[-1]
    pa = _analytics_of(app)

    # The Regime section only shows on the Scatter, so select it first.
    _chart_chip(card, "Scatter").click()
    source_dd = next(
        w
        for w in _walk(panel)
        if isinstance(w, W.Dropdown) and w.description == "Source"
    )

    assert pa.regime_type_chips.value == "Volatility"
    assert source_dd.layout.display == "none"  # no source for Volatility
    vix_buckets = [label for label, _ in pa.regime_bucket_chips.options]

    pa.regime_type_chips.value = "Trend"  # tercile regime — observer re-syncs
    assert source_dd.layout.display != "none"
    assert len(source_dd.options) > 0
    assert [label for label, _ in pa.regime_bucket_chips.options] != vix_buckets

    pa.regime_type_chips.value = "Volatility"  # back to fixed buckets
    assert source_dd.layout.display == "none"
    assert [label for label, _ in pa.regime_bucket_chips.options] == vix_buckets


def test_platform_chart_chips_swap_the_chart():
    """The Chart chips are the selector the three pills used to be (#331 dec. 4)."""
    from src.layout import build_app

    app = build_app(verbose=False)
    panel = app.children[5].children[0]
    card = panel.children[-1]
    chart_box = card.children[2].children[0]
    first = chart_box.children[0]

    _chart_chip(card, "Scatter").click()
    assert chart_box.children[0] is not first
    _chart_chip(card, "Icicle").click()
    assert chart_box.children[0] is first


def test_the_bar_shows_only_the_sections_the_active_chart_reads():
    """#331 decision 3 — and the chips keep their state across the switch."""
    pa = _analytics()
    pa.fresh.update({"icicle", "scatter", "strip"})

    def shown(heading):
        return pa.bar.section(heading).layout.display != "none"

    pa.activate(pd.DataFrame(), "icicle")
    # The Icicle draws every level at once and zooms itself, so a Level or a
    # Scope would be describing a position it does not have.
    assert not shown("Level") and not shown("Scope")
    assert shown("Metric") and shown("Window")
    assert not shown("Regime")

    pa.metric_chips.value = "calmar"
    pa.activate(pd.DataFrame(), "strip")
    # The Strip's metric and window are fixed (1D returns over five days).
    assert not shown("Metric") and not shown("Window")
    assert shown("Level") and shown("Scope")

    pa.activate(pd.DataFrame(), "scatter")
    assert shown("Regime")
    # Hidden, not rebuilt: the selection survives the round trip.
    assert pa.metric_chips.value == "calmar"


def test_platform_analytics_render_is_lazy(monkeypatch):
    """v0.9.13 #168: only the visible chart renders on load; the others render
    on their chip's first selection and not again while fresh."""
    from src.layout import build_app

    calls = {"icicle": 0, "scatter": 0}
    methods = {"icicle": "render_icicle", "scatter": "render_regime_scatter"}

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
    assert calls == {"icicle": 1, "scatter": 0}

    card = app.children[5].children[0].children[-1]
    _chart_chip(card, "Scatter").click()  # first selection → render once
    assert calls["scatter"] == 1
    _chart_chip(card, "Icicle").click()  # already fresh → no re-render
    _chart_chip(card, "Scatter").click()  # still fresh → no re-render
    assert calls["scatter"] == 1
    assert calls["icicle"] == 1


def test_platform_analytics_owns_its_card_and_lazy_state():
    # #219: the twenty-field `pa` namespace is now an object that builds its own
    # widgets, so `build_app` mounts `.card` instead of assembling them.
    import ipywidgets as W

    pa = _analytics()
    assert isinstance(pa.card, W.VBox)
    assert "bbg-card" in pa.card._dom_classes
    assert set(pa.analytics_tabs) == {"icicle", "scatter", "strip"}
    for key, mounted in pa.analytics_tabs.items():
        assert isinstance(mounted, W.Widget), key
    # Opens on the Icicle with nothing drawn yet — the lazy contract's start.
    assert pa.active_analytics == "icicle"
    assert pa.fresh == set()
    assert pa.chart_box.children == (pa.icicle.fig,)


def test_platform_analytics_instances_do_not_share_state():
    # `fresh` is a per-instance set, not a class attribute — the mutable-default
    # trap on a field `activate` / `invalidate` mutate constantly.
    a, b = _analytics(), _analytics()
    a.fresh.add("scatter")
    a.active_analytics = "scatter"
    assert b.fresh == set()
    assert b.active_analytics == "icicle"
    assert a.icicle is not b.icicle
    # The drill is per-instance too, for the same reason.
    a.set_drill(("Equity",), "family")
    assert b.drill.scope == ()


def test_activate_swaps_the_chart():
    # The chip's visible effect, independent of any rendering.
    pa = _analytics()
    pa.fresh.update({"icicle", "scatter", "strip"})
    pa.activate(pd.DataFrame(), "scatter")
    assert pa.active_analytics == "scatter"
    assert pa.chart_box.children == (pa.regime_scatter_fig,)
    pa.activate(pd.DataFrame(), "strip")
    assert pa.chart_box.children == (pa.strip_placeholder,)


def test_invalidate_marks_every_chart_stale():
    # A data change stales all three; only the visible one redraws (the redraw
    # itself no-ops here — the stub state has no prices).
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()
    pa.fresh.update({"icicle", "scatter", "strip"})
    pa.invalidate(pd.DataFrame())
    assert pa.fresh == {"icicle"}


# --- the drill (#333) -------------------------------------------------------


def test_set_drill_is_the_only_writer_and_repaints_both_displays():
    """#331 decision 15: no chart holds a private focus."""
    pa = _analytics()
    pa.set_drill(("Equity", "Momentum"), "family")

    assert pa.drill.scope == ("Equity", "Momentum")
    assert pa.drill.level == "family"
    # The two controls that DISPLAY the state follow it, rather than each
    # holding a copy that could disagree.
    assert pa.level_chips.value == "family"
    assert [b.description for b in pa.breadcrumb.children] == [
        "All",
        "Equity",
        "Momentum",
    ]


def test_narrowing_moves_one_stop_down_and_bottoms_out_at_the_leaf():
    pa = _analytics()
    pa.narrow_to(("Equity", "Momentum"))
    assert pa.drill.level == "family"
    pa.narrow_to(("Equity", "Momentum", "Fast"))
    assert pa.drill.level == "ticker"
    # A click on a strategy is a no-op, not an error: the table row is the way
    # into Single Strategy.
    pa.narrow_to(("Equity", "Momentum", "Fast"))
    assert pa.drill.level == "ticker"


def test_a_breadcrumb_segment_returns_to_its_prefix():
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()  # renders no-op
    pa.wire(lambda: pd.DataFrame())
    pa.set_drill(("Equity", "Momentum"), "family")

    pa.breadcrumb.children[1].click()  # "Equity"
    assert pa.drill.scope == ("Equity",)
    assert pa.drill.level == "category"  # the stop below an asset class

    pa.breadcrumb.children[0].click()  # "All"
    assert pa.drill.scope == ()
    assert pa.drill.level == "category"


def test_a_level_chip_sets_the_depth_within_the_current_scope():
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()
    pa.wire(lambda: pd.DataFrame())
    pa.set_drill(("Equity",), "category")

    pa.level_chips.value = "ticker"
    assert pa.drill.level == "ticker"
    assert pa.drill.scope == ("Equity",), "the chip changes depth, not scope"


def test_syncing_the_displays_does_not_re_enter_the_setter():
    """`set_drill` repaints the Level chips; their observer must not fire back.

    Without the guard a drill change renders twice — and a breadcrumb click
    would set the level from the chip it had just repainted, not from the
    prefix that was clicked.
    """
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()
    renders: list[str] = []
    pa.wire(lambda: pd.DataFrame())
    pa._render_tab = lambda meta, which: renders.append(which)  # type: ignore

    pa.breadcrumb.children[0].click()  # "All" — one drill change
    assert len(renders) == 1


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
