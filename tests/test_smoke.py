"""End-to-end smoke test — the regression guard for the whole v0.6.0 refactor.

`build_app()` must render the full dashboard on the deterministic mock-price
fallback (no Bloomberg session: `bql` isn't importable here, so
`src/bql_client.py` falls back to `_mock_prices`) and return the expected
top-level widget tree. If a later refactor breaks construction or reshuffles
the layout, this fails loudly instead of leaving the UI silently empty.
"""

from __future__ import annotations

import ipywidgets as W
from src.config import leaderboard_window_days
from src.layout import build_app
from src.layout.chrome import _render_overlay
from src.layout.html import STYLE_CTX, render_template
from src.style import Color


def test_build_app_renders_expected_tree():
    app = build_app(verbose=False)

    # Top-level container.
    assert isinstance(app, W.VBox)

    # injected CSS, banner, status toast, commentary, top tab bar, tab content,
    # perf disclaimer, legal disclosure, loading overlay, selection-cap popup —
    # 10 children in this order (see builder.py). The leading W.HTML is the
    # global stylesheet (`_app_css()`); the trailing two W.HTMLs are the
    # `.bbg-overlay` (Workstream C) and the `.bbg-limit-popup` (v0.9.13 #181).
    children = app.children
    assert len(children) == 10
    (
        css,
        banner,
        status,
        commentary,
        tab_bar,
        tab_content,
        perf_disc,
        legal,
        overlay,
        limit_popup,
    ) = children
    assert isinstance(css, W.HTML)
    assert "<style" in css.value
    assert isinstance(banner, W.HBox)
    assert isinstance(status, W.HTML)
    assert isinstance(commentary, W.VBox)
    assert isinstance(tab_bar, W.HBox)
    assert isinstance(perf_disc, W.HTML)
    assert isinstance(legal, W.HTML)
    assert isinstance(overlay, W.HTML)
    # On the mock-price path the load succeeds, so the overlay is dismissed.
    assert "is-hidden" in overlay.value
    # The selection-cap popup starts hidden (shown only on an over-cap pick).
    assert isinstance(limit_popup, W.HTML)
    assert "is-hidden" in limit_popup.value


