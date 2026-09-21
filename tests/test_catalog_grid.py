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
import re

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
    zscore_column_name,
)

# The ranking column's real header, built the way the app builds it (#324).
_Z_NAME = zscore_column_name("Sharpe", "1Y")


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
    # The builder also hands back the ranking column's name (#323); the tests
    # below spell it as `_Z_NAME`, which this drops on the floor deliberately —
    # `test_the_builder_names_the_column_it_inserted` is what pins the two
    # agreeing.
    frame, _z_key = _build_universe_frame(
        meta,
        pd.DataFrame(),
        zcol=zcol,
        zname=_Z_NAME if zcol is not None else None,
    )
    return frame


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
    assert (
        _catalog_table_options(display, groups, zscore_col=_Z_NAME)["rowGroup"] is False
    )


def test_the_default_selection_does_not_set_the_nesting_order(monkeypatch):
    # v0.9.18 (#273): nesting is the hierarchy's, not the order fields are
    # listed in. Spelling the default out of order must NOT re-nest the table —
    # otherwise ticking order would quietly become meaningful again.
    monkeypatch.setattr(
        config, "UNIVERSE_GRID_GROUP_FIELDS", ("category", "solution", "family")
    )
    frame = _frame(_catalog(), _zcol(_catalog()))
    _display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    assert groups == ["Solution", "Category", "Family"]


def test_the_hierarchy_order_is_the_config_knob(monkeypatch):
    # Reordering the *groupable* tuple is how the nesting changes — that is the
    # declaration of what sits above what.
    monkeypatch.setattr(
        config,
        "UNIVERSE_GRID_GROUPABLE_FIELDS",
        ("category", "solution", "family", "asset_class"),
    )
    meta = _catalog()
    zcol = _zcol(meta)
    frame, _z_key = _build_universe_frame(
        meta,
        pd.DataFrame(),
        zcol=zcol,
        zname=_Z_NAME,
        group_fields=("solution", "category", "family"),
    )
    _display, groups = _catalog_display_frame(
        frame, _catalog_group_labels(("solution", "category", "family"))
    )
    assert groups == ["Category", "Solution", "Family"]
    # Category is now outermost, so it is the level that must form single runs.
    top = _runs(list(frame["Category"]))
    assert len(top) == len(set(top))


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

    options = _catalog_table_options(display, groups, zscore_col=_Z_NAME)
    hidden = [d for d in options["columnDefs"] if d.get("visible") is False]
    assert len(hidden) == 1
    # The same indices are hidden from the body and used as group sources —
    # the tiers leave the body and come back as headers. If these ever diverge
    # the grid either repeats the tier text or groups on the wrong column.
    assert hidden[0]["targets"] == options["rowGroup"]["dataSrc"]
    assert hidden[0]["targets"] == list(range(len(groups)))


def test_numeric_renderers_are_scoped_to_the_numeric_columns():
    meta = _catalog()
    frame, z_key = _build_universe_frame(
        meta,
        _up(meta["ticker"]),
        zcol=_zcol(meta),
        zname=_Z_NAME,
    )
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    options = _catalog_table_options(display, groups, zscore_col=z_key)
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
    assert heated == {_Z_NAME, "6M Sharpe", "1Y Sharpe", "3Y Sharpe", "5Y Sharpe"}


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
    grid.update(meta, pd.DataFrame(), zcol=_zcol(meta), zname=_Z_NAME)
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
    grid.update(meta, pd.DataFrame(), zcol=_zcol(meta), zname=_Z_NAME)
    grid.widget.selected_rows = [0]  # must not raise


def test_the_row_to_ticker_map_follows_the_rendered_frame():
    # The map is rebuilt on the single write path, so a re-render with a
    # different catalog cannot leave the previous catalog's tickers behind —
    # which would route clicks to strategies that are no longer on screen.
    picked: list[str] = []
    grid = _grid_with(picked)
    first = grid._tickers
    smaller = _catalog().head(4)
    grid.update(smaller, pd.DataFrame(), zcol=_zcol(smaller), zname=_Z_NAME)
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
    options = _catalog_table_options(display, groups, zscore_col=_Z_NAME)
    assert options["select"] == {"style": "single"}


def test_the_catalog_is_never_downsampled():
    # itables drops the middle of a table over ~64KB of JSON. On a browse
    # surface that is silent data loss, and the row a user wants is as likely
    # to be in the dropped middle as anywhere.
    meta = _catalog()
    frame = _frame(meta, _zcol(meta))
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    assert _catalog_table_options(display, groups, zscore_col=_Z_NAME)["maxBytes"] == 0


# --- header alignment: why the catalog does not use DataTables scrolling ----


def _catalog_css() -> str:
    from src.config import TEMPLATES_DIR

    return (TEMPLATES_DIR / "app_css.html").read_text(encoding="utf-8")


def test_the_catalog_does_not_use_datatables_scrolling():
    # `scrollY` renders the header in a SECOND table and sizes both once, at
    # init. When the container settles to its real width afterwards — or when
    # this app's `!important` font rules land after DataTables measured — the
    # two end up different widths and the header sits off its columns until a
    # redraw. On a BQuant terminal that showed as headers needing one click to
    # snap into place; measured here at a 169px drift across 18 columns.
    #
    # Scrolling in CSS keeps header and body in one table, where they cannot
    # drift. Re-adding either option brings the bug back with no other symptom,
    # so it is pinned rather than left to a comment.
    meta = _catalog()
    frame = _frame(meta, _zcol(meta))
    display, groups = _catalog_display_frame(frame, _catalog_group_labels())
    options = _catalog_table_options(display, groups, zscore_col=_Z_NAME)
    assert "scrollY" not in options
    assert "scrollCollapse" not in options


