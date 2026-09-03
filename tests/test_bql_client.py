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

import os
import time
from datetime import date, timedelta

import pandas as pd
import pytest
import src.bql_client as bc
from src.config import RATE_LEVEL_TICKERS, VIX_TICKER


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch):
    """Neutralize the retry backoff so the failure-path tests stay fast.

    ``_fetch_batch_with_retry`` sleeps ``BACKOFF * 2**n`` between attempts, so
    every test that exercises a failing batch would otherwise pay ~3s of real
    wall clock. The retry ladder itself still runs — only the waiting is
    removed, so attempt counts remain exactly as they are in production.
    """
    monkeypatch.setattr(bc.time, "sleep", lambda _seconds: None)


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


# --- v0.9.13: incremental / containment cache (#165) -------------------------


def _spy_live(monkeypatch) -> list[tuple[list[str], date, date]]:
    """Record every live fetch's (tickers, start, end); still run the real mock."""
    calls: list[tuple[list[str], date, date]] = []
    real = bc._live_fetch

    def spy(tickers, start, end):
        calls.append((list(tickers), start, end))
        return real(tickers, start, end)

    monkeypatch.setattr(bc, "_live_fetch", spy)
    return calls


def test_ticker_subset_is_served_without_refetch(monkeypatch):
    calls = _spy_live(monkeypatch)
    bc.fetch_prices(["A Index", "B Index", "C Index"], _START, _END)
    df, src = bc.fetch_prices(["A Index", "C Index"], _START, _END)
    assert src == "cache"  # subset of a cached superset → sliced, no fetch
    assert len(calls) == 1  # only the first (full) fetch hit the wire
    assert list(df.columns) == ["A Index", "C Index"]


def test_narrower_date_range_is_served_without_refetch(monkeypatch):
    calls = _spy_live(monkeypatch)
    bc.fetch_prices(_TICKERS, _START, _END)
    mid = date(2020, 2, 1)
    df, src = bc.fetch_prices(_TICKERS, _START, mid)  # sub-range of the cover
    assert src == "cache"
    assert len(calls) == 1
    assert df.index.max() <= pd.Timestamp(mid)


def test_added_ticker_fetches_only_the_new_ticker(monkeypatch):
    calls = _spy_live(monkeypatch)
    df1, _ = bc.fetch_prices(["A Index", "B Index"], _START, _END)
    df2, src2 = bc.fetch_prices(["A Index", "B Index", "C Index"], _START, _END)
    assert src2 == "mock"  # a delta was fetched
    assert calls[0][0] == ["A Index", "B Index"]  # first call: the two originals
    assert calls[1][0] == ["C Index"]  # second call: only the added ticker
    assert list(df2.columns) == ["A Index", "B Index", "C Index"]
    # The originals are served unchanged from the superset.
    pd.testing.assert_frame_equal(df2[["A Index", "B Index"]], df1)


def test_extended_lookback_fetches_only_the_new_range(monkeypatch):
    calls = _spy_live(monkeypatch)
    mid = date(2020, 2, 1)
    bc.fetch_prices(_TICKERS, mid, _END)  # cover [mid, END]
    _, src2 = bc.fetch_prices(_TICKERS, _START, _END)  # extend back to START
    assert src2 == "mock"
    # The delta is the existing tickers over just the uncovered older range,
    # ending the day before the previous cover start (no overlap with cache).
    assert calls[1][0] == _TICKERS
    assert calls[1][1] == _START
    assert calls[1][2] == mid - timedelta(days=1)
    assert bc._covers(_TICKERS, _START, _END)  # now fully covered in memory


def test_disk_superset_serves_a_ticker_subset(monkeypatch):
    calls = _spy_live(monkeypatch)
    full, _ = bc.fetch_prices(["A Index", "B Index", "C Index"], _START, _END)
    assert (bc.CACHE_DIR / f"prices_{_END.isoformat()}.parquet").exists()

    # New session (in-memory dropped) but the disk parquet is warm.
    bc._MEM_SUPERSET = None
    bc._MEM_COVER = None
    calls.clear()

    sub, src = bc.fetch_prices(["A Index", "C Index"], _START, _END)
    assert src == "cache"  # served from the disk superset
    assert calls == []  # no live fetch
    assert list(sub.columns) == ["A Index", "C Index"]
    # Values identical; the parquet round-trip drops the index's BusinessDay freq.
    pd.testing.assert_frame_equal(sub, full[["A Index", "C Index"]], check_freq=False)


