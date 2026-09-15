"""Unit tests for the all-catalog grid data prep (v0.7.0 Workstream A).

`_build_universe_frame` is the pure assembly behind `_update_universe_grid` —
it builds the flat single-index frame, inserts the dynamic z-score column, and
sorts by it — so it's testable without constructing an `ipydatagrid.DataGrid`.
The conditional-format renderer scoping is checked against `_perf_renderers`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src import config
from src.layout.grids import (
    PERF_COLOR_COLUMN_NAME,
    ZSCORE_SUPERCOL,
    _build_universe_frame,
    _calendar_renderers,
    _perf_renderers,
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


def test_build_universe_frame_zscore_after_info_and_sorted():
    meta = _meta()
    up = _up(meta["ticker"])
    zcol = pd.Series({"AAA Index": 0.5, "BBB Index": 2.0, "CCC Index": -1.0})
    frame = _build_universe_frame(meta, up, zcol=zcol, zlabel="Sharpe 1M/1Y")

    # v0.9.18 #256: the tiers are row-header levels, so the body opens on Name
    # and the Z-Score column still sits right after the remaining Info block.
    cols = list(frame.columns)
    z_name = f"{ZSCORE_SUPERCOL} Sharpe 1M/1Y"
    # Headers and their order both come from the schema (#212); the three tier
    # fields have moved out to the index, and `live_date` carries its schema
    # label ("Launch Date", not the raw feed's "Live Date").
    info_cols = ["Name", "Asset Class", "Return Type", "Launch Date"]
    assert cols[: len(info_cols)] == info_cols
    assert cols[len(info_cols)] == z_name
    assert cols[len(info_cols) + 1] == "1Y Return"
    # Each group holds one ticker here, so ordering groups by their best member
    # reduces to the plain z-rank: BBB (2.0) > AAA (0.5) > CCC (-1.0).
    assert list(frame.index.get_level_values("Ticker")) == [
        "BBB Index",
        "AAA Index",
        "CCC Index",
    ]


def test_build_universe_frame_nan_z_sinks_to_bottom():
    meta = _meta()
    up = _up(meta["ticker"])
    zcol = pd.Series({"AAA Index": np.nan, "BBB Index": 1.0, "CCC Index": 0.0})
    frame = _build_universe_frame(meta, up, zcol=zcol, zlabel="Sharpe 1M/1Y")
    assert list(frame.index.get_level_values("Ticker")) == [
        "BBB Index",
        "CCC Index",
        "AAA Index",
    ]


def test_build_universe_frame_without_zcol_sorts_by_group():
    meta = _meta()
    up = _up(meta["ticker"])
    frame = _build_universe_frame(meta, up)
    cols = list(frame.columns)
    # Info block then flat stat columns; no z-score column at all.
    assert cols[0] == "Name"
    assert "1Y Return" in cols and "5Y Sharpe" in cols
    assert not any(
        c == ZSCORE_SUPERCOL or c.startswith(ZSCORE_SUPERCOL + " ") for c in cols
    )
    # With no z to rank by, rows are ordered by the group keys. That is not
    # cosmetic: ipydatagrid merges equal *neighbouring* row-header values, so an
    # unsorted frame would render one group as several broken blocks.
    tiers = frame.index.to_frame(index=False)[["Solution", "Category", "Family"]]
    assert tiers.values.tolist() == sorted(tiers.values.tolist())


def test_build_universe_frame_empty_meta():
    assert _build_universe_frame(pd.DataFrame(), pd.DataFrame()).empty


def _bg_expr(renderer) -> str:
    # ipydatagrid defaults `background_color` to an Expr(value="default_value");
    # a configured VegaExpr carries the real expression string in `.value`.
    v = getattr(renderer.background_color, "value", "")
    return "" if v == "default_value" else v


def test_perf_renderers_heatmap_scopes_sharpe_and_zscore():
    z_name = f"{ZSCORE_SUPERCOL} Sharpe 1M/1Y"
    cols = pd.Index(["1Y Sharpe", "1Y Return", z_name])
    on = _perf_renderers(cols, sharpe_heatmap=True)
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
    z_name = f"{ZSCORE_SUPERCOL} Sharpe 1M/1Y"
    cols = pd.Index([PERF_COLOR_COLUMN_NAME, "Name", "1Y Return", "1Y Sharpe", z_name])
    r = _perf_renderers(cols, sharpe_heatmap=True)
    dash = "isNaN(cell.value) ? '-' : ''"
    assert _text_value_expr(r["1Y Return"]) == dash
    assert _text_value_expr(r["1Y Sharpe"]) == dash
    assert _text_value_expr(r[z_name]) == dash
    # Text + swatch stay plain.
    assert _text_value_expr(r["Name"]) == ""
    assert _text_value_expr(r[PERF_COLOR_COLUMN_NAME]) == ""


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


# --- Grouped row headers (v0.9.18 #256) ---------------------------------------
#
# The tiers become a merged row-header block instead of three body columns. The
# frame builder is where that is decided, so these pin the frame shape, the
# ordering the merge depends on, and the escape hatch back to the flat grid.


def _grouped_meta() -> pd.DataFrame:
    """Two tickers in one group and one in another, so "order groups by their
    best member" is distinguishable from a plain global z-rank."""
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "asset_class": ["Equity", "Equity", "Equity"],
            "solution": ["ARP", "ARP", "ARP"],
            "category": ["Carry", "Carry", "Momentum"],
            "family": ["FX Carry", "FX Carry", "FX Momentum"],
            "return_type": ["Total", "Total", "Total"],
            "live_date": pd.to_datetime(["2010-01-01", "2015-06-01", "2020-03-15"]),
        }
    )


