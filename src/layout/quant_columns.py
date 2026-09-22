"""The per-ticker quant metrics, computed once and read by both tabs (#345).

Sortino · Calmar · Beta · Treynor · Jensen α · VaR · RSI were nine `≥ / ≤`
threshold rows on the Multi-Strategy tab, typed against a table the user never
saw. Epic #341 makes them **columns** of the basket table, filtered by the
comparison row the catalog already carries (#297) — the same operator, on a
number that is on screen.

The memo moved here out of `QuantFilter` so the two consumers could not
disagree — Single Strategy still filtered by threshold then, and the basket
table rendered the values. #365 retired that panel too, so **both** tabs draw
these as columns now and there is no threshold left to disagree with; what
the one object still buys is a single measurement for two tables, and
`frame` is the per-window block both of them ask for. It is keyed on
`(years, benchmark)` and on the
**identity** of the price frame, which is what a Refresh invalidates — a new
fetch rebinds `arp_universe_prices`, so the old entries can never be served
against new prices. The frame is held by reference rather than by `id()`:
CPython reuses addresses, so an `id()` compared against a frame nobody holds
any more can match a *different* frame allocated at the same address, and the
memo would answer for the wrong prices. One extra reference is the cost.
"""

from __future__ import annotations

import pandas as pd

from ..config import stat_windows
from ..stats import (
    ann_beta,
    benchmark_returns,
    daily_returns,
    jensen_alpha,
    quant_metrics_table,
    treynor_ratio,
)

#: The metrics the selection table carries, in column order.
#:
#: Four, not the old nine. **Z** went first (v0.9.29): a cross-sectional
#: z-score is a ranking, and the Platform tab's ranking column is where a
#: ranking belongs. **VaR, RSI and Jensen alpha** followed in v0.9.30, from
#: terminal use — seven metrics across four windows is 28 columns, and the
#: three dropped are the ones a reader narrows by least. What is left is two
#: risk-adjusted returns and two benchmark-relative measures.
QUANT_METRICS: tuple[str, ...] = (
    "Sortino",
    "Calmar",
    "Beta",
    "Treynor",
)

#: The ones that need a benchmark. One dropdown feeds them here, where
#: `QuantFilter` gave each its own — three benchmarks in one table is a
#: comparison nobody asked for, and the bar has room for one control.
#: Jensen is still computed (Single Strategy's thresholds read it); it is no
#: longer a column.
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
        # `benchmark` is a price series; `ann_beta` covaries against
        # returns. See `stats.risk.benchmark_returns`.
        table["Beta"] = ann_beta(rets, benchmark_returns(benchmark), years)
        table["Treynor"] = treynor_ratio(rets, prices, benchmark, years)
        table["Jensen"] = jensen_alpha(rets, prices, benchmark, years)
        self._memo[key] = table
        return table

    def clear(self) -> None:
        """Drop everything, and the frame reference with it."""
        self._memo.clear()
        self._source = None

    def frame(
        self,
        prices: pd.DataFrame,
        tickers: pd.Index,
        *,
        benchmark: pd.Series | None,
        benchmark_name: str | None,
        returns: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """The quant block a catalog table carries: every metric, every window.

        Columns are `"<window> <metric>"`, which is what lets the Window chip
        hide the ones not on show and the comparison filter row filter the
        rest with no branch of its own (`quant_column_name`).

        **Every window is computed up front**, the catalog table's own rule
        (#324): switching windows hides columns, it never recomputes and never
        issues BQL. The memo above is what keeps that cheap across the four.

        Both tabs call this rather than each assembling the loop (#363 dec. 1).
        The one that existed before was the Multi tab's, and it had already
        been wrong twice — `stat_windows()` yields **years**, and dividing
        them by `TRADING_DAYS_PER_YEAR` asked for 1/252 of a year (v0.9.30).
        A second copy is a second chance at exactly that.
        """
        if prices.empty:
            return pd.DataFrame(index=tickers)
        blocks: list[pd.DataFrame] = []
        for label, years in stat_windows():
            table = self.table(
                prices,
                years=years,
                benchmark=benchmark,
                benchmark_name=benchmark_name,
                returns=returns,
            )
            if table.empty:
                continue
            block = table.reindex(columns=list(QUANT_METRICS))
            block.columns = [quant_column_name(label, m) for m in QUANT_METRICS]
            blocks.append(block)
        if not blocks:
            return pd.DataFrame(index=tickers)
        return pd.concat(blocks, axis=1).reindex(tickers)
