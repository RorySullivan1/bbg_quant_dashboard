"""Unit tests for the all-catalog grid data prep (v0.7.0 Workstream A).

`_build_universe_frame` is the pure assembly behind `_update_universe_grid` —
it builds the MultiIndex frame, inserts the dynamic z-score column, and sorts by
it — so it's testable without constructing an `ipydatagrid.DataGrid`. The
conditional-format renderer scoping is checked against `_perf_renderers`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.layout.grids import (
    ZSCORE_SUPERCOL,
    _build_universe_frame,
    _calendar_renderers,
    _perf_renderers,
)

_CAL_COLS = [
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
    "Year",
    "Sharpe",
]


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


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "category": ["X", "Y", "Z"],
            "theme": ["T1", "T2", "T3"],
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

    # Z-Score supercolumn present, immediately after the Info block.
    level0 = list(dict.fromkeys(frame.columns.get_level_values(0)))
    assert level0 == ["Info", ZSCORE_SUPERCOL, "1Y", "3Y", "5Y"]
    assert (ZSCORE_SUPERCOL, "Sharpe 1M/1Y") in frame.columns
    # Sorted by z descending: BBB (2.0) > AAA (0.5) > CCC (-1.0).
    assert list(frame.index) == ["BBB Index", "AAA Index", "CCC Index"]


def test_build_universe_frame_nan_z_sinks_to_bottom():
    meta = _meta()
    up = _up(meta["ticker"])
    zcol = pd.Series({"AAA Index": np.nan, "BBB Index": 1.0, "CCC Index": 0.0})
    frame = _build_universe_frame(meta, up, zcol=zcol, zlabel="Sharpe 1M/1Y")
    assert list(frame.index) == ["BBB Index", "CCC Index", "AAA Index"]


def test_build_universe_frame_without_zcol_is_unsorted_no_zcol():
    meta = _meta()
    up = _up(meta["ticker"])
    frame = _build_universe_frame(meta, up)
    level0 = list(dict.fromkeys(frame.columns.get_level_values(0)))
    assert level0 == ["Info", "1Y", "3Y", "5Y"]
    assert ZSCORE_SUPERCOL not in frame.columns.get_level_values(0)
    # No sort applied → original metadata order preserved.
    assert list(frame.index) == list(meta["ticker"])


def test_build_universe_frame_empty_meta():
    assert _build_universe_frame(pd.DataFrame(), pd.DataFrame()).empty


def _bg_expr(renderer) -> str:
    # ipydatagrid defaults `background_color` to an Expr(value="default_value");
    # a configured VegaExpr carries the real expression string in `.value`.
    v = getattr(renderer.background_color, "value", "")
    return "" if v == "default_value" else v


def test_perf_renderers_heatmap_scopes_sharpe_and_zscore():
    cols = pd.MultiIndex.from_tuples(
        [("1Y", "Sharpe"), ("1Y", "Return"), (ZSCORE_SUPERCOL, "Sharpe 1M/1Y")]
    )
    on = _perf_renderers(cols, sharpe_heatmap=True)
    # Heatmap on: Sharpe leaf + Z-Score column get the diverging ramp.
    assert "cell.value <" in _bg_expr(on[("1Y", "Sharpe")])
    assert "cell.value <" in _bg_expr(on[(ZSCORE_SUPERCOL, "Sharpe 1M/1Y")])
    # Non-Sharpe numeric leaves keep the plain (default) background.
    assert _bg_expr(on[("1Y", "Return")]) == ""


def test_perf_renderers_flat_sharpe_heatmap_toggle():
    # The selected-strategy grid uses flat string columns. v0.7.5 turns the
    # diverging Sharpe heatmap on for it too, so a flat "1Y Sharpe" leaf must
    # get the ramp when the flag is on and stay plain when off.
    cols = pd.Index(["1Y Sharpe", "1Y Return", "Chart Color"])
    on = _perf_renderers(cols, sharpe_heatmap=True)
    assert "cell.value <" in _bg_expr(on["1Y Sharpe"])
    # Non-Sharpe numeric + swatch columns are untouched by the flag.
    assert _bg_expr(on["1Y Return"]) == ""
    off = _perf_renderers(cols)
    assert _bg_expr(off["1Y Sharpe"]) == ""
