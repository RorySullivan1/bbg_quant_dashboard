"""Regenerable files stay out of the project folder (v0.9.41).

On a BQuant terminal the project has a size limit, and the app was writing
two kinds of throwaway file into it: the parquet price cache (~1.4 MB for the
shipped catalog at the 15-year fetch) and `src` bytecode (~0.9 MB). Together
they put the project over. These pin where the cache goes now, that the
notebook stops bytecode being written, and that what older versions left
behind is cleared once — without touching anything the app did not put there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from src.config import CACHE_DIR, LEGACY_CACHE_DIR, REPO_ROOT, RUNTIME_DIR
from src.housekeeping import clear_legacy_artifacts

# --- where the cache lives ----------------------------------------------------


def test_the_price_cache_lives_outside_the_project():
    """The whole point: nothing the app regenerates may count against the
    project's size limit."""
    assert not CACHE_DIR.resolve().is_relative_to(REPO_ROOT.resolve())
    assert CACHE_DIR.parent == RUNTIME_DIR


def test_the_cache_root_can_be_overridden(monkeypatch):
    """For a terminal where the temp folder is unsuitable."""
    import importlib

    import src.config as cfg

    monkeypatch.setenv("BBG_DASHBOARD_CACHE_DIR", "/somewhere/else")
    try:
        importlib.reload(cfg)
        assert Path("/somewhere/else") == cfg.RUNTIME_DIR
        assert Path("/somewhere/else/prices") == cfg.CACHE_DIR
    finally:
        monkeypatch.delenv("BBG_DASHBOARD_CACHE_DIR")
        importlib.reload(cfg)


def test_user_benchmarks_stay_in_the_project():
    """Moving the cache out must not take user configuration with it: the
    cache is deletable at any time, a user's added benchmarks are not."""
    from src.config import USER_BENCHMARKS_PATH

    assert USER_BENCHMARKS_PATH.resolve().is_relative_to(REPO_ROOT.resolve())


# --- the notebook -------------------------------------------------------------


def test_the_notebook_stops_bytecode_before_importing_src():
    """`sys.dont_write_bytecode` must be set before the first `src` import,
    or `src/__pycache__` is written by the very import it was meant to stop.

    The flag rather than `sys.pycache_prefix`: a prefix redirects reads as
    well as writes, so every library imported after it recompiled into temp —
    measured at 2.3 s and ~19 MB cold, where the flag leaves libraries reading
    their own bytecode.
    """
    nb = json.loads((REPO_ROOT / "dashboard.ipynb").read_text())
    source = "".join(nb["cells"][-1]["source"])
    flag = source.index("sys.dont_write_bytecode = True")
    first_src_import = source.index("from src")
    assert flag < first_src_import
    assert "pycache_prefix" not in source


# --- the one-time cleanup -------------------------------------------------------


@pytest.fixture
def legacy(tmp_path):
    cache = tmp_path / "data" / ".cache"
    cache.mkdir(parents=True)
    src = tmp_path / "src"
    (src / "layout" / "__pycache__").mkdir(parents=True)
    (src / "__pycache__").mkdir()
    (src / "layout" / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"x" * 64)
    (src / "__pycache__" / "config.cpython-311.pyc").write_bytes(b"x" * 64)
    (src / "layout" / "app.py").write_text("# source is never touched\n")
    return cache, src


def test_old_price_cache_files_are_removed_and_the_empty_folder_with_them(legacy):
    cache, src = legacy
    (cache / "prices_2026-09-21.parquet").write_bytes(b"p" * 128)
    (cache / "prices_2026-09-22.parquet").write_bytes(b"p" * 128)

    clear_legacy_artifacts(legacy_cache_dir=cache, source_root=src)

    assert not cache.exists(), "emptied, so the folder goes too"


def test_a_file_the_app_did_not_write_is_left_and_so_is_its_folder(legacy):
    """Only `prices_*.parquet` is ours. Anything else in that folder was put
    there by someone else, so it stays — and the folder with it."""
    cache, src = legacy
    (cache / "prices_2026-09-22.parquet").write_bytes(b"p")
    (cache / "notes.txt").write_text("not ours")

    clear_legacy_artifacts(legacy_cache_dir=cache, source_root=src)

    assert (cache / "notes.txt").exists()
    assert not (cache / "prices_2026-09-22.parquet").exists()


def test_bytecode_is_removed_only_while_it_is_not_being_written(legacy, monkeypatch):
    """With the flag clear, Python rewrites `__pycache__` on the next import,
    so deleting it would only churn — and a test run must not have its caches
    pulled from under it."""
    cache, src = legacy

    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    clear_legacy_artifacts(legacy_cache_dir=cache, source_root=src)
    assert (src / "layout" / "__pycache__").exists()

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    clear_legacy_artifacts(legacy_cache_dir=cache, source_root=src)
    assert not list(src.rglob("__pycache__"))
    assert (src / "layout" / "app.py").exists(), "source is never touched"


def test_nothing_to_clear_is_not_an_error(tmp_path, monkeypatch):
    """A fresh checkout has neither folder. Nothing here may stop the
    dashboard from starting."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    clear_legacy_artifacts(
        legacy_cache_dir=tmp_path / "absent", source_root=tmp_path / "also-absent"
    )


def test_the_legacy_location_is_the_one_v0_9_40_wrote_to():
    assert REPO_ROOT / "data" / ".cache" == LEGACY_CACHE_DIR


def test_build_app_clears_them_and_the_app_class_does_not(monkeypatch):
    """The cleanup runs from the notebook's entry point only. `DashboardApp` is
    also constructed by tests, and a test run has no business deleting files
    from the checkout."""
    import src.layout.builder as builder

    calls = []
    monkeypatch.setattr(builder, "clear_legacy_artifacts", lambda: calls.append(1))
    monkeypatch.setattr(
        builder, "DashboardApp", lambda **kw: type("A", (), {"root": None})()
    )
    builder.build_app()
    assert calls == [1]

    import inspect

    from src.layout.app import DashboardApp

    assert "clear_legacy_artifacts" not in inspect.getsource(DashboardApp)
