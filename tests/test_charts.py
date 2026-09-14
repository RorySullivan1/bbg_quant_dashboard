"""The `Chart` objects (#223).

Every chart used to be two functions in two files — a `_*_chart()` factory in
`panes.py` and a `_update_*(fig, …)` here — paired only by the field a pane
happened to hold them in. Nothing stopped `_update_heatmap` being handed the
drawdown figure, and nothing exercised a chart that no pane mounted.

These tests cover the whole class list mechanically, so a new `Chart` is
exercised the moment it exists rather than when someone remembers to add a case.
"""

from __future__ import annotations

import inspect

import pandas as pd
import plotly.graph_objects as go
import pytest
from src.layout import charts as ch

#: How to construct each concrete chart, and the empty input its `update` takes.
#: `None` args are the "no data" shape for that chart, which is what a cleared
#: selection hands it.
EMPTY_UPDATE: dict[str, tuple[dict, tuple]] = {
    "LineChart": ({}, (pd.DataFrame(),)),
    "OutperformanceChart": ({}, (pd.DataFrame(),)),
    "CorrHeatmap": ({}, (pd.DataFrame(),)),
    "SharpeZChart": ({}, (pd.DataFrame(),)),
    "ScatterChart": ({}, (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())),
    "DrawdownChart": ({}, (pd.DataFrame(),)),
    "RollingRefChart": (
        {"title_prefix": "Rolling Correlation", "y_label": "Correlation", "ref_y": 0.0},
        (pd.DataFrame(),),
    ),
    "ReturnDistChart": ({}, (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())),
    "WeeklyScatterChart": ({}, (None, None)),
    "FactorCorrChart": ({}, (None, None, None)),
    "FactorScoringChart": ({}, (None,)),
    "PerfRankingChart": ({}, (None,)),
    "PcaChart": ({}, ()),
    "DefensiveChart": ({}, ()),
}

#: Keyword arguments `update` needs on top of the positional empties.
EMPTY_KWARGS: dict[str, dict] = {
    "OutperformanceChart": {"benchmark_label": ""},
    "RollingRefChart": {"benchmark_label": ""},
}


def _concrete() -> dict[str, type]:
    """Every instantiable `Chart` subclass in the module."""
    return {
        name: obj
        for name, obj in vars(ch).items()
        if inspect.isclass(obj)
        and issubclass(obj, ch.Chart)
        and obj not in (ch.Chart, ch._StubChart)
    }


def _make(name: str) -> ch.Chart:
    kwargs, _ = EMPTY_UPDATE[name]
    return _concrete()[name](**kwargs)


def test_every_chart_class_is_covered():
    """A new `Chart` subclass must arrive with a case in `EMPTY_UPDATE`.

    Without this the table silently stops covering the module, which is the
    failure the old free-function layout had by default.
    """
    assert set(_concrete()) == set(EMPTY_UPDATE)


@pytest.mark.parametrize("name", sorted(EMPTY_UPDATE))
def test_chart_constructs_with_a_figure(name):
    chart = _make(name)
    assert isinstance(chart.fig, go.FigureWidget)


@pytest.mark.parametrize("name", sorted(EMPTY_UPDATE))
def test_chart_updates_with_empty_input(name):
    # Empty input is the live path on startup and whenever a selection clears,
    # so "does not raise" here is a real guarantee, not a smoke test.
    chart = _make(name)
    args = EMPTY_UPDATE[name][1]
    chart.update(*args, **EMPTY_KWARGS.get(name, {}))


@pytest.mark.parametrize("name", sorted(EMPTY_UPDATE))
def test_chart_clears(name):
    chart = _make(name)
    chart.clear()


@pytest.mark.parametrize("name", sorted(EMPTY_UPDATE))
def test_chart_clear_is_idempotent(name):
    # A pane clears every chart on each recompute with no valid selection, so
    # clear runs back-to-back in practice.
    chart = _make(name)
    chart.clear()
    chart.clear()


def test_two_charts_of_a_kind_own_separate_figures():
    # The two analysis panes each build their own; a shared figure would make
    # one pane's render overwrite the other's.
    for name in EMPTY_UPDATE:
        a, b = _make(name), _make(name)
        assert a.fig is not b.fig, name


def test_rolling_ref_chart_titles_itself_from_its_prefix():
    # The prefix used to be passed to the factory *and* to every update, with
    # nothing checking the two agreed — a rolling-beta figure could be titled
    # "Rolling Correlation". It is one value on the object now.
    beta = ch.RollingRefChart(title_prefix="Rolling Beta", y_label="Beta", ref_y=1.0)
    assert "Rolling Beta" in beta.fig.layout.title.text
    beta.update(pd.DataFrame(), benchmark_label="SPTR Index")
    assert beta.fig.layout.title.text.startswith("Rolling Beta vs SPTR Index")


def test_stub_charts_draw_a_placeholder():
    for cls in (ch.PcaChart, ch.DefensiveChart):
        chart = cls()
        chart.update()
        assert len(chart.fig.data) == 0
        assert len(chart.fig.layout.annotations) == 1
        assert chart.PLACEHOLDER in chart.fig.layout.annotations[0].text


def test_return_dist_chart_owns_its_stats_grid():
    # The grid is part of the chart, so an update that blanks the figure blanks
    # the grid too — they cannot drift apart.
    chart = ch.ReturnDistChart()
    chart.clear()
    assert chart.stats_grid.data.empty