def test_platform_panel_has_zscore_controls_and_factor_scatter():
    # The catalog's whole control set, in one bar above the table: Group by,
    # then the ranking Metric (Sharpe by default), then the Window the score is
    # measured over. It was Metric/Window/Lookback in a rail (#279); #324 fixed
    # the sample at five years and handed the window to the bar, #325 moved the
    # Metric in after it, and #326 removed the emptied rail — so the table now
    # runs the full width. The three analytics charts live in one boxed
    # "Platform analytics" card with inner pill-tabs sharing the lookback
    # toggle (sunburst default tab).
    import plotly.graph_objects as go
    from itables.widget import ITable
    from src.config import RANKABLE_METRICS, stat_windows
    from src.layout.rails import ChipGroup, MultiChipGroup

    app = build_app(verbose=False)
    platform_panel = app.children[5].children[0]  # tab_content → active panel
    assert isinstance(platform_panel, W.VBox)
    # Header, the control bar, the table itself, the card — no row between.
    universe_header, table_bar, table, analytics_card = platform_panel.children
    assert isinstance(table, ITable)
    assert table.layout.width == "100%"
    bar_chips = [
        chips
        for block in table_bar.children
        for chips in getattr(block, "children", ())
        if isinstance(chips, ChipGroup | MultiChipGroup)
    ]
    assert [c.label for c in bar_chips if isinstance(c, ChipGroup)] == ["Sharpe", "1Y"]

    # The analytics card is a bordered box: header, the Chart view bar, then
    # the body = HBox[chart box]. The pill row, the 260px control column and
    # the shared Lookback toggle went in #333; the card's controls are chips
    # in one `control_bar`, the catalog table's own chrome.
    assert analytics_card._dom_classes == ("bbg-card",)
    _card_header, bar, drill_row, body = analytics_card.children
    assert "bbg-rail" in bar._dom_classes
    headings = [
        block.children[0].value
        for block in bar.children
        if "bbg-rail-block" in getattr(block, "_dom_classes", ())
    ]
    # Settings on the bar; the drill's *position* on its own strip below, the
    # breadcrumb leading it (v0.9.25).
    assert headings == ["Chart", "Metric", "Window", "Regime", "Solution"]
    assert "bbg-drill-bar" in drill_row._dom_classes
    drill_headings = [
        block.children[0].value
        for block in drill_row.children
        if "bbg-drill-block" in getattr(block, "_dom_classes", ())
    ]
    assert drill_headings == ["Scope", "Level"]
    assert not [w for w in _walk(analytics_card) if isinstance(w, W.ToggleButtons)]

    chart_box, points_box = body.children
    # The card's Metric and Window offer the table's option lists, so the two
    # surfaces can be read at different windows but cannot offer different
    # things (#331 decision 1).
    pa = analytics_card._analytics
    # The card draws ONE solution at a time (v0.9.27), and the chips offer
    # only the solutions the analytics universe actually contains — the
    # catalog's `Beta` is filtered out of it, and a chip for it would draw an
    # empty chart.
    assert [label for label, _ in pa.solution_chips.options] == [
        "ARP",
        "Alternative Risk Premia",
        "Smart Beta",
    ]
    assert [label for label, _ in pa.metric_chips.options] == [
        label for _key, label in RANKABLE_METRICS
    ]
    assert [label for label, _ in pa.card_window_chips.options] == [
        label for label, _years in stat_windows()
    ]
    # Solution is the base now, so it is not a depth to select.
    assert [label for label, _ in pa.level_chips.options] == [
        "Asset Class",
        "Category",
        "Family",
        "Strategy",
    ]

    icicle = chart_box.children[0]
    assert isinstance(icicle, go.FigureWidget)
    assert icicle.data and isinstance(icicle.data[0], go.Icicle)
    # Sized by count: every leaf is one strategy, so the root totals the
    # catalog rather than a sum of |z| (#331 decision 8).
    assert set(icicle.data[0].values) >= {1.0}

    # The third chart is the Strip: five dates of 1D returns, the only view on
    # the card that can draw *this week*. The 3D factor scatter that was the
    # third pill merged into the Scatter in #335, Mesh3d planes and all.
    pa.chart_chips.value = "strip"
    assert chart_box.children[0] is pa.strip.fig
    # Five date columns of 1D returns, drawn as markers the kernel can index.
    assert pa.strip.fig.data
    assert all(isinstance(t, go.Scatter) for t in pa.strip.fig.data)


