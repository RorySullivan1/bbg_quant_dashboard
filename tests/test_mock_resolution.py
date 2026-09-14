"""Making the off-terminal mock able to say "no" (#195).

`_mock_prices` seeds a generator off `hash(ticker)`, so it returned a clean,
plausible series for *any* string. Off-terminal — where the whole test suite
runs and all local development happens — an invalid ticker therefore did not
exist, and no test could be written for one. That blocks every validation
criterion in the user-defined-benchmarks epic (#189), and it is the same shape
of gap that produced #186: behaviour marked untestable in CI that then broke on
the terminal.

Two seams now let a test drive the mock into the live path's two failure modes.
They are genuinely different and must stay distinguishable downstream:

- **unresolvable** — a wrong ticker; nothing comes back, ever.
- **no data in the window** — a real security that launched mid-lookback (or a
  stale one); it resolves, but the early rows are empty.

Reported as one generic error those look identical, and a user reads the second
as a bug. `test_the_two_failure_modes_are_distinguishable` is the one that pins
them apart.

The seams are empty by default, and the first test here guards that: every
ticker the app actually uses resolves over the full window exactly as before.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
import src.bql_client as bc
from src.price_cache import PriceCache
from src.price_source import MockPriceSource, TickersUnresolved, _ticker_seed

_TICKERS = ["A Index", "B Index", "C Index"]
_START = date(2022, 1, 3)
_END = date(2022, 6, 30)


@pytest.fixture(autouse=True)
def _hermetic_cache(monkeypatch, tmp_path):
    """A private `PriceCache` for every test."""
    monkeypatch.setattr(bc, "_DEFAULT_CACHE", PriceCache(tmp_path / "cache"))


@pytest.fixture
def mock_source(monkeypatch) -> MockPriceSource:
    """A `MockPriceSource` installed as the default, for the seams to be set on.

    #222: the seams are this instance's attributes, so there is nothing to
    reset — the next test gets a new source. Tests that don't go through
    `fetch_prices` construct their own inline instead.
    """
    source = MockPriceSource()
    monkeypatch.setattr(bc, "_DEFAULT_SOURCE", source)
    return source


# --------------------------------------------------------------------------
# Default behaviour is untouched
# --------------------------------------------------------------------------


def test_mock_resolves_everything_by_default():
    # The seams are opt-in: with neither set, the mock behaves exactly as it
    # always has, which is what the app and every other test rely on.
    out = MockPriceSource().fetch(_TICKERS, _START, _END)

    assert list(out.columns) == _TICKERS
    assert not out.isna().any().any()
    assert out.index.name == "DATE"
    assert len(out) == len(pd.bdate_range(_START, _END))


def test_mock_is_still_deterministic_per_ticker():
    first = MockPriceSource().fetch(["A Index"], _START, _END)
    second = MockPriceSource().fetch(["A Index"], _START, _END)
    pd.testing.assert_frame_equal(first, second)


def test_mock_series_are_pinned_across_processes():
    # #235: the seed used to be `hash(ticker)`, which Python randomizes per
    # process — so the off-terminal dashboard showed different numbers on every
    # restart and no two renders were comparable. Pinning actual values is the
    # only assertion that catches a regression here: a same-process
    # determinism check passed even while the bug was live.
    assert _ticker_seed("SPX Index") == 435375205
    assert _ticker_seed("VIX Index") == 1101518666

    df = MockPriceSource().fetch(
        ["SPX Index", "VIX Index"], date(2024, 1, 1), date(2024, 3, 1)
    )
    assert len(df) == 45
    assert df["SPX Index"].iloc[0] == pytest.approx(100.571298, abs=1e-6)
    assert df["SPX Index"].iloc[-1] == pytest.approx(110.555940, abs=1e-6)
    # The level-indicator path (mean-reverting, not compounding) is seeded the
    # same way, so pin it too.
    assert df["VIX Index"].iloc[0] == pytest.approx(20.606146, abs=1e-6)
    assert df["VIX Index"].iloc[-1] == pytest.approx(11.653985, abs=1e-6)


def test_the_seed_depends_on_nothing_but_the_ticker():
    # Stable across calls and independent of any process or global state.
    assert _ticker_seed("A Index") == _ticker_seed("A Index")
    assert _ticker_seed("A Index") != _ticker_seed("B Index")
    assert 0 <= _ticker_seed("A Index") < 2**32


# --------------------------------------------------------------------------
# Unresolvable tickers
# --------------------------------------------------------------------------


def test_unresolvable_ticker_degrades_to_a_nan_column():
    source = MockPriceSource(unresolvable={"B Index"})

    with pytest.warns(UserWarning, match="did not resolve"):
        out = source.fetch(_TICKERS, _START, _END)

    # Column order follows the request, so callers can still reindex blindly.
    assert list(out.columns) == _TICKERS
    assert out["B Index"].isna().all()
    assert not out[["A Index", "C Index"]].isna().any().any()


def test_a_request_where_nothing_resolves_raises():
    # Mirrors `_assemble_batches`' terminal raise: a dead request stays loud
    # rather than serving a silently all-NaN dashboard.
    source = MockPriceSource(unresolvable=set(_TICKERS))

    with pytest.raises(RuntimeError, match="resolved none of"):
        source.fetch(_TICKERS, _START, _END)


def test_nothing_resolving_raises_the_typed_error():
    # `TickersUnresolved` separates "your ticker is wrong" from "the session
    # dropped" — the two are indistinguishable in a one-ticker request, which
    # is exactly what adding a benchmark issues (#193).
    source = MockPriceSource(unresolvable={"A Index"})

    with pytest.raises(TickersUnresolved):
        source.fetch(["A Index"], _START, _END)


def test_the_typed_error_is_still_a_runtime_error():
    # Subclassing keeps every existing handler and test working.
    assert issubclass(TickersUnresolved, RuntimeError)


def test_an_empty_request_is_not_a_failure():
    # No tickers is a no-op, not a "nothing resolved" error.
    out = MockPriceSource().fetch([], _START, _END)
    assert out.empty or list(out.columns) == []


# --------------------------------------------------------------------------
# Resolves, but has no data in the window
# --------------------------------------------------------------------------


def test_late_launching_ticker_is_nan_before_its_first_trade():
    launch = date(2022, 4, 1)
    source = MockPriceSource(first_trade={"B Index": launch})

    out = source.fetch(_TICKERS, _START, _END)

    before = out.loc[out.index < pd.Timestamp(launch), "B Index"]
    after = out.loc[out.index >= pd.Timestamp(launch), "B Index"]
    assert before.isna().all()
    assert not after.isna().any()
    assert len(after) > 0  # the window must actually reach past the launch
    # The frame keeps its full index — a short series, not a short frame.
    assert len(out) == len(pd.bdate_range(_START, _END))
    assert not out[["A Index", "C Index"]].isna().any().any()


def test_the_two_failure_modes_are_distinguishable():
    # This is the property #193's error reporting depends on. Told apart, the
    # user gets "that ticker is wrong" vs "that ticker has no history in this
    # window"; conflated, the second reads as a bug.
    source = MockPriceSource(
        unresolvable={"A Index"}, first_trade={"B Index": date(2022, 4, 1)}
    )

    with pytest.warns(UserWarning):
        out = source.fetch(_TICKERS, _START, _END)

    assert out["A Index"].isna().all()  # unresolvable → nothing, ever
    assert out["B Index"].isna().any()  # late launch → gap at the start …
    assert not out["B Index"].isna().all()  # … but real data by the end
    assert out["B Index"].notna().sum() > 0


# --------------------------------------------------------------------------
# Reaching the seams through the public API
# --------------------------------------------------------------------------


def test_fetch_prices_surfaces_an_unresolvable_ticker_as_nan(mock_source):
    # The seam has to be reachable through the caller the app actually uses,
    # not only via the source's own method.
    mock_source.unresolvable.add("C Index")

    with pytest.warns(UserWarning, match="did not resolve"):
        out, source = bc.fetch_prices(_TICKERS, _START, _END)

    assert source == "mock"
    assert out["C Index"].isna().all()
    assert not out["A Index"].isna().any()


def test_fetch_prices_raises_when_nothing_resolves(mock_source):
    mock_source.unresolvable.update(_TICKERS)

    with pytest.raises(RuntimeError, match="resolved none of"):
        bc.fetch_prices(_TICKERS, _START, _END)


def test_downstream_stats_tolerate_an_unresolved_column():
    # A NaN column must be inert for the compute layer, not a source of
    # exceptions — that is what lets an unresolvable ticker fail softly.
    from src.stats import daily_returns

    source = MockPriceSource(unresolvable={"B Index"})
    with pytest.warns(UserWarning):
        out = source.fetch(_TICKERS, _START, _END)

    rets = daily_returns(out)
    assert rets["B Index"].isna().all()
    assert np.isfinite(rets["A Index"].dropna()).all()


# --------------------------------------------------------------------------
# Seam hygiene
# --------------------------------------------------------------------------


def test_seams_are_per_instance_so_they_cannot_leak():
    # #222 replaced the module-level seam sets with instance attributes, so
    # there is no reset to forget: a configured source cannot affect another.
    configured = MockPriceSource(
        unresolvable={"A Index"}, first_trade={"B Index": date(2022, 4, 1)}
    )
    fresh = MockPriceSource()

    assert fresh.unresolvable == set()
    assert fresh.first_trade == {}
    # The fresh source resolves everything, including what the other rejects.
    out = fresh.fetch(_TICKERS, _START, _END)
    assert not out.isna().any().any()
    # ...and mutating one does not reach the other.
    configured.unresolvable.add("C Index")
    assert fresh.unresolvable == set()
