"""The switchable `CommentaryPane` (v0.9.20, #289).

Two things carry the pane: which board the content box currently holds, and
which pill is marked active. They are set by the same call, so every test here
asserts both — a swap that moved one without the other would leave the pane
showing one board and claiming the other.
"""

from __future__ import annotations

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


def _pane() -> CommentaryPane:
    return CommentaryPane(as_of=AS_OF)


def _showing(pane: CommentaryPane):
    assert len(pane.content.children) == 1  # exactly one board at a time
    return pane.content.children[0]


def _active(pane: CommentaryPane) -> list[str]:
    return [v for v, b in pane.buttons.items() if "is-active" in b._dom_classes]


# ---- the default view ------------------------------------------------------


def test_the_pane_opens_on_the_commentary():
    pane = _pane()

    assert pane.active == "commentary"
    assert _showing(pane) is pane.commentary_w
    assert _active(pane) == ["commentary"]
    assert "Weekly Commentary" in pane.commentary_w.value
    assert AS_OF.isoformat() in pane.commentary_w.value


def test_the_pane_is_a_card_with_both_pills():
    pane = _pane()

    assert "bbg-card" in pane.root._dom_classes
    assert [b.description for b in pane.buttons.values()] == [
        "Commentary",
        "New Launches",
    ]
    assert all("bbg-pill" in b._dom_classes for b in pane.buttons.values())


# ---- switching -------------------------------------------------------------


def test_show_launches_swaps_the_board_and_the_active_pill():
    pane = _pane()
    pane.show("launches")

    assert pane.active == "launches"
    assert _showing(pane) is pane.launches_w
    assert _active(pane) == ["launches"]


def test_show_commentary_swaps_back():
    pane = _pane()
    pane.show("launches")
    pane.show("commentary")

    assert _showing(pane) is pane.commentary_w
    assert _active(pane) == ["commentary"]


def test_the_pills_drive_the_swap():
    """The wiring, not just the method: a pill that is not connected leaves the
    pane switchable from Python and dead on screen."""
    pane = _pane()

    pane.buttons["launches"].click()
    assert _showing(pane) is pane.launches_w
    assert _active(pane) == ["launches"]

    pane.buttons["commentary"].click()
    assert _showing(pane) is pane.commentary_w
    assert _active(pane) == ["commentary"]


def test_showing_the_open_board_again_is_harmless():
    pane = _pane()
    pane.buttons["commentary"].click()

    assert _showing(pane) is pane.commentary_w
    assert _active(pane) == ["commentary"]


def test_an_unknown_view_is_refused():
    pane = _pane()
    with pytest.raises(KeyError):
        pane.show("superlatives")  # type: ignore[arg-type]


def test_the_pills_never_carry_an_inline_colour():
    """Inline button colours would win over the `:hover` / `:focus-visible`
    rules in `app_css.html`, which is why the active state is a class."""
    pane = _pane()
    pane.show("launches")
    pane.show("commentary")

    for button in pane.buttons.values():
        assert button.style.button_color is None
        assert button.style.text_color is None


# ---- the launches board ----------------------------------------------------


def test_an_empty_board_says_so_rather_than_rendering_blank():
    pane = _pane()
    pane.update_launches([])

    assert "No new launches" in pane.launches_w.value
    assert "New Launches" in pane.launches_w.value
    assert f"past {NEW_LAUNCH_DAYS} days" in pane.launches_w.value


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


def test_a_refresh_while_the_launches_board_is_open_leaves_it_open():
    pane = _pane()
    pane.show("launches")

    pane.update_launches([_launch("AAA Index")])

    assert _showing(pane) is pane.launches_w
    assert "AAA Index" in pane.launches_w.value