def test_regime_analysis_section_conditions_live():
    # The Regime analysis chart is the middle tab of the Platform analytics card:
    # a single regime-conditioned risk/return scatter (no Correlation sub-tab —
    # that lives in Multi-Strategy). Volatility uses fixed VIX-level buckets;
    # Trend / Rate-level split a live indicator into terciles, with each carrying
    # a conditional indicator-source dropdown.
    import plotly.graph_objects as go

    app = build_app(verbose=False)
    platform_panel = app.children[5].children[0]
    analytics_card = platform_panel.children[-1]  # the analytics card is last (#279)
    body = analytics_card.children[3]
    pa = analytics_card._analytics
    pa.chart_chips.value = "scatter"  # the Regime section shows on the Scatter
    # The regime is **opt-in** since v0.9.33: unticked, the Scatter is the
    # plain factor view over the whole Window and the controls that describe a
    # bucket are hidden. Everything below is about the conditioned view, so
    # tick it on first.
    assert pa.regime.on.value is False
    assert pa.regime.types.layout.display == "none"
    pa.regime.on.value = True

    chart_box, _points_box = body.children
    # Type and Bucket are chips since #333; Source stays a dropdown because its
    # options are a long live list (#331 decision 13).
    regime_type, bucket_dd = pa.regime.types, pa.regime.buckets
    selector_dd = pa.regime.source
    assert [label for label, _ in regime_type.options] == [
        "Volatility",
        "Trend",
        "Rate-level",
    ]
    assert regime_type.value == "Volatility"
    # Volatility: fixed VIX buckets (≥35 dropped, second-highest uncapped), no
    # indicator-source dropdown.
    assert [lbl for lbl, _ in bucket_dd.options] == [
        "VIX < 15",
        "15 ≤ VIX < 25",
        "VIX ≥ 25",
    ]
    assert selector_dd.layout.display == "none"

    # One 3D scatter since #335: Y the metric, X the term-premium β, Z the
    # equity-risk-premium β, all over the bucket's days. The regime view and
    # the factor view were two charts answering halves of one question.
    scatter_fig = chart_box.children[0]
    assert isinstance(scatter_fig, go.FigureWidget)
    assert scatter_fig.data
    assert all(isinstance(t, go.Scatter3d) for t in scatter_fig.data)
    assert not [t for t in scatter_fig.data if isinstance(t, go.Mesh3d)]
    vol_bucketed = [tuple(t.y) for t in scatter_fig.data]

    # Trend: a benchmark dropdown appears, buckets become terciles, and the
    # conditioning visibly changes the scatter (no traceback).
    regime_type.value = "Trend"
    assert selector_dd.layout.display == ""
    assert [key for _, key in bucket_dd.options] == ["low", "mid", "high"]
    assert scatter_fig.data
    trend_low = [tuple(t.y) for t in scatter_fig.data]
    assert trend_low != vol_bucketed
    bucket_dd.value = "high"
    assert [tuple(t.y) for t in scatter_fig.data] != trend_low

    # Rate-level: a region dropdown (US / EU / JP) appears with terciles.
    regime_type.value = "Rate-level"
    assert selector_dd.layout.display == ""
    assert [lbl for lbl, _ in selector_dd.options] == [
        "US (FEDL01)",
        "EU (EONIA)",
        "JP (MUTKCALM)",
    ]
    assert [key for _, key in bucket_dd.options] == ["low", "mid", "high"]
    assert scatter_fig.data


def test_universe_includes_smart_beta_solution():
    # v0.8.9: the dashboard universe now spans ARP + Smart Beta + Risk Management
    # solutions (plain "Beta" stays excluded).
    from src.config import UNIVERSE_SOLUTION_VALUES
    from src.data import load_metadata

    assert {"smart beta", "risk management"} <= UNIVERSE_SOLUTION_VALUES
    meta = load_metadata()
    universe = meta[
        meta["solution"].astype(str).str.lower().isin(UNIVERSE_SOLUTION_VALUES)
    ]
    sols = set(universe["solution"].astype(str).str.lower())
    assert "smart beta" in sols  # Smart Beta indices now enter the universe
    assert "beta" not in sols  # plain Beta stays excluded


