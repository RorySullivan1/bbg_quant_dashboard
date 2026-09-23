"""The dashboard's entry point.

`build_app()` is what the notebook calls and what `src.layout` re-exports; the
controller it returns lives in `app.py` (v0.9.16 #225). Keeping the two apart
means this module stays the one-line answer to "how do I start the dashboard",
while the ~1,300 lines of widget construction and orchestration sit behind a
name that says what they are.
"""

from __future__ import annotations

import ipywidgets as W

from ..housekeeping import clear_legacy_artifacts
from .app import DashboardApp

__all__ = ["DashboardApp", "build_app"]


def build_app(verbose: bool = False) -> W.VBox:
    """Build and return the whole dashboard — the notebook's one-liner.

    Clears what older versions left in the project folder first (v0.9.41).
    Here rather than in `DashboardApp`, because the app is also constructed by
    tests, and a test run has no business deleting files from the checkout.
    """
    clear_legacy_artifacts()
    return DashboardApp(verbose=verbose).root
