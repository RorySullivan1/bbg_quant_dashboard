"""`strategy_metrics` and the two HTML blocks it feeds (#366).

The Single Strategy tab's numbers used to be two `ipydatagrid` canvases — a
`PerfGrid` and the calendar's grid — whose dark theme has to be re-asserted on
every write (#223), for tables that never sort, scroll sideways or take a
click. These pin the frame behind the styled HTML that replaced them, and the
two rendering decisions that are easy to get wrong: what an unserved window
shows, and what since-inception is measured over.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from src.layout.html import (
    FILTERED_OUT_NOTE,
    METRICS_NA,
    _render_calendar,
    _render_strategy_metrics,
)
from src.stats import (
    SINCE_INCEPTION,
    STRATEGY_METRICS,
    calendar_return_table,
    strategy_metrics,
)
from src.style import MISSING_DASH

_METRICS = [name for name, _ in STRATEGY_METRICS]


@pytest.fixture
def prices() -> pd.DataFrame:
    """Twelve years of two synthetic series, so every window is served.

    The strategy is deliberately **correlated** with the benchmark — a real
    beta of roughly 0.6 plus idiosyncratic noise — because two independent
    random walks give a beta indistinguishable from zero, and a beta test
    against zero cannot tell a correct answer from a broken one.
    """
    index = pd.bdate_range("2014-01-01", "2026-09-01")
    rng = np.random.default_rng(7)
    bench = rng.normal(0.0003, 0.011, len(index))
    strat = 0.6 * bench + rng.normal(0.0002, 0.006, len(index))
    return pd.DataFrame(
        {
            "AAA Index": 100 * np.cumprod(1 + strat),
            "SPTR Index": 100 * np.cumprod(1 + bench),
        },
        index=index,
    )


# --- the frame ----------------------------------------------------------------


def test_the_table_carries_every_metric_over_every_window(prices):
    frame = strategy_metrics(prices, "AAA Index", benchmark=prices["SPTR Index"])
    assert list(frame.index) == _METRICS
    assert frame.columns[-1] == SINCE_INCEPTION
    assert frame.notna().all().all()


def test_a_window_the_strategy_has_not_lived_through_is_blank(prices):
    """`perf_table`'s rule: a partially-served window would report a 3Y
    number measured over eighteen months."""
    young = prices.copy()
    young.loc[young.index < "2025-06-01", "AAA Index"] = np.nan
    frame = strategy_metrics(young, "AAA Index", benchmark=young["SPTR Index"])

    assert frame["6M"].notna().all(), "the window it has lived through is served"
    for window in ("3Y", "5Y", "10Y"):
        assert frame[window].isna().all(), f"{window} is not served"


def test_since_inception_is_measured_over_the_strategys_own_history(prices):
    """Not the frame's.

    Handed a frame that starts before the index launched, `ann_return` would
    divide the strategy's total return by the *frame's* span and understate
    the CAGR — which is the bug `since_inception_perf` avoids by taking the
    per-column valid bounds. One strategy can simply be sliced, and this pins
    that it is: padding the frame with earlier all-NaN rows must not move the
    number.
    """
    padded = prices.reindex(
        pd.bdate_range("2010-01-01", prices.index.max()).union(prices.index)
    )
    plain = strategy_metrics(prices, "AAA Index")
    padded_frame = strategy_metrics(padded, "AAA Index")
    assert padded_frame.loc["Return", SINCE_INCEPTION] == pytest.approx(
        plain.loc["Return", SINCE_INCEPTION], rel=1e-9
    )


def test_beta_and_correlation_need_a_benchmark(prices):
    frame = strategy_metrics(prices, "AAA Index")
    assert frame.loc["Beta"].isna().all()
    assert frame.loc["Correlation"].isna().all()
    # And the rest is unaffected — a missing benchmark blanks two rows, not
    # the table.
    assert frame.loc["Sharpe"].notna().any()


def test_beta_is_taken_against_the_benchmarks_returns(prices):
    """v0.9.30's fix, which cost every Beta in the app before it landed.

    `ann_beta` covaries against whatever it is handed, and the caller holds
    *prices*. Handing the levels straight in divides a covariance of returns
    by a variance of index levels, so the beta collapses toward zero.
    """
    from src.stats import ann_beta, benchmark_returns, daily_returns

    frame = strategy_metrics(prices, "AAA Index", benchmark=prices["SPTR Index"])
    returns = daily_returns(prices[["AAA Index"]])
    correct = ann_beta(returns, benchmark_returns(prices["SPTR Index"]), 1.0)
    wrong = ann_beta(returns, prices["SPTR Index"], 1.0)

    assert frame.loc["Beta", "1Y"] == pytest.approx(float(correct.iloc[0]))
    assert frame.loc["Beta", "1Y"] == pytest.approx(0.6, abs=0.15)
    # The levels-in-place beta is not merely different, it is collapsed:
    # orders of magnitude, which is what let the bug run unnoticed until the
    # column reached a screen.
    assert abs(float(wrong.iloc[0])) < abs(frame.loc["Beta", "1Y"]) / 1000


def test_an_absent_ticker_gives_the_empty_table_not_an_exception(prices):
    frame = strategy_metrics(prices, "NOPE Index")
    assert list(frame.index) == _METRICS
    assert frame.isna().all().all()


# --- the rendered block --------------------------------------------------------


def test_every_number_renders_at_two_decimals(prices):
    """v0.9.32's rule, which the itables renderer had been breaking by
    printing four quant metrics at full float precision in an 82px cell."""
    import re

    html = _render_strategy_metrics(
        strategy_metrics(prices, "AAA Index", benchmark=prices["SPTR Index"])
    )
    numbers = re.findall(r">(-?\d+\.\d+)%?<", html)
    assert numbers
    for text in numbers:
        assert len(text.split(".")[1]) == 2, f"{text} is not at two decimals"


def test_an_unserved_window_renders_a_dash(prices):
    young = prices.copy()
    young.loc[young.index < "2025-06-01", "AAA Index"] = np.nan
    html = _render_strategy_metrics(strategy_metrics(young, "AAA Index"))
    assert METRICS_NA in html


def test_the_benchmark_is_named_where_beta_and_correlation_are_read(prices):
    html = _render_strategy_metrics(
        strategy_metrics(prices, "AAA Index", benchmark=prices["SPTR Index"]),
        benchmark="SPTR Index",
    )
    assert "vs SPTR Index" in html


def test_the_rendered_table_carries_no_inline_hex(prices):
    """#363 dec. 12: colours through `Color` / `STYLE_CTX` / `app_css.html`.

    The block's own markup must be class names only — the template supplies
    the type and the stylesheet the fills, so a palette change reaches it
    without editing a renderer.
    """
    import re

    html = _render_strategy_metrics(
        strategy_metrics(prices, "AAA Index", benchmark=prices["SPTR Index"])
    )
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", html)


def test_no_green_on_a_metric_with_no_direction(prices):
    """Red for negative and nothing for positive.

    Half these rows have no direction — a high Vol is not good, a negative
    Beta is not bad — so sentiment colour would claim an axis that does not
    exist. Sign alone is what a terminal says.
    """
    html = _render_strategy_metrics(
        strategy_metrics(prices, "AAA Index", benchmark=prices["SPTR Index"])
    )
    assert "bbg-metrics-neg" in html, "Max DD is negative on any real series"
    assert "bbg-metrics-pos" not in html


# --- the calendar ---------------------------------------------------------------


def test_the_calendar_renders_a_row_per_year_and_shades_its_cells(prices):
    html = _render_calendar(
        calendar_return_table(prices["AAA Index"], kind="absolute"), kind="absolute"
    )
    import re

    years = re.findall(r"<tr><th>(\d{4})</th>", html)
    assert years == sorted(years)
    assert "bbg-heat-" in html, "the heatmap survived the grid (#363 dec. 4)"
    assert "bbg-cal-edge" in html, "the annual summary is set off"


def test_an_empty_month_renders_the_shared_dash(prices):
    """The first year is partial, so January of it has no return."""
    partial = prices["AAA Index"].copy()
    partial.loc[partial.index < "2014-06-01"] = np.nan
    html = _render_calendar(
        calendar_return_table(partial, kind="absolute"), kind="absolute"
    )
    assert f">{MISSING_DASH}<" in html


def test_the_month_cells_format_by_kind(prices):
    """A return kind reads as a percentage, beta and correlation as ratios.

    Ported from `_calendar_renderers`' tests when #366 replaced the grid: the
    rule is the calendar's, not the rendering stack's.
    """
    series = prices["AAA Index"]
    bench = prices["SPTR Index"]
    percent = _render_calendar(
        calendar_return_table(series, kind="absolute"), kind="absolute"
    )
    ratio = _render_calendar(
        calendar_return_table(series, kind="beta", benchmark=bench), kind="beta"
    )
    assert "%<" in percent
    assert "%<" not in ratio.split("<tbody>")[1]


def test_vol_carries_no_heat_ramp(prices):
    """The summary bands' one deliberate exception, kept across the port.

    A red→green ramp on volatility would claim a good/bad axis it does not
    have — the same call the metrics table makes by using no green at all.
    """
    from src.layout.html import _CALENDAR_SUMMARY_BANDS

    assert _CALENDAR_SUMMARY_BANDS["Vol"][0] is None
    for named in ("Return", "Sharpe", "Beta", "Correlation"):
        assert _CALENDAR_SUMMARY_BANDS[named][0] is not None


def test_the_bands_are_the_ones_the_grid_renderers_read():
    """One declaration, two stacks (#366).

    `grids.py` kept these private until the HTML calendar needed them too.
    Two tables disagreeing about where "neutral" ends is exactly the drift a
    single declaration in `style.py` prevents.
    """
    from src.layout import grids
    from src.style import SHARPE_HEAT_BAND, ZSCORE_HEAT_BAND

    assert grids._SHARPE_HEAT_THRESHOLDS is SHARPE_HEAT_BAND
    assert grids._ZSCORE_HEAT_THRESHOLDS is ZSCORE_HEAT_BAND
    assert grids._MISSING_DASH == MISSING_DASH


def test_the_calendar_carries_no_inline_hex(prices):
    import re

    html = _render_calendar(
        calendar_return_table(prices["AAA Index"], kind="absolute"), kind="absolute"
    )
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", html)


def test_an_empty_frame_renders_nothing_rather_than_a_headed_shell(prices):
    assert _render_calendar(pd.DataFrame(), kind="absolute") == ""
    assert _render_strategy_metrics(pd.DataFrame()) == ""


def test_the_filtered_out_note_is_the_cards_and_not_a_literal():
    """Pins that the note has one spelling — the card is the only thing that
    can say a pick is off the table (#363 dec. 2)."""
    assert FILTERED_OUT_NOTE
    assert "filter" in FILTERED_OUT_NOTE.lower()
