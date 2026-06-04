"""A tiny bounded LRU cache (stdlib only).

Used to memoize the benchmark-dependent chart results (rolling correlation /
beta, outperformance, regime correlation matrix) so flipping back to a
previously-viewed benchmark is an instant cache hit instead of a recompute.
The DataFrame/Series inputs to those stats functions are unhashable and the
cache must be cleared whenever the selection slice changes, so `functools.
lru_cache` doesn't fit — this is the manual-dict equivalent, mirroring the
`_MEM_CACHE` pattern in `src/bql_client.py`.

Leaf module: no project imports, so anything may depend on it.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import TypeVar

T = TypeVar("T")


class LRUCache:
    """Least-recently-used cache with a fixed capacity.

    Keys must be hashable; values are arbitrary. On overflow the
    least-recently-used entry is evicted. `get_or_compute` is the primary
    entry point: it returns the cached value on a hit (refreshing its
    recency) or computes, stores, and returns it on a miss.
    """

    def __init__(self, maxsize: int = 64) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._store: OrderedDict[Hashable, object] = OrderedDict()

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        if key in self._store:
            self._store.move_to_end(key)
            return self._store[key]  # type: ignore[return-value]
        value = compute()
        self._store[key] = value
        if len(self._store) > self._maxsize:
            self._store.popitem(last=False)
        return value

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: Hashable) -> bool:
        return key in self._store
