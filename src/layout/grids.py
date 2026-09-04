"""ipydatagrid table construction, theming, and formatting.

Every DataGrid in the app is built here: the all-catalog and selected-strategy
perf grids, the Single Strategy monthly-return calendar, and the return-
distribution stats table.

Three concerns recur. **Theming** — `_dark_grid_style` / `_dark_grid_kwargs`
express the dark chrome purely in `style.py` tokens, and `_reassert_dark_theme`
reapplies them after a data swap, which otherwise resets the frontend's style.
**Sizing** — perf-grid column widths are computed in Python (see
`_perf_column_widths`) rather than by the frontend's autofit. **Formatting** —
renderers centre numeric cells, show missing values as a dash, and apply the
diverging red→green background to the Sharpe and Z-Score columns.
"""

from __future__ import annotations

import ipywidgets as W
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer, VegaExpr

from ..style import Color
from .theme import _palette_color


def _dark_grid_style() -> dict:
    """ipydatagrid `grid_style` for the dark chrome. All values
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
            text_color=Color.TEXT,
            background_color=Color.SURFACE,
            horizontal_alignment="center",
        ),
        "corner_renderer": TextRenderer(
            text_color=Color.TEXT, background_color=Color.SURFACE
        ),
        "default_renderer": TextRenderer(text_color=Color.TEXT),
    }


def _reassert_dark_theme(grid: DataGrid) -> None:
    """Re-apply the dark grid theme after a ``grid.data`` reassignment.

    The dark ``grid_style`` (background / zebra / header colors) and the
    bright-text header/corner/default renderers are set once at construction
    (``_dark_grid_kwargs``). Reassigning ``grid.data`` on a Refresh rebuilds the
    frontend grid model, which drops the styling back to ipydatagrid's default
    (white) background — the "reverts to the original background" symptom. The
    per-column ``renderers`` are already rebuilt on each update (their column
    keys change with the data), but ``grid_style`` is not, so re-assert the full
    dark theme here. ``grid_style`` is force-synced via ``send_state`` because an
    equal dict would otherwise short-circuit the traitlets diff and never
    re-reach the frontend."""
    kw = _dark_grid_kwargs()
    grid.grid_style = kw["grid_style"]
    grid.header_renderer = kw["header_renderer"]
    grid.corner_renderer = kw["corner_renderer"]
    grid.default_renderer = kw["default_renderer"]
    grid.send_state("grid_style")


def _perf_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=_STAT_COL_WIDTH,  # uniform stat cols; per-col widths
        base_column_header_size=26,  # single-row header (flat, single-index)
        base_row_header_size=110,  # re-fit to the ticker content per update
        layout=W.Layout(width="100%", height="240px"),
        **_dark_grid_kwargs(),
    )
    grid.add_class("bbg-grid")
    return grid


# The per-strategy chart-color swatch column. Its header is intentionally blank
# (a single space) — the column is a narrow color chip, not a labelled field —
# so it reads as a nameless legend swatch rather than a clipped "Chart Color".
PERF_COLOR_COLUMN_NAME: str = " "


#: Column sizing for the flat perf / catalog grids. Descriptive columns are fit
#: to their content in Python rather than by ipydatagrid's `auto_fit_columns`,
#: which fits *every* column and writes the result back over `column_widths` —
#: so it cannot be scoped to those columns while keeping the rest pinned.
_COLOR_COL_WIDTH: int = 30  # narrow swatch chip — visible color, minimal space
_STAT_COL_WIDTH: int = 82  # uniform width for every Return/Vol/Sharpe/Max DD col
_CHAR_PX: float = 7.6  # ~avg glyph width at the 12px grid font
_TEXT_PAD: int = 24  # cell padding + a little header slack
_TEXT_COL_MIN: int = 56
_TEXT_COL_MAX: int = 340
# Flat stat-column suffixes (a column is a "stat" if its name ends with one).
_STAT_SUFFIXES: tuple[str, ...] = (" Return", " Vol", " Sharpe", " Max DD")


def _content_px(header: object, values: object) -> int:
    """Pixel width to fit ``header`` plus the widest of ``values`` at the grid
    font — a deterministic stand-in for ipydatagrid's frontend-only autofit
    (which can't be limited to a subset of columns). Clamped to keep long
    strategy names from blowing out the row."""
    longest = len(str(header))
    for v in values or ():
        s = "" if v is None else str(v)
        if s and s.lower() != "nan":
            longest = max(longest, len(s))
    return int(min(_TEXT_COL_MAX, max(_TEXT_COL_MIN, longest * _CHAR_PX + _TEXT_PAD)))


def _is_stat_col(name: str) -> bool:
    return name.endswith(_STAT_SUFFIXES)


def _is_zscore_col(name: str) -> bool:
    return name == ZSCORE_SUPERCOL or name.startswith(ZSCORE_SUPERCOL + " ")


def _flatten_perf_columns(columns: pd.Index) -> list[str]:
    """Flatten (period, metric) column tuples to single-index labels, e.g.
    ``("1Y", "Return") -> "1Y Return"``. Non-tuple names pass through."""
    return [
        " ".join(str(p) for p in c) if isinstance(c, tuple) else str(c) for c in columns
    ]


def _perf_column_widths(frame: pd.DataFrame) -> dict[str, int]:
    """Per-column pixel widths for a flat perf / catalog grid: a tiny color
    swatch, uniform stat columns, and content-fit descriptive / z-score
    columns (fit to the header + the actual cell strings)."""
    widths: dict[str, int] = {}
    for col in frame.columns:
        name = str(col)
        if name == PERF_COLOR_COLUMN_NAME:
            widths[name] = _COLOR_COL_WIDTH
        elif _is_zscore_col(name):
            widths[name] = _content_px(name, frame[col].tolist())
        elif _is_stat_col(name):
            widths[name] = _STAT_COL_WIDTH
        else:
            widths[name] = _content_px(name, frame[col].tolist())
    return widths


# The all-catalog grid's dynamic z-score column name, and the diverging-heatmap
# thresholds for its conditional-formatted columns.
ZSCORE_SUPERCOL: str = "Z-Score"
# Sharpe leaves: neutral band straddles ~0–0.5, red below, green above.
_SHARPE_HEAT_THRESHOLDS: tuple[float, float, float, float] = (-0.5, 0.0, 0.5, 1.0)
# Z-Score column: already centered at 0, so the bands are symmetric.
_ZSCORE_HEAT_THRESHOLDS: tuple[float, float, float, float] = (-1.5, -0.5, 0.5, 1.5)


def _zebra_expr() -> str:
    """VegaExpr fragment for the row-parity zebra background, so neutral / blank
    heatmap cells blend into the grid_style striping instead of overriding it."""
    return f"(cell.row % 2 === 0 ? '{Color.CHROME_BG}' : '{Color.SURFACE}')"


# Empty (NaN) numeric cells render as this dash rather than "NaN" / "NaN%".
_MISSING_DASH: str = "-"


def _dash_text_value(missing: str) -> VegaExpr:
    """A `text_value` VegaExpr that shows `missing` (e.g. "-") for empty cells.

    ipydatagrid's `missing` trait only substitutes on a strict JSON ``null``, but
    a pandas ``NaN`` round-trips through serialization to a JS ``NaN`` (never
    null), so that trait never fires for our data. The frontend instead renders
    ``text_value || <the d3-formatted number>``, so returning ``''`` for real
    values falls back to the renderer's normal numeric format while NaN cells
    return `missing`. `cell.value` stays numeric, so any diverging background
    ramp is unaffected.

    Only wire this onto *numeric* columns: ``isNaN`` is true for any non-numeric
    string, so on a text column it would blank every cell to the dash."""
    return VegaExpr(f"isNaN(cell.value) ? '{missing}' : ''")


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
    background ramp is unaffected. The empty-cell text is driven through a
    `text_value` VegaExpr (see `_dash_text_value`) because ipydatagrid's
    `missing` trait never fires for a pandas NaN."""
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
        horizontal_alignment="center",
    )
    if missing:
        renderer.text_value = _dash_text_value(missing)
    return renderer