def test_startup_selects_top_zscore_and_populates_multi_strategy():
    # The Multi-Strategy views load populated on startup (no manual Refresh): the
    # default selection is the top indices by z(1W Sharpe, 1Y), capped at the
    # universe size, so the selected-strategy grid + panes render with data.
    import plotly.graph_objects as go
    from src.bql_client import default_window, fetch_prices
    from src.config import (
        TRADING_DAYS_PER_YEAR,
        UNIVERSE_SOLUTION_VALUES,
        WEEK_WINDOW,
    )
    from src.data import load_metadata
    from src.stats import rolling_metric_zscore

    app = build_app(verbose=False)
    ms = next(
        b
        for b in app.children[4].children
        if isinstance(b, W.Button) and "Multi-Strategy" in b.description
    )
    ms.click()
    panel = app.children[5].children[0]
    from src.layout.basket import BasketCards

    basket = next(w for w in _walk(panel) if isinstance(w, BasketCards)).basket

    # Expected: the top-5 (capped) by z(1W Sharpe, 1Y) over the fetched universe.
    meta = load_metadata()
    meta = meta[meta["solution"].astype(str).str.lower().isin(UNIVERSE_SOLUTION_VALUES)]
    start, end = default_window(5)
    px, _ = fetch_prices(list(meta["ticker"]), start, end)
    z = rolling_metric_zscore(
        px, metric="sharpe", window=WEEK_WINDOW, zscore_window=TRADING_DAYS_PER_YEAR
    ).dropna()
    expected = set(z.nlargest(5).index)
    assert set(basket.value) == expected
    assert 1 <= len(basket.value) <= 5

    # **No perf grid under the table** (v0.9.30): it was a second table of the
    # same strategies below the catalog, whose numbers the catalog already
    # shows per row.
    assert not [w for w in _walk(panel) if w.__class__.__name__ == "DataGrid"]
    # Both panes' mounted figures carry data with nothing to click.
    figs = [w for w in _walk(panel) if isinstance(w, go.FigureWidget)]
    assert sum(1 for f in figs if f.data) >= 1


def test_single_strategy_picks_from_the_catalog_table():
    """The Single Strategy tab renders its picker, and the v0.8 idiom is gone.

    What this replaced was `test_quant_zscore_row_has_window_dropdown`, which
    pinned the Quantitative filter's cross-sectional Z row — a `≥ / ≤`
    threshold typed against a number that appeared nowhere on screen. #345
    retired the Multi tab's copy and #365 the last one with `FilterPanel`
    itself; the catalog's ranking column is where a ranking lives now.
    """
    from src.layout.builder import DashboardApp
    from src.layout.rails import (
        FILTER_BAR_TITLE,
        FILTER_DIMENSION_HEADING,
        FILTER_VALUES_HEADING,
        TABLE_BAR_TITLE,
    )

    # The controller rather than `build_app`'s root: the assertions below are
    # about the pick, which is an object on the panel and not a widget in the
    # tree — that is the point of #363 dec. 2.
    controller = DashboardApp(verbose=False)
    app = controller.root
    single = next(
        b
        for b in app.children[4].children
        if isinstance(b, W.Button) and "Single Strategy" in b.description
    )
    single.click()
    panel = app.children[5].children[0]

    # No accordion anywhere on the tab — the last one in the app.
    assert not [w for w in _walk(panel) if isinstance(w, W.Accordion)]

    # The two bars, headed as the Multi-Strategy tab heads them. Read through
    # the constants rather than spelled, so a relabel reaches both tabs.
    headings = {w.value for w in _walk(panel) if isinstance(w, W.HTML) and w.value}
    text = " ".join(headings)
    for word in (
        TABLE_BAR_TITLE,
        FILTER_BAR_TITLE,
        FILTER_DIMENSION_HEADING,
        FILTER_VALUES_HEADING,
        "Group by",
        "Window",
        "Benchmark",
    ):
        assert word in text, f"the picker's bars are missing {word!r}"

    # And the picker is the catalog table, with a row for every index.
    grid = controller.single_strategy.grid
    assert set(grid._tickers) == set(controller.meta["ticker"])
    # Opened on a strategy rather than on an empty card.
    picked = controller.single_strategy.pick.value
    assert picked in set(grid._tickers)
    assert grid.tickers_at(grid.widget.selected_rows) == [picked]


def test_the_retired_filter_panel_is_gone_from_src():
    """#363 dec. 3 / #365: `FilterPanel` and its parts leave the tree.

    A grep guard rather than an import check, because the failure this
    prevents is a *reintroduction* — a second kernel-side categorical filter
    growing back beside the Filter bar that replaced it.
    """
    from pathlib import Path

    assert not Path("src/layout/filter_panel.py").exists()
    sources = " ".join(p.read_text() for p in Path("src").rglob("*.py"))
    for name in (
        "class FilterPanel",
        "class QuantFilter",
        "class CategoricalFilter",
        "def make_filter_panel",
        "def _q_row",
        "def _checkbox_group",
    ):
        assert name not in sources, f"{name} should have gone with #365"


