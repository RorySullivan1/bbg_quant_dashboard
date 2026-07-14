"""Dark grid theme survives a Refresh (regression for the reverted background).

The dark ``grid_style`` (background / zebra / header colors) is applied once at
construction via ``_dark_grid_kwargs``. Reassigning ``grid.data`` on a Refresh
rebuilds the frontend grid model and drops the styling back to ipydatagrid's
default (white) background. ``_reassert_dark_theme`` re-applies the dark theme
on every ``_update_*_grid`` and force-syncs ``grid_style`` to the frontend.

These tests assert that, after a data update, each themed grid still carries the
dark ``grid_style`` *and* that ``grid_style`` is force-sent to the frontend (an
equal dict would otherwise short-circuit the traitlets diff and never re-reach
it, leaving the frontend on the reverted white background).
"""

from __future__ import annotations

import pandas as pd
from src.layout.grids import (
    _calendar_grid,
    _perf_grid,
    _reassert_dark_theme,
    _universe_grid,
    _update_calendar_grid,
    _update_perf_grid,
    _update_universe_grid,
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


def _perf_frame():
    cols = pd.MultiIndex.from_tuples(
        [("1Y", "Return"), ("1Y", "Vol"), ("1Y", "Sharpe"), ("1Y", "Max DD")]
    )
    pt = pd.DataFrame(
        [[0.1, 0.2, 0.5, -0.1]],
        index=pd.Index(["A Index"], name="ticker"),
        columns=cols,
    )
    meta = pd.DataFrame(
        {
            "ticker": ["A Index"],
            "name": ["Alpha"],
            "asset_class": ["Equity"],
            "theme": ["Core"],
        }
    )
    return pt, meta


def test_reassert_dark_theme_force_syncs_grid_style():
    grid = _perf_grid()
    calls = _spy_send_state(grid)
    _reassert_dark_theme(grid)
    assert "grid_style" in calls  # force-sent regardless of value equality
    assert grid.grid_style["background_color"] == Color.CHROME_BG.value


def test_perf_grid_keeps_dark_theme_after_update():
    grid = _perf_grid()
    pt, meta = _perf_frame()
    calls = _spy_send_state(grid)
    _update_perf_grid(grid, pt, meta)
    assert grid.grid_style["background_color"] == Color.CHROME_BG.value
    assert "grid_style" in calls


def test_perf_grid_keeps_dark_theme_on_empty_update():
    grid = _perf_grid()
    calls = _spy_send_state(grid)
    _update_perf_grid(grid, pd.DataFrame(), pd.DataFrame())
    assert grid.grid_style["background_color"] == Color.CHROME_BG.value
    assert "grid_style" in calls


def test_universe_grid_keeps_dark_theme_after_update():
    grid = _universe_grid()
    meta = pd.DataFrame(
        {
            "ticker": ["A Index"],
            "name": ["Alpha"],
            "asset_class": ["Equity"],
            "category": ["Core"],
            "theme": ["Core"],
            "return_type": ["Total"],
            "live_date": pd.to_datetime(["2020-01-01"]),
        }
    )
    calls = _spy_send_state(grid)
    _update_universe_grid(grid, meta, pd.DataFrame())
    assert grid.grid_style["background_color"] == Color.CHROME_BG.value
    assert "grid_style" in calls


def test_calendar_grid_keeps_dark_theme_after_update():
    grid = _calendar_grid()
    table = pd.DataFrame([[0.01, 0.02]], index=pd.Index([2024]), columns=["Jan", "Feb"])
    calls = _spy_send_state(grid)
    _update_calendar_grid(grid, table, kind="absolute")
    assert grid.grid_style["background_color"] == Color.CHROME_BG.value
    assert "grid_style" in calls