def test_prune_removes_stale_cache_files():
    bc.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stale = bc.CACHE_DIR / "prices_2000-01-01.parquet"
    stale.write_bytes(b"stale")  # prune only inspects mtime, not contents
    old = time.time() - (bc.CACHE_TTL_HOURS + 1) * 3600
    os.utime(stale, (old, old))

    df = pd.DataFrame({"A Index": [1.0, 2.0], "B Index": [3.0, 4.0]})
    bc._cache_write(_END, df)  # writes today's file and prunes stale ones

    assert not stale.exists()  # older-than-TTL file pruned
    assert (bc.CACHE_DIR / f"prices_{_END.isoformat()}.parquet").exists()  # fresh kept


def test_mock_vix_is_a_bounded_level_spanning_buckets():
    # The VIX regime indicator mocks as a bounded mean-reverting *level* (not a
    # compounding price), so the absolute VIX buckets partition it.
    df = bc._mock_prices([VIX_TICKER, "AAA Index"], date(2020, 1, 1), date(2024, 1, 1))
    vix = df[VIX_TICKER]
    assert vix.min() >= 9.0 and vix.max() <= 60.0
    assert vix.mean() < 40.0  # hovers low, unlike the ~100+ GBM strategies
    # Crosses the lower regime buckets so they actually partition the mock.
    assert (vix < 15).any()
    assert ((vix >= 15) & (vix < 25)).any()
    # A normal strategy still compounds around 100 (the level branch is scoped).
    assert df["AAA Index"].iloc[0] > 50


# --- v0.9.13: batched / fault-isolated BQL fetch (#164) ----------------------


_DATES = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])


def _wide(tickers: list[str]) -> pd.DataFrame:
    """A stand-in for one batch's reshaped wide frame."""
    return pd.DataFrame({t: [100.0, 101.0, 102.0] for t in tickers}, index=_DATES)


def _fake_raw(tickers: list[str]) -> pd.DataFrame:
    """A long-form BQL-style response: ID index + DATE / px_last columns."""
    rows = [
        {"DATE": d, "px_last": 100.0 + i} for t in tickers for i, d in enumerate(_DATES)
    ]
    idx = pd.Index([t for t in tickers for _ in _DATES], name="ID")
    return pd.DataFrame(rows, index=idx)


def test_chunked_splits_evenly_and_remainder():
    assert bc._chunked(["a", "b", "c", "d", "e"], 2) == [["a", "b"], ["c", "d"], ["e"]]
    assert bc._chunked(["a"], 100) == [["a"]]
    assert bc._chunked([], 100) == []


def test_reshape_bql_response_pivots_long_to_wide():
    tickers = ["A Index", "B Index"]
    wide = bc._reshape_bql_response(_fake_raw(tickers), tickers, _START, _END)
    assert list(wide.columns) == tickers
    assert isinstance(wide.index, pd.DatetimeIndex)
    assert wide.index.is_monotonic_increasing
    assert wide["A Index"].tolist() == [100.0, 101.0, 102.0]


def test_reshape_bql_response_empty_raises():
    with pytest.raises(RuntimeError, match="no rows"):
        bc._reshape_bql_response(pd.DataFrame(), ["A Index"], _START, _END)
    with pytest.raises(RuntimeError, match="no rows"):
        bc._reshape_bql_response(None, ["A Index"], _START, _END)


def test_assemble_batches_concatenates_and_orders_to_request():
    tickers = ["A Index", "B Index", "C Index", "D Index", "E Index"]
    calls: list[list[str]] = []

    def fetch_batch(batch, s, e):
        calls.append(batch)
        return _wide(batch)

    out = bc._assemble_batches(tickers, _START, _END, fetch_batch, batch_size=2)
    # 5 tickers → batches of 2/2/1.
    assert [len(b) for b in calls] == [2, 2, 1]
    # Result carries every ticker, in the requested order.
    assert list(out.columns) == tickers
    assert not out.isna().any().any()


def test_assemble_batches_isolates_a_failing_batch_to_the_bad_ticker():
    # C is unresolvable and drags its whole batch (C, D) down. The per-ticker
    # re-fetch must narrow that to C alone — D is innocent and must survive.
    tickers = ["A Index", "B Index", "C Index", "D Index"]

    def fetch_batch(batch, s, e):
        if "C Index" in batch:
            raise RuntimeError("BQL limit hit")
        return _wide(batch)

    with pytest.warns(UserWarning, match="re-fetching its tickers individually"):
        out = bc._assemble_batches(tickers, _START, _END, fetch_batch, batch_size=2)

    assert list(out.columns) == tickers
    assert not out["A Index"].isna().any()  # good batch survives
    assert out["C Index"].isna().all()  # only the bad ticker degrades
    assert not out["D Index"].isna().any()  # salvaged from the failed batch


