"""The two-tier price cache: an in-memory superset over a parquet tier (#221).

Both tiers used to be module globals in `bql_client`, mutated through `global`
statements by nine free functions. That made the cache a singleton — tests
reset it between cases, and nothing could hold a second one — while the
containment logic was spread across functions that all read the same two names.

The tiers themselves are unchanged:

**The superset.** One growing frame plus the interval it covers, tracked apart
from the data's own index so a weekend `end` with no trading row still counts
as covered. A contained request is served by slicing; a miss fetches only the
missing rectangle (`delta_specs`) and merges it in.

**The parquet tier**, keyed by `end` date under `cache_dir` and honoured only
within `ttl_hours` — and **absent** when `cache_dir` is None, which is the
app's default since v0.9.42 (`PRICE_CACHE_ON_DISK`). Every disk operation is
best-effort by contract: a read failure is a clean miss, and `disk_writable`
is the same tri-state warn-once probe as before — `None` until tried, then
`True`/`False`, and once `False` (a read-only BQuant terminal) writes stop for
the rest of the session while the in-memory tier carries on serving.
"""

from __future__ import annotations

import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .config import CACHE_DIR, CACHE_TTL_HOURS

#: One fetch rectangle: the tickers to fetch and the span to fetch them over.
DeltaSpec = tuple[list[str], date, date]


class PriceCache:
    """A two-tier price cache. Construct one per session, or per test."""

    def __init__(
        self,
        cache_dir: Path | str | None = CACHE_DIR,
        *,
        ttl_hours: float = CACHE_TTL_HOURS,
    ) -> None:
        #: None is memory-only: nothing is read from or written to disk.
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.ttl_hours = ttl_hours
        self.superset: pd.DataFrame | None = None
        self.cover: tuple[date, date] | None = None
        self.disk_writable: bool | None = None

    # --- in-memory superset ---------------------------------------------------

    def clear(self) -> None:
        """Drop everything held, including the writability probe."""
        self.superset = None
        self.cover = None
        self.disk_writable = None

    def covers(self, tickers: list[str], start: date, end: date) -> bool:
        """Whether the superset can serve ``(tickers, [start, end])``."""
        if self.superset is None or self.cover is None:
            return False
        if not set(tickers) <= set(self.superset.columns):
            return False
        return self.cover[0] <= start and self.cover[1] >= end

    def serve(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        """Slice the superset to ``(tickers, [start, end])`` in requested order."""
        sub = self.superset.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        return sub.reindex(columns=list(tickers)).copy()

    def merge(self, incoming: pd.DataFrame | None) -> None:
        """Union ``incoming`` into the superset; incoming wins on any overlap."""
        if incoming is None or incoming.empty:
            return
        if self.superset is None or self.superset.empty:
            self.superset = incoming.sort_index()
            return
        self.superset = incoming.combine_first(self.superset).sort_index()

    def extend_cover(self, start: date, end: date) -> None:
        """Widen the covered interval to include ``[start, end]``."""
        if self.cover is None:
            self.cover = (start, end)
        else:
            self.cover = (min(self.cover[0], start), max(self.cover[1], end))

    def delta_specs(
        self, tickers: list[str], start: date, end: date, *, use_cache: bool = True
    ) -> list[DeltaSpec]:
        """The minimal rectangles to fetch so the superset covers the request
        while staying a full grid.

        With nothing cached (or on a forced refresh) that's the whole request.
        Else: the existing columns are extended over any uncovered date range —
        non-overlapping with what's held, so cached values are never disturbed —
        and any new tickers are fetched over the full needed span.
        """
        cover = self.cover if (use_cache and self.superset is not None) else None
        columns = self.superset.columns if self.superset is not None else []
        if cover is None:
            return [(list(tickers), start, end)]
        cur_start, cur_end = cover
        existing_cols = list(columns)
        new_cols = [t for t in tickers if t not in set(columns)]
        need_start, need_end = min(start, cur_start), max(end, cur_end)
        specs: list[DeltaSpec] = []
        if existing_cols and start < cur_start:
            specs.append((existing_cols, start, cur_start - timedelta(days=1)))
        if existing_cols and end > cur_end:
            specs.append((existing_cols, cur_end + timedelta(days=1), end))
        if new_cols:
            specs.append((new_cols, need_start, need_end))
        if not specs:  # defensive: shouldn't happen on a genuine miss
            specs.append((list(tickers), start, end))
        return specs

    # --- parquet tier ---------------------------------------------------------

    def path_for(self, day: date) -> Path:
        return self.cache_dir / f"prices_{day.isoformat()}.parquet"

    def written_at(self, day: date) -> float | None:
        """The mtime of ``day``'s parquet, or None when there is none."""
        if self.cache_dir is None:
            return None
        try:
            return self.path_for(day).stat().st_mtime
        except OSError:
            return None

    def read_disk(
        self, day: date, tickers: list[str], start: date
    ) -> pd.DataFrame | None:
        """Read the same-day parquet, serving a ticker/date subset by containment.

        Returns the requested tickers over the file's dates when the file holds
        every requested ticker and reaches back to at least ``start`` (its `end`
        is the filename day). A missing ticker or too-short a history is a clean
        miss.
        """
        if self.cache_dir is None:
            return None
        path = self.path_for(day)
        if not path.exists():
            return None
        # Treat any read failure (corrupt parquet, vanished file, I/O error) as
        # a clean miss rather than crashing the load.
        try:
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            if age_hours >= self.ttl_hours:
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

    def write_disk(self, day: date, df: pd.DataFrame | None) -> None:
        """Persist ``df`` for ``day``, best-effort.

        Skips empties, and once the filesystem is known to be unwritable (e.g. a
        read-only BQuant terminal) stops retrying and stops re-warning — the
        in-memory tier carries the session.
        """
        if (
            self.cache_dir is None
            or df is None
            or df.empty
            or self.disk_writable is False
        ):
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(self.path_for(day), engine="pyarrow")
            self.disk_writable = True
            self.prune()
        except Exception as exc:
            self.disk_writable = False
            warnings.warn(
                f"Disk price cache is unwritable ({self.cache_dir}): {exc}. "
                "Continuing with the in-memory session cache only.",
                stacklevel=2,
            )

    def prune(self) -> None:
        """Delete parquet cache files older than the TTL (best-effort).

        One file is written per `end` date; without pruning they accumulate
        without bound. Never raises — a prune failure must not disturb the write
        that just succeeded.
        """
        if self.cache_dir is None:
            return
        try:
            cutoff = time.time() - self.ttl_hours * 3600
            for path in self.cache_dir.glob("prices_*.parquet"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    pass
        except Exception:
            pass
