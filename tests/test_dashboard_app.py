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
from src.config import (
    FACTOR_TICKERS,
    MONTH_WINDOW,
    QUARTER_WINDOW,
    REGIME_TICKERS,
    universe_grid_default_window,
)
from src.layout.app import DashboardApp
from src.layout.rails import RAIL_WIDTH
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


def _group_chip(app, key):
    """The chip carrying `key`, found by value rather than by position."""
    index = [value for _label, value in app.group_chips.options].index(key)
    return app.group_chips.children[index]


def test_group_chips_cover_every_groupable_field_in_hierarchy_order(app):
    from src.config import field_label, universe_grid_groupable_fields

    fields = list(universe_grid_groupable_fields())
    assert [value for _label, value in app.group_chips.options] == fields
    # The text is schema-read, never spelled at the call site.
    assert list(app.group_chips.labels) == [field_label(key) for key in fields]


def test_group_chips_start_on_the_configured_default(app):
    from src.config import universe_grid_group_fields

    assert app.group_chips.value == universe_grid_group_fields()


def test_ticking_a_chip_regroups_the_grid(app):
    app.group_chips.value = ("solution", "category", "family")
    _group_chip(app, "asset_class").click()
    assert app.universe_grid.group_fields == (
        "asset_class",
        "solution",
        "category",
        "family",
    )


def test_ticking_order_does_not_change_the_nesting(app):
    # The fixed hierarchy order, exercised through the actual chips: the two
    # sequences below differ only in the order they are clicked.
    def _click(order):
        app.group_chips.value = ()
        for key in order:
            _group_chip(app, key).click()
        return app.universe_grid.group_fields

    assert _click(["family", "asset_class"]) == _click(["asset_class", "family"])
    assert app.universe_grid.group_fields == ("asset_class", "family")


def test_unticking_everything_leaves_a_flat_grid(app):
    for key in [value for _label, value in app.group_chips.options]:
        if key in app.group_chips.value:
            _group_chip(app, key).click()
    assert app.group_chips.value == ()
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


def test_the_platform_shell_is_a_bar_above_and_a_rail_beside_the_table(app):
    # The controls that shape the rows sit above the table; the ranking rail
    # runs down its left side. Neither is a row of widgets the table has to
    # share its own line with.
    rail, table = app.universe_grid_row.children
    assert (rail, table) == (app.ranking_rail, app.universe_grid.widget)

    children = list(app._top_panels["platform"].children)
    assert children.index(app.table_bar) < children.index(app.universe_grid_row)


def test_the_bar_lays_its_sections_across(app):
    # Group by before Window: the order the two act in.
    headings = [
        c.value
        for block in app.table_bar.children
        for c in getattr(block, "children", ())
        if "bbg-rail-heading" in c._dom_classes
    ]
    assert headings == ["Group by", "Window"]
    # Same chrome as the rail beside the table, turned.
    assert "bbg-rail" in app.table_bar._dom_classes
    assert "bbg-rail-bar" in app.table_bar._dom_classes
    # Its chips lay out across too, or the bar would be as tall as a rail.
    for chips in (app.group_chips, app.window_chips):
        assert chips.layout.flex_flow == "row wrap"
        assert "bbg-chip-row" in chips._dom_classes


def _declarations(css: str, selector: str) -> list[str]:
    """The property declarations of one rule, with comment text left out."""
    body = css.split(selector + " {")[1].split("}")[0]
    lines = [line.strip() for line in body.splitlines()]
    return [line for line in lines if line.endswith(";") and ":" in line]


def test_the_table_and_the_rail_are_one_fixed_height(app):
    from src.style import CATALOG_TABLE_HEIGHT

    # Both boxes take the SAME constant, from the same token. Stretching was
    # tried and is wrong here: it makes whichever box holds more content set
    # the row, so the table grew to the rail on a small catalog and the rail to
    # the table on a large one.
    assert app.universe_grid.widget.layout.height == CATALOG_TABLE_HEIGHT
    assert app.ranking_rail.layout.height == CATALOG_TABLE_HEIGHT
    assert app.ranking_rail.layout.flex == f"0 0 {RAIL_WIDTH}"