def test_the_stylesheet_scrolls_the_catalog_and_pins_its_header():
    # The scroll must sit on `.dt-layout-cell`, not the row around it:
    # DataTables' own stylesheet already gives the cell `overflow: auto`, which
    # makes it the nearest scrolling ancestor of the header. Scrolling the row
    # instead leaves the header scrolling away with the body — sticky in name
    # and not in behaviour.
    css = _catalog_css()
    assert ".dt-layout-row.dt-layout-table .dt-layout-cell" in css
    assert "max-height" in css
    sticky = css[css.index("table.dataTable thead th {") :]
    assert "position: sticky" in sticky[:400]


# --- one stats window at a time, and user-chosen grouping (#266, #273) -----


def _visible_columns(grid) -> list[str]:
    """The columns DataTables would actually draw, in order."""

    options = grid.table_options()
    hidden: set[int] = set()
    for spec in options["columnDefs"]:
        if spec.get("visible") is False:
            hidden.update(spec["targets"])
    return [c for i, c in enumerate(grid._display.columns) if i not in hidden]


def _populated_grid(group_fields: tuple[str, ...] | None = None):
    from src.layout.grids import UniverseGrid

    meta = _catalog()
    grid = UniverseGrid()
    if group_fields is not None:
        grid.set_group_fields(group_fields)
    grid.update(meta, _up(meta["ticker"]), zcol=_zcol(meta), zname=_Z_NAME)
    return grid


def _up(tickers, windows=("6M", "1Y", "3Y", "5Y")) -> pd.DataFrame:
    """A `universe_perf`-shaped frame: (window, metric) MultiIndex columns."""
    metrics = ["Return", "Vol", "Sharpe", "Max DD"]
    cols = pd.MultiIndex.from_product([list(windows), metrics])
    data = np.arange(len(tickers) * len(cols), dtype=float).reshape(
        len(tickers), len(cols)
    )
    return pd.DataFrame(data, index=pd.Index(tickers, name="ticker"), columns=cols)


# --- the offered windows follow the data, not a wish list -------------------


def test_only_windows_the_price_history_supports_are_offered():
    # A window longer than the fetch has nothing to measure: every row blanks
    # and the column renders as a full column of dashes, which reads as a
    # broken dashboard rather than a pending feature.
    offered = [label for label, _ in config.stat_windows()]
    assert offered == ["6M", "1Y", "3Y", "5Y"]
    assert "10Y" not in offered and "15Y" not in offered
    # They are declared, though — widening the fetch is meant to reveal them
    # with no UI change.
    assert "15Y" in [label for label, _ in config.STAT_WINDOWS]


def test_widening_the_fetch_reveals_the_longer_windows(monkeypatch):
    # The mechanism the note above promises, exercised rather than asserted in
    # a comment: nothing but LOOKBACK_YEARS decides what is on offer.
    monkeypatch.setattr(config, "LOOKBACK_YEARS", 20)
    assert [label for label, _ in config.stat_windows()] == [
        "6M",
        "1Y",
        "3Y",
        "5Y",
        "10Y",
        "15Y",
    ]


def test_a_default_window_the_history_cannot_serve_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "UNIVERSE_GRID_DEFAULT_WINDOW", "15Y")
    with pytest.raises(ValueError, match="15Y"):
        config.universe_grid_default_window()


def test_a_half_year_window_is_labelled_6m_not_zero_point_five_years():
    # `ann_return` and friends take a float, so 0.5 computes correctly; only
    # the label needed somewhere to live.
    assert config.stat_window_label(0.5) == "6M"
    assert config.stat_window_years("6M") == 0.5
    # An unlisted window still labels sensibly, so callers passing their own
    # year tuples keep working.
    assert config.stat_window_label(7) == "7Y"


# --- exactly one window is visible ------------------------------------------


def test_only_the_default_window_is_visible_on_load():
    grid = _populated_grid()
    assert grid.window == config.UNIVERSE_GRID_DEFAULT_WINDOW
    visible = _visible_columns(grid)
    assert [c for c in visible if c.startswith("1Y ")]
    assert not [c for c in visible if c.startswith(("6M ", "3Y ", "5Y "))]


def test_changing_the_window_swaps_exactly_four_columns():
    grid = _populated_grid()
    before = _visible_columns(grid)
    grid.set_window("5Y")
    after = _visible_columns(grid)
    assert [c for c in after if c not in before] == [
        "5Y Return",
        "5Y Vol",
        "5Y Sharpe",
        "5Y Max DD",
    ]
    assert [c for c in before if c not in after] == [
        "1Y Return",
        "1Y Vol",
        "1Y Sharpe",
        "1Y Max DD",
    ]


def test_hidden_windows_stay_in_the_frame():
    # The statistics do not move with the window: every one was computed up
    # front and the ones not on show are hidden, not dropped. That half of the
    # old invariant survives #324 — what changed is that the *ranking* column
    # moves with the window, so the app re-renders around this.
    grid = _populated_grid()
    columns_before = list(grid._display.columns)
    grid.set_window("6M")
    grid.set_window("3Y")
    assert list(grid._display.columns) == columns_before


