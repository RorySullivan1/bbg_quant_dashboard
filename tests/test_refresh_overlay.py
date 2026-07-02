"""Refresh-prices loading overlay (regression for the vanished loading screen).

Under a live frontend the Refresh-prices click must hand its blocking fetch +
recompute to a worker thread, so the click handler returns and the frontend
gets a paint cycle to actually show the overlay before the kernel blocks on
BQL. Headlessly (``get_ipython() is None``) the work stays synchronous so
callers observe the refetch immediately after ``.click()``.

These tests drive the rendered widget tree and assert both paths: the headless
path refetches inline, and the forced-frontend path spawns a ``bbg-refresh``
worker that refetches, dismisses the overlay, and re-enables the button.
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
    """Click the Multi-Strategy Analysis tab so its Refresh-prices button (and
    the rest of the panel) is mounted into the tree and reachable by ``_walk``
    (the default mounted tab is Platform)."""
    btn = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Multi-Strategy Analysis"
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
    return next(
        w for w in _walk(app) if isinstance(w, W.HTML) and "bbg-overlay" in w.value
    )


def _patch_fetch_counter(monkeypatch):
    import src.layout.builder as builder_mod

    real_fetch = builder_mod.fetch_prices
    calls = {"n": 0}

    def counting_fetch(*args, **kwargs):
        calls["n"] += 1
        return real_fetch(*args, **kwargs)

    monkeypatch.setattr(builder_mod, "fetch_prices", counting_fetch)
    return calls


def _join_refresh_worker(timeout: float = 30.0) -> None:
    for t in threading.enumerate():
        if t.name == "bbg-refresh":
            t.join(timeout)


def test_headless_refresh_runs_synchronously(monkeypatch):
    """With no frontend, `.click()` returns only after the refetch — the
    existing synchronous contract the other suites rely on."""
    calls = _patch_fetch_counter(monkeypatch)
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    before = calls["n"]

    _refresh_button(app).click()

    # No worker thread was spawned, and the refetch already happened inline.
    assert not any(t.name == "bbg-refresh" for t in threading.enumerate())
    assert calls["n"] == before + 1
    assert "is-hidden" in _overlay(app).value


def test_frontend_refresh_uses_worker_thread(monkeypatch):
    """With a (faked) live frontend, the click offloads to a `bbg-refresh`
    worker; once it finishes the overlay is dismissed and the button re-enabled.

    This is the fix for the vanished loading screen: the click handler must
    return before the fetch so the frontend can paint the visible overlay."""
    import src.layout.builder as builder_mod

    calls = _patch_fetch_counter(monkeypatch)
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    before = calls["n"]

    # Force the "live frontend" branch (build_app already ran, so faking this
    # now only affects the refresh handler).
    monkeypatch.setattr(builder_mod, "get_ipython", lambda: object())

    btn = _refresh_button(app)
    btn.click()
    _join_refresh_worker()

    assert calls["n"] == before + 1
    assert not btn.disabled  # re-enabled in the worker's finally block
    assert "is-hidden" in _overlay(app).value
