"""Unit tests for ``DashboardState`` — the explicit session-state object.

The point of Workstream D was to make the state legible and testable *without*
standing up the whole widget tree, so these construct the dataclass with cheap
placeholder handles and assert its defaults and isolation.
"""

from __future__ import annotations

import pandas as pd
from src.config import filter_dimensions
from src.layout.state import DashboardState
from src.stats import BasketWindow


def _make(**overrides) -> DashboardState:
    """A DashboardState with throwaway handles (no real widgets needed)."""
    handles = dict(
        basket=object(),
        status_w=object(),
        overlay_w=object(),
        universe_grid=object(),
        selected_perf_grid=object(),
        pane_left=object(),
        pane_right=object(),
        errors_w=object(),
    )
    handles.update(overrides)
    return DashboardState(**handles)


def test_defaults():
    s = _make()
    # The panel opens on the first filter dimension, which is the top tier.
    assert s.active_filter == filter_dimensions()[0].key == "solution"
    # The window is derived, never chosen (#341 dec. 12): `sync_guard`,
    # `last_sel_key` and `cur_bound_*` went with the date pickers.
    assert s.basket_window.start is None and s.basket_window.end is None
    assert s.basket_window.binding_start is None
    assert s.init_errors == []
    assert isinstance(s.universe_prices, pd.DataFrame) and s.universe_prices.empty
    assert (
        isinstance(s.arp_universe_prices, pd.DataFrame) and s.arp_universe_prices.empty
    )


def test_mutable_defaults_are_per_instance():
    # Each instance must get its own list / frame (field default_factory),
    # never a shared mutable — otherwise one app's errors would leak to another.
    a, b = _make(), _make()
    a.init_errors.append("boom")
    a.universe_prices = pd.DataFrame({"X Index": [1.0, 2.0]})
    assert b.init_errors == []
    assert b.universe_prices.empty
    assert a.init_errors == ["boom"]


def test_fields_are_assignable():
    s = _make()
    s.active_filter = "return_type"
    s.basket_window = BasketWindow(
        pd.Timestamp("2021-01-04"), pd.Timestamp("2026-01-02"), "AAA Index", "BBB Index"
    )
    assert s.active_filter == "return_type"
    assert s.basket_window.binding_start == "AAA Index"
    assert s.basket_window.binding_end == "BBB Index"


def test_holds_the_passed_widget_handles():
    basket, status = object(), object()
    s = _make(basket=basket, status_w=status)
    assert s.basket is basket
    assert s.status_w is status
