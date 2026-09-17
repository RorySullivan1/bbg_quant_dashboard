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


def test_the_window_chips_offer_what_the_history_supports(app):
    from src.config import stat_windows, universe_grid_default_window

    assert list(app.window_chips.labels) == [label for label, _ in stat_windows()]
    assert app.window_chips.value == universe_grid_default_window()


def test_picking_a_window_moves_the_grid(app):
    app.window_chips.value = "5Y"
    assert app.universe_grid.window == "5Y"
    app.window_chips.value = "6M"
    assert app.universe_grid.window == "6M"


def test_clicking_a_window_chip_moves_the_grid(app):
    # The route a user actually takes. The test above drives the trait, which
    # a broken click handler would still pass.
    chip = dict(zip(app.window_chips.labels, app.window_chips.children, strict=True))[
        "5Y"
    ]
    chip.click()
    assert app.universe_grid.window == "5Y"


def test_the_window_rail_sits_left_of_the_grid(app):
    # It reads as the table's own axis rather than another control in the row
    # of dropdowns, which is why it is an HBox and not another row.
    left, right = app.universe_grid_row.children
    assert right is app.universe_grid.widget
    assert app.window_chips in left.children


# --- the commentary block: leaderboard + switchable pane (#290) -------------


def _board_tickers(app) -> list[str]:
    return [
        slot.shown
        for column in app.leaderboard.columns.values()
        for slot in column.slots
        if slot.shown is not None
    ]


def test_the_leaderboard_is_populated_after_the_initial_load(app):
    for metric, column in app.leaderboard.columns.items():
        filled = [s for s in column.slots if s.shown is not None]
        assert filled, f"{metric} column is empty"
        # Ranks read top-down, and every filled row carries a formatted value.
        ranks = [s.rank.description for s in filled]
        assert ranks == sorted(ranks, key=int)
        assert all(s.value.description for s in filled)
    assert "Ranking · " in app.leaderboard.title_w.value


def test_every_leaderboard_row_names_an_index_in_the_catalog(app):
    # A row whose ticker is not in the catalog would route a click to a
    # strategy the Single Strategy picker cannot offer.
    catalog = set(app.meta["ticker"])
    shown = _board_tickers(app)
    assert shown
    assert set(shown) <= catalog


def test_a_leaderboard_click_opens_that_strategy_in_single_strategy(app):
    target = _board_tickers(app)[0]
    slot = next(
        s
        for column in app.leaderboard.columns.values()
        for s in column.slots
        if s.shown == target
    )
    slot.ticker.click()

    assert app.single_strategy.picker.value == target
    assert app.top_tab_content.children == (app._top_panels["single"],)


def test_the_window_toggle_re_ranks_the_board_without_fetching(app, monkeypatch):
    from src.layout import app as app_mod

    before_title = app.leaderboard.title_w.value
    before_rows = _board_tickers(app)

    calls = {"n": 0}
    real = app_mod.fetch_prices

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(app_mod, "fetch_prices", counting)
    try:
        app.ranking_window.value = 5  # WEEK_WINDOW → fires the observer
        assert calls["n"] == 0  # re-ranked from the cache, no BQL
        assert "Past Week" in app.leaderboard.title_w.value
        assert app.leaderboard.title_w.value != before_title
        # The board is genuinely re-ranked, not just retitled: a week's
        # ordering differs from a month's on this catalog.
        after_rows = _board_tickers(app)
        assert after_rows
        assert after_rows != before_rows
    finally:
        app.ranking_window.value = 21  # restore the module-scoped fixture


def test_re_toggling_a_window_is_a_cache_hit(app):
    # The cache is keyed by window, so returning to one already computed must
    # not rebuild it — this is what makes the toggle feel live.
    app.ranking_window.value = 63
    first = app.highlights_cache[63]
    app.ranking_window.value = 21
    app.ranking_window.value = 63
    assert app.highlights_cache[63] is first
    app.ranking_window.value = 21


def test_an_init_error_survives_a_window_change_and_a_pane_switch(app):
    # `errors_w` is a sibling of both panes precisely so neither live control
    # can wipe it. It was split out of the old highlights widget for this.
    marker = "INIT-ERROR-MARKER"
    before = app.state.errors_w.value
    app.state.errors_w.value = before + marker
    try:
        app.ranking_window.value = 5
        assert marker in app.state.errors_w.value
        app.commentary_pane.show("launches")
        assert marker in app.state.errors_w.value
        app.commentary_pane.show("commentary")
        assert marker in app.state.errors_w.value
    finally:
        app.state.errors_w.value = before
        app.ranking_window.value = 21


def test_the_pane_carries_the_launch_cards_built_from_the_catalog(app):
    assert "launches" in app.highlights_cache
    assert "New Launches" in app.commentary_pane.launches_w.value
    assert app.commentary_pane.active == "commentary"  # opens on the commentary


def test_the_block_is_a_fixed_leaderboard_beside_an_absorbing_pane(app):
    # #276's rail idiom: the leaderboard takes a fixed basis wide enough for
    # its four columns and the pane absorbs the remainder, so the split holds
    # at any viewport width with no pixel constant on the pane. A pane given
    # its own fixed width would leave dead space or overflow instead.
    errors_w, row = app.commentary_box.children
    assert errors_w is app.state.errors_w  # the error strip is first, full width
    board_col, pane_col = row.children

    assert board_col.layout.flex.startswith("0 0 ")  # fixed basis
    assert pane_col.layout.flex == "1 1 0%"  # absorbs the remainder
    assert board_col.layout.min_width == "0"
    assert pane_col.layout.min_width == "0"

    # The toggle sits above the board it re-ranks, inside the same column.
    assert board_col.children == (app.ranking_window_row, app.leaderboard.root)
    assert pane_col.children == (app.commentary_pane.root,)
