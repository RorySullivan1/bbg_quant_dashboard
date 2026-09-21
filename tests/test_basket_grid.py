"""`BasketGrid` — the catalog table as the picker (#343).

**What these can and cannot reach.** The reconciliation is kernel-side and is
pinned here in full: the diff by ticker, the in-frame restriction, the cap
rejection and the re-push. The *browser* half — the tick column, the Select
buttons, the group-header click — cannot be exercised without a DOM, so the
walking rule is pinned through `group_member_rows`, the Python specification
the JS transcribes, and the rest is the Voila gate the issue asks for.
"""

from __future__ import annotations

import pandas as pd
from src.data import load_metadata
from src.layout.basket import Basket
from src.layout.grids import BasketGrid, group_member_rows


def _grid(cap: int = 25) -> tuple[BasketGrid, Basket, list]:
    basket = Basket(cap=cap)
    limits: list = []
    grid = BasketGrid(basket, on_limit=limits.append)
    grid.update(load_metadata(), pd.DataFrame())
    return grid, basket, limits


def _select(grid: BasketGrid, positions: list[int]) -> None:
    """What the widget does when the browser reports a selection change."""
    grid._on_selected_rows({"new": positions})


# --- the diff -----------------------------------------------------------------


def test_ticking_rows_adds_exactly_those_tickers():
    grid, basket, _ = _grid()
    _select(grid, [0, 2])
    assert basket.value == (grid._tickers[0], grid._tickers[2])


def test_one_add_and_one_remove_in_a_single_change():
    """The acceptance case: two new rows, one gone, one event."""
    grid, basket, _ = _grid()
    _select(grid, [0, 1])
    _select(grid, [1, 3, 4])
    assert set(basket.value) == {grid._tickers[1], grid._tickers[3], grid._tickers[4]}


def test_an_empty_selection_empties_the_in_frame_members():
    """Unlike the Platform's grid, a deselection is a real event here —
    it is *Select none*, or the last ticked row being untoggled."""
    grid, basket, _ = _grid()
    _select(grid, [0, 1])
    _select(grid, [])
    assert basket.value == ()


def test_a_member_outside_the_frame_is_never_touched_by_a_table_event():
    """A basket member the filters hide keeps its card (#341 dec. 6)."""
    grid, basket, _ = _grid()
    basket.add("HIDDEN Index")  # not in the frame at all
    _select(grid, [0])
    assert "HIDDEN Index" in basket.value
    _select(grid, [])
    assert basket.value == ("HIDDEN Index",)


def test_a_position_outside_the_frame_is_ignored():
    grid, basket, _ = _grid()
    _select(grid, [0, 9999])
    assert basket.value == (grid._tickers[0],)


def test_an_unchanged_selection_does_not_write_the_basket():
    grid, basket, _ = _grid()
    _select(grid, [0, 1])
    fires: list = []
    basket.observe(lambda c: fires.append(c["new"]), names="value")
    _select(grid, [1, 0])  # same set, different order
    assert fires == []


# --- the cap ------------------------------------------------------------------


def test_over_the_cap_the_basket_is_unchanged_and_the_table_is_put_back():
    grid, basket, limits = _grid(cap=2)
    _select(grid, [0, 1])
    before = basket.value

    _select(grid, [0, 1, 2, 3])

    assert basket.value == before, "a rejected add leaves the basket alone"
    assert list(grid.widget.selected_rows) == sorted(
        grid.positions_of(before)
    ), "the browser drew the ticks already — the table has to be put back"
    assert len(limits) == 1
    assert (limits[0].accepted, limits[0].shown, limits[0].cap) == (False, 4, 2)


def test_a_group_worth_of_rows_over_the_cap_is_rejected_whole():
    """Same path as *Select all shown* — the kernel does not seat a subset."""
    grid, basket, limits = _grid(cap=3)
    _select(grid, list(range(8)))
    assert basket.value == ()
    assert limits and limits[0].shown == 8


