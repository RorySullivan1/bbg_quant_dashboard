"""Fetching a benchmark the user typed, and reporting what happened (#193).

This is the piece that makes arbitrary tickers real. Three things carry the
risk:

1. **It is a delta, not a refetch.** #176's containment cache means adding one
   ticker fetches only the missing rectangle. The v0.9.0 non-goal "no extra BQL
   call" predates that cache; a delta stays inside the spirit of
   one-call-per-session, a whole-universe refetch would not.

2. **The two failure modes stay apart.** An unresolvable ticker and one that
   resolves with no history in the window both arrive as an empty column, so
   the data alone cannot separate them — the per-ticker warning from #187 is
   the signal. Conflated, users read the second as a bug. These tests use the
   #195 mock seams to drive both, which is precisely why #195 was sequenced
   first.

3. **An added benchmark survives.** Refresh refetches the full request and a
   lookback change re-requests a different window; a benchmark that was not
   folded into that request would silently vanish. And it must never leak into
   the universe views, which are scoped by `reindex(columns=meta["ticker"])`.
"""

from __future__ import annotations

import ipywidgets as W
import pandas as pd
import pytest
import src.bql_client as bc
import src.layout.builder as builder_mod
from src.config import BENCHMARK_TICKERS, DEFAULT_BENCHMARK
from src.layout import build_app
from src.layout.benchmarks import BenchmarkRegistry, BenchmarkSelect

NEW = "NEWBM Index"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    bc._clear_caches()
    monkeypatch.setattr(bc, "CACHE_DIR", tmp_path / "cache")
    yield
    bc._clear_caches()


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _click(app, description: str) -> None:
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == description
    ).click()


def _selectors(app) -> list[BenchmarkSelect]:
    return [w for w in _walk(app) if isinstance(w, BenchmarkSelect)]


@pytest.fixture
def captured(monkeypatch):
    """The registry and state `build_app` builds for itself."""
    made: dict = {}
    real_reg = builder_mod.BenchmarkRegistry
    real_state = builder_mod.DashboardState

    def reg_factory(*a, **k):
        made["registry"] = r = real_reg(*a, **k)
        return r

    def state_factory(*a, **k):
        made["state"] = s = real_state(*a, **k)
        return s

    monkeypatch.setattr(builder_mod, "BenchmarkRegistry", reg_factory)
    monkeypatch.setattr(builder_mod, "DashboardState", state_factory)
    return made


# --------------------------------------------------------------------------
# Registry-level: request / resolver contract
# --------------------------------------------------------------------------


def test_a_known_ticker_never_reaches_the_resolver():
    # A curated benchmark or catalog index is already fetched — asking BQL
    # about it again would be a pointless round trip on every pick.
    seen: list[str] = []
    reg = BenchmarkRegistry(["A Index"])
    reg.set_catalog([("X Index — Ex", "X Index")])
    reg.set_resolver(lambda t: seen.append(t) or True)

    assert reg.request("A Index") is True
    assert reg.request("X Index") is True
    assert seen == []


def test_an_unknown_ticker_is_added_only_once_the_resolver_confirms():
    reg = BenchmarkRegistry(["A Index"])
    reg.set_resolver(lambda _t: True)

    assert reg.request("B Index") is True
    assert "B Index" in reg.tickers


def test_a_refused_ticker_never_enters_the_registry():
    reg = BenchmarkRegistry(["A Index"])
    reg.set_resolver(lambda _t: False)

    assert reg.request("B Index") is False
    assert reg.tickers == ["A Index"]


def test_without_a_resolver_unknown_tickers_are_refused():
    # The safe default for any caller that cannot fetch.
    reg = BenchmarkRegistry(["A Index"])
    assert reg.request("B Index") is False
    assert reg.tickers == ["A Index"]


def test_registering_a_selector_wires_it_to_the_registry():
    reg = BenchmarkRegistry(["A Index"])
    reg.set_resolver(lambda _t: True)
    sel = reg.register(BenchmarkSelect(default="A Index"), include_catalog=True)

    sel._box.value = "newbm"  # freehand entry, normalized on commit

    assert sel.value == "NEWBM Index"
    assert "NEWBM Index" in reg.tickers


# --------------------------------------------------------------------------
# App-level: the delta fetch
# --------------------------------------------------------------------------


def test_adding_a_ticker_fetches_only_that_ticker(monkeypatch, captured):
    requested: list[list[str]] = []
    real = builder_mod.fetch_prices

    def spy(tickers, *a, **k):
        requested.append(list(tickers))
        return real(tickers, *a, **k)

    monkeypatch.setattr(builder_mod, "fetch_prices", spy)

    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    startup_calls = len(requested)

    _selectors(app)[0]._box.value = "newbm"

    # Exactly one extra request, and it asks for the one ticker — a delta, not
    # a whole-universe refetch.
    assert len(requested) == startup_calls + 1
    assert requested[-1] == [NEW]


