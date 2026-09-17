"""Control rails and the chip groups they carry (v0.9.21, #277).

A rail is the stylized side panel the Platform tab hangs its controls off:
a fixed-width stack of headed sections, each section a heading plus one chip
group. Both of the tab's rails (#278, #279) are built from `control_rail`
rather than assembled at the call site, because two near-identical `W.VBox`es
reconciled after the fact is the duplication this component exists to remove.

**A chip group is a widget, not a row of buttons.** The controls these replace
are read for their state, not just clicked: `PlatformAnalytics` takes three of
them by constructor injection and reads `.value` to compute, `.label` to title
the z-score column, and `.observe` to re-render (#279). `ChipGroup` therefore
presents the `W.Dropdown` surface those call sites already use — `value`,
`label`, `observe(..., names="value")` — so swapping the widget is a chrome
change and an annotation, not a rewrite.

`MultiChipGroup` is the multi-select flavour, and it reports **membership**:
its `value` is always in options order, whatever order the chips were clicked.
That is not a convenience — the catalog grid nests by the hierarchy and never
by click order (#273), so a group that could report a click sequence would be
offering state that nothing downstream is allowed to honour.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from typing import Any, NamedTuple

import ipywidgets as W
import traitlets as T

from .chrome import _make_chip, _style_chip

#: The fixed flex basis every rail is built at. The rails do not flex: the
#: table between them absorbs the remaining width (#276, #280), so a rail that
#: grew with its content would take that width back invisibly.
RAIL_WIDTH = "210px"

#: One option, normalized: the text a chip shows and the value it carries.
OptionPair = tuple[str, Any]


def _option_pairs(options: Iterable[Any]) -> tuple[OptionPair, ...]:
    """Normalize either option shape `W.Dropdown` accepts into (label, value).

    A bare sequence of labels carries itself as the value, so
    `ChipGroup(["1Y", "3Y"])` behaves like the radio it replaces, while
    explicit `(label, value)` pairs keep a display string separate from the
    key the call site computes with.
    """
    pairs: list[OptionPair] = []
    for option in options:
        if isinstance(option, tuple):
            label, value = option
            pairs.append((str(label), value))
        else:
            pairs.append((str(option), option))
    return tuple(pairs)


class _ChipStack(W.VBox):
    """Shared plumbing: the chips, their labels, and the click wiring.

    Subclasses decide what a click *means* — one selection or a membership
    toggle — and own the traits that carry it.
    """

    def __init__(self, options: Sequence[Any], **kwargs) -> None:
        super().__init__(**kwargs)
        pairs = _option_pairs(options)
        if not pairs:
            raise ValueError("a chip group needs at least one option")
        self._pairs = pairs
        self._chips = [_make_chip(label, active=False) for label, _ in pairs]
        for index, chip in enumerate(self._chips):
            # Default-arg binding, not a closure over `index`: a closure would
            # leave every chip reporting the last index.
            chip.on_click(lambda _btn, i=index: self._clicked(i))
        self.children = tuple(self._chips)
        self.layout.width = "100%"
        self.add_class("bbg-chip-group")

    @property
    def options(self) -> tuple[OptionPair, ...]:
        """The (label, value) pairs, in the order the chips are stacked."""
        return self._pairs

    @property
    def labels(self) -> tuple[str, ...]:
        """Just the display texts, for a caller checking what is on offer."""
        return tuple(label for label, _ in self._pairs)

    def _index_of(self, value: Any) -> int:
        for index, (_label, candidate) in enumerate(self._pairs):
            if candidate == value:
                return index
        raise ValueError(f"{value!r} is not one of {list(self.labels)}")

    def _clicked(self, index: int) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class ChipGroup(_ChipStack):
    """Single-select chips with a `W.Dropdown`'s surface.

    `value` is the selected option's value and `label` its display text, both
    traits, so a call site keeps `widget.observe(handler, names="value")` and
    `widget.label` working unchanged across the swap (#279). Assigning an
    unknown `value` raises rather than silently selecting nothing — the failure
    a radio would have raised too.
    """

    value = T.Any(help="The selected option's value.")
    label = T.Unicode("", help="The selected option's display text.")

    def __init__(self, options: Sequence[Any], *, value: Any = None, **kwargs) -> None:
        super().__init__(options, **kwargs)
        self.observe(self._sync, names="value")
        # Setting the trait drives `_sync`, which paints the chips — so the
        # initial selection takes the same path a click does.
        self.value = self._pairs[0][1] if value is None else value
        self._sync()

    @T.validate("value")
    def _check_value(self, proposal):
        self._index_of(proposal["value"])
        return proposal["value"]

    def _sync(self, _change=None) -> None:
        chosen = self._index_of(self.value)
        self.label = self._pairs[chosen][0]
        for index, chip in enumerate(self._chips):
            _style_chip(chip, active=index == chosen)

    def _clicked(self, index: int) -> None:
        self.value = self._pairs[index][1]


class MultiChipGroup(_ChipStack):
    """Multi-select chips that report membership, never click order.

    `value` is a tuple of the ticked values **in options order**, normalized on
    every write, so "ticked A then C" and "ticked C then A" are the same state
    to every reader. The catalog grid's nesting depends on that (#273, #278).
    """

    value = T.Tuple(help="The ticked options' values, in options order.")

    def __init__(
        self, options: Sequence[Any], *, value: Iterable[Any] = (), **kwargs
    ) -> None:
        super().__init__(options, **kwargs)
        self.observe(self._sync, names="value")
        self.value = tuple(value)
        self._sync()

    @T.validate("value")
    def _check_value(self, proposal):
        picked = {self._index_of(value) for value in proposal["value"]}
        return tuple(value for i, (_l, value) in enumerate(self._pairs) if i in picked)

    def _sync(self, _change=None) -> None:
        picked = set(self.value)
        for (_label, value), chip in zip(self._pairs, self._chips, strict=True):
            _style_chip(chip, active=value in picked)

    def _clicked(self, index: int) -> None:
        value = self._pairs[index][1]
        picked = set(self.value)
        picked.symmetric_difference_update({value})
        # The validator re-orders, so the write below cannot encode click order.
        self.value = tuple(picked)


class RailSection(NamedTuple):
    """One headed block of a rail: what it is called, and the control itself."""

    heading: str
    control: W.Widget


def _rail_heading(text: str) -> W.HTML:
    """A rail's section header — uppercase and letterspaced, styled by class.

    The type is `.bbg-rail-heading` in app_css.html rather than inline style,
    so the rails follow a token change the way the rest of the chrome does.
    """
    heading = W.HTML(html.escape(text))
    heading.add_class("bbg-rail-heading")
    return heading


def control_rail(*sections: RailSection, width: str = RAIL_WIDTH) -> W.VBox:
    """A rail: its sections stacked in the order given.

    Declared, not assembled — the caller says what the rail contains and this
    owns the frame, the fixed basis and the heading treatment, so the two
    Platform rails cannot drift apart.
    """
    children: list[W.Widget] = []
    for section in sections:
        children.append(_rail_heading(section.heading))
        children.append(section.control)
    rail = W.VBox(
        children,
        layout=W.Layout(
            width=width,
            flex=f"0 0 {width}",
            align_items="stretch",
            margin="0 8px 0 0",
        ),
    )
    rail.add_class("bbg-rail")
    return rail