def test_grouped_frame_indexes_on_tiers_and_drops_them_from_the_body():
    meta = _grouped_meta()
    frame = _build_universe_frame(meta, _up(meta["ticker"]))
    assert list(frame.index.names) == ["Solution", "Category", "Family", "Ticker"]
    # The point of the change: ~414px of repeated tier text leaves the body.
    for tier in ("Solution", "Category", "Family"):
        assert tier not in frame.columns


def test_grouped_rows_of_one_group_are_contiguous():
    # ipydatagrid merges equal *neighbouring* row-header values. If a group's
    # rows are not adjacent it renders as several broken blocks rather than one
    # spanning cell, which is the whole feature — so contiguity is a guarantee
    # of the frame, not an accident of the data arriving pre-sorted.
    meta = _grouped_meta()
    zcol = pd.Series({"AAA Index": 0.1, "BBB Index": 3.0, "CCC Index": 2.0})
    frame = _build_universe_frame(meta, _up(meta["ticker"]), zcol=zcol, zlabel="S")
    keys = frame.index.to_frame(index=False)[["Solution", "Category", "Family"]]
    runs = (keys != keys.shift()).any(axis=1).cumsum().nunique()
    assert runs == len(keys.drop_duplicates())


def test_grouped_sort_puts_the_catalog_best_first():
    # #255 q3, option D: groups are ordered by their best member, so the first
    # row is still the best index in the catalog — the property the flat grid
    # had. Sorting on the group keys alone would bury BBB under whichever group
    # sorts first alphabetically ("Carry" < "Momentum" here hides the tie).
    meta = _grouped_meta()
    zcol = pd.Series({"AAA Index": -1.0, "BBB Index": 3.0, "CCC Index": 2.0})
    frame = _build_universe_frame(meta, _up(meta["ticker"]), zcol=zcol, zlabel="S")
    z = f"{ZSCORE_SUPERCOL} S"
    assert frame.index.get_level_values("Ticker")[0] == "BBB Index"
    assert frame[z].iloc[0] == frame[z].max()
    # And deliberately NOT globally monotonic: AAA (-1.0) rides above CCC (2.0)
    # because it sits inside the leading group. That is inherent to grouping,
    # and is the trade recorded on #254.
    assert list(frame.index.get_level_values("Ticker")) == [
        "BBB Index",
        "AAA Index",
        "CCC Index",
    ]
    assert not frame[z].is_monotonic_decreasing


