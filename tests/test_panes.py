"""The typed analysis panes (#216), now holding `Chart` objects (#223).

`_make_analysis_pane` / `_make_single_analysis_pane` used to return a
`SimpleNamespace`, so a factory that forgot a field produced a pane that only
failed later, inside whichever renderer reached for it. These assert the shape
the renderers depend on.
"""

from __future__ import annotations

import dataclasses

import ipywidgets as W
import pandas as pd
import plotly.graph_objects as go
import pytest
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
    assert isinstance(pane.retdist.stats_w, W.HTML)
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
    assert isinstance(pane.retdist.stats_w, W.HTML)
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


def test_one_rolling_chart_serves_all_four_statistics():
    """#223's fix, in its stronger #368 form.

    The title prefix used to be passed to the factory *and* again to every
    update, with nothing checking they matched — a rolling-beta figure could
    be titled "Rolling Correlation". It became one value on the object, and
    is now derived from the statistic key, so the title, the y-axis and the
    reference line cannot disagree with each other or with the data.
    """
    from src.layout.charts import ROLLING_STATS

    pane = _make_analysis_pane("left")
    assert pane.rolling.stat == "correlation"
    assert "Rolling Correlation" in pane.rolling.fig.layout.title.text
    assert [v for _, v in pane.rolling_chips.options] == [
        key for key, *_ in ROLLING_STATS
    ]

    for key, label, y_label, ref, _needs in ROLLING_STATS:
        pane.rolling.update(pd.DataFrame(), stat=key)
        assert f"Rolling {label}" in pane.rolling.fig.layout.title.text
        assert pane.rolling.fig.layout.yaxis.title.text == y_label
        assert pane.rolling.fig.layout.shapes[0]["y0"] == ref


def test_the_rolling_benchmark_hides_for_the_statistics_that_ignore_one():
    """Sharpe and Calmar do not read a benchmark, so naming one would name a
    series the number does not touch. Hidden, not rebuilt (#331 dec. 3)."""
    pane = _make_analysis_pane("left")
    pane.picker.value = "Rolling"
    pane.rolling_dd.value = "MXWO Index"

    pane.rolling_chips.value = "sharpe"
    assert pane.rolling_dd.layout.display == "none"
    pane.rolling_chips.value = "beta"
    assert pane.rolling_dd.layout.display == ""
    # And the selection survived being hidden.
    assert pane.rolling_dd.value == "MXWO Index"


def test_fresh_starts_empty_and_is_per_pane():
    # `fresh` is a default_factory set, not a shared class attribute — the
    # classic dataclass mutable-default trap, and the builder mutates it.
    a = _make_analysis_pane("left")
    b = _make_analysis_pane("left")
    assert a.fresh == set()
    a.fresh.add("Cumulative Performance")
    assert b.fresh == set()
