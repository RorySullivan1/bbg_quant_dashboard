"""Persisting the benchmarks a user added, and removing them again (#194).

Two contracts carry all the risk here, and neither is about the happy path.

**A read runs during `build_app`, before anything is on screen.** Anything that
raises there takes the whole dashboard down — the precise failure mode this
epic exists to avoid. So a missing, empty, malformed, wrong-shaped or
unreadable file must all load as "no additions".

**A write must never block an add.** `bql_client` already carries a tri-state
writability probe because locked-down BQuant filesystems are frequently
read-only; this reuses that contract. On a read-only filesystem the benchmark
still works for the session and the user is told — nothing raises.

Removal ships alongside because persistence without it means a typo that
happened to resolve is stuck forever. A *curated* benchmark is not the user's
to remove: it is part of the shipped app.

The suite-wide autouse fixture in `conftest.py` redirects the sidecar path, so
no test here (or anywhere) can write the real `data/user_benchmarks.json`.
"""

from __future__ import annotations

import json

import ipywidgets as W
import pytest
import src.layout.builder as builder_mod
import src.user_benchmarks as ub
from src.config import BENCHMARK_TICKERS, DEFAULT_BENCHMARK
from src.layout import build_app
from src.layout.benchmarks import BenchmarkRegistry, BenchmarkSelect

NEW = "NEWBM Index"


def _write(payload) -> None:
    ub.USER_BENCHMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ub.USER_BENCHMARKS_PATH.write_text(
        payload if isinstance(payload, str) else json.dumps(payload)
    )


# --------------------------------------------------------------------------
# Loading: never raises, whatever is on disk
# --------------------------------------------------------------------------


def test_a_missing_file_is_the_normal_first_run():
    assert not ub.USER_BENCHMARKS_PATH.exists()
    assert ub.load_user_benchmarks() == []


def test_a_round_trip_returns_what_was_saved():
    assert ub.save_user_benchmarks(["A Index", "B Index"]) is True
    assert ub.load_user_benchmarks() == ["A Index", "B Index"]


def test_saving_dedupes():
    ub.save_user_benchmarks(["A Index", "A Index", "B Index"])
    assert ub.load_user_benchmarks() == ["A Index", "B Index"]


@pytest.mark.parametrize(
    "payload",
    [
        "",  # empty file
        "   ",  # whitespace
        "{not json",  # malformed
        "null",
        '{"benchmarks": "A Index"}',  # right key, wrong type
        '{"benchmarks": {"a": 1}}',
        '{"nothing": "useful"}',  # missing key
        "42",
    ],
    ids=[
        "empty",
        "whitespace",
        "malformed",
        "null",
        "string-not-list",
        "dict-not-list",
        "missing-key",
        "scalar",
    ],
)
def test_unusable_content_loads_as_no_additions(payload):
    # This read happens before the dashboard is on screen; raising here would
    # take the whole app down over a corrupt sidecar.
    _write(payload)
    with pytest.warns(UserWarning):
        assert ub.load_user_benchmarks() == []


def test_a_bare_list_is_accepted_too():
    # Tolerate the simpler shape rather than discarding a usable file.
    _write(["A Index", "B Index"])
    assert ub.load_user_benchmarks() == ["A Index", "B Index"]


def test_junk_entries_are_dropped_not_fatal():
    _write({"benchmarks": ["A Index", "", "   ", 7, None, "B Index"]})
    assert ub.load_user_benchmarks() == ["A Index", "B Index"]


def test_an_unreadable_file_loads_as_no_additions(monkeypatch):
    _write({"benchmarks": ["A Index"]})

    def boom(*_a, **_k):
        raise OSError("permission denied")

    monkeypatch.setattr(type(ub.USER_BENCHMARKS_PATH), "read_text", boom)
    with pytest.warns(UserWarning, match="Could not read"):
        assert ub.load_user_benchmarks() == []


# --------------------------------------------------------------------------
# Saving: best-effort, never fatal
# --------------------------------------------------------------------------


