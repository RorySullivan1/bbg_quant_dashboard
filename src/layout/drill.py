"""The Platform card's drill state: where the user is in the hierarchy.

`src/stats/drill.py` decides *what is drawn* at a position; this decides
*what the position is*. One frozen `Drill` is held by `PlatformAnalytics` and
read by all three charts and the points table, so a marker click, an icicle
zoom, a Level chip, a breadcrumb segment and a table row cannot disagree
about where the user is (#331 decision 15).

Frozen because the state is small and replaced wholesale: an object that can
be mutated in place invites a renderer to nudge one field and leave the
others describing a position that no longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..config import DRILL_LEAF_LEVEL, analytics_levels, drill_levels


@dataclass(frozen=True)
class Drill:
    """A position: a path prefix, and the depth the points are drawn at.

    ``scope`` is a path through `ANALYTICS_LEVELS` — ``()`` is the root, which
    draws one point per first drill stop. ``level`` is one of `drill_levels()`.
    """

    scope: tuple[str, ...] = ()
    level: str = ""

    def __post_init__(self) -> None:
        stops = drill_levels()
        if not self.level:
            object.__setattr__(self, "level", stops[0])
        elif self.level not in stops:
            raise ValueError(f"{self.level!r} is not one of {list(stops)}")
        if len(self.scope) > len(analytics_levels()):
            raise ValueError(
                f"scope {self.scope!r} is deeper than " f"{list(analytics_levels())}"
            )

    @property
    def depth(self) -> int:
        """How many levels of the hierarchy the scope pins down."""
        return len(self.scope)

    def narrowed_to(self, path: tuple[str, ...]) -> Drill:
        """This drill moved into ``path``, at the stop that shows its children.

        The one-liner a click uses: the clicked node's own path becomes the
        scope, and the level moves to the next stop down. At the deepest stop
        it stays on the leaf, so clicking a strategy is a no-op rather than an
        error — the table row is the way into Single Strategy.
        """
        return replace(self, scope=tuple(path), level=next_stop(tuple(path)))

    def at_level(self, level: str) -> Drill:
        """This drill at a different depth, same scope — what a Level chip sets."""
        return replace(self, level=level)


def next_stop(path: tuple[str, ...]) -> str:
    """The drill stop that shows ``path``'s children.

    One stop per path segment consumed: the root shows the first level, a
    scope pinning one segment shows the second, and so on down to the ticker
    leaf, which is as deep as it goes.

    This used to need an off-by-one (`max(len(path), 1) - 1`) because the
    hierarchy's first level was a colour key rather than a stop, so the root
    and a one-segment scope both showed the same level. Every level is a stop
    now, so the mapping is the plain one.
    """
    stops = drill_levels()
    return stops[min(len(path), len(stops) - 1)]


def is_leaf(level: str) -> bool:
    """Whether ``level`` is the ticker leaf — where a click opens a strategy."""
    return level == DRILL_LEAF_LEVEL