def test_assemble_batches_single_bad_ticker_does_not_blank_a_one_batch_universe():
    # The regression this guards: with the real BQL_BATCH_SIZE (100) and a ~22
    # ticker universe, everything is ONE batch — so batch-level isolation used
    # to mean no isolation, and one bad ticker raised for the entire load.
    tickers = [f"T{i} Index" for i in range(22)]
    bad = "T7 Index"

    def fetch_batch(batch, s, e):
        if bad in batch:
            raise RuntimeError("unresolvable ticker")
        return _wide(batch)

    with pytest.warns(UserWarning):
        out = bc._assemble_batches(tickers, _START, _END, fetch_batch, batch_size=100)

    assert list(out.columns) == tickers
    assert out[bad].isna().all()
    survivors = [t for t in tickers if t != bad]
    assert not out[survivors].isna().any().any()


def test_assemble_batches_salvage_pass_costs_one_request_per_ticker():
    # The failed batch already burned its retry ladder, so the per-ticker sweep
    # must not repeat it: one attempt per ticker, not one ladder per ticker.
    tickers = ["A Index", "B Index", "C Index"]
    calls: list[list[str]] = []

    def fetch_batch(batch, s, e):
        calls.append(list(batch))
        if "C Index" in batch:
            raise RuntimeError("bad ticker")
        return _wide(batch)

    with pytest.warns(UserWarning):
        bc._assemble_batches(tickers, _START, _END, fetch_batch, batch_size=3)

    # 1 batch attempt + BQL_MAX_RETRIES retries, then exactly one try per ticker.
    batch_attempts = [c for c in calls if len(c) == 3]
    per_ticker = [c for c in calls if len(c) == 1]
    assert len(batch_attempts) == bc.BQL_MAX_RETRIES + 1
    assert per_ticker == [["A Index"], ["B Index"], ["C Index"]]


def test_assemble_batches_healthy_path_issues_no_per_ticker_requests():
    tickers = ["A Index", "B Index", "C Index", "D Index"]
    calls: list[list[str]] = []

    def fetch_batch(batch, s, e):
        calls.append(list(batch))
        return _wide(batch)

    out = bc._assemble_batches(tickers, _START, _END, fetch_batch, batch_size=2)

    assert [len(c) for c in calls] == [2, 2]  # no single-ticker salvage requests
    assert not out.isna().any().any()


def test_assemble_batches_all_failing_raises():
    def fetch_batch(batch, s, e):
        raise RuntimeError("session dead")

    # A dead session must stay loud rather than degrade to an all-NaN dashboard.
    with pytest.raises(RuntimeError, match="Every BQL request failed"):
        bc._assemble_batches(
            ["A Index", "B Index"], _START, _END, fetch_batch, batch_size=1
        )


def test_assemble_batches_all_failing_raises_after_per_ticker_retry():
    def fetch_batch(batch, s, e):
        raise RuntimeError("session dead")

    with (
        pytest.warns(UserWarning),
        pytest.raises(RuntimeError, match="Every BQL request failed"),
    ):
        bc._assemble_batches(
            ["A Index", "B Index"], _START, _END, fetch_batch, batch_size=2
        )


def test_fetch_batch_with_retry_recovers_then_succeeds():
    attempts = {"n": 0}

    def flaky(batch, s, e):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return _wide(batch)

    out = bc._fetch_batch_with_retry(
        ["A Index"], _START, _END, flaky, retries=2, backoff=0
    )
    assert attempts["n"] == 3  # failed twice, third try succeeded
    assert list(out.columns) == ["A Index"]


def test_fetch_batch_with_retry_exhausts_and_reraises():
    attempts = {"n": 0}

    def always_fail(batch, s, e):
        attempts["n"] += 1
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        bc._fetch_batch_with_retry(
            ["A Index"], _START, _END, always_fail, retries=2, backoff=0
        )
    assert attempts["n"] == 3  # first try + 2 retries


def test_mock_rate_indicators_are_levels():
    # Regional rates mock as positive mean-reverting levels (terciles of level →
    # Rate-level regime), unlike the ~100+ GBM strategies.
    rate_ticker = RATE_LEVEL_TICKERS[0][1]
    df = bc._mock_prices([rate_ticker, "AAA Index"], date(2018, 1, 1), date(2024, 1, 1))
    rate = df[rate_ticker]
    assert (rate >= 0.0).all() and rate.max() <= 8.0
    assert rate.std() > 0  # actually moves, so its terciles partition the mock
    assert df["AAA Index"].iloc[0] > 50  # a normal strategy still compounds ~100
