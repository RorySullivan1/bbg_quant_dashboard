"""The cumulative chart's zoom readout (#380).

Zooming used to be cosmetic: the line rescaled and nothing else on the tab
knew the reader had narrowed to a period. What is pinned here is the span
arithmetic (`stats.span_metrics`), the rule that drops the annualized metrics
under a year, the rendered panel, and the round trip from a range change on
the figure to the text drawn inside it.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest
from src.layout.charts import LineChart
from src.layout.html import _render_span_readout
from src.stats import ANNUALIZED_METRICS, CUMULATIVE_RETURN, span_metrics


@pytest.fixture
def prices() -> pd.DataFrame:
    """Five years of two series, one steadier than the other."""
    index = pd.bdate_range("2019-01-01", "2024-01-01")
    rng = np.random.default_rng(380)
    return pd.DataFrame(
        {
            "AAA Index": 100 * np.cumprod(1 + rng.normal(0.0004, 0.010, len(index))),
            "SPTR Index": 100 * np.cumprod(1 + rng.normal(0.0003, 0.008, len(index))),
        },
        index=index,
    )


# --- the span arithmetic ------------------------------------------------------


def test_a_span_of_a_year_or_more_reports_every_metric(prices):
    out = span_metrics(
        prices,
        "AAA Index",
        pd.Timestamp("2020-01-01"),
        pd.Timestamp("2023-01-01"),
        benchmark=prices["SPTR Index"],
    )
    assert out.attrs["annualized"] is True
    assert set(out.index) >= ANNUALIZED_METRICS
    assert "Return" in out.index and CUMULATIVE_RETURN not in out.index
    assert not out["value"].isna().any()


def test_under_a_year_the_annualized_metrics_are_dropped_not_scaled(prices):
    """The rule the issue asked for: no annualizing a four-month sample.

    They **leave the frame** rather than rendering as a dash, because a dash
    reads as "could not be measured" where the truth is that the figure does
    not mean anything over this span.
    """
    out = span_metrics(
        prices,
        "AAA Index",
        pd.Timestamp("2022-01-01"),
        pd.Timestamp("2022-05-01"),
        benchmark=prices["SPTR Index"],
    )
    assert out.attrs["annualized"] is False
    assert not (ANNUALIZED_METRICS & set(out.index)), "no annualized metric survives"
    # Max DD, Beta and Correlation do not annualize, so they stay.
    assert {"Max DD", "Beta", "Correlation"} <= set(out.index)


def test_under_a_year_return_becomes_cumulative(prices):
    lo, hi = pd.Timestamp("2022-01-01"), pd.Timestamp("2022-05-01")
    out = span_metrics(prices, "AAA Index", lo, hi)
    assert "Return" not in out.index
    assert CUMULATIVE_RETURN in out.index

    series = prices.loc[lo:hi, "AAA Index"].dropna()
    expected = series.iloc[-1] / series.iloc[0] - 1.0
    assert out.loc[CUMULATIVE_RETURN, "value"] == pytest.approx(expected)


def test_the_span_is_clamped_to_the_strategys_own_history(prices):
    """A zoom can run past either end of the data. Measuring across the empty
    part would divide a real return by a span including dates the index did
    not exist for — `_valid_span`'s argument, one level up."""
    out = span_metrics(
        prices,
        "AAA Index",
        pd.Timestamp("2000-01-01"),
        pd.Timestamp("2040-01-01"),
    )
    assert out.attrs["start"] == prices.index.min()
    assert out.attrs["end"] == prices.index.max()


def test_an_empty_or_degenerate_span_is_empty_not_an_exception(prices):
    assert span_metrics(prices, "ZZZ Index", prices.index[0], prices.index[-1]).empty
    assert span_metrics(
        pd.DataFrame(), "AAA Index", prices.index[0], prices.index[-1]
    ).empty
    # hi before lo, and a single day: both are spans nothing can be measured over.
    assert span_metrics(prices, "AAA Index", prices.index[-1], prices.index[0]).empty
    assert span_metrics(prices, "AAA Index", prices.index[5], prices.index[5]).empty


def test_without_a_benchmark_beta_and_correlation_are_nan(prices):
    out = span_metrics(
        prices, "AAA Index", pd.Timestamp("2020-01-01"), pd.Timestamp("2023-01-01")
    )
    assert out.loc["Beta", "value"] != out.loc["Beta", "value"]  # NaN
    assert out.loc["Correlation", "value"] != out.loc["Correlation", "value"]


# --- the rendered panel -------------------------------------------------------


def test_the_readout_names_the_span_and_the_basis(prices):
    out = span_metrics(
        prices, "AAA Index", pd.Timestamp("2022-01-01"), pd.Timestamp("2022-05-01")
    )
    text = _render_span_readout(out)
    # The dates the frame actually measured, not the ones asked for: the span
    # is clamped to the data, and a literal here would pin the test to the
    # fixture's calendar rather than to the rule.
    assert f"{out.attrs['start']:%Y-%m-%d}" in text
    assert f"{out.attrs['end']:%Y-%m-%d}" in text
    assert f"{out.attrs['days']}d" in text
    # Says which regime it is in, so a missing Sharpe reads as a decision.
    assert "cumulative" in text
    assert "Sharpe" not in text


