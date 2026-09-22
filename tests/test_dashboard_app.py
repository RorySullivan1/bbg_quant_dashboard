"""Orchestration steps of `DashboardApp`, reachable on their own (#225).

Before the controller existed these were closures inside a 1,100-line
`build_app`, so the only way to exercise any of them was to build the whole
dashboard and drive it through the UI. They are methods now, so each can be
called directly against a constructed app.

The app is built once per module — `build_app()` runs a full synchronous load,
so rebuilding it per test would dominate the suite's runtime.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest
from src.config import (
    FACTOR_TICKERS,
    LOOKBACK_YEARS,
    MONTH_WINDOW,
    NEW_LAUNCH_DAYS,
    REGIME_TICKERS,
    universe_grid_default_window,
)
from src.layout.app import DashboardApp
from src.price_source import MockPriceSource
from src.style import COMMENTARY_BULLETIN_SHARE, COMMENTARY_LEADERBOARD_SHARE


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
    options = [str(x) for x in app.meta["ticker"]]
    assert 0 < len(sel) <= 5
    assert set(sel) <= set(options)
    assert len(set(sel)) == len(sel)  # no duplicates


def test_default_selection_is_empty_without_options(app, monkeypatch):
    # No catalog -> no selection, rather than an index error on the fallback.
    monkeypatch.setattr(app, "meta", app.meta.iloc[:0])
    assert app._default_selection() == ()


def test_default_selection_falls_back_when_the_zscore_is_unavailable(app, monkeypatch):
    # A degenerate/empty price cache must still yield a usable starting basket.
    monkeypatch.setattr(app.state, "arp_universe_prices", pd.DataFrame())
    sel = app._default_selection()
    options = [str(x) for x in app.meta["ticker"]]
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
    # Late measured against the **analysis** window, which is what the note is
    # about — the fetch now reaches years further back (#322), so a start
    # measured off `universe_start` can still cover the whole analysis window
    # and deserve no caveat at all.
    start = app._analytics_window_start() + pd.Timedelta(days=400)
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


# The `app` fixture is module-scoped, and since #324 the window is not just a
# column-visibility toggle — it renames the ranking column and re-sorts the
# table. A test that leaves it moved now leaks into every test after it, so
# these put it back.


def test_picking_a_window_moves_the_grid(app):
    app.window_chips.value = "5Y"
    assert app.universe_grid.window == "5Y"
    app.window_chips.value = "6M"
    assert app.universe_grid.window == "6M"
    app.window_chips.value = universe_grid_default_window()


def test_clicking_a_window_chip_moves_the_grid(app):
    # The route a user actually takes. The test above drives the trait, which
    # a broken click handler would still pass.
    chip = dict(zip(app.window_chips.labels, app.window_chips.children, strict=True))[
        "5Y"
    ]
    chip.click()
    assert app.universe_grid.window == "5Y"
    app.window_chips.value = universe_grid_default_window()


def test_the_platform_shell_is_a_bar_above_a_full_width_table(app):
    # One bar of controls, then the table, then the analytics card. The rail
    # that ran down the table's left side went in #326 with the last of its
    # contents, and the table took the width back.
    children = list(app._top_panels["platform"].children)
    assert children == [
        app.universe_header,
        app.table_bar,
        app.universe_grid.widget,
        app.analytics.card,
    ]
    assert not hasattr(app, "ranking_rail")
    assert not hasattr(app, "universe_grid_row")


def test_the_table_takes_the_whole_width(app):
    layout = app.universe_grid.widget.layout
    assert layout.width == "100%"
    # The flex share that gave it "whatever the rail leaves" is gone: in a
    # column that basis applies to the HEIGHT and would fight the fixed box.
    assert layout.flex is None
    # `min_width` stays — no longer what keeps a wide column set inside the
    # table (the `.dt-layout-cell` scroll does that), but the guard that made
    # the row work, and putting the table back in a row without it is #280.
    assert layout.min_width == "0"


def test_the_bar_lays_its_sections_across(app):
    # Group by · Metric · Window: the order the three act in — what the rows
    # are gathered into, what is measured, over how long (#325).
    headings = [
        c.value
        for block in app.table_bar.children
        for c in getattr(block, "children", ())
        if "bbg-rail-heading" in c._dom_classes
    ]
    assert headings == ["Group by", "Metric", "Window"]
    # Same chrome as a rail, turned.
    assert "bbg-rail" in app.table_bar._dom_classes
    assert "bbg-rail-bar" in app.table_bar._dom_classes
    # Its chips lay out across too, or the bar would be as tall as a rail.
    for chips in (app.group_chips, app.z_metric_chips, app.window_chips):
        assert chips.layout.flex_flow == "row wrap"
        assert "bbg-chip-row" in chips._dom_classes


def test_the_bar_holds_the_very_chips_the_analytics_reads(app):
    """A container change, not a second copy (#325).

    `PlatformAnalytics` was injected with these objects at construction and
    reads `.value` / `.label` / `.observe` off them. A bar that built its own
    would leave the chips on screen driving nothing.
    """
    from src.layout.rails import ChipGroup, MultiChipGroup

    bar_chips = [
        c
        for block in app.table_bar.children
        for c in getattr(block, "children", ())
        if isinstance(c, ChipGroup | MultiChipGroup)
    ]
    assert bar_chips == [app.group_chips, app.z_metric_chips, app.window_chips]
    assert app.analytics.z_metric_chips is app.z_metric_chips
    assert app.analytics.window_chips is app.window_chips


def _declarations(css: str, selector: str) -> list[str]:
    """Every declaration the cascade gives `selector`, comment text left out.

    All of its rules, not the first: a selector legitimately carries more than
    one (#340 painted wrappers that already had layout rules), and taking the
    first made an unrelated addition look like a deleted declaration.
    """
    plain = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: list[str] = []
    for rule in plain.split("}"):
        if "{" not in rule:
            continue
        prelude, body = rule.split("{", 1)
        # `selector` is either one selector out of the rule's list, or the
        # whole list as written — both are used by callers here.
        parts = [" ".join(s.split()) for s in prelude.split(",")]
        if " ".join(selector.split()) not in parts + [" ".join(prelude.split())]:
            continue
        found += [
            line.strip()
            for line in body.splitlines()
            if line.strip().endswith(";") and ":" in line
        ]
    return found


def test_the_table_stands_at_a_fixed_height(app):
    from src.style import CATALOG_TABLE_HEIGHT

    # One token, and since #326 only one box reads it — it was the number the
    # table and the rail beside it had to share, because stretching made
    # whichever held more content set the row.
    assert app.universe_grid.widget.layout.height == CATALOG_TABLE_HEIGHT


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
        "div.itables_anywidget.bbg-itable .dt-container",
        "div.itables_anywidget.bbg-itable .dt-layout-row.dt-layout-table",
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


def test_the_bar_carries_a_title(app):
    # One container left, and it says what its three sections belong to.
    titles = [
        c.value for c in app.table_bar.children if "bbg-rail-title" in c._dom_classes
    ]
    assert titles == ["Table view"]


def test_no_control_row_sits_above_the_grid(app):
    # #278 moved the grouping into the left rail and #279 the z-score ranking
    # into the right one, which retired the row they shared.
    assert not hasattr(app, "z_controls_row")


def _ranking_columns(app) -> list[str]:
    from src.layout.grids import ZSCORE_SUPERCOL

    return [c for c in app.universe_grid._display.columns if ZSCORE_SUPERCOL in str(c)]


def test_the_ranking_header_says_all_four_facts(app):
    """`Normalized 1Y Sharpe (5Y Z-Score)` — standardized, over what window,
    which metric, against what (#324). It replaced `Z-Score Sharpe 1M/1Y`,
    which compressed a window over a *movable* lookback into six characters."""
    from src.config import SCORE_SAMPLE_YEARS

    app.window_chips.value = "1Y"
    assert _ranking_columns(app) == [
        f"Normalized 1Y Sharpe ({SCORE_SAMPLE_YEARS}Y Z-Score)"
    ]

    app.z_metric_chips.value = "sortino"
    assert _ranking_columns(app) == [
        f"Normalized 1Y Sortino ({SCORE_SAMPLE_YEARS}Y Z-Score)"
    ]

    app.window_chips.value = "3Y"
    assert _ranking_columns(app) == [
        f"Normalized 3Y Sortino ({SCORE_SAMPLE_YEARS}Y Z-Score)"
    ]

    app.z_metric_chips.value = "sharpe"
    app.window_chips.value = universe_grid_default_window()


def test_the_catalog_and_the_leaderboard_rank_by_the_same_metrics(app):
    """One set, one declaration (#328).

    The two boards rank the same catalog by the same kind of number, so a
    reader should be able to carry a reading from one to the other. They were
    Return/Sharpe/Calmar/Sortino on the board and Sharpe/Sortino/Return/Vol on
    the table, spelled in two places.
    """
    from src.config import RANKABLE_METRICS

    assert RANKABLE_METRICS == (
        ("return", "Return"),
        ("sharpe", "Sharpe"),
        ("calmar", "Calmar"),
        ("sortino", "Sortino"),
    )
    # The table's chips, in the same order...
    assert list(app.z_metric_chips.labels) == [label for _, label in RANKABLE_METRICS]
    # ...and the board's columns.
    assert list(app.leaderboard.columns) == [key for key, _ in RANKABLE_METRICS]


def test_the_catalog_cannot_rank_by_volatility(app):
    """Vol is not merely off the list — the column could not have meant it.

    The ranking column is painted on a symmetric red→green ramp and sorted
    descending, and both say *higher is better*. An index two standard
    deviations above its own vol history rendered bright green at the top of
    the table (#328).
    """
    from src.config import RANKABLE_METRICS

    assert "vol" not in [key for key, _ in RANKABLE_METRICS]
    assert "Vol" not in app.z_metric_chips.labels
    with pytest.raises(ValueError):
        app.z_metric_chips.value = "vol"


def test_ranking_by_calmar_rescores_the_table(app):
    from src.config import SCORE_SAMPLE_YEARS

    app.z_metric_chips.value = "calmar"
    assert _ranking_columns(app) == [
        f"Normalized 1Y Calmar ({SCORE_SAMPLE_YEARS}Y Z-Score)"
    ]
    app.z_metric_chips.value = "sharpe"


def test_the_card_offers_the_rankable_metrics_and_not_vol(app):
    """What #321 left for "its own issue" — epic #331 is that issue.

    The card used to carry its own Sharpe / Sortino / Return / **Vol** list.
    Vol on a diverging red-to-green ramp reads as *green is good*, which
    volatility is not (#328), and Calmar was missing from a card that ranks by
    it everywhere else. The card's Metric is now the one rankable set, so the
    board, the table and the chart cannot disagree about what is rankable.
    """
    from src.config import RANKABLE_METRICS

    assert [label for label, _ in app.analytics.metric_chips.options] == [
        label for _key, label in RANKABLE_METRICS
    ]
    assert "Vol" not in app.analytics.metric_chips.labels
    assert "Calmar" in app.analytics.metric_chips.labels


def test_the_catalog_has_no_lookback_and_no_second_window(app):
    """The score's sample is fixed, so there is nothing left to choose (#324).

    Two chip groups went with it. What is asserted is the absence of the
    *controls*, not of the concept: the sample is still five years, it is just
    no longer negotiable.
    """
    assert not hasattr(app, "z_lookback_chips")
    assert not hasattr(app, "z_window_chips")
    assert not hasattr(app.analytics, "z_lookback_chips")
    assert not hasattr(app.analytics, "z_window_chips")
    # The Metric moved into the bar in #325 and the emptied rail went in #326,
    # so the bar is the only place a catalog control can be.
    from src.layout.rails import ChipGroup, MultiChipGroup

    bar_chips = [
        c
        for block in app.table_bar.children
        for c in getattr(block, "children", ())
        if isinstance(c, ChipGroup | MultiChipGroup)
    ]
    assert bar_chips == [app.group_chips, app.z_metric_chips, app.window_chips]


def test_the_ranking_column_is_scored_over_a_fixed_five_year_sample(app, monkeypatch):
    """The window the table shows is the window the score is measured over, and
    the sample behind it does not move with it (#324)."""
    import src.layout.platform as platform_mod
    from src.config import (
        CATALOG_SCORE_MIN_SAMPLE_DAYS,
        SCORE_SAMPLE_DAYS,
        TRADING_DAYS_PER_YEAR,
    )

    seen: list[dict] = []
    real = platform_mod.rolling_metric_zscore

    def spy(prices, **kwargs):
        seen.append(kwargs)
        return real(prices, **kwargs)

    monkeypatch.setattr(platform_mod, "rolling_metric_zscore", spy)

    for label, years in (("6M", 0.5), ("1Y", 1), ("3Y", 3), ("5Y", 5)):
        seen.clear()
        app.window_chips.value = label
        assert seen, f"{label} should have re-scored the column"
        call = seen[-1]
        assert call["window"] == round(years * TRADING_DAYS_PER_YEAR)
        # The sample is the same five years at every window — which is what
        # makes the column comparable to itself, and to the Leaderboard.
        assert call["zscore_window"] == SCORE_SAMPLE_DAYS
        assert call["min_sample"] == CATALOG_SCORE_MIN_SAMPLE_DAYS

    app.window_chips.value = universe_grid_default_window()


def test_the_window_rebuilds_and_reranks_the_table(app):
    """The window does two jobs now (#324): it swaps the visible performance
    columns *and* re-measures the score, so the table is rebuilt and re-sorted
    the way a grouping change rebuilds it.

    This retires the old invariant that a window change could not disturb the
    grouping or the row order. The statistics still do not recompute — every
    window is in the frame, and the ones not on show are hidden.
    """
    columns_before = list(app.universe_grid._display.columns)

    app.window_chips.value = "5Y"

    after = list(app.universe_grid._display.columns)
    # The ranking column was renamed, so the column set is not the old one...
    assert after != columns_before
    # ...but every performance window is still there, hidden rather than dropped.
    for window in ("6M", "1Y", "3Y", "5Y"):
        assert f"{window} Sharpe" in after
    # And the grid knows which one is on show.
    assert app.universe_grid.window == "5Y"

    app.window_chips.value = universe_grid_default_window()


def test_the_window_chips_cannot_hide_the_ranking_column(app):
    # The header embeds a window label ("Normalized 1Y Sharpe …"), which
    # `_window_of` deliberately does not match — a stats-window switch must not
    # take the ranking column with it (#279, and more easily broken since #324).
    app.window_chips.value = "6M"
    assert len(_ranking_columns(app)) == 1
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
    to `SHORT_WINDOW_OPTIONS`, because that constant also drives the
    Multi-Strategy Quantitative Z-Score window, which was not asked to grow a
    year. This is the test that catches a future one-line edit to the shared
    list. (The Platform card was its third consumer until #333 moved the card
    onto `stat_windows()`.)"""
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
    # Single Strategy's panel: the Multi tab's was retired with its thresholds
    # (#345), so this is the one `QuantFilter` left.
    assert [
        label for label, _ in app.single_strategy.filters.quant.z_window_dd.options
    ] == [
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
    # The board no longer titles itself (#307), so the evidence it was rendered
    # is its caption naming the launch window.
    assert "launches" in app.highlights_cache
    assert f"past {NEW_LAUNCH_DAYS} days" in app.commentary_pane.launches_w.value
    assert app.commentary_pane.active == "commentary"  # opens on the commentary


def test_the_leaderboard_title_says_what_the_board_is_ranked_by(app):
    """The rows carry a score and a raw value, and nothing else on screen says
    the order comes from the former — so the section title does.

    The years are read from `SCORE_SAMPLE_YEARS`, which is what
    `SCORE_SAMPLE_DAYS` is derived from. A literal `5Y` in the
    caption would be free to drift from the sample the scorer standardizes
    over, and a caption that misstates the basis is worse than none — and so
    would `LOOKBACK_YEARS`, which the sample stopped following in v0.9.34
    (#361).
    """
    from src.config import SCORE_SAMPLE_DAYS, SCORE_SAMPLE_YEARS, TRADING_DAYS_PER_YEAR

    (panel,) = app.commentary_box.children[1].children[0].children
    title = panel.children[0].value

    assert f"(Ranked By Normalized {SCORE_SAMPLE_YEARS}Y Z-Score)" in title
    assert f"Normalized {LOOKBACK_YEARS}Y" not in title
    # The caption is only true while the sample really is that many years.
    assert SCORE_SAMPLE_DAYS == SCORE_SAMPLE_YEARS * TRADING_DAYS_PER_YEAR

    # The Bulletin has no basis to explain, so it carries no caption.
    bulletin = app.commentary_box.children[1].children[1].children[0]
    assert "Ranked By" not in bulletin.children[0].value


def test_the_block_is_two_sections_at_sixty_forty(app):
    # #308: both sections share, neither absorbs. The `0 0 620px` basis this
    # replaced was a width that happened to look like 60% on one screen — it
    # read as 60% at 1030px wide and 43% at 1440px. `flex: 1 1 <share>` on each
    # is what makes the ratio survive a narrower viewport.
    errors_w, row = app.commentary_box.children
    assert errors_w is app.state.errors_w  # the error strip is first, full width
    board_col, pane_col = row.children

    assert board_col.layout.flex == f"1 1 {COMMENTARY_LEADERBOARD_SHARE}"
    assert pane_col.layout.flex == f"1 1 {COMMENTARY_BULLETIN_SHARE}"
    # Load-bearing, not tidiness: a flex item's automatic minimum is its
    # content, so without this the leaderboard's four columns would refuse to
    # narrow and push the Bulletin off the row instead of both shrinking.
    assert board_col.layout.min_width == "0"
    assert pane_col.layout.min_width == "0"
    # No pixel basis survives anywhere in the block.
    assert "px" not in board_col.layout.flex
    assert "px" not in pane_col.layout.flex

    # The board sits in a `section_panel`: title line, the Window chip bar it
    # is re-ranked by, then the boxed board (#305, #306).
    (panel,) = board_col.children
    title, bar, box = panel.children
    assert "Leaderboard" in title.value
    assert bar is app.ranking_window_bar
    assert box.children == (app.leaderboard.root,)

    # The Bulletin is the same `section_panel`, differing only in what it holds
    # (#307): the board-selection chips over the container that swaps boards.
    (pane_panel,) = pane_col.children
    pane_title, pane_bar, pane_box = pane_panel.children
    assert "QIS Bulletin" in pane_title.value
    assert pane_bar is app.commentary_pane.bar
    assert pane_box.children == (app.commentary_pane.root,)


# --- two horizons: fetch fifteen years, analyse ten (#311, #322, #361) -----
#
# The fetch reaches back far enough that a score is never standardized against a
# truncated sample: the longest window the catalog offers, plus the five years
# behind it. That makes a missed slice a fifteen-year statistic under a `10Y`
# label — which is why the boundary is one helper and why these tests exist.


def test_the_fetch_reaches_further_back_than_the_analysis(app):
    from src.config import LOOKBACK_YEARS, score_history_years

    fetch_start = pd.Timestamp(app.universe_start)
    analytics_start = app._analytics_window_start()

    assert fetch_start == pd.Timestamp(app.today) - pd.DateOffset(
        years=score_history_years()
    )
    assert analytics_start == pd.Timestamp(app.today) - pd.DateOffset(
        years=LOOKBACK_YEARS
    )
    assert fetch_start < analytics_start


def test_the_fetch_covers_the_longest_window_plus_its_sample():
    """The relationship, not the number.

    `6` was the leaderboard's deepest case written as a literal; the catalog's
    is deeper, and a third consumer would have been a third literal. What is
    pinned here is that the fetch always clears the longest offered window plus
    the `SCORE_SAMPLE_YEARS` standardized behind it.
    """
    from src.config import SCORE_SAMPLE_YEARS, score_history_years, stat_windows

    longest = max(years for _, years in stat_windows())
    assert score_history_years() >= longest + SCORE_SAMPLE_YEARS
    # Today: the 10Y window over a 5Y sample — the fifteen years #361 asked for.
    assert score_history_years() == 15


def test_the_fetch_horizon_follows_the_lookback(monkeypatch):
    """Widen the analysis window and the fetch widens with it, untouched."""
    import src.config as config

    monkeypatch.setattr(config, "LOOKBACK_YEARS", 15)
    # `stat_windows()` is capped by the lookback, so 15Y comes on offer with
    # it — the deepest case is now 15Y over the same 5Y sample.
    assert max(years for _, years in config.stat_windows()) == 15.0
    assert config.score_history_years() == 20


def test_the_fetch_horizon_follows_the_sample_too(monkeypatch):
    """The other half of the sum. The sample was the lookback until v0.9.34
    (#361) made it its own constant, which is a second number the fetch has
    to follow — and the one a reader would forget, since nothing on screen
    changes when it is wrong: the scorer standardizes against whatever it is
    given and says nothing."""
    import src.config as config

    monkeypatch.setattr(config, "SCORE_SAMPLE_YEARS", 8)
    assert max(years for _, years in config.stat_windows()) == 10.0
    assert config.score_history_years() == 18


def test_the_sample_is_not_the_lookback():
    """Reading C of #361: widen the analysis, keep the scores comparable.

    A 10-year sample is a different statistic from a 5-year one, and the
    half-sample floor would then need ~22 years of history to rank at the
    deepest window — more than any strategy in the catalog has. So the two
    numbers are separate, and this is the test that fails if someone folds
    them back together.
    """
    from src.config import (
        CATALOG_SCORE_MIN_SAMPLE_DAYS,
        LOOKBACK_YEARS,
        SCORE_SAMPLE_DAYS,
        SCORE_SAMPLE_YEARS,
        TRADING_DAYS_PER_YEAR,
    )

    assert LOOKBACK_YEARS == 10
    assert SCORE_SAMPLE_YEARS == 5
    assert SCORE_SAMPLE_DAYS == SCORE_SAMPLE_YEARS * TRADING_DAYS_PER_YEAR
    assert CATALOG_SCORE_MIN_SAMPLE_DAYS == SCORE_SAMPLE_DAYS // 2


def test_a_fractional_window_rounds_the_fetch_up(monkeypatch):
    """`6M` is a real window; `pd.DateOffset(years=...)` is not fractional."""
    import src.config as config

    monkeypatch.setattr(config, "STAT_WINDOWS", (("6M", 0.5),))
    horizon = config.score_history_years()
    assert isinstance(horizon, int)
    assert horizon == 6  # ceil(5 + 0.5)


def _fifteen_years_of_prices(tickers=("AAA Index", "BBB Index", "CCC Index")):
    """~15 trading years of seeded daily prices — the fetch horizon since
    v0.9.34 (#361)."""
    import numpy as np

    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end="2026-09-18", periods=252 * 15)
    drifts = np.linspace(-0.0002, 0.0005, len(tickers))
    return pd.DataFrame(
        {
            ticker: 100.0
            * np.cumprod(1.0 + rng.normal(loc=drift, scale=0.01, size=len(idx)))
            for ticker, drift in zip(tickers, drifts, strict=True)
        },
        index=idx,
    )


def test_a_longer_fetch_moves_no_analytic():
    """The whole bet of the two horizons: more history in, same numbers out.

    Every perf window slices its own tail, so handing `universe_perf` fifteen
    years instead of eleven must be invisible. If it ever is not, the fetch
    stopped being free and a `10Y` column quietly became a fifteen-year one.
    (Eleven, not six: the shorter frame still has to cover the deepest window
    the table offers, or the `10Y` block is dashes on one side only.)
    """
    from src.stats import universe_perf

    full = _fifteen_years_of_prices()
    eleven_years = full.tail(252 * 11)

    pd.testing.assert_frame_equal(universe_perf(full), universe_perf(eleven_years))


def test_a_longer_fetch_moves_no_leaderboard_score():
    """The scorer is the one consumer that *reads* the extra history — and it
    already had all it needed at six years, so the deeper book adds nothing to
    it either. `rolling_metric_zscore` tails to `window + sample`, so both
    frames hand it the same rows."""
    from src.commentary import build_leaderboard, window_returns
    from src.stats import daily_returns

    full = _fifteen_years_of_prices()
    six_years = full.tail(252 * 6)
    meta = pd.DataFrame({"ticker": list(full.columns), "name": list(full.columns)})

    def board(prices):
        return build_leaderboard(
            meta,
            prices,
            window_returns(prices, window_days=MONTH_WINDOW),
            window_days=MONTH_WINDOW,
            history_returns=daily_returns(prices),
        )

    assert board(full) == board(six_years)


def test_no_call_site_computes_the_analytics_window_for_itself():
    """The rule that stops a fifth consumer opting out by omission.

    Four sites each carried their own copy of this expression. While the fetch
    and the analysis window were the same number a missed slice was harmless;
    now it is five years of extra history under a `10Y` label.
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

    Measured against the fifteen-year fetch start, a benchmark carrying a full
    ten years of history looks five years late and would trip a warning it
    does not deserve.
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
