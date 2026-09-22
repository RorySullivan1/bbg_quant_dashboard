"""One strategy's metrics, over every window at once (#366).

The Single Strategy tab used to show these through two `ipydatagrid`
canvases — a `PerfGrid` of Return / Vol / Sharpe / Max DD over three windows,
and the monthly calendar's summary columns repeating Return and Vol per kind —
whose dark theme has to be re-asserted on every write (#223), for what is a
dozen static numbers. `strategy_metrics` is the frame behind the styled HTML
block that replaced them.

**Its own module rather than a function in `performance.py` or `risk.py`.**
`risk.py` imports `performance.py`, so a table drawing on both cannot live in
either without inverting that; and the table is neither — it is the *view* a
tab needs, assembled from metrics both modules define. A reader looking for
"the strategy's metrics table" finds a module named for it.

Pure compute over the already-fetched cache — no BQL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import stat_windows
from ._common import _has_enough_history, _slice_last_years, daily_returns, max_drawdown
from .performance import ann_return, ann_volatility
from .risk import ann_beta, benchmark_returns, calmar_ratio, sortino_ratio

#: The label for the full-history column. Short because it is a column header
#: beside `6M` / `1Y` / `3Y`; the table's own heading spells it out.
SINCE_INCEPTION: str = "SI"

#: Each metric, and whether it reads as a percentage or as a plain ratio —
#: which is the *only* thing that differs in how they are rendered, since
#: v0.9.32 put every number in a table at two decimals.
#:
#: **Not the grid's `_PERCENT_SUFFIXES`.** That tuple decides by *column-name
#: suffix*, because a catalog column is named `"1Y Return"` and the renderer
#: has nothing else to go on. Here the metric is the row, so it is named
#: directly; reaching into the grid's tuple would couple this table to a
#: naming scheme it does not use. What the two share is the rule, not the
#: mechanism: two decimals, and the unit decided in one place per table.
STRATEGY_METRICS: tuple[tuple[str, str], ...] = (
    ("Return", "percent"),
    ("Vol", "percent"),
    ("Sharpe", "ratio"),
    ("Sortino", "ratio"),
    ("Calmar", "ratio"),
    ("Max DD", "percent"),
    ("Beta", "ratio"),
    ("Correlation", "ratio"),
)

#: The two that need a benchmark. Without one they are NaN — a dash in the
#: rendered table — rather than silently measured against the strategy itself.
BENCHMARK_METRICS: frozenset[str] = frozenset({"Beta", "Correlation"})

_METRIC_NAMES: tuple[str, ...] = tuple(name for name, _ in STRATEGY_METRICS)


def metric_unit(metric: str) -> str:
    """``"percent"`` or ``"ratio"`` for one metric name."""
    return dict(STRATEGY_METRICS)[metric]


def _window_metrics(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    years: float,
    bench_returns: pd.Series | None,
) -> dict[str, float]:
    """Every metric for a one-column `prices` frame over the trailing window.

    The window functions all slice by trailing date, so the whole column is
    one call each; Correlation is the only one without an existing helper,
    because nothing else needed a single pair's ρ over a window.
    """
    values = {
        "Return": ann_return(prices, years),
        "Vol": ann_volatility(returns, years),
        "Calmar": calmar_ratio(prices, years),
        "Sortino": sortino_ratio(returns, prices, years),
        "Max DD": max_drawdown(prices, years),
    }
    out = {name: float(series.iloc[0]) for name, series in values.items()}
    vol = out["Vol"]
    out["Sharpe"] = out["Return"] / vol if vol else np.nan
    out["Beta"] = np.nan
    out["Correlation"] = np.nan
    if bench_returns is not None and not bench_returns.empty:
        out["Beta"] = float(ann_beta(returns, bench_returns, years).iloc[0])
        window = _slice_last_years(returns, years)
        leg = bench_returns.reindex(window.index)
        out["Correlation"] = float(window.iloc[:, 0].corr(leg))
    return out


def _valid_span(series: pd.Series) -> pd.Series:
    """`series` between its own first and last non-NaN dates.

    Since-inception has to be measured over the *strategy's* history, not the
    frame's: handed a frame that starts before the index launched,
    `ann_return` would divide the strategy's total return by the frame's span
    and understate the CAGR. `since_inception_perf` solves this by taking the
    per-column valid bounds; one strategy can simply be sliced.
    """
    valid = series.dropna()
    if valid.empty:
        return valid
    return series.loc[valid.index.min() : valid.index.max()]


def strategy_metrics(
    prices: pd.DataFrame,
    ticker: str,
    *,
    benchmark: pd.Series | None = None,
) -> pd.DataFrame:
    """One strategy's metrics: rows `STRATEGY_METRICS`, columns the windows.

    Columns are every window `stat_windows()` offers plus `SINCE_INCEPTION`.
    A window the strategy has not lived through is **all-NaN**, the same rule
    `perf_table` applies through `_has_enough_history` — a partially-served
    window would report a 3Y number measured over eighteen months.

    `benchmark` is a **price** series; it is converted through
    `benchmark_returns` so Beta covaries against returns, which is the
    v0.9.30 fix. Without one, Beta and Correlation are NaN.

    An empty frame or an absent ticker gives the empty table with its rows and
    columns, so a caller renders a grid of dashes rather than branching.
    """
    labels = [label for label, _ in stat_windows()]
    columns = [*labels, SINCE_INCEPTION]
    empty = pd.DataFrame(np.nan, index=list(_METRIC_NAMES), columns=columns)
    if prices.empty or ticker not in prices.columns:
        return empty

    one = prices[[ticker]]
    returns = daily_returns(one)
    bench_returns = benchmark_returns(benchmark)

    out = empty.copy()
    for label, years in stat_windows():
        if not bool(_has_enough_history(one, years).iloc[0]):
            continue
        for name, value in _window_metrics(one, returns, years, bench_returns).items():
            out.loc[name, label] = value

    span = _valid_span(prices[ticker])
    if not span.empty:
        # A window long enough to cover the whole valid span, so the same
        # trailing-window helpers measure it end to end. One strategy, so the
        # per-column bounds `since_inception_perf` needs are just a slice.
        si_prices = span.to_frame()
        si_years = max(
            (span.index.max() - span.index.min()).days / 365.25, 1.0 / 365.25
        )
        si = _window_metrics(
            si_prices, daily_returns(si_prices), si_years, bench_returns
        )
        for name, value in si.items():
            out.loc[name, SINCE_INCEPTION] = value
    return out


#: How many buckets the benchmark's returns are cut into. Ten, so each is a
#: readable slice of the sample and the tails are single columns rather than
#: something a reader has to average in their head.
DECILE_COUNT: int = 10


def decile_profile(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    mask: pd.Series | None = None,
    buckets: int = DECILE_COUNT,
) -> pd.DataFrame:
    """Mean return per benchmark-return decile: rows deciles, columns the two.

    Convexity, read left to right — how the strategy does in the benchmark's
    worst tenth of periods through to its best. Columns are ``strategy`` and
    ``benchmark``; the index is ``1``…``buckets``, worst first.

    **The benchmark decides the buckets**; the strategy is only measured
    inside them. Cutting on the strategy's own returns would sort the answer
    into the question and draw a monotone staircase for any series at all.

    ``mask`` restricts the periods cut, which is how the regime conditioning
    reaches this (#369): every bucket is a subset of the window, so the
    columns are recomputed over the bucket's periods only rather than
    re-sliced from a full-sample cut.

    `qcut` with ``duplicates="drop"`` rather than a fixed grid: a sample whose
    returns repeat — a short window, a stale series — has fewer distinct
    quantile edges than buckets, and a fixed grid would raise on it. Fewer
    columns is the honest answer there.

    An empty frame with the columns when the two series share fewer than
    ``buckets`` aligned periods, so a caller clears rather than drawing a
    staircase out of six points.
    """
    columns = ["strategy", "benchmark"]
    if strategy is None or benchmark is None:
        return pd.DataFrame(columns=columns)
    pair = pd.DataFrame({"strategy": strategy, "benchmark": benchmark}).dropna()
    if mask is not None and not mask.empty:
        pair = pair.loc[mask.reindex(pair.index, fill_value=False)]
    if len(pair) < buckets:
        return pd.DataFrame(columns=columns)
    try:
        cut = pd.qcut(pair["benchmark"], buckets, labels=False, duplicates="drop")
    except ValueError:  # every value identical — no quantile edges at all
        return pd.DataFrame(columns=columns)
    grouped = pair.groupby(cut, observed=True).mean()
    # 1-based, because "the 1st decile" is how a reader says it and a 0 column
    # on an axis of ten reads as a count rather than a rank.
    grouped.index = pd.Index(range(1, len(grouped) + 1), name="decile")
    return grouped[columns]
