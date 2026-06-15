from __future__ import annotations

import ipywidgets as W
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer, VegaExpr

from ..style import Color
from .theme import _palette_color


def _dark_grid_style() -> dict:
    """ipydatagrid `grid_style` for the dark chrome (v0.6.5 PR 5). All values
    are `src/style.py` Color tokens, matching the dark charts/chrome. A subtle
    `SURFACE` zebra over the `CHROME_BG` body keeps wide rows readable; selection
    / cursor pick up the orange `ACCENT`."""
    return {
        "void_color": Color.CHROME_BG,
        "background_color": Color.CHROME_BG,
        "row_background_color": VegaExpr(
            f"cell.row % 2 === 0 ? '{Color.CHROME_BG}' : '{Color.SURFACE}'"
        ),
        "grid_line_color": Color.BORDER,
        "header_background_color": Color.SURFACE,
        "header_grid_line_color": Color.BORDER,
        "selection_fill_color": Color.SURFACE_2,
        "selection_border_color": Color.ACCENT,
        "header_selection_fill_color": Color.SURFACE_2,
        "header_selection_border_color": Color.ACCENT,
        "cursor_fill_color": Color.SURFACE_2,
        "cursor_border_color": Color.ACCENT,
    }


def _dark_grid_kwargs() -> dict:
    """Static dark-theme kwargs shared by both grid constructors: the
    `grid_style` plus bright-text header / corner / body-fallback renderers
    (header text color is a renderer trait, not a `grid_style` key)."""
    return {
        "grid_style": _dark_grid_style(),
        "header_renderer": TextRenderer(
            text_color=Color.TEXT, background_color=Color.SURFACE
        ),
        "corner_renderer": TextRenderer(
            text_color=Color.TEXT, background_color=Color.SURFACE
        ),
        "default_renderer": TextRenderer(text_color=Color.TEXT),
    }


def _perf_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=80,  # default for numeric metric cols
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="240px"),
        **_dark_grid_kwargs(),
    )
    grid.add_class("bbg-grid")
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


# v0.7.0 Workstream A — the all-catalog grid's dynamic z-score supercolumn name
# and the diverging-heatmap thresholds for its conditional-formatted columns.
ZSCORE_SUPERCOL: str = "Z-Score"
# Sharpe leaves: neutral band straddles ~0–0.5, red below, green above.
_SHARPE_HEAT_THRESHOLDS: tuple[float, float, float, float] = (-0.5, 0.0, 0.5, 1.0)
# Z-Score column: already centered at 0, so the bands are symmetric.
_ZSCORE_HEAT_THRESHOLDS: tuple[float, float, float, float] = (-1.5, -0.5, 0.5, 1.5)


def _zebra_expr() -> str:
    """VegaExpr fragment for the row-parity zebra background, so neutral / blank
    heatmap cells blend into the grid_style striping instead of overriding it."""
    return f"(cell.row % 2 === 0 ? '{Color.CHROME_BG}' : '{Color.SURFACE}')"


def _diverging_bg_renderer(
    thresholds: tuple[float, float, float, float],
    *,
    fmt: str = ".2f",
    missing: str = "",
) -> TextRenderer:
    """A numeric renderer whose background is a diverging red→neutral→green
    ramp keyed to `cell.value` via the existing VegaExpr mechanism. NaN/null and
    the neutral band (between the two middle thresholds) fall back to the zebra
    so empty / middling cells read normally. `fmt` is the display number format
    (".2f" for ratios / Sharpe, ".2%" for return cells); `missing` is the text
    shown for empty cells (e.g. "-") while the value stays numeric so the
    background ramp is unaffected.

    Note on `missing`: ipydatagrid's `missing` trait only substitutes on a strict
    JSON ``null``, but a pandas ``NaN`` round-trips to a JS ``NaN`` (never null),
    so that trait never fires for our data. We instead drive the empty-cell text
    through a `text_value` VegaExpr: the frontend renders ``text_value || <the
    d3-formatted number>``, so returning ``''`` for real numbers falls back to
    the normal `fmt` output while NaN cells return `missing`. `cell.value` stays
    numeric, so the background ramp (which already routes NaN to the zebra) is
    unaffected."""
    t0, t1, t2, t3 = thresholds
    zebra = _zebra_expr()
    expr = (
        f"(cell.value == null || isNaN(cell.value)) ? {zebra} : "
        f"cell.value < {t0} ? '{Color.HEAT_NEG_STRONG}' : "
        f"cell.value < {t1} ? '{Color.HEAT_NEG_SOFT}' : "
        f"cell.value < {t2} ? {zebra} : "
        f"cell.value < {t3} ? '{Color.HEAT_POS_SOFT}' : "
        f"'{Color.HEAT_POS_STRONG}'"
    )
    renderer = TextRenderer(
        format=fmt,
        missing=missing,
        text_color=Color.TEXT,
        background_color=VegaExpr(expr),
    )
    if missing:
        renderer.text_value = VegaExpr(f"isNaN(cell.value) ? '{missing}' : ''")
    return renderer


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
    _apply_grid_styling(grid, combined.columns, widths=True, sharpe_heatmap=True)


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


