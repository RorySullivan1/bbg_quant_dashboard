"""Lazy analysis-view rendering (v0.6.9 Workstream D).

Each pane renders only its currently-mounted view per recompute; the other
eight are built on first pick and stay fresh until the next recompute. We prove
this by spying on `multi_strategy.rolling_series` (the compute behind the
Rolling view, which is NOT a default-mounted view) and counting how
often it actually runs as we drive the picker.
"""

from __future__ import annotations

import ipywidgets as W
import src.layout.app as app_mod
import src.layout.multi_strategy as ms_mod
from src.layout import build_app


def _basket(root):
    """The app's selection state — what re-slices the analytics (v0.9.30)."""
    from src.layout.basket import BasketCards

    return next(w for w in _walk(root) if isinstance(w, BasketCards)).basket


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _mount_multi_strategy(app) -> None:
    btn = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Multi-Strategy"
    )
    btn.click()


def _pickers(app) -> list[W.Dropdown]:
    return [
        w
        for w in _walk(app)
        if isinstance(w, W.Dropdown) and "Rolling" in list(w.options)
    ]


def _spy(monkeypatch, name: str) -> dict:
    # The Rolling compute lives in the multi_strategy pane engine
    # (extracted from builder in v0.9.12-review #156), so spy there.
    real = getattr(ms_mod, name)
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ms_mod, name, counting)
    return calls


def _fetch_counter(monkeypatch) -> dict:
    real = app_mod.fetch_prices
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(app_mod, "fetch_prices", counting)
    return calls


def test_offscreen_view_not_rendered_at_load(monkeypatch):
    rc = _spy(monkeypatch, "rolling_series")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    # Default mounted views are Cumulative Performance (left) / Correlation
    # Heatmap (right) — Rolling is off-screen, so it isn't computed.
    assert rc["n"] == 0


def test_first_pick_renders_on_demand_without_fetch(monkeypatch):
    fetches = _fetch_counter(monkeypatch)
    rc = _spy(monkeypatch, "rolling_series")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    assert fetches["n"] == 1  # the single load fetch

    _pickers(app)[0].value = "Rolling"
    assert rc["n"] == 1  # built on demand
    assert fetches["n"] == 1  # no refetch on a pick


def test_revisit_is_free(monkeypatch):
    rc = _spy(monkeypatch, "rolling_series")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    picker = _pickers(app)[0]

    picker.value = "Rolling"
    assert rc["n"] == 1
    picker.value = "Drawdown"  # navigate away
    picker.value = "Rolling"  # ...and back: already fresh
    assert rc["n"] == 1  # no recompute on revisit


def test_refresh_restales_offscreen_views(monkeypatch):
    rc = _spy(monkeypatch, "rolling_series")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    picker = _pickers(app)[0]

    picker.value = "Rolling"
    assert rc["n"] == 1
    picker.value = "Drawdown"  # leave Rolling mounted elsewhere

    # A basket change rebuilds the slice (v0.9.30 — Refresh prices is gone and
    # this is what re-slices now); only the now-mounted Drawdown view renders,
    # so Rolling is not recomputed here...
    # Two, not one: a correlation needs a pair, so dropping to a
    # single strategy would leave `rolling_series` uncalled and
    # the counter unmoved for the wrong reason.
    _basket(app).replace(list(_basket(app).value)[:2])
    assert rc["n"] == 1

    # ...but it's now stale, so re-picking it rebuilds on demand.
    picker.value = "Rolling"
    assert rc["n"] == 2
