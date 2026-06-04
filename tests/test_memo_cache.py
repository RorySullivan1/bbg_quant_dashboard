"""Memoization of benchmark-dependent chart results (v0.6.9 Workstream B).

Flipping a per-pane benchmark and flipping back must hit the memo instead of
recomputing, and the memo must be invalidated when Refresh prices rebuilds the
selection slice. We assert this by spying on `builder.rolling_correlation` and
counting how often it actually runs as we drive the rendered widget tree.
"""

from __future__ import annotations

import ipywidgets as W
import src.layout.builder as builder_mod
from src.config import BENCHMARK_TICKERS, DEFAULT_BENCHMARK
from src.layout import build_app


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _mount_multi_strategy(app) -> None:
    btn = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Multi-Strategy Analysis"
    )
    btn.click()


def _benchmark_dropdowns(app) -> list[W.Dropdown]:
    return [
        w
        for w in _walk(app)
        if isinstance(w, W.Dropdown) and list(w.options) == list(BENCHMARK_TICKERS)
    ]


def _spy_rolling_correlation(monkeypatch) -> dict:
    real = builder_mod.rolling_correlation
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(builder_mod, "rolling_correlation", counting)
    return calls


def _set_all(dropdowns, value) -> None:
    for dd in dropdowns:
        dd.value = value


def test_flip_back_hits_memo_and_shares_across_panes(monkeypatch):
    calls = _spy_rolling_correlation(monkeypatch)
    app = build_app(verbose=False)
    _mount_multi_strategy(app)

    # The load renders both panes for the default benchmark; the shared memo
    # means rolling_correlation runs once even though two panes consume it.
    after_load = calls["n"]
    assert after_load == 1

    other = next(b for b in BENCHMARK_TICKERS if b != DEFAULT_BENCHMARK)
    dds = _benchmark_dropdowns(app)

    # Flip every benchmark to `other`: the two panes' rolling-correlation
    # dropdowns both fire, but the result is computed once (cross-pane share).
    _set_all(dds, other)
    after_flip = calls["n"]
    assert after_flip == after_load + 1

    # Flip back to the default: still cached from load -> a pure memo hit.
    _set_all(dds, DEFAULT_BENCHMARK)
    assert calls["n"] == after_flip


def test_refresh_invalidates_memo(monkeypatch):
    calls = _spy_rolling_correlation(monkeypatch)
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    assert calls["n"] == 1  # default benchmark computed once at load

    # Refresh prices rebuilds the slice and must clear the memo, so the same
    # benchmark is recomputed rather than served stale.
    refresh_btn = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Refresh prices"
    )
    refresh_btn.click()
    assert calls["n"] == 2  # recomputed after invalidation
