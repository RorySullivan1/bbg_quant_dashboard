"""Control rails, the chip groups they carry, and the section shell they sit in
(v0.9.21 #277, v0.9.22 #305).

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
from .html import STYLE_CTX, render_template

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

    def __init__(self, options: Sequence[Any], *, row: bool = False, **kwargs) -> None:
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
        self.add_class("bbg-chip-group")
        if row:
            # A `VBox` with `flex_flow: row wrap` rather than an `HBox`, so the
            # class stays one type whichever way it is laid out — a caller that
            # reads `.value` should not have to know, and the chips wrap rather
            # than squeezing when a bar runs out of width.
            self.add_class("bbg-chip-row")
            self.layout.flex_flow = "row wrap"
            self.layout.width = "auto"
        else:
            self.layout.width = "100%"

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

    def __init__(
        self, options: Sequence[Any], *, value: Any = None, row: bool = False, **kwargs
    ) -> None:
        super().__init__(options, row=row, **kwargs)
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
        self,
        options: Sequence[Any],
        *,
        value: Iterable[Any] = (),
        row: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(options, row=row, **kwargs)
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


def _rail_title(text: str) -> W.HTML:
    """A rail's own title, above its sections.

    It names what the rail's sections belong to — the Z-Score rail's Metric /
    Window / Lookback are three facets of one control, and saying so in each
    heading would spell "Z-Score" three times. Both Platform rails carry one,
    so the two read identically; it stays optional because a rail with a single
    self-explanatory section does not need the line.
    """
    title = W.HTML(html.escape(text))
    title.add_class("bbg-rail-title")
    return title


def _section_title(text: str) -> W.HTML:
    """A section's heading line, in the catalog table's own type.

    `grid_header` is what "All-catalog performance" is drawn with, so a section
    titled this way reads as a sibling of the table rather than as a new kind
    of thing.
    """
    return W.HTML(render_template("grid_header", **STYLE_CTX, text=html.escape(text)))


def control_rail(
    *sections: RailSection,
    title: str | None = None,
    width: str = RAIL_WIDTH,
    height: str | None = None,
) -> W.VBox:
    """A rail: its sections stacked in the order given, under an optional title.

    Declared, not assembled — the caller says what the rail contains and this
    owns the frame, the fixed basis and the heading treatment, so the two
    Platform rails cannot drift apart.
    """
    children: list[W.Widget] = []
    if title is not None:
        children.append(_rail_title(title))
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
            # A caller that stands a rail beside the table passes the table's
            # height, so the two are one number rather than two that agree
            # today (#298).
            height=height,
        ),
    )
    rail.add_class("bbg-rail")
    return rail


def control_bar(*sections: RailSection, title: str | None = None) -> W.HBox:
    """The same rail, laid out across instead of down.

    Controls that shape the table's *rows* sit above it, where the eye starts,
    and a stack of chips there would cost vertical space the table wants. Each
    section keeps its heading over its own chips, so a bar reads as the same
    component turned on its side rather than as a second control idiom — it
    carries `.bbg-rail`, and only the direction differs.
    """
    blocks: list[W.Widget] = []
    if title is not None:
        blocks.append(_rail_title(title))
    for section in sections:
        block = W.VBox(
            [_rail_heading(section.heading), section.control],
            layout=W.Layout(flex="0 0 auto", margin="0 18px 0 0"),
        )
        block.add_class("bbg-rail-block")
        blocks.append(block)
    bar = W.HBox(blocks, layout=W.Layout(width="100%", align_items="flex-start"))
    bar.add_class("bbg-rail")
    bar.add_class("bbg-rail-bar")
    return bar


def section_panel(
    title: str,
    bar: W.Widget,
    body: W.Widget,
    *,
    height: str,
) -> W.VBox:
    """A titled section: a heading line, a row of controls, then a boxed body.

    Not a new idiom — the Platform tab is already assembled this way
    (`universe_header` / `table_bar` / the bordered table), and the commentary
    block's two sections have to match it and each other. Naming the
    arrangement is what stops three copies of it drifting apart, the same
    argument that gave `control_rail` and `control_bar` one component.

    The title is the `grid_header` treatment the catalog table wears, not
    `_rail_title`: that one is the accent, uppercase, underlined type that
    belongs *inside* a rail, and using it here would put two competing title
    styles on one screen.

    `bar` arrives already built — `control_bar` brings its own bordered surface
    and its own bottom margin, so this adds nothing around it.

    **`height` is required.** The component owns the shape; the caller owns the
    size. A default sized for the commentary block would quietly impose that
    number on a Platform caller, which wants `CATALOG_TABLE_HEIGHT` instead.
    The body scrolls inside that height rather than growing the row, which is
    what `min_height="0"` buys: a flex child otherwise refuses to shrink below
    its content, and the box grows instead of scrolling. (`.bbg-rail` scrolls
    on exactly this pair; the catalog table needs a second, inner element only
    because its header has to stay sticky against the scroller.)
    """
    box = W.Box(
        [body],
        layout=W.Layout(width="100%", height=height, min_height="0"),
    )
    box.add_class("bbg-section-box")
    return W.VBox(
        [_section_title(title), bar, box],
        layout=W.Layout(width="100%", min_width="0"),
    )
