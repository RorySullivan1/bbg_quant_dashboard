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

from ..cache import LRUCache


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
    highlights_w: W.HTML  # the two-section Key Highlights panel (toggle-driven)
    errors_w: W.HTML  # init/pane-error boxes, kept out of highlights_w so the
    # live superlatives-window toggle never wipes them (v0.8.x)

    # --- mutable session state ---
    # The single startup BQL/mock fetch (benchmarks included) and its
    # ARP-only view (benchmark columns reindexed out).
    universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    arp_universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    # The all-catalog perf table (universe_perf of arp_universe_prices), cached
    # at load/refresh so the Platform grid's Metric/Window/Lookback dropdowns
    # re-rank by recomputing only the z-score column — no universe_perf rerun,
    # no BQL (v0.7.0 Workstream A).
    universe_up: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Tracebacks from the initial fetch / perf compute, surfaced in commentary.
    init_errors: list[str] = field(default_factory=list)
    # Currently visible filter dimension — drives "Clear section".
    active_filter: str = "Asset Class"
    # The ticker set rendered on the last recompute; when it changes the
    # analysis date-range boxes reset to the new overlap window.
    last_sel_key: tuple | None = None
    # Suppresses the bidirectional date-range observers during programmatic
    # box updates.
    sync_guard: bool = False
    # The selection's current overlap-window bounds (datetime.date), set when
    # the date boxes are re-bounded on Refresh; `Clear all` snaps the boxes back
    # to this full span (v0.7.5: the SelectionRangeSlider's option list used to
    # carry this).
    cur_bound_start: object | None = None
    cur_bound_end: object | None = None
    # The selected-set data slice from the last recompute, plus its window
    # bounds, persisted so the live benchmark/regime chart observers can
    # re-render a single chart without a refetch or full recompute. ``None``
    # means there is no valid selection, so the live observers no-op.
    cur_prep: object | None = None  # SimpleNamespace built in _recompute
    cur_win_start: pd.Timestamp | None = None
    cur_win_end: pd.Timestamp | None = None
    # Bounded memo for benchmark-dependent chart results, keyed by
    # (chart_kind, benchmark[, direction, pct]). Shared by both panes (the
    # result depends only on `cur_prep` + benchmark, not the pane); cleared
    # whenever _recompute rebuilds `cur_prep`, so it only ever holds
    # current-slice results. Makes flipping back to a previously-viewed
    # benchmark an instant cache hit (v0.6.9 Workstream B).
    memo: LRUCache = field(default_factory=LRUCache)
