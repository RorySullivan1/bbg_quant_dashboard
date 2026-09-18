"""The rail component and its chip groups (#277).

These cover the two contracts the rest of epic #276 leans on: that a chip's
selected state is a CSS *class* (so the hover/focus rules keep working), and
that a chip group presents the `W.Dropdown` surface — `value`, `label`,
`observe` — the call sites it replaces already read (#279).
"""

from __future__ import annotations

import re

import ipywidgets as W
import pytest
from src.layout.chrome import _make_chip, _style_chip
from src.layout.html import STYLE_CTX, render_template
from src.layout.rails import (
    ChipGroup,
    MultiChipGroup,
    RailSection,
    control_bar,
    section_panel,
)
from src.style import (
    COMMENTARY_BOX_HEIGHT,
    COMMENTARY_BULLETIN_SHARE,
    COMMENTARY_LEADERBOARD_SHARE,
    Color,
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


# --- the bar builder -------------------------------------------------------
#
# These covered `control_rail` until #326 removed it. The behaviours are the
# component's, not the column's, so they moved to the one that survives rather
# than going with it.


def test_a_bar_composes_its_sections_in_order():
    windows = ChipGroup(WINDOWS, row=True)
    tiers = MultiChipGroup(TIERS, row=True)
    bar = control_bar(RailSection("Group by", tiers), RailSection("Window", windows))

    blocks = [c for c in bar.children if "bbg-rail-block" in _classes(c)]
    assert [b.children[0].value for b in blocks] == ["Group by", "Window"]
    assert [b.children[1] for b in blocks] == [tiers, windows]


def test_a_bar_is_typed_and_its_sections_do_not_squeeze():
    bar = control_bar(RailSection("Window", ChipGroup(WINDOWS, row=True)))
    # `.bbg-rail` is the surface, `.bbg-rail-bar` the direction — the second is
    # what the stylesheet keys the across layout off (#326).
    assert "bbg-rail" in _classes(bar)
    assert "bbg-rail-bar" in _classes(bar)
    (block,) = [c for c in bar.children if "bbg-rail-block" in _classes(c)]
    # A flex item shrinks before its container gives way, so a bar with more
    # chips than fit would squeeze them flat rather than wrap.
    assert block.layout.flex == "0 0 auto"


def test_a_bar_can_carry_a_title_beside_its_sections():
    # A bar whose sections are facets of one thing says so once (#279, #325):
    # Group by / Metric / Window are three facets of the table view.
    bar = control_bar(
        RailSection("Metric", ChipGroup(WINDOWS, row=True)),
        RailSection("Window", ChipGroup(WINDOWS, row=True)),
        title="Table view",
    )
    assert "bbg-rail-title" in _classes(bar.children[0])
    assert bar.children[0].value == "Table view"


def test_a_bar_without_a_title_renders_none():
    bar = control_bar(RailSection("Window", ChipGroup(WINDOWS, row=True)))
    assert not any("bbg-rail-title" in _classes(c) for c in bar.children)
    assert "bbg-rail-title" in render_template("app_css", **STYLE_CTX)


def test_the_rail_component_is_gone():
    """#326 removed the column and everything that only served it.

    A component nothing reads is one more thing to keep in step with the rest
    of the chrome — the argument that retired `WINDOW_LABELS` in #306.
    """
    import src.layout.rails as rails

    assert not hasattr(rails, "control_rail")
    assert not hasattr(rails, "RAIL_WIDTH")
    css = render_template("app_css", **STYLE_CTX)
    # The stacked-column rules go; the surface they were drawn on stays,
    # because the bar is drawn on it too.
    assert ".bbg-rail > .bbg-rail-heading" not in css
    assert ".bbg-app .bbg-rail {" in css


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
    """The catalog table's type, not `_rail_title`'s.

    The rail's title is the accent, uppercase, underlined type that belongs
    *inside* a rail. Using it here would put two competing title treatments on
    one screen, which is the drift this component exists to prevent.

    `section_title` is a separate template from `grid_header` only because
    `_substitute` leaves an unfilled `{{note}}` on screen, so the slot could
    not be added to the template seven other call sites share. The *type* must
    still match, and this is what says so: the title's weight and size are read
    out of `grid_header` rather than spelled here, so a change to one that is
    not made to the other fails.
    """
    panel = _panel()
    title = panel.children[0]

    assert "bbg-rail-title" not in _classes(title)
    assert not any("bbg-rail-title" in _classes(c) for c in panel.children)
    assert "Leaderboard" in title.value

    header = render_template("grid_header", **STYLE_CTX, text="x")
    for declaration in ("font-weight:600", "font-size:"):
        assert declaration in header
    # The size token the header uses, whatever it is, is the one the title uses.
    (size,) = re.findall(r"font-size:([^;]+);", header)
    assert f"font-weight:600;font-size:{size};" in title.value


def test_a_panel_takes_an_optional_note_beside_its_title():
    """A caption, not a second title — it qualifies the heading rather than
    competing with it, so it is lighter, smaller and muted."""
    panel = _panel()  # no note
    plain = panel.children[0].value

    noted = section_panel(
        "Leaderboard",
        control_bar(RailSection("Window", ChipGroup(WINDOWS))),
        W.HTML("body"),
        height="300px",
        note="(Ranked By Normalized 5Y Z-Score)",
    ).children[0]

    assert "(Ranked By Normalized 5Y Z-Score)" in noted.value
    assert "Leaderboard" in noted.value
    # Absent by default, and an empty note leaves nothing visible behind —
    # the span is still emitted, so it must render as no text at all.
    assert "Ranked By" not in plain
    (empty,) = re.findall(r"color:[^']*'>([^<]*)</span>", plain)
    assert empty == ""

    # The note is weaker type than the title it sits beside.
    assert "font-weight:400" in noted.value
    assert str(Color.TEXT_MUTED) in noted.value


def test_a_note_is_escaped_like_any_other_dynamic_text():
    panel = section_panel(
        "T",
        control_bar(RailSection("W", ChipGroup(WINDOWS))),
        W.HTML("body"),
        height="300px",
        note="<script>& 5Y",
    )

    value = panel.children[0].value
    assert "<script>" not in value
    assert "&lt;script&gt;&amp; 5Y" in value


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
    # A fixed height alone does not scroll a flex child: without `min-height`
    # it refuses to shrink below its content and the body pushes the box open.
    # (`.bbg-rail` carried the same pair until #326, when the stretched column
    # it was for went away.)
    assert "min-height: 0;" in box
    assert "overflow-y: auto;" in box


def test_the_two_shares_are_one_ratio():
    left = int(COMMENTARY_LEADERBOARD_SHARE.rstrip("%"))
    right = int(COMMENTARY_BULLETIN_SHARE.rstrip("%"))

    assert (left, right) == (60, 40)
    assert left + right == 100
