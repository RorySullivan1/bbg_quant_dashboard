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


# --- a catalog-grid click steers the Single Strategy tab (#265) -------------


def _offered(app) -> list[str]:
    return [
        o[1] if isinstance(o, tuple) else o for o in app.single_strategy.picker.options
    ]


def test_a_catalog_click_opens_that_strategy_in_single_strategy(app):
    target = _offered(app)[-1]
    app._show_in_single_strategy(target)
    assert app.single_strategy.picker.value == target
    # And the user is taken there, not left on Platform wondering what happened.
    assert app.top_tab_content.children == (app._top_panels["single"],)


def test_the_catalog_click_goes_through_the_picker_not_around_it(app):
    # Routing sets the picker's value and lets that picker's own observer
    # render. If this ever renders directly instead, a click and a manual pick
    # can diverge — the bug would be two code paths, not one wrong line.
    seen: list[object] = []
    app.single_strategy.picker.observe(seen.append, names="value")
    try:
        first, second = _offered(app)[0], _offered(app)[1]
        app._show_in_single_strategy(first)
        app._show_in_single_strategy(second)
        assert [c["new"] for c in seen][-2:] == [first, second]
    finally:
        app.single_strategy.picker.unobserve(seen.append, names="value")


def test_a_filtered_out_strategy_clears_the_filters_and_says_so(app):
    # The Single Strategy tab has its own filters, which can narrow the picker
    # below the full catalog. Refusing the click would be a dead end — the user
    # named the strategy they want — but silently discarding their filters is
    # the surprising part, so it has to be reported.
    everything = list(app.meta["ticker"])
    target = everything[-1]
    # Narrow the picker so `target` is not on offer.
    app.single_strategy._suspend = True
    try:
        app.single_strategy.picker.options = _ticker_options_for(app, everything[:1])
        app.single_strategy.picker.value = everything[0]
    finally:
        app.single_strategy._suspend = False
    assert target not in _offered(app)

    app._show_in_single_strategy(target)
    assert app.single_strategy.picker.value == target
    assert target in _offered(app)
    assert target in app.state.status_w.value


def _ticker_options_for(app, tickers):
    from src.layout.app import _ticker_options

    return _ticker_options(app.meta.loc[app.meta["ticker"].isin(tickers)])


# --- the grid's own controls: grouping and stats window (#266, #273) -------


def test_group_checkboxes_cover_every_groupable_field_in_hierarchy_order(app):
    from src.config import universe_grid_groupable_fields

    assert list(app.group_boxes) == list(universe_grid_groupable_fields())


def test_group_checkboxes_start_on_the_configured_default(app):
    from src.config import universe_grid_group_fields

    default = set(universe_grid_group_fields())
    for key, box in app.group_boxes.items():
        assert box.value == (key in default)


def test_checking_a_box_regroups_the_grid(app):
    for key, box in app.group_boxes.items():
        box.unobserve(app._on_grouping_change, names="value")
        box.value = key in ("solution", "category", "family")
        box.observe(app._on_grouping_change, names="value")
    app.group_boxes["asset_class"].value = True
    assert app.universe_grid.group_fields == (
        "asset_class",
        "solution",
        "category",
        "family",
    )


def test_ticking_order_does_not_change_the_nesting(app):
    # The fixed hierarchy order, exercised through the actual widgets: the two
    # sequences below differ only in the order the boxes are set.
    def _set(order):
        for box in app.group_boxes.values():
            box.unobserve(app._on_grouping_change, names="value")
            box.value = False
            box.observe(app._on_grouping_change, names="value")
        for key in order:
            app.group_boxes[key].value = True
        return app.universe_grid.group_fields

    assert _set(["family", "asset_class"]) == _set(["asset_class", "family"])
    assert app.universe_grid.group_fields == ("asset_class", "family")


def test_unchecking_everything_leaves_a_flat_grid(app):
    for box in app.group_boxes.values():
        box.value = False
    assert app.universe_grid.group_fields == ()


def test_the_window_radio_offers_what_the_history_supports(app):
    from src.config import stat_windows, universe_grid_default_window

    assert list(app.window_radio.options) == [label for label, _ in stat_windows()]
    assert app.window_radio.value == universe_grid_default_window()


def test_picking_a_window_moves_the_grid(app):
    app.window_radio.value = "5Y"
    assert app.universe_grid.window == "5Y"
    app.window_radio.value = "6M"
    assert app.universe_grid.window == "6M"


def test_the_window_rail_sits_left_of_the_grid(app):
    # It reads as the table's own axis rather than another control in the row
    # of dropdowns, which is why it is an HBox and not another row.
    left, right = app.universe_grid_row.children
    assert right is app.universe_grid.widget
    assert app.window_radio in left.children
