"""The commentary block's switchable right pane (v0.9.20, #289).

One pane, two boards: the Weekly Commentary and the New Launches cards, with a
pill pair choosing which is on screen. It replaces the stacked arrangement
where the commentary sat above a two-section highlights panel and both competed
for the vertical above the tab bar.

The swap is the same idiom as the top-level tab band — `_style_tab_button`
toggles the `is-active` CSS class and the content box is re-pointed at one
child — so the active pill inherits the `:hover` and `:focus-visible` states
from `app_css.html` instead of blocking them with an inline colour.

`errors_w` deliberately stays outside this pane, a sibling in the commentary
block. It was split out of the highlights widget in v0.8.x precisely so a live
control could not wipe an initialization error off the screen, and a pane that
swaps its whole child on a click is exactly that hazard.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import ipywidgets as W

from ..commentary import LaunchCard
from .chrome import _make_tab_button, _style_tab_button
from .html import _load_weekly_commentary, _render_launches, _render_weekly_commentary

#: The two boards, in pill order. `commentary` is the default view.
PaneView = Literal["commentary", "launches"]
_VIEW_LABELS: tuple[tuple[str, str], ...] = (
    ("commentary", "Commentary"),
    ("launches", "New Launches"),
)


class CommentaryPane:
    """The right-hand pane, mounted from `.root`.

    `as_of` dates the Weekly Commentary header; it defaults to today so the
    pane can be built without the app, and the app passes its own `today` so a
    single session cannot date two things differently.
    """

    def __init__(self, *, as_of: date | None = None) -> None:
        self.commentary_w = W.HTML(
            _render_weekly_commentary(_load_weekly_commentary(), as_of or date.today())
        )
        self.launches_w = W.HTML()
        self.update_launches([])

        self.buttons: dict[str, W.Button] = {
            view: _make_tab_button(
                label, active=(view == "commentary"), width="150px", height="30px"
            )
            for view, label in _VIEW_LABELS
        }
        self._views: dict[str, W.HTML] = {
            "commentary": self.commentary_w,
            "launches": self.launches_w,
        }
        self.pill_row = W.HBox(
            list(self.buttons.values()),
            layout=W.Layout(width="100%", padding="0 0 6px 0"),
        )
        #: Holds exactly one board at a time; `show` re-points it.
        self.content = W.Box([], layout=W.Layout(width="100%", min_width="0"))
        self.root = W.VBox(
            [self.pill_row, self.content],
            layout=W.Layout(width="100%", min_width="0"),
        )
        self.root.add_class("bbg-card")
        self.root.add_class("bbg-commentary-pane")

        for view, button in self.buttons.items():
            button.on_click(lambda _b, view=view: self.show(view))
        #: The board currently on screen.
        self.active: str = "commentary"
        self.show("commentary")

    def show(self, which: PaneView) -> None:
        """Put `which` board on screen and mark its pill active."""
        if which not in self._views:
            raise KeyError(f"No commentary pane view named {which!r}")
        self.active = which
        for view, button in self.buttons.items():
            _style_tab_button(button, active=(view == which))
        self.content.children = (self._views[which],)

    def update_launches(self, cards: list[LaunchCard]) -> None:
        """Rewrite the launches board from `cards`.

        It does not switch to that board: new data arrives on a load or a
        Refresh, and pulling the pane away from whatever the reader had open
        would make the board harder to keep open than to reach.
        """
        self.launches_w.value = _render_launches(cards)
