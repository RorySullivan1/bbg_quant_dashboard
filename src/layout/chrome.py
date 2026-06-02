from __future__ import annotations

import html

import ipywidgets as W

from ..config import LOGO_PATH
from ..style import Color, Font, FontSize, StatusTone, TabButtonTone

BANNER_HTML = (
    "<div style='display:flex;align-items:center;gap:16px;"
    f"padding:12px 16px;background:{Color.BRAND_NAVY};color:{Color.WHITE};'>"
    f"<div style='font-size:{FontSize.HERO};font-weight:600;'>"
    "Index Catalog Dashboard</div>"
    f"<div style='font-size:{FontSize.SMALL};opacity:0.75;'>"
    "Metadata · Performance · Risk</div>"
    "</div>"
)


def _banner() -> W.HBox:
    children: list[W.Widget] = []
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            children.append(W.Image(value=f.read(), format="png", width=48, height=48))
    children.append(W.HTML(BANNER_HTML, layout=W.Layout(flex="1 1 auto")))
    return W.HBox(
        children,
        layout=W.Layout(width="100%", align_items="center"),
    )


def _status_banner() -> W.HTML:
    return W.HTML(
        _render_status("Initializing…", tone=StatusTone.INFO),
        layout=W.Layout(width="100%"),
    )


def _render_status(text: str, *, tone: StatusTone) -> str:
    return (
        f"<div style='font-family:{Font.MONO};"
        f"font-size:{FontSize.LABEL};padding:6px 14px;"
        f"background:{tone.bg};border-bottom:1px solid {tone.border};"
        f"color:{tone.fg};'>"
        f"{html.escape(text)}"
        "</div>"
    )


def _style_tab_button(btn: W.Button, *, active: bool) -> None:
    tone = TabButtonTone.ACTIVE if active else TabButtonTone.INACTIVE
    btn.style.button_color = tone.bg
    btn.style.text_color = tone.fg
    btn.style.font_weight = tone.weight


def _make_tab_button(
    label: str, *, active: bool, width: str = "240px", height: str = "40px"
) -> W.Button:
    btn = W.Button(
        description=label,
        layout=W.Layout(
            width=width,
            height=height,
            margin="0 6px 0 0",
        ),
    )
    _style_tab_button(btn, active=active)
    return btn