def _walk(widget):
    """Yield the widget and all its descendants (children / .child)."""
    yield widget
    for child in getattr(widget, "children", ()):
        yield from _walk(child)


def test_analysis_date_range_is_two_boxes_no_slider():
    # v0.7.5 Workstream B: the analysis date range is two DatePicker boxes
    # (hyphen-separated), no SelectionRangeSlider. The Multi-Strategy panel
    # mounts only when its tab is selected, so click that tab first.
    app = build_app(verbose=False)
    tab_bar = app.children[4]
    ms_btn = next(
        b
        for b in tab_bar.children
        if isinstance(b, W.Button) and "Multi-Strategy" in b.description
    )
    ms_btn.click()
    panel = app.children[5].children[0]  # tab_content → mounted Multi-Strategy
    widgets = list(_walk(panel))
    assert not any(isinstance(w, W.SelectionRangeSlider) for w in widgets)
    # The two analysis-range boxes + the Characteristics launch-date pair are
    # DatePickers, so at least two exist with the slider class absent.
    assert sum(isinstance(w, W.DatePicker) for w in widgets) >= 2


def test_correlation_benchmark_regime_controls():
    # v0.7.5 Workstream C: a pane exposes a Benchmark checkbox and a nested
    # Regime checkbox; the tail-direction control is a >/< dropdown whose values
    # map straight to regime_corr_matrix's direction ("<" worst, ">" best).
    from src.layout.panes import _make_analysis_pane

    pane = _make_analysis_pane("left")
    assert isinstance(pane.heat_benchmark_chk, W.Checkbox)
    assert pane.heat_benchmark_chk.description == "Benchmark"
    assert isinstance(pane.heat_regime_chk, W.Checkbox)
    assert pane.heat_regime_chk.description == "Regime"
    assert isinstance(pane.heat_dir, W.Dropdown)
    assert dict(pane.heat_dir.options) == {"<": "down", ">": "up"}

    # Benchmark off → benchmark dropdown + Regime checkbox hidden; ticking
    # Benchmark reveals them; ticking Regime reveals the >/< + tail controls.
    assert pane.heat_dd.layout.display == "none"
    pane.picker.value = "Correlation Heatmap"
    pane.heat_benchmark_chk.value = True
    assert pane.heat_dd.layout.display == ""
    assert pane.heat_regime_chk.layout.display == ""
    assert pane.heat_dir.layout.display == "none"
    pane.heat_regime_chk.value = True
    assert pane.heat_dir.layout.display == ""
    # Unticking Benchmark clears Regime so the chart reverts to plain.
    pane.heat_benchmark_chk.value = False
    assert pane.heat_regime_chk.value is False


def test_the_commentary_block_is_the_leaderboard_beside_the_switchable_pane():
    # v0.9.20 (#290): the block above the tab bar is two panes side by side —
    # the ranked leaderboard on the left under its window toggle, the
    # Commentary / New Launches pane on the right. The 16-card Market
    # 16-card board it replaced must be nowhere on screen.
    from src.layout.rails import ChipGroup

    app = build_app(verbose=False)
    commentary_box = app.children[3]
    widgets = list(_walk(commentary_box))

    boards = [w for w in widgets if "bbg-leaderboard" in getattr(w, "_dom_classes", ())]
    panes = [
        w for w in widgets if "bbg-commentary-pane" in getattr(w, "_dom_classes", ())
    ]
    assert len(boards) == 1
    assert len(panes) == 1

    # The window control lives with the leaderboard, as chips in the section's
    # bar since #306 — the same idiom as the Platform tab rather than a third
    # one. It gained 1Y when the board started scoring against five years of
    # history (#310), and 1D in v0.9.40.
    chips = next(
        w
        for w in widgets
        if isinstance(w, ChipGroup)
        and [label for label, _ in w.options] == ["1D", "1W", "1M", "3M", "6M", "1Y"]
    )
    labels = [w.value for w in widgets if isinstance(w, W.HTML)]
    assert any("Leaderboard" in (v or "") for v in labels)
    assert any("Window" in (v or "") for v in labels)
    # The default, read from config rather than typed — it moved from a
    # month to a week in #384, and a literal here is what made that a
    # two-file change instead of one.
    assert chips.value == leaderboard_window_days()

    # No trace of the retired board survives anywhere in the app — #291 took
    # the cards, the two templates and the stylesheet rule with it.
    rendered = [w for w in _walk(app) if isinstance(w, W.HTML)]
    assert rendered  # the sweep is not vacuous
    assert not any("bbg-superlative" in (w.value or "") for w in rendered)


