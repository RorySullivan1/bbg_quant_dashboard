"""The selected set's data slice, computed once per recompute (#217).

`build_app._recompute` used to assemble this as a `SimpleNamespace` of five
fields and then bolt three more on afterwards, so the object was briefly
incomplete and nothing said which shape a renderer could rely on. `build`
computes all eight together and the result is frozen, which is also what lets
`DashboardState.cur_prep` carry a real type.

Everything here derives from one windowed price frame plus the window bounds.
The bounds are carried rather than re-derived from the frame's index: they come
from the analysis date boxes and may fall outside the traded days, and the
benchmark series are sliced against them, so `index.min()` would quietly narrow
the comparison window.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..stats import (
    corr_matrix,
    cum_perf,
    daily_returns,
    drawdown_series,
    perf_table,
    return_distribution_stats,
    rolling_sharpe_zscore,
)


@dataclass(frozen=True)
class SelectionSlice:
    """Everything the analysis panes need about the current selection."""

    #: The selected tickers' prices over the analysis window.
    window: pd.DataFrame
    rets: pd.DataFrame
    perf: pd.DataFrame
    pt: pd.DataFrame
    dd: pd.DataFrame
    sz_series: pd.DataFrame
    cm: pd.DataFrame
    rd_stats: pd.DataFrame
    win_start: pd.Timestamp
    win_end: pd.Timestamp

    @classmethod
    def build(
        cls, window: pd.DataFrame, win_start: pd.Timestamp, win_end: pd.Timestamp
    ) -> SelectionSlice:
        """Compute the whole slice from ``window``.

        Returns are computed once and threaded into every dependent rather than
        each of them calling `daily_returns` again — the reason this is one
        object and not seven separate calls at the call site.
        """
        rets = daily_returns(window)
        return cls(
            window=window,
            rets=rets,
            perf=cum_perf(window),
            pt=perf_table(window, returns=rets),
            dd=drawdown_series(window),
            sz_series=rolling_sharpe_zscore(rets),
            cm=corr_matrix(rets),
            rd_stats=return_distribution_stats(rets),
            win_start=win_start,
            win_end=win_end,
        )