def test_the_readout_carries_no_hex_of_its_own_beyond_the_tokens(prices):
    """The panel is drawn as annotation text, so it cannot use the stylesheet
    — but the colours it does inline must be the tokens, not new literals."""
    from src.style import Color

    out = span_metrics(
        prices, "AAA Index", pd.Timestamp("2020-01-01"), pd.Timestamp("2023-01-01")
    )
    text = _render_span_readout(out, benchmark="SPTR Index")
    for found in set(re.findall(r"#[0-9a-fA-F]{3,8}", text)):
        assert found in {
            Color.RED_600.value,
            Color.TEXT_MUTED.value,
        }, found


def test_the_readout_is_empty_for_an_empty_frame():
    assert _render_span_readout(pd.DataFrame({"value": []})) == ""


def test_the_readout_reads_the_same_two_decimals_as_the_table(prices):
    out = span_metrics(
        prices, "AAA Index", pd.Timestamp("2020-01-01"), pd.Timestamp("2023-01-01")
    )
    text = _render_span_readout(out)
    # A percent row and a ratio row, both at two decimals.
    assert re.search(r"\d+\.\d{2}%", text), text
    assert re.search(r"\d+\.\d{2}(?!%|\d)", text), text


# --- the round trip -----------------------------------------------------------


def test_the_chart_pre_allocates_its_readout_and_hides_it_when_empty():
    chart = LineChart()
    assert len(chart.fig.layout.annotations) == 1
    assert chart.fig.layout.annotations[0].visible is False

    chart.set_readout("a<br>b")
    assert chart.fig.layout.annotations[0].visible is True
    chart.set_readout("")
    assert chart.fig.layout.annotations[0].visible is False


def test_a_range_change_reaches_the_callback_and_a_reset_reports_none():
    chart = LineChart()
    seen: list[tuple] = []
    chart.on_range(lambda lo, hi: seen.append((lo, hi)))

    chart.fig.layout.xaxis.range = ["2020-01-01", "2021-01-01"]
    assert seen[-1] == ("2020-01-01", "2021-01-01")

    chart.fig.layout.xaxis.range = None
    assert seen[-1] == (None, None), "a reset reports no range, not a stale one"


# --- the panel wires the two together ------------------------------------------


def test_the_panel_fills_the_readout_on_render_and_follows_a_zoom():
    """The whole point of #380: the zoom *means* something. A fresh render
    shows the window; a zoom narrows the readout to the period on screen; a
    reset puts the window back. It is never blank while a line is drawn."""
    from src.layout.app import DashboardApp

    app = DashboardApp(verbose=False)
    line = app.single_strategy.line
    annotation = line.fig.layout.annotations[0]

    assert annotation.visible is True, "a drawn line always carries a readout"
    whole = annotation.text
    assert "annualized" in whole

    line.fig.layout.xaxis.range = ["2024-01-01", "2024-06-01"]
    zoomed = annotation.text
    assert zoomed != whole
    assert "2024-01" in zoomed
    assert "cumulative" in zoomed, "under a year"
    assert "Sharpe" not in zoomed

    line.fig.layout.xaxis.range = None
    assert annotation.text == whole, "a reset restores the window"
    assert annotation.visible is True


def test_a_zoom_never_fetches(monkeypatch):
    """No BQL from a control — the readout re-slices the same cached frame
    `render` sliced."""
    from src.layout import app as app_mod
    from src.layout.app import DashboardApp

    app = DashboardApp(verbose=False)

    def no_fetch(*a, **kw):  # pragma: no cover - the assert is that it is unused
        raise AssertionError("a zoom must not issue BQL")

    monkeypatch.setattr(app_mod, "fetch_prices", no_fetch)
    line = app.single_strategy.line
    for lo, hi in (
        ("2023-01-01", "2023-03-01"),
        ("2020-01-01", "2024-01-01"),
        (None, None),
    ):
        line.fig.layout.xaxis.range = None if lo is None else [lo, hi]


def test_the_readout_clears_when_there_is_no_pick():
    """No line, no panel — rather than a stale one describing the last pick."""
    from types import SimpleNamespace

    import pandas as pd
    from src.layout.single_strategy import SingleStrategyPanel
    from tests.test_single_strategy import _meta

    panel = SingleStrategyPanel(_meta(), None)
    panel.state = SimpleNamespace(universe_prices=pd.DataFrame())
    panel.render_readout()
    assert panel.line.fig.layout.annotations[0].visible is False


def test_the_readout_uses_only_entities_plotly_can_render(prices):
    """#386. Plotly's bundled parser knows exactly four named entities —
    `&amp;`, `&lt;`, `&gt;` and `&nbsp;`. Anything else is printed as typed,
    which is how a separator written `&middot;` reached the screen as the
    literal text `&middot;`."""
    out = span_metrics(
        prices, "AAA Index", pd.Timestamp("2020-01-01"), pd.Timestamp("2023-01-01")
    )
    for text in (
        _render_span_readout(out, benchmark="SPTR Index"),
        _render_span_readout(
            span_metrics(
                prices,
                "AAA Index",
                pd.Timestamp("2022-01-01"),
                pd.Timestamp("2022-05-01"),
            )
        ),
    ):
        named = set(re.findall(r"&([a-zA-Z][a-zA-Z0-9]*);", text))
        assert named <= {"amp", "lt", "gt", "nbsp"}, named
        # The separator is the character itself, not an entity for it.
        assert "·" in text
