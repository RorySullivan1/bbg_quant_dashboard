"""The per-ticker quant metrics, computed once and read by both tabs (#345).

Sortino · Calmar · Beta · Treynor · Jensen α · VaR · RSI were nine `≥ / ≤`
threshold rows on the Multi-Strategy tab, typed against a table the user never
saw. Epic #341 makes them **columns** of the basket table, filtered by the
comparison row the catalog already carries (#297) — the same operator, on a
number that is on screen.

The memo moved here out of `QuantFilter` so the two consumers cannot disagree.
Single Strategy still filters by threshold and the basket table renders the
values; both now ask this object, so *the number the user sees is the number
the threshold compares*. It is keyed on `(years, benchmark)` and on the
**identity** of the price frame, which is what a Refresh invalidates — a new
fetch rebinds `arp_universe_prices`, so the old entries can never be served
against new prices. The frame is held by reference rather than by `id()`:
CPython reuses addresses, so an `id()` compared against a frame nobody holds
any more can match a *different* frame allocated at the same address, and the
memo would answer for the wrong prices. One extra reference is the cost.
"""

from __future__ import annotations

import pandas as pd

from ..stats import (
    ann_beta,
    daily_returns,
    jensen_alpha,
    quant_metrics_table,
    treynor_ratio,
)

#: The metrics the basket table carries, in column order. Deliberately the old
#: threshold set **minus Z**: a cross-sectional z-score is a ranking, and the
#: Platform tab's ranking column is where a ranking belongs (#341 dec. 9).
QUANT_METRICS: tuple[str, ...] = (
    "Sortino",
    "Calmar",
    "Beta",
    "Treynor",
    "Jensen",
    "VaR",
    "RSI",
)

#: The three that need a benchmark. One dropdown feeds all of them here, where
#: `QuantFilter` gave each its own — three benchmarks in one table is a
#: comparison nobody asked for, and the bar has room for one control.
BENCHMARK_METRICS: tuple[str, ...] = ("Beta", "Treynor", "Jensen")


def quant_column_name(window_label: str, metric: str) -> str:
    """`"1Y Sortino"` — the same shape the performance columns use.

    Named this way on purpose: `_window_of`, `_is_stat_col`, `_filter_kinds`
    and the numeric renderer all key off the `"<window> <stat>"` prefix, so
    these columns are hidden by the Window chip, filtered by comparison and
    rendered as numbers **with no new branches anywhere** (#341 dec. 9).
    """
    return f"{window_label} {metric}"


class QuantColumns:
    """The metric table, memoised per `(years, benchmark)` per price frame."""

    def __init__(self) -> None:
        self._memo: dict[tuple, pd.DataFrame] = {}
        #: The price frame the memo was built from, held so `is` can be trusted
        #: (see the module docstring on why `id()` cannot).
        self._source: pd.DataFrame | None = None

    def table(
        self,
        prices: pd.DataFrame,
        *,
        years: float,
        benchmark: pd.Series | None,
        benchmark_name: str | None,
        returns: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Every metric for every ticker in `prices`, over `years`.

        `benchmark_name` is part of the key while `benchmark` is the data: two
        different series can be equal, and comparing frames to decide a cache
        hit costs more than recomputing.
        """
        if prices.empty:
            return pd.DataFrame(columns=list(QUANT_METRICS))
        if prices is not self._source:
            self._memo.clear()
            self._source = prices
        key = (round(years, 6), benchmark_name)
        cached = self._memo.get(key)
        if cached is not None:
            return cached

        rets = returns if returns is not None and not returns.empty else None
        if rets is None:
            rets = daily_returns(prices)
        table = quant_metrics_table(prices, None, years, returns=rets)
        table["Beta"] = ann_beta(rets, benchmark, years)
        table["Treynor"] = treynor_ratio(rets, prices, benchmark, years)
        table["Jensen"] = jensen_alpha(rets, prices, benchmark, years)
        self._memo[key] = table
        return table

    def clear(self) -> None:
        """Drop everything, and the frame reference with it."""
        self._memo.clear()
        self._source = None