def test_set_window_records_without_redrawing():
    """`set_window` is a recorder, like `set_group_fields` (#324).

    It used to *be* the window change — options re-sent, columns toggled,
    nothing else moved. The window now also measures the score, so the caller
    re-renders and this would otherwise be a discarded round trip. The
    row-to-ticker map is untouched here precisely because nothing was
    rebuilt; `test_the_window_rebuilds_and_reranks_the_table` is where the
    user-visible behaviour is pinned.
    """
    grid = _populated_grid()
    before = grid._tickers
    display_before = grid._display

    grid.set_window("5Y")

    assert grid.window == "5Y"
    assert grid._tickers == before
    assert grid._display is display_before


def test_window_columns_are_recognised_by_their_prefix_only():
    from src.layout.grids import _window_of

    assert _window_of("1Y Sharpe") == "1Y"
    assert _window_of("6M Max DD") == "6M"
    # The Z-Score label embeds its own window and must not be swept up by the
    # window chips — it is the ranking column, always shown. A *prefix* test is
    # what buys that, under today's header and under the one #324 gives it: a
    # substring test would match the `1Y` sitting inside both.
    assert _window_of("Z-Score Sharpe 1M/1Y") is None
    assert _window_of("Normalized 1Y Sharpe (5Y Z-Score)") is None
    assert _window_of("Name") is None


# An arbitrary header, matching no pattern any helper here knows. #324 already
# moved the real one off the `Z-Score ` stem; this is what proves the column is
# found by the key it was inserted under and not by its text at all.
_RELABELLED_Z_NAME = "Ranking"


def test_the_ranking_column_is_found_by_key_not_by_its_header():
    """The rename guard (#323).

    Four catalog behaviours used to key off `startswith("Z-Score ")`. None of
    them raises on a relabel — the column just quietly becomes a text column
    with no ramp, a substring filter and the wrong units. Renaming it here is
    the only way to catch that before a user does.
    """
    from src.layout.grids import _filter_kinds, _window_of

    meta = _catalog()
    frame, z_key = _build_universe_frame(
        meta, _up(meta["ticker"]), zcol=_zcol(meta), zname=_Z_NAME
    )
    renamed = frame.rename(columns={z_key: _RELABELLED_Z_NAME})
    display, groups = _catalog_display_frame(renamed, _catalog_group_labels())
    position = list(display.columns).index(_RELABELLED_Z_NAME)

    # 1. A comparison filter, not a substring one.
    kinds = _filter_kinds(display, groups, zscore_col=_RELABELLED_Z_NAME)
    assert kinds[position] == "number"

    options = _catalog_table_options(display, groups, zscore_col=_RELABELLED_Z_NAME)
    spec = next(d for d in options["columnDefs"] if d.get("targets") == [position])
    # 2. Rendered as a plain 2dp number — not ×100, which is the percent path.
    assert "* 100" not in str(spec["render"])
    # 3. And on the symmetric z ramp, not the Sharpe one it would inherit from
    #    a header ending in " Sharpe".
    assert str(spec["createdCell"]) == str(_js_heat_cell(_ZSCORE_HEAT_THRESHOLDS))

    # 4. Still out of the window chips' reach.
    assert _window_of(_RELABELLED_Z_NAME) is None


def test_the_header_names_the_sample_it_claims():
    """`Normalized <window> <metric> (<n>Y Z-Score)`, with the `n` derived.

    The header is a promise about what was standardized, so the number in it
    and the sample behind it have to come from the same place. Both are read
    off `LOOKBACK_YEARS`: the label here, and `SCORE_SAMPLE_DAYS` — which
    `render_universe_grid` passes as the z-window — there. A literal `5Y` typed
    into the header would be free to outlive a config change.
    """
    from src.config import LOOKBACK_YEARS, SCORE_SAMPLE_DAYS, TRADING_DAYS_PER_YEAR
    from src.layout.grids import zscore_column_name

    assert zscore_column_name("Sharpe", "1Y") == "Normalized 1Y Sharpe (5Y Z-Score)"
    assert zscore_column_name("Calmar", "6M") == "Normalized 6M Calmar (5Y Z-Score)"

    # The `5Y` is that constant, not a coincidence...
    assert zscore_column_name("Sharpe", "1Y").endswith(f"({LOOKBACK_YEARS}Y Z-Score)")
    # ...and it is the same constant the sample itself is sized from.
    assert SCORE_SAMPLE_DAYS == LOOKBACK_YEARS * TRADING_DAYS_PER_YEAR


def test_a_window_or_metric_change_keeps_every_group_contiguous():
    """RowGroup only gathers adjacent rows, so re-ranking must not fragment a
    group (#273). The window re-ranks now (#324), which is a second way in.
    """
    meta = _catalog()
    up = _up(meta["ticker"])
    ranked = _zcol(meta)
    # A different metric at a different window puts the catalog in a different
    # order — which is the case that could fragment a group.
    reranked = pd.Series(
        dict(zip(meta["ticker"], list(ranked)[::-1], strict=True)),
    )

    grid = _populated_grid(("solution", "category"))
    for zcol, zname in (
        (ranked, _Z_NAME),
        (reranked, zscore_column_name("Sortino", "5Y")),
    ):
        grid.update(meta, up, zcol=zcol, zname=zname)
        labels = _catalog_group_labels(("solution", "category"))
        for depth in range(1, len(labels) + 1):
            # Contiguity is per *path*, not per label: a category name may
            # legitimately recur under a different solution.
            path = list(
                zip(*(grid._display[label] for label in labels[:depth]), strict=True)
            )
            runs = _runs(path)
            assert len(runs) == len(set(runs)), f"{zname} fragments at {depth}"


