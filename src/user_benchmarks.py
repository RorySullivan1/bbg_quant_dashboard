"""Persistence for benchmarks the user added at runtime.

**Only the user's additions are stored.** The curated `BENCHMARK_TICKERS` list
stays in `config.py`; a sidecar mixing the two could silently override a
curated benchmark.

**Every operation is best-effort**, because locked-down BQuant environments
frequently expose a read-only filesystem. Two rules follow, and they are why
this module is defensive rather than terse:

- A **read** happens during `build_app`, before anything is on screen, so
  anything that raises takes the whole dashboard down. A missing, empty,
  malformed, or unreadable file all load as "no additions".
- A **write** must never block an add. On a read-only filesystem the user still
  gets their benchmark for the session, is told it will not persist, and
  nothing raises.
"""

from __future__ import annotations

import json
import warnings

from .config import USER_BENCHMARKS_PATH

# Tri-state writability, mirroring `bql_client._disk_cache_writable`: ``None``
# until probed, then True/False. Once False we stop attempting writes and stop
# re-warning for the rest of the session.
_writable: bool | None = None


def _reset() -> None:
    """Reset the writability probe (test hook)."""
    global _writable
    _writable = None


def is_writable() -> bool | None:
    """``True``/``False`` once probed, ``None`` before the first write."""
    return _writable


def load_user_benchmarks() -> list[str]:
    """The persisted user-added tickers, or ``[]`` if there are none to load.

    Runs during `build_app`, so it must not raise for *any* reason: a missing
    file (the normal first-run case), an empty one, malformed JSON, the wrong
    shape, or an unreadable path all mean "no additions". Deduped and
    order-preserving, matching how the registry holds them.
    """
    try:
        raw = USER_BENCHMARKS_PATH.read_text()
    except FileNotFoundError:
        return []  # the normal first-run case, not a problem
    except Exception as exc:  # noqa: BLE001 — a bad read must not block startup
        warnings.warn(
            f"Could not read {USER_BENCHMARKS_PATH} ({exc}); "
            "starting with no user benchmarks.",
            stacklevel=2,
        )
        return []

    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — malformed JSON is not fatal
        warnings.warn(
            f"{USER_BENCHMARKS_PATH} is not valid JSON ({exc}); "
            "starting with no user benchmarks.",
            stacklevel=2,
        )
        return []

    tickers = parsed.get("benchmarks") if isinstance(parsed, dict) else parsed
    if not isinstance(tickers, list):
        warnings.warn(
            f"{USER_BENCHMARKS_PATH} does not hold a list of tickers; "
            "starting with no user benchmarks.",
            stacklevel=2,
        )
        return []

    return list(dict.fromkeys(t for t in tickers if isinstance(t, str) and t.strip()))


def save_user_benchmarks(tickers: list[str]) -> bool:
    """Persist ``tickers``, returning whether it actually reached disk.

    Best-effort by contract: a read-only filesystem warns once and returns
    ``False`` so the caller can tell the user their additions are session-only.
    It never raises — failing to save must not fail the add itself.
    """
    global _writable
    if _writable is False:
        return False  # already known unwritable; don't retry or re-warn

    payload = {"benchmarks": list(dict.fromkeys(tickers))}
    try:
        USER_BENCHMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_BENCHMARKS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    except Exception as exc:  # noqa: BLE001 — a failed save must not fail the add
        _writable = False
        warnings.warn(
            f"Could not save user benchmarks to {USER_BENCHMARKS_PATH} ({exc}). "
            "They will work for this session only.",
            stacklevel=2,
        )
        return False

    _writable = True
    return True
