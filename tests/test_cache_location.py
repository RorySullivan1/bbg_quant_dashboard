"""Regenerable files stay out of the project folder (v0.9.41).

On a BQuant terminal the project has a size limit, and the app was writing
two kinds of throwaway file into it: the parquet price cache (~1.4 MB for the
shipped catalog at the 15-year fetch) and `src` bytecode (~0.9 MB). Together
they put the project over. These pin where the cache goes now and that the
notebook stops bytecode being written.

Nothing clears what older versions wrote, and nothing needs to: a terminal
resets the project folder on every reload.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.config import CACHE_DIR, REPO_ROOT, RUNTIME_DIR


def test_the_price_cache_lives_outside_the_project():
    """The whole point: nothing the app regenerates may count against the
    project's size limit."""
    assert not CACHE_DIR.resolve().is_relative_to(REPO_ROOT.resolve())
    assert CACHE_DIR.parent == RUNTIME_DIR


def test_the_cache_root_can_be_overridden(monkeypatch):
    """For a terminal where the temp folder is unsuitable."""
    import src.config as cfg

    monkeypatch.setenv("BBG_DASHBOARD_CACHE_DIR", "/somewhere/else")
    try:
        importlib.reload(cfg)
        assert Path("/somewhere/else") == cfg.RUNTIME_DIR
        assert Path("/somewhere/else/prices") == cfg.CACHE_DIR
    finally:
        monkeypatch.delenv("BBG_DASHBOARD_CACHE_DIR")
        importlib.reload(cfg)


def test_the_default_price_cache_writes_outside_the_project():
    """The constant is only half of it: the cache the app actually uses must
    be the one pointed there."""
    from src import bql_client as bc

    assert bc._DEFAULT_CACHE.cache_dir == CACHE_DIR


def test_user_benchmarks_stay_in_the_project():
    """Moving the cache out must not take user configuration with it: the
    cache is deletable at any time, a user's added benchmarks are not."""
    from src.config import USER_BENCHMARKS_PATH

    assert USER_BENCHMARKS_PATH.resolve().is_relative_to(REPO_ROOT.resolve())


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