def test_the_builder_names_the_column_it_inserted():
    """The key travels with the frame, so no consumer re-derives it."""
    meta = _catalog()
    frame, z_key = _build_universe_frame(
        meta, _up(meta["ticker"]), zcol=_zcol(meta), zname=_Z_NAME
    )
    assert z_key == _Z_NAME
    assert z_key in frame.columns

    # No z column asked for, none named — the condition is decided once.
    plain, no_key = _build_universe_frame(meta, _up(meta["ticker"]))
    assert no_key is None
    assert not [c for c in plain.columns if "Z-Score" in str(c)]


def test_the_grid_holds_the_key_across_a_window_switch():
    """`set_window` re-sends options with no data, so it has to read the key
    from the grid rather than from the frame it is not being handed."""
    grid = _populated_grid()
    assert grid._zscore_col == _Z_NAME
    before = grid.table_options()
    grid.set_window("5Y")
    assert grid._zscore_col == _Z_NAME
    columns = list(grid._display.columns)
    position = columns.index(_Z_NAME)
    for options in (before, grid.table_options()):
        spec = next(d for d in options["columnDefs"] if d.get("targets") == [position])
        assert "createdCell" in spec


def test_clearing_the_grid_forgets_the_key():
    grid = _populated_grid()
    grid.clear()
    assert grid._zscore_col is None


# --- the user chooses the grouping ------------------------------------------


def test_asset_class_is_groupable_above_the_tiers():
    assert config.universe_grid_groupable_fields() == (
        "asset_class",
        *config.CLASSIFICATION_TIERS,
    )


def test_nesting_follows_the_hierarchy_not_the_order_boxes_were_ticked():
    # The whole point of the fixed order: the table reads the same however the
    # user got there, so ticking order is not invisible state to remember.
    assert config.universe_grid_group_fields(("family", "asset_class")) == (
        "asset_class",
        "family",
    )
    assert config.universe_grid_group_fields(("asset_class", "family")) == (
        "asset_class",
        "family",
    )


def test_a_field_that_is_not_groupable_is_rejected_by_name():
    with pytest.raises(KeyError, match="currency"):
        config.universe_grid_group_fields(("currency",))


def test_grouping_on_a_subset_groups_only_those_levels():
    grid = _populated_grid(("asset_class", "family"))
    assert grid.group_fields == ("asset_class", "family")
    assert list(grid._display.columns)[:2] == ["Asset Class", "Family"]
    # Solution and Category stay in the body — unchecked levels leave the
    # hierarchy, they are not hidden from the table altogether.
    assert "Solution" in grid._display.columns
    assert "Solution" not in grid._groups


def test_grouping_on_nothing_renders_a_flat_table():
    grid = _populated_grid(())
    assert grid.group_fields == ()
    assert grid._groups == []

    # Explicitly disabled, not merely absent: `ITable.update` merges options,
    # so an omitted `rowGroup` keeps the previous one and the grid carries on
    # grouping by whatever column 0 has become — a header per row, each named
    # after a ticker. Only the browser showed this; "key not in options" was
    # true the whole time.
    assert grid.table_options()["rowGroup"] is False


def test_every_grouping_subset_stays_contiguous_at_every_level():
    # The guarantee RowGroup depends on has to hold for whatever the user
    # picks, not just the default — that is what makes the grouping safe to
    # hand over.
    import itertools

    fields = config.universe_grid_groupable_fields()
    for size in range(1, len(fields) + 1):
        for subset in itertools.combinations(fields, size):
            grid = _populated_grid(subset)
            labels = [config.field_label(k) for k in subset]
            for depth in range(1, len(labels) + 1):
                path = list(
                    zip(
                        *(grid._display[label] for label in labels[:depth]),
                        strict=True,
                    )
                )
                runs = _runs(path)
                assert len(runs) == len(set(runs)), f"{subset} fragments at {depth}"


# --- the search box leads the table from the top-left (#283) ---------------


def test_the_search_box_is_slotted_top_left_and_only_once():
    from src.layout.grids import _catalog_table_options

    layout = _catalog_table_options(_catalog(), [])["layout"]
    assert layout["topStart"] == "search"
    # Cleared explicitly: the default layout object is merged, so leaving
    # `topEnd` alone would draw a second search box on the right.
    assert layout["topEnd"] is None
    assert "search" not in [
        layout["topEnd"],
        layout["bottomStart"],
        layout["bottomEnd"],
    ]
    # The row-count readout stays where it was.
    assert layout["bottomStart"] == "info"


def test_the_search_box_carries_a_placeholder_the_bundle_actually_reads():
    from src.layout.grids import _catalog_table_options

    language = _catalog_table_options(_catalog(), [])["language"]
    # `sSearchPlaceholder`, not the documented camelCase `searchPlaceholder`:
    # this bundle's camelCase map does not carry that key, so the camelCase
    # form would be dropped silently and no placeholder would ever render.
    assert language["sSearchPlaceholder"]
    assert language["sSearch"] == ""  # the "Search:" label, dropped


