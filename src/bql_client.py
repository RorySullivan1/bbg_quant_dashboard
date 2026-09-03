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

# In-memory session cache. Rather than an exact-key map (which forced a full
# refetch whenever the lookback shifted or one ticker was added), the session
# holds a single growing **superset** frame plus the date interval it covers.
# Any request whose tickers ⊆ the superset's columns and whose [start, end] ⊆
# the covered interval is served by *slicing* — no BQL. A miss fetches only the
# missing rectangle (new tickers, and/or the uncovered date extension) and
# merges it in, so extending the lookback or adding an index costs a delta, not
# a whole-universe refetch. The covered interval is tracked separately from the
# data index so a weekend/holiday `end` (no trading row) still counts as covered.
_MEM_SUPERSET: pd.DataFrame | None = None
_MEM_COVER: tuple[date, date] | None = None

# Tri-state writability of the on-disk parquet cache: ``None`` until probed,
# then ``True``/``False``. Once ``False`` (e.g. a read-only filesystem) we stop
# attempting disk writes for the rest of the session.
_disk_cache_writable: bool | None = None

# --- off-terminal mock resolution seams (#195) -------------------------------
# `_mock_prices` seeds a generator off `hash(ticker)`, so off-terminal it
# resolves *any* string — which is right for its original purpose (the whole
# dashboard renders without a terminal) and wrong for anything that has to cope
# with a ticker the user typed. With no way to make the mock say "no", every
# validation path is untestable off-terminal, and the test suite runs nowhere
# else. That is the shape of failure #186 was: a caveat marked untestable in CI
# that then broke in production.
#
# These two seams let a test drive the mock into the live path's two failure
# modes, which are *different* and must not be conflated downstream:
#
#   _MOCK_UNRESOLVABLE  the ticker does not resolve at all — a wrong ticker.
#   _MOCK_FIRST_TRADE   the ticker resolves but has no data before the given
#                       date — a real security that launched mid-window, or a
#                       stale one. Rows before it are NaN.
#
# Both are empty by default, so the mock's behaviour is unchanged for every
# ticker the app actually uses. `_clear_caches` resets them.
_MOCK_UNRESOLVABLE: set[str] = set()
_MOCK_FIRST_TRADE: dict[str, date] = {}


def _clear_caches() -> None:
    """Reset the in-memory superset, disk-writability probe, and mock seams."""
    global _disk_cache_writable, _MEM_SUPERSET, _MEM_COVER
    _MEM_SUPERSET = None
    _MEM_COVER = None
    _disk_cache_writable = None
    _MOCK_UNRESOLVABLE.clear()
    _MOCK_FIRST_TRADE.clear()


