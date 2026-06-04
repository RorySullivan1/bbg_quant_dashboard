"""Caching behavior for ``fetch_prices`` (v0.6.9 Workstream A).

The price fetch is fronted by an in-memory session cache and backed by a
best-effort on-disk parquet cache. These tests pin the two guarantees that
matter on a read-only BQuant filesystem: a disk write that fails must never
crash the load (the in-memory cache carries the session), and the caches must
actually spare a refetch — while ``use_cache=False`` (Refresh prices) still
refetches.

Each test clears the module caches and points ``CACHE_DIR`` at a tmp dir so it
never touches the real ``data/.cache``. The unwritable-FS cases raise from a
patched ``Path.mkdir`` rather than ``chmod`` (the suite runs as root, which
bypasses permission bits).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
import src.bql_client as bc


@pytest.fixture(autouse=True)
def _hermetic_cache(monkeypatch, tmp_path):
    """Fresh caches + a throwaway CACHE_DIR for every test."""
    bc._clear_caches()
    monkeypatch.setattr(bc, "CACHE_DIR", tmp_path / "cache")
    yield
    bc._clear_caches()


def _raise_oserror(*_args, **_kwargs):
    raise OSError("read-only file system")


_TICKERS = ["A Index", "B Index"]
_START = date(2020, 1, 1)
_END = date(2020, 3, 1)


def test_cache_write_survives_unwritable_fs(monkeypatch):
    # mkdir raising stands in for a read-only filesystem.
    monkeypatch.setattr(bc.Path, "mkdir", _raise_oserror)
    df = pd.DataFrame({"A Index": [1.0, 2.0], "B Index": [3.0, 4.0]})

    with pytest.warns(UserWarning, match="unwritable"):
        bc._cache_write(_END, df)  # must not raise

    assert bc._disk_cache_writable is False
    # Once known-unwritable we stop probing — a second call is a silent no-op.
    bc._cache_write(_END, df)
    assert bc._disk_cache_writable is False


def test_fetch_prices_degrades_to_inmemory_on_unwritable_fs(monkeypatch):
    monkeypatch.setattr(bc.Path, "mkdir", _raise_oserror)

    with pytest.warns(UserWarning, match="unwritable"):
        df, source = bc.fetch_prices(_TICKERS, _START, _END)
    assert not df.empty
    assert source == "mock"  # bql isn't importable in tests
    # No parquet was written...
    assert not (bc.CACHE_DIR / f"prices_{_END.isoformat()}.parquet").exists()

    # ...but the identical request is served from the in-memory cache.
    df2, source2 = bc.fetch_prices(_TICKERS, _START, _END)
    assert source2 == "cache"
    pd.testing.assert_frame_equal(df2, df)


def test_cache_hit_avoids_refetch(monkeypatch):
    calls = {"n": 0}
    real = bc._mock_prices

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(bc, "_mock_prices", counting)

    df1, src1 = bc.fetch_prices(_TICKERS, _START, _END)
    df2, src2 = bc.fetch_prices(_TICKERS, _START, _END)

    assert calls["n"] == 1  # second call served from cache
    assert src1 == "mock"
    assert src2 == "cache"
    # Column order follows the request even though the key is order-insensitive.
    df3, _ = bc.fetch_prices(list(reversed(_TICKERS)), _START, _END)
    assert list(df3.columns) == list(reversed(_TICKERS))


def test_use_cache_false_refetches(monkeypatch):
    calls = {"n": 0}
    real = bc._mock_prices

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(bc, "_mock_prices", counting)

    bc.fetch_prices(_TICKERS, _START, _END)  # warm the cache
    bc.fetch_prices(_TICKERS, _START, _END, use_cache=False)  # Refresh prices

    assert calls["n"] == 2  # use_cache=False bypasses the cache reads
