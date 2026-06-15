"""Tests for the Single Strategy tab (v0.9.0 Workstream C).

Covers the pure profile-card renderer (incl. NA-safety) and the Section 1
recompute (`render_single_strategy`) against a mock cache: chart traces, the
benchmark overlay, the compact perf table, and the empty/missing-ticker guard.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from src.layout.html import _na, _render_profile_card
from src.layout.single_strategy import (
    make_single_strategy_panel,
    render_single_strategy,
)


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "category": ["X", "Y", "Z"],
            "theme": ["T1", "T2", "T3"],
            "return_type": ["Total", "Total", "Excess"],
            "currency": ["USD", "EUR", "USD"],
            "description": ["Alpha desc", pd.NA, "Charlie desc"],
        }
    )


def test_na_helper():
    assert _na(pd.NA) == "—"
    assert _na(None) == "—"
    assert _na("   ") == "—"
    assert _na("USD") == "USD"


def test_render_profile_card_contains_fields():
    html = _render_profile_card(_meta().iloc[0])
    for token in ("Alpha", "AAA Index", "USD", "Total", "Alpha desc"):
        assert token in html


def test_render_profile_card_is_na_safe():
    # Bravo's description is NA → renders an em dash, no exception.
    html = _render_profile_card(_meta().iloc[1])
    assert "Bravo" in html and "BBB Index" in html
    assert "—" in html


def test_render_single_strategy_populates_chart_and_grid(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = multiyear_prices.copy()
    universe["SPX Index"] = benchmark  # a benchmark column rides along
    state = SimpleNamespace(universe_prices=universe)
    window_start = universe.index.min()

    ss.picker.value = "AAA Index"
    render_single_strategy(ss, state, meta, window_start)
    assert len(ss.line_fig.data) == 1  # strategy only, no overlay
    assert not ss.perf_grid.data.empty
    assert "Alpha" in ss.profile_w.value

    # Toggling the overlay adds the benchmark trace.
    ss.bench_chk.value = True
    ss.bench_dd.value = "SPX Index"
    render_single_strategy(ss, state, meta, window_start)
    assert len(ss.line_fig.data) == 2


def test_render_single_strategy_reacts_to_picker(multiyear_prices, benchmark):
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    universe = multiyear_prices.copy()
    universe["SPX Index"] = benchmark
    state = SimpleNamespace(universe_prices=universe)
    window_start = universe.index.min()

    ss.picker.value = "AAA Index"
    render_single_strategy(ss, state, meta, window_start)
    assert "Alpha" in ss.profile_w.value
    ss.picker.value = "BBB Index"
    render_single_strategy(ss, state, meta, window_start)
    assert "Bravo" in ss.profile_w.value


def test_render_single_strategy_empty_cache_no_raise():
    meta = _meta()
    ss = make_single_strategy_panel(meta)
    state = SimpleNamespace(universe_prices=pd.DataFrame())
    render_single_strategy(ss, state, meta, pd.Timestamp("2020-01-01"))
    assert len(ss.line_fig.data) == 0
    assert ss.perf_grid.data.empty
