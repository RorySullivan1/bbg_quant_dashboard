"""The typed analysis panes (#216).

`_make_analysis_pane` / `_make_single_analysis_pane` used to return a
`SimpleNamespace`, so a factory that forgot a field produced a pane that only
failed later, inside whichever renderer reached for it. These assert the shape
the renderers depend on.
"""

from __future__ import annotations

import dataclasses

import ipywidgets as W
import plotly.graph_objects as go
import pytest
from ipydatagrid import DataGrid
from src.layout.panes import (
    ANALYSIS_OPTIONS,
    SINGLE_ANALYSIS_OPTIONS,
    AnalysisPane,
    SingleAnalysisPane,
    _make_analysis_pane,
    _make_single_analysis_pane,
)


@pytest.mark.parametrize("side", ["left", "right"])
def test_analysis_pane_is_typed_and_fully_populated(side):
    pane = _make_analysis_pane(side)
    assert isinstance(pane, AnalysisPane)
    # Every declared field is set — a dataclass makes a forgotten one a
    # TypeError at construction, which the namespace never could.
    for f in dataclasses.fields(pane):
        assert getattr(pane, f.name) is not None, f.name
    # Every *_fig field really is a figure, and the grid really is a grid.
    for f in dataclasses.fields(pane):
        if f.name.endswith("_fig"):
            assert isinstance(getattr(pane, f.name), go.FigureWidget), f.name
    assert isinstance(pane.retdist_stats_grid, DataGrid)
    assert isinstance(pane.root, W.VBox)
    # The views dict covers the tab's whole option list, so every pick mounts.
    assert set(pane.views) == set(ANALYSIS_OPTIONS)
    assert pane.picker.value in ANALYSIS_OPTIONS


@pytest.mark.parametrize("side", ["left", "right"])
def test_single_analysis_pane_is_typed_and_fully_populated(side):
    pane = _make_single_analysis_pane(side)
    assert isinstance(pane, SingleAnalysisPane)
    for f in dataclasses.fields(pane):
        assert getattr(pane, f.name) is not None, f.name
        if f.name.endswith("_fig"):
            assert isinstance(getattr(pane, f.name), go.FigureWidget), f.name
    assert isinstance(pane.retdist_stats_grid, DataGrid)
    assert isinstance(pane.root, W.VBox)
    assert set(pane.views) == set(SINGLE_ANALYSIS_OPTIONS)
    assert pane.picker.value in SINGLE_ANALYSIS_OPTIONS


def test_panes_do_not_share_figures():
    # Each pane owns its own figures so the two can render the same analysis
    # side-by-side; sharing one would make the second pick overwrite the first.
    left = _make_analysis_pane("left")
    right = _make_analysis_pane("right")
    assert left.line_fig is not right.line_fig
    assert left.heat_fig is not right.heat_fig
    assert left.fresh is not right.fresh


def test_fresh_starts_empty_and_is_per_pane():
    # `fresh` is a default_factory set, not a shared class attribute — the
    # classic dataclass mutable-default trap, and the builder mutates it.
    a = _make_analysis_pane("left")
    b = _make_analysis_pane("left")
    assert a.fresh == set()
    a.fresh.add("Cumulative Performance")
    assert b.fresh == set()
