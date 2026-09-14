"""Price fetching: BQL on a Bloomberg terminal, deterministic mock off it.

`fetch_prices` is the only entry point the app uses. It returns a wide frame
(dates × tickers of `px_last`) plus the source it came from, and is designed so
the dashboard issues **one** fetch at startup and serves everything after that
from cache.

Three mechanisms make that hold:

**A superset session cache.** One growing frame plus the interval it covers:
a contained request is served by slicing, a miss fetches only the missing
rectangle. Extending the lookback or adding a benchmark costs a delta, not a
whole-universe refetch. The interval is tracked apart from the data index, so
a weekend `end` with no trading row still counts as covered.

**Batched requests with per-ticker fallback.** One request for hundreds of
tickers risks BQL's row and wall-clock limits, so the universe is split into
retried batches. A batch that still fails is re-fetched a ticker at a time, so
only genuinely unresolvable tickers degrade to NaN instead of blanking the load.

**A best-effort parquet tier** keyed by `end` date, skipped once a write fails
so a read-only filesystem costs nothing.

Both tiers live on a `PriceCache` (`price_cache.py`, #221) rather than module
globals; `fetch_prices` uses the module's default instance unless a caller
passes its own.

Off-terminal the mock stands in for all of this, deterministically per ticker.
"""

from __future__ import annotations

import time
import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import (
    BQL_BATCH_SIZE,
    BQL_MAX_RETRIES,
    BQL_RETRY_BACKOFF_S,
    LEVEL_INDICATOR_MOCK,
)
from .price_cache import PriceCache

try:
    import bql  # type: ignore

    _HAS_BQL = True
except Exception:
    _HAS_BQL = False


BQL_FIELD_KEY = "px_last"


class TickersUnresolved(RuntimeError):
    """No ticker in the request resolved.

    Distinct from a transport or session failure, which is what every *other*
    exception out of a fetch means. Callers that add a single ticker need the
    difference: a one-ticker request has no healthy peers to degrade against,
    so the per-ticker isolation cannot turn a bad ticker into a NaN column — it
    comes back as this, and "your ticker is wrong" is a very different message
    from "the BQL session dropped". Subclasses ``RuntimeError`` so existing
    handlers and tests are unaffected.
    """


#: The cache `fetch_prices` uses when a caller doesn't pass its own — the app
#: only ever wants one per session. Tests construct their own `PriceCache`
#: instead of resetting this one.
_DEFAULT_CACHE = PriceCache()

# --- off-terminal mock resolution seams ---------------------------------------
# `_mock_prices` resolves *any* string, so these two seams let a test drive it
# into the live path's two failure modes, which must not be conflated
# downstream. Both are empty by default and `_clear_caches` resets them; see
# `.claude/context/testing_notes.md` for why they exist.

#: Tickers that do not resolve at all — a wrong ticker.
_MOCK_UNRESOLVABLE: set[str] = set()
#: Ticker -> first date with data. The ticker resolves but has no history
#: before that date (a security that launched mid-window, or a stale one), so
#: earlier rows are NaN.
_MOCK_FIRST_TRADE: dict[str, date] = {}


def _clear_caches() -> None:
    """Reset the default cache and the mock seams (test hook)."""
    _DEFAULT_CACHE.clear()
    _MOCK_UNRESOLVABLE.clear()
    _MOCK_FIRST_TRADE.clear()


