"""Unit tests for the bounded LRU cache (v0.6.9 Workstream B)."""

from __future__ import annotations

import pytest
from src.cache import LRUCache


def test_miss_computes_once_then_hits():
    cache = LRUCache(maxsize=8)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return "value"

    assert cache.get_or_compute("k", compute) == "value"
    assert cache.get_or_compute("k", compute) == "value"
    assert calls["n"] == 1  # second call was a hit
    assert "k" in cache


def test_lru_eviction_at_capacity():
    cache = LRUCache(maxsize=2)
    cache.get_or_compute("a", lambda: 1)
    cache.get_or_compute("b", lambda: 2)
    # Touch "a" so "b" becomes least-recently-used.
    cache.get_or_compute("a", lambda: 99)
    cache.get_or_compute("c", lambda: 3)  # evicts "b"

    assert "a" in cache
    assert "c" in cache
    assert "b" not in cache
    assert len(cache) == 2

    # "a" survived with its original value (the lambda above was never called).
    assert cache.get_or_compute("a", lambda: -1) == 1


def test_clear_empties_cache():
    cache = LRUCache(maxsize=4)
    cache.get_or_compute("a", lambda: 1)
    cache.get_or_compute("b", lambda: 2)
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0
    assert "a" not in cache


def test_maxsize_must_be_positive():
    with pytest.raises(ValueError):
        LRUCache(maxsize=0)
