from __future__ import annotations

import ipywidgets as W
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer, VegaExpr

from .theme import _palette_color


def _perf_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=80,  # default for numeric metric cols
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="240px"),
    )
    return grid


PERF_COLOR_COLUMN_NAME: str = "Chart Color"


# Column widths in pixels, keyed by the column's *leaf* label. The grid uses
# 2-level MultiIndex columns (Info / 1Y / 3Y / 5Y supercolumns over their
# leaves); `_build_perf_column_widths` emits ipydatagrid's "<level0>,<level1>"
# comma-joined keys from these. The descriptive text columns carry the slack
# that makes the grid fill a wide dashboard — ipydatagrid has no responsive
# stretch-to-container mode, so widths are set by hand to sum to ~full-HD
# width (~2014px incl. the 120px row header + metric columns).
_PERF_INFO_WIDTHS: dict[str, int] = {
    PERF_COLOR_COLUMN_NAME: 90,  # color swatch — wide enough to show header
    "Name": 360,
    "Asset Class": 180,
    "Theme": 280,
}


_PERF_METRIC_WIDTHS: dict[str, int] = {
    "Return": 88,
    "Vol": 76,
    "Sharpe": 72,
    "Max DD": 92,
}


_PERF_INFO_TEXT_COLS: frozenset[str] = frozenset({"Name", "Asset Class", "Theme"})


def _build_perf_column_widths(columns: pd.Index) -> dict[str, int]:
    """Map each MultiIndex column to a pixel width, keyed by ipydatagrid's
    "<level0>,<level1>" comma-joined field name (e.g. "Info,Name",
    "1Y,Return"). Info leaves take fixed widths; metric leaves
    (Return/Vol/Sharpe/Max DD) take one width each so 1Y/3Y/5Y stay aligned."""
    widths: dict[str, int] = {}
    for col in columns:
        leaf = col[-1] if isinstance(col, tuple) else col
        key = ",".join(str(p) for p in col) if isinstance(col, tuple) else str(col)
        if leaf in _PERF_INFO_WIDTHS:
            widths[key] = _PERF_INFO_WIDTHS[leaf]
        elif leaf in _PERF_METRIC_WIDTHS:
            widths[key] = _PERF_METRIC_WIDTHS[leaf]
    return widths


def _update_perf_grid(grid: DataGrid, pt: pd.DataFrame, meta: pd.DataFrame) -> None:
    if pt.empty:
        grid.data = pd.DataFrame()
        return
    info_block = _build_info_block(
        meta,
        pt.index,
        ["name", "asset_class", "theme"],
        {"name": "Name", "asset_class": "Asset Class", "theme": "Theme"},
    )
    # Per-row color swatch: each cell carries the hex string; the renderer
    # paints background + text the same color so it shows as a solid block —
    # the universal legend for every chart in the panes. It leads the Info
    # supercolumn so the grid acts as the legend left-to-right.
    info_block.insert(
        0, PERF_COLOR_COLUMN_NAME, [_palette_color(i) for i in range(len(pt))]
    )
    info_block.columns = pd.MultiIndex.from_product([["Info"], info_block.columns])
    perf = pt.copy()
    perf.columns = pd.MultiIndex.from_tuples(
        [(str(period), str(metric)) for period, metric in pt.columns]
    )
    combined = pd.concat([info_block, perf], axis=1)
    combined.index.name = "Ticker"
    grid.data = combined
    _apply_grid_styling(grid, combined.columns, widths=True)


def _build_info_block(
    meta: pd.DataFrame,
    tickers: pd.Index | None,
    columns: list[str],
    rename: dict[str, str],
    *,
    date_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Build a grid 'Info' block from metadata: index by ticker, optionally
    `reindex` to `tickers` (selected-set order), select `columns`, ISO-format
    any `date_cols`, then `rename` to display headers. Shared by the
    selected-strategy grid (3 cols, reindexed to the current selection) and
    the all-catalog grid (6 cols incl. a formatted live_date, all tickers)."""
    info = meta.set_index("ticker")
    if tickers is not None:
        info = info.reindex(tickers)
    info = info[columns].copy()
    for col in date_cols:
        info[col] = info[col].dt.strftime("%Y-%m-%d")
    return info.rename(columns=rename)


def _perf_renderers(columns: pd.Index) -> dict:
    text = TextRenderer()
    pct = TextRenderer(format=".2%")
    f2 = TextRenderer(format=".2f")
    color_swatch = TextRenderer(
        background_color=VegaExpr("cell.value"),
        text_color=VegaExpr("cell.value"),
    )
    renderers: dict = {}
    for col in columns:
        # Columns are flat strings in the selected-strategy grid
        # (e.g. "1Y Sharpe") but MultiIndex tuples in the all-catalog grid
        # (e.g. ("1Y", "Sharpe")). Match on the metric leaf either way so
        # `.endswith` is only ever called on a string.
        leaf = col[-1] if isinstance(col, tuple) else col
        if leaf == PERF_COLOR_COLUMN_NAME:
            renderers[col] = color_swatch
        elif leaf in _PERF_INFO_TEXT_COLS:
            renderers[col] = text
        elif leaf == "Sharpe" or leaf.endswith(" Sharpe"):
            renderers[col] = f2
        elif leaf in ("Return", "Vol", "Max DD") or leaf.endswith(
            (" Return", " Vol", " Max DD")
        ):
            renderers[col] = pct
        else:
            renderers[col] = text
    return renderers


def _apply_grid_styling(
    grid: DataGrid, columns: pd.Index, *, widths: bool = False
) -> None:
    """Wire the shared per-column renderers (text / pct / 2dp / color-swatch)
    onto a grid, and — for the selected-strategy grid — the hand-tuned
    MultiIndex column widths. The all-catalog grid uses uniform
    `base_column_size`, so it leaves `widths` off."""
    grid.renderers = _perf_renderers(columns)
    if widths:
        grid.column_widths = _build_perf_column_widths(columns)


def _universe_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=92,
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="360px"),
    )
    return grid


def _update_universe_grid(grid: DataGrid, meta: pd.DataFrame, up: pd.DataFrame) -> None:
    if meta.empty:
        grid.data = pd.DataFrame()
        return
    info = _build_info_block(
        meta,
        None,
        ["name", "asset_class", "category", "theme", "return_type", "live_date"],
        {
            "name": "Name",
            "asset_class": "Asset Class",
            "category": "Category",
            "theme": "Theme",
            "return_type": "Return Type",
            "live_date": "Live Date",
        },
        date_cols=("live_date",),
    )
    info.columns = pd.MultiIndex.from_product([["Info"], info.columns])

    if up.empty:
        combined = info
    else:
        up_norm = up.copy()
        up_norm.columns = pd.MultiIndex.from_tuples(
            [(str(a), str(b)) for a, b in up_norm.columns]
        )
        # Order: Info block first, then 1Y, 3Y, 5Y, SI.
        period_order = ["1Y", "3Y", "5Y", "SI"]
        present = [p for p in period_order if p in up_norm.columns.get_level_values(0)]
        up_norm = up_norm.reindex(columns=present, level=0)
        combined = info.join(up_norm.reindex(info.index))

    combined.index.name = "Ticker"
    grid.data = combined
    _apply_grid_styling(grid, combined.columns)
