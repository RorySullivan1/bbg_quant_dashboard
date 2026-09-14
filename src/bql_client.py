"""Price fetching with caching: the one entry point the app uses.

`fetch_prices` returns a wide frame (dates × tickers of `px_last`) plus the
source it came from, and is designed so the dashboard issues **one** fetch at
startup and serves everything after that from cache.

Two collaborators do the actual work, so this module is just the orchestration
between them:

- **`PriceSource`** (`price_source.py`) — BQL on a terminal, a deterministic
  mock off it, both honouring the same failure contract (batched requests with
  per-ticker fallback, NaN columns for unresolvable tickers among healthy peers,
  `TickersUnresolved` when nothing resolves).
- **`PriceCache`** (`price_cache.py`) — the in-memory superset over a
  best-effort parquet tier. A contained request is served by slicing; a miss
  fetches only the missing rectangle.

Both default to a module-level instance, so callers pass nothing and get the
session's; a test passes its own and is fully isolated.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .price_cache import PriceCache
from .price_source import (
    HAS_BQL,
    BqlPriceSource,
    MockPriceSource,
    PriceSource,
    TickersUnresolved,
    default_price_source,
)

# Re-exported so existing imports (`from .bql_client import TickersUnresolved`)
# and tests that reach for `bc.HAS_BQL` keep working after the #222 split.
__all__ = [
    "HAS_BQL",
    "BqlPriceSource",
    "MockPriceSource",
    "PriceCache",
    "PriceSource",
    "TickersUnresolved",
    "default_window",
    "fetch_prices",
]

#: The cache and source `fetch_prices` uses when a caller doesn't pass its own —
#: the app only ever wants one of each per session. Tests construct their own.
_DEFAULT_CACHE = PriceCache()
_DEFAULT_SOURCE: PriceSource = default_price_source()


def fetch_prices(
    tickers: list[str],
    start: date,
    end: date,
    use_cache: bool = True,
    cache: PriceCache | None = None,
    source: PriceSource | None = None,
) -> tuple[pd.DataFrame, str]:
    """Wide DataFrame of px_last: date index, one column per ticker.

    Returns `(df, source_name)` where `source_name` is one of `"cache"`,
    `"bql"`, or `"mock"` so callers can report what served the request.

    When `use_cache=True` (default) the request is served from the in-memory
    session superset if its tickers and date range are already covered; else a
    same-day parquet under the cache's `cache_dir` (within its `ttl_hours`) is
    tried the same way. On a miss, only the missing rectangle — new tickers
    and/or the uncovered date extension — is fetched and merged into the
    superset, so a lookback change or an added index costs a delta rather than a
    whole-universe refetch. `use_cache=False` (Refresh prices) refetches the
    full request and overwrites the overlapping region. Disk writes are
    best-effort: on a read-only filesystem the in-memory superset still serves
    the session.

    `cache` and `source` default to the module's session-wide instances; pass
    either to isolate a fetch (a test, or a second independent session).
    """
    cache = cache if cache is not None else _DEFAULT_CACHE
    source = source if source is not None else _DEFAULT_SOURCE
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
    for spec_tickers, spec_start, spec_end in specs:
        cache.merge(source.fetch(spec_tickers, spec_start, spec_end))
    cache.extend_cover(start, end)
    cache.write_disk(end, cache.superset)
    return cache.serve(tickers, start, end), source.name


def default_window(lookback_years: int) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=int(lookback_years * 365.25))
    return start, end