def test_the_table_s_internals_fill_its_box_rather_than_capping_a_cell(app):
    from src.layout.html import STYLE_CTX, render_template

    css = render_template("app_css", **STYLE_CTX)
    # No second height to keep in step with the box by hand: the row area takes
    # what the search row and the readout leave.
    cell = _declarations(
        css, "div.itables_anywidget .dt-layout-row.dt-layout-table .dt-layout-cell"
    )
    assert not any(d.startswith("max-height") for d in cell)
    assert "height: 100%;" in cell
    # `min-height: 0` at every level, or a flex child refuses to shrink below
    # its content and the body pushes the box open instead of scrolling.
    for selector in (
        "div.itables_anywidget.bbg-catalog .dt-container",
        "div.itables_anywidget.bbg-catalog .dt-layout-row.dt-layout-table",
    ):
        assert any(d.startswith("min-height: 0") for d in _declarations(css, selector))
    assert "overflow: auto;" in cell


def test_the_chips_never_shrink_to_fit(app):
    from src.layout.html import STYLE_CTX, render_template

    # A flex item shrinks before its container scrolls, so a rail holding more
    # chips than fit squeezed every chip flat instead of giving them a
    # scrollbar. That read as a styling bug and was the default `flex-shrink`.
    css = render_template("app_css", **STYLE_CTX)
    rule = ".bbg-app .bbg-chip,\n.bbg-app .bbg-rail-heading,\n.bbg-app .bbg-rail-title"
    assert rule in css
    assert "flex: 0 0 auto !important;" in _declarations(css, rule)


def test_both_containers_carry_a_title(app):
    titles = []
    for container in (app.table_bar, app.ranking_rail):
        titles += [
            c.value for c in container.children if "bbg-rail-title" in c._dom_classes
        ]
    assert titles == ["Table view", "Z-Score ranking"]


def test_no_control_row_sits_above_the_grid(app):
    # #278 moved the grouping into the left rail and #279 the z-score ranking
    # into the right one, which retired the row they shared.
    assert not hasattr(app, "z_controls_row")


def test_the_z_score_column_header_follows_the_chips(app):
    app.z_metric_chips.value = "sortino"
    app.z_window_chips.value = QUARTER_WINDOW
    zcols = [c for c in app.universe_grid._display.columns if c.startswith("Z-Score")]
    assert zcols == ["Z-Score Sortino 3M/1Y"]
    app.z_metric_chips.value = "sharpe"
    app.z_window_chips.value = MONTH_WINDOW


def test_the_window_chips_cannot_hide_the_z_score_column(app):
    # The z-score's own window is embedded in its label ("Sharpe 1M/1Y"), which
    # `_window_of` deliberately does not match — a stats-window switch must not
    # take the column with it (#279).
    app.window_chips.value = "6M"
    assert any(c.startswith("Z-Score") for c in app.universe_grid._display.columns)
    app.window_chips.value = universe_grid_default_window()


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
        # Every filled row carries both numbers (#310, #306): the score it is
        # ranked by, and the raw value in parentheses behind it.
        assert all(s.score.description for s in filled)
        assert all(s.value.description.startswith("(") for s in filled)


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
        # The board is genuinely re-ranked: a week's ordering differs from a
        # month's on this catalog. (The board no longer titles itself — the
        # section heading and the chips say the window since #306 — so the
        # rows are the only evidence that anything happened.)
        after_rows = _board_tickers(app)
        assert after_rows
        assert after_rows != before_rows
    finally:
        app.ranking_window.value = 21  # restore the module-scoped fixture


def test_the_leaderboard_window_offers_a_year_without_lengthening_the_others(app):
    """#306 added 1Y to the board's chips. It is a list of its own, not an edit
    to `SHORT_WINDOW_OPTIONS`, because that constant also drives the Platform
    sunburst's Z-score control and the Multi-Strategy Quantitative Z-Score
    window — neither of which was asked to grow a year. This is the test that
    catches a future one-line edit to the shared list."""
    from src.config import (
        LEADERBOARD_WINDOW_OPTIONS,
        SHORT_WINDOW_OPTIONS,
        TRADING_DAYS_PER_YEAR,
    )

    assert [label for label, _ in LEADERBOARD_WINDOW_OPTIONS] == [
        "1W",
        "1M",
        "3M",
        "6M",
        "1Y",
    ]
    assert LEADERBOARD_WINDOW_OPTIONS[-1] == ("1Y", TRADING_DAYS_PER_YEAR)
    assert [label for label, _ in app.ranking_window.options] == [
        label for label, _ in LEADERBOARD_WINDOW_OPTIONS
    ]
    # The shared list, and both controls built from it, stop at six months.
    assert [label for label, _ in SHORT_WINDOW_OPTIONS] == ["1W", "1M", "3M", "6M"]
    assert [label for label, _ in app.analytics.sb_window_dd.options] == [
        "1W",
        "1M",
        "3M",
        "6M",
    ]
    assert [label for label, _ in app.filter_panel.quant.z_window_dd.options] == [
        "1W",
        "1M",
        "3M",
        "6M",
    ]


