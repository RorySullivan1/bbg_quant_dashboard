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


def test_build_app_renders_expected_tree():
    app = build_app(verbose=False)

    # Top-level container.
    assert isinstance(app, W.VBox)

    # injected CSS, banner, status, commentary, top tab bar, tab content, perf
    # disclaimer, legal disclosure — 8 children in this order (see builder.py).
    # The leading W.HTML is the global stylesheet mounted by `_app_css()`.
    children = app.children
    assert len(children) == 8
    css, banner, status, commentary, tab_bar, tab_content, perf_disc, legal = children
    assert isinstance(css, W.HTML)
    assert "<style" in css.value
    assert isinstance(banner, W.HBox)
    assert isinstance(status, W.HTML)
    assert isinstance(commentary, W.VBox)
    assert isinstance(tab_bar, W.HBox)
    assert isinstance(perf_disc, W.HTML)
    assert isinstance(legal, W.HTML)


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