def test_the_relocated_search_box_keeps_the_dark_chrome():
    from src.layout.html import STYLE_CTX, render_template

    css = render_template("app_css", **STYLE_CTX)
    # The `topStart` cell aligns with `justify-content`, so the feature moving
    # is not enough on its own.
    assert ".dt-layout-cell.dt-layout-start" in css
    assert ".dt-search input::placeholder" in css


def test_moving_the_search_box_leaves_the_scroll_container_alone():
    from src.layout.html import STYLE_CTX, render_template

    # That cell is what keeps header and body in ONE table; the `scrollY` drift
    # recorded in grids.py is what it exists to avoid.
    css = render_template("app_css", **STYLE_CTX)
    assert ".dt-layout-row.dt-layout-table .dt-layout-cell" in css


# --- nested group-header bands (#284) --------------------------------------


def _luminance(color: str) -> float:
    """WCAG relative luminance of an opaque ``#rrggbb`` colour."""

    def _channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast(fill: str, text: str) -> float:
    dark, light = sorted((_luminance(fill), _luminance(text)))
    return (light + 0.05) / (dark + 0.05)


def _bands() -> list[str]:
    from src.layout.html import STYLE_CTX

    return [str(STYLE_CTX[f"group_band{level}"]) for level in range(4)]


def test_every_nesting_level_gets_its_own_band():
    from src.style import Color

    bands = _bands()
    assert len(set(bands)) == 4
    # Level 2 used to be `chrome_bg` — the table body's own colour — so the
    # deepest tier separated from its rows by weight and indent alone.
    assert str(Color.CHROME_BG) not in bands


def test_text_contrast_holds_on_every_band_including_the_brightest():
    from src.style import Color

    # The foreground flips partway down: the two bright fills take dark text,
    # the two deep ones take light text. A band that kept the light text all
    # the way up is exactly the failure this asserts against.
    dark, light = str(Color.CHROME_BG), str(Color.TEXT)
    band0, band1, band2, band3 = _bands()
    for fill, text in ((band0, dark), (band1, dark), (band2, light), (band3, light)):
        assert _contrast(fill, text) >= 4.5, f"{fill} on {text}"
    # And the pairing is the right way round — light text on the brightest
    # fill would fail, which is why it is not used there.
    assert _contrast(band0, light) < 4.5


def test_the_stylesheet_bands_every_reachable_level_and_then_some():
    from src.config import UNIVERSE_GRID_GROUPABLE_FIELDS
    from src.layout.html import STYLE_CTX, render_template

    css = render_template("app_css", **STYLE_CTX)
    deepest = len(UNIVERSE_GRID_GROUPABLE_FIELDS) - 1
    for level in range(deepest + 1):
        assert f"tr.dtrg-group.dtrg-level-{level} th" in css
    # The base rule carries a band of its own, so a level past the named ones
    # renders as a defined band rather than falling through to the body.
    base = css.split("tr.dtrg-group th,")[1].split("}")[0]
    assert "background-color" in base and "color" in base
    # Both elements stay listed: RowGroup emits a `th`, and a td-only rule
    # matches nothing at all.
    assert "tr.dtrg-group td {" in css


# --- per-column filter row (#285) ------------------------------------------
#
# The row itself is built in the browser, so what is asserted here is
# everything that decides whether it *can* work: which columns get an input,
# that the callback reaches DataTables at all through the itables widget, and
# the invariants the JS depends on. The rendered DOM is the manual pass.


def _draw_callback(grid) -> str:

    options = grid.table_options()
    return str(options["drawCallback"])


def test_every_column_gets_a_filter_and_the_numbers_get_a_comparison():
    from src.layout.grids import _filter_kinds

    grid = _populated_grid(("solution",))
    kinds = {
        str(grid._display.columns[p]): kind
        for p, kind in _filter_kinds(
            grid._display, grid._groups, zscore_col=grid._zscore_col
        ).items()
    }

    assert kinds["Name"] == "text" and kinds["Asset Class"] == "text"
    assert kinds["Launch Date"] == "text"
    # The numbers filter by comparison, not by substring (#297). A substring
    # over them is not merely coarse: they render through `_js_number_render`,
    # which hands filtering the raw value, so "5.23" over a cell reading
    # "5.23%" would be searched against 0.0523 and match nothing.
    assert kinds["1Y Sharpe"] == "number"
    assert kinds[_Z_NAME] == "number"
    assert kinds["1Y Return"] == "percent"
    assert kinds["1Y Vol"] == "percent" and kinds["1Y Max DD"] == "percent"
    # Grouped columns are hidden and come back as row-group headers.
    assert "Solution" not in kinds


