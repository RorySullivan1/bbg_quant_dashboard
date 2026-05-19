from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

try:
    import bql  # type: ignore
    _HAS_BQL = True
except Exception:
    _HAS_BQL = False


def fetch_prices(
    tickers: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Wide DataFrame of px_last: date index, one column per ticker.

    Falls back to a deterministic synthetic series when bql is unavailable
    (off-terminal development), so the dashboard renders end-to-end.
    """
    if not tickers:
        return pd.DataFrame()

    if _HAS_BQL:
        return _fetch_via_bql(tickers, start, end)
    return _mock_prices(tickers, start, end)


def _fetch_via_bql(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    bq = bql.Service()
    px = bq.data.px_last(
        dates=bq.func.range(start.isoformat(), end.isoformat()),
        fill="prev",
    )
    request = bql.Request(tickers, {"px_last": px})
    response = bq.execute(request)
    df = response[0].df().reset_index()
    wide = df.pivot(index="DATE", columns="ID", values="px_last")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()[tickers]


def _mock_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    idx = pd.bdate_range(start=start, end=end)
    out = pd.DataFrame(index=idx)
    for ticker in tickers:
        rng = np.random.default_rng(abs(hash(ticker)) % (2**32))
        drift = rng.uniform(0.02, 0.10) / 252
        vol = rng.uniform(0.08, 0.30) / np.sqrt(252)
        steps = rng.normal(loc=drift, scale=vol, size=len(idx))
        out[ticker] = 100 * np.exp(np.cumsum(steps))
    out.index.name = "DATE"
    return out


def default_window(lookback_years: int) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=int(lookback_years * 365.25))
    return start, end
