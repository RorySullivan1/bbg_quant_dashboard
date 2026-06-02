from __future__ import annotations

import html
from collections.abc import Callable

import ipywidgets as W
import pandas as pd

from ..style import FontSize


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
    return W.HTML(
        f"<div style='font-weight:600;font-size:{FontSize.LABEL};"
        f"margin:6px 4px 2px 4px;'>{html.escape(text)}</div>"
    )


def _q_row(label: str, *, trailing: W.Widget | None = None):
    op = W.Dropdown(options=["≥", "≤"], value="≥", layout=W.Layout(width="60px"))
    box = W.Text(placeholder="value", layout=W.Layout(width="100px"))
    children = [
        W.HTML(
            f"<div style='width:84px;font-size:{FontSize.LABEL};'>{html.escape(label)}</div>"
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