def test_the_renderer_and_the_filter_agree_on_which_columns_are_percentages():
    """One predicate behind both, or the filter answers in the wrong units.

    The renderer multiplies a Return by 100 to display it; the filter has to
    scale the same columns by the same 100 to compare against what is on
    screen. Written twice they would drift on the next stat metric, and the
    symptom would be a `>1` that matches every row of a percent column.
    """
    from src.layout.grids import _filter_kinds, _is_percent_col

    grid = _populated_grid()
    kinds = _filter_kinds(grid._display, grid._groups, zscore_col=grid._zscore_col)
    options = grid.table_options()

    scaled_in_render = {
        target
        for spec in options["columnDefs"]
        if "render" in spec and "* 100" in str(spec["render"])
        for target in spec["targets"]
    }
    scaled_in_filter = {p for p, kind in kinds.items() if kind == "percent"}
    assert scaled_in_render == scaled_in_filter
    assert scaled_in_filter  # the frame has percent columns at all
    assert all(_is_percent_col(str(grid._display.columns[p])) for p in scaled_in_filter)


def test_the_kinds_do_not_move_with_the_stats_window():
    from src.layout.grids import _filter_kinds

    grid = _populated_grid()
    first = _filter_kinds(grid._display, grid._groups, zscore_col=grid._zscore_col)
    grid.set_window("6M")
    assert (
        _filter_kinds(grid._display, grid._groups, zscore_col=grid._zscore_col) == first
    )


def test_the_filter_row_is_built_from_a_drawcallback_the_widget_forwards():
    from itables import JavascriptFunction

    grid = _populated_grid()
    options = grid.table_options()

    # `drawCallback`, NOT `initComplete`: the itables widget destructures
    # `initComplete` out of the options and calls it only from inside its own
    # wrapper, which it installs only when `column_filters` or
    # `text_in_header_can_be_selected` is set — so a bare `initComplete` is
    # dropped in silence.
    assert isinstance(options["drawCallback"], JavascriptFunction)
    assert "initComplete" not in options
    # And not itables' own column filters: in this build that replaces the
    # header with a flat `<thead><th>…</th></thead>` — no labels, no `<tr>` —
    # and its wrapper only wires inputs it finds, creating none.
    assert "column_filters" not in options


def test_the_callback_reaches_datatables_through_the_widget():
    from itables.javascript import get_itables_extension_arguments

    grid = _populated_grid()
    options = grid.table_options()
    dt_args, _ = get_itables_extension_arguments(grid._display, **options)

    # Present in the args the widget forwards, and registered for evaluation —
    # a JS function that arrives as a string never runs.
    assert "drawCallback" in dt_args
    assert ["drawCallback"] in dt_args["keys_to_be_evaluated"]


def test_the_callback_holds_the_invariants_the_row_depends_on():
    grid = _populated_grid(("solution", "category"))
    js = _draw_callback(grid)

    # Built once: every later draw finds the row intact and returns, so a
    # focused input is never torn out from under someone mid-type. "Intact" is
    # a count of inputs, not the row's existence — see the next test.
    assert "querySelector('tr.bbg-filter-row')" in js
    assert "querySelectorAll('input.bbg-filter-input').length" in js
    # Only visible columns, so a hidden one cannot leave an orphaned input.
    assert "columns(':visible')" in js
    # Matched by data index, which is stable under sorting and filtering.
    assert "this.index()" in js
    # The text survives the destroy-and-rebuild any options change causes:
    # nothing carries it to the kernel, so it is stashed in the browser.
    assert "window.__bbgCatalogFilters" in js
    # Re-applied outside the draw that is running, or it re-enters it.
    assert "setTimeout" in js
    # `input`, not `keyup`: a paste and the clear button of a `type=search`
    # box both change the value with no keystroke behind it.
    assert "addEventListener('input'" in js
    # A numeric column filters by DataTables' own registered predicate, not by
    # `column.search()` — which is a substring over the raw value, so it reads
    # a percent column in fractions (#297).
    assert "column.search.fixed('bbg'" in js
    # Probed, not assumed: a bundle without it would throw inside this callback
    # and take the text filters down with it, so it degrades to numeric columns
    # with no input — where they were before #297.
    assert "api.columns().search.fixed" in js


def test_the_filter_cells_are_td_so_itables_cannot_empty_them():
    """The regression that left the row rendering blank.

    itables leaves `text_in_header_can_be_selected` on by default, and the
    wrapper it installs walks `$("thead th", …)` in `initComplete` — which runs
    *after* the first draw, so after this callback — and `.empty()`s every cell
    whose `span.dt-column-title` is missing or blank. A filter cell has an
    input and no title, so every one of them was emptied: the `<tr>` survived
    with the right number of cells and not one input in it, which is
    indistinguishable from a callback that never ran.
    """
    js = _draw_callback(_populated_grid())
    assert "createElement('td')" in js
    assert "createElement('th')" not in js


def test_the_itables_pass_that_forced_that_choice_is_still_there():
    # Grounds the test above in the dependency rather than in a memory of it:
    # if a future itables stops emptying untitled `thead th` cells — or widens
    # the selector to `td` — this fails and the choice gets re-made against
    # what the bundle actually does.
    from pathlib import Path

    import itables.widget

    bundle = Path(itables.widget.__file__).parent / "static" / "widget.js"
    if not bundle.exists():  # pragma: no cover - a source layout we don't ship
        pytest.skip("itables widget bundle not found")
    js = bundle.read_text(encoding="utf-8")
    assert '"thead th"' in js
    assert "text_in_header_can_be_selected" in js