def _live_fetch(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """One live fetch (BQL on a terminal, deterministic mock off it)."""
    if _HAS_BQL:
        return _fetch_via_bql(tickers, start, end)
    return _mock_prices(tickers, start, end)


def _covers(tickers: list[str], start: date, end: date) -> bool:
    """Whether the in-memory superset can serve ``(tickers, [start, end])``."""
    if _MEM_SUPERSET is None or _MEM_COVER is None:
        return False
    if not set(tickers) <= set(_MEM_SUPERSET.columns):
        return False
    return _MEM_COVER[0] <= start and _MEM_COVER[1] >= end


def _serve(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Slice the superset to ``(tickers, [start, end])`` in requested order."""
    sub = _MEM_SUPERSET.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    return sub.reindex(columns=list(tickers)).copy()


def _merge_superset(base: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Union ``incoming`` into ``base`` (incoming wins on any overlap)."""
    if incoming is None or incoming.empty:
        return base if base is not None else incoming
    if base is None or base.empty:
        return incoming.sort_index()
    return incoming.combine_first(base).sort_index()


def _extend_cover(
    cover: tuple[date, date] | None, start: date, end: date
) -> tuple[date, date]:
    if cover is None:
        return (start, end)
    return (min(cover[0], start), max(cover[1], end))


def _delta_specs(
    cover: tuple[date, date] | None,
    columns,
    tickers: list[str],
    start: date,
    end: date,
) -> list[tuple[list[str], date, date]]:
    """The minimal (tickers, start, end) rectangles to fetch so the superset
    covers ``(tickers, [start, end])`` while staying a full grid.

    With nothing cached (or on a forced refresh) that's the whole request. Else:
    the existing columns are extended over any uncovered date range (non-
    overlapping with what's held, so cached values are never disturbed), and any
    new tickers are fetched over the full needed span.
    """
    if cover is None:
        return [(list(tickers), start, end)]
    cur_start, cur_end = cover
    existing_cols = list(columns)
    new_cols = [t for t in tickers if t not in set(columns)]
    need_start, need_end = min(start, cur_start), max(end, cur_end)
    specs: list[tuple[list[str], date, date]] = []
    if existing_cols and start < cur_start:
        specs.append((existing_cols, start, cur_start - timedelta(days=1)))
    if existing_cols and end > cur_end:
        specs.append((existing_cols, cur_end + timedelta(days=1), end))
    if new_cols:
        specs.append((new_cols, need_start, need_end))
    if not specs:  # defensive: shouldn't happen on a genuine miss
        specs.append((list(tickers), start, end))
    return specs


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

    When `use_cache=True` (default) the request is served from the in-memory
    session superset if its tickers and date range are already covered; else a
    same-day parquet under `CACHE_DIR` (within `CACHE_TTL_HOURS`) is tried the
    same way. On a miss, only the missing rectangle — new tickers and/or the
    uncovered date extension — is fetched and merged into the superset, so a
    lookback change or an added index costs a delta rather than a whole-universe
    refetch. `use_cache=False` (Refresh prices) refetches the full request and
    overwrites the overlapping region. Disk writes are best-effort: on a
    read-only filesystem the in-memory superset still serves the session.
    """
    global _MEM_SUPERSET, _MEM_COVER
    if not tickers:
        return pd.DataFrame(), "cache"

    if use_cache:
        if _covers(tickers, start, end):
            return _serve(tickers, start, end), "cache"
        disk = _cache_read(end, tickers, start)
        if disk is not None:
            _MEM_SUPERSET = _merge_superset(_MEM_SUPERSET, disk)
            _MEM_COVER = _extend_cover(_MEM_COVER, start, end)
            if _covers(tickers, start, end):
                return _serve(tickers, start, end), "cache"

    # Fetch only what's missing (the whole request when nothing is cached or on
    # a forced refresh), then merge into the superset.
    base_cover = _MEM_COVER if (use_cache and _MEM_SUPERSET is not None) else None
    base_cols = _MEM_SUPERSET.columns if _MEM_SUPERSET is not None else []
    specs = _delta_specs(base_cover, base_cols, tickers, start, end)
    source = "bql" if _HAS_BQL else "mock"
    merged = _MEM_SUPERSET
    for spec_tickers, spec_start, spec_end in specs:
        merged = _merge_superset(
            merged, _live_fetch(spec_tickers, spec_start, spec_end)
        )
    _MEM_SUPERSET = merged
    _MEM_COVER = _extend_cover(_MEM_COVER, start, end)
    _cache_write(end, _MEM_SUPERSET)
    return _serve(tickers, start, end), source


def _cache_path(day: date) -> Path:
    return CACHE_DIR / f"prices_{day.isoformat()}.parquet"


def _cache_read(day: date, tickers: list[str], start: date) -> pd.DataFrame | None:
    """Read the same-day parquet, serving a ticker/date subset by containment.

    Returns the requested tickers over the file's dates when the file holds
    every requested ticker and reaches back to at least ``start`` (its `end` is
    the filename day). A missing ticker or too-short a history is a clean miss.
    """
    path = _cache_path(day)
    if not path.exists():
        return None
    # Treat any read failure (corrupt parquet, vanished file, I/O error) as a
    # clean miss rather than crashing the load.
    try:
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours >= CACHE_TTL_HOURS:
            return None
        df = pd.read_parquet(path, columns=list(tickers))
    except Exception:
        return None
    if set(tickers) - set(df.columns):
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.empty or df.index.min() > pd.Timestamp(start):
        return None
    return df.reindex(columns=list(tickers))


def _cache_write(day: date, df: pd.DataFrame) -> None:
    # Best-effort: skip empties, and once the filesystem is known to be
    # unwritable (e.g. a read-only BQuant terminal) don't keep retrying — the
    # in-memory cache carries the session.
    global _disk_cache_writable
    if df is None or df.empty or _disk_cache_writable is False:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(_cache_path(day), engine="pyarrow")
        _disk_cache_writable = True
        _prune_cache_files()
    except Exception as exc:
        _disk_cache_writable = False
        warnings.warn(
            f"Disk price cache is unwritable ({CACHE_DIR}): {exc}. "
            "Continuing with the in-memory session cache only.",
            stacklevel=2,
        )


def _prune_cache_files() -> None:
    """Delete parquet cache files older than the TTL (best-effort).

    The cache writes one file per `end` date; without pruning they accumulate
    without bound. Never raises — a prune failure must not disturb the write
    that just succeeded.
    """
    try:
        cutoff = time.time() - CACHE_TTL_HOURS * 3600
        for path in CACHE_DIR.glob("prices_*.parquet"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
    except Exception:
        pass


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
    """Deterministic synthetic prices, one column per ticker.

    Mirrors the *contract* of the live path rather than its internals: a ticker
    that doesn't resolve comes back as an all-NaN column (warned, not fatal) so
    the rest of the frame still loads, and only a request where **nothing**
    resolves raises. See the ``_MOCK_UNRESOLVABLE`` / ``_MOCK_FIRST_TRADE``
    seams above for how a test drives those cases; with both empty — always, in
    the app — every ticker resolves over the full window exactly as before.
    """
    idx = pd.bdate_range(start=start, end=end)
    resolved = [t for t in tickers if t not in _MOCK_UNRESOLVABLE]
    unresolved = [t for t in tickers if t in _MOCK_UNRESOLVABLE]

    if tickers and not resolved:
        # Matches `_assemble_batches`' terminal raise: a request where nothing
        # resolves is loud, never a silently all-NaN dashboard.
        raise RuntimeError(
            f"Mock resolved none of {len(tickers)} tickers "
            f"({start.isoformat()} → {end.isoformat()})."
        )
    if unresolved:
        warnings.warn(
            f"{len(unresolved)} of {len(tickers)} tickers did not resolve in the "
            f"mock and are NaN in the result (e.g. {unresolved[:5]}).",
            stacklevel=2,
        )

    out = pd.DataFrame(index=idx)
    for ticker in resolved:
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

    # A ticker that launched mid-window resolves but has no data before its
    # first trade date — NaN there, not a shorter frame, matching how BQL
    # returns a security with no history at the start of the range.
    for ticker, first in _MOCK_FIRST_TRADE.items():
        if ticker in out.columns:
            out.loc[out.index < pd.Timestamp(first), ticker] = np.nan

    # Unresolved tickers come back as all-NaN columns, in the requested order.
    out = out.reindex(columns=list(tickers))
    out.index.name = "DATE"
    return out


def default_window(lookback_years: int) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=int(lookback_years * 365.25))
    return start, end
