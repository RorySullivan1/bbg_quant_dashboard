"""Runtime bootstrap for packages the BQuant terminal cannot preinstall.

`itables` cannot be added to the environment outside the notebook, so the app
installs it at startup. This lives in `src/` rather than in a notebook cell so
it is version-controlled and testable, and so `dashboard.ipynb` stays thin.

Deliberately importable without `itables` present — it must run *before* any
module that imports it.
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys

#: Packages installed at startup when missing, in pip syntax.
RUNTIME_REQUIREMENTS: tuple[str, ...] = ("itables", "anywidget")


def _missing(names: tuple[str, ...]) -> list[str]:
    return [n for n in names if importlib.util.find_spec(n.split("==")[0]) is None]


def ensure_runtime_packages(
    packages: tuple[str, ...] = RUNTIME_REQUIREMENTS,
) -> tuple[bool, str]:
    """Install any missing `packages`, quietly. Returns (ok, detail).

    Silent by construction: pip runs through `subprocess` with its pipes
    captured, so nothing reaches the notebook's stdout and nothing renders in
    Voila. `IPython.display.clear_output` does **not** work for this — a
    subprocess writes to the real file descriptor, outside IPython's display
    machinery, so its output survives the clear.

    Never raises. A failed install must surface as a visible message in the
    app, not as a traceback in a cell the user cannot see under Voila.
    """
    missing = _missing(packages)
    if not missing:
        return True, "already present"

    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", *missing],
        capture_output=True,  # the whole point: nothing reaches the notebook
        text=True,
    )
    # pip wrote into site-packages after this interpreter cached its listing;
    # without this the fresh package stays invisible to import in this kernel.
    importlib.invalidate_caches()

    still = _missing(packages)
    if still:
        tail = (proc.stderr or proc.stdout or "").strip()[-600:]
        return False, f"failed to install {', '.join(still)}\n{tail}"
    return True, f"installed {', '.join(missing)}"


def startup_failure_banner(detail: str):
    """A widget explaining why startup failed, to render in place of the app.

    `ensure_runtime_packages` never raises, so the caller needs something to
    show. Under Voila an exception in a cell leaves the page blank with the
    reason only in the server log, which is the worst outcome for a user on a
    terminal — hence a visible banner carrying pip's own message.

    Imported lazily so this module stays importable in a bare interpreter.
    """
    import ipywidgets as W

    from .style import Color

    return W.HTML(
        f"<div style='background:{Color.SURFACE.value};"
        f"border:1px solid {Color.BORDER.value};border-left:3px solid #ff5c5c;"
        f"padding:12px 14px;font:13px system-ui;color:{Color.TEXT.value}'>"
        f"<b>Dashboard startup failed</b><br>"
        f"<span style='color:{Color.TEXT_MUTED.value}'>A package the app needs "
        f"could not be installed. The terminal may have no network access to "
        f"PyPI.</span>"
        f"<pre style='white-space:pre-wrap;font:11px ui-monospace,monospace;"
        f"color:{Color.TEXT_MUTED.value};margin:8px 0 0'>{detail}</pre></div>"
    )