def test_empty_group_fields_restores_the_flat_grid(monkeypatch):
    # The escape hatch: if grouping misbehaves on a terminal, one config edit
    # returns the exact v0.9.17 grid — flat index, tiers back in the body,
    # global z-rank.
    monkeypatch.setattr(config, "UNIVERSE_GRID_GROUP_FIELDS", ())
    meta = _meta()
    zcol = pd.Series({"AAA Index": 0.5, "BBB Index": 2.0, "CCC Index": -1.0})
    frame = _build_universe_frame(meta, _up(meta["ticker"]), zcol=zcol, zlabel="S")

    assert not isinstance(frame.index, pd.MultiIndex)
    assert frame.index.name == "Ticker"
    assert list(frame.columns)[:7] == [
        "Name",
        "Asset Class",
        "Solution",
        "Category",
        "Family",
        "Return Type",
        "Launch Date",
    ]
    assert list(frame.index) == ["BBB Index", "AAA Index", "CCC Index"]


def test_group_nesting_follows_the_configured_tier_order(monkeypatch):
    # Reordering the hierarchy is a config edit, not a code edit.
    monkeypatch.setattr(
        config, "UNIVERSE_GRID_GROUP_FIELDS", ("family", "category", "solution")
    )
    meta = _grouped_meta()
    frame = _build_universe_frame(meta, _up(meta["ticker"]))
    assert list(frame.index.names) == ["Family", "Category", "Solution", "Ticker"]


def test_group_level_names_come_from_the_schema(monkeypatch):
    # Relabelling a tier reaches the grouped headers — nothing respells a label.
    relabelled = tuple(
        (
            config.CatalogField(f.key, f.sources, f"ZZ_{f.label}", f.role)
            if f.key in ("solution", "category", "family")
            else f
        )
        for f in config.CATALOG_SCHEMA
    )
    monkeypatch.setattr(config, "CATALOG_SCHEMA", relabelled)
    meta = _grouped_meta()
    frame = _build_universe_frame(meta, _up(meta["ticker"]))
    assert list(frame.index.names) == [
        "ZZ_Solution",
        "ZZ_Category",
        "ZZ_Family",
        "Ticker",
    ]


def test_grouping_does_not_leak_into_perf_or_calendar_grids():
    """`_apply_grid_styling` is shared. Grouping added a `MultiIndex` branch to
    it, so assert the other two grids still take the flat path unchanged — they
    keep a single-level index and size their row header from it, with no tier
    level anywhere in their widths."""
    from src.layout.grids import CalendarGrid, PerfGrid

    meta = _grouped_meta().set_index("ticker")
    cols = pd.MultiIndex.from_product([["1Y"], ["Return", "Vol", "Sharpe", "Max DD"]])
    pt = pd.DataFrame(
        np.arange(12, dtype=float).reshape(3, 4),
        index=pd.Index(meta.index, name="ticker"),
        columns=cols,
    )
    pg = PerfGrid()
    pg.update(pt, _grouped_meta())
    assert not isinstance(pg.grid.data.index, pd.MultiIndex)
    # The selected-strategy grid still carries the tiers as ordinary body
    # columns with their own widths — grouping is the all-catalog grid's alone.
    assert all(k in pg.grid.column_widths for k in ("Solution", "Category", "Family"))
    assert pg.grid.base_row_header_size > 0

    cg = CalendarGrid()
    cg.update(
        pd.DataFrame([[0.01, 0.02]], index=pd.Index([2024]), columns=["Jan", "Feb"]),
        kind="absolute",
    )
    assert not isinstance(cg.grid.data.index, pd.MultiIndex)
