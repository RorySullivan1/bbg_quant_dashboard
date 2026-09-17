"""End-to-end smoke test — the regression guard for the whole v0.6.0 refactor.

`build_app()` must render the full dashboard on the deterministic mock-price
fallback (no Bloomberg session: `bql` isn't importable here, so
`src/bql_client.py` falls back to `_mock_prices`) and return the expected
top-level widget tree. If a later refactor breaks construction or reshuffles
the layout, this fails loudly instead of leaving the UI silently empty.
"""

from __future__ import annotations

import ipywidgets as W
from src.layout import build_app
from src.layout.chrome import _render_overlay
from src.layout.filters import CheckboxMultiSelect
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
    # v0.7.0 Workstream A: a Z-Score control row (Metric/Window/Lookback) above
    # the grid, defaulting to z(1M Sharpe, 1Y). The three analytics charts now
    # live in one boxed "Platform analytics" card with inner pill-tabs sharing
    # the lookback toggle (sunburst default tab).
    import plotly.graph_objects as go

    app = build_app(verbose=False)
    platform_panel = app.children[5].children[0]  # tab_content → active panel
    assert isinstance(platform_panel, W.VBox)
    # Grid group (header + z-score controls + grid) then the analytics card.
    universe_header, controls, grid, analytics_card = platform_panel.children
    dropdowns = [c for c in controls.children if isinstance(c, W.Dropdown)]
    assert [d.label for d in dropdowns] == ["Sharpe", "1M", "1Y"]

    # The analytics card is a bordered box: header, tab bar (pills only), then
    # the body = HBox[left control column, chart box].
    assert analytics_card._dom_classes == ("bbg-card",)
    _card_header, tab_bar, body = analytics_card.children
    pills = [c for c in tab_bar.children if isinstance(c, W.Button)]
    assert [p.description for p in pills] == [
        "Sunburst",
        "Regime analysis",
        "Factor exposures",
    ]
    assert [p.description for p in pills if "is-active" in p._dom_classes] == [
        "Sunburst"
    ]
    left_col, chart_box = body.children
    # The shared lookback toggle (defaults to 1Y) sits at the TOP of the left
    # control column, above the active tab's controls box.
    toggles = [c for c in left_col.children if isinstance(c, W.ToggleButtons)]
    assert len(toggles) == 1 and toggles[0].label == "1Y"
    tab_controls_box = left_col.children[-1]

    # Default tab = sunburst: the controls box stacks Metric + Window (the
    # lookback above is shared); the figure fills the rest with a Sunburst trace.
    sb_dds = [
        c for c in tab_controls_box.children[0].children if isinstance(c, W.Dropdown)
    ]
    assert [d.label for d in sb_dds] == ["Sharpe", "1W"]
    sunburst = chart_box.children[0]
    assert isinstance(sunburst, go.FigureWidget)
    assert sunburst.data and isinstance(sunburst.data[0], go.Sunburst)

    # Factor exposures tab: chart swaps to the 3D scatter (Scatter3d markers +
    # the three Mesh3d zero planes); its controls box is empty (lookback only).
    pills[2].click()
    assert len(tab_controls_box.children[0].children) == 0
    scatter = chart_box.children[0]
    assert isinstance(scatter, go.FigureWidget)
    assert [tr for tr in scatter.data if isinstance(tr, go.Scatter3d)]
    planes = {tr.name for tr in scatter.data if isinstance(tr, go.Mesh3d)}
    assert planes == {"x=0", "y=0", "z=0"}
    assert not scatter.layout.title.text


