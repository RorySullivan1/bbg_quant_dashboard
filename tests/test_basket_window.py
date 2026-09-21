"""The analysis window, derived from the basket (#341 dec. 12, #344).

The two date pickers that used to let the user narrow inside the overlap are
gone. What replaced them is one function of the basket's prices, so these pin
the arithmetic — `max(first valid) → min(last valid)` — and the thing the
pickers never provided: **which member sets each edge**, so shortening the
sample is a decision the user can act on rather than a number they can only
argue with.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.stats import BasketWindow, basket_window


def _staggered() -> pd.DataFrame:
    """Three members: one full history, one short, one stale."""
    idx = pd.bdate_range("2020-01-01", "2026-01-01")
    frame = pd.DataFrame({"LONG": 1.0, "SHORT": 1.0, "STALE": 1.0}, index=idx)
    frame.loc[:"2022-06-30", "SHORT"] = np.nan  # starts late
    frame.loc["2025-01-01":, "STALE"] = np.nan  # stops early
    return frame


def test_the_window_is_the_intersection_not_the_union():
    """Every day in it is a day every member traded."""
    frame = _staggered()
    window = basket_window(frame)

    expected_start = frame["SHORT"].first_valid_index()
    expected_end = frame["STALE"].last_valid_index()
    assert window.start == expected_start
    assert window.end == expected_end
    assert window.start > frame.index[0], "a union would start at the earliest"
    assert window.end < frame.index[-1], "a union would end at the latest"


def test_the_binding_members_are_named():
    window = basket_window(_staggered())
    assert window.binding_start == "SHORT"
    assert window.binding_end == "STALE"


def test_removing_the_binding_member_moves_the_start_earlier():
    """The one-click decision the readout exists to enable."""
    frame = _staggered()
    before = basket_window(frame)
    after = basket_window(frame.drop(columns=[before.binding_start]))
    assert after.start < before.start


def test_a_single_member_binds_both_edges_itself():
    frame = _staggered()[["SHORT"]]
    window = basket_window(frame)
    assert window.binding_start == "SHORT"
    assert window.binding_end == "SHORT"


def test_years_is_the_span():
    window = basket_window(_staggered())
    assert window.years == (window.end - window.start).days / 365.25


def test_an_empty_basket_has_no_window():
    window = basket_window(pd.DataFrame())
    assert window == BasketWindow(None, None)
    assert window.years == 0.0


def test_members_with_no_shared_day_have_no_window():
    idx = pd.to_datetime(["2020-01-01", "2020-01-02"])
    frame = pd.DataFrame({"A": [1.0, np.nan], "B": [np.nan, 1.0]}, index=idx)
    window = basket_window(frame)
    assert window.start is None and window.end is None
    assert window.binding_start is None


def test_a_tie_is_broken_by_column_order():
    """Two members starting on the same date: the first named wins. Either is
    correct; the choice only has to be stable, or the readout would flicker
    between two equally true answers."""
    idx = pd.bdate_range("2020-01-01", periods=10)
    frame = pd.DataFrame({"FIRST": 1.0, "SECOND": 1.0}, index=idx)
    assert basket_window(frame).binding_start == "FIRST"
    assert basket_window(frame[["SECOND", "FIRST"]]).binding_start == "SECOND"