def test_the_datatables_api_the_numeric_filter_calls_is_in_the_bundle():
    """Grounds the numeric filter in the dependency rather than in the docs.

    `column().search.fixed()` is how a column filters by predicate instead of
    by substring — the same API DataTables' own ColumnControl extension filters
    numbers with. The callback probes for it and degrades quietly, so an
    upgrade that dropped it would show up as numeric boxes that stopped
    appearing, with nothing failing. This fails instead.
    """
    from pathlib import Path

    import itables.widget

    bundle = Path(itables.widget.__file__).parent / "static" / "widget.js"
    if not bundle.exists():  # pragma: no cover - a source layout we don't ship
        pytest.skip("itables widget bundle not found")
    assert "column().search.fixed()" in bundle.read_text(encoding="utf-8")


# The grammar a numeric box accepts is JavaScript, and the only honest way to
# assert what it accepts is to run it. `_JS_NUMBER_PREDICATE` is a module
# constant precisely so that can happen without a browser: node evaluates the
# one function, with no DOM and no DataTables around it. The rest of the row
# still needs the rendered pass — see `testing_notes.md`.


def _grammar(cases: list[tuple[str, float, object]]) -> list:
    """Run `(expression, scale, value)` triples through the parser in node.

    Returns `"empty"` for an expression that filters nothing, `"invalid"` for
    one that does not parse, and the predicate's verdict otherwise — the three
    outcomes the callback distinguishes.
    """
    import json
    import shutil
    import subprocess

    from src.layout.grids import _JS_NUMBER_PREDICATE

    node = shutil.which("node")
    if node is None:  # pragma: no cover - node is present on CI's runner
        pytest.skip("node is needed to run the filter grammar")
    script = (
        f"const parse = {_JS_NUMBER_PREDICATE};"
        f"const cases = {json.dumps(cases)};"
        "console.log(JSON.stringify(cases.map(function (c) {"
        "  const test = parse(c[0], c[1]);"
        "  if (test === null) { return 'empty'; }"
        "  if (test === false) { return 'invalid'; }"
        "  return test(c[2]);"
        "})));"
    )
    done = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


def test_the_numeric_grammar_accepts_the_comparisons_it_advertises():
    assert _grammar(
        [
            (">1", 1, 1.5),
            (">1", 1, 1.0),
            (">=1", 1, 1.0),
            ("<0", 1, -0.2),
            ("<0", 1, 0.1),
            ("<=-0.5", 1, -0.5),
            ("1..3", 1, 3.0),
            ("1..3", 1, 3.01),
            ("-1..-0.5", 1, -0.75),
            # Whitespace and thousands separators are noise, not syntax.
            (" > 1 ", 1, 2.0),
            ("1,500", 1, 1500.0),
        ]
    ) == [True, False, True, True, False, True, True, False, True, True, True]


def test_a_bare_number_matches_at_the_precision_typed():
    """ "1.2" is the neighbourhood of 1.2, not the float that is exactly it.

    A browse surface asks for "about 1.2", and the column renders to two
    decimals — exact equality would be a box that stays empty for most of what
    is on screen. So the digits typed set the band: 1.2 is [1.15, 1.25], 5 is
    [4.5, 5.5].
    """
    assert _grammar(
        [
            ("1.2", 1, 1.24),
            ("1.2", 1, 1.15),
            ("1.2", 1, 1.26),
            ("5", 1, 5.4),
            ("5", 1, 5.6),
            ("=1.23", 1, 1.23),
            ("=1.23", 1, 1.3),
        ]
    ) == [True, True, False, True, False, True, False]


def test_a_percent_column_is_filtered_in_the_units_it_renders():
    # A Return cell holds 0.0523 and reads "5.23%". The user types what they
    # can see, so the scale the renderer applies is the scale the filter
    # compares in — without it `>5` would match every row in the catalog.
    assert _grammar(
        [
            (">5", 100, 0.0523),
            (">5", 100, 0.04),
            ("5.23", 100, 0.0523),
            # The `%` someone copies off the screen is stripped, not rejected.
            (">5%", 100, 0.0523),
        ]
    ) == [True, False, True, True]


def test_an_empty_box_a_half_typed_one_and_a_blank_cell_are_all_distinct():
    # ">" alone is what every ">1" passes through on its way to being typed.
    # Treating it as a filter of zero rows would empty the table under the
    # user's hands mid-keystroke; it leaves the column alone and marks the box.
    assert _grammar(
        [
            ("", 1, 1.0),
            ("   ", 1, 1.0),
            (">", 1, 1.0),
            ("abc", 1, 1.0),
            ("1..", 1, 1.0),
            # A dash cell is not a number and matches no comparison, so the
            # blanks drop out of a filtered column instead of riding along.
            (">-999", 1, None),
            ("<1", 1, ""),
        ]
    ) == ["empty", "empty", "invalid", "invalid", "invalid", False, False]


def test_the_sticky_filter_row_clears_the_labels_it_sits_under():
    from src.layout.html import STYLE_CTX, render_template
    from src.style import CATALOG_HEADER_ROW_HEIGHT

    css = render_template("app_css", **STYLE_CTX)
    # One token drives both the label row's height and the filter row's sticky
    # offset. Written separately they would drift, and the symptom would be a
    # filter row parked over the labels.
    assert f"height: {CATALOG_HEADER_ROW_HEIGHT} !important" in css
    assert f"top: {CATALOG_HEADER_ROW_HEIGHT} !important" in css
    assert ".bbg-filter-input" in css
    # A `td` inherits none of the `thead th` chrome, so the filter cells carry
    # their own pin and their own opaque surface — without which the body
    # scrolls straight through the row that is supposed to be pinned over it.
    cell = "tr.bbg-filter-row td.bbg-filter-cell"
    block = css.split(cell, 1)[-1].split("}", 1)[0]
    assert cell in css
    assert "position: sticky" in block
    assert "background-color" in block


