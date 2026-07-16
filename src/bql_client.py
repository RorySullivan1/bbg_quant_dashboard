from __future__ import annotations

import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    BQL_BATCH_SIZE,
    BQL_MAX_RETRIES,
    BQL_RETRY_BACKOFF_S,
    CACHE_DIR,
    CACHE_TTL_HOURS,
    LEVEL_INDICATOR_MOCK,
)

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


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    """Split ``seq`` into consecutive chunks of at most ``size`` items."""
    size = max(1, size)
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _reshape_bql_response(
    raw: pd.DataFrame | None,
    batch: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Pivot one batch's long-form BQL response into a wide date×ticker frame.

    Raises ``RuntimeError`` on an empty response or unlocatable columns so the
    caller can retry the batch or degrade it to NaN columns. The ID column is
    cast to ``category`` before the pivot — a per-row string label over a
    multi-year daily response is a large object-dtype column, and categorizing
    it shrinks the pivot's transient memory.
    """
    if raw is None or raw.empty:
        raise RuntimeError(
            f"BQL returned no rows for {len(batch)} tickers "
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

    df[id_col] = df[id_col].astype("category")
    wide = df.pivot(index=date_col, columns=id_col, values=value_col)
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def _fetch_batch_with_retry(
    batch: list[str],
    start: date,
    end: date,
    fetch_batch,
    *,
    retries: int = BQL_MAX_RETRIES,
    backoff: float = BQL_RETRY_BACKOFF_S,
) -> pd.DataFrame:
    """Call ``fetch_batch(batch, start, end)`` with bounded exponential backoff.

    Retries transient BQL failures (network blips, momentary server limits) up
    to ``retries`` extra times; re-raises the last error if they all fail so the
    batch can be degraded to NaN columns by the caller.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fetch_batch(batch, start, end)
        except Exception as exc:  # noqa: BLE001 — retry any BQL failure
            last_exc = exc
            if attempt < retries and backoff > 0:
                time.sleep(backoff * (2**attempt))
    assert last_exc is not None
    raise last_exc


def _assemble_batches(
    tickers: list[str],
    start: date,
    end: date,
    fetch_batch,
    *,
    batch_size: int = BQL_BATCH_SIZE,
) -> pd.DataFrame:
    """Fetch ``tickers`` in batches via ``fetch_batch``, isolating failures.

    Each batch of ``batch_size`` tickers is fetched (with retry) independently;
    a batch that still fails degrades to NaN columns — warned, not fatal — so a
    handful of unresolvable tickers can't blank the whole dashboard. Only when
    **every** batch fails (nothing fetched) does this raise. The surviving
    batches are concatenated and reindexed to the full requested ticker list.
    """
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    for batch in _chunked(tickers, batch_size):
        try:
            frames.append(_fetch_batch_with_retry(batch, start, end, fetch_batch))
        except Exception as exc:  # noqa: BLE001 — one bad batch shouldn't fail all
            failed.extend(batch)
            warnings.warn(
                f"BQL batch of {len(batch)} tickers failed after retries "
                f"({exc}); degrading those to NaN columns. "
                f"Sample: {batch[:5]}.",
                stacklevel=2,
            )

    if not frames:
        raise RuntimeError(
            f"Every BQL batch failed for {len(tickers)} tickers "
            f"({start.isoformat()} → {end.isoformat()}). "
            "Check the terminal session and that tickers include the ' Index' suffix."
        )
    if failed:
        warnings.warn(
            f"{len(failed)} of {len(tickers)} tickers could not be fetched and "
            f"are NaN in the result (e.g. {failed[:5]}).",
            stacklevel=2,
        )

    combined = frames[0] if len(frames) == 1 else pd.concat(frames, axis=1)
    combined = combined.sort_index()
    aligned = combined.reindex(columns=tickers)
    if aligned.dropna(how="all", axis=1).empty:
        raise RuntimeError(
            f"BQL response columns {list(combined.columns)[:5]}"
            f"{'…' if len(combined.columns) > 5 else ''} did not match any "
            f"requested ticker (sample requested: {tickers[:5]}). "
            "The reindex produced an all-NaN frame."
        )
    return aligned


def _fetch_via_bql(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Batched whole-universe px_last fetch (one BQL request per ticker batch)."""
    bq = bql.Service()
    px = bq.data.px_last(
        dates=bq.func.range(start.isoformat(), end.isoformat()),
        fill="prev",
    )

    def fetch_batch(batch: list[str], s: date, e: date) -> pd.DataFrame:
        response = bq.execute(bql.Request(batch, {BQL_FIELD_KEY: px}))
        return _reshape_bql_response(response[0].df(), batch, s, e)

    return _assemble_batches(tickers, start, end, fetch_batch)


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
        if ticker in LEVEL_INDICATOR_MOCK:
            # Mean-reverting absolute *level* (not a compounding price) so the
            # regime buckets partition the off-terminal mock. Per-indicator
            # (mean, vol, lo, hi): VIX hovers ~18 clipped [9, 60]; short rates
            # ~2.0; the NFCI risk subindex straddles 0.
            mean, vol, lo, hi = LEVEL_INDICATOR_MOCK[ticker]
            level = mean
            vals = np.empty(len(idx))
            for t in range(len(idx)):
                level += 0.05 * (mean - level) + rng.normal(0.0, vol)
                level = min(max(level, lo), hi)
                vals[t] = level
            out[ticker] = vals
            continue
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
