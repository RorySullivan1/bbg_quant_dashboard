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
from ..config import filter_dimensions
from ..stats import BasketWindow
from .basket import Basket
from .benchmarks import BenchmarkRegistry
from .grids import PerfGrid, UniverseGrid
from .panes import AnalysisPane
from .selection import SelectionSlice
from .single_strategy import SingleStrategyPanel


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

    ``cur_prep`` plays the same role one level down, for
    the selected set: they persist the last recompute's slice so a benchmark or
    regime change re-renders a single chart directly. ``memo`` caches those
    per-benchmark chart results and is cleared whenever ``cur_prep`` is rebuilt,
    so it only ever holds results for the current slice.
    """

    # --- widget handles (set once at construction in build_app) ---
    #: The Multi-Strategy selection. An **object, not a widget** (#341 dec. 1):
    #: the picker used to be the store, so the cap lived in three places and a
    #: row position had to survive a table rebuild, which it cannot. The grid,
    #: the cards and the analytics are views of this.
    basket: Basket
    status_w: W.HTML  # post-load summary toast
    overlay_w: W.HTML  # dimmed loading overlay + staged progress
    universe_grid: UniverseGrid
    selected_perf_grid: PerfGrid
    pane_left: AnalysisPane
    pane_right: AnalysisPane
    #: Init/pane-error boxes. A sibling of the commentary block's two panes,
    #: never inside one, so neither the live ranking-window toggle nor a
    #: Commentary/New Launches switch can wipe an error off the screen. (The
    #: v0.9.20 leaderboard and pane are owned by `DashboardApp`, not held here:
    #: nothing outside the controller renders them.)
    errors_w: W.HTML

    # --- mutable session state ---
    #: Single Strategy tab namespace (picker + profile/chart/grid handles), set
    #: once in build_app; its observers re-render Section 1.
    single_strategy: SingleStrategyPanel | None = None
    universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    arp_universe_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    universe_rets: pd.DataFrame = field(default_factory=pd.DataFrame)
    universe_up: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: Tracebacks from the initial fetch / perf compute, surfaced in commentary.
    init_errors: list[str] = field(default_factory=list)
    #: Currently visible filter dimension, as a schema field key — drives
    #: "Clear section". Defaults to whichever dimension the panel opens on.
    active_filter: str = field(default_factory=lambda: filter_dimensions()[0].key)
    #: The window the selected-set analytics last ran over, and the members
    #: that bound each edge. **Derived, never chosen** (#341 dec. 12): the two
    #: date pickers and the `last_sel_key` / `sync_guard` / `cur_bound_*`
    #: machinery that kept them in step are gone, because the overlap is a
    #: fact about the basket and the tab never explained where it came from.
    #: The strip's readout renders this.
    basket_window: BasketWindow = field(
        default_factory=lambda: BasketWindow(None, None)
    )
    #: ``None`` means there is no valid selection, so the live observers no-op.
    #: The selected set's slice from the last recompute, window bounds
    #: included (#217 folded `cur_win_start` / `cur_win_end` into it). `None`
    #: when there is no valid selection, which is what the live observers check.
    cur_prep: SelectionSlice | None = None
    #: Keyed by (chart_kind, benchmark[, direction, pct]) and shared by both
    #: panes, since the result depends on `cur_prep` and the benchmark only.
    memo: LRUCache = field(default_factory=LRUCache)
    #: The live benchmark set and the selectors bound to it. ``build_app``
    #: creates it before the widgets (they register on construction) and hands
    #: it here; the default is the curated list.
    benchmarks: BenchmarkRegistry = field(default_factory=BenchmarkRegistry)
