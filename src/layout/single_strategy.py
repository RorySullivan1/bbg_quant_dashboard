"""The Single Strategy tab (v0.9.0): a per-strategy deep-dive.

Workstream C delivers the tab **shell** — a single-select strategy picker plus a
shared benchmark selector + overlay toggle — and **Section 1**: a two-column
profile (metadata card on the left; a cumulative chart + compact standard-perf
table on the right). Sections 2 (calendar) and 3 (analytics charts) land in
Workstreams D/E; this module leaves empty ``section2_slot`` / ``section3_slot``
containers for them to fill.

Everything reuses the existing layout toolkit — no new runtime deps:
``_line_chart`` / ``_make_benchmark_dropdown`` (panes), ``_perf_grid`` /
``_update_perf_grid`` (grids), ``_update_line`` (charts), ``_ticker_options``
(filters), ``_render_profile_card`` (html), and the stats perf tables. No BQL:
prices come from the cached ``state.universe_prices``.
"""

from __future__ import annotations

from types import SimpleNamespace

import ipywidgets as W
import pandas as pd

from ..stats import cum_perf, perf_table, since_inception_perf
from .charts import _update_line
from .filters import _ticker_options
from .grids import _perf_grid, _update_perf_grid
from .html import STYLE_CTX, _render_profile_card, render_template
from .panes import _line_chart, _make_benchmark_dropdown


def make_single_strategy_panel(meta: pd.DataFrame) -> SimpleNamespace:
    """Build the Single Strategy tab widgets and assemble ``.root``.

    Returns a ``SimpleNamespace`` of the live handles the builder binds and
    re-renders: the strategy ``picker``, the shared ``bench_dd`` + ``bench_chk``
    overlay toggle, the ``profile_w`` card, the ``line_fig`` cumulative chart,
    the compact ``perf_grid``, and the empty ``section2_slot`` / ``section3_slot``
    containers reserved for Workstreams D/E.
    """
    options = _ticker_options(meta)
    picker = W.Dropdown(
        options=options,
        value=options[0][1] if options else None,
        description="Strategy",
        style={"description_width": "70px"},
        layout=W.Layout(width="360px"),
    )
    bench_dd = _make_benchmark_dropdown()
    bench_chk = W.Checkbox(
        value=False,
        description="Show benchmark",
        indent=False,
        layout=W.Layout(width="160px"),
    )
    controls_row = W.HBox(
        [picker, bench_dd, bench_chk],
        layout=W.Layout(width="100%", align_items="center", margin="0 0 6px 0"),
    )

    profile_w = W.HTML()
    line_fig = _line_chart()
    perf_grid = _perf_grid()

    profile_header = W.HTML(
        render_template("grid_header", **STYLE_CTX, text="Strategy profile")
    )
    perf_header = W.HTML(
        render_template("grid_header", **STYLE_CTX, text="Standard performance")
    )
    left_col = W.VBox(
        [profile_header, profile_w],
        layout=W.Layout(width="38%", padding="0 8px 0 0"),
    )
    right_col = W.VBox(
        [line_fig, perf_header, perf_grid],
        layout=W.Layout(width="62%"),
    )
    section1 = W.HBox(
        [left_col, right_col],
        layout=W.Layout(width="100%", align_items="stretch"),
    )

    # Reserved for Workstreams D (calendar table) and E (analytics charts).
    section2_slot = W.Box(layout=W.Layout(width="100%"))
    section3_slot = W.Box(layout=W.Layout(width="100%"))

    root = W.VBox(
        [controls_row, section1, section2_slot, section3_slot],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )

    return SimpleNamespace(
        root=root,
        picker=picker,
        bench_dd=bench_dd,
        bench_chk=bench_chk,
        profile_w=profile_w,
        line_fig=line_fig,
        perf_grid=perf_grid,
        section2_slot=section2_slot,
        section3_slot=section3_slot,
    )


def render_single_strategy(
    ss: SimpleNamespace,
    state: object,
    meta: pd.DataFrame,
    window_start: pd.Timestamp,
) -> None:
    """Render Section 1 for the currently-picked strategy.

    Reads the cached ``state.universe_prices`` (no BQL): renders the profile
    card, the cumulative chart (rebased to 100, with the benchmark overlaid when
    the toggle is on), and the compact 1/3/5Y + since-inception perf table. A
    missing ticker / empty cache clears the chart and grid without raising.
    """
    ticker = ss.picker.value
    prices = state.universe_prices
    row = meta.loc[meta["ticker"] == ticker] if ticker is not None else meta.iloc[0:0]
    ss.profile_w.value = _render_profile_card(row.iloc[0]) if not row.empty else ""

    if ticker is None or prices is None or prices.empty or ticker not in prices.columns:
        _update_line(ss.line_fig, pd.DataFrame(), meta)
        _update_perf_grid(ss.perf_grid, pd.DataFrame(), meta)
        return

    cols = [ticker]
    if ss.bench_chk.value:
        bench = ss.bench_dd.value
        if bench in prices.columns and bench != ticker:
            cols.append(bench)
    window = prices.loc[prices.index >= window_start, cols]
    _update_line(ss.line_fig, cum_perf(window), meta)

    full = prices[[ticker]]
    pt = pd.concat([perf_table(full), since_inception_perf(full)], axis=1)
    _update_perf_grid(ss.perf_grid, pt, meta)
