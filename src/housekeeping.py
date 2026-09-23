"""Clear the regenerable files older versions left inside the project (v0.9.41).

Until v0.9.40 the app wrote two kinds of throwaway file **into the project
folder**: the parquet price cache under `data/.cache/` and compiled bytecode
under `src/**/__pycache__`. On a BQuant terminal both count against the
project's size limit, and together they were what put it over. v0.9.41 sends
both to `config.RUNTIME_DIR` instead — but moving where new files go does not
remove the old ones, and nothing else ever would: the cache's own `prune`
only looks at the directory it writes to now, and Python never deletes a
`__pycache__` it has stopped using.

This removes them once. Every step is best-effort and silent: a file that
cannot be deleted is left for the next launch, and nothing here may stop the
dashboard from starting.
"""

from __future__ import annotations

import shutil
import sys
from contextlib import suppress
from pathlib import Path

from .config import LEGACY_CACHE_DIR, REPO_ROOT


def clear_legacy_artifacts(
    *,
    legacy_cache_dir: Path = LEGACY_CACHE_DIR,
    source_root: Path = REPO_ROOT / "src",
) -> None:
    """Delete the in-project price cache and, when bytecode is no longer being
    written, the in-project `__pycache__` directories.

    **The bytecode step is conditional on `sys.dont_write_bytecode`.** Without
    it, Python writes `__pycache__` beside the source on the next import, so
    deleting them would only churn — rebuilt on every launch. The notebook sets
    the flag; a test run or a bare `python -c` does not, and must not have its
    caches removed from under it.

    Why the flag and not `sys.pycache_prefix`, which keeps a cache in temp: a
    prefix redirects **reads** as well as writes, so every library imported
    after it — pandas, plotly — recompiled into temp. That measured 2.3 s and
    ~19 MB on a cold start, where the flag stops only writes: libraries still
    read their own bytecode and just `src` recompiles, ~0.7 s on every launch.
    On a terminal whose temp folder may not survive a session, the prefix
    would be cold as often as not.

    Only `prices_*.parquet` is removed from the old cache directory, and the
    directory itself only once it is empty — anything else found there was not
    put there by this app.
    """
    with suppress(OSError):
        for path in legacy_cache_dir.glob("prices_*.parquet"):
            with suppress(OSError):
                path.unlink()
        with suppress(OSError):
            legacy_cache_dir.rmdir()  # only succeeds if now empty

    if not sys.dont_write_bytecode:
        return
    with suppress(OSError):
        for cache in source_root.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
