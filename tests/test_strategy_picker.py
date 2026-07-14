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
