"""`strategy_metrics` and the two HTML blocks it feeds (#366).

The Single Strategy tab's numbers used to be two `ipydatagrid` canvases — a
`PerfGrid` and the calendar's grid — whose dark theme has to be re-asserted on
every write (#223), for tables that never sort, scroll sideways or take a
click. These pin the frame behind the styled HTML that replaced them, and the
two rendering decisions that are easy to get wrong: what an unserved window
shows, and what since-inception is measured over.
"""

from __future__ import annotations

import re

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


# --- the return-distribution stats table (#386) --------------------------------


def _ret_stats() -> tuple[pd.DataFrame, pd.DataFrame]:
    stats = pd.DataFrame(
        {
            "Mean": [0.0004, -0.0002],
            "Std": [0.0107, 0.0081],
            "Skew": [-0.35, 0.12],
            "Kurtosis": [4.10, 3.02],
            "Min": [-0.0455, -0.0310],
            "Max": [0.0512, 0.0288],
        },
        index=["AAA Index", "SPTR Index"],
    )
    meta = pd.DataFrame(
        {
            "ticker": ["AAA Index", "SPTR Index"],
            "name": ["Alpha Strategy", "S&P 500 Total Return"],
        }
    )
    return stats, meta


def test_the_return_stats_table_is_tickers_down_statistics_across():
    """The transpose of `.bbg-metrics`: here the row is the series, because a
    basket can hold five of them where the metrics table has one strategy."""
    from src.layout.html import _render_return_stats

    stats, meta = _ret_stats()
    out = _render_return_stats(stats, meta)
    assert "bbg-retstats" in out
    # One body row per ticker, short-form as the chart's legend writes them.
    assert out.count("<tr><th>") == 2
    assert "<th>AAA</th>" in out and "<th>SPTR</th>" in out
    # Every statistic is a column, under the heading it declares — which is
    # not always its column name: Mean reads in basis points (#388).
    for heading in ("Mean (bp)", "Std", "Min", "Max", "Skew", "Kurtosis"):
        assert f"<th>{heading}</th>" in out


def test_the_return_stats_table_reads_the_same_units_and_two_decimals():
    """`_metric_cell`'s rule, reused rather than re-implemented — so the
    percent/ratio split and the dash and the negative colour are one
    implementation across every HTML stats table."""
    from src.layout.html import _render_return_stats

    stats, meta = _ret_stats()
    out = _render_return_stats(stats, meta)
    assert "1.07%" in out, "Std reads as a percentage"
    assert "4.10" in out, "Kurtosis reads as a plain ratio"
    # Red for negative, and no green — the metrics table's rule.
    assert "bbg-metrics-neg" in out
    assert "bbg-metrics-pos" not in out


def test_the_return_stats_table_escapes_a_name_and_carries_no_hex():
    from src.layout.html import _render_return_stats

    stats, meta = _ret_stats()
    out = _render_return_stats(stats, meta)
    assert "S&amp;P 500 Total Return" in out
    assert "S&P 500" not in out, "an unescaped ampersand would break the markup"
    assert not re.search(r"#[0-9a-fA-F]{3,8}", out), "colours come from the stylesheet"


def test_the_return_stats_table_is_empty_for_an_empty_frame():
    from src.layout.html import _render_return_stats

    assert _render_return_stats(pd.DataFrame(), pd.DataFrame()) == ""


def test_a_missing_stat_column_is_simply_absent():
    """A frame without Skew renders without a Skew column rather than a row of
    dashes under a heading nothing filled."""
    from src.layout.html import _render_return_stats

    stats, meta = _ret_stats()
    out = _render_return_stats(stats.drop(columns=["Skew"]), meta)
    assert "<th>Skew</th>" not in out
    assert "<th>Kurtosis</th>" in out


def test_a_ticker_the_catalog_does_not_name_still_renders():
    """A benchmark is not in the catalog, so its name lookup misses — the row
    is drawn with an empty name rather than the literal `nan`."""
    from src.layout.html import _render_return_stats

    stats, meta = _ret_stats()
    out = _render_return_stats(stats, meta[meta["ticker"] == "AAA Index"])
    assert "<th>SPTR</th>" in out
    assert "nan" not in out.lower()


def test_the_mean_reads_in_basis_points_so_two_decimals_still_resolve_it():
    """#388. A **daily** mean sits three orders below the other percentages in
    this table. At two decimals of a percentage it rendered one significant
    figure, and two strategies whose means differ by a fifth printed the same
    number — `0.0577` and `0.0588` were both `0.06%`.

    Basis points keep v0.9.32's two-decimal rule and move the decimal instead,
    which is why this is not an exception to that rule.
    """
    from src.layout.html import _render_return_stats

    stats = pd.DataFrame(
        {"Mean": [0.0005774, 0.0005876], "Std": [0.0154, 0.0135]},
        index=["AAA Index", "BBB Index"],
    )
    meta = pd.DataFrame({"ticker": stats.index, "name": ["A", "B"]})
    out = _render_return_stats(stats, meta)

    assert "<th>Mean (bp)</th>" in out, "the heading carries the unit"
    assert "5.77" in out and "5.88" in out, "the two means are distinguishable"
    assert "0.06%" not in out
    # Its neighbour is untouched: only Mean changes unit.
    assert "1.54%" in out


def test_a_negative_mean_in_basis_points_is_still_red():
    """The negative rule is `_metric_cell`'s and applies whatever the unit."""
    from src.layout.html import _render_return_stats

    stats = pd.DataFrame({"Mean": [-0.0002]}, index=["AAA Index"])
    out = _render_return_stats(
        stats, pd.DataFrame({"ticker": ["AAA Index"], "name": ["A"]})
    )
    assert "bbg-metrics-neg" in out
    assert "-2.00" in out


def test_the_metrics_table_is_untouched_by_the_basis_point_unit():
    """`_metric_cell` is shared, so a new unit must not reach the table that
    does not declare it — every `STRATEGY_METRICS` row is percent or ratio."""
    from src.stats import STRATEGY_METRICS

    assert {unit for _name, unit in STRATEGY_METRICS} == {"percent", "ratio"}