def test_a_numeric_filter_box_reads_as_one_and_flags_what_it_cannot_parse():
    from src.layout.html import STYLE_CTX, render_template

    css = render_template("app_css", **STYLE_CTX)
    # The mono face and right alignment say "this column takes a number", which
    # is the only hint besides the placeholder that it is not a substring box.
    assert ".bbg-filter-input.bbg-filter-number" in css
    # Half-typed text leaves the column unfiltered, so the box is the only
    # place the user can see that nothing is being applied yet.
    assert ".bbg-filter-input.bbg-filter-invalid" in css


def test_the_strips_around_the_table_are_painted_with_the_table():
    """#340 — the search row and row-count readout sat on the bundle's white.

    They have no background of their own: they are the container showing
    through where the table does not cover it. The widget bundle paints that
    container from `--dt-html-background`, which its own stylesheet defines as
    `white`, so the strips rendered light under text already themed for navy.

    What is assertable here is that the rules exist and carry the table's own
    colour. Whether the strips *draw* dark is a render question — the #255
    lesson — so the screenshot on the PR is the other half of the evidence.
    """
    from src.layout.html import STYLE_CTX, render_template
    from src.style import Color

    # Comments go first: the rule's own commentary quotes the bundle's
    # `--dt-html-background: white`, which a plain substring search would
    # find before the declaration that overrides it.
    css = re.sub(r"/\*.*?\*/", "", render_template("app_css", **STYLE_CTX), flags=re.S)

    painted = [b for b in css.split("}") if "--dt-html-background" in b]
    assert painted, "nothing redefines --dt-html-background; the bundle's white wins"
    rule = painted[0]
    # Redefining the bundle's property is the fix at its source: its own rules
    # keep painting, in our colour. The explicit background beside it is the
    # belt for a bundle that stopped reading the property.
    assert f"--dt-html-background: {Color.CHROME_BG};" in rule
    assert f"background-color: {Color.CHROME_BG} !important" in rule
    # The container is painted too, not only the widget host — it is the
    # element the strips actually sit on.
    assert ".dt-container" in rule.split("{", 1)[0]
    # `chrome_bg`, not `surface`: the strips read as part of the table, whose
    # own base this is. A header-coloured band above and below would not.
    assert Color.CHROME_BG != Color.SURFACE
    # Preserved: the scroll cell keeps its own rules. It is the nearest
    # scrolling ancestor of the sticky header, so a background must not have
    # arrived with an `overflow` or a `height` beside it.
    scroll = "div.itables_anywidget .dt-layout-row.dt-layout-table .dt-layout-cell"
    assert scroll in css
    assert "overflow: auto" in css.split(scroll, 1)[-1].split("}", 1)[0]


# --- the table claims the width between the rails (#280) -------------------
#
# What is assertable here is that the rules exist and compose: the flex share,
# the `min-width: 0` that lets the item shrink, and the width rules inside the
# cell. Whether the result fits a real BQuant viewport is a measurement, and
# it is on the manual checklist rather than here.


def test_the_table_widget_takes_the_whole_width_and_can_shrink():
    from src.layout.grids import UniverseGrid

    layout = UniverseGrid().widget.layout
    assert layout.width == "100%"
    # The flex share that gave it "whatever the rail leaves" went with the rail
    # (#326). Keeping it would be worse than useless: the Platform panel is a
    # column, so a `0%` basis applies to the HEIGHT and would fight the fixed
    # box below.
    assert layout.flex is None
    # `min_width` stays. It is no longer what keeps a wide column set inside
    # the table — `.dt-layout-cell`'s own `overflow: auto` does that — but it
    # is the guard that made the row work, and a flex item's default
    # `min-width: auto` refusing to shrink below its content is #280.
    assert layout.min_width == "0"


def test_the_table_fills_its_cell_from_the_inside_too():
    from src.layout.html import STYLE_CTX, render_template

    css = re.sub(r"/\*.*?\*/", "", render_template("app_css", **STYLE_CTX), flags=re.S)
    # The widget, DataTables' own wrapper, and the table itself. Widening the
    # outer widget alone moves the dead space rather than removing it.
    #
    # These selectors carry more than one rule — #340 paints them as well — so
    # the width rule is the one to read, not whichever comes first.
    rule = next(
        r
        for r in css.split("}")
        if "div.itables_anywidget.bbg-catalog," in r and "width: 100%" in r
    )
    assert ".dt-container" in rule and "table.dataTable" in rule
    assert "width: 100% !important" in rule


def test_a_too_wide_column_set_scrolls_inside_the_table():
    from src.layout.html import STYLE_CTX, render_template

    css = render_template("app_css", **STYLE_CTX)
    # The same cell that makes the header sticky is the scroll container, so
    # the overflow stays inside the table and the rails keep their place.
    cell = css.split(".dt-layout-row.dt-layout-table .dt-layout-cell {")[1].split("}")[
        0
    ]
    assert "overflow: auto" in cell