def test_an_unwritable_filesystem_degrades_to_session_only(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(type(ub.USER_BENCHMARKS_PATH), "write_text", boom)

    with pytest.warns(UserWarning, match="this session only"):
        assert ub.save_user_benchmarks(["A Index"]) is False
    assert ub.is_writable() is False


def test_an_unwritable_filesystem_is_probed_once(monkeypatch):
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise OSError("read-only file system")

    monkeypatch.setattr(type(ub.USER_BENCHMARKS_PATH), "write_text", boom)
    with pytest.warns(UserWarning):
        ub.save_user_benchmarks(["A Index"])

    # Already known unwritable: no retry, and no second warning to spam.
    assert ub.save_user_benchmarks(["B Index"]) is False
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# Registry: what counts as the user's own
# --------------------------------------------------------------------------


def test_only_additions_count_as_the_users_own():
    reg = BenchmarkRegistry(["A Index"])
    reg.add("B Index")

    assert reg.added == ["B Index"]  # the curated one is not persisted
    assert reg.is_user_added("B Index") is True
    assert reg.is_user_added("A Index") is False


def test_a_curated_benchmark_cannot_be_removed():
    # The shipped list is not the user's to edit.
    reg = BenchmarkRegistry(["A Index"])
    assert reg.remove("A Index") is False
    assert reg.tickers == ["A Index"]


def test_removing_an_unknown_ticker_is_a_no_op():
    reg = BenchmarkRegistry(["A Index"])
    assert reg.remove("Z Index") is False


def test_removing_drops_it_from_every_selector():
    reg = BenchmarkRegistry(["A Index"])
    sel = reg.register(BenchmarkSelect(default="A Index"), include_catalog=True)
    reg.add(NEW)

    reg.remove(NEW)

    assert NEW not in reg.tickers
    assert NEW not in [v for _, v in sel.options]


def test_a_selector_showing_the_removed_ticker_falls_back():
    # Otherwise it is left holding a value that is no longer an option, which
    # reads as a broken control.
    reg = BenchmarkRegistry(["A Index"])
    sel = reg.register(BenchmarkSelect(default="A Index"), include_catalog=True)
    reg.set_resolver(lambda _t: True)
    sel._box.value = "newbm"
    assert sel.value == NEW

    reg.remove(NEW)

    assert sel.value == "A Index"


def test_the_persister_sees_only_the_users_own(tmp_path):
    saved: list[list[str]] = []
    reg = BenchmarkRegistry(["A Index"])
    reg.set_persister(saved.append)

    reg.add(NEW)
    reg.remove(NEW)

    assert saved == [[NEW], []]


def test_the_catalog_does_not_trigger_a_save():
    # The catalog is derived from shipped metadata, not user state.
    saved: list[list[str]] = []
    reg = BenchmarkRegistry(["A Index"])
    reg.set_persister(saved.append)

    reg.set_catalog([("X Index — Ex", "X Index")])

    assert saved == []


# --------------------------------------------------------------------------
# The remove button
# --------------------------------------------------------------------------


def test_the_remove_button_is_hidden_for_a_curated_benchmark():
    reg = BenchmarkRegistry(["A Index"])
    sel = reg.register(BenchmarkSelect(default="A Index"), include_catalog=True)
    assert sel._remove_btn.layout.display == "none"


def test_the_remove_button_appears_only_for_an_added_benchmark():
    reg = BenchmarkRegistry(["A Index"])
    reg.set_resolver(lambda _t: True)
    sel = reg.register(BenchmarkSelect(default="A Index"), include_catalog=True)

    sel._box.value = "newbm"
    assert sel._remove_btn.layout.display == ""

    sel.value = "A Index"
    assert sel._remove_btn.layout.display == "none"


def test_clicking_remove_takes_the_benchmark_away():
    reg = BenchmarkRegistry(["A Index"])
    reg.set_resolver(lambda _t: True)
    sel = reg.register(BenchmarkSelect(default="A Index"), include_catalog=True)
    sel._box.value = "newbm"

    sel._remove_btn.click()

    assert NEW not in reg.tickers
    assert sel.value == "A Index"
    assert sel._remove_btn.layout.display == "none"


# --------------------------------------------------------------------------
# App-level
# --------------------------------------------------------------------------


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _click(app, description: str) -> None:
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == description
    ).click()


