"""The rail component and its chip groups (#277).

These cover the two contracts the rest of epic #276 leans on: that a chip's
selected state is a CSS *class* (so the hover/focus rules keep working), and
that a chip group presents the `W.Dropdown` surface — `value`, `label`,
`observe` — the call sites it replaces already read (#279).
"""

from __future__ import annotations

import pytest
from src.layout.chrome import _make_chip, _style_chip
from src.layout.html import STYLE_CTX, render_template
from src.layout.rails import ChipGroup, MultiChipGroup, RailSection, control_rail

WINDOWS = ["1M", "6M", "1Y"]
TIERS = [("Solution", "solution"), ("Category", "category"), ("Family", "family")]


def _classes(widget) -> list[str]:
    return list(widget._dom_classes)


# --- chips: the state is a class, never inline colour ----------------------


def test_a_chip_carries_the_pill_family_and_its_own_type():
    chip = _make_chip("1Y", active=False)
    assert "bbg-pill" in _classes(chip)
    assert "bbg-chip" in _classes(chip)


def test_styling_a_chip_toggles_the_class_both_ways():
    chip = _make_chip("1Y", active=False)
    assert "is-active" not in _classes(chip)
    _style_chip(chip, active=True)
    assert "is-active" in _classes(chip)
    _style_chip(chip, active=False)
    assert "is-active" not in _classes(chip)


def test_styling_a_chip_never_writes_an_inline_colour():
    # Inline button colours outrank the `:hover` / `:focus-visible` rules in
    # app_css.html, so a chip styled that way would render dead.
    chip = _make_chip("1Y", active=False)
    _style_chip(chip, active=True)
    assert chip.style.button_color is None


def test_the_rail_and_chip_types_are_defined_in_the_stylesheet():
    css = render_template("app_css", **STYLE_CTX)
    for selector in (".bbg-rail", ".bbg-rail-heading", ".bbg-chip"):
        assert selector in css
    for state in (".bbg-chip:hover", ".bbg-chip.is-active", ".bbg-chip:focus-visible"):
        assert state in css


# --- ChipGroup: a dropdown's surface over a stack of buttons ---------------


def test_a_group_starts_on_the_value_it_was_given():
    group = ChipGroup(WINDOWS, value="6M")
    assert group.value == "6M"
    assert group.label == "6M"
    assert _classes(group.children[1]).count("is-active") == 1
    assert "is-active" not in _classes(group.children[0])


def test_a_group_defaults_to_its_first_option():
    assert ChipGroup(WINDOWS).value == "1M"


def test_clicking_a_chip_moves_the_value_and_the_active_class():
    group = ChipGroup(WINDOWS)
    group.children[2].click()
    assert group.value == "1Y"
    assert "is-active" in _classes(group.children[2])
    assert "is-active" not in _classes(group.children[0])


def test_a_group_notifies_observers_the_way_a_dropdown_does():
    seen = []
    group = ChipGroup(WINDOWS)
    group.observe(lambda change: seen.append(change["new"]), names="value")
    group.children[1].click()
    group.value = "1Y"
    assert seen == ["6M", "1Y"]


def test_a_group_separates_the_label_from_the_value():
    # The z-score rail titles its column from `.label` while computing from
    # `.value` (#279), so the two cannot be the same field.
    group = ChipGroup(TIERS, value="category")
    assert (group.value, group.label) == ("category", "Category")
    group.children[2].click()
    assert (group.value, group.label) == ("family", "Family")


def test_a_group_refuses_a_value_it_does_not_offer():
    group = ChipGroup(WINDOWS)
    with pytest.raises(ValueError):
        group.value = "10Y"
    assert group.value == "1M"


def test_a_group_needs_at_least_one_option():
    with pytest.raises(ValueError):
        ChipGroup([])


# --- MultiChipGroup: membership, never click order -------------------------


def test_a_multi_group_starts_empty_unless_told_otherwise():
    assert MultiChipGroup(TIERS).value == ()
    assert MultiChipGroup(TIERS, value=["family"]).value == ("family",)


def test_clicking_toggles_membership_on_and_off():
    group = MultiChipGroup(TIERS)
    group.children[0].click()
    assert group.value == ("solution",)
    assert "is-active" in _classes(group.children[0])
    group.children[0].click()
    assert group.value == ()
    assert "is-active" not in _classes(group.children[0])


def test_click_order_cannot_reach_the_value():
    # The catalog grid nests by the hierarchy and never by the order the user
    # ticked (#273) — so the group must not be able to report one.
    forwards = MultiChipGroup(TIERS)
    forwards.children[0].click()
    forwards.children[2].click()

    backwards = MultiChipGroup(TIERS)
    backwards.children[2].click()
    backwards.children[0].click()

    assert forwards.value == backwards.value == ("solution", "family")


def test_assigning_a_value_is_normalized_into_options_order():
    group = MultiChipGroup(TIERS, value=["family", "solution"])
    assert group.value == ("solution", "family")


# --- the rail builder ------------------------------------------------------


def test_a_rail_composes_its_sections_in_order():
    windows = ChipGroup(WINDOWS)
    tiers = MultiChipGroup(TIERS)
    rail = control_rail(RailSection("Group by", tiers), RailSection("Window", windows))

    headings = [c for c in rail.children if "bbg-rail-heading" in _classes(c)]
    assert [h.value for h in headings] == ["Group by", "Window"]
    assert list(rail.children) == [headings[0], tiers, headings[1], windows]


def test_a_rail_is_typed_and_holds_its_basis():
    rail = control_rail(RailSection("Window", ChipGroup(WINDOWS)), width="210px")
    assert "bbg-rail" in _classes(rail)
    assert rail.layout.width == "210px"
    # It must not flex: the table between the rails absorbs the width (#280).
    assert rail.layout.flex == "0 0 210px"


def test_a_rail_can_carry_a_title_above_its_sections():
    # A rail whose sections are facets of one control says so once (#279).
    rail = control_rail(
        RailSection("Metric", ChipGroup(WINDOWS)),
        RailSection("Window", ChipGroup(WINDOWS)),
        title="Z-Score ranking",
    )
    assert "bbg-rail-title" in _classes(rail.children[0])
    assert rail.children[0].value == "Z-Score ranking"


def test_a_rail_without_a_title_renders_none():
    rail = control_rail(RailSection("Window", ChipGroup(WINDOWS)))
    assert not any("bbg-rail-title" in _classes(c) for c in rail.children)
    assert "bbg-rail-title" in render_template("app_css", **STYLE_CTX)
