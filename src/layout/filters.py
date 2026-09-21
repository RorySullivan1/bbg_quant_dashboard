"""Filter-panel input widgets.

Small, reusable controls the filter panels are assembled from — the checkbox
groups a `CategoricalFilter` is built on, the threshold rows the Quantitative
view stacks, and the ticker-option formatter both tabs' pickers read.

`CheckboxMultiSelect` lived here until #344: a `SelectMultiple` drop-in that
carried the Multi-Strategy picker and its selection cap. That tab's picker is
the catalog table now and the cap belongs to `Basket`, so the class had no
callers left.

This module knows nothing about which dimensions exist or how they combine —
that is `filter_panel.py`'s job.
"""

from __future__ import annotations

import html
from collections.abc import Callable

import ipywidgets as W
import pandas as pd

from .html import STYLE_CTX, render_template


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
