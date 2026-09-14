"""The typed analysis panes (#216), now holding `Chart` objects (#223).

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
from src.layout.charts import Chart
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
    # Every chart field is a `Chart` owning a real figure (#223) — the pairing
    # of figure to updater is the object's, not the caller's.
    for f in dataclasses.fields(pane):
        value = getattr(pane, f.name)
        if isinstance(value, Chart):
            assert isinstance(value.fig, go.FigureWidget), f.name
    assert isinstance(pane.retdist.stats_grid, DataGrid)
    assert isinstance(pane.root, W.VBox)
    # The views dict covers the tab's whole option list, so every pick mounts.
    assert set(pane.views) == set(ANALYSIS_OPTIONS)
    assert pane.picker.value in ANALYSIS_OPTIONS


@pytest.mark.parametrize("side", ["left", "right"])
def test_single_analysis_pane_is_typed_and_fully_populated(side):
    pane = _make_single_analysis_pane(side)
    assert isinstance(pane, SingleAnalysisPane)
    for f in dataclasses.fields(pane):
        value = getattr(pane, f.name)
        assert value is not None, f.name
        if isinstance(value, Chart):
            assert isinstance(value.fig, go.FigureWidget), f.name
    assert isinstance(pane.retdist.stats_grid, DataGrid)
    assert isinstance(pane.root, W.VBox)
    assert set(pane.views) == set(SINGLE_ANALYSIS_OPTIONS)
    assert pane.picker.value in SINGLE_ANALYSIS_OPTIONS


def test_panes_do_not_share_charts():
    # Each pane owns its own charts (and so its own figures) so the two can
    # render the same analysis side-by-side; sharing one would make the second
    # pick overwrite the first.
    left = _make_analysis_pane("left")
    right = _make_analysis_pane("right")
    assert left.line is not right.line
    assert left.line.fig is not right.line.fig
    assert left.heat is not right.heat
    assert left.heat.fig is not right.heat.fig
    assert left.fresh is not right.fresh


def test_rolling_charts_carry_their_own_title_prefix():
    # #223: the prefix used to be passed to the factory *and* again to every
    # update, with nothing checking they matched. It is the chart's now.
    pane = _make_analysis_pane("left")
    assert pane.rcorr.title_prefix == "Rolling Correlation"
    assert pane.rbeta.title_prefix == "Rolling Beta"
    assert "Rolling Correlation" in pane.rcorr.fig.layout.title.text
    assert "Rolling Beta" in pane.rbeta.fig.layout.title.text


def test_fresh_starts_empty_and_is_per_pane():
    # `fresh` is a default_factory set, not a shared class attribute — the
    # classic dataclass mutable-default trap, and the builder mutates it.
    a = _make_analysis_pane("left")
    b = _make_analysis_pane("left")
    assert a.fresh == set()
    a.fresh.add("Cumulative Performance")
    assert b.fresh == set()
