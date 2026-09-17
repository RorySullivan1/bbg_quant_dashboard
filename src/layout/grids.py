"""Table construction, theming, and formatting.

Every table in the app is built here. Two stacks coexist deliberately. The
selected-strategy perf grids, the Single Strategy monthly-return calendar and
the return-distribution stats table are `ipydatagrid` ``DataGrid``s. The
all-catalog grid is an `itables` ``ITable`` (v0.9.18 #263), because only
DataTables renders the classification tiers as nested **row groups** rather
than as three columns repeating the same strings on every row. Converging the
other two is a separate decision, deliberately not taken here.

Three concerns recur. **Theming** — `_dark_grid_style` / `_dark_grid_kwargs`
express the dark chrome purely in `style.py` tokens, and `_reassert_dark_theme`
reapplies them after a data swap, which otherwise resets the frontend's style.
**Sizing** — perf-grid column widths are computed in Python (see
`_perf_column_widths`) rather than by the frontend's autofit. **Formatting** —
renderers centre numeric cells, show missing values as a dash, and apply the
diverging red→green background to the Sharpe and Z-Score columns.
"""

from __future__ import annotations

from collections.abc import Callable

import ipywidgets as W
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer, VegaExpr
from itables import JavascriptFunction
from itables.widget import ITable

from ..config import (
    SELECTED_GRID_FIELDS,
    UNIVERSE_GRID_FIELDS,
    field_label,
    universe_grid_group_fields,
)
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


class _Grid:
    """One `DataGrid` and the code that refills it.

    The subclass's `update` is the **only** place `grid.data` is assigned, and
    `_set_data` re-asserts the dark theme on every assignment. That is the whole
    point of these classes: the v0.6.5 theme-refresh invariant used to live in
    each caller's memory — every `_update_*_grid` had to remember a trailing
    `_reassert_dark_theme(grid)`, and a new grid or a new update path silently
    reverted to ipydatagrid's white background if its author forgot. Here it is
    structural.
    """

    def __init__(self, **kwargs) -> None:
        self.grid = DataGrid(pd.DataFrame(), **_dark_grid_kwargs(), **kwargs)
        self.grid.add_class("bbg-grid")

    def _set_data(
        self,
        frame: pd.DataFrame,
        renderers: dict | None = None,
        style: Callable[[pd.DataFrame], None] | None = None,
    ) -> None:
        """Assign `frame`, apply any styling, then restore the dark theme.

        Every write goes through here, and the theme is re-asserted **last** —
        `style` rewrites `renderers` / `column_widths`, so re-asserting before it
        would leave the frontend holding the pre-style model.
        """
        self.grid.data = frame
        if renderers is not None:
            self.grid.renderers = renderers
        if style is not None:
            style(frame)
        _reassert_dark_theme(self.grid)


class PerfGrid(_Grid):
    """The per-strategy performance grid — an Info block (color swatch, name,
    classification) beside the flat 1Y/3Y/5Y stat columns.

    Backs both the Multi-Strategy selected-set grid and the Single Strategy
    per-strategy grid.
    """

    def __init__(self) -> None:
        super().__init__(
            base_row_size=28,
            base_column_size=_STAT_COL_WIDTH,  # uniform stat cols; per-col widths
            base_column_header_size=26,  # single-row header (flat, single-index)
            base_row_header_size=110,  # re-fit to the ticker content per update
            layout=W.Layout(width="100%", height="240px"),
        )

    def update(self, pt: pd.DataFrame, meta: pd.DataFrame) -> None:
        if pt.empty:
            self.clear()
            return
        info_block = _build_info_block(meta, pt.index, UNIVERSE_GRID_FIELDS)
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
        self._set_data(combined, style=self._style)

    def _style(self, frame: pd.DataFrame) -> None:
        _apply_grid_styling(self.grid, frame, sharpe_heatmap=True)

    def clear(self) -> None:
        self._set_data(pd.DataFrame())


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