def test_a_swap_at_the_cap_is_one_write_and_succeeds():
    """Untick one, tick another in the same change: the target is resolved
    first, so the cap sees the size it would actually reach."""
    grid, basket, limits = _grid(cap=2)
    _select(grid, [0, 1])
    fires: list = []
    basket.observe(lambda c: fires.append(c["new"]), names="value")

    _select(grid, [1, 2])

    assert set(basket.value) == {grid._tickers[1], grid._tickers[2]}
    assert limits == []
    assert len(fires) == 1, "one click is one basket event, not a remove and an add"


def test_an_over_cap_change_that_also_removes_applies_neither():
    """All or nothing. Applying the remove and letting the add fail behind it
    would honour half a gesture the user made in one click."""
    grid, basket, limits = _grid(cap=2)
    _select(grid, [0, 1])
    before = basket.value

    # Untick row 0 and tick rows 2 and 3 — three names for two seats.
    _select(grid, [1, 2, 3])

    assert basket.value == before, "the remove must not survive a rejected add"
    assert len(limits) == 1 and limits[0].shown == 3


# --- the push back ------------------------------------------------------------


def test_a_basket_change_from_elsewhere_re_ticks_the_table():
    """A card's x, or Clear all."""
    grid, basket, _ = _grid()
    basket.add([grid._tickers[2], grid._tickers[5]])
    assert list(grid.widget.selected_rows) == [2, 5]
    basket.clear()
    assert list(grid.widget.selected_rows) == []


def test_ticks_follow_the_frame_after_a_regroup():
    """The acceptance case: after `update` with a re-ordered frame the widget's
    positions are `positions_of(basket.value)` — never the previous frame's."""
    grid, basket, _ = _grid()
    basket.add([grid._tickers[0], grid._tickers[-1]])

    grid.set_group_fields(("asset_class",))
    grid.update(load_metadata(), pd.DataFrame())

    assert list(grid.widget.selected_rows) == sorted(grid.positions_of(basket.value))
    assert set(grid.tickers_at(grid.widget.selected_rows)) == set(basket.value)


def test_the_push_is_not_read_back_as_a_user_edit():
    """Without the guard a push would diff against itself and empty the
    basket's out-of-frame members."""
    grid, basket, _ = _grid()
    basket.add("HIDDEN Index")
    basket.add(grid._tickers[0])
    grid.push_ticks()
    assert "HIDDEN Index" in basket.value


# --- the group header's walking rule ------------------------------------------
#
# `levels` is one entry per rendered row: a header's nesting level, or None for
# a data row. This is the rule `_JS_GROUP_SELECT` transcribes.


def test_a_leaf_group_header_takes_only_its_own_rows():
    levels = [1, None, None, 1, None]
    assert group_member_rows(levels, 0) == [1, 2]
    assert group_member_rows(levels, 3) == [4]


def test_an_outer_header_takes_every_row_nested_under_it():
    #  0: Solution
    #    1: Category A
    #       2,3: rows
    #    4: Category B
    #       5: row
    #  6: another Solution
    #       7: row
    levels = [0, 1, None, None, 1, None, 0, None]
    assert group_member_rows(levels, 0) == [2, 3, 5]
    assert group_member_rows(levels, 1) == [2, 3]
    assert group_member_rows(levels, 4) == [5]
    assert group_member_rows(levels, 6) == [7]


def test_a_header_with_no_rows_under_it_takes_nothing():
    assert group_member_rows([0, 0, None], 0) == []


def test_a_non_header_position_takes_nothing():
    assert group_member_rows([0, None], 1) == []
    assert group_member_rows([0, None], 99) == []


def test_the_walk_stops_at_a_sibling_not_at_the_end_of_the_table():
    levels = [1, None, 1, None, 1, None]
    assert group_member_rows(levels, 0) == [1]


def test_a_deeper_header_does_not_stop_an_outer_walk():
    """Three tiers: the Solution header must reach the Family rows."""
    levels = [0, 1, 2, None, 2, None, 1, 2, None]
    assert group_member_rows(levels, 0) == [3, 5, 8]