def test_an_added_benchmark_becomes_selectable_everywhere(captured):
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    _click(app, "Quantitative")

    _selectors(app)[0]._box.value = "newbm"

    registry = captured["registry"]
    assert NEW in registry.tickers
    for sel in _selectors(app):
        assert NEW in [v for _, v in sel.options]


def test_an_added_benchmark_lands_in_the_price_cache(captured):
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    _selectors(app)[0]._box.value = "newbm"

    prices = captured["state"].universe_prices
    assert NEW in prices.columns
    assert prices[NEW].notna().any()


def test_an_added_benchmark_never_enters_the_universe_views(captured):
    # Benchmarks are scoped out by `reindex(columns=meta["ticker"])`; a user
    # benchmark is not a catalog member and must not show up in the grid,
    # highlights, or superlatives.
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    _selectors(app)[0]._box.value = "newbm"

    state = captured["state"]
    assert NEW not in state.arp_universe_prices.columns
    assert NEW not in state.universe_rets.columns


# --------------------------------------------------------------------------
# The two failure modes, told apart
# --------------------------------------------------------------------------


def test_an_unresolvable_ticker_is_refused_and_reported(captured):
    bc._MOCK_UNRESOLVABLE.add(NEW)
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    sel = _selectors(app)[0]
    before = sel.value

    sel._box.value = "newbm"

    assert sel.value == before  # not selected
    assert NEW not in captured["registry"].tickers  # not registered
    assert "did not resolve" in captured["state"].status_w.value


def test_a_ticker_with_no_history_in_the_window_is_reported_differently(captured):
    # Resolves, but the window holds nothing. Told apart from "wrong ticker",
    # because the user should look at their lookback, not their spelling.
    bc._MOCK_FIRST_TRADE[NEW] = pd.Timestamp.today().date() + pd.Timedelta(days=365)
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    sel = _selectors(app)[0]
    before = sel.value

    sel._box.value = "newbm"

    status = captured["state"].status_w.value
    assert sel.value == before
    assert "no price history" in status
    assert "did not resolve" not in status  # the distinction that matters


def test_a_late_launching_ticker_is_accepted_with_a_caveat(captured):
    # Partial history is usable for correlation and beta — accept it, but say
    # so, or the chart just appears to start late for no reason.
    launch = pd.Timestamp.today().normalize() - pd.Timedelta(days=200)
    bc._MOCK_FIRST_TRADE[NEW] = launch.date()
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    _selectors(app)[0]._box.value = "newbm"

    status = captured["state"].status_w.value
    assert NEW in captured["registry"].tickers  # accepted
    assert "History starts" in status  # with the caveat


def test_a_full_history_ticker_is_accepted_without_a_caveat(captured):
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    _selectors(app)[0]._box.value = "newbm"

    status = captured["state"].status_w.value
    assert "Added benchmark" in status
    assert "History starts" not in status


def test_a_failed_fetch_cannot_break_a_loaded_dashboard(monkeypatch, captured):
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    sel = _selectors(app)[0]
    before = sel.value

    def boom(*_a, **_k):
        raise RuntimeError("BQL session dropped")

    monkeypatch.setattr(builder_mod, "fetch_prices", boom)

    sel._box.value = "newbm"  # must not raise

    assert sel.value == before
    assert "Could not fetch" in captured["state"].status_w.value
    assert "BQL session dropped" in captured["state"].errors_w.value


# --------------------------------------------------------------------------
# Survival: an added benchmark rides the later fetches
# --------------------------------------------------------------------------


def test_an_added_benchmark_rides_the_refresh(monkeypatch, captured):
    requested: list[list[str]] = []
    real = builder_mod.fetch_prices

    def spy(tickers, *a, **k):
        requested.append(list(tickers))
        return real(tickers, *a, **k)

    monkeypatch.setattr(builder_mod, "fetch_prices", spy)

    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    _selectors(app)[0]._box.value = "newbm"

    _click(app, "Refresh prices")

    # Without folding the added benchmark into the refresh request it would
    # silently drop out of the cache the first time the user refreshed.
    assert NEW in requested[-1]
    assert NEW in captured["state"].universe_prices.columns
    assert NEW in captured["registry"].tickers


def test_the_startup_request_still_covers_the_curated_benchmarks(monkeypatch):
    # The dynamic ticker list must stay a superset of the constant it replaced.
    requested: list[list[str]] = []
    real = builder_mod.fetch_prices

    def spy(tickers, *a, **k):
        requested.append(list(tickers))
        return real(tickers, *a, **k)

    monkeypatch.setattr(builder_mod, "fetch_prices", spy)
    build_app(verbose=False)

    assert set(BENCHMARK_TICKERS) <= set(requested[0])
    assert DEFAULT_BENCHMARK in requested[0]
