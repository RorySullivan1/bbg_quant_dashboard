"""The all-catalog grid's grouping (v0.9.18 #263).

The catalog table renders the classification tiers as nested row-group headers
instead of three body columns. DataTables' RowGroup starts a new header
whenever a group value changes between **adjacent** rows — it does not gather
scattered rows — so the ordering `_build_universe_frame` produces is a
correctness requirement, not presentation. These tests pin that contiguity,
the configurability of which fields group, and the widget options that carry
the grouping to the frontend.

What they cannot see is whether the table *draws* correctly. That gap is the
whole lesson of #255, where every frame-level assertion passed against a grid
that rendered wrong; the screenshot in the PR is the other half of the
evidence.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from src import config
from src.layout.grids import (
    _SHARPE_HEAT_THRESHOLDS,
    _ZSCORE_HEAT_THRESHOLDS,
    _build_universe_frame,
    _catalog_display_frame,
    _catalog_group_labels,
    _catalog_table_options,
    _js_heat_cell,
    _js_number_render,
)

_Z_LABEL = "Sharpe 1M/1Y"
_Z_NAME = f"Z-Score {_Z_LABEL}"


def _catalog() -> pd.DataFrame:
    """A catalog with enough shape to fragment if the ordering is wrong.

    Three solutions, several categories each, several families inside those —
    and deliberately *interleaved* in source order, so a frame that merely
    preserves input order, or sorts by z alone, fails the contiguity tests.
    """
    rows = [
        # ticker, solution, category, family
        ("AAA", "ARP", "Equity", "Value"),
        ("BBB", "Smart Beta", "Credit", "IG"),
        ("CCC", "ARP", "Equity", "Momentum"),
        ("DDD", "Macro", "Rates", "Carry"),
        ("EEE", "ARP", "Commodity", "Curve"),
        ("FFF", "Smart Beta", "Equity", "Quality"),
        ("GGG", "ARP", "Equity", "Value"),
        ("HHH", "Macro", "FX", "Trend"),
        ("III", "Smart Beta", "Credit", "HY"),
        ("JJJ", "ARP", "Commodity", "Carry"),
        ("KKK", "Macro", "Rates", "Trend"),
        ("LLL", "Smart Beta", "Equity", "Quality"),
    ]
    return pd.DataFrame(
        {
            "ticker": [f"{t} Index" for t, _, _, _ in rows],
            "name": [f"Name {t}" for t, _, _, _ in rows],
            "asset_class": ["Equity"] * len(rows),
            "solution": [s for _, s, _, _ in rows],
            "category": [c for _, _, c, _ in rows],
            "family": [f for _, _, _, f in rows],
            "return_type": ["Total"] * len(rows),
            "live_date": pd.to_datetime(["2015-01-01"] * len(rows)),
        }
    )


def _zcol(meta: pd.DataFrame, values: list[float] | None = None) -> pd.Series:
    """Per-ticker z-scores. The default spreads them so no two groups tie."""
    if values is None:
        values = [round(1.5 - 0.23 * i, 3) for i in range(len(meta))]
    return pd.Series(dict(zip(meta["ticker"], values, strict=True)))


def _frame(meta: pd.DataFrame, zcol: pd.Series | None) -> pd.DataFrame:
    return _build_universe_frame(
        meta,
        pd.DataFrame(),
        zcol=zcol,
        zlabel=_Z_LABEL if zcol is not None else None,
    )


def _runs(values: list) -> list:
    """The sequence of values with consecutive duplicates collapsed.

    `['A','A','B','A']` -> `['A','B','A']`, so a value appearing twice in the
    result is a group that was split into two runs.
    """
    out: list = []
    for v in values:
        if not out or out[-1] != v:
            out.append(v)
    return out


# --- contiguity: what RowGroup depends on ----------------------------------


def test_every_group_is_one_contiguous_run_at_every_level():
    meta = _catalog()
    frame = _frame(meta, _zcol(meta))
    labels = _catalog_group_labels()
    assert labels, "this test is meaningless if nothing is grouped"

    # Check each level on the *path* down to it, which is what nesting means:
    # "Equity" under ARP and "Equity" under Smart Beta are different groups and
    # are allowed to be non-adjacent, but ARP/Equity must be a single run.
    for depth in range(1, len(labels) + 1):
        path = list(zip(*(frame[label] for label in labels[:depth]), strict=True))
        runs = _runs(path)
        assert len(runs) == len(set(runs)), (
            f"level {depth} ({labels[:depth]}) fragments: "
            f"{len(runs)} runs for {len(set(runs))} groups"
        )


def test_deepest_level_alone_would_not_be_enough():
    # Guards the reasoning, not just the result: ordering by the deepest group
    # is the obvious implementation and it leaves outer levels interleaved.
    # If this ever stops fragmenting, the contiguity test above has gone slack.
    meta = _catalog()
    frame = _frame(meta, _zcol(meta))
    labels = _catalog_group_labels()
    naive = frame.sort_values(
        [labels[-1], _Z_NAME], ascending=[True, False], na_position="last"
    )
    top = _runs(list(naive[labels[0]]))
    assert len(top) > len(set(top))


def test_groups_that_tie_on_their_best_member_do_not_interleave():
    # Two solutions whose best z is identical must still not alternate. Without
    # the label tiebreaker the sort is free to interleave them.
    meta = _catalog()
    z = dict.fromkeys(meta["ticker"], 0.0)
    for ticker in meta.loc[meta["solution"] == "ARP", "ticker"]:
        z[ticker] = 1.0
    for ticker in meta.loc[meta["solution"] == "Macro", "ticker"]:
        z[ticker] = 1.0
    frame = _frame(meta, pd.Series(z))
    top = _runs(list(frame["Solution"]))
    assert len(top) == len(set(top))


# --- ordering still puts the best index first -------------------------------


def test_first_row_is_the_catalogs_best_index_by_zscore():
    meta = _catalog()
    zcol = _zcol(meta)
    frame = _frame(meta, zcol)
    assert frame.index[0] == zcol.idxmax()
    assert frame[_Z_NAME].iloc[0] == zcol.max()


def test_a_group_with_no_zscore_at_all_sinks_to_the_bottom():
    meta = _catalog()
    z = {t: 1.0 for t in meta["ticker"]}
    for ticker in meta.loc[meta["solution"] == "Macro", "ticker"]:
        z[ticker] = np.nan
    frame = _frame(meta, pd.Series(z))
    assert list(frame["Solution"])[-3:] == ["Macro"] * 3


# --- the fields that group are configuration --------------------------------


def test_group_fields_are_the_classification_tiers_by_reference():
    # Splatted, not respelled: reordering or renaming a tier in
    # CLASSIFICATION_TIERS reaches the grouping without an edit here.
    assert config.UNIVERSE_GRID_GROUP_FIELDS == config.CLASSIFICATION_TIERS


def test_no_group_fields_degrades_to_the_plain_zscore_sort(monkeypatch):
    meta = _catalog()
    zcol = _zcol(meta)
    monkeypatch.setattr(config, "UNIVERSE_GRID_GROUP_FIELDS", ())
    frame = _frame(meta, zcol)
    expected = list(zcol.sort_values(ascending=False).index)
    assert list(frame.index) == expected
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    assert groups == []
    assert "rowGroup" not in _catalog_table_options(display, groups)


def test_reordering_the_group_fields_reorders_the_nesting(monkeypatch):
    meta = _catalog()
    zcol = _zcol(meta)
    monkeypatch.setattr(
        config, "UNIVERSE_GRID_GROUP_FIELDS", ("category", "solution", "family")
    )
    frame = _frame(meta, zcol)
    # Category is now the outermost group, so it — not Solution — is the level
    # that must form single runs.
    top = _runs(list(frame["Category"]))
    assert len(top) == len(set(top))
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    assert groups == ["Category", "Solution", "Family"]


def test_an_unknown_group_field_is_rejected_by_name(monkeypatch):
    monkeypatch.setattr(config, "UNIVERSE_GRID_GROUP_FIELDS", ("solution", "nonesuch"))
    with pytest.raises(KeyError, match="nonesuch"):
        config.universe_grid_group_fields()


def test_relabelling_a_tier_reaches_the_group_headers(monkeypatch):
    # The headers a user reads come from CATALOG_SCHEMA, so a relabel must
    # arrive without touching the grid. A sentinel proves the label is read
    # rather than coincidentally matching the field key.
    sentinel = "Strategy Bucket"
    patched = tuple(
        dataclasses.replace(f, label=sentinel) if f.key == "solution" else f
        for f in config.CATALOG_SCHEMA
    )
    monkeypatch.setattr(config, "CATALOG_SCHEMA", patched)
    assert _catalog_group_labels()[0] == sentinel

    frame = _frame(_catalog(), None)
    assert sentinel in frame.columns
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    assert groups[0] == sentinel


# --- the widget options that carry the grouping to the frontend -------------


def test_group_columns_lead_the_display_frame_and_are_hidden():
    meta = _catalog()
    frame = _frame(meta, _zcol(meta))
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())

    assert list(display.columns)[: len(groups)] == groups
    assert list(display.columns)[len(groups)] == "Ticker"

    options = _catalog_table_options(display, groups)
    hidden = [d for d in options["columnDefs"] if d.get("visible") is False]
    assert len(hidden) == 1
    # The same indices are hidden from the body and used as group sources —
    # the tiers leave the body and come back as headers. If these ever diverge
    # the grid either repeats the tier text or groups on the wrong column.
    assert hidden[0]["targets"] == options["rowGroup"]["dataSrc"]
    assert hidden[0]["targets"] == list(range(len(groups)))


def test_numeric_renderers_are_scoped_to_the_numeric_columns():
    meta = _catalog()
    frame = _build_universe_frame(
        meta,
        _up(meta["ticker"]),
        zcol=_zcol(meta),
        zlabel=_Z_LABEL,
    )
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    options = _catalog_table_options(display, groups)
    columns = list(display.columns)
    rendered = {
        columns[d["targets"][0]] for d in options["columnDefs"] if "render" in d
    }
    heated = {
        columns[d["targets"][0]] for d in options["columnDefs"] if "createdCell" in d
    }

    assert "1Y Return" in rendered and "1Y Vol" in rendered
    assert _Z_NAME in rendered and "1Y Sharpe" in rendered
    # Text columns must not get a numeric renderer — it would blank them.
    assert "Name" not in rendered and "Ticker" not in rendered
    # The heat ramp belongs to the ranking columns only.
    assert heated == {_Z_NAME, "1Y Sharpe", "3Y Sharpe", "5Y Sharpe"}


def test_display_renderer_leaves_sort_values_numeric():
    # The renderer formats only `type === 'display'`. Everything else — sort,
    # filter, type detection — gets the raw number back, or the column would
    # sort lexically: "9.00%" above "12.00%".
    js = str(_js_number_render(percent=True))
    assert "type !== 'display'" in js
    assert "return data;" in js
    assert "(data * 100).toFixed(2)" in js
    assert str(_js_number_render(percent=False)).count("toFixed(2)") == 1


def test_heat_ramp_reads_the_same_bands_as_the_ipydatagrid_grids():
    # The catalog grid and the perf grids draw the same red→green ramp through
    # two different stacks. They share the threshold tuples so the two cannot
    # drift apart; this asserts the numbers actually reach the JavaScript.
    z_js = str(_js_heat_cell(_ZSCORE_HEAT_THRESHOLDS))
    for bound in _ZSCORE_HEAT_THRESHOLDS:
        assert str(bound) in z_js
    sharpe_js = str(_js_heat_cell(_SHARPE_HEAT_THRESHOLDS))
    for bound in _SHARPE_HEAT_THRESHOLDS:
        assert str(bound) in sharpe_js


def test_heat_ramp_is_written_important_or_the_chrome_overrides_it():
    # The dark chrome themes body cells with an `!important` background, and an
    # `!important` author rule beats a plain inline style. Assigning
    # `td.style.backgroundColor` computes the ramp and renders none of it — the
    # colour sits in the inline style while the cell paints flat navy. Caught
    # only by reading a computed style in a real browser, so it is pinned here.
    js = str(_js_heat_cell(_ZSCORE_HEAT_THRESHOLDS))
    assert "setProperty('background-color', bg, 'important')" in js
    assert "td.style.backgroundColor =" not in js
    assert "removeProperty('background-color')" in js


def test_heat_ramp_leaves_empty_and_neutral_cells_to_the_zebra():
    # Painting the neutral band would flatten the row striping, so those cells
    # set no background at all and the CSS stripe shows through.
    js = str(_js_heat_cell(_ZSCORE_HEAT_THRESHOLDS))
    assert "isNaN(cellData)" in js
    assert js.count("bg = ''") == 2  # the empty guard and the neutral band


def _up(tickers) -> pd.DataFrame:
    """A `universe_perf`-shaped frame: (period, metric) MultiIndex columns."""
    periods = ["1Y", "3Y", "5Y"]
    metrics = ["Return", "Vol", "Sharpe", "Max DD"]
    cols = pd.MultiIndex.from_product([periods, metrics])
    data = np.arange(len(tickers) * len(cols), dtype=float).reshape(
        len(tickers), len(cols)
    )
    return pd.DataFrame(data, index=pd.Index(tickers, name="ticker"), columns=cols)


# --- a clicked row names a strategy (#265) ---------------------------------


def _grid_with(picked: list[str]):
    """A populated grid whose picks land in `picked`."""
    from src.layout.grids import UniverseGrid

    meta = _catalog()
    grid = UniverseGrid(on_pick=picked.append)
    grid.update(meta, pd.DataFrame(), zcol=_zcol(meta), zlabel=_Z_LABEL)
    return grid


def test_a_selected_row_reports_the_ticker_at_that_position():
    picked: list[str] = []
    grid = _grid_with(picked)
    # The widget reports a row by position into the data it was given, so the
    # expected ticker is read off the same frame rather than assumed to be the
    # catalog's source order — which the grouping has already changed.
    for position in (0, 3, len(grid._tickers) - 1):
        picked.clear()
        grid.widget.selected_rows = [position]
        assert picked == [grid._tickers[position]]


def test_deselecting_is_a_no_op_rather_than_a_blank_selection():
    # Clicking the selected row again deselects it. Treating that as "the user
    # chose nothing" and clearing the analysis panes would be worse than
    # useless, so an empty list must not reach the callback at all.
    picked: list[str] = []
    grid = _grid_with(picked)
    grid.widget.selected_rows = [1]
    assert len(picked) == 1
    grid.widget.selected_rows = []
    assert len(picked) == 1  # unchanged, and no exception


def test_a_row_position_outside_the_current_frame_is_ignored():
    # Reachable when a re-render lands between the click and the callback.
    # Unguarded this raises inside traitlets, where the exception surfaces as a
    # widget that has quietly stopped responding rather than as an error.
    picked: list[str] = []
    grid = _grid_with(picked)
    grid.widget.selected_rows = [len(grid._tickers) + 5]
    assert picked == []


def test_a_grid_with_no_callback_still_accepts_clicks():
    from src.layout.grids import UniverseGrid

    grid = UniverseGrid()
    meta = _catalog()
    grid.update(meta, pd.DataFrame(), zcol=_zcol(meta), zlabel=_Z_LABEL)
    grid.widget.selected_rows = [0]  # must not raise


def test_the_row_to_ticker_map_follows_the_rendered_frame():
    # The map is rebuilt on the single write path, so a re-render with a
    # different catalog cannot leave the previous catalog's tickers behind —
    # which would route clicks to strategies that are no longer on screen.
    picked: list[str] = []
    grid = _grid_with(picked)
    first = grid._tickers
    smaller = _catalog().head(4)
    grid.update(smaller, pd.DataFrame(), zcol=_zcol(smaller), zlabel=_Z_LABEL)
    assert len(grid._tickers) == 4
    assert grid._tickers != first
    grid.widget.selected_rows = [2]
    assert picked[-1] == grid._tickers[2]


def test_the_catalog_enables_single_row_selection():
    # Without the Select extension switched on, `selected_rows` never changes
    # and every test above passes against a table nobody can click.
    meta = _catalog()
    frame = _frame(meta, _zcol(meta))
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    options = _catalog_table_options(display, groups)
    assert options["select"] == {"style": "single"}


def test_the_catalog_is_never_downsampled():
    # itables drops the middle of a table over ~64KB of JSON. On a browse
    # surface that is silent data loss, and the row a user wants is as likely
    # to be in the dropped middle as anywhere.
    meta = _catalog()
    frame = _frame(meta, _zcol(meta))
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    assert _catalog_table_options(display, groups)["maxBytes"] == 0
