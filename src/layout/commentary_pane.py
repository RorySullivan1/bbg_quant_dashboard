"""The QIS Bulletin's switchable board (v0.9.20 #289, reshaped v0.9.22 #307).

One container, two boards: the authored Commentary notes and the New Launches
cards, with a chip pair choosing which is on screen. It replaces the stacked
arrangement where the commentary sat above a two-section highlights panel and
both competed for the vertical above the tab bar.

Since #307 the pane owns its **control** and its **content**, and nothing else:
the title line and the bordered box around it come from `section_panel`, the
same component the Leaderboard and the Platform table are framed with. So
`.bar` and `.root` are what the app mounts, `.root` being the box that holds
exactly one board at a time. The pane carries no `bbg-card` of its own —
`section_panel`'s box is the frame, and two nested would draw two.

The control is a `ChipGroup`, not the pill pair it was: the block reads as the
Platform tab's idiom rather than as a third one, and `value` being a trait
means the swap is observable instead of hand-wired to two buttons.

`errors_w` deliberately stays outside this pane, a sibling in the commentary
block. It was split out of the highlights widget in v0.8.x precisely so a live
control could not wipe an initialization error off the screen, and a pane that
swaps its whole child on a click is exactly that hazard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import ipywidgets as W

from ..commentary import LaunchCard, load_commentary_notes
from ..config import COMMENTARY_PATH
from .html import _render_commentary_notes, _render_launches
from .rails import ChipGroup, RailSection, control_bar

#: The two boards, in chip order. `commentary` is the default view.
PaneView = Literal["commentary", "launches"]
_VIEW_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Commentary", "commentary"),
    ("New Launches", "launches"),
)


class CommentaryPane:
    """The QIS Bulletin's control (`.bar`) and container (`.root`).

    `notes_path` is the JSON the Commentary board is read from, defaulted so
    the pane can be built without the app and pointed at a fixture in a test —
    the same shape `load_commentary_notes` and the disclaimer loaders take.
    Notes are loaded once, at build: they are authored files, not price data,
    and nothing in the session invalidates them.

    It takes no `as_of`. The board used to be dated by the app so one session
    could not date two things differently; a note carries its own date now
    (#304), and the parameter went with the rest of the weekly-commentary
    plumbing in #308.
    """

    def __init__(self, *, notes_path: Path | str = COMMENTARY_PATH) -> None:
        self.commentary_w = W.HTML(
            _render_commentary_notes(load_commentary_notes(notes_path))
        )
        self.launches_w = W.HTML()
        self.update_launches([])

        self._views: dict[str, W.HTML] = {
            "commentary": self.commentary_w,
            "launches": self.launches_w,
        }
        self.chips = ChipGroup(_VIEW_OPTIONS, value="commentary", row=True)
        self.bar = control_bar(RailSection("Board", self.chips))

        #: Holds exactly one board at a time; `show` re-points it.
        self.root = W.Box([], layout=W.Layout(width="100%", min_width="0"))
        self.root.add_class("bbg-commentary-pane")

        self.chips.observe(lambda change: self.show(change["new"]), names="value")
        #: The board currently on screen.
        self.active: str = "commentary"
        self.show("commentary")

    def show(self, which: PaneView) -> None:
        """Put `which` board on screen and light its chip.

        Safe to call from the chip observer: re-asserting the chip's current
        value writes no change, so traitlets does not fire it again.
        """
        if which not in self._views:
            raise KeyError(f"No commentary pane view named {which!r}")
        self.active = which
        self.chips.value = which
        self.root.children = (self._views[which],)

    def update_launches(self, cards: list[LaunchCard]) -> None:
        """Rewrite the launches board from `cards`.

        It does not switch to that board: new data arrives on a load or a
        Refresh, and pulling the pane away from whatever the reader had open
        would make the board harder to keep open than to reach.
        """
        self.launches_w.value = _render_launches(cards)
