from __future__ import annotations

import html
from collections.abc import Callable

import ipywidgets as W
import pandas as pd
import traitlets

from .html import STYLE_CTX, render_template


class CheckboxMultiSelect(W.VBox):
    """A ``W.SelectMultiple``-compatible multi-select rendered as a scrollable
    list of checkboxes (one row per option).

    Exposes the same public surface as ``SelectMultiple`` — an ``options`` trait
    (a list of ``(label, value)`` pairs or plain values) and a ``value`` trait
    (a tuple of the selected values), and it fires ``observe(..., names="value")``
    — so it drops into code written for ``SelectMultiple`` (the Multi-Strategy
    picker: `_on_filter_change` search/filter narrowing, `_default_selection`,
    `_recompute`). Setting ``options`` rebuilds the rows and drops any selected
    value no longer present (SelectMultiple parity; callers re-set ``value``
    explicitly right after)."""

    options = traitlets.Any(())  # list[(label, value)] | list[value]
    value = traitlets.Tuple()  # tuple of selected values

    def __init__(self, *, options=(), value=(), **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_class("bbg-strat-list")
        self._checks: dict = {}  # value -> W.Checkbox
        self._guard = False  # suppress observer feedback loops
        self.observe(self._rebuild_rows, names="options")
        self.observe(self._sync_checks, names="value")
        self.options = list(options)
        self.value = tuple(value)

    def _pairs(self):
        for opt in self.options or ():
            if isinstance(opt, tuple):
                yield str(opt[0]), opt[1]
            else:
                yield str(opt), opt

    def _rebuild_rows(self, *_) -> None:
        selected = set(self.value)
        checks: dict = {}
        rows = []
        for label, val in self._pairs():
            cb = W.Checkbox(
                value=val in selected,
                description=label,
                indent=False,
                layout=W.Layout(width="100%", margin="1px 0"),
            )
            cb.add_class("bbg-strat-check")
            cb.observe(self._on_toggle, names="value")
            checks[val] = cb
            rows.append(cb)
        self._checks = checks
        self.children = tuple(rows)
        # SelectMultiple parity: options change drops selections no longer
        # present. Guarded so it doesn't re-enter `_sync_checks`.
        kept = tuple(v for v in self.value if v in checks)
        if kept != tuple(self.value):
            self._guard = True
            try:
                self.value = kept
            finally:
                self._guard = False

    def _sync_checks(self, *_) -> None:
        if self._guard:
            return
        self._guard = True
        try:
            selected = set(self.value)
            for val, cb in self._checks.items():
                want = val in selected
                if cb.value != want:
                    cb.value = want
        finally:
            self._guard = False

    def _on_toggle(self, _change) -> None:
        if self._guard:
            return
        self._guard = True
        try:
            self.value = tuple(v for v, cb in self._checks.items() if cb.value)
        finally:
            self._guard = False


def _checkbox_group(
    options: list[str],
) -> tuple[W.VBox, Callable[[], list[str]], list[W.Checkbox]]:
    """A scrollable list of value checkboxes for one filter dimension.

    Returns `(content_vbox, getter, checkboxes)`. The getter reads each
    checkbox's `.value` regardless of whether the content is currently the
    visible filter-type view, so `_on_filter_change` works the same way it did
    with the old toggle groups. No header — the filter-type pill button above
    the content area is the label now.
    """
    checks = {
        opt: W.Checkbox(
            value=False,
            description=opt,
            indent=False,
            layout=W.Layout(width="100%", margin="1px 0"),
        )
        for opt in options
    }
    content = W.VBox(
        list(checks.values()),
        layout=W.Layout(
            max_height="240px",
            overflow="auto",
            width="100%",
            padding="2px 4px",
        ),
    )
    return (
        content,
        (lambda: [v for v, c in checks.items() if c.value]),
        list(checks.values()),
    )


def _ticker_options(df: pd.DataFrame) -> list[tuple[str, str]]:
    return [(f"{r['ticker']} — {r['name']}", r["ticker"]) for _, r in df.iterrows()]


def _section_label(text: str) -> W.HTML:
    return W.HTML(render_template("section_label", **STYLE_CTX, text=html.escape(text)))


def _q_row(label: str, *, trailing: W.Widget | None = None):
    op = W.Dropdown(options=["≥", "≤"], value="≥", layout=W.Layout(width="60px"))
    box = W.Text(placeholder="value", layout=W.Layout(width="100px"))
    children = [
        W.HTML(
            render_template("quant_row_label", **STYLE_CTX, text=html.escape(label))
        ),
        op,
        box,
    ]
    if trailing is not None:
        children.append(trailing)
    row = W.HBox(
        children,
        layout=W.Layout(width="100%", align_items="center", margin="1px 0"),
    )
    return row, op, box
