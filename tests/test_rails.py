"""The rail component and its chip groups (#277).

These cover the two contracts the rest of epic #276 leans on: that a chip's
selected state is a CSS *class* (so the hover/focus rules keep working), and
that a chip group presents the `W.Dropdown` surface — `value`, `label`,
`observe` — the call sites it replaces already read (#279).
"""

from __future__ import annotations

import ipywidgets as W
import pytest
from src.layout.chrome import _make_chip, _style_chip
from src.layout.html import STYLE_CTX, render_template
from src.layout.rails import (
    ChipGroup,
    MultiChipGroup,
    RailSection,
    control_bar,
    control_rail,
    section_panel,
)
from src.style import (
    COMMENTARY_BOX_HEIGHT,
    COMMENTARY_BULLETIN_SHARE,
    COMMENTARY_LEADERBOARD_SHARE,
)

WINDOWS = ["1M", "6M", "1Y"]
TIERS = [("Solution", "solution"), ("Category", "category"), ("Family", "family")]


def _classes(widget) -> list[str]:
    return list(widget._dom_classes)


def _declarations(css: str, selector: str) -> list[str]:
    """The declaration lines of one rule, for per-property assertions."""
    block = css.split(selector + " {", 1)[1].split("}", 1)[0]
    return [line.strip() for line in block.splitlines() if line.strip()]


def _panel(title: str = "Leaderboard", height: str = COMMENTARY_BOX_HEIGHT):
    bar = control_bar(RailSection("Window", ChipGroup(WINDOWS)))
    return section_panel(title, bar, W.HTML("body"), height=height)


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


# --- section_panel: the shape the Platform tab already had (#305) ----------
#
# The commentary block's two sections and the Platform tab's table surface all
# read as title line -> chip row -> boxed body. These pin the shell so the
# three cannot drift; #306 and #307 put the two sections into it.


def test_a_panel_is_a_title_a_bar_and_a_boxed_body_in_that_order():
    bar = control_bar(RailSection("Window", ChipGroup(WINDOWS)))
    body = W.HTML("body")
    panel = section_panel("Leaderboard", bar, body, height="300px")

    title, mounted_bar, box = panel.children
    assert mounted_bar is bar
    assert list(box.children) == [body]
    assert "Leaderboard" in title.value


def test_a_panel_titles_itself_the_way_the_catalog_table_does():
    """`grid_header`, not `_rail_title`.

    The rail's title is the accent, uppercase, underlined type that belongs
    *inside* a rail. Using it here would put two competing title treatments on
    one screen, which is the drift this component exists to prevent.
    """
    panel = _panel()
    title = panel.children[0]

    assert "bbg-rail-title" not in _classes(title)
    assert not any("bbg-rail-title" in _classes(c) for c in panel.children)
    assert title.value == render_template(
        "grid_header", **STYLE_CTX, text="Leaderboard"
    )


def test_the_box_is_typed_and_holds_the_height_it_was_given():
    box = _panel(height="360px").children[2]

    assert "bbg-section-box" in _classes(box)
    assert box.layout.height == "360px"
    # The load-bearing half: a flex child refuses to shrink below its content,
    # so without this the box grows instead of scrolling inside its height.
    assert box.layout.min_height == "0"


def test_two_panels_built_from_one_token_stand_at_one_height():
    # What #308's 60:40 row relies on: neither section can set the row for the
    # other. Asserted here, where the component is, and not only where it is used.
    left, right = _panel("Leaderboard"), _panel("QIS Bulletin")

    assert left.children[2].layout.height == right.children[2].layout.height
    assert left.children[2].layout.height == COMMENTARY_BOX_HEIGHT


def test_the_box_wears_the_catalog_table_s_chrome_and_not_a_card_s():
    css = render_template("app_css", **STYLE_CTX)
    box = _declarations(css, ".bbg-app .bbg-section-box")

    # The table's radius, not `.bbg-card`'s 8px — the two are a pixel apart on
    # screen and a section that took the card's would read as a different kind
    # of container standing beside the table.
    assert "border-radius: 6px;" in box
    assert "border-radius: 6px;" in _declarations(
        css, "div.itables_anywidget.bbg-catalog"
    )
    assert "border-radius: 8px;" in _declarations(css, ".bbg-app .bbg-card")
    # It scrolls the way a rail does, and for the same reason.
    assert "min-height: 0;" in box
    assert "overflow-y: auto;" in box
    assert "min-height: 0;" in _declarations(css, ".bbg-app .bbg-rail")


def test_the_two_shares_are_one_ratio():
    left = int(COMMENTARY_LEADERBOARD_SHARE.rstrip("%"))
    right = int(COMMENTARY_BULLETIN_SHARE.rstrip("%"))

    assert (left, right) == (60, 40)
    assert left + right == 100
