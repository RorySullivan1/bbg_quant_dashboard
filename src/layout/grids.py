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

A column's *kind* is read off its name — `" Sharpe"`, `" Return"` — because
those suffixes are built by `_flatten_perf_columns` from a fixed metric set and
cannot drift. The catalog's **ranking column is the exception**: its header is
free text, so it is passed down as `zscore_col`, the key `_build_universe_frame`
returned along with the frame (v0.9.23 #323). Recognising it by prefix instead
made a relabel silently cost it its ramp, its width, its number renderer and
its filter's units — four wrong-looking columns and no error anywhere.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import ipywidgets as W
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer, VegaExpr
from itables import JavascriptFunction
from itables.widget import ITable

from ..config import (
    CATALOG_GRID_FIELDS,
    LOOKBACK_YEARS,
    PERF_GRID_FIELDS,
    field_label,
    stat_windows,
    universe_grid_default_window,
    universe_grid_group_fields,
)
from ..style import ANALYTICS_HEIGHT, CATALOG_TABLE_HEIGHT, Color
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
        info_block = _build_info_block(meta, pt.index, PERF_GRID_FIELDS)
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
# The stat columns whose stored value is a fraction and whose rendered value is
# a percentage. Read by both the catalog renderer and the numeric filter, so a
# column cannot be rendered as a percentage and filtered as a fraction — which
# would answer ">1" on a Return column with every row in the catalog.
_PERCENT_SUFFIXES: tuple[str, ...] = (" Return", " Vol", " Max DD")


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


def _is_percent_col(name: str) -> bool:
    return name.endswith(_PERCENT_SUFFIXES)


def _flatten_perf_columns(columns: pd.Index) -> list[str]:
    """Flatten (period, metric) column tuples to single-index labels, e.g.
    ``("1Y", "Return") -> "1Y Return"``. Non-tuple names pass through."""
    return [
        " ".join(str(p) for p in c) if isinstance(c, tuple) else str(c) for c in columns
    ]


def _perf_column_widths(
    frame: pd.DataFrame, *, zscore_col: str | None = None
) -> dict[str, int]:
    """Per-column pixel widths for a flat perf / catalog grid: a tiny color
    swatch, uniform stat columns, and content-fit descriptive / z-score
    columns (fit to the header + the actual cell strings).

    `zscore_col` is the ranking column's name as the frame's builder spelled
    it, not something to recognise — see `_catalog_table_options`."""
    widths: dict[str, int] = {}
    for col in frame.columns:
        name = str(col)
        if name == PERF_COLOR_COLUMN_NAME:
            widths[name] = _COLOR_COL_WIDTH
        elif name == zscore_col:
            widths[name] = _content_px(name, frame[col].tolist())
        elif _is_stat_col(name):
            widths[name] = _STAT_COL_WIDTH
        else:
            widths[name] = _content_px(name, frame[col].tolist())
    return widths


# The words the ranking column's name is built from (see
# `zscore_column_name`), and the diverging-heatmap thresholds for the
# conditional-formatted columns.
#
# The name is *built* here; nothing reads it back off a header to decide what a
# column is. That distinction is the whole of #323 — the renderers, the widths,
# the filter kinds and the column defs are handed the key the builder returned.
ZSCORE_SUPERCOL: str = "Z-Score"
ZSCORE_COLUMN_PREFIX: str = "Normalized"
# Sharpe leaves: neutral band straddles ~0–0.5, red below, green above.
_SHARPE_HEAT_THRESHOLDS: tuple[float, float, float, float] = (-0.5, 0.0, 0.5, 1.0)
# Z-Score column: already centered at 0, so the bands are symmetric.
_ZSCORE_HEAT_THRESHOLDS: tuple[float, float, float, float] = (-1.5, -0.5, 0.5, 1.5)


def zscore_column_name(metric_label: str, window_label: str) -> str:
    """The ranking column's header, e.g. `Normalized 1Y Sharpe (5Y Z-Score)`.

    Four facts in the order a reader needs them: that the number is
    standardized, over what window it was measured, which metric it is, and
    what it was standardized against. It replaced `Z-Score Sharpe 1M/1Y`
    (#324), which compressed a window *over a lookback* into a notation nobody
    reads off a screen — and whose lookback was a control the user could move,
    so the same column meant three things.

    The `5Y` is `LOOKBACK_YEARS`, not a literal, for the reason the
    Leaderboard's title note is (#309): the sample and the number naming it
    must not be free to drift apart.

    Built in one place and never parsed back — `_window_of` has to keep
    returning None for this string even though a window label sits inside it,
    and every consumer that cares which column this is receives the name
    rather than recognising it (#323).
    """
    return (
        f"{ZSCORE_COLUMN_PREFIX} {window_label} {metric_label} "
        f"({LOOKBACK_YEARS}Y {ZSCORE_SUPERCOL})"
    )


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


def _perf_renderers(
    columns: pd.Index,
    *,
    sharpe_heatmap: bool = False,
    zscore_col: str | None = None,
) -> dict:
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
        # Z-Score first: its name ends in " Sharpe" whenever Sharpe is the
        # metric being ranked, so it must win over the Sharpe branch below.
        if name == zscore_col:
            renderers[col] = zscore_renderer
        elif name == PERF_COLOR_COLUMN_NAME:
            renderers[col] = color_swatch
        elif name.endswith(" Sharpe"):
            renderers[col] = sharpe_renderer
        elif _is_percent_col(name):
            renderers[col] = pct
        else:
            renderers[col] = text
    return renderers


def _apply_grid_styling(
    grid: DataGrid,
    frame: pd.DataFrame,
    *,
    sharpe_heatmap: bool = False,
    zscore_col: str | None = None,
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
    grid.renderers = _perf_renderers(
        frame.columns, sharpe_heatmap=sharpe_heatmap, zscore_col=zscore_col
    )
    grid.column_widths = _perf_column_widths(frame, zscore_col=zscore_col)
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

#: The dark-table chrome both `ITable`s wear — the catalog's and the chart's
#: points table. Hoisted out of `.bbg-catalog` in #337, which keeps only what
#: is catalog-specific: the group bands and the filter row.
ITABLE_CLASS: str = "bbg-itable"

#: What the catalog table adds on top of that chrome. The itables container's
#: own class is `itables_anywidget` (NOT `itables`), and the stylesheet must
#: outrank DataTables' bundled one — see the `.bbg-itable` block in
#: `app_css.html`.
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


def _catalog_group_labels(selected: tuple[str, ...] | None = None) -> list[str]:
    """Display labels of the fields the catalog groups by, outermost first.

    Read through `universe_grid_group_fields` and `field_label` so both the
    grouping and its headers follow `CATALOG_SCHEMA` — never respelled here,
    and the nesting order is the hierarchy's rather than the order the user
    ticked the boxes.
    """
    return [field_label(key) for key in universe_grid_group_fields(selected)]


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


def _window_of(name: str) -> str | None:
    """The stats window a flat column belongs to, e.g. `"1Y Sharpe"` -> `"1Y"`.

    Returns None for anything that is not a window stat — the Info columns and
    the Z-Score, which the window radio never hides. The Z-Score matters here:
    its label embeds its own window ("Z-Score Sharpe 1M/1Y"), and matching on a
    prefix rather than a substring is what keeps it out of the radio's reach.
    """
    for label, _ in stat_windows():
        if name.startswith(f"{label} "):
            return label
    return None


#: The numeric filter's grammar, as one JS function: `(raw, scale)` in, and a
#: predicate over the column's raw value out — or `null` for an empty box (no
#: filter) and `false` for text that is not a comparison at all. The three are
#: distinct: only the last marks the input.
#:
#: A module constant rather than a fragment inlined into `_js_filter_row`
#: because this is the part of the row with behaviour of its own: the tests run
#: this function in a JS engine and assert what it accepts, which they cannot
#: do to a parser welded into a 60-line DOM callback.
_JS_NUMBER_PREDICATE: str = (
    "function (raw, scale) {"
    # Whitespace, thousands separators and a typed `%` are noise: the percent
    # columns wear a `%`, so "5%" is what someone reading the screen types.
    "  var text = String(raw).replace(/[\\s,%]/g, '');"
    "  if (!text) { return null; }"
    "  var test;"
    "  var range = text.match(/^(-?\\d*\\.?\\d+)\\.\\.(-?\\d*\\.?\\d+)$/);"
    "  if (range) {"
    "    var lo = parseFloat(range[1]);"
    "    var hi = parseFloat(range[2]);"
    "    test = function (v) { return v >= lo && v <= hi; };"
    "  } else {"
    "    var parts = text.match(/^(>=|<=|>|<|=)?(-?\\d*\\.?\\d+)$/);"
    "    if (!parts) { return false; }"
    "    var n = parseFloat(parts[2]);"
    "    var op = parts[1];"
    "    if (op === '>') { test = function (v) { return v > n; }; }"
    "    else if (op === '>=') { test = function (v) { return v >= n; }; }"
    "    else if (op === '<') { test = function (v) { return v < n; }; }"
    "    else if (op === '<=') { test = function (v) { return v <= n; }; }"
    "    else {"
    # A bare number (or an explicit `=`) matches at the precision typed: "1.2"
    # is every value that rounds to 1.2, not the one that is exactly 1.2.
    # Anything tighter, over a column rendered to two decimals, is a box that
    # answers most of what is on screen with nothing.
    "      var dot = parts[2].indexOf('.');"
    "      var decimals = dot === -1 ? 0 : parts[2].length - dot - 1;"
    # Inclusive at both ends, and with a hair of slack: the difference at an
    # exact boundary is not exactly the tolerance in binary (|1.15 - 1.2| comes
    # out at 0.050000000000000044), so a strict test drops the very value the
    # band was drawn around. Two adjacent bands overlapping on their shared
    # edge is the cheaper error.
    "      var tolerance = 0.5 * Math.pow(10, -decimals) + 1e-9;"
    "      test = function (v) { return Math.abs(v - n) <= tolerance; };"
    "    }"
    "  }"
    # `scale` is the factor between the stored value and the rendered one, so
    # the comparison happens in the units on screen. An empty cell is not a
    # number and matches no comparison, so the dash rows drop out of a filtered
    # column rather than riding along in it.
    "  return function (value) {"
    "    var v = parseFloat(value);"
    "    if (isNaN(v)) { return false; }"
    "    return test(v * scale);"
    "  };"
    "}"
)


#: What a numeric filter box offers, as its placeholder and its tooltip. The
#: grammar has to be advertised somewhere — nothing about an empty box says it
#: takes ">1" rather than the substring a text column takes — and a stat column
#: is ~70px wide, so the placeholder carries one example and the tooltip the
#: rest. Kept as ASCII with no apostrophes: both are interpolated into a
#: single-quoted JS string literal.
_NUMBER_FILTER_PLACEHOLDER: str = ">0"
_NUMBER_FILTER_HINT: str = "Filter by number: 1.5, >1, <=2, 1..3"
_PERCENT_FILTER_HINT: str = _NUMBER_FILTER_HINT + " (in %, as shown)"


def _filter_kinds(
    frame: pd.DataFrame, groups: list[str], *, zscore_col: str | None = None
) -> dict[int, str]:
    """Which columns get a filter input and of what kind, by position in
    `frame` (#285, widened to the numbers in #297).

    Positions rather than names: the JS matches on `column().index()`, which is
    the *data* index and is stable under sorting, filtering and the hidden
    columns a window switch produces — a name match would have to survive
    DataTables wrapping the title in its own markup.

    Every column that is not a hidden group column gets an input. The Info
    block is `"text"` — a substring match, where "2019" over a launch date is
    useful. The stat and Z-Score columns are `"number"` / `"percent"` instead,
    which is a **comparison** filter rather than a substring one, because a
    substring over these columns would not merely be coarse ("1.2" matching
    1.23, 11.2 and -1.2 alike) but wrong: they render through
    `_js_number_render`, which hands filtering the raw value, so a cell reading
    "5.23%" is searched as "0.0523" and typing what is on screen matches
    nothing at all. `"percent"` is what carries that ×100 to the browser, so
    the units the user types in are the units they can see.

    Group columns get nothing: they are hidden, and come back as row-group
    headers.
    """
    kinds: dict[int, str] = {}
    for position, name in enumerate(str(c) for c in frame.columns):
        if name in groups:
            continue
        if _is_percent_col(name):
            kinds[position] = "percent"
        elif name == zscore_col or _is_stat_col(name):
            kinds[position] = "number"
        else:
            kinds[position] = "text"
    return kinds


def _js_filter_row(kinds: dict[int, str]) -> JavascriptFunction:
    """A `drawCallback` that builds the per-column filter row, once per table.

    **Why `drawCallback` and not `initComplete`.** The itables widget
    destructures `initComplete` out of the options and calls it *only* from
    inside its own wrapper, which it installs only when `column_filters` or
    `text_in_header_can_be_selected` is set — so a bare `initComplete` is
    dropped without a word. `drawCallback` is a documented itables option and
    lands in the options the widget forwards to DataTables untouched.

    **Why not itables' own `column_filters="header"`.** In this build it does
    not create inputs at all: its wrapper only *wires* inputs it finds
    (`$("input", this.header())`), and it replaces the header markup with a
    flat `<thead><th>…</th></thead>` — no `<tr>`, and no labels. It costs the
    header row to gain nothing.

    **Why the state lives in the browser.** Any options change destroys and
    rebuilds the whole DataTable (`ITable.update` writes `_dt_args`; the widget
    does `destroy()` then `new`), and only `selected_rows` is re-sent across
    that. Typed filter text never reaches the kernel — there is no traitlet
    carrying it — so `UniverseGrid` cannot hold it. It is stashed on `window`,
    keyed by table id and column index, and re-applied here after every
    rebuild. That is what makes a window switch preserve the filters.

    The row is appended **after** DataTables has parsed the header and bound
    its sort listeners, so its cells cannot receive them: sorting stays on the
    label row and clicking into an input cannot re-sort. (`orderCellsTop`, the
    documented answer when both rows exist at init, is therefore not needed —
    and is not a documented itables option, so passing it warns.)

    **Why the cells are `td` and not `th`.** This is what made the first cut of
    the row render blank. itables leaves `text_in_header_can_be_selected` on by
    default, and the wrapper that option installs walks `$("thead th", …)` in
    `initComplete` — which runs *after* the first draw, so after this callback
    — and calls `.empty()` on every cell whose `span.dt-column-title` is
    missing or blank. Our cells carry an input and no title, so it read them as
    stray header cells and emptied all of them: the `<tr>` survived with the
    right number of cells and not one input inside it, which looks exactly like
    a callback that never ran. A `td` is outside that selector's reach, and the
    row is a strip of controls rather than a row of column headings, so it is
    also the truer element. (Turning the option off would work too, but it
    would trade the filters for header-text selection and move sorting onto the
    whole label cell — a change to the header this issue never asked for.)

    The guard below counts inputs rather than testing for the row, so if a
    future version of that pass empties them anyway the next draw rebuilds
    them, instead of the row sitting there blank forever.

    **How a numeric column filters (#297).** Not by `column.search()`, which is
    a substring over the raw value and so is answered in fractions for the
    percent columns. It is `column.search.fixed()`, DataTables' own registered
    per-column predicate (the same API its ColumnControl extension filters
    numbers with), fed a comparison parsed from what the user typed:
    `>1`, `>=1`, `<2`, `<=2`, `1..3`, or a bare number. A bare number matches
    **at the precision typed** — "1.2" is every value that rounds to 1.2, not
    the one that is exactly 1.2 — because a browse surface asks for the
    neighbourhood of a number and exact float equality over a rendered 2dp
    column is a box that stays empty. Text that parses as neither is not a
    filter of zero rows: it leaves the column unfiltered and marks the input,
    so a half-typed ">" shows everything rather than nothing.

    `search.fixed` is probed rather than assumed. It is in this bundle (and
    pinned by a test), but a future one without it would throw inside this
    callback and take the *text* filters down with it; the probe degrades to
    numeric columns with no input, which is where they were before #297.
    """
    text_cols = sorted(position for position, kind in kinds.items() if kind == "text")
    # Position -> the factor between the stored value and the rendered one, so
    # the browser never has to re-derive which columns are percentages.
    scales = {
        str(position): (100 if kind == "percent" else 1)
        for position, kind in sorted(kinds.items())
        if kind != "text"
    }
    return JavascriptFunction(
        "function (settings) {"
        "  var api = this.api();"
        "  var node = api.table().node();"
        "  var head = node.tHead;"
        "  if (!head) { return; }"
        f"  var textCols = {text_cols!r};"
        f"  var numberCols = {json.dumps(scales)};"
        "  var numberOk = !!(api.columns().search && api.columns().search.fixed);"
        "  var isNumber = function (index) {"
        "    return numberOk && numberCols.hasOwnProperty(index);"
        "  };"
        "  var isFilterable = function (index) {"
        "    return isNumber(index) || textCols.indexOf(index) !== -1;"
        "  };"
        f"  var parse = {_JS_NUMBER_PREDICATE};"
        "  var applyTo = function (column, index, input) {"
        "    if (!isNumber(index)) { column.search(input.value); return; }"
        "    var test = parse(input.value, numberCols[index]);"
        "    input.classList.toggle('bbg-filter-invalid', test === false);"
        # `''` is how DataTables clears a fixed search — the same value its own
        # ColumnControl writes for an empty box.
        "    column.search.fixed('bbg', test ? test : '');"
        "  };"
        "  var expected = 0;"
        "  api.columns(':visible').every(function () {"
        "    if (isFilterable(this.index())) { expected++; }"
        "  });"
        # Built once per table. Every later draw — a filter keystroke, a sort,
        # a regroup — finds the row intact and returns, so a focused input is
        # never torn out from under the user mid-type. A row whose inputs are
        # gone, or that predates a column-visibility change, is rebuilt.
        "  var existing = head.querySelector('tr.bbg-filter-row');"
        "  if (existing) {"
        "    if (existing.querySelectorAll('input.bbg-filter-input').length"
        "        === expected) { return; }"
        "    existing.remove();"
        "  }"
        "  var store = (window.__bbgCatalogFilters = window.__bbgCatalogFilters || {});"
        "  var saved = (store[node.id] = store[node.id] || {});"
        "  var row = document.createElement('tr');"
        "  row.className = 'bbg-filter-row';"
        "  var pending = [];"
        # ':visible' only — an input under a hidden column would be an orphan
        # the user could type into with nothing to filter.
        "  api.columns(':visible').every(function () {"
        "    var cell = document.createElement('td');"
        "    cell.className = 'bbg-filter-cell';"
        "    var index = this.index();"
        "    if (isFilterable(index)) {"
        "      var column = this;"
        "      var input = document.createElement('input');"
        "      input.type = 'search';"
        "      input.className = 'bbg-filter-input';"
        "      input.value = saved[index] || '';"
        "      if (isNumber(index)) {"
        "        input.classList.add('bbg-filter-number');"
        f"        input.placeholder = '{_NUMBER_FILTER_PLACEHOLDER}';"
        f"        input.title = numberCols[index] === 100 ? '{_PERCENT_FILTER_HINT}'"
        f"          : '{_NUMBER_FILTER_HINT}';"
        "      }"
        "      input.addEventListener('click', function (e) { e.stopPropagation(); });"
        "      var applied = input.value;"
        "      var apply = function () {"
        "        saved[index] = input.value;"
        "        if (input.value === applied) { return; }"
        "        applied = input.value;"
        "        applyTo(column, index, input);"
        "        api.draw();"
        "      };"
        # `input` rather than `keyup`: a paste and the clear button of a
        # `type=search` box both change the value without a keystroke. `search`
        # is the clear button's own event; the guard above makes the pair idem-
        # potent when a browser fires both.
        "      input.addEventListener('input', apply);"
        "      input.addEventListener('search', apply);"
        "      cell.appendChild(input);"
        "      if (saved[index]) { pending.push([column, index, input]); }"
        "    }"
        "    row.appendChild(cell);"
        "  });"
        "  head.appendChild(row);"
        # Deferred out of the draw cycle: re-applying inside `drawCallback`
        # would re-enter the draw that is still running.
        "  if (pending.length) {"
        "    setTimeout(function () {"
        "      pending.forEach(function (p) { applyTo(p[0], p[1], p[2]); });"
        "      api.draw();"
        "    }, 0);"
        "  }"
        "}"
    )


def _catalog_table_options(
    frame: pd.DataFrame,
    groups: list[str],
    window: str | None = None,
    *,
    zscore_col: str | None = None,
) -> dict:
    """DataTable options for the catalog: hidden group columns surfaced as
    nested row-group headers, numeric renderers, and the Sharpe / Z-Score heat.

    `rowGroup.dataSrc` and the hidden `targets` are the *same* indices — the
    tiers leave the body and come back as headers, which is the whole point of
    the change. With no group fields both fall away and this is a flat table.

    `window` selects the one stats window that is **visible**. Every other
    window stays in the frame and is hidden here, so changing the radio is a
    column-visibility change rather than a rebuild: the data, the grouping and
    the selected row all survive it, and nothing recomputes. Dropping the
    columns from the frame instead would reset all three, including the
    row-to-ticker map that routes a click (#265).

    `zscore_col` is the ranking column's name **as the frame's builder spelled
    it** (`_build_universe_frame` returns it), not something recognised here.
    It used to be re-derived from the string by a `startswith("Z-Score ")`
    test, with five behaviours hanging off it — this column's width, its
    diverging ramp, its DataTables kind, its number renderer and the units its
    filter compares in. All five failed *silently* on a relabel, which is a
    poor way to hold a header still (#323).
    """
    if window is None:
        window = universe_grid_default_window()
    column_defs: list[dict] = []
    if groups:
        targets = list(range(len(groups)))
        column_defs.append({"targets": targets, "visible": False})
    hidden_windows = [
        position
        for position, name in enumerate(str(c) for c in frame.columns)
        if (w := _window_of(name)) is not None and w != window
    ]
    if hidden_windows:
        column_defs.append({"targets": hidden_windows, "visible": False})
    for position, name in enumerate(str(c) for c in frame.columns):
        if name in groups:
            continue
        if name == zscore_col:
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
        elif _is_percent_col(name):
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
        # The search box goes top-LEFT (#283). DataTables' default puts it at
        # `topEnd`, which is a default rather than a decision: the Platform tab
        # reads from the left rail inwards, so the table's own search was the
        # one piece of its chrome facing the other way. `topEnd` has to be
        # cleared explicitly — the default layout object is merged, so setting
        # `topStart` alone draws the search box twice. `None` → JSON `null` is
        # how a slot is removed; DataTables' own SearchPanes extension clears
        # layout the same way. `paging: False` already empties the two slots
        # below, and `bottomStart` keeps the row-count readout where it is.
        "layout": {
            "topStart": "search",
            "topEnd": None,
            "bottomStart": "info",
            "bottomEnd": None,
        },
        # Read as `sSearch` / `sSearchPlaceholder` — the internal names. The
        # documented camelCase `searchPlaceholder` does not appear anywhere in
        # this bundle's `widget.js`: DataTables translates camelCase options
        # through a fixed map and that key is not in it, so the camelCase form
        # would be dropped silently and the placeholder would never appear.
        # An empty `sSearch` drops the "Search:" label; with the box now
        # leading the table, the placeholder carries the meaning instead.
        "language": {
            "sSearch": "",
            "sSearchPlaceholder": "Search the catalog…",
        },
        # The per-column filter row (#285), built in the browser because the
        # inputs are not part of the frame. See `_js_filter_row` for why this
        # is a `drawCallback` and why the filter text lives on `window`.
        "drawCallback": _js_filter_row(
            _filter_kinds(frame, groups, zscore_col=zscore_col)
        ),
        # itables downsamples a table over ~64KB of JSON, keeping the head and
        # tail and dropping the middle. For a browse surface whose job is to
        # show the whole catalog that is a silent data loss, and the row a user
        # wants is as likely to be in the dropped middle as anywhere. A
        # terminal-sized catalog measures ~31KB, so this is headroom rather
        # than a live fix — but it is the kind of limit that bites after the
        # catalog grows, far from any change that would explain it.
        "maxBytes": 0,
    }
    # Always sent, never omitted. `ITable.update` *merges* options — anything
    # left out keeps its previous value — so dropping `rowGroup` when the user
    # unchecks every box leaves the old `dataSrc` in place, pointing at
    # whatever column 0 has become. That renders one group header per row,
    # each named after a ticker. `False` is how RowGroup is switched off.
    options["rowGroup"] = {"dataSrc": list(range(len(groups)))} if groups else False
    return options


def picked_row(change: dict, size: int) -> int | None:
    """The row position a `selected_rows` change picked, or None for a non-event.

    Two non-events are swallowed deliberately, and both tables that observe
    `selected_rows` need the same treatment — so this is a function rather
    than a rule each of them re-implements.

    A **deselection** arrives as an empty list and must do nothing: clearing
    the panes because the user clicked the selected row again would be worse
    than useless. And a row position **outside the current frame** is reachable
    whenever a re-render lands between the click and the callback, so it is
    guarded rather than left to raise inside traitlets, where the exception
    surfaces as a dead widget rather than as an error anyone can act on.
    """
    rows = change.get("new") or []
    if not rows:
        return None
    row = rows[0]
    return row if 0 <= row < size else None


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
        #: The stats window currently shown, and the fields currently grouped.
        #: Held on the object per the v0.9.16 object model — both are state, not
        #: something a caller threads through every `update`.
        self.window: str = universe_grid_default_window()
        self.group_fields: tuple[str, ...] = universe_grid_group_fields()
        self.widget = ITable(
            pd.DataFrame(), **_catalog_table_options(pd.DataFrame(), [])
        )
        self.widget.add_class(ITABLE_CLASS)
        self.widget.add_class(CATALOG_TABLE_CLASS)
        # Full width since #326, where the rail beside it was removed: the
        # table is a child of the Platform column now, not of a row it had to
        # share. The `flex: 1 1 0%` that gave it the remaining width went with
        # the rail — in a *column* that basis applies to the height, so it
        # would fight the fixed box below rather than do nothing.
        #
        # `min_width` stays. With no sibling to push off it is no longer what
        # keeps a wide column set inside the table — the `.dt-layout-cell`
        # scroll does that — but it is the guard that made the row work, and
        # putting the table back in a row without it is how #280 happened.
        #
        # The height is fixed (#298) and the internals fill it: the search row
        # and the row-count readout take what they need and the row area
        # scrolls in the remainder. See the `.bbg-catalog` flex rules in
        # app_css.html.
        self.widget.layout = W.Layout(
            width="100%",
            min_width="0",
            height=CATALOG_TABLE_HEIGHT,
        )
        #: Row position -> ticker for the frame currently rendered. The widget
        #: reports a clicked row by position, and the grid is the only object
        #: that knows which ticker that was, so the translation lives here
        #: rather than at the handler's call site.
        self._tickers: tuple[str, ...] = ()
        #: The frame as last handed to the widget, kept so a period toggle can
        #: re-send options without rebuilding it.
        self._display: pd.DataFrame | None = None
        self._groups: list[str] = []
        #: The ranking column's name in the frame currently rendered, as
        #: `_build_universe_frame` spelled it — the grid is told, it never
        #: reads it back off the header (#323).
        self._zscore_col: str | None = None
        self._on_pick = on_pick
        self.widget.observe(self._forward_pick, names="selected_rows")

    def _forward_pick(self, change: dict) -> None:
        """Translate a clicked row into a ticker and hand it to `on_pick`."""
        picked = picked_row(change, len(self._tickers))
        if picked is None or self._on_pick is None:
            return
        self._on_pick(self._tickers[picked])

    def update(
        self,
        meta: pd.DataFrame,
        up: pd.DataFrame,
        *,
        zcol: pd.Series | None = None,
        zname: str | None = None,
    ) -> None:
        combined, zscore_col = _build_universe_frame(
            meta, up, zcol=zcol, zname=zname, group_fields=self.group_fields
        )
        self._set_data(combined, zscore_col=zscore_col)

    def _set_data(self, frame: pd.DataFrame, *, zscore_col: str | None = None) -> None:
        """The single write path. Options are rebuilt on every write because
        they are keyed to column *positions*, and the Z-Score column's name —
        and so the column set — changes with the ranking controls."""
        # Recorded from the index before `_catalog_display_frame` moves the
        # ticker into a column: that function reorders columns only, so row
        # positions line up with the frame the widget is about to render.
        self._tickers = tuple(str(t) for t in frame.index)
        self._zscore_col = zscore_col
        self._display, self._groups = _catalog_display_frame(
            frame, _catalog_group_labels(self.group_fields)
        )
        self.widget.update(self._display, **self.table_options())

    def table_options(self) -> dict:
        """The DataTable options for the frame currently rendered.

        The three things the options are keyed to — the group columns, the
        visible window and the ranking column's name — are all held here, so
        reading them together is this method rather than three attribute reads
        repeated at each call site (there are two: a write, and a window
        switch that re-sends options with no data)."""
        return _catalog_table_options(
            self._display if self._display is not None else pd.DataFrame(),
            self._groups,
            self.window,
            zscore_col=self._zscore_col,
        )

    def set_window(self, window: str) -> None:
        """Record which stats window is visible. **The caller re-renders.**

        A sibling of `set_group_fields`, and for the same reason. Until #324
        this *was* the window change: the options were re-sent with no
        dataframe, so DataTables only toggled column visibility, and the
        grouping and the selected row both survived it. The window now also
        measures the Z-Score, so a change renames the ranking column and
        re-sorts the frame — including the per-level group ranks, which are
        taken from it — and the table is rebuilt either way. Re-sending options
        here as well would be a discarded round trip through the browser.

        What has *not* changed is the performance columns: every window is
        still computed once, up front, and `_catalog_table_options` still hides
        the ones not on show rather than dropping them. It is the frame that is
        rebuilt, not the statistics.
        """
        self.window = window

    def set_group_fields(self, fields: tuple[str, ...]) -> None:
        """Change which fields the grid groups by.

        Unlike the window, this **does** rebuild: the grouping decides the row
        order, because RowGroup only gathers consecutive rows. The caller has
        to re-`update` with the data afterwards — there is no way to regroup
        without reordering, and no way to reorder without rebuilding.
        """
        self.group_fields = universe_grid_group_fields(fields)

    def clear(self) -> None:
        self._set_data(pd.DataFrame())


def _build_universe_frame(
    meta: pd.DataFrame,
    up: pd.DataFrame,
    *,
    zcol: pd.Series | None = None,
    zname: str | None = None,
    group_fields: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """Assemble the all-catalog grid's DataFrame (pure — no grid side effects),
    **and the name of the ranking column it inserted** (None when it did not).

    Column order is Info → the ranking column (when supplied) → 1Y → 3Y → 5Y,
    as flat single-index labels ("1Y Return", …). When a `zcol` (per-ticker
    z-score Series) + `zname` are given, a column called exactly `zname` is
    inserted right after the Info block — it's the headline ranking column, so
    it sits next to the names — and the whole frame is sorted by it descending
    (insufficient-history tickers, NaN z, sink to the bottom).

    `zname` is the **whole** header, built by `zscore_column_name`. It was a
    suffix under a fixed `"Z-Score "` stem until #324; the parameter was
    renamed with the meaning so a caller passing the old thing gets an error
    rather than a column called `Normalized Normalized 1Y Sharpe …`.

    The key travels back with the frame rather than being re-derived from the
    column names downstream: this function is the only place that decides both
    *whether* there is a ranking column and *what it is called*, and a
    consumer re-deciding either from the string gets it wrong the moment the
    header is relabelled (#323)."""
    if meta.empty:
        return pd.DataFrame(), None
    info = _build_info_block(meta, None, CATALOG_GRID_FIELDS, date_cols=("live_date",))

    blocks = [info]
    z_key: str | None = None
    if zcol is not None and zname is not None:
        z_key = zname
        blocks.append(pd.DataFrame({z_key: zcol.reindex(info.index)}))

    if not up.empty:
        # Flatten the (window, metric) columns to single-index "1Y Return".
        # Every window stays in the frame even when it is not the one on show —
        # see `_catalog_table_options`, which hides the others rather than
        # dropping them, so the radio can switch without a recompute.
        available = up.columns.get_level_values(0)
        present = [label for label, _ in stat_windows() if label in available]
        up_norm = up.reindex(columns=present, level=0).reindex(info.index)
        up_norm.columns = _flatten_perf_columns(up_norm.columns)
        blocks.append(up_norm)

    combined = pd.concat(blocks, axis=1) if len(blocks) > 1 else info
    combined = _group_ordered(combined, _catalog_group_labels(group_fields), z_key)
    combined.index.name = "Ticker"
    return combined, z_key


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


def _points_table_options(frame: pd.DataFrame, fmt: str) -> dict:
    """DataTable options for the chart's points table.

    Shares `_catalog_table_options`' renderer helpers and nothing else. The
    catalog's table is grouped, searched and filtered because it is the thing
    the user browses; this one *reports* whatever the chart beside it drew, so
    a search box that could hide a point the chart still shows would be a way
    for the two to disagree.
    """
    value_column = len(frame.columns) - 1
    return {
        "columnDefs": [
            {
                "targets": [value_column],
                "render": _js_number_render(percent=fmt.endswith("%")),
                "className": "dt-body-right",
            }
        ],
        # Sorted by the frame, not by DataTables: the order is part of what the
        # chart handed over, and re-sorting here would let the table disagree
        # with the legend's reading order.
        "order": [],
        "paging": False,
        # Slots cleared through `layout`, not through `searching` / `info`:
        # this bundle's ITable does not carry those two options and warns that
        # it is passing them through undocumented. `None` → JSON `null` is how
        # a slot is removed, the way `_catalog_table_options` clears `topEnd`.
        #
        # There is no search box and no row-count readout because this table
        # *reports* what the chart beside it drew: a filter that could hide a
        # point the chart still shows would be a way for the two to disagree.
        "layout": {
            "topStart": None,
            "topEnd": None,
            "bottomStart": None,
            "bottomEnd": None,
        },
        "select": {"style": "single"},
        # NO `scrollY`, for the reason spelled out above `_catalog_table_options`:
        # it renders the header in a second table and sizes the two once, at
        # init, so they drift apart when the container settles. This table
        # scrolls the same way the catalog does — in CSS, through the
        # `.bbg-itable` flex chain, which it wears.
        "autoWidth": True,
    }


class ChartPointsGrid:
    """The active chart's own points, as a table beside it.

    Hover was the only way to read a value — one point at a time, with no way
    to sort and no path from a point to the strategy it stands for. This is
    that path: the table shows whatever `points()` the visible chart drew, and
    a click on a row goes where a click on the marker would (#331 dec. 6, 19).

    A sibling of `UniverseGrid` rather than a subclass: they share an `ITable`,
    the numeric renderers and the dark chrome, but nothing of the grouping,
    the filter row or the window-visibility machinery that makes the catalog
    table what it is.
    """

    def __init__(self, on_pick: Callable[[pd.Series], None] | None = None) -> None:
        self.widget = ITable(
            pd.DataFrame(), **_points_table_options(pd.DataFrame(), "")
        )
        self.widget.add_class(ITABLE_CLASS)
        self.widget.layout = W.Layout(
            width="100%", min_width="0", height=ANALYTICS_HEIGHT
        )
        #: The rows as last rendered, so a click can be answered with the whole
        #: row — its path and its count — rather than just a label.
        self._rows: pd.DataFrame = pd.DataFrame()
        self._on_pick = on_pick
        self.widget.observe(self._forward_pick, names="selected_rows")

    def _forward_pick(self, change: dict) -> None:
        picked = picked_row(change, len(self._rows))
        if picked is None or self._on_pick is None:
            return
        self._on_pick(self._rows.iloc[picked])

    def update(
        self,
        points: pd.DataFrame,
        *,
        level_label: str,
        value_label: str,
        fmt: str,
    ) -> None:
        """Render `points` as `<level_label>` · Name · `<value_label>`.

        A **Count** column appears only when some row stands for more than one
        strategy: at the leaf level every row is one strategy, and a column of
        1s would be noise. Sorted by value descending with NaN last, so a
        strategy with no history sinks rather than topping the table.
        """
        if points.empty:
            self.clear()
            return
        self._rows = points.sort_values("value", ascending=False, na_position="last")
        display = pd.DataFrame(
            {
                level_label: [str(v) for v in self._rows["label"]],
                "Name": [str(v) for v in self._rows["name"]],
            }
        )
        if (self._rows["count"] > 1).any():
            display["Count"] = self._rows["count"].to_numpy()
        display[value_label] = self._rows["value"].to_numpy()
        self.widget.update(display, **_points_table_options(display, fmt))

    def clear(self) -> None:
        self._rows = pd.DataFrame()
        self.widget.update(pd.DataFrame(), **_points_table_options(pd.DataFrame(), ""))
