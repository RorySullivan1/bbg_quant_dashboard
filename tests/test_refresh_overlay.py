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
    import src.layout.builder as builder_mod

    monkeypatch.setattr(builder_mod, "get_ipython", lambda: object())
    monkeypatch.setattr(builder_mod, "display", lambda *a, **k: None)
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
    import src.layout.builder as builder_mod

    def boom(*_a, **_k):
        raise RuntimeError("simulated BQL outage")

    monkeypatch.setattr(builder_mod, "fetch_prices", boom)

    app = build_app(verbose=False)

    errors = [
        w
        for w in _walk(app)
        if isinstance(w, W.HTML) and "simulated BQL outage" in w.value
    ]
    assert errors, "the startup traceback must be rendered for the user"


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


def test_refresh_holds_overlay_visible_before_instant_refetch(monkeypatch):
    """The worker must hold the overlay visible (the paint-delay beat) BEFORE it
    runs the refetch, so an instant (mock / warm-cache) refetch can't hide the
    overlay inside the same frame it was shown — the "loading dialog never
    appears" regression."""
    import src.layout.builder as builder_mod

    calls = _patch_fetch_counter(monkeypatch)
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    monkeypatch.setattr(builder_mod, "get_ipython", lambda: object())
    before = calls["n"]

    seen: dict = {}
    real_sleep = builder_mod.time.sleep

    def spy_sleep(secs):
        # At the paint-hold beat, capture the overlay state and whether the
        # refetch has run yet — don't actually block the test.
        if abs(secs - builder_mod._OVERLAY_PAINT_DELAY_S) < 1e-9:
            seen["overlay"] = _overlay(app).value
            seen["fetches_so_far"] = calls["n"]
            return real_sleep(0)
        return real_sleep(secs)

    monkeypatch.setattr(builder_mod.time, "sleep", spy_sleep)

    _refresh_button(app).click()
    _join_refresh_worker()

    assert builder_mod._OVERLAY_PAINT_DELAY_S > 0
    assert "overlay" in seen  # the paint-hold beat ran
    assert "is-hidden" not in seen["overlay"]  # overlay was VISIBLE during it
    assert seen["fetches_so_far"] == before  # ...and it ran BEFORE the refetch
    assert calls["n"] == before + 1  # the refetch still happened
    assert "is-hidden" in _overlay(app).value  # dismissed at the end


def test_refresh_does_not_re_toast(monkeypatch):
    """The post-load "Loaded N indices …" toast only appears on the initial
    load — a Refresh must not re-toast (the loading overlay already signals
    progress). The status widget's value is unchanged across a refresh."""
    calls = _patch_fetch_counter(monkeypatch)
    app = build_app(verbose=False)
    _mount_multi_strategy(app)

    toast = _toast(app)
    before_value = toast.value  # the initial-load toast
    before_n = calls["n"]

    _refresh_button(app).click()  # headless => synchronous refresh

    assert calls["n"] == before_n + 1  # the refetch happened
    assert toast.value == before_value  # ...but no new toast was emitted
