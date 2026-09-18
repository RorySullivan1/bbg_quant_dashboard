"""The QIS Bulletin's `CommentaryPane` (v0.9.20 #289, reshaped v0.9.22 #307).

Two things carry the pane: which board the container currently holds, and which
chip is lit. They are set by the same call, so every switching test here asserts
both — a swap that moved one without the other would leave the pane showing one
board and claiming the other.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from src.commentary import LaunchCard
from src.config import NEW_LAUNCH_DAYS
from src.layout.commentary_pane import CommentaryPane

AS_OF = date(2026, 9, 17)


def _launch(ticker: str, *, days_ago: int = 5) -> LaunchCard:
    return LaunchCard(
        name=f"Name {ticker.split()[0]}",
        ticker=ticker,
        meta="Equity · Core",
        live_date=date(2026, 9, 12),
        days_ago=days_ago,
        since_return=0.0123,
    )


def _notes_file(tmp_path, notes: list[dict]) -> str:
    path = tmp_path / "commentary.json"
    path.write_text(json.dumps(notes), encoding="utf-8")
    return str(path)


def _pane(notes_path: str | None = None) -> CommentaryPane:
    if notes_path is None:
        # A path that does not exist → the loader's "no notes yet" state, which
        # is what every test not about the notes wants: no dependency on
        # whatever `data/commentary.json` happens to hold.
        return CommentaryPane(as_of=AS_OF, notes_path="does/not/exist.json")
    return CommentaryPane(as_of=AS_OF, notes_path=notes_path)


def _showing(pane: CommentaryPane):
    assert len(pane.root.children) == 1  # exactly one board at a time
    return pane.root.children[0]


# ---- the default view ------------------------------------------------------


def test_the_pane_opens_on_the_commentary():
    pane = _pane()

    assert pane.active == "commentary"
    assert _showing(pane) is pane.commentary_w
    assert pane.chips.value == "commentary"


def test_the_control_is_a_chip_group_not_a_pill_pair():
    """#307 put the Bulletin on the Platform tab's control idiom. The pills and
    their `is-active` class are gone, and with them `pane.buttons`."""
    pane = _pane()

    assert list(pane.chips.labels) == ["Commentary", "New Launches"]
    assert not hasattr(pane, "buttons")
    # The bar is a `control_bar`, the same component the Leaderboard's Window
    # control sits in.
    assert "bbg-rail-bar" in pane.bar._dom_classes


def test_the_pane_is_the_container_alone_and_not_a_second_card():
    """`section_panel` supplies the frame; a `bbg-card` here would nest two
    bordered surfaces and draw two."""
    pane = _pane()

    assert "bbg-commentary-pane" in pane.root._dom_classes
    assert "bbg-card" not in pane.root._dom_classes


# ---- switching -------------------------------------------------------------


def test_show_launches_swaps_the_board_and_the_chip():
    pane = _pane()
    pane.show("launches")

    assert pane.active == "launches"
    assert _showing(pane) is pane.launches_w
    assert pane.chips.value == "launches"


def test_show_commentary_swaps_back():
    pane = _pane()
    pane.show("launches")
    pane.show("commentary")

    assert _showing(pane) is pane.commentary_w
    assert pane.chips.value == "commentary"


def test_the_chips_drive_the_swap():
    """The wiring, not just the method: a chip that is not observed leaves the
    pane switchable from Python and dead on screen."""
    pane = _pane()

    pane.chips.value = "launches"
    assert _showing(pane) is pane.launches_w
    assert pane.active == "launches"

    pane.chips.value = "commentary"
    assert _showing(pane) is pane.commentary_w
    assert pane.active == "commentary"


def test_showing_the_open_board_again_is_harmless():
    """`show` writes the chip and the chip observer calls `show`. Re-asserting
    the value writes no change, so traitlets does not fire again — this is the
    test that the pair cannot recurse."""
    pane = _pane()
    pane.show("commentary")
    pane.chips.value = "commentary"

    assert _showing(pane) is pane.commentary_w
    assert pane.active == "commentary"


def test_an_unknown_view_is_refused():
    pane = _pane()
    with pytest.raises(KeyError):
        pane.show("highlights")  # type: ignore[arg-type]


# ---- the commentary board --------------------------------------------------


def test_one_card_per_note_newest_first(tmp_path):
    path = _notes_file(
        tmp_path,
        [
            {"title": "Older", "date": "2026-01-02", "text": "First."},
            {"title": "Newest", "date": "2026-03-04", "text": "Third."},
            {"title": "Middle", "date": "2026-02-03", "text": "Second."},
        ],
    )
    value = _pane(path).commentary_w.value

    assert [value.index(t) for t in ("Newest", "Middle", "Older")] == sorted(
        value.index(t) for t in ("Newest", "Middle", "Older")
    )
    # Each note dates itself — the board no longer stamps one date across all
    # of them the way the Weekly Commentary header did.
    for iso in ("2026-03-04", "2026-02-03", "2026-01-02"):
        assert iso in value


def test_a_blank_line_starts_a_new_paragraph(tmp_path):
    path = _notes_file(
        tmp_path,
        [{"title": "T", "date": "2026-01-01", "text": "One.\n\nTwo.\n\n\nThree."}],
    )
    value = _pane(path).commentary_w.value

    assert "<p>One.</p>" in value
    assert "<p>Two.</p>" in value
    assert "<p>Three.</p>" in value
    assert value.count("<p>") == 3  # the run of blank lines adds no empty one


def test_a_single_newline_does_not_split_a_paragraph(tmp_path):
    path = _notes_file(
        tmp_path,
        [{"title": "T", "date": "2026-01-01", "text": "A wrapped\nsentence."}],
    )
    value = _pane(path).commentary_w.value

    assert value.count("<p>") == 1
    assert "A wrapped\nsentence." in value


def test_markup_in_a_note_is_shown_not_interpreted(tmp_path):
    """The notes are authored *data*. A board that renders data as markup is a
    board that renders whatever the data says."""
    path = _notes_file(
        tmp_path,
        [
            {
                "title": "<script>alert(1)</script>",
                "date": "2026-01-01",
                "text": "Spreads <b>widened</b> & held > 20bp.",
            }
        ],
    )
    value = _pane(path).commentary_w.value

    assert "<script>" not in value
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in value
    assert "<b>" not in value
    assert "&lt;b&gt;widened&lt;/b&gt;" in value
    assert "&amp;" in value and "&gt; 20bp" in value


def test_no_notes_says_so_rather_than_rendering_blank(tmp_path):
    empty = _notes_file(tmp_path, [])
    value = _pane(empty).commentary_w.value

    assert "No commentary yet" in value
    assert "data/commentary.json" in value


def test_a_missing_notes_file_shows_the_same_empty_state():
    assert "No commentary yet" in _pane().commentary_w.value


def test_the_board_does_not_title_itself(tmp_path):
    """The section is titled `QIS Bulletin` and the lit chip says which board
    is open; a heading inside the HTML would be the third thing saying so."""
    path = _notes_file(
        tmp_path, [{"title": "T", "date": "2026-01-01", "text": "Body."}]
    )
    value = _pane(path).commentary_w.value

    assert "<h3" not in value
    assert "Weekly Commentary" not in value
    assert "max-height" not in value  # the container owns the height now


# ---- the launches board ----------------------------------------------------


def test_an_empty_board_says_so_rather_than_rendering_blank():
    pane = _pane()
    pane.update_launches([])

    assert "No new launches" in pane.launches_w.value
    assert f"past {NEW_LAUNCH_DAYS} days" in pane.launches_w.value


def test_the_launches_board_does_not_title_itself_either():
    pane = _pane()
    pane.update_launches([_launch("AAA Index")])

    value = pane.launches_w.value
    assert "<h3" not in value
    assert "max-height" not in value
    # The caption stays: it is the only place the launch window is stated.
    assert f"past {NEW_LAUNCH_DAYS} days" in value


def test_update_launches_renders_one_card_per_launch():
    pane = _pane()
    pane.update_launches([_launch("AAA Index"), _launch("BBB Index")])

    value = pane.launches_w.value
    assert "No new launches" not in value
    assert value.count("AAA Index") == 1
    assert value.count("BBB Index") == 1
    assert "+1.2%" in value  # the since-launch return


def test_update_launches_replaces_the_previous_board():
    pane = _pane()
    pane.update_launches([_launch("AAA Index")])
    pane.update_launches([_launch("BBB Index")])

    assert "AAA Index" not in pane.launches_w.value
    assert "BBB Index" in pane.launches_w.value


def test_update_launches_does_not_steal_the_view():
    """New data arrives on a load or a Refresh. Switching the pane then would
    pull it away from whatever the reader had open."""
    pane = _pane()
    assert pane.active == "commentary"

    pane.update_launches([_launch("AAA Index")])

    assert pane.active == "commentary"
    assert _showing(pane) is pane.commentary_w
    assert pane.chips.value == "commentary"


def test_a_refresh_while_the_launches_board_is_open_leaves_it_open():
    pane = _pane()
    pane.show("launches")

    pane.update_launches([_launch("AAA Index")])

    assert _showing(pane) is pane.launches_w
    assert "AAA Index" in pane.launches_w.value
