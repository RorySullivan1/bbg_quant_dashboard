from __future__ import annotations

import html

import ipywidgets as W

from ..config import LOGO_PATH
from ..style import StatusTone
from .html import STYLE_CTX, render_template


def _app_css() -> W.HTML:
    """Global stylesheet, injected once at the top of the app VBox.

    Renders ``data/templates/app_css.html`` (a single ``<style>`` block whose
    values come from the shared style tokens via ``STYLE_CTX``) into a
    ``W.HTML``. The ``<style>`` is document-global, so widgets opt into the
    classes it defines via ``widget.add_class(...)`` (Workstreams B/C/D)."""
    return W.HTML(render_template("app_css", **STYLE_CTX))


def _banner() -> W.HBox:
    children: list[W.Widget] = []
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            children.append(W.Image(value=f.read(), format="png", width=56, height=56))
    children.append(
        W.HTML(render_template("banner", **STYLE_CTX), layout=W.Layout(flex="1 1 auto"))
    )
    hbox = W.HBox(
        children,
        layout=W.Layout(width="100%", align_items="center"),
    )
    # Dark surface + accent rule (bg/border/padding live on `.bbg-masthead` in
    # app_css.html) span the logo and text together.
    hbox.add_class("bbg-masthead")
    return hbox


def _status_banner() -> W.HTML:
    return W.HTML(
        _render_status("Initializing…", tone=StatusTone.INFO),
        layout=W.Layout(width="100%"),
    )


def _render_status(text: str, *, tone: StatusTone) -> str:
    # Rendered as the slim auto-fading `.bbg-toast` (status.html); the tone
    # kwargs are kept for signature stability and ignored by the toast markup.
    return render_template(
        "status",
        **STYLE_CTX,
        bg=tone.bg,
        border=tone.border,
        fg=tone.fg,
        text=html.escape(text),
    )


def _loading_overlay() -> W.HTML:
    """The dimmed full-screen loading overlay (v0.6.5 Workstream C).

    A single `W.HTML` whose value is re-rendered through `_render_overlay` at
    each load stage. The outer template div carries the `.bbg-overlay`
    (`position:fixed`) class, so the overlay covers the viewport regardless of
    where the widget is mounted."""
    return W.HTML(_render_overlay(0, "Initializing…"))


def _render_overlay(
    pct: int, label: str, *, error: bool = False, hidden: bool = False
) -> str:
    if hidden:
        state_class = "bbg-overlay is-hidden"
    elif error:
        state_class = "bbg-overlay is-error"
    else:
        state_class = "bbg-overlay"
    return render_template(
        "loading_overlay",
        **STYLE_CTX,
        pct=int(pct),
        label=html.escape(label),
        state_class=state_class,
    )


def _style_tab_button(btn: W.Button, *, active: bool) -> None:
    # Active state is a CSS class toggle (`.bbg-pill.is-active`), not inline
    # `.style` — inline button colors would block the `:hover`/`:focus` states
    # defined in app_css.html.
    if active:
        btn.add_class("is-active")
    else:
        btn.remove_class("is-active")


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
    btn.add_class("bbg-pill")
    _style_tab_button(btn, active=active)
    return btn