def test_the_error_strip_sits_outside_both_panes():
    # It was split out of the highlights widget in v0.8.x so a live control
    # could not wipe an init error. Inside either pane it would be back in
    # range of the window toggle or the pane switch.
    app = build_app(verbose=False)
    commentary_box = app.children[3]
    board = next(
        w
        for w in _walk(commentary_box)
        if "bbg-leaderboard" in getattr(w, "_dom_classes", ())
    )
    pane = next(
        w
        for w in _walk(commentary_box)
        if "bbg-commentary-pane" in getattr(w, "_dom_classes", ())
    )
    errors_w = commentary_box.children[0]
    assert errors_w not in list(_walk(board))
    assert errors_w not in list(_walk(pane))


def test_masthead_renders():
    app = build_app(verbose=False)
    banner = app.children[1]
    # The masthead HBox opts into the dark `.bbg-masthead` chrome class.
    assert "bbg-masthead" in banner._dom_classes
    # Its trailing HTML child holds the title block; tokens must be substituted.
    masthead_html = banner.children[-1].value
    assert "Index Catalog Dashboard" in masthead_html
    assert "32px" in masthead_html  # FontSize.TITLE
    assert "{{" not in masthead_html


def test_build_app_reports_successful_load():
    app = build_app(verbose=False)
    status_html = app.children[2].value
    # Success states read "Loaded N indices …"; failure reads "Load failed".
    assert "Loaded" in status_html
    assert "Load failed" not in status_html


def test_render_overlay_substitutes():
    html_str = _render_overlay(60, "Fetching prices for 12 indices…")
    assert "width:60%" in html_str
    assert "60%" in html_str
    assert "Fetching prices" in html_str
    assert "bbg-overlay" in html_str
    assert "bbg-progress" in html_str
    assert "{{" not in html_str


def test_render_overlay_states():
    assert "is-error" in _render_overlay(60, "Load failed", error=True)
    assert "is-hidden" in _render_overlay(100, "Ready", hidden=True)


def test_app_css_has_overlay_and_toast_rules():
    css = render_template("app_css", **STYLE_CTX)
    for rule in (".bbg-overlay", ".bbg-progress", ".bbg-toast"):
        assert rule in css
    assert Color.ACCENT.value in css  # accent token substituted
    assert "{{" not in css


def test_app_css_plotly_backdrop_is_transparent():
    # Charts render transparent (theme._chart_layout) so the themed card shows
    # through. The plotly backdrop CSS must force the wrapper DIVs / SVG layers
    # transparent to defeat the FigureWidget theme-following default background
    # (plotly.py #3811), AND force the paper `.bg` rect transparent so a remount
    # (Stack view swap) can't redraw it with the plotly_dark dark paper color.
    css = render_template("app_css", **STYLE_CTX)
    assert ".js-plotly-plot" in css
    # Isolate the plotly backdrop section (up to the next CSS section).
    start = css.find(".bbg-app .js-plotly-plot")
    block = css[start : css.find("Workstream D", start)]
    # Wrapper + SVG-layer background is transparent — never an opaque color
    # (an opaque `.main-svg` background hides the chart's plotted data).
    assert "background: transparent !important" in block
    assert str(Color.CHROME_BG) not in block  # no opaque backdrop leaked in
    assert str(Color.CHART_BG) not in block
    # Every plotly background rect (paper + subplot + legend) fill is forced
    # transparent, so a remount can't redraw them with the plotly_dark dark
    # colors (the revisit-goes-dark fix, incl. legend / plot-area backgrounds).
    assert ".main-svg .bg" in block
    assert "fill: transparent !important" in block


