"""Lazy analysis-view rendering (v0.6.9 Workstream D).

Each pane renders only its currently-mounted view per recompute; the other
eight are built on first pick and stay fresh until the next recompute. We prove
this by spying on `multi_strategy.rolling_correlation` (the compute behind the
Rolling Correlation view, which is NOT a default-mounted view) and counting how
often it actually runs as we drive the picker.
"""

from __future__ import annotations

import ipywidgets as W
import src.layout.builder as builder_mod
import src.layout.multi_strategy as ms_mod
from src.layout import build_app


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
        if isinstance(w, W.Dropdown) and "Rolling Correlation" in list(w.options)
    ]


def _spy(monkeypatch, name: str) -> dict:
    # The Rolling Correlation compute lives in the multi_strategy pane engine
    # (extracted from builder in v0.9.12-review #156), so spy there.
    real = getattr(ms_mod, name)
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ms_mod, name, counting)
    return calls


def _fetch_counter(monkeypatch) -> dict:
    real = builder_mod.fetch_prices
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(builder_mod, "fetch_prices", counting)
    return calls


def test_offscreen_view_not_rendered_at_load(monkeypatch):
    rc = _spy(monkeypatch, "rolling_correlation")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    # Default mounted views are Cumulative Performance (left) / Correlation
    # Heatmap (right) — Rolling Correlation is off-screen, so it isn't computed.
    assert rc["n"] == 0


def test_first_pick_renders_on_demand_without_fetch(monkeypatch):
    fetches = _fetch_counter(monkeypatch)
    rc = _spy(monkeypatch, "rolling_correlation")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    assert fetches["n"] == 1  # the single load fetch

    _pickers(app)[0].value = "Rolling Correlation"
    assert rc["n"] == 1  # built on demand
    assert fetches["n"] == 1  # no refetch on a pick


def test_revisit_is_free(monkeypatch):
    rc = _spy(monkeypatch, "rolling_correlation")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    picker = _pickers(app)[0]

    picker.value = "Rolling Correlation"
    assert rc["n"] == 1
    picker.value = "Drawdown"  # navigate away
    picker.value = "Rolling Correlation"  # ...and back: already fresh
    assert rc["n"] == 1  # no recompute on revisit


def test_refresh_restales_offscreen_views(monkeypatch):
    rc = _spy(monkeypatch, "rolling_correlation")
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    picker = _pickers(app)[0]

    picker.value = "Rolling Correlation"
    assert rc["n"] == 1
    picker.value = "Drawdown"  # leave Rolling Correlation mounted elsewhere

    # Refresh rebuilds the slice; only the now-mounted Drawdown view renders, so
    # Rolling Correlation is not recomputed here...
    refresh_btn = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Refresh prices"
    )
    refresh_btn.click()
    assert rc["n"] == 1

    # ...but it's now stale, so re-picking it rebuilds on demand.
    picker.value = "Rolling Correlation"
    assert rc["n"] == 2