def _plain_num_renderer(fmt: str, *, missing: str = "") -> TextRenderer:
    """A numeric renderer with no diverging background (the grid zebra shows
    through), but the same empty-cell dash handling as `_diverging_bg_renderer`.
    Used for summary columns like Vol where a red→green ramp would imply a
    good/bad axis that doesn't exist."""
    renderer = TextRenderer(
        format=fmt,
        missing=missing,
        text_color=Color.TEXT,
        horizontal_alignment="center",
    )
    if missing:
        renderer.text_value = _dash_text_value(missing)
    return renderer


def _update_perf_grid(grid: DataGrid, pt: pd.DataFrame, meta: pd.DataFrame) -> None:
    if pt.empty:
        grid.data = pd.DataFrame()
        _reassert_dark_theme(grid)
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
    # columns so the grid acts as the legend left-to-right.
    info_block.insert(
        0, PERF_COLOR_COLUMN_NAME, [_palette_color(i) for i in range(len(pt))]
    )
    # Flat single-index columns ("1Y Return", …) — single-row header, autofit
    # of the descriptive columns, and clean per-column widths.
    perf = pt.copy()
    perf.columns = _flatten_perf_columns(pt.columns)
    combined = pd.concat([info_block, perf], axis=1)
    combined.index.name = "Ticker"
    grid.data = combined
    _apply_grid_styling(grid, combined, sharpe_heatmap=True)
    _reassert_dark_theme(grid)


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
    # No background_color, so the `grid_style` zebra shows through.
    # `sharpe_heatmap` swaps the plain 2dp renderer for a diverging-background
    # one on the Sharpe and Z-Score columns. NaN numeric cells show "-" via a
    # `text_value` expr; text columns keep plain text, since `isNaN` is true for
    # any non-numeric string.
    dash = _dash_text_value(_MISSING_DASH)
    text = TextRenderer(text_color=Color.TEXT)  # descriptive — left aligned
    pct = TextRenderer(
        format=".2%",
        text_color=Color.TEXT,
        text_value=dash,
        horizontal_alignment="center",
    )
    f2 = TextRenderer(
        format=".2f",
        text_color=Color.TEXT,
        text_value=dash,
        horizontal_alignment="center",
    )
    color_swatch = TextRenderer(
        background_color=VegaExpr("cell.value"),
        text_color=VegaExpr("cell.value"),
    )
    sharpe_renderer = (
        _diverging_bg_renderer(_SHARPE_HEAT_THRESHOLDS, missing=_MISSING_DASH)
        if sharpe_heatmap
        else f2
    )
    zscore_renderer = (
        _diverging_bg_renderer(_ZSCORE_HEAT_THRESHOLDS, missing=_MISSING_DASH)
        if sharpe_heatmap
        else f2
    )
    renderers: dict = {}
    for col in columns:
        name = str(col)
        # Z-Score first: its name (e.g. "Z-Score 1M Sharpe") also ends in
        # " Sharpe", so it must win over the Sharpe branch below.
        if _is_zscore_col(name):
            renderers[col] = zscore_renderer
        elif name == PERF_COLOR_COLUMN_NAME:
            renderers[col] = color_swatch
        elif name.endswith(" Sharpe"):
            renderers[col] = sharpe_renderer
        elif name.endswith((" Return", " Vol", " Max DD")):
            renderers[col] = pct
        else:
            renderers[col] = text
    return renderers


