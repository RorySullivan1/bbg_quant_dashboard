from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

try:
    import bql  # type: ignore
    _HAS_BQL = True
except Exception:
    _HAS_BQL = False


BQL_FIELD_KEY = "px_last"


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
    request = bql.Request(tickers, {BQL_FIELD_KEY: px})
    response = bq.execute(request)

    raw = response[0].df()
    if raw is None or raw.empty:
        raise RuntimeError(
            f"BQL returned no rows for {len(tickers)} tickers "
            f"({start.isoformat()} → {end.isoformat()}). "
            "Check that the tickers include the ' Index' suffix and resolve on the terminal."
        )

    df = raw.reset_index()
    df.columns = [str(c) for c in df.columns]

    id_col = _pick_column(df, ["ID", "id", "Security", "security", "TICKER", "ticker"])
    date_col = _pick_column(df, ["DATE", "Date", "date", "AS_OF_DATE", "as_of_date"])
    value_col = _pick_column(
        df,
        [BQL_FIELD_KEY, "px_last", "PX_LAST", "VALUE", "value", "Value"],
    )

    if id_col is None or date_col is None or value_col is None:
        raise RuntimeError(
            f"Could not locate ID/DATE/value columns in BQL response. "
            f"Available columns: {list(df.columns)}. "
            f"Raw shape: {raw.shape}, index: {list(raw.index.names)}."
        )

    wide = df.pivot(index=date_col, columns=id_col, values=value_col)
    wide.index = pd.to_datetime(wide.index)
    wide = wide.sort_index()
    aligned = wide.reindex(columns=tickers)
    if aligned.dropna(how="all", axis=1).empty:
        raise RuntimeError(
            f"BQL response columns {list(wide.columns)[:5]}{'…' if len(wide.columns) > 5 else ''} "
            f"did not match any requested ticker (sample requested: {tickers[:5]}). "
            "The reindex produced an all-NaN frame."
        )
    return aligned


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    lower = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in df.columns:
            return cand
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


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
