"""Unit tests for the all-catalog grid data prep (v0.7.0 Workstream A).

`_build_universe_frame` is the pure assembly behind `_update_universe_grid` —
it builds the flat single-index frame, inserts the dynamic z-score column, and
sorts by it — so it's testable without constructing an `ipydatagrid.DataGrid`.
The conditional-format renderer scoping is checked against `_perf_renderers`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.layout.grids import (
    PERF_COLOR_COLUMN_NAME,
    ZSCORE_SUPERCOL,
    _build_universe_frame,
    _calendar_renderers,
    _perf_renderers,
    zscore_column_name,
)

_CAL_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
# Absolute kind's grid columns: months + Return / Vol / Sharpe.
_CAL_COLS = [*_CAL_MONTHS, "Return", "Vol", "Sharpe"]


def test_calendar_renderers_show_dash_for_missing():
    # Every calendar cell renders empty (NaN) months as "-" while keeping the
    # value numeric for the diverging background. The dash is driven by a
    # `text_value` VegaExpr (ipydatagrid's `missing` trait only fires on a strict
    # JSON null, which pandas NaN never serializes to), so assert the expr is
    # wired up and substitutes the dash only for NaN cells.
    renderers = _calendar_renderers(pd.Index(_CAL_COLS), kind="absolute")
    assert set(renderers) == set(_CAL_COLS)
    assert all(r.missing == "-" for r in renderers.values())
    for r in renderers.values():
        assert r.text_value is not None
        assert r.text_value.value == "isNaN(cell.value) ? '-' : ''"


def test_calendar_renderers_format_by_kind():
    # Return kinds format months as %, beta/correlation as plain 2dp.
    pct = _calendar_renderers(pd.Index(_CAL_COLS), kind="absolute")["Jan"]
    beta = _calendar_renderers(pd.Index(_CAL_COLS), kind="beta")["Jan"]
    assert pct.format == ".2%"
    assert beta.format == ".2f"


def test_calendar_summary_column_renderers():
    # Each summary column takes its own renderer: Return as a % diverging ramp,
    # Sharpe on the Sharpe band (2dp), and Vol plain (no diverging background) so
    # its higher-is-not-better axis isn't color-coded good/bad.
    r = _calendar_renderers(pd.Index(_CAL_COLS), kind="absolute")
    assert r["Return"].format == ".2%"
    assert "cell.value <" in _bg_expr(r["Return"])
    assert r["Sharpe"].format == ".2f"
    assert "cell.value <" in _bg_expr(r["Sharpe"])
    # Vol: plain numeric, default (empty) background, but still 2%-formatted + dash.
    assert r["Vol"].format == ".2%"
    assert _bg_expr(r["Vol"]) == ""
    assert r["Vol"].missing == "-"

    # Beta / Correlation single summary columns format as 2dp diverging ramps.
    beta = _calendar_renderers(pd.Index([*_CAL_MONTHS, "Beta"]), kind="beta")["Beta"]
    corr = _calendar_renderers(
        pd.Index([*_CAL_MONTHS, "Correlation"]), kind="correlation"
    )["Correlation"]
    assert beta.format == ".2f" and "cell.value <" in _bg_expr(beta)
    assert corr.format == ".2f" and "cell.value <" in _bg_expr(corr)


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "solution": ["ARP", "ARP", "Smart Beta"],
            "category": ["T1", "T2", "T3"],
            "family": ["X", "Y", "Z"],
            "return_type": ["Total", "Total", "Excess"],
            "live_date": pd.to_datetime(["2010-01-01", "2015-06-01", "2020-03-15"]),
        }
    )


def _up(tickers) -> pd.DataFrame:
    """A `universe_perf`-shaped frame: (period, metric) MultiIndex columns.

    v0.7.2: no Since-Inception block, mirroring `universe_perf`.
    """
    periods = ["1Y", "3Y", "5Y"]
    metrics = ["Return", "Vol", "Sharpe", "Max DD"]
    cols = pd.MultiIndex.from_product([periods, metrics])
    data = np.arange(len(tickers) * len(cols), dtype=float).reshape(
        len(tickers), len(cols)
    )
    return pd.DataFrame(data, index=pd.Index(tickers, name="ticker"), columns=cols)


# The ranking column's real header (#324), built rather than spelled.
_Z_NAME = zscore_column_name("Sharpe", "1Y")


def test_build_universe_frame_zscore_after_info_and_sorted():
    meta = _meta()
    up = _up(meta["ticker"])
    zcol = pd.Series({"AAA Index": 0.5, "BBB Index": 2.0, "CCC Index": -1.0})
    frame, z_key = _build_universe_frame(meta, up, zcol=zcol, zname=_Z_NAME)

    # Flat single-index columns; the Z-Score column sits right after the Info
    # block and immediately before the first stat column.
    cols = list(frame.columns)
    z_name = _Z_NAME
    # Headers and their order both come from the schema (#212): the info block
    # is `CATALOG_GRID_FIELDS`, so the tiers read broadest-first and `live_date`
    # carries its schema label ("Launch Date", not the raw feed's "Live Date").
    # Return Type left this table in #282 — it is near-constant across the
    # catalog and cost a column on every row; it stays on the profile card.
    info_cols = [
        "Name",
        "Asset Class",
        "Solution",
        "Category",
        "Family",
        "Launch Date",
    ]
    assert cols[: len(info_cols)] == info_cols
    assert cols[len(info_cols)] == z_name
    # And the builder hands that name back, so nothing downstream re-derives it.
    assert z_key == z_name
    assert cols[len(info_cols) + 1] == "1Y Return"
    # Sorted by z descending: BBB (2.0) > AAA (0.5) > CCC (-1.0).
    assert list(frame.index) == ["BBB Index", "AAA Index", "CCC Index"]


def test_build_universe_frame_nan_z_sinks_within_its_group():
    # A ticker with no z-score sinks to the bottom *of its group*, not of the
    # table: AAA and BBB are both ARP, and pulling AAA out to the very bottom
    # would split ARP into two runs, which is precisely what row grouping
    # cannot render.
    meta = _meta()
    up = _up(meta["ticker"])
    zcol = pd.Series({"AAA Index": np.nan, "BBB Index": 1.0, "CCC Index": 0.0})
    frame, _z_key = _build_universe_frame(meta, up, zcol=zcol, zname=_Z_NAME)
    assert list(frame.index) == ["BBB Index", "AAA Index", "CCC Index"]
    assert list(frame["Solution"]) == ["ARP", "ARP", "Smart Beta"]


def test_build_universe_frame_without_zcol_is_unsorted_no_zcol():
    meta = _meta()
    up = _up(meta["ticker"])
    frame, z_key = _build_universe_frame(meta, up)
    assert z_key is None
    cols = list(frame.columns)
    # Info block then flat stat columns; no z-score column at all.
    assert cols[0] == "Name"
    assert "1Y Return" in cols and "5Y Sharpe" in cols
    assert not any(ZSCORE_SUPERCOL in str(c) for c in cols)
    # No sort applied → original metadata order preserved.
    assert list(frame.index) == list(meta["ticker"])


def test_build_universe_frame_empty_meta():
    empty, z_key = _build_universe_frame(pd.DataFrame(), pd.DataFrame())
    assert empty.empty
    assert z_key is None


def _bg_expr(renderer) -> str:
    # ipydatagrid defaults `background_color` to an Expr(value="default_value");
    # a configured VegaExpr carries the real expression string in `.value`.
    v = getattr(renderer.background_color, "value", "")
    return "" if v == "default_value" else v


def test_perf_renderers_heatmap_scopes_sharpe_and_zscore():
    # The ranking column is named by its caller, not recognised from its label
    # (#323) — so the renderer is told which column it is.
    z_name = _Z_NAME
    cols = pd.Index(["1Y Sharpe", "1Y Return", z_name])
    on = _perf_renderers(cols, sharpe_heatmap=True, zscore_col=z_name)
    # Heatmap on: Sharpe column + Z-Score column get the diverging ramp.
    assert "cell.value <" in _bg_expr(on["1Y Sharpe"])
    assert "cell.value <" in _bg_expr(on[z_name])
    # Non-Sharpe numeric columns keep the plain (default) background.
    assert _bg_expr(on["1Y Return"]) == ""


def test_perf_renderers_flat_sharpe_heatmap_toggle():
    # The selected-strategy grid uses flat string columns. v0.7.5 turns the
    # diverging Sharpe heatmap on for it too, so a flat "1Y Sharpe" leaf must
    # get the ramp when the flag is on and stay plain when off.
    cols = pd.Index(["1Y Sharpe", "1Y Return", PERF_COLOR_COLUMN_NAME])
    on = _perf_renderers(cols, sharpe_heatmap=True)
    assert "cell.value <" in _bg_expr(on["1Y Sharpe"])
    # Non-Sharpe numeric + swatch columns are untouched by the flag.
    assert _bg_expr(on["1Y Return"]) == ""
    off = _perf_renderers(cols)
    assert _bg_expr(off["1Y Sharpe"]) == ""


def _text_value_expr(renderer) -> str:
    tv = getattr(renderer, "text_value", None)
    return getattr(tv, "value", "") if tv is not None else ""


def test_perf_renderers_dash_on_numeric_not_text_or_swatch():
    # Empty numeric cells (Return/Vol/Sharpe/Max DD/Z-Score) show "-" via a
    # `text_value` expr, since ipydatagrid's `missing` trait never fires for a
    # pandas NaN. Text columns and the color swatch must NOT carry it — `isNaN`
    # is true for any non-numeric string and would blank every cell.
    z_name = _Z_NAME
    cols = pd.Index([PERF_COLOR_COLUMN_NAME, "Name", "1Y Return", "1Y Sharpe", z_name])
    r = _perf_renderers(cols, sharpe_heatmap=True, zscore_col=z_name)
    dash = "isNaN(cell.value) ? '-' : ''"
    assert _text_value_expr(r["1Y Return"]) == dash
    assert _text_value_expr(r["1Y Sharpe"]) == dash
    assert _text_value_expr(r[z_name]) == dash
    # Text + swatch stay plain.
    assert _text_value_expr(r["Name"]) == ""
    assert _text_value_expr(r[PERF_COLOR_COLUMN_NAME]) == ""


def test_the_perf_grid_finds_the_ranking_column_by_key_too():
    """The ipydatagrid half of #323's guarantee.

    `PerfGrid` carries no ranking column today, but it reads the same two
    helpers the catalog's ramp is defined by — so they must follow the key as
    well, under a header that starts with neither "Z-Score" nor a window.
    """
    from src.layout.grids import _STAT_COL_WIDTH, _perf_column_widths

    future = "Normalized 1Y Sharpe (5Y Z-Score)"
    cols = pd.Index(["1Y Sharpe", "1Y Return", future])
    renderers = _perf_renderers(cols, sharpe_heatmap=True, zscore_col=future)
    # The symmetric z ramp, not the Sharpe bands and not the plain 2dp default.
    assert "cell.value <" in _bg_expr(renderers[future])
    assert _bg_expr(renderers[future]) != _bg_expr(renderers["1Y Sharpe"])

    frame = pd.DataFrame([[1.0, 0.1, 2.0]], columns=cols)
    widths = _perf_column_widths(frame, zscore_col=future)
    # Content-fit to its long header, not squeezed into the uniform stat width.
    assert widths[future] != _STAT_COL_WIDTH
    assert widths["1Y Sharpe"] == _STAT_COL_WIDTH


def test_perf_renderers_dash_on_numeric_without_heatmap():
    # Even with the heatmap off (selected-strategy grid), the plain 2dp / pct
    # renderers still substitute "-" for empty numeric cells.
    cols = pd.Index(["1Y Return", "1Y Sharpe", "Name", PERF_COLOR_COLUMN_NAME])
    r = _perf_renderers(cols)
    dash = "isNaN(cell.value) ? '-' : ''"
    assert _text_value_expr(r["1Y Return"]) == dash
    assert _text_value_expr(r["1Y Sharpe"]) == dash
    assert _text_value_expr(r["Name"]) == ""
    assert _text_value_expr(r[PERF_COLOR_COLUMN_NAME]) == ""


def test_the_two_grids_read_different_field_tuples():
    """The trap #282 closed: each tuple feeds exactly one grid, and the names
    now say which. `PerfGrid` keeps Return Type; the catalog table dropped it.

    Asserted together, in one test, because the failure mode is editing one
    tuple and changing the other grid — which only shows up when both are
    checked against each other.
    """
    from src.config import CATALOG_GRID_FIELDS, PERF_GRID_FIELDS
    from src.layout.grids import PerfGrid

    meta = _meta()
    grid = PerfGrid()
    grid.update(_up(meta["ticker"]), meta)
    perf_cols = list(grid.grid.data.columns)

    assert perf_cols[1:6] == ["Name", "Asset Class", "Solution", "Category", "Family"]
    assert "Return Type" not in perf_cols  # PerfGrid never carried it

    catalog_cols = list(_build_universe_frame(meta, _up(meta["ticker"]))[0].columns)
    assert "Return Type" not in catalog_cols
    assert "Launch Date" in catalog_cols  # the other Info column stays

    assert "return_type" not in CATALOG_GRID_FIELDS
    assert "return_type" not in PERF_GRID_FIELDS
