"""The Multi-Strategy picker, wired into the app (#341).

**The picker is the catalog table.** This file used to test a
`CheckboxMultiSelect` — a 240px scrollable checkbox list of the whole catalog,
with the cap guarded on the widget and a `Selected Strategies: n/25` caption
above it. All three are gone: the rows are the Platform tab's own grouped
table, the cap belongs to `Basket`, and the count is the Basket strip's note.

These are the *integration* assertions — that the tab is assembled from those
pieces and that they are wired to each other. `Basket`'s own rules live in
`test_basket.py` and the table's reconciliation in `test_basket_grid.py`.
"""

from __future__ import annotations

import ipywidgets as W
import pytest
from src.layout.app import DashboardApp


@pytest.fixture
def app() -> DashboardApp:
    return DashboardApp(verbose=False)


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _mount_multi_strategy(app) -> None:
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Multi-Strategy"
    ).click()


# --- the tab is the table + the strip ----------------------------------------


def test_the_tab_is_a_section_a_bar_and_the_basket_table(app):
    _mount_multi_strategy(app.root)
    assert app.basket_grid.widget in list(_walk(app.root))
    assert app.basket_grid.table_options()["select"] == {"style": "multi"}
    # The bar's four sections, in the order they act in.
    headings = [w.value for w in _walk(app.basket_bar) if isinstance(w, W.HTML)]
    assert headings[0] == "Table view"
    assert headings[1:5] == [
        "Group by",
        "Window",
        "Benchmark",
        "Filter",
    ], "the bar reads in the order the controls act in"


def test_the_retired_idioms_are_gone_from_the_multi_strategy_assembly(app):
    """The v0.8 idiom this replaced: an accordion over a checkbox list, with
    pill-tabs and two date pickers for the analysis range."""
    _mount_multi_strategy(app.root)
    panel = app._top_panels["selected"]
    assert not [w for w in _walk(panel) if isinstance(w, W.Accordion)]
    # Scoped to the selection surface: the analysis panes below it have
    # checkboxes of their own (Benchmark / Regime), which this never touched.
    selection = list(_walk(app.basket_section)) + list(_walk(app.basket_strip))
    assert not [
        w for w in selection if isinstance(w, W.Checkbox)
    ], "the 240px checkbox picker is gone — the rows are the catalog table"
    widgets = list(_walk(panel))
    # The only date pickers left are the filter strip's **Launch date** — a
    # characteristic of a strategy. The *analysis range* pair is gone: that
    # window is derived from the basket and nothing can move it (#341 dec. 12).
    pickers = [w for w in widgets if isinstance(w, W.DatePicker)]
    assert pickers == [app.filter_strip.live_min, app.filter_strip.live_max]


def test_the_startup_selection_seeds_the_basket_and_ticks_the_table(app):
    assert 1 <= len(app.basket.value) <= 5
    ticked = app.basket_grid.tickers_at(app.basket_grid.widget.selected_rows)
    assert set(ticked) == set(app.basket.value) & set(app.basket_grid._tickers)


# --- the basket is the only selection state ----------------------------------


def test_every_entry_point_writes_through_the_basket(app):
    """A row tick, a card's x and Clear all all land on the same object."""
    grid, basket = app.basket_grid, app.basket

    grid._on_selected_rows({"new": [0]})
    assert basket.value == (grid._tickers[0],)

    card = app.basket_cards.children[0]
    card.children[-1].click()  # the x
    assert basket.value == ()

    grid._on_selected_rows({"new": [0, 1]})
    assert len(basket.value) == 2
    next(
        w
        for w in _walk(app.basket_strip)
        if isinstance(w, W.Button) and w.description == "Clear all"
    ).click()
    assert basket.value == ()


def test_the_cap_is_rejected_on_the_basket_and_the_popup_names_the_count(app):
    basket = app.basket
    basket.clear()
    result = basket.add([f"SYNTH{i} Index" for i in range(basket.cap + 1)])
    assert result.accepted is False
    assert basket.value == ()

    app._on_basket_limit(result)
    assert "is-hidden" not in app.limit_popup_w.value
    assert str(result.shown) in app.limit_popup_w.value
    assert str(basket.cap) in app.limit_popup_w.value


def test_the_strip_note_tracks_the_basket(app):
    app.basket.clear()
    assert "0 / 25 selected" in app.basket_note_w.value
    app.basket.add(app.basket_grid._tickers[0])
    assert "1 / 25 selected" in app.basket_note_w.value


# --- filters narrow the table, never the basket ------------------------------


def test_a_filter_narrows_the_table_and_leaves_the_basket_alone(app):
    """A member the filter hides keeps its place and its card (#341 dec. 6)."""
    grid, basket = app.basket_grid, app.basket
    basket.replace(list(grid._tickers))
    held = basket.value
    group = app.filter_strip.groups["asset_class"]

    group.value = (group.options[0][1],)
    assert len(grid._tickers) < len(held), "the filter narrowed the table"
    assert basket.value == held, "the basket is untouched by a filter"
    assert len(app.basket_cards.children) == len(held), "every member keeps a card"
    assert set(grid.tickers_at(grid.widget.selected_rows)) == set(held) & set(
        grid._tickers
    )

    group.value = ()
    assert set(grid.tickers_at(grid.widget.selected_rows)) == set(held)


def test_the_filter_chip_badges_count_active_values(app):
    group = app.filter_strip.groups["asset_class"]
    group.value = ()
    assert "Asset Class" in [label for label, _ in app.filter_dim_chips.options]

    group.value = (group.options[0][1],)
    assert "Asset Class · 1" in [label for label, _ in app.filter_dim_chips.options]


def test_switching_filter_dimension_keeps_every_dimension_s_ticks(app):
    strip = app.filter_strip
    group = strip.groups["asset_class"]
    group.value = (group.options[0][1],)

    app.filter_dim_chips.value = "solution"
    assert group.value, "switching dimension must not clear another's values"
    assert group.layout.display == "none"
    assert strip.groups["solution"].layout.display == ""


# --- no inline duplication ---------------------------------------------------


def test_no_inline_filter_duplication_in_the_controller():
    """Regression guard for #155: the filter reducer stays out of the
    controller. `apply_filters` is `FilterStrip`'s and `FilterPanel`'s to call;
    `app.py` composes them."""
    from pathlib import Path

    src = Path("src/layout/app.py").read_text()
    assert "def _quant_keep" not in src
    assert "def _quant_thresholds" not in src
    assert "_q_row(" not in src
    # And the quant metrics reach the table as columns, not thresholds (#345).
    assert "QuantColumns" in src
