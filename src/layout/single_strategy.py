"""The Single Strategy tab (v0.9.0): a per-strategy deep-dive.

Workstream C delivered the tab **shell** — a single-select strategy picker plus
a shared benchmark selector + overlay toggle — and **Section 1**: a two-column
profile (metadata card on the left; a cumulative chart + compact standard-perf
table on the right). Workstream D adds **Section 2**: a 3-pill monthly-return
calendar (Absolute / Outperformance / Vol-adjusted) over one DataGrid. Section 3
(analytics charts) lands in Workstream E; ``section3_slot`` is left empty.

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

from ..stats import (
    calendar_return_table,
    cum_perf,
    perf_table,
    since_inception_perf,
)
from .charts import _update_line
from .chrome import _make_tab_button, _style_tab_button
from .filters import _ticker_options
from .grids import _calendar_grid, _perf_grid, _update_calendar_grid, _update_perf_grid
from .html import STYLE_CTX, _render_profile_card, render_template
from .panes import _line_chart, _make_benchmark_dropdown

# Calendar tabs: (pill label, calendar_return_table `kind`).
_CALENDAR_TABS: tuple[tuple[str, str], ...] = (
    ("Absolute", "absolute"),
    ("Outperformance", "outperformance"),
    ("Vol-adjusted", "vol_adjusted"),
)


def make_single_strategy_panel(meta: pd.DataFrame) -> SimpleNamespace:
    """Build the Single Strategy tab widgets and assemble ``.root``.

    Returns a ``SimpleNamespace`` of the live handles the builder binds and
    re-renders: the strategy ``picker``, the shared ``bench_dd`` + ``bench_chk``
    overlay toggle, the ``profile_w`` card, the ``line_fig`` cumulative chart,
    the compact ``perf_grid``, the calendar ``cal_grid`` + ``cal_pills`` (active
    ``cal_kind``), and the ``section3_slot`` container reserved for Workstream E.
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

    # Section 2 (Workstream D): a 3-pill monthly-return calendar over one grid.
    cal_pills = [
        _make_tab_button(label, active=i == 0)
        for i, (label, _k) in enumerate(_CALENDAR_TABS)
    ]
    cal_pill_bar = W.HBox(
        cal_pills,
        layout=W.Layout(width="100%", margin="0 0 4px 0"),
    )
    cal_grid = _calendar_grid()
    cal_header = W.HTML(
        render_template("grid_header", **STYLE_CTX, text="Monthly return calendar")
    )
    section2_slot = W.Box(
        [W.VBox([cal_header, cal_pill_bar, cal_grid], layout=W.Layout(width="100%"))],
        layout=W.Layout(width="100%", padding="8px 0 0 0"),
    )
    # Reserved for Workstream E (analytics charts).
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
        cal_grid=cal_grid,
        cal_pills=cal_pills,
        cal_kind=_CALENDAR_TABS[0][1],
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

    render_calendar(ss, state)


def set_calendar_kind(ss: SimpleNamespace, which: str) -> None:
    """Activate one calendar pill (`absolute` / `outperformance` /
    `vol_adjusted`): restyle the pills and record the kind. The caller
    re-renders via `render_calendar`."""
    ss.cal_kind = which
    for pill, (_label, kind) in zip(ss.cal_pills, _CALENDAR_TABS, strict=True):
        _style_tab_button(pill, active=kind == which)


def render_calendar(ss: SimpleNamespace, state: object) -> None:
    """Render the monthly-return calendar for the picked strategy + active kind.

    Reads the cached prices (no BQL). The `outperformance` kind uses the shared
    benchmark Dropdown; a missing ticker / benchmark clears the grid."""
    prices = state.universe_prices
    ticker = ss.picker.value
    kind = ss.cal_kind
    if ticker is None or prices is None or prices.empty or ticker not in prices.columns:
        _update_calendar_grid(ss.cal_grid, pd.DataFrame(), kind=kind)
        return
    benchmark = None
    if kind == "outperformance":
        bench = ss.bench_dd.value
        benchmark = prices[bench] if bench in prices.columns else None
    table = calendar_return_table(prices[ticker], kind=kind, benchmark=benchmark)
    _update_calendar_grid(ss.cal_grid, table, kind=kind)