def _build_info_block(
    meta: pd.DataFrame,
    tickers: pd.Index | None,
    fields: tuple[str, ...],
    *,
    date_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Build a grid 'Info' block from metadata: index by ticker, optionally
    `reindex` to `tickers` (selected-set order), select `fields`, ISO-format any
    `date_cols`, then head each column with its schema label.

    Headers are `field_label` reads, so a relabelled column follows from the
    schema rather than from a rename map spelled at each call site."""
    info = meta.set_index("ticker")
    if tickers is not None:
        info = info.reindex(tickers)
    info = info[list(fields)].copy()
    for col in date_cols:
        info[col] = info[col].dt.strftime("%Y-%m-%d")
    return info.rename(columns={key: field_label(key) for key in fields})


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
    ticker row-header. Shared by the selected-strategy and single-strategy perf
    grids; `sharpe_heatmap` opts into the diverging Sharpe / Z-Score ramp.

    The all-catalog grid no longer comes through here — it is an `ITable` and
    expresses the same ramp as a DataTables `createdCell` (`_js_heat_cell`).
    The two must stay visually identical, so they read their bands from the
    same `_SHARPE_HEAT_THRESHOLDS` / `_ZSCORE_HEAT_THRESHOLDS` tuples."""
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


class CalendarGrid(_Grid):
    """The Single Strategy monthly-return calendar — years x Jan…Dec plus the
    summary columns for the active `kind`."""

    def __init__(self) -> None:
        super().__init__(
            base_row_size=26,
            base_column_size=62,
            base_row_header_size=54,
            layout=W.Layout(width="100%", height="260px"),
        )

    def update(self, table: pd.DataFrame, *, kind: str) -> None:
        """Render a `calendar_return_table` frame (years x Jan…Dec + the kind's
        summary columns), oldest year on top, with diverging conditional
        formatting keyed to `kind`."""
        if table is None or table.empty:
            self.clear()
            return
        display = table.sort_index(ascending=True)
        display.index = display.index.astype(int).astype(str)
        display.index.name = ""
        self._set_data(display, _calendar_renderers(display.columns, kind=kind))

    def clear(self) -> None:
        self._set_data(pd.DataFrame())


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


# --- the all-catalog grid (itables / DataTables) -----------------------------
#
# This table is the one place the app leaves ipydatagrid. The reason is row
# grouping: the three classification tiers are a hierarchy, and rendering them
# as three body columns spends ~414px repeating the same strings on every row.
# DataTables' RowGroup draws them as nested headers instead. ipydatagrid's
# merged row headers were evaluated for the same job and render incorrectly in
# 1.4.0 (#255), which is why two table stacks coexist.

#: The class the dark-chrome CSS hangs off. The itables container's own class
#: is `itables_anywidget` (NOT `itables`), and the stylesheet must outrank
#: DataTables' bundled one — see the `.bbg-catalog` block in `app_css.html`.
CATALOG_TABLE_CLASS: str = "bbg-catalog"

# The catalog scrolls rather than pages, but that scrolling is done in CSS
# (`.bbg-catalog` in `app_css.html`), NOT by DataTables' `scrollY`.
#
# `scrollY` puts the header in its own table and sizes both tables once, at
# init. Anything that changes the metrics afterwards — the container settling
# to its real width, or this app's own `!important` font rules landing after
# DataTables measured — leaves the two at different widths, and the header sits
# off its columns until a redraw snaps it back. On a BQuant terminal that
# showed as headers that needed one click to jump into place. Measured here at
# a 169px drift across an 18-column table, which a redraw did not always clear.
#
# A CSS-scrolled container keeps header and body in **one** table, so there is
# nothing to drift: measured at a 0px offset, including after a resize.


def _catalog_group_labels() -> list[str]:
    """Display labels of the fields the catalog groups by, outermost first.

    Read through `universe_grid_group_fields` and `field_label` so both the
    grouping and its headers follow `CATALOG_SCHEMA` — never respelled here.
    """
    return [field_label(key) for key in universe_grid_group_fields()]


def _js_number_render(*, percent: bool) -> JavascriptFunction:
    """A DataTables column renderer that formats only the *display* value.

    Returning the raw number for every non-display request is what keeps
    sorting and filtering numeric: DataTables asks for `type === 'sort'`
    separately, and a column that answered "12.34%" there would sort
    lexically. Empty cells show the same dash as the ipydatagrid grids.
    """
    body = "(data * 100).toFixed(2) + '%'" if percent else "Number(data).toFixed(2)"
    return JavascriptFunction(
        "function (data, type) {"
        "  if (type !== 'display') { return data; }"
        f"  if (data === null || data === '' || isNaN(data)) {{ return '{_MISSING_DASH}'; }}"
        f"  return {body};"
        "}"
    )


def _js_heat_cell(thresholds: tuple[float, float, float, float]) -> JavascriptFunction:
    """A `createdCell` callback painting the diverging red→green ramp.

    The same four-band scheme as `_diverging_bg_renderer`, which the
    ipydatagrid grids use — the ramps have to read identically across the two
    stacks. Empty cells and the neutral middle band set no background at all,
    so the CSS zebra stripe shows through rather than being overpainted.

    The band **must** be written with `setProperty(..., 'important')`, not
    `td.style.backgroundColor = …`. The dark chrome themes body cells with an
    `!important` background (it has to, to outrank DataTables' bundled
    stylesheet), and an `!important` author rule beats an ordinary inline
    style. Assigning the property the plain way computes the whole ramp
    correctly and then renders none of it — the cells carry the colour in
    their inline style and still paint flat navy.
    """
    t0, t1, t2, t3 = thresholds
    return JavascriptFunction(
        "function (td, cellData) {"
        "  var bg = '';"
        "  if (cellData !== null && cellData !== '' && !isNaN(cellData)) {"
        f"    if (cellData < {t0}) {{ bg = '{Color.HEAT_NEG_STRONG}'; }}"
        f"    else if (cellData < {t1}) {{ bg = '{Color.HEAT_NEG_SOFT}'; }}"
        f"    else if (cellData < {t2}) {{ bg = ''; }}"
        f"    else if (cellData < {t3}) {{ bg = '{Color.HEAT_POS_SOFT}'; }}"
        f"    else {{ bg = '{Color.HEAT_POS_STRONG}'; }}"
        "  }"
        "  if (bg) { td.style.setProperty('background-color', bg, 'important'); }"
        "  else { td.style.removeProperty('background-color'); }"
        "}"
    )


def _catalog_display_frame(
    frame: pd.DataFrame, group_labels: list[str]
) -> tuple[pd.DataFrame, list[str]]:
    """Reshape the assembled frame for DataTables: group columns first, then
    the ticker, then everything else.

    The ticker moves out of the index because DataTables addresses columns by
    position, and a frame whose group fields lead gives the widget a stable
    `[0 … n-1]` to both hide and group on. Returns the frame and the group
    columns actually present, which is what `()` group fields degrade to.
    """
    if frame.empty:
        return frame, []
    display = frame.reset_index()
    present = [label for label in group_labels if label in display.columns]
    rest = [col for col in display.columns if col not in present]
    return display[[*present, *rest]], present


def _catalog_table_options(frame: pd.DataFrame, groups: list[str]) -> dict:
    """DataTable options for the catalog: hidden group columns surfaced as
    nested row-group headers, numeric renderers, and the Sharpe / Z-Score heat.

    `rowGroup.dataSrc` and the hidden `targets` are the *same* indices — the
    tiers leave the body and come back as headers, which is the whole point of
    the change. With no group fields both fall away and this is a flat table.
    """
    column_defs: list[dict] = []
    if groups:
        targets = list(range(len(groups)))
        column_defs.append({"targets": targets, "visible": False})
    for position, name in enumerate(str(c) for c in frame.columns):
        if name in groups:
            continue
        if _is_zscore_col(name):
            column_defs.append(
                {
                    "targets": [position],
                    "render": _js_number_render(percent=False),
                    "createdCell": _js_heat_cell(_ZSCORE_HEAT_THRESHOLDS),
                }
            )
        elif name.endswith(" Sharpe"):
            column_defs.append(
                {
                    "targets": [position],
                    "render": _js_number_render(percent=False),
                    "createdCell": _js_heat_cell(_SHARPE_HEAT_THRESHOLDS),
                }
            )
        elif name.endswith((" Return", " Vol", " Max DD")):
            column_defs.append(
                {"targets": [position], "render": _js_number_render(percent=True)}
            )
    options: dict = {
        "columnDefs": column_defs,
        "showIndex": False,
        "paging": False,
        # The frame arrives already ordered (see `_group_ordered`); an initial
        # DataTables sort would undo the grouping contiguity it establishes.
        "order": [],
        # One row at a time. Without this the Select extension is inert and
        # `selected_rows` never changes, so the click handler below never runs.
        "select": {"style": "single"},
        # itables downsamples a table over ~64KB of JSON, keeping the head and
        # tail and dropping the middle. For a browse surface whose job is to
        # show the whole catalog that is a silent data loss, and the row a user
        # wants is as likely to be in the dropped middle as anywhere. A
        # terminal-sized catalog measures ~31KB, so this is headroom rather
        # than a live fix — but it is the kind of limit that bites after the
        # catalog grows, far from any change that would explain it.
        "maxBytes": 0,
    }
    if groups:
        options["rowGroup"] = {"dataSrc": list(range(len(groups)))}
    return options


class UniverseGrid:
    """The all-catalog Platform grid — every in-universe index with its
    metadata, 1Y/3Y/5Y performance and the selectable Z-Score column, with the
    classification tiers drawn as nested row-group headers.

    Deliberately not a `_Grid`: that base class exists to make ipydatagrid's
    theme-refresh invariant structural, and this table has no such invariant —
    its chrome is ordinary page CSS, which a data swap cannot reset. It keeps
    `update` / `clear` so its callers do not know the difference.
    """

    def __init__(self, on_pick: Callable[[str], None] | None = None) -> None:
        self.widget = ITable(
            pd.DataFrame(), **_catalog_table_options(pd.DataFrame(), [])
        )
        self.widget.add_class(CATALOG_TABLE_CLASS)
        #: Row position -> ticker for the frame currently rendered. The widget
        #: reports a clicked row by position, and the grid is the only object
        #: that knows which ticker that was, so the translation lives here
        #: rather than at the handler's call site.
        self._tickers: tuple[str, ...] = ()
        self._on_pick = on_pick
        self.widget.observe(self._forward_pick, names="selected_rows")

    def _forward_pick(self, change: dict) -> None:
        """Translate a clicked row into a ticker and hand it to `on_pick`.

        Two non-events are swallowed deliberately. A **deselection** arrives as
        an empty list and must do nothing — clearing the panes because the user
        clicked the selected row again would be worse than useless. And a row
        position **outside the current frame** is reachable whenever a re-render
        lands between the click and this callback, so it is guarded rather than
        left to raise inside traitlets, where the exception would surface as a
        dead widget rather than as an error anyone can act on.
        """
        rows = change.get("new") or []
        if not rows or self._on_pick is None:
            return
        row = rows[0]
        if 0 <= row < len(self._tickers):
            self._on_pick(self._tickers[row])

    def update(
        self,
        meta: pd.DataFrame,
        up: pd.DataFrame,
        *,
        zcol: pd.Series | None = None,
        zlabel: str | None = None,
    ) -> None:
        combined = _build_universe_frame(meta, up, zcol=zcol, zlabel=zlabel)
        self._set_data(combined)

    def _set_data(self, frame: pd.DataFrame) -> None:
        """The single write path. Options are rebuilt on every write because
        they are keyed to column *positions*, and the Z-Score column's name —
        and so the column set — changes with the Metric/Window dropdowns."""
        # Recorded from the index before `_catalog_display_frame` moves the
        # ticker into a column: that function reorders columns only, so row
        # positions line up with the frame the widget is about to render.
        self._tickers = tuple(str(t) for t in frame.index)
        display, groups = _catalog_display_frame(frame, _catalog_group_labels())
        self.widget.update(display, **_catalog_table_options(display, groups))

    def clear(self) -> None:
        self._set_data(pd.DataFrame())


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
    info = _build_info_block(meta, None, SELECTED_GRID_FIELDS, date_cols=("live_date",))

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
    combined = _group_ordered(combined, _catalog_group_labels(), z_key)
    combined.index.name = "Ticker"
    return combined


#: Temporary per-level ranking columns used to order groups; dropped before the
#: frame is returned, so they never reach a renderer.
_GROUP_RANK_PREFIX: str = "_group_rank_"


def _group_ordered(
    frame: pd.DataFrame, group_labels: list[str], z_key: str | None
) -> pd.DataFrame:
    """Order rows so that each group is a single contiguous run at **every**
    level, best group first, best row first within it.

    RowGroup starts a new header whenever the group value changes between
    adjacent rows — it does not gather scattered rows. So contiguity is a
    correctness requirement of the frame, not a presentation nicety: a frame
    sorted by z alone fragments into a header per row.

    Ranking by the *deepest* group is not sufficient either. It makes families
    contiguous while leaving their solutions interleaved, which measured as 17
    top-level headers for 10 categories. Each level therefore gets its own
    rank — a solution is ranked by its best member, a category by its best
    member within that solution, and so on — and the level's own label follows
    each rank as a tiebreaker, so two groups that happen to share a best member
    still cannot interleave.

    With no group fields this degrades to the plain z-descending sort the grid
    had before grouping existed.
    """
    present = [label for label in group_labels if label in frame.columns]
    if not present:
        if z_key is None:
            return frame
        return frame.sort_values(z_key, ascending=False, na_position="last")
    if z_key is None:
        # No ranking column to order groups by, but they must still be
        # contiguous, so fall back to the labels themselves.
        return frame.sort_values(present, na_position="last")

    ranked = frame.copy()
    by: list[str] = []
    ascending: list[bool] = []
    for depth in range(1, len(present) + 1):
        rank_key = f"{_GROUP_RANK_PREFIX}{depth}"
        ranked[rank_key] = ranked.groupby(present[:depth], sort=False)[z_key].transform(
            "max"
        )
        by += [rank_key, present[depth - 1]]
        ascending += [False, True]
    return ranked.sort_values(
        [*by, z_key], ascending=[*ascending, False], na_position="last"
    ).drop(columns=[c for c in ranked.columns if c.startswith(_GROUP_RANK_PREFIX)])
