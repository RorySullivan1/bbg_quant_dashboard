from __future__ import annotations

import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CACHE_DIR, CACHE_TTL_HOURS

try:
    import bql  # type: ignore

    _HAS_BQL = True
except Exception:
    _HAS_BQL = False


BQL_FIELD_KEY = "px_last"

# In-memory session cache for fetched prices, checked before the on-disk
# parquet so the BQuant filesystem (which may be read-only) is never required.
# Keyed by ``(tuple(sorted(tickers)), start, end)`` → the wide price frame.
_MEM_CACHE: dict[tuple, pd.DataFrame] = {}

# Tri-state writability of the on-disk parquet cache: ``None`` until probed,
# then ``True``/``False``. Once ``False`` (e.g. a read-only filesystem) we stop
# attempting disk writes for the rest of the session.
_disk_cache_writable: bool | None = None


def _clear_caches() -> None:
    """Reset the in-memory cache and disk-writability probe (test hook)."""
    global _disk_cache_writable
    _MEM_CACHE.clear()
    _disk_cache_writable = None


def fetch_prices(
    tickers: list[str],
    start: date,
    end: date,
    use_cache: bool = True,
) -> tuple[pd.DataFrame, str]:
    """Wide DataFrame of px_last: date index, one column per ticker.

    Returns `(df, source)` where `source` is one of `"cache"`, `"bql"`,
    or `"mock"` so callers can report what served the request.

    Falls back to a deterministic synthetic series when bql is unavailable
    (off-terminal development), so the dashboard renders end-to-end.

    When `use_cache=True` (default) the in-memory session cache is checked
    first, then a same-day parquet under `CACHE_DIR` that covers every
    requested ticker within `CACHE_TTL_HOURS`; either is returned without
    hitting BQL. On a miss or with `use_cache=False` the live fetch result is
    written to both caches before returning. Disk writes are best-effort: on a
    read-only filesystem the in-memory cache still serves the session.
    """
    if not tickers:
        return pd.DataFrame(), "cache"

    key = (tuple(sorted(tickers)), start, end)
    if use_cache:
        mem = _MEM_CACHE.get(key)
        if mem is not None:
            return mem.reindex(columns=tickers), "cache"
        cached = _cache_read(end, tickers)
        if cached is not None:
            _MEM_CACHE[key] = cached
            return cached, "cache"

    if _HAS_BQL:
        df = _fetch_via_bql(tickers, start, end)
        source = "bql"
    else:
        df = _mock_prices(tickers, start, end)
        source = "mock"
    _cache_write(end, df)
    _MEM_CACHE[key] = df
    return df, source


def _cache_path(day: date) -> Path:
    return CACHE_DIR / f"prices_{day.isoformat()}.parquet"


def _cache_read(day: date, tickers: list[str]) -> pd.DataFrame | None:
    path = _cache_path(day)
    if not path.exists():
        return None
    # Treat any read failure (corrupt parquet, vanished file, I/O error) as a
    # clean miss rather than crashing the load.
    try:
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours >= CACHE_TTL_HOURS:
            return None
        df = pd.read_parquet(path)
    except Exception:
        return None
    missing = set(tickers) - set(df.columns)
    if missing:
        return None
    return df.reindex(columns=tickers)


def _cache_write(day: date, df: pd.DataFrame) -> None:
    # Best-effort: skip empties, and once the filesystem is known to be
    # unwritable (e.g. a read-only BQuant terminal) don't keep retrying — the
    # in-memory cache carries the session.
    global _disk_cache_writable
    if df.empty or _disk_cache_writable is False:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(_cache_path(day), engine="pyarrow")
        _disk_cache_writable = True
    except Exception as exc:
        _disk_cache_writable = False
        warnings.warn(
            f"Disk price cache is unwritable ({CACHE_DIR}): {exc}. "
            "Continuing with the in-memory session cache only.",
            stacklevel=2,
        )


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
