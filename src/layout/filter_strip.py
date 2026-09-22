"""A tab's filter values, as a strip beside the Dimension chips (#345, #365).

**Structure in the bar, text and numbers in the table.** The bar's *Dimension*
chips name a dimension; this strip shows that dimension's values as a wrapping
row of chips (or, for Launch date, the two date pickers). Everything that is a
*number* — Sharpe, Sortino, VaR, a return threshold — is a column of the table
with the comparison filter row under it, and everything that is *free text* is
the table's search box. This strip carries only what is neither: a closed set
of labels the user picks from.

Two rules shape it.

**One control per dimension, built once and swapped by `display`.** Switching
Filter chips must not clear what another dimension holds, so the controls all
exist and all but one are hidden. Rebuilding on switch would be the cheaper
implementation and the wrong behaviour.

**A hidden selection stays discoverable.** A dimension whose chips are off
screen still narrows the table, so its bar chip carries a count badge —
*Family · 2*. Without it the only evidence of an active filter is rows that are
not there.

**Each tab holds its own.** Two tabs filtering the same catalog independently
is two selections, and sharing one would make narrowing the Multi tab silently
narrow Single Strategy's picker.
"""

from __future__ import annotations

import ipywidgets as W
import pandas as pd

from ..config import field_label, filter_dimensions
from ..data import apply_filters, unique_values
from .rails import MultiChipGroup

#: The two dimensions the schema does not declare as tier/attribute fields but
#: that the catalog is browsed by all the same. They live at the end of the
#: chip row, after the schema's own, because they qualify a strategy rather
#: than classify it.
CURRENCY_KEY: str = "currency"
LAUNCH_KEY: str = "live_date"


class FilterStrip:
    """The value controls for every filter dimension, one shown at a time.

    It owns the values and the reducer; the bar owns which one is *visible*.
    **Both picking tabs build one** since #365 — their own instance each, so
    the two filter independently while running the identical reducer. It was
    the Multi tab's alone while Single Strategy still had `FilterPanel`, whose
    `apply_categorical` called the same `apply_filters`; retiring that panel
    left one implementation rather than two agreeing ones (#341 dec. 8, 10).
    """

    def __init__(self, meta: pd.DataFrame, *, on_change=None) -> None:
        self._on_change = on_change
        # Suspended through construction: the handler the caller passes reads
        # widgets it builds *after* this (the bar's Filter chips), so a chip
        # firing while its group is being seeded would reach a half-built tab.
        self._suspended = True

        #: Schema field key -> its chip group. Insertion order is the bar's.
        self.groups: dict[str, MultiChipGroup] = {}
        for dimension in filter_dimensions():
            values = unique_values(meta, dimension.key)
            if values:
                self.groups[dimension.key] = self._chips(values)
        currencies = unique_values(meta, CURRENCY_KEY)
        if currencies:
            self.groups[CURRENCY_KEY] = self._chips(currencies)

        self.live_min = W.DatePicker(layout=W.Layout(width="160px"))
        self.live_max = W.DatePicker(layout=W.Layout(width="160px"))
        for picker in (self.live_min, self.live_max):
            picker.observe(self._changed, names="value")
        # A *characteristic* of a strategy, not the analysis range #341 dec. 12
        # retired: when an index launched is a fact about the index, and the
        # window the analytics run over is a fact about the basket.
        self.launch_box = W.HBox(
            [
                self.live_min,
                W.HTML("<div class='bbg-strip-dash'>–</div>"),
                self.live_max,
            ],
            layout=W.Layout(align_items="center"),
        )

        self._boxes: dict[str, W.Widget] = {**self.groups, LAUNCH_KEY: self.launch_box}
        self.root = W.VBox(
            list(self._boxes.values()),
            layout=W.Layout(width="100%"),
        )
        self.root.add_class("bbg-filter-strip")
        self.show(self.keys[0])
        self._suspended = False

    # --- what the bar offers --------------------------------------------------

    @property
    def keys(self) -> list[str]:
        """The dimensions, in bar order."""
        return list(self._boxes)

    def chip_label(self, key: str) -> str:
        """`Family · 2` — the label with its active-value count.

        The count is the whole reason the label is computed rather than fixed:
        a dimension's chips are hidden most of the time, so the badge is where
        an active filter is visible from.
        """
        label = "Launch date" if key == LAUNCH_KEY else field_label(key)
        count = self.active_count(key)
        return f"{label} · {count}" if count else label

    def active_count(self, key: str) -> int:
        if key == LAUNCH_KEY:
            return sum(p.value is not None for p in (self.live_min, self.live_max))
        group = self.groups.get(key)
        return len(group.value) if group is not None else 0

    def show(self, key: str) -> None:
        """Reveal one dimension's control and hide the rest."""
        for name, box in self._boxes.items():
            box.layout.display = "" if name == key else "none"

    # --- the reducer ----------------------------------------------------------

    def apply(self, meta: pd.DataFrame) -> pd.DataFrame:
        """`meta` narrowed by every dimension, in `meta` row order.

        Currency is just another key in the mapping, and an empty list means
        that dimension is unfiltered.
        """
        return apply_filters(
            meta,
            {key: list(group.value) for key, group in self.groups.items()},
            live_date_min=self.live_min.value,
            live_date_max=self.live_max.value,
        )

    def clear(self) -> None:
        """Reset every dimension — one change event, not one per group."""
        self._suspended = True
        try:
            for group in self.groups.values():
                group.value = ()
            self.live_min.value = None
            self.live_max.value = None
        finally:
            self._suspended = False
        self._changed()

    # --- internals ------------------------------------------------------------

    def _chips(self, values: list[str]) -> MultiChipGroup:
        group = MultiChipGroup([(v, v) for v in values], value=(), row=True)
        group.observe(self._changed, names="value")
        return group

    def _changed(self, _change=None) -> None:
        if self._suspended or self._on_change is None:
            return
        self._on_change()
