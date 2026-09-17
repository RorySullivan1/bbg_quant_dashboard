"""Dark grid theme survives a Refresh (regression for the reverted background).

The dark ``grid_style`` (background / zebra / header colors) is applied once at
construction via ``_dark_grid_kwargs``. Reassigning ``grid.data`` on a Refresh
rebuilds the frontend grid model and drops the styling back to ipydatagrid's
default (white) background. ``_reassert_dark_theme`` re-applies the dark theme
and force-syncs ``grid_style`` to the frontend.

`UniverseGrid` is deliberately absent since v0.9.18 (#263): it is an `itables`
table whose chrome is ordinary page CSS, which a data swap cannot reset, so it
has no theme-refresh invariant to pin and is not a `_Grid`.

Since #223 this is **structural**: every ipydatagrid grid is a `_Grid` subclass whose only
write path is `_set_data`, which re-asserts the theme itself. So rather than
re-testing each `_update_*_grid` call site, these tests pin the invariant at the
base class — and `test_every_grid_class_is_covered` fails if a new subclass is
added without a case here, which is the failure mode that produced the original
bug.
"""

from __future__ import annotations

import pandas as pd
import pytest
from src.layout import grids
from src.layout.grids import (
    CalendarGrid,
    PerfGrid,
    _Grid,
    _reassert_dark_theme,
)
from src.style import Color


def _spy_send_state(grid):
    calls: list = []
    orig = grid.send_state

    def spy(key=None):
        calls.append(key)
        return orig(key)

    grid.send_state = spy
    return calls


def _meta():
    return pd.DataFrame(
        {
            "ticker": ["A Index"],
            "name": ["Alpha"],
            "asset_class": ["Equity"],
            "solution": ["ARP"],
            "category": ["Core"],
            "family": ["Core"],
            "return_type": ["Total"],
            "live_date": pd.to_datetime(["2020-01-01"]),
        }
    )


def _perf_frame():
    cols = pd.MultiIndex.from_tuples(
        [("1Y", "Return"), ("1Y", "Vol"), ("1Y", "Sharpe"), ("1Y", "Max DD")]
    )
    pt = pd.DataFrame(
        [[0.1, 0.2, 0.5, -0.1]],
        index=pd.Index(["A Index"], name="ticker"),
        columns=cols,
    )
    return pt, _meta()


def _calendar_table():
    return pd.DataFrame([[0.01, 0.02]], index=pd.Index([2024]), columns=["Jan", "Feb"])


#: (label, class, populated-update thunk) per concrete grid. The thunk takes the
#: grid object so each case drives that grid's real `update` signature.
GRID_CASES: list[tuple[str, type, object]] = [
    ("perf", PerfGrid, lambda g: g.update(*_perf_frame())),
    ("calendar", CalendarGrid, lambda g: g.update(_calendar_table(), kind="absolute")),
]


def test_reassert_dark_theme_force_syncs_grid_style():
    g = PerfGrid()
    calls = _spy_send_state(g.grid)
    _reassert_dark_theme(g.grid)
    assert "grid_style" in calls  # force-sent regardless of value equality
    assert g.grid.grid_style["background_color"] == Color.CHROME_BG.value


@pytest.mark.parametrize(
    "label,cls,populate", GRID_CASES, ids=[c[0] for c in GRID_CASES]
)
def test_grid_keeps_dark_theme_after_update(label, cls, populate):
    g = cls()
    calls = _spy_send_state(g.grid)
    populate(g)
    assert g.grid.grid_style["background_color"] == Color.CHROME_BG.value
    assert "grid_style" in calls


@pytest.mark.parametrize(
    "label,cls,populate", GRID_CASES, ids=[c[0] for c in GRID_CASES]
)
def test_grid_keeps_dark_theme_on_clear(label, cls, populate):
    # The empty path is a separate branch in every `update` — it must re-assert
    # too, or clearing a selection reverts the grid to white.
    g = cls()
    populate(g)  # populate first, so `clear` is a real transition
    calls = _spy_send_state(g.grid)
    g.clear()
    assert g.grid.grid_style["background_color"] == Color.CHROME_BG.value
    assert "grid_style" in calls


def test_every_grid_class_is_covered():
    """A new `_Grid` subclass must arrive with a case above.

    This is the guard that makes the invariant hold for grids that don't exist
    yet — the original bug was exactly "a new update path forgot the re-assert".
    """
    defined = {
        obj
        for obj in vars(grids).values()
        if isinstance(obj, type) and issubclass(obj, _Grid) and obj is not _Grid
    }
    assert defined == {cls for _, cls, _ in GRID_CASES}