def _apply_grid_styling(
    grid: DataGrid,
    frame: pd.DataFrame,
    *,
    sharpe_heatmap: bool = False,
) -> None:
    """Wire the shared per-column renderers (text / pct / 2dp / color-swatch)
    onto a grid, plus the flat single-index column widths (tiny color swatch,
    uniform stat columns, content-fit descriptive columns) and a content-fit
    ticker row-header. Shared by the selected-strategy / single-strategy perf
    grids and the all-catalog grid; the latter opts into the diverging Sharpe /
    Z-Score `sharpe_heatmap`."""
    grid.renderers = _perf_renderers(frame.columns, sharpe_heatmap=sharpe_heatmap)
    grid.column_widths = _perf_column_widths(frame)
    grid.base_row_header_size = _content_px(
        frame.index.name or "", frame.index.tolist()
    )


# The Single Strategy monthly-return calendar.
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
# Renderer spec per calendar summary column: (thresholds | None, fmt). A
# `None` threshold → a plain (non-diverging) renderer, used for Vol where a
# good/bad color ramp would mislead. Return-like columns use the return ramp
# (".2%"); Sharpe / Beta / Correlation use their own bands (".2f").
_CALENDAR_SUMMARY_SPECS: dict[str, tuple[tuple[float, float, float, float] | None, str]]
_CALENDAR_SUMMARY_SPECS = {
    "Return": (_CALENDAR_RETURN_THRESHOLDS, ".2%"),
    "Bench": (_CALENDAR_RETURN_THRESHOLDS, ".2%"),
    "Excess": (_CALENDAR_RETURN_THRESHOLDS, ".2%"),
    "Vol": (None, ".2%"),
    "Sharpe": (_SHARPE_HEAT_THRESHOLDS, ".2f"),
    "Bench Sharpe": (_SHARPE_HEAT_THRESHOLDS, ".2f"),
    "Beta": (_CALENDAR_BETA_THRESHOLDS, ".2f"),
    "Correlation": (_CALENDAR_CORR_THRESHOLDS, ".2f"),
}
# Empty (NaN) calendar cells render as the shared dash rather than "NaN".
_CALENDAR_MISSING: str = _MISSING_DASH


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
    """Renderers for the calendar grid, keyed by `kind`. Month cells use a
    diverging ramp whose band/format match the kind (returns ".2%" for absolute /
    outperformance, ratios ".2f" for vol-adjusted, beta / correlation ".2f"). The
    trailing summary columns each take their own renderer from
    `_CALENDAR_SUMMARY_SPECS` (e.g. Return as a ".2%" ramp, Sharpe on the Sharpe
    band, Vol plain). Empty cells display ``-`` (`_CALENDAR_MISSING`) via the
    renderers' numeric-preserving `text_value`."""
    if kind == "vol_adjusted":
        month_thr, month_fmt = _CALENDAR_VOLADJ_THRESHOLDS, ".2f"
    elif kind == "beta":
        month_thr, month_fmt = _CALENDAR_BETA_THRESHOLDS, ".2f"
    elif kind == "correlation":
        month_thr, month_fmt = _CALENDAR_CORR_THRESHOLDS, ".2f"
    else:  # absolute / outperformance
        month_thr, month_fmt = _CALENDAR_RETURN_THRESHOLDS, ".2%"
    month_r = _diverging_bg_renderer(
        month_thr, fmt=month_fmt, missing=_CALENDAR_MISSING
    )
    renderers: dict = {}
    for col in columns:
        spec = _CALENDAR_SUMMARY_SPECS.get(col)
        if spec is None:  # a month cell (Jan…Dec)
            renderers[col] = month_r
            continue
        thresholds, fmt = spec
        renderers[col] = (
            _plain_num_renderer(fmt, missing=_CALENDAR_MISSING)
            if thresholds is None
            else _diverging_bg_renderer(thresholds, fmt=fmt, missing=_CALENDAR_MISSING)
        )
    return renderers