def _perf_renderers(columns: pd.Index, *, sharpe_heatmap: bool = False) -> dict:
    # Bright text on the dark body; no background_color so the `grid_style`
    # zebra (`row_background_color`) shows through. The color-swatch keeps its
    # VegaExpr bg/text (a renderer's own background overrides grid_style).
    # `sharpe_heatmap` (all-catalog grid only) swaps the plain 2dp renderer for
    # a diverging-background one on the Sharpe leaves + the Z-Score column,
    # leaving the selected-strategy grid (defaults off) visually unchanged.
    text = TextRenderer(text_color=Color.TEXT)
    pct = TextRenderer(format=".2%", text_color=Color.TEXT)
    f2 = TextRenderer(format=".2f", text_color=Color.TEXT)
    color_swatch = TextRenderer(
        background_color=VegaExpr("cell.value"),
        text_color=VegaExpr("cell.value"),
    )
    sharpe_renderer = (
        _diverging_bg_renderer(_SHARPE_HEAT_THRESHOLDS) if sharpe_heatmap else f2
    )
    zscore_renderer = (
        _diverging_bg_renderer(_ZSCORE_HEAT_THRESHOLDS) if sharpe_heatmap else f2
    )
    renderers: dict = {}
    for col in columns:
        # Columns are flat strings in the selected-strategy grid
        # (e.g. "1Y Sharpe") but MultiIndex tuples in the all-catalog grid
        # (e.g. ("1Y", "Sharpe")). Match on the metric leaf either way so
        # `.endswith` is only ever called on a string.
        leaf = col[-1] if isinstance(col, tuple) else col
        if isinstance(col, tuple) and col[0] == ZSCORE_SUPERCOL:
            renderers[col] = zscore_renderer
        elif leaf == PERF_COLOR_COLUMN_NAME:
            renderers[col] = color_swatch
        elif leaf in _PERF_INFO_TEXT_COLS:
            renderers[col] = text
        elif leaf == "Sharpe" or leaf.endswith(" Sharpe"):
            renderers[col] = sharpe_renderer
        elif leaf in ("Return", "Vol", "Max DD") or leaf.endswith(
            (" Return", " Vol", " Max DD")
        ):
            renderers[col] = pct
        else:
            renderers[col] = text
    return renderers


def _apply_grid_styling(
    grid: DataGrid,
    columns: pd.Index,
    *,
    widths: bool = False,
    sharpe_heatmap: bool = False,
) -> None:
    """Wire the shared per-column renderers (text / pct / 2dp / color-swatch)
    onto a grid, and — for the selected-strategy grid — the hand-tuned
    MultiIndex column widths. The all-catalog grid uses uniform
    `base_column_size` (so it leaves `widths` off) and opts into the diverging
    Sharpe / Z-Score `sharpe_heatmap`."""
    grid.renderers = _perf_renderers(columns, sharpe_heatmap=sharpe_heatmap)
    if widths:
        grid.column_widths = _build_perf_column_widths(columns)


# v0.9.0 Workstream D — the Single Strategy monthly-return calendar.
# Month / annual cells are returns: red below -5%, soft red to -1%, neutral
# ±1%, soft green to +5%, strong green above. Vol-adjusted cells are
# return/vol ratios on a wider unitless band. The Sharpe summary column reuses
# the perf-grid Sharpe band.
_CALENDAR_RETURN_THRESHOLDS: tuple[float, float, float, float] = (
    -0.05,
    -0.01,
    0.01,
    0.05,
)
_CALENDAR_VOLADJ_THRESHOLDS: tuple[float, float, float, float] = (
    -1.0,
    -0.25,
    0.25,
    1.0,
)
# Correlation cells diverge around 0; beta cells around the 1.0 market-beta
# neutral band. The ramp encodes magnitude/sign, not good/bad.
_CALENDAR_CORR_THRESHOLDS: tuple[float, float, float, float] = (-0.5, -0.1, 0.1, 0.5)
_CALENDAR_BETA_THRESHOLDS: tuple[float, float, float, float] = (0.0, 0.7, 1.3, 2.0)
_CALENDAR_SUMMARY_COLS: frozenset[str] = frozenset({"Year", "Sharpe"})
# Empty (NaN) calendar cells render as this dash rather than blank / "NaN".
_CALENDAR_MISSING: str = "-"


def _calendar_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=26,
        base_column_size=62,
        base_row_header_size=54,
        layout=W.Layout(width="100%", height="260px"),
        **_dark_grid_kwargs(),
    )
    grid.add_class("bbg-grid")
    return grid