def test_selecting_the_year_window_re_ranks_from_cache_without_fetching(
    app, monkeypatch
):
    from src.config import TRADING_DAYS_PER_YEAR
    from src.layout import app as app_mod

    before_rows = _board_tickers(app)

    def no_fetch(*a, **kw):  # pragma: no cover - the assert is that it is unused
        raise AssertionError("a window change must not issue BQL")

    monkeypatch.setattr(app_mod, "fetch_prices", no_fetch)
    try:
        app.ranking_window.value = TRADING_DAYS_PER_YEAR
        assert TRADING_DAYS_PER_YEAR in app.highlights_cache
        after_rows = _board_tickers(app)
        assert after_rows
        assert after_rows != before_rows
    finally:
        app.ranking_window.value = 21


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

    # The board sits in a `section_panel`: title line, the Window chip bar it
    # is re-ranked by, then the boxed board (#305, #306).
    (panel,) = board_col.children
    title, bar, box = panel.children
    assert "Leaderboard" in title.value
    assert bar is app.ranking_window_bar
    assert box.children == (app.leaderboard.root,)
    assert pane_col.children == (app.commentary_pane.root,)


# --- two horizons: fetch six years, analyse five (#311) --------------------
#
# The fetch reaches a year further back than the app analyses, so the leaderboard's
# score has its 5-year sample at the 1Y window (#310). That makes a missed slice a
# six-year statistic under a `5Y` label — which is why the boundary is one helper
# and why these tests exist.


def test_the_fetch_reaches_further_back_than_the_analysis(app):
    from src.config import LOOKBACK_YEARS, SCORE_HISTORY_YEARS

    fetch_start = pd.Timestamp(app.universe_start)
    analytics_start = app._analytics_window_start()

    assert fetch_start == pd.Timestamp(app.today) - pd.DateOffset(
        years=SCORE_HISTORY_YEARS
    )
    assert analytics_start == pd.Timestamp(app.today) - pd.DateOffset(
        years=LOOKBACK_YEARS
    )
    assert fetch_start < analytics_start


def test_no_call_site_computes_the_analytics_window_for_itself():
    """The rule that stops a fifth consumer opting out by omission.

    Four sites each carried their own copy of this expression. While the fetch
    and the analysis window were the same number a missed slice was harmless;
    now it is a year of extra history under a `5Y` label.
    """
    from pathlib import Path

    import src.layout as layout

    offset = "DateOffset(years=LOOKBACK_YEARS)"
    hits = [
        path.name
        for path in Path(layout.__file__).parent.glob("*.py")
        if offset in path.read_text(encoding="utf-8")
    ]
    # Only the helper itself, which is where the expression belongs.
    assert hits == ["app.py"]
    source = (Path(layout.__file__).parent / "app.py").read_text(encoding="utf-8")
    assert source.count(offset) == 1
    assert "def _analytics_window_start" in source


def test_a_benchmark_with_a_full_analysis_window_draws_no_caveat(app):
    """The caveat is about covering the *analysis*, not the fetch.

    Measured against the six-year fetch start, a benchmark carrying a full five
    years of history looks ~365 days late and would trip a warning it does not
    deserve.
    """
    analytics_start = app._analytics_window_start()
    full = pd.Series(
        1.0, index=pd.bdate_range(analytics_start, pd.Timestamp(app.today))
    )

    assert app._benchmark_window_note(full) == ""

    short = pd.Series(
        1.0,
        index=pd.bdate_range(
            analytics_start + pd.Timedelta(days=400), pd.Timestamp(app.today)
        ),
    )
    assert "History starts" in app._benchmark_window_note(short)


def test_the_disclaimer_states_the_period_the_numbers_cover(app):
    # It is the one place the window is asserted to the reader in prose, so it
    # tracks the analytics window rather than the fetch.
    analytics_start = app._analytics_window_start().date().isoformat()
    disclaimers = [
        child.value
        for child in app.root.children
        if getattr(child, "value", None) and "performance" in str(child.value).lower()
    ]

    assert disclaimers, "no performance disclaimer on the app root"
    assert any(analytics_start in text for text in disclaimers)
    assert not any(app.universe_start.isoformat() in text for text in disclaimers)
