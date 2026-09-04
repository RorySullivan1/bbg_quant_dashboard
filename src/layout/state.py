"""Explicit session state for the dashboard.

``DashboardState`` holds the mutable session data and the key widget handles
that ``build_app``'s orchestration closures read and write. Because the
closures mutate attributes rather than rebinding names, they stay nested in
``build_app`` without ``nonlocal`` declarations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ipywidgets as W
import pandas as pd

from ..cache import LRUCache
from .benchmarks import BenchmarkRegistry


@dataclass
class DashboardState:
    """Session state shared by ``build_app``'s orchestration closures.

    Construction takes the key widget handles (created once in ``build_app``);
    the remaining fields carry the mutable session data and default to empty so
    the object is valid before the initial price fetch populates it.

    The cached frames are a deliberate hierarchy, each derived from the one
    above it and stored so the live controls can re-render without refetching:
    ``universe_prices`` is the single startup fetch, ``arp_universe_prices``
    drops the benchmark/factor/regime columns, ``universe_rets`` is its daily
    returns, and ``universe_up`` its whole-catalog perf table. Together they let
    the Platform grid's Metric/Window/Lookback dropdowns re-rank by recomputing
    only the z-score column — no perf rerun, no BQL call.

    ``cur_prep`` and its window bounds play the same role one level down, for
    the selected set: they persist the last recompute's slice so a benchmark or
    regime change re-renders a single chart directly. ``memo`` caches those
    per-benchmark chart results and is cleared whenever ``cur_prep`` is rebuilt,
    so it only ever holds results for the current slice.
    """

    # --- widget handles (set once at construction in build_app) ---
    ticker_w: W.SelectMultiple
    status_w: W.HTML  # post-load summary toast
    overlay_w: W.HTML  # dimmed loading overlay + staged progress
    universe_grid: object  # ipydatagrid.DataGrid
    selected_perf_grid: object  # ipydatagrid.DataGrid
    pane_left: object  # SimpleNamespace analysis pane
    pane_right: object  # SimpleNamespace analysis pane
    highlights_w: W.HTML  # the two-section Key Highlights panel (toggle-driven)
    #: Init/pane-error boxes. Kept out of ``highlights_w`` so the live
    #: superlatives-window toggle never wipes them.
    errors_w: W.HTML

    # --- mutable session state ---
    #: Single Strategy tab namespace (picker + profile/chart/grid handles), set
    #: once in build_app; its observers re-render Section 1.
    single_strategy: object | None = None
    universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    arp_universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    universe_rets: pd.DataFrame = field(default_factory=pd.DataFrame)
    universe_up: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: Tracebacks from the initial fetch / perf compute, surfaced in commentary.
    init_errors: list[str] = field(default_factory=list)
    #: Currently visible filter dimension — drives "Clear section".
    active_filter: str = "Asset Class"
    #: The ticker set rendered on the last recompute; when it changes the
    #: analysis date-range boxes reset to the new overlap window.
    last_sel_key: tuple | None = None
    #: Suppresses the bidirectional date-range observers during programmatic
    #: box updates.
    sync_guard: bool = False
    #: The selection's current overlap-window bounds (datetime.date), set when
    #: the date boxes are re-bounded on Refresh; `Clear all` snaps the boxes
    #: back to this full span.
    cur_bound_start: object | None = None
    cur_bound_end: object | None = None
    #: ``None`` means there is no valid selection, so the live observers no-op.
    cur_prep: object | None = None  # SimpleNamespace built in _recompute
    cur_win_start: pd.Timestamp | None = None
    cur_win_end: pd.Timestamp | None = None
    #: Keyed by (chart_kind, benchmark[, direction, pct]) and shared by both
    #: panes, since the result depends on `cur_prep` and the benchmark only.
    memo: LRUCache = field(default_factory=LRUCache)
    #: The live benchmark set and the selectors bound to it. ``build_app``
    #: creates it before the widgets (they register on construction) and hands
    #: it here; the default is the curated list.
    benchmarks: BenchmarkRegistry = field(default_factory=BenchmarkRegistry)