def test_regime_analysis_section_conditions_live():
    # The Regime analysis chart is the middle tab of the Platform analytics card:
    # a single regime-conditioned risk/return scatter (no Correlation sub-tab —
    # that lives in Multi-Strategy). Volatility uses fixed VIX-level buckets;
    # Trend / Rate-level split a live indicator into terciles, with each carrying
    # a conditional indicator-source dropdown.
    import plotly.graph_objects as go

    app = build_app(verbose=False)
    platform_panel = app.children[5].children[0]
    analytics_card = platform_panel.children[3]
    tab_bar, body = analytics_card.children[1], analytics_card.children[2]
    pills = [c for c in tab_bar.children if isinstance(c, W.Button)]
    pills[1].click()  # activate the Regime analysis tab

    left_col, chart_box = body.children
    tab_controls_box = left_col.children[-1]
    regime_dds = [
        c for c in tab_controls_box.children[0].children if isinstance(c, W.Dropdown)
    ]
    regime_type, selector_dd, bucket_dd = regime_dds
    assert list(regime_type.options) == [
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

    # The chart is a 2D risk/return scatter conditioned on the default VIX bucket.
    scatter_fig = chart_box.children[0]
    assert isinstance(scatter_fig, go.FigureWidget)
    assert scatter_fig.data
    assert all(
        isinstance(t, go.Scatter) and not isinstance(t, go.Scatter3d)
        for t in scatter_fig.data
    )
    vol_bucketed = [tuple(t.x) for t in scatter_fig.data]

    # Trend: a benchmark dropdown appears, buckets become terciles, and the
    # conditioning visibly changes the scatter (no traceback).
    regime_type.value = "Trend"
    assert selector_dd.layout.display == ""
    assert [key for _, key in bucket_dd.options] == ["low", "mid", "high"]
    assert scatter_fig.data
    trend_low = [tuple(t.x) for t in scatter_fig.data]
    assert trend_low != vol_bucketed
    bucket_dd.value = "high"
    assert [tuple(t.x) for t in scatter_fig.data] != trend_low

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
    ticker_w = next(w for w in _walk(panel) if isinstance(w, CheckboxMultiSelect))

    # Expected: the top-5 (capped) by z(1W Sharpe, 1Y) over the fetched universe.
    meta = load_metadata()
    meta = meta[meta["solution"].astype(str).str.lower().isin(UNIVERSE_SOLUTION_VALUES)]
    start, end = default_window(5)
    px, _ = fetch_prices(list(meta["ticker"]), start, end)
    z = rolling_metric_zscore(
        px, metric="sharpe", window=WEEK_WINDOW, zscore_window=TRADING_DAYS_PER_YEAR
    ).dropna()
    expected = set(z.nlargest(5).index)
    assert set(ticker_w.value) == expected
    assert 1 <= len(ticker_w.value) <= 5

    # The selected-strategy perf grid is populated on load (one row per pick).
    grid = next(w for w in _walk(panel) if w.__class__.__name__ == "DataGrid")
    assert grid.data.shape[0] == len(ticker_w.value)
    # Both panes' mounted figures carry data without a Refresh click.
    figs = [w for w in _walk(panel) if isinstance(w, go.FigureWidget)]
    assert sum(1 for f in figs if f.data) >= 1


def test_quant_zscore_row_has_window_dropdown():
    # v0.8.11: the Quantitative Z-Score row carries a window dropdown
    # (1W/1M/3M/6M, default 1M) right after the base-metric dropdown — it sets the
    # lookback the base metric is computed over for the cross-sectional z-score.
    from src.config import MONTH_WINDOW

    z_metrics = [
        "Sharpe",
        "Sortino",
        "Calmar",
        "Beta",
        "Treynor",
        "Jensen",
        "VaR",
        "RSI",
    ]
    app = build_app(verbose=False)
    ms = next(
        b
        for b in app.children[4].children
        if isinstance(b, W.Button) and "Multi-Strategy" in b.description
    )
    ms.click()
    panel = app.children[5].children[0]
    # Activate the Quantitative filter pill so its metric rows mount.
    quant_pill = next(
        w
        for w in _walk(panel)
        if isinstance(w, W.Button) and w.description == "Quantitative"
    )
    quant_pill.click()

    # The Z-Score row's trailing HBox holds: <"of"> label, base-metric dd, window dd.
    trailing = next(
        hb
        for hb in _walk(panel)
        if isinstance(hb, W.HBox)
        and any(
            isinstance(c, W.Dropdown) and list(c.options) == z_metrics
            for c in hb.children
        )
        and any(
            isinstance(c, W.Dropdown)
            and [o[0] if isinstance(o, tuple) else o for o in c.options]
            == ["1W", "1M", "3M", "6M"]
            for c in hb.children
        )
    )
    dds = [c for c in trailing.children if isinstance(c, W.Dropdown)]
    metric_dd, window_dd = dds[0], dds[1]
    assert list(metric_dd.options) == z_metrics  # base metric first
    assert [o[0] for o in window_dd.options] == ["1W", "1M", "3M", "6M"]
    assert window_dd.value == MONTH_WINDOW  # defaults to 1M


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
    app = build_app(verbose=False)
    commentary_box = app.children[3]
    widgets = list(_walk(commentary_box))

    boards = [w for w in widgets if "bbg-leaderboard" in getattr(w, "_dom_classes", ())]
    panes = [
        w for w in widgets if "bbg-commentary-pane" in getattr(w, "_dom_classes", ())
    ]
    assert len(boards) == 1
    assert len(panes) == 1

    # The window toggle lives with the leaderboard, labelled for what it now
    # ranks rather than for the board it replaced.
    toggle = next(
        w
        for w in widgets
        if isinstance(w, W.ToggleButtons)
        and [o[0] for o in w.options] == ["1W", "1M", "3M", "6M"]
    )
    labels = [w.value for w in widgets if isinstance(w, W.HTML)]
    assert any("Ranking window" in (v or "") for v in labels)
    assert toggle.value == 21  # MONTH_WINDOW, the default

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
    # instead — see `test_catalog_grid_carries_the_chrome_hook`.
    from src.layout.grids import CalendarGrid, PerfGrid

    for owner in (PerfGrid(), CalendarGrid()):
        grid = owner.grid
        assert grid.grid_style["background_color"] == Color.CHROME_BG.value
        assert grid.header_renderer.text_color == Color.TEXT.value
        assert "bbg-grid" in grid._dom_classes


def test_catalog_grid_carries_the_chrome_hook():
    # The dark chrome reaches the catalog table only if the CSS selector has
    # something to hang off, so the class is part of the contract rather than
    # decoration — and the stylesheet must actually define it.
    from src.config import TEMPLATES_DIR
    from src.layout.grids import CATALOG_TABLE_CLASS, UniverseGrid

    assert CATALOG_TABLE_CLASS in UniverseGrid().widget._dom_classes
    css = (TEMPLATES_DIR / "app_css.html").read_text(encoding="utf-8")
    assert f".{CATALOG_TABLE_CLASS}" in css
