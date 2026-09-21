"""The `CatalogTable` base the Platform's grid and the basket's share (#342).

Two things are pinned here. **The Platform's options did not move**: the
extraction added two keyword arguments, and the `single` path has to produce
exactly what it produced before, because every one of those options was argued
for somewhere and none of them was re-decided. And **the position ↔ ticker map
guards both ends** — itables destroys and re-news the table on every options
change, so a position from the previous frame is a live hazard, not a
hypothetical one (#265).
"""

from __future__ import annotations

import pandas as pd
from src.data import load_metadata
from src.layout.grids import (
    CatalogTable,
    UniverseGrid,
    _catalog_table_options,
)


def _catalog() -> pd.DataFrame:
    return load_metadata()


# --- the single path is unchanged ---------------------------------------------


def test_single_select_options_are_the_pre_extraction_defaults():
    """`select_style` / `select_buttons` default to what the Platform had."""
    options = _catalog_table_options(pd.DataFrame(), [])
    assert options["select"] == {"style": "single"}
    assert options["layout"]["topStart"] == "search"


def test_universe_grid_options_match_the_bare_builder():
    """The subclass adds no options of its own — it only reads a click."""
    grid = UniverseGrid()
    grid.update(_catalog(), pd.DataFrame())
    direct = _catalog_table_options(
        grid._display,
        grid._groups,
        grid.window,
        zscore_col=grid._zscore_col,
    )
    assert grid.table_options() == direct


def test_multi_select_options_carry_the_style_and_the_buttons():
    table = CatalogTable(select_style="multi", select_buttons=True)
    options = table.table_options()
    assert options["select"] == {"style": "multi"}
    assert options["layout"]["topStart"] == [
        "search",
        {"buttons": ["selectAll", "selectNone"]},
    ]


def test_the_buttons_are_opt_in():
    """A table that does not ask for them keeps the plain search slot."""
    assert (
        CatalogTable(select_style="multi").table_options()["layout"]["topStart"]
        == "search"
    )


# --- the position <-> ticker map ----------------------------------------------


def test_positions_and_tickers_round_trip_on_a_grouped_frame():
    table = CatalogTable()
    table.update(_catalog(), pd.DataFrame())
    tickers = list(table._tickers[:4])
    assert table.tickers_at(table.positions_of(tickers)) == tickers


def test_positions_of_skips_tickers_the_frame_does_not_hold():
    """A basket member hidden by the filters is the normal case, not an error."""
    table = CatalogTable()
    table.update(_catalog(), pd.DataFrame())
    held = list(table._tickers[:2])
    assert table.positions_of([held[0], "NOT A TICKER", held[1]]) == (
        table.positions_of(held)
    )


def test_tickers_at_skips_positions_outside_the_frame():
    """The #265 race: a re-render landing between a click and its callback."""
    table = CatalogTable()
    table.update(_catalog(), pd.DataFrame())
    size = len(table._tickers)
    assert table.tickers_at([0, size, size + 99, -1]) == [table._tickers[0]]


def test_positions_follow_a_regrouped_frame():
    """Positions are re-derived per frame — the whole reason the basket holds
    tickers and the grid holds the map."""
    table = CatalogTable()
    table.update(_catalog(), pd.DataFrame())
    ticker = table._tickers[-1]
    before = table.positions_of([ticker])

    table.set_group_fields(("asset_class",))
    table.update(_catalog(), pd.DataFrame())
    after = table.positions_of([ticker])

    assert after, "the ticker is still in the frame"
    assert table.tickers_at(after) == [ticker]
    if before != after:
        assert table.tickers_at(before) != [ticker]


def test_the_base_ignores_a_selection_change():
    """A table with no click behaviour needs no handler — and must not raise."""
    table = CatalogTable()
    table.update(_catalog(), pd.DataFrame())
    table.widget.selected_rows = [0]  # must not raise


def test_universe_grid_still_swallows_its_two_non_events():
    picked: list[str] = []
    grid = UniverseGrid(on_pick=picked.append)
    grid.update(_catalog(), pd.DataFrame())

    grid._on_selected_rows({"new": []})
    assert picked == [], "a deselection is not a pick"

    grid._on_selected_rows({"new": [len(grid._tickers) + 10]})
    assert picked == [], "a position outside the frame is not a pick"

    grid._on_selected_rows({"new": [0]})
    assert picked == [grid._tickers[0]]
