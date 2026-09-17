"""Orchestration steps of `DashboardApp`, reachable on their own (#225).

Before the controller existed these were closures inside a 1,100-line
`build_app`, so the only way to exercise any of them was to build the whole
dashboard and drive it through the UI. They are methods now, so each can be
called directly against a constructed app.

The app is built once per module — `build_app()` runs a full synchronous load,
so rebuilding it per test would dominate the suite's runtime.
"""

from __future__ import annotations

import pandas as pd
import pytest
from src.config import FACTOR_TICKERS, REGIME_TICKERS
from src.layout.app import DashboardApp
from src.price_source import MockPriceSource


@pytest.fixture(scope="module")
def app() -> DashboardApp:
    return DashboardApp(verbose=False)


def test_build_app_returns_the_controller_s_root():
    from src.layout import build_app

    root = build_app(verbose=False)
    # The notebook's one-liner is unchanged: it still gets a widget, not the app.
    assert hasattr(root, "children")
    assert "bbg-app" in root._dom_classes


# --- default selection -------------------------------------------------------


def test_default_selection_picks_five_from_the_options(app):
    sel = app._default_selection()
    options = [o[1] if isinstance(o, tuple) else o for o in app.state.ticker_w.options]
    assert 0 < len(sel) <= 5
    assert set(sel) <= set(options)
    assert len(set(sel)) == len(sel)  # no duplicates


def test_default_selection_is_empty_without_options(app, monkeypatch):
    # No catalog -> no selection, rather than an index error on the fallback.
    monkeypatch.setattr(app.state.ticker_w, "options", [])
    assert app._default_selection() == ()


def test_default_selection_falls_back_when_the_zscore_is_unavailable(app, monkeypatch):
    # A degenerate/empty price cache must still yield a usable starting basket.
    monkeypatch.setattr(app.state, "arp_universe_prices", pd.DataFrame())
    sel = app._default_selection()
    options = [o[1] if isinstance(o, tuple) else o for o in app.state.ticker_w.options]
    assert list(sel) == options[: len(sel)]


# --- the startup fetch list --------------------------------------------------


def test_fetch_tickers_carries_the_ride_alongs(app):
    # The whole ride-along rule in one assertion: benchmarks, factor proxies and
    # regime indicators all join the single startup request (#193).
    tickers = app._fetch_tickers()
    assert set(app.meta_all["ticker"]) <= set(tickers)
    assert set(app.benchmarks.tickers) <= set(tickers)
    assert set(FACTOR_TICKERS) <= set(tickers)
    assert set(REGIME_TICKERS) <= set(tickers)
    assert len(tickers) == len(set(tickers))  # deduped, order-preserving


def test_fetch_tickers_picks_up_a_benchmark_added_at_runtime(app):
    # Recomputed per call, so an added benchmark rides the *next* Refresh.
    before = app._fetch_tickers()
    # `tickers` hands back a copy, so go through the registry's own API.
    app.benchmarks._tickers.append("NEWBM Index")
    try:
        assert "NEWBM Index" not in before
        assert "NEWBM Index" in app._fetch_tickers()
    finally:
        app.benchmarks._tickers.remove("NEWBM Index")


# --- resolving a typed benchmark: the three outcomes -------------------------


def test_resolve_new_benchmark_accepts_a_ticker_already_in_the_cache(app):
    known = str(app.state.universe_prices.columns[0])
    assert app._resolve_new_benchmark(known) is True


def test_resolve_new_benchmark_refuses_an_unresolvable_ticker(app, monkeypatch):
    import src.bql_client as bc

    bad = "DEFINITELYNOTATICKER Index"
    monkeypatch.setattr(bc, "_DEFAULT_SOURCE", MockPriceSource(unresolvable={bad}))
    assert app._resolve_new_benchmark(bad) is False
    assert "did not resolve" in app.state.status_w.value


def test_resolve_new_benchmark_reports_no_history_differently(app, monkeypatch):
    # #193's distinction: a ticker that resolves but holds nothing in the window
    # must not read as a spelling mistake.
    import src.bql_client as bc

    late = "LATEBM Index"
    future = pd.Timestamp.today().date() + pd.Timedelta(days=365)
    monkeypatch.setattr(
        bc, "_DEFAULT_SOURCE", MockPriceSource(first_trade={late: future})
    )
    assert app._resolve_new_benchmark(late) is False
    status = app.state.status_w.value
    assert "no price history" in status
    assert "did not resolve" not in status


# --- the window caveat -------------------------------------------------------


def test_benchmark_window_note_is_silent_for_full_history(app):
    idx = pd.bdate_range(app.universe_start, periods=40)
    assert app._benchmark_window_note(pd.Series(1.0, index=idx)) == ""


def test_benchmark_window_note_flags_a_late_start(app):
    start = pd.Timestamp(app.universe_start) + pd.Timedelta(days=400)
    idx = pd.bdate_range(start, periods=40)
    note = app._benchmark_window_note(pd.Series(1.0, index=idx))
    assert "History starts" in note
    # The note reports the series' first index, not the requested start:
    # bdate_range snaps a weekend start forward to the next business day.
    # Asserting `start` here passes or fails on what weekday today is.
    assert str(idx[0].date()) in note