def _calendar_renderers(columns: pd.Index, *, kind: str) -> dict:
    """Diverging renderers for the calendar grid, keyed by `kind`. Month + Year
    cells are returns (".2%") for absolute / outperformance, ratios (".2f") for
    vol-adjusted, and beta / correlation values (".2f") for those kinds; `Sharpe`
    always uses the Sharpe band. Empty cells display ``-`` (`_CALENDAR_MISSING`)
    via the renderer's numeric-preserving `text_value` empty-cell text."""
    if kind == "vol_adjusted":
        month_thr, month_fmt = _CALENDAR_VOLADJ_THRESHOLDS, ".2f"
        year_thr, year_fmt = _CALENDAR_RETURN_THRESHOLDS, ".2%"
    elif kind == "beta":
        month_thr = year_thr = _CALENDAR_BETA_THRESHOLDS
        month_fmt = year_fmt = ".2f"
    elif kind == "correlation":
        month_thr = year_thr = _CALENDAR_CORR_THRESHOLDS
        month_fmt = year_fmt = ".2f"
    else:  # absolute / outperformance
        month_thr = year_thr = _CALENDAR_RETURN_THRESHOLDS
        month_fmt = year_fmt = ".2%"
    month_r = _diverging_bg_renderer(
        month_thr, fmt=month_fmt, missing=_CALENDAR_MISSING
    )
    year_r = _diverging_bg_renderer(year_thr, fmt=year_fmt, missing=_CALENDAR_MISSING)
    sharpe_r = _diverging_bg_renderer(
        _SHARPE_HEAT_THRESHOLDS, fmt=".2f", missing=_CALENDAR_MISSING
    )
    renderers: dict = {}
    for col in columns:
        if col == "Year":
            renderers[col] = year_r
        elif col == "Sharpe":
            renderers[col] = sharpe_r
        else:
            renderers[col] = month_r
    return renderers


def _update_calendar_grid(grid: DataGrid, table: pd.DataFrame, *, kind: str) -> None:
    """Render a `calendar_return_table` frame (years × Jan…Dec + Year + Sharpe)
    into the calendar DataGrid, oldest year on top, with diverging conditional
    formatting keyed to `kind`."""
    if table is None or table.empty:
        grid.data = pd.DataFrame()
        return
    display = table.sort_index(ascending=True)
    display.index = display.index.astype(int).astype(str)
    display.index.name = ""
    grid.data = display
    grid.renderers = _calendar_renderers(display.columns, kind=kind)


def _universe_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=92,
        base_row_header_size=120,
        layout=W.Layout(width="100%", height="360px"),
        **_dark_grid_kwargs(),
    )
    grid.add_class("bbg-grid")
    return grid


def _build_universe_frame(
    meta: pd.DataFrame,
    up: pd.DataFrame,
    *,
    zcol: pd.Series | None = None,
    zlabel: str | None = None,
) -> pd.DataFrame:
    """Assemble the all-catalog grid's DataFrame (pure — no grid side effects).

    Column order is Info → Z-Score (when supplied) → 1Y → 3Y → 5Y, all
    under 2-level MultiIndex supercolumns. When a `zcol` (per-ticker z-score
    Series) + `zlabel` are given, a `(ZSCORE_SUPERCOL, zlabel)` column is
    inserted right after the Info block — it's the headline ranking column, so
    it sits next to the names — and the whole frame is sorted by it descending
    (insufficient-history tickers, NaN z, sink to the bottom)."""
    if meta.empty:
        return pd.DataFrame()
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

    blocks = [info]
    z_key: tuple[str, str] | None = None
    if zcol is not None and zlabel is not None:
        z_key = (ZSCORE_SUPERCOL, zlabel)
        zframe = pd.DataFrame({zlabel: zcol.reindex(info.index)})
        zframe.columns = pd.MultiIndex.from_product([[ZSCORE_SUPERCOL], zframe.columns])
        blocks.append(zframe)

    if not up.empty:
        up_norm = up.copy()
        up_norm.columns = pd.MultiIndex.from_tuples(
            [(str(a), str(b)) for a, b in up_norm.columns]
        )
        # Order: 1Y, 3Y, 5Y (Since-Inception dropped in v0.7.2).
        period_order = ["1Y", "3Y", "5Y"]
        present = [p for p in period_order if p in up_norm.columns.get_level_values(0)]
        up_norm = up_norm.reindex(columns=present, level=0)
        blocks.append(up_norm.reindex(info.index))

    combined = pd.concat(blocks, axis=1) if len(blocks) > 1 else info
    if z_key is not None:
        combined = combined.sort_values(z_key, ascending=False, na_position="last")
    combined.index.name = "Ticker"
    return combined


def _update_universe_grid(
    grid: DataGrid,
    meta: pd.DataFrame,
    up: pd.DataFrame,
    *,
    zcol: pd.Series | None = None,
    zlabel: str | None = None,
) -> None:
    combined = _build_universe_frame(meta, up, zcol=zcol, zlabel=zlabel)
    grid.data = combined
    _apply_grid_styling(grid, combined.columns, sharpe_heatmap=True)
