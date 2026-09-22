"""`StrategyGrid` and `Pick` — the catalog table as the Single Strategy
picker (#365).

The kernel half is pinned here in full: a click sets the pick, another entry
point setting the pick lights the row, and the pick survives the rebuild every
options change forces. The *browser* half — the click itself, the search box,
the per-column filter row — needs a DOM and is the Voila gate #365 asks for.

What distinguishes these from `test_basket_grid.py` is the shape of the
selection, and the two places that shape shows: an empty `selected_rows` is
swallowed here where the basket reads it as *Select none*, and a pick outside
the frame keeps its value where a basket member outside the frame keeps its
card.
"""

from __future__ import annotations

import pandas as pd
from src.data import load_metadata
from src.layout.basket import Pick
from src.layout.grids import StrategyGrid


def _grid() -> tuple[StrategyGrid, Pick]:
    pick = Pick()
    grid = StrategyGrid(pick)
    grid.update(load_metadata(), pd.DataFrame())
    return grid, pick


def _select(grid: StrategyGrid, positions: list[int]) -> None:
    """What the widget does when the browser reports a selection change."""
    grid._on_selected_rows({"new": positions})


# --- Pick ---------------------------------------------------------------------


def test_a_pick_starts_empty_and_holds_one_ticker():
    pick = Pick()
    assert pick.value is None
    pick.value = "AAA Index"
    assert pick.value == "AAA Index"
    assert "AAA Index" in pick
    pick.clear()
    assert pick.value is None


def test_a_pick_is_observable_like_the_widget_it_replaced():
    """Every entry point writes `.value` and every view observes it — the
    surface `_show_in_single_strategy` used to write on a `W.Dropdown`."""
    pick = Pick()
    seen: list[str] = []
    pick.observe(lambda c: seen.append(c["new"]), names="value")
    pick.value = "AAA Index"
    pick.value = "BBB Index"
    assert seen == ["AAA Index", "BBB Index"]


# --- the table writes the pick -------------------------------------------------


def test_clicking_a_row_picks_that_strategy():
    grid, pick = _grid()
    _select(grid, [2])
    assert pick.value == grid._tickers[2]


def test_clicking_another_row_moves_the_pick():
    grid, pick = _grid()
    _select(grid, [0])
    _select(grid, [3])
    assert pick.value == grid._tickers[3]


def test_a_deselection_is_swallowed_not_read_as_unpicking():
    """Clicking the lit row again must not blank the tab.

    The opposite of `BasketGrid`, where an empty list is *Select none* and has
    to empty the basket — which is why the two handlers are separate rather
    than one with a flag.
    """
    grid, pick = _grid()
    _select(grid, [1])
    _select(grid, [])
    assert pick.value == grid._tickers[1]


def test_a_position_outside_the_frame_is_ignored():
    """The #265 race: a re-render landing between the click and the callback."""
    grid, pick = _grid()
    _select(grid, [0])
    _select(grid, [len(grid._tickers) + 5])
    assert pick.value == grid._tickers[0]


# --- the pick writes the table -------------------------------------------------


def test_setting_the_pick_lights_its_row():
    """A catalog row, a Leaderboard row, a points-table row or a basket card
    sets the pick; the grid is a view of it."""
    grid, pick = _grid()
    pick.value = grid._tickers[4]
    assert grid.widget.selected_rows == [4]


def test_a_pick_the_frame_does_not_hold_lights_nothing_and_survives():
    """A pick the filters hide keeps its value (#363 dec. 2).

    `positions_of` skips a name the frame does not carry, so the table simply
    shows nothing selected — the pick is never cleared to match the view.
    """
    grid, pick = _grid()
    pick.value = "NOT IN THE CATALOG Index"
    assert grid.widget.selected_rows == []
    assert pick.value == "NOT IN THE CATALOG Index"


def test_the_pick_is_re_derived_by_ticker_after_a_rebuild():
    """Positions are worthless across a rebuild; tickers are not.

    itables destroys and re-news the table on every options change, so the
    row a position pointed at in the previous frame is a different row in the
    next one. Narrowing the frame to a different order is the cheapest way to
    force that here.
    """
    meta = load_metadata()
    grid, pick = _grid()
    target = grid._tickers[5]
    pick.value = target

    grid.update(meta.iloc[::-1].reset_index(drop=True), pd.DataFrame())

    assert grid.widget.selected_rows == grid.positions_of([target])
    assert grid.tickers_at(grid.widget.selected_rows) == [target]


def test_a_narrowing_rebuild_does_not_raise_on_stale_positions():
    """itables validates `selected_rows` against the incoming data and raises
    *Selected rows out of range* when the new frame is shorter — which is
    every narrowing filter. Clearing before the write is what survives it."""
    meta = load_metadata()
    grid, pick = _grid()
    # The last *row*, which grouping and sorting have reordered — not the last
    # record in `meta`.
    target = grid._tickers[-1]
    pick.value = target

    grid.update(meta.iloc[:2].reset_index(drop=True), pd.DataFrame())

    assert grid.widget.selected_rows == []
    assert pick.value == target


def test_a_push_is_not_read_back_as_a_user_edit():
    """The `_pushing` guard: the widget re-sends `selected_rows` after every
    rebuild, and without it a push would diff against itself."""
    grid, pick = _grid()
    seen: list[str] = []
    pick.observe(lambda c: seen.append(c["new"]), names="value")

    pick.value = grid._tickers[2]
    grid.update(load_metadata(), pd.DataFrame())

    assert seen == [grid._tickers[2]], "the rebuild must not re-write the pick"
