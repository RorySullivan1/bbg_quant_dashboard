"""Explicit session state for the dashboard.

Before v0.6.0 #6, ``build_app`` threaded its mutable session state through a
``nonlocal`` declaration (``universe_prices`` / ``arp_universe_prices``) plus
three list-as-mutable-cell hacks (``active_filter``, ``last_sel_key``,
``_sync_guard``). ``DashboardState`` centralizes that — together with the key
widget handles the orchestration closures read and write — into one explicit,
documented object. Mutating an attribute (``state.universe_prices = ...``)
needs no ``nonlocal``, so the closures stay nested in ``build_app`` while the
data flow becomes legible. Behavior is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ipywidgets as W
import pandas as pd


@dataclass
class DashboardState:
    """Session state shared by ``build_app``'s orchestration closures.

    Construction takes the key widget handles (created once in ``build_app``);
    the remaining fields carry the mutable session data and default to empty so
    the object is valid before the initial price fetch populates it.
    """

    # --- widget handles (set once at construction in build_app) ---
    ticker_w: W.SelectMultiple
    status_w: W.HTML  # post-load summary toast (v0.6.5: was the status banner)
    overlay_w: W.HTML  # dimmed loading overlay + staged progress (v0.6.5)
    universe_grid: object  # ipydatagrid.DataGrid
    selected_perf_grid: object  # ipydatagrid.DataGrid
    pane_left: object  # SimpleNamespace analysis pane
    pane_right: object  # SimpleNamespace analysis pane
    highlights_w: W.HTML

    # --- mutable session state ---
    # The single startup BQL/mock fetch (benchmarks included) and its
    # ARP-only view (benchmark columns reindexed out).
    universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    arp_universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Tracebacks from the initial fetch / perf compute, surfaced in commentary.
    init_errors: list[str] = field(default_factory=list)
    # Currently visible filter dimension — drives "Clear section".
    active_filter: str = "Asset Class"
    # The ticker set rendered on the last recompute; when it changes the
    # analysis date-range slider resets to the new overlap window.
    last_sel_key: tuple | None = None
    # Suppresses the bidirectional date-range observers during programmatic
    # slider/box updates.
    sync_guard: bool = False