def _update_calendar_grid(grid: DataGrid, table: pd.DataFrame, *, kind: str) -> None:
    """Render a `calendar_return_table` frame (years × Jan…Dec + the kind's
    summary columns) into the calendar DataGrid, oldest year on top, with
    diverging conditional formatting keyed to `kind`."""
    if table is None or table.empty:
        grid.data = pd.DataFrame()
        _reassert_dark_theme(grid)
        return
    display = table.sort_index(ascending=True)
    display.index = display.index.astype(int).astype(str)
    display.index.name = ""
    grid.data = display
    grid.renderers = _calendar_renderers(display.columns, kind=kind)
    _reassert_dark_theme(grid)


def _universe_grid() -> DataGrid:
    grid = DataGrid(
        pd.DataFrame(),
        base_row_size=28,
        base_column_size=_STAT_COL_WIDTH,  # uniform stat cols; per-col widths
        base_column_header_size=26,  # single-row header (flat, single-index)
        base_row_header_size=110,  # re-fit to the ticker content per update
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

    Column order is Info → Z-Score (when supplied) → 1Y → 3Y → 5Y, as flat
    single-index labels ("1Y Return", …). When a `zcol` (per-ticker z-score
    Series) + `zlabel` are given, a `"Z-Score <zlabel>"` column is inserted
    right after the Info block — it's the headline ranking column, so it sits
    next to the names — and the whole frame is sorted by it descending
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

    blocks = [info]
    z_key: str | None = None
    if zcol is not None and zlabel is not None:
        z_key = f"{ZSCORE_SUPERCOL} {zlabel}"
        blocks.append(pd.DataFrame({z_key: zcol.reindex(info.index)}))

    if not up.empty:
        # Flatten the (period, metric) columns to single-index "1Y Return".
        period_order = ["1Y", "3Y", "5Y"]
        present = [p for p in period_order if p in up.columns.get_level_values(0)]
        up_norm = up.reindex(columns=present, level=0).reindex(info.index)
        up_norm.columns = _flatten_perf_columns(up_norm.columns)
        blocks.append(up_norm)

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
    _apply_grid_styling(grid, combined, sharpe_heatmap=True)
    _reassert_dark_theme(grid)
