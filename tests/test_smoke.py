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
from src.layout.html import STYLE_CTX, render_template


def test_build_app_renders_expected_tree():
    app = build_app(verbose=False)

    # Top-level container.
    assert isinstance(app, W.VBox)

    # injected CSS, banner, status toast, commentary, top tab bar, tab content,
    # perf disclaimer, legal disclosure, loading overlay — 9 children in this
    # order (see builder.py). The leading W.HTML is the global stylesheet
    # (`_app_css()`); the trailing W.HTML is the `.bbg-overlay` (Workstream C).
    children = app.children
    assert len(children) == 9
    css, banner, status, commentary, tab_bar, tab_content, perf_disc, legal, overlay = (
        children
    )
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


def test_platform_panel_has_zscore_controls_and_factor_scatter():
    # v0.7.0 Workstream A: a Z-Score control row (Metric/Window/Lookback) above
    # the grid, defaulting to z(1M Sharpe, 1Y). Workstream C+D: a 6M/1Y/3Y/5Y
    # lookback ToggleButtons + the factor-beta scatter FigureWidget below it.
    import plotly.graph_objects as go

    app = build_app(verbose=False)
    platform_panel = app.children[5].children[0]  # tab_content → active panel
    assert isinstance(platform_panel, W.VBox)
    (
        header,
        controls,
        grid,
        lookback_row,
        scatter_header,
        scatter,
        treemap_header,
        treemap,
    ) = platform_panel.children
    dropdowns = [c for c in controls.children if isinstance(c, W.Dropdown)]
    assert [d.label for d in dropdowns] == ["Sharpe", "1M", "1Y"]
    # Shared lookback selector (defaults to 1Y) + scatter + treemap figures.
    toggles = [c for c in lookback_row.children if isinstance(c, W.ToggleButtons)]
    assert len(toggles) == 1
    assert toggles[0].label == "1Y"
    assert isinstance(scatter, go.FigureWidget)
    assert isinstance(treemap, go.FigureWidget)
    # v0.7.1: the scatter is 3D (Scatter3d traces) with no in-figure title.
    assert scatter.data and all(isinstance(tr, go.Scatter3d) for tr in scatter.data)
    assert not scatter.layout.title.text


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
    assert "#FFA000" in css  # Color.ACCENT, tokens substituted
    assert "{{" not in css


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
    assert gs["background_color"] == "#0d1117"  # Color.CHROME_BG
    assert gs["header_background_color"] == "#161b22"  # Color.SURFACE
    assert gs["grid_line_color"] == "#30363d"  # Color.BORDER


def test_grids_are_dark_themed():
    from src.layout.grids import _perf_grid, _universe_grid

    for grid in (_perf_grid(), _universe_grid()):
        assert grid.grid_style["background_color"] == "#0d1117"
        assert grid.header_renderer.text_color == "#e6edf3"  # Color.TEXT
        assert "bbg-grid" in grid._dom_classes
