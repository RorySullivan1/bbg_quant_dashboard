"""Live benchmark/regime chart controls (v0.6.9 Workstream C).

Changing a per-pane benchmark dropdown (or a Correlation-Heatmap regime
control) must re-render only that one chart, immediately, from the prices
already fetched at the last recompute — with **no** new BQL/mock fetch and no
full recompute. These tests drive the controls through the rendered widget
tree (the panes/state are closures inside ``build_app``) and assert the
headline guarantees: a benchmark change re-renders live without refetching,
and is a safe no-op when there is no valid selection.
"""

from __future__ import annotations

import ipywidgets as W
import plotly.graph_objects as go
from src.config import BENCHMARK_TICKERS, DEFAULT_BENCHMARK
from src.layout import build_app


def _walk(widget):
    """Yield ``widget`` and every descendant reachable via ``.children``."""
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _mount_multi_strategy(app) -> None:
    """Click the Multi-Strategy Analysis tab so its panel (the strategies
    picker + analysis panes) is mounted into the tree and reachable by
    ``_walk`` (the default mounted tab is Platform)."""
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


def _figure_titles(app) -> list[str]:
    titles = []
    for w in _walk(app):
        if isinstance(w, go.FigureWidget):
            text = w.layout.title.text
            if text:
                titles.append(text)
    return titles


def _patch_fetch_counter(monkeypatch):
    """Wrap ``builder.fetch_prices`` so the real mock fetch still runs but
    every call is counted; returns the mutable counter dict."""
    import src.layout.builder as builder_mod

    real_fetch = builder_mod.fetch_prices
    calls = {"n": 0}

    def counting_fetch(*args, **kwargs):
        calls["n"] += 1
        return real_fetch(*args, **kwargs)

    monkeypatch.setattr(builder_mod, "fetch_prices", counting_fetch)
    return calls


def test_benchmark_change_rerenders_live_without_refetch(monkeypatch):
    calls = _patch_fetch_counter(monkeypatch)
    app = build_app(verbose=False)

    # build_app issues exactly one fetch at load; the default 5-ticker
    # selection means the panes (and `state.cur_prep`) are already populated.
    assert calls["n"] == 1
    after_load = calls["n"]
    _mount_multi_strategy(app)

    # Mount the benchmark-titled views so their figures are in the tree (each
    # pane's stack holds only the picked view). The picker swap is a pure
    # mount — it must not refetch.
    pickers = [
        w
        for w in _walk(app)
        if isinstance(w, W.Dropdown) and "Rolling Correlation" in list(w.options)
    ]
    pickers[0].value = "Rolling Correlation"
    pickers[1].value = "Outperformance"
    assert calls["n"] == after_load

    other = next(b for b in BENCHMARK_TICKERS if b != DEFAULT_BENCHMARK)
    # Flip every benchmark dropdown still on the default to a different
    # benchmark — the rolling-corr/beta/outperf charts retitle with the new
    # label (the heatmap dropdown is benign with the regime filter off).
    for dd in _benchmark_dropdowns(app):
        if dd.value == DEFAULT_BENCHMARK:
            dd.value = other

    # Live re-render only: no additional fetch, and the now-mounted charts
    # carry the new benchmark in their titles.
    assert calls["n"] == after_load
    assert any(other in t for t in _figure_titles(app))


def test_benchmark_change_is_noop_without_selection(monkeypatch):
    calls = _patch_fetch_counter(monkeypatch)
    app = build_app(verbose=False)
    _mount_multi_strategy(app)

    # Clear the selection, then click Refresh prices so the recompute runs the
    # empty-selection branch (which sets `state.cur_prep = None`).
    ticker_w = next(w for w in _walk(app) if isinstance(w, W.SelectMultiple))
    ticker_w.value = ()
    refresh_btn = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Refresh prices"
    )
    refresh_btn.click()
    after_refresh = calls["n"]  # the refresh did refetch once

    # With no selection the live observers must early-return: no crash, no
    # fetch triggered by toggling a benchmark.
    other = next(b for b in BENCHMARK_TICKERS if b != DEFAULT_BENCHMARK)
    for dd in _benchmark_dropdowns(app):
        if dd.value == DEFAULT_BENCHMARK:
            dd.value = other

    assert calls["n"] == after_refresh
