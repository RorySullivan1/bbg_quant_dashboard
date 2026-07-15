"""The Multi-Strategy strategy picker (v0.9.11 visual edits).

The picker is now a `CheckboxMultiSelect` — a scrollable checkbox list that is a
drop-in for `W.SelectMultiple` (`options` / `value` traits + `observe`) — and a
"Clear" button to the right of the search box wipes the strategy selection
(distinct from "Clear all", which keeps the picked strategies).
"""

from __future__ import annotations

import ipywidgets as W
from src.layout import build_app
from src.layout.filters import CheckboxMultiSelect


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _mount_multi_strategy(app) -> None:
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == "Multi-Strategy"
    ).click()


# --- CheckboxMultiSelect: SelectMultiple-compatible surface ------------------


def _opts():
    return [("AAA — Alpha", "AAA"), ("BBB — Bravo", "BBB"), ("CCC — Chuck", "CCC")]


def test_checkbox_multiselect_renders_a_row_per_option():
    m = CheckboxMultiSelect(options=_opts(), value=("BBB",))
    assert len(m.children) == 3
    assert all(isinstance(c, W.Checkbox) for c in m.children)
    # The pre-selected value is checked; the others are not.
    checked = [c.description for c in m.children if c.value]
    assert checked == ["BBB — Bravo"]


def test_checkbox_toggle_updates_value_and_value_updates_checks():
    m = CheckboxMultiSelect(options=_opts(), value=())
    m.children[0].value = True  # tick AAA
    assert set(m.value) == {"AAA"}
    # Setting value programmatically reflects back onto the checkboxes.
    m.value = ("CCC",)
    assert [c.value for c in m.children] == [False, False, True]


def test_checkbox_options_reset_drops_missing_selection():
    m = CheckboxMultiSelect(options=_opts(), value=("CCC",))
    m.options = [("BBB — Bravo", "BBB"), ("DDD — Delta", "DDD")]
    # CCC is gone from the options, so it drops out of value (SelectMultiple
    # parity); still-present selections would survive.
    assert set(m.value) == set()
    assert len(m.children) == 2


def test_checkbox_multiselect_reuses_widgets_across_option_changes():
    # Search narrows `options` on every keystroke; the checkbox widgets must be
    # reused (not rebuilt) so the list stays responsive.
    opts = [(f"T{i} — N{i}", f"T{i}") for i in range(20)]
    m = CheckboxMultiSelect(options=opts, value=())
    original = {id(cb) for cb in m.children}
    m.options = opts[:5]  # narrow (like a search)
    assert {id(cb) for cb in m.children} <= original  # reused, not recreated
    m.options = opts  # widen back
    assert {id(cb) for cb in m.children} == original  # exact same widget objects


def test_checkbox_multiselect_fires_value_observers():
    m = CheckboxMultiSelect(options=_opts(), value=())
    seen = []
    m.observe(lambda c: seen.append(tuple(sorted(c["new"]))), names="value")
    m.children[1].value = True  # tick BBB
    assert seen == [("BBB",)]


# --- Wired into the app ------------------------------------------------------


def test_multi_strategy_picker_is_a_checkbox_list():
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    picker = next(w for w in _walk(app) if isinstance(w, CheckboxMultiSelect))
    assert len(picker.children) >= 1
    assert all(isinstance(c, W.Checkbox) for c in picker.children)
    # Capped height + scroll — the list must NOT grow to fill the panel; it's
    # bounded to the same 240px as the categorical filter groups.
    assert picker.layout.max_height == "240px"
    assert picker.layout.overflow == "auto"
    assert picker.layout.flex is None


def test_clear_button_clears_the_strategy_selection():
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    picker = next(w for w in _walk(app) if isinstance(w, CheckboxMultiSelect))
    assert len(picker.value) > 0  # startup seeds a selection

    clear_btn = next(
        w for w in _walk(app) if isinstance(w, W.Button) and w.description == "Clear"
    )
    clear_btn.click()
    assert picker.value == ()
    assert not any(c.value for c in picker.children)


# --- Shared filter panel (v0.9.12-review #155) -------------------------------


def _click(app, description):
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == description
    ).click()


def test_multi_strategy_filter_narrows_picker_via_shared_panel():
    """The Multi-Strategy tab drives `make_filter_panel` — a live filter change
    narrows the strategy picker (no Refresh needed)."""
    app = build_app(verbose=False)
    _mount_multi_strategy(app)
    panel = app.children[5].children[0]
    picker = next(w for w in _walk(panel) if isinstance(w, CheckboxMultiSelect))
    n_all = len(picker.options)
    assert n_all > 0

    # The Refresh + Clear controls all live in the shared panel's action row.
    labels = {w.description for w in _walk(panel) if isinstance(w, W.Button)}
    assert {"Refresh prices", "Clear section", "Clear all"} <= labels

    # Clear the seeded selection so the keep-selected union can't mask narrowing.
    _click(app, "Clear")
    assert picker.value == ()

    # An impossible quant threshold (Sharpe ≥ 1e6) filters everything out — proof
    # the quant reducer is wired through the shared panel.
    _click(app, "Quantitative")
    value_boxes = [
        w for w in _walk(panel) if isinstance(w, W.Text) and w.placeholder == "value"
    ]
    assert len(value_boxes) == 9  # one per quant metric
    value_boxes[0].value = "1000000"
    assert len(picker.options) == 0

    # Clearing the quant box restores the full catalog live.
    value_boxes[0].value = ""
    assert len(picker.options) == n_all


def test_no_inline_filter_duplication_in_builder():
    """Regression guard for #155: the Multi-Strategy filter must stay on the
    shared `make_filter_panel` and not re-grow an inline copy of the widget
    construction / quant reducer in builder.py."""
    from pathlib import Path

    src = Path("src/layout/builder.py").read_text()
    assert "from .filter_panel import make_filter_panel" in src
    assert "make_filter_panel(" in src
    # The quant reducer + row factories now live only in filter_panel.py.
    assert "def _quant_keep" not in src
    assert "def _quant_thresholds" not in src
    assert "_q_row(" not in src