def _selectors(app) -> list[BenchmarkSelect]:
    return [w for w in _walk(app) if isinstance(w, BenchmarkSelect)]


@pytest.fixture
def captured_registry(monkeypatch):
    created: list[BenchmarkRegistry] = []
    real = builder_mod.BenchmarkRegistry

    def factory(*a, **k):
        created.append(r := real(*a, **k))
        return r

    monkeypatch.setattr(builder_mod, "BenchmarkRegistry", factory)
    return created


@pytest.fixture
def captured_state(monkeypatch):
    created = []
    real = builder_mod.DashboardState

    def factory(*a, **k):
        created.append(st := real(*a, **k))
        return st

    monkeypatch.setattr(builder_mod, "DashboardState", factory)
    return created


def test_an_added_benchmark_is_written_to_disk(captured_registry):
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    _selectors(app)[0]._box.value = "newbm"

    assert ub.load_user_benchmarks() == [NEW]


def test_a_persisted_benchmark_comes_back_on_the_next_build(captured_registry):
    ub.save_user_benchmarks([NEW])

    app = build_app(verbose=False)
    (registry,) = captured_registry
    _click(app, "Multi-Strategy")

    assert NEW in registry.tickers
    assert registry.added == [NEW]  # restored as the user's, so still removable
    assert NEW in [v for _, v in _selectors(app)[0].options]


def test_a_persisted_benchmark_rides_the_startup_fetch(monkeypatch):
    ub.save_user_benchmarks([NEW])
    requested: list[list[str]] = []
    real = builder_mod.fetch_prices

    def spy(tickers, *a, **k):
        requested.append(list(tickers))
        return real(tickers, *a, **k)

    monkeypatch.setattr(builder_mod, "fetch_prices", spy)
    build_app(verbose=False)

    # Restored before the first `_fetch_tickers()`, so it needs no extra call.
    assert NEW in requested[0]
    assert set(BENCHMARK_TICKERS) <= set(requested[0])


def test_loading_persisted_benchmarks_does_not_immediately_resave(monkeypatch):
    ub.save_user_benchmarks([NEW])
    writes = {"n": 0}
    real = builder_mod.save_user_benchmarks

    def counting(tickers):
        writes["n"] += 1
        return real(tickers)

    monkeypatch.setattr(builder_mod, "save_user_benchmarks", counting)
    build_app(verbose=False)

    assert writes["n"] == 0


def test_removing_in_the_app_clears_it_from_disk(captured_registry):
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    sel = _selectors(app)[0]
    sel._box.value = "newbm"
    assert ub.load_user_benchmarks() == [NEW]

    sel._remove_btn.click()

    assert ub.load_user_benchmarks() == []
    assert sel.value == DEFAULT_BENCHMARK


def test_a_corrupt_sidecar_does_not_stop_the_app_loading():
    # The whole point of the defensive read: a bad file is a non-event.
    _write("{ this is not json")

    with pytest.warns(UserWarning):
        app = build_app(verbose=False)

    _click(app, "Multi-Strategy")
    assert _selectors(app)  # the dashboard built normally
    assert all(sel.value == DEFAULT_BENCHMARK for sel in _selectors(app))


def test_a_read_only_filesystem_still_allows_the_add(
    monkeypatch, captured_registry, captured_state
):
    app = build_app(verbose=False)
    (registry,) = captured_registry
    (state,) = captured_state
    _click(app, "Multi-Strategy")

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(type(ub.USER_BENCHMARKS_PATH), "write_text", boom)

    with pytest.warns(UserWarning):
        _selectors(app)[0]._box.value = "newbm"

    # The benchmark works for the session, and the user is told it won't last
    # rather than discovering it at the next restart.
    assert NEW in registry.tickers
    assert "session only" in state.status_w.value
