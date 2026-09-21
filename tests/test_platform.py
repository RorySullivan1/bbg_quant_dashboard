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
from src.layout.grids import ChartPointsGrid
from src.layout.platform import (
    PlatformAnalytics,
    regime_bucket_options,
)
from src.layout.platform_charts import (
    IcicleChart,
    RegimeFactorScatter,
    StripChart,
    asset_class_colors,
    group_colors,
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


def _scatter_points(n_groups=2, counts=(3, 1)) -> pd.DataFrame:
    """An aggregated points frame of the shape `drill_points` returns."""
    labels = ["Equity", "Fixed Income"][:n_groups]
    return pd.DataFrame(
        {
            "path": [(label,) for label in labels],
            "label": labels,
            "name": labels,
            "count": list(counts)[:n_groups],
            "value": [1.5, -0.5][:n_groups],
            "x": [0.2, -0.1][:n_groups],
            "z": [0.9, 0.3][:n_groups],
        },
        index=labels,
    )


def test_the_scatter_draws_one_trace_per_colour_key():
    chart = RegimeFactorScatter()
    points = _scatter_points()
    chart.update(
        points,
        metric="sharpe",
        metric_label="1Y Sharpe",
        color_key="asset_class",
        colors=ASSET_CLASS_COLORS,
    )

    assert not chart.fig.layout.title.text
    by_name = {tr.name: tr for tr in chart.fig.data}
    assert set(by_name) == {"Equity", "Fixed Income"}
    assert all(isinstance(tr, go.Scatter3d) for tr in chart.fig.data)
    assert by_name["Equity"].marker.color == ASSET_CLASS_COLORS["Equity"]


def test_the_scatter_puts_the_metric_on_y_and_the_betas_on_x_and_z():
    """#331 decision 10 — the axes are the merge, so they are pinned."""
    chart = RegimeFactorScatter()
    points = _scatter_points(n_groups=1, counts=(3,))
    chart.update(
        points,
        metric="sharpe",
        metric_label="1Y Sharpe",
        color_key="asset_class",
        colors=ASSET_CLASS_COLORS,
    )

    (trace,) = chart.fig.data
    assert trace.y[0] == points.loc["Equity", "value"]
    assert trace.x[0] == points.loc["Equity", "x"]  # term premium
    assert trace.z[0] == points.loc["Equity", "z"]  # equity risk premium
    scene = chart.fig.layout.scene
    assert scene.xaxis.title.text == "Term-premium β"
    assert scene.yaxis.title.text == "1Y Sharpe"
    assert scene.zaxis.title.text == "Equity risk-premium β"


def test_the_origin_is_drawn_by_the_axes_and_the_planes_are_gone():
    """The translucent Mesh3d planes dimmed the markers they framed (#331
    decision 11). A scene takes no paper shapes, but its axes carry a zero
    line and a wall edge, which is enough."""
    from src.style import Color

    chart = RegimeFactorScatter()
    chart.update(
        _scatter_points(),
        metric="sharpe",
        metric_label="1Y Sharpe",
        color_key="asset_class",
        colors=ASSET_CLASS_COLORS,
    )

    assert not [tr for tr in chart.fig.data if isinstance(tr, go.Mesh3d)]
    assert all(isinstance(tr, go.Scatter3d) for tr in chart.fig.data)
    scene = chart.fig.layout.scene
    for axis in (scene.xaxis, scene.yaxis, scene.zaxis):
        assert axis.zeroline is True
        assert axis.zerolinecolor == Color.CHART_ZERO_LINE.value
        assert axis.zerolinewidth == 3
        assert axis.showline is True
        assert axis.linecolor == Color.CHART_AXIS_LINE.value
    # The three axes stay comparable, so a beta of 0.2 looks the same size
    # whichever axis it is on.
    assert scene.aspectmode == "cube"


def test_a_group_marker_is_bigger_than_a_strategy_marker():
    chart = RegimeFactorScatter()
    chart.update(
        _scatter_points(counts=(9, 1)),
        metric="sharpe",
        metric_label="1Y Sharpe",
        color_key="asset_class",
        colors=ASSET_CLASS_COLORS,
    )
    by_name = {tr.name: tr for tr in chart.fig.data}
    assert by_name["Equity"].marker.size[0] > by_name["Fixed Income"].marker.size[0]


def test_clicking_a_group_marker_narrows_and_a_strategy_marker_does_not():
    got: list[tuple[str, ...]] = []
    chart = RegimeFactorScatter(on_drill=got.append)
    chart.update(
        _scatter_points(counts=(3, 1)),
        metric="sharpe",
        metric_label="1Y Sharpe",
        color_key="asset_class",
        colors=ASSET_CLASS_COLORS,
    )
    by_name = {tr.name: tr for tr in chart.fig.data}

    chart._clicked(by_name["Equity"], SimpleNamespace(point_inds=[0]), None)
    assert got == [("Equity",)]

    # A leaf has no children; the table row is the way into Single Strategy.
    chart._clicked(by_name["Fixed Income"], SimpleNamespace(point_inds=[0]), None)
    assert got == [("Equity",)]


def test_every_trace_carries_the_click_handler_not_just_the_first():
    chart = RegimeFactorScatter(on_drill=lambda _p: None)
    chart.update(
        _scatter_points(),
        metric="sharpe",
        metric_label="1Y Sharpe",
        color_key="asset_class",
        colors=ASSET_CLASS_COLORS,
    )
    assert len(chart.fig.data) == 2
    assert all(tr._click_callbacks for tr in chart.fig.data)


def test_the_scatter_empty_clears_traces():
    chart = RegimeFactorScatter()
    chart.update(
        pd.DataFrame(),
        metric="sharpe",
        metric_label="1Y Sharpe",
        color_key="asset_class",
        colors={},
    )
    assert chart.fig.data == ()


def test_catalog_asset_classes_get_distinct_non_fallback_colors():
    """Every distinct AssetClass in the catalog maps to a distinct, non-fallback
    color — guards against the all-grey legend (driven off the loaded metadata,
    so future catalog additions are covered too)."""
    classes = sorted(load_metadata()["asset_class"].dropna().unique())
    colors = asset_class_colors(classes)
    assert set(colors) == set(classes)
    assert ASSET_CLASS_FALLBACK_COLOR not in colors.values()
    assert len(set(colors.values())) == len(classes)  # all distinct


def test_asset_class_colors_unmapped_class_avoids_fallback():
    """An unmapped class still gets a distinct palette color, not the grey
    fallback, as long as the palette isn't exhausted."""
    colors = asset_class_colors(["Equity", "Crypto"])
    assert colors["Equity"] == ASSET_CLASS_COLORS["Equity"]
    assert colors["Crypto"] != ASSET_CLASS_FALLBACK_COLOR
    assert colors["Crypto"] != colors["Equity"]


def test_group_colors_serves_keys_that_are_not_asset_classes():
    """The drill re-keys colours at every depth (#331 decision 17), so the
    palette has to serve families and tickers too — with no curated map, and
    with no claim on an asset class's identity colour."""
    colors = group_colors(["Momentum", "Carry", "Value"])
    assert len(set(colors.values())) == 3
    assert ASSET_CLASS_FALLBACK_COLOR not in colors.values()


def test_group_colors_cycles_rather_than_collapsing_to_grey():
    """A family larger than the palette should still draw distinguishable
    neighbours; the legend and hover name every point whatever the hue."""
    from src.style import LINE_PALETTE

    keys = [f"k{i:02d}" for i in range(len(LINE_PALETTE) + 3)]
    colors = group_colors(keys)
    assert set(colors) == set(keys)
    assert ASSET_CLASS_FALLBACK_COLOR not in colors.values()
    assert len(set(colors.values())) == len(LINE_PALETTE)


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


def _analytics(on_open_strategy=None) -> PlatformAnalytics:
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
        on_open_strategy=on_open_strategy,
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


def test_the_regime_mask_conditions_the_scatter_s_sample():
    """What the old regime scatter tested, at the level it now lives.

    The chart no longer owns the conditioning: `_regime_window_mask` picks the
    days and `regime_factor_frame` measures all three axes over them, so the
    behaviour is pinned on the pair rather than on a figure's coordinates.
    """
    from src.layout.platform import _regime_window_mask
    from src.stats import daily_returns, regime_factor_frame

    arp, vix = _regime_universe()
    rets = daily_returns(arp).tail(200)
    erp = pd.Series(0.001, index=rets.index)
    tp = pd.Series(0.0005, index=rets.index)

    lo_low, lo_high = tercile_bounds(vix.tail(200), "low")
    hi_low, hi_high = tercile_bounds(vix.tail(200), "high")
    low_mask = _regime_window_mask(vix, rets.index, lo_low, lo_high)
    high_mask = _regime_window_mask(vix, rets.index, hi_low, hi_high)

    # Disjoint day sets, so the two buckets describe the catalog differently.
    assert not (low_mask & high_mask).any()
    low = regime_factor_frame(rets, low_mask, erp, tp, metric="sharpe")
    high = regime_factor_frame(rets, high_mask, erp, tp, metric="sharpe")
    assert not low.empty and not high.empty
    assert not low["value"].equals(high["value"])


def test_a_scaffolded_regime_is_the_unconditioned_view():
    # A regime with no indicator in the cache must not blank the chart; it
    # falls back to every day in the window, as it did before the merge.
    from src.layout.platform import _regime_window_mask

    arp, _ = _regime_universe()
    index = daily_returns(arp).tail(200).index
    mask = _regime_window_mask(None, index, None, None)
    assert mask.all()


# --- the Strip (#336) -------------------------------------------------------


def _strip_points(counts=(3, 1)) -> tuple[pd.DataFrame, list]:
    """An aggregated points frame with one column per date."""
    dates = list(pd.bdate_range("2026-09-14", periods=3))
    labels = ["Equity", "Fixed Income"]
    frame = pd.DataFrame(
        {
            "path": [(label,) for label in labels],
            "label": labels,
            "name": labels,
            "count": list(counts),
            dates[0]: [0.01, -0.02],
            dates[1]: [0.02, 0.01],
            dates[2]: [-0.01, 0.03],
        },
        index=labels,
    )
    return frame, dates


def test_the_strip_draws_one_column_per_date_with_the_dates_as_labels():
    chart = StripChart()
    points, dates = _strip_points()
    chart.update(points, dates, color_key="asset_class", colors=ASSET_CLASS_COLORS)

    assert chart.fig.data
    axis = chart.fig.layout.xaxis
    assert list(axis.tickvals) == [0, 1, 2]
    assert list(axis.ticktext) == ["14 Sep", "15 Sep", "16 Sep"]
    # A dashed zero reference, so a down day reads as down at a glance.
    assert chart.fig.layout.shapes


def test_the_strip_jitters_within_a_date_rather_than_stacking_on_it():
    """A categorical axis puts every marker of a column on one line, so a
    group of ten strategies would draw as a single dot."""
    chart = StripChart()
    points, dates = _strip_points()
    chart.update(points, dates, color_key="asset_class", colors=ASSET_CLASS_COLORS)

    xs = [x for tr in chart.fig.data for x in tr.x]
    # Two points per date, each offset from the date's centre, none overlapping.
    first_column = sorted(x for x in xs if abs(x) < 0.5)
    assert len(first_column) == 2
    assert first_column[0] != first_column[1]
    assert all(abs(x - round(x)) <= StripChart.JITTER + 1e-9 for x in xs)


def test_the_strip_s_jitter_is_stable_across_redraws():
    # Drawn at random it would reshuffle on every redraw and read as movement
    # in the data.
    points, dates = _strip_points()
    first = StripChart()
    first.update(points, dates, color_key="asset_class", colors=ASSET_CLASS_COLORS)
    second = StripChart()
    second.update(points, dates, color_key="asset_class", colors=ASSET_CLASS_COLORS)
    assert [tuple(t.x) for t in first.fig.data] == [tuple(t.x) for t in second.fig.data]


def test_the_strip_s_points_value_is_the_compounded_return_of_its_row():
    """#331 decision 12 — a `label · name · value` row cannot hold five dots,
    and what they add up to is the honest single number."""
    from src.stats import compounded_return

    chart = StripChart()
    points, dates = _strip_points()
    chart.update(points, dates, color_key="asset_class", colors=ASSET_CLASS_COLORS)

    drawn = chart.points()
    expected = compounded_return(points[dates].T)
    assert drawn.loc["Equity", "value"] == pytest.approx(expected["Equity"])
    assert chart.value_label == "5D Return"
    assert chart.value_format == ".2%"


def test_clicking_a_strip_group_narrows_and_a_strategy_does_not():
    got: list[tuple[str, ...]] = []
    chart = StripChart(on_drill=got.append)
    points, dates = _strip_points(counts=(3, 1))
    chart.update(points, dates, color_key="asset_class", colors=ASSET_CLASS_COLORS)

    by_name = {tr.name: tr for tr in chart.fig.data}
    chart._clicked(by_name["Equity"], SimpleNamespace(point_inds=[0]), None)
    assert got == [("Equity",)]
    chart._clicked(by_name["Fixed Income"], SimpleNamespace(point_inds=[0]), None)
    assert got == [("Equity",)]


def test_the_strip_draws_what_exists_below_five_days():
    # A fresh mock, or a benchmark added mid-session as a delta.
    chart = StripChart()
    points, dates = _strip_points()
    chart.update(points, dates[:2], color_key="asset_class", colors=ASSET_CLASS_COLORS)
    assert list(chart.fig.layout.xaxis.tickvals) == [0, 1]


def test_the_strip_empty_clears():
    chart = StripChart()
    chart.update(pd.DataFrame(), [], color_key="asset_class", colors={})
    assert chart.fig.data == ()
    assert chart.points().empty


def test_a_metric_or_window_change_does_not_render_the_strip():
    """The Strip's metric and window are fixed, so the controls that would
    normally re-render the visible chart must not touch it (#331 dec. 3)."""
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()
    pa.wire(lambda: pd.DataFrame())
    rendered: list[str] = []
    pa._render_tab = lambda meta, which: rendered.append(which)  # type: ignore

    pa.activate(pd.DataFrame(), "strip")
    rendered.clear()
    # Both sections are hidden while the Strip is active, so a user cannot
    # reach them — this pins that the wiring agrees with the chrome.
    assert pa.bar.section("Metric").layout.display == "none"
    assert pa.bar.section("Window").layout.display == "none"


# --- the points table (#337) ------------------------------------------------


def _points_frame(counts=(3, 1)) -> pd.DataFrame:
    labels = ["Equity", "Fixed Income"]
    return pd.DataFrame(
        {
            "path": [(label,) for label in labels],
            "label": labels,
            "name": ["Equity basket", "Credit basket"],
            "count": list(counts),
            "value": [0.5, 1.5],
        },
        index=labels,
    )


def test_the_points_table_heads_its_columns_from_the_chart_and_the_level():
    """The first column says what a row *is*; the last, in the chart's own
    units, says what it is worth. Neither label is spelled here (#337)."""
    grid = ChartPointsGrid()
    grid.update(
        _points_frame(), level_label="Category", value_label="1Y Sharpe", fmt=".2f"
    )
    assert list(grid.widget.df.columns) == [
        "Category",
        "Name",
        "Count",
        "1Y Sharpe",
    ]


def test_the_points_table_sorts_by_value_descending_with_blanks_last():
    grid = ChartPointsGrid()
    frame = _points_frame()
    frame.loc["Equity", "value"] = float("nan")
    grid.update(frame, level_label="Category", value_label="1Y Sharpe", fmt=".2f")
    # A strategy with no history sinks rather than topping the table.
    assert list(grid.widget.df["Category"]) == ["Fixed Income", "Equity"]


def test_the_count_column_appears_only_above_the_leaf():
    """At the leaf every row is one strategy, and a column of 1s is noise."""
    grid = ChartPointsGrid()
    grid.update(
        _points_frame(counts=(1, 1)),
        level_label="Strategy",
        value_label="1Y Sharpe",
        fmt=".2f",
    )
    assert "Count" not in grid.widget.df.columns

    grid.update(
        _points_frame(counts=(4, 1)),
        level_label="Category",
        value_label="1Y Sharpe",
        fmt=".2f",
    )
    assert "Count" in grid.widget.df.columns


def test_a_points_row_click_hands_over_the_whole_row():
    picked: list[pd.Series] = []
    grid = ChartPointsGrid(on_pick=picked.append)
    grid.update(
        _points_frame(), level_label="Category", value_label="1Y Sharpe", fmt=".2f"
    )
    # Sorted descending, so row 0 is Fixed Income.
    grid._forward_pick({"new": [0]})
    assert picked and picked[0]["label"] == "Fixed Income"
    assert picked[0]["path"] == ("Fixed Income",)


def test_a_points_deselection_and_a_stale_row_do_nothing():
    picked: list[pd.Series] = []
    grid = ChartPointsGrid(on_pick=picked.append)
    grid.update(
        _points_frame(), level_label="Category", value_label="1Y Sharpe", fmt=".2f"
    )
    grid._forward_pick({"new": []})  # deselection
    grid._forward_pick({"new": [99]})  # a re-render landed between click and callback
    assert picked == []


def test_a_group_row_narrows_and_a_strategy_row_opens_single_strategy():
    """#331 decision 19 — `count` routes it, not the level: a row that stands
    for one strategy IS that strategy, whatever depth the chart is drawn at."""
    opened: list[str] = []
    pa = _analytics(on_open_strategy=opened.append)
    pa.state.arp_universe_prices = pd.DataFrame()
    pa.wire(lambda: pd.DataFrame())

    pa._pick_point(_points_frame().loc["Equity"])  # count 3 → narrow
    assert pa.drill.scope == ("Equity",)
    assert opened == []

    pa._pick_point(_points_frame().loc["Fixed Income"])  # count 1 → open
    assert opened == ["Fixed Income"]


def test_the_points_table_follows_every_chart_render():
    pa = _analytics()
    pa.state.arp_universe_prices = pd.DataFrame()
    seen: list[str] = []
    pa.render_points = lambda: seen.append(pa.active_analytics)  # type: ignore

    pa.fresh.update({"icicle", "scatter", "strip"})
    pa.activate(pd.DataFrame(), "scatter")
    assert seen == ["scatter"]


def test_chart_and_table_stand_at_one_height():
    """#331 decision 7 — stretching would let whichever box holds more content
    set the row (the #298 lesson)."""
    from src.style import ANALYTICS_HEIGHT, ANALYTICS_TABLE_WIDTH

    pa = _analytics()
    chart_box, points_box = pa.card.children[2].children
    assert chart_box.layout.height == ANALYTICS_HEIGHT
    assert points_box.layout.height == ANALYTICS_HEIGHT
    # A wide chart pushes nothing off: it takes the remaining width and its
    # own content scrolls inside it (the #280 pair).
    assert chart_box.layout.flex == "1 1 0%"
    assert chart_box.layout.min_width == "0"
    assert points_box.layout.flex == f"0 0 {ANALYTICS_TABLE_WIDTH}"


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
    methods = {"icicle": "render_icicle", "scatter": "render_scatter"}

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
    assert pa.chart_box.children == (pa.scatter.fig,)
    pa.activate(pd.DataFrame(), "strip")
    assert pa.chart_box.children == (pa.strip.fig,)


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
