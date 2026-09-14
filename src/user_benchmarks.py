"""Persistence for benchmarks the user added at runtime (#194).

Without this, every added benchmark dies with the session and the user re-types
the same ticker every morning — which makes the feature feel like a toy rather
than configuration.

**Only the user's additions are stored.** The curated `BENCHMARK_TICKERS` list
ships with the app and stays in `config.py`; mixing shipped defaults with user
state in one file makes both harder to reason about, and would mean a user's
sidecar could silently override a curated benchmark.

**Every operation is best-effort.** `PriceCache` already carries a tri-state
writability probe because locked-down BQuant environments frequently expose a
read-only filesystem, and this reuses that contract exactly: probe once, warn
once, then fall back to session-only. Two rules follow, and they are the whole
reason this module is defensive rather than terse:

- A **read** happens during `build_app`, before anything is on screen. Anything
  that raises here takes the entire dashboard down — the precise failure this
  epic exists to avoid. So a missing, empty, malformed, or unreadable file all
  load as "no additions".
- A **write** must never block an add. On a read-only filesystem the user still
  gets their benchmark for the session; they are told it will not persist, and
  nothing raises.

The store is an object (#221) rather than module state, so a test points one at
a temp path instead of monkeypatching a module constant and resetting a global.
`load_user_benchmarks` / `save_user_benchmarks` stay as wrappers over the
session's default store, which is what the app calls.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from .config import USER_BENCHMARKS_PATH


class UserBenchmarkStore:
    """The gitignored JSON sidecar holding benchmarks the user added."""

    def __init__(self, path: Path | str = USER_BENCHMARKS_PATH) -> None:
        self.path = Path(path)
        #: Tri-state writability, mirroring `PriceCache.disk_writable`: ``None``
        #: until probed, then True/False. Once False we stop attempting writes
        #: and stop re-warning for the rest of the session.
        self.writable: bool | None = None

    def load(self) -> list[str]:
        """The persisted user-added tickers, or ``[]`` if there are none to load.

        Runs during `build_app`, so it must not raise for *any* reason: a
        missing file (the normal first-run case), an empty one, malformed JSON,
        the wrong shape, or an unreadable path all mean "no additions". Deduped
        and order-preserving, matching how the registry holds them.
        """
        try:
            raw = self.path.read_text()
        except FileNotFoundError:
            return []  # the normal first-run case, not a problem
        except Exception as exc:  # noqa: BLE001 — a bad read must not block startup
            warnings.warn(
                f"Could not read {self.path} ({exc}); "
                "starting with no user benchmarks.",
                stacklevel=2,
            )
            return []

        try:
            parsed = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 — malformed JSON is not fatal
            warnings.warn(
                f"{self.path} is not valid JSON ({exc}); "
                "starting with no user benchmarks.",
                stacklevel=2,
            )
            return []

        tickers = parsed.get("benchmarks") if isinstance(parsed, dict) else parsed
        if not isinstance(tickers, list):
            warnings.warn(
                f"{self.path} does not hold a list of tickers; "
                "starting with no user benchmarks.",
                stacklevel=2,
            )
            return []

        return list(
            dict.fromkeys(t for t in tickers if isinstance(t, str) and t.strip())
        )

    def save(self, tickers: list[str]) -> bool:
        """Persist ``tickers``, returning whether it actually reached disk.

        Best-effort by contract: a read-only filesystem warns once and returns
        ``False`` so the caller can tell the user their additions are
        session-only. It never raises — failing to save must not fail the add.
        """
        if self.writable is False:
            return False  # already known unwritable; don't retry or re-warn

        payload = {"benchmarks": list(dict.fromkeys(tickers))}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2) + "\n")
        except Exception as exc:  # noqa: BLE001 — a failed save must not fail the add
            self.writable = False
            warnings.warn(
                f"Could not save user benchmarks to {self.path} ({exc}). "
                "They will work for this session only.",
                stacklevel=2,
            )
            return False

        self.writable = True
        return True


#: The store the app uses. Tests replace this with one pointed at a temp path.
_DEFAULT_STORE = UserBenchmarkStore()


def is_writable() -> bool | None:
    """``True``/``False`` once probed, ``None`` before the first write."""
    return _DEFAULT_STORE.writable


def load_user_benchmarks() -> list[str]:
    """The default store's persisted tickers. See `UserBenchmarkStore.load`."""
    return _DEFAULT_STORE.load()


def save_user_benchmarks(tickers: list[str]) -> bool:
    """Persist to the default store. See `UserBenchmarkStore.save`."""
    return _DEFAULT_STORE.save(tickers)
