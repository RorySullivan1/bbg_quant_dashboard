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

    # banner, status, commentary, top tab bar, tab content, perf disclaimer,
    # legal disclosure — 7 children in this order (see builder.py).
    children = app.children
    assert len(children) == 7
    banner, status, commentary, tab_bar, tab_content, perf_disc, legal = children
    assert isinstance(banner, W.HBox)
    assert isinstance(status, W.HTML)
    assert isinstance(commentary, W.VBox)
    assert isinstance(tab_bar, W.HBox)
    assert isinstance(perf_disc, W.HTML)
    assert isinstance(legal, W.HTML)


def test_build_app_reports_successful_load():
    app = build_app(verbose=False)
    status_html = app.children[1].value
    # Success states read "Loaded N indices …"; failure reads "Load failed".
    assert "Loaded" in status_html
    assert "Load failed" not in status_html
