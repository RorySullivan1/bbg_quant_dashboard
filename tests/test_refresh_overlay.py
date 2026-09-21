"""The initial load's overlay (regression for the vanished loading screen).

`build_app` is synchronous: it displays the overlay, pushes staged progress as
each load step completes, then mounts the dashboard and dismisses it. These
drive the rendered widget tree and assert that path — headless and under a
forced frontend — plus the error branch, where a fatal fetch leaves the
overlay up in its red state and renders the traceback.

**The Refresh-prices half of this file went in v0.9.30**, with the button. It
covered the worker thread that kept the overlay painting while a refetch
blocked the kernel; nothing refetches any more, so the initial load is the
only thing the overlay serves.
"""

from __future__ import annotations

import threading

import ipywidgets as W
from src.layout import build_app


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _mount_multi_strategy(app) -> None:
    """Click the Multi-Strategy tab so its Refresh-prices button (and the rest
    of the panel) is mounted into the tree and reachable by ``_walk`` (the
    default mounted tab is Platform)."""
    btn = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Multi-Strategy"
    )
    btn.click()


def _refresh_button(app) -> W.Button:
    return next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Refresh prices"
    )


def _overlay(app) -> W.HTML:
    # The loading overlay is the trailing `.bbg-overlay` W.HTML in the app VBox.
    # Exclude the injected `<style>` block, whose CSS text also mentions
    # `.bbg-overlay` / `.is-hidden` and would otherwise match first.
    return next(
        w
        for w in _walk(app)
        if isinstance(w, W.HTML)
        and "bbg-overlay" in w.value
        and "<style" not in w.value
    )


def _toast(app) -> W.HTML:
    # The post-load summary toast (`.bbg-toast`), set on the initial load.
    return next(
        w
        for w in _walk(app)
        if isinstance(w, W.HTML) and "bbg-toast" in w.value and "<style" not in w.value
    )


def _patch_fetch_counter(monkeypatch):
    import src.layout.app as app_mod

    real_fetch = app_mod.fetch_prices
    calls = {"n": 0}

    def counting_fetch(*args, **kwargs):
        calls["n"] += 1
        return real_fetch(*args, **kwargs)

    monkeypatch.setattr(app_mod, "fetch_prices", counting_fetch)
    return calls


def _join_refresh_worker(timeout: float = 30.0) -> None:
    for t in threading.enumerate():
        if t.name == "bbg-refresh":
            t.join(timeout)


# --- initial load: must stay synchronous (deployed-app regression) ----------


def test_headless_initial_load_is_synchronous(monkeypatch):
    """With no frontend, `build_app()` runs the fetch + compute inline, so the
    returned tree is fully populated — the contract every other suite relies on.
    No worker thread lingers and the overlay is already dismissed."""
    calls = _patch_fetch_counter(monkeypatch)
    app = build_app(verbose=False)

    assert calls["n"] == 1  # the initial load fetched inline during build
    assert not any(t.name == "bbg-initial-load" for t in threading.enumerate())
    assert "is-hidden" in _overlay(app).value  # dismissed on the synchronous path


def test_initial_load_is_synchronous_under_a_live_frontend(monkeypatch):
    """Regression for the deployed-app failure: the **initial** load must stay
    synchronous even with a live frontend.

    Under Voila the notebook is executed to completion and the page is then
    assembled from the resulting output, so a `build_app()` that returns before
    the dashboard is populated serves an empty app stuck behind the loading
    overlay. `get_ipython()` is not None under Voila either, so it can't
    distinguish a notebook (threading harmless) from a Voila render (fatal) —
    the initial load therefore never threads."""
    import src.layout.app as app_mod

    monkeypatch.setattr(app_mod, "get_ipython", lambda: object())
    monkeypatch.setattr(app_mod, "display", lambda *a, **k: None)
    calls = _patch_fetch_counter(monkeypatch)

    app = build_app(verbose=False)

    # `build_app` returned only after the load completed: no worker thread, the
    # fetch already happened, and the overlay is dismissed.
    assert not any(t.name == "bbg-initial-load" for t in threading.enumerate())
    assert calls["n"] == 1
    assert "is-hidden" in _overlay(app).value


def test_dismissed_overlay_is_hidden_without_relying_on_css(monkeypatch):
    """The overlay must be dismissed at the widget-layout level too.

    `.bbg-overlay.is-hidden` only sets `opacity: 0`, so if the injected
    stylesheet isn't applied the overlay would stay fully opaque at
    `z-index: 9999` and hide the whole (successfully loaded) dashboard."""
    app = build_app(verbose=False)
    overlay = _overlay(app)
    assert "is-hidden" in overlay.value  # CSS-level dismissal
    assert overlay.layout.display == "none"  # ...and layout-level dismissal


def test_failed_initial_load_renders_the_traceback(monkeypatch):
    """A startup failure must surface the traceback in the error box rather than
    only painting 'Load failed — see error below' with nothing below it."""
    import src.layout.app as app_mod

    def boom(*_a, **_k):
        raise RuntimeError("simulated BQL outage")

    monkeypatch.setattr(app_mod, "fetch_prices", boom)

    app = build_app(verbose=False)

    errors = [
        w
        for w in _walk(app)
        if isinstance(w, W.HTML) and "simulated BQL outage" in w.value
    ]
    assert errors, "the startup traceback must be rendered for the user"