def _live_fetch(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """One live fetch (BQL on a terminal, deterministic mock off it)."""
    if _HAS_BQL:
        return _fetch_via_bql(tickers, start, end)
    return _mock_prices(tickers, start, end)


def fetch_prices(
    tickers: list[str],
    start: date,
    end: date,
    use_cache: bool = True,
    cache: PriceCache | None = None,
) -> tuple[pd.DataFrame, str]:
    """Wide DataFrame of px_last: date index, one column per ticker.

    Returns `(df, source)` where `source` is one of `"cache"`, `"bql"`,
    or `"mock"` so callers can report what served the request.

    Falls back to a deterministic synthetic series when bql is unavailable
    (off-terminal development), so the dashboard renders end-to-end.

    When `use_cache=True` (default) the request is served from the in-memory
    session superset if its tickers and date range are already covered; else a
    same-day parquet under the cache's `cache_dir` (within its `ttl_hours`) is
    tried the same way. On a miss, only the missing rectangle — new tickers and/or the
    uncovered date extension — is fetched and merged into the superset, so a
    lookback change or an added index costs a delta rather than a whole-universe
    refetch. `use_cache=False` (Refresh prices) refetches the full request and
    overwrites the overlapping region. Disk writes are best-effort: on a
    read-only filesystem the in-memory superset still serves the session.

    `cache` defaults to the module's session-wide `PriceCache`; pass one to
    isolate a fetch (a test, or a second independent session).
    """
    cache = cache if cache is not None else _DEFAULT_CACHE
    if not tickers:
        return pd.DataFrame(), "cache"

    if use_cache:
        if cache.covers(tickers, start, end):
            return cache.serve(tickers, start, end), "cache"
        disk = cache.read_disk(end, tickers, start)
        if disk is not None:
            cache.merge(disk)
            cache.extend_cover(start, end)
            if cache.covers(tickers, start, end):
                return cache.serve(tickers, start, end), "cache"

    # Fetch only what's missing (the whole request when nothing is cached or on
    # a forced refresh), then merge into the superset.
    specs = cache.delta_specs(tickers, start, end, use_cache=use_cache)
    source = "bql" if _HAS_BQL else "mock"
    for spec_tickers, spec_start, spec_end in specs:
        cache.merge(_live_fetch(spec_tickers, spec_start, spec_end))
    cache.extend_cover(start, end)
    cache.write_disk(end, cache.superset)
    return cache.serve(tickers, start, end), source


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


def _salvage_batch(
    batch: list[str],
    start: date,
    end: date,
    fetch_batch,
) -> tuple[list[pd.DataFrame], list[str]]:
    """Re-fetch a failed batch's tickers one at a time.

    A batch fails as a unit, so a single unresolvable ticker would otherwise
    take every ticker beside it down. Fetching them individually narrows the
    blast radius to the tickers that are actually bad.

    Each ticker gets a *single* attempt (``retries=0``): the batch has already
    exhausted the retry ladder, so repeating it per ticker would multiply an
    already-slow failure path by the batch size for no added signal.

    Returns ``(frames, failed)`` — the single-ticker frames that resolved, and
    the tickers the caller should degrade to NaN columns.
    """
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    for ticker in batch:
        try:
            frames.append(
                _fetch_batch_with_retry([ticker], start, end, fetch_batch, retries=0)
            )
        except Exception:  # noqa: BLE001 — one bad ticker shouldn't fail its peers
            failed.append(ticker)
    return frames, failed


def _assemble_batches(
    tickers: list[str],
    start: date,
    end: date,
    fetch_batch,
    *,
    batch_size: int = BQL_BATCH_SIZE,
) -> pd.DataFrame:
    """Fetch ``tickers`` in batches via ``fetch_batch``, isolating failures.

    Each batch of ``batch_size`` tickers is fetched (with retry) independently.
    A batch that still fails is **re-fetched one ticker at a time** so only the
    genuinely unresolvable tickers degrade to NaN columns — warned, not fatal.
    Without that per-ticker pass the isolation is only as fine-grained as the
    batch, which is no isolation at all whenever the universe fits in a single
    batch: one bad ticker would blank the whole dashboard. Only when **every**
    ticker fails, individually, does this raise. The surviving frames are
    concatenated and reindexed to the full requested ticker list.

    The per-ticker sweep runs only for a batch that already failed, so the
    healthy path still costs exactly one request per batch.
    """
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    for batch in _chunked(tickers, batch_size):
        try:
            frames.append(_fetch_batch_with_retry(batch, start, end, fetch_batch))
        except Exception as exc:  # noqa: BLE001 — one bad batch shouldn't fail all
            if len(batch) == 1:
                # Already at ticker granularity — nothing left to narrow down.
                failed.extend(batch)
                continue
            warnings.warn(
                f"BQL batch of {len(batch)} tickers failed after retries "
                f"({exc}); re-fetching its tickers individually. "
                f"Sample: {batch[:5]}.",
                stacklevel=2,
            )
            recovered, lost = _salvage_batch(batch, start, end, fetch_batch)
            frames.extend(recovered)
            failed.extend(lost)

    if not frames:
        raise TickersUnresolved(
            f"Every BQL request failed for {len(tickers)} tickers "
            f"({start.isoformat()} → {end.isoformat()}) — batched, then retried "
            "one ticker at a time. Check the terminal session and that tickers "
            "include the ' Index' suffix."
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
        raise TickersUnresolved(
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