def test_tab_button_classes():
    from src.layout.chrome import _make_tab_button, _style_tab_button

    active = _make_tab_button("X", active=True)
    assert "bbg-pill" in active._dom_classes
    assert "is-active" in active._dom_classes

    inactive = _make_tab_button("Y", active=False)
    assert "bbg-pill" in inactive._dom_classes
    assert "is-active" not in inactive._dom_classes

    # State is a class toggle, not inline `.style`.
    _style_tab_button(active, active=False)
    assert "is-active" not in active._dom_classes
    _style_tab_button(inactive, active=True)
    assert "is-active" in inactive._dom_classes


def test_app_css_has_button_and_control_rules():
    css = render_template("app_css", **STYLE_CTX)
    for rule in (".bbg-btn", ".bbg-btn-secondary", ".bbg-pill", ".bbg-app select"):
        assert rule in css
    assert "#16a34a" in css  # Color.GREEN_600 (primary button), substituted
    assert "{{" not in css


def test_dark_grid_style():
    from src.layout.grids import _dark_grid_style

    gs = _dark_grid_style()
    assert gs["background_color"] == Color.CHROME_BG.value
    assert gs["header_background_color"] == Color.SURFACE.value
    assert gs["grid_line_color"] == Color.BORDER.value


def test_grids_are_dark_themed():
    # The ipydatagrid grids theme their canvas through the `grid_style` API.
    # The all-catalog grid is an `itables` table and is themed by page CSS
    # instead — see `test_catalog_grid_carries_the_chrome_hook`, which is also
    # how the Single Strategy metrics table and calendar are themed since
    # #366 replaced their two canvases with HTML.
    from src.layout.grids import PerfGrid

    grid = PerfGrid().grid
    assert grid.grid_style["background_color"] == Color.CHROME_BG.value
    assert grid.header_renderer.text_color == Color.TEXT.value
    assert "bbg-grid" in grid._dom_classes


def test_the_html_tables_carry_their_chrome_hooks():
    """The metrics table and the calendar are themed by page CSS (#366).

    Same contract as the catalog table's: the class is what the stylesheet
    hangs off, so it is part of the contract rather than decoration — and the
    stylesheet has to actually define it.
    """
    from src.config import TEMPLATES_DIR

    css = (TEMPLATES_DIR / "app_css.html").read_text(encoding="utf-8")
    for name in ("strategy_metrics", "calendar"):
        markup = (TEMPLATES_DIR / f"{name}.html").read_text(encoding="utf-8")
        hook = "bbg-metrics" if name == "strategy_metrics" else "bbg-calendar"
        assert f"class='{hook}'" in markup
        assert f".{hook}" in css


def test_catalog_grid_carries_the_chrome_hook():
    # The dark chrome reaches the catalog table only if the CSS selector has
    # something to hang off, so the class is part of the contract rather than
    # decoration — and the stylesheet must actually define it.
    from src.config import TEMPLATES_DIR
    from src.layout.grids import CATALOG_TABLE_CLASS, UniverseGrid

    assert CATALOG_TABLE_CLASS in UniverseGrid().widget._dom_classes
    css = (TEMPLATES_DIR / "app_css.html").read_text(encoding="utf-8")
    assert f".{CATALOG_TABLE_CLASS}" in css
