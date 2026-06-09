from __future__ import annotations

import html
from datetime import date
from functools import cache
from pathlib import Path

from ..config import TEMPLATES_DIR, WEEKLY_COMMENTARY_PATH
from ..style import Color, Font, FontSize, StatusTone
from .theme import _sentiment_color

# Shared style-token vocabulary spread into every template's context, so the
# `data/templates/*.html` files carry placeholders ({{navy}}, {{label_size}},
# …) instead of hardcoded hex/fonts — a token change in `src/style.py` still
# propagates. Size placeholders end in `_size` so they never collide with a
# dynamic-data key (e.g. a highlight card's `{{label}}` text).
STYLE_CTX = {
    "navy": Color.BRAND_NAVY,
    "white": Color.WHITE,
    "slate50": Color.SLATE_50,
    "slate200": Color.SLATE_200,
    "slate500": Color.SLATE_500,
    "sans": Font.SANS,
    "mono": Font.MONO,
    "title_size": FontSize.TITLE,
    "hero_size": FontSize.HERO,
    "display_size": FontSize.DISPLAY,
    "h3_size": FontSize.H3,
    "body_size": FontSize.BODY,
    "small_size": FontSize.SMALL,
    "label_size": FontSize.LABEL,
    "caption_size": FontSize.CAPTION,
    "micro_size": FontSize.MICRO,
    # Dark technical chrome (v0.6.5). `border`/`text` are reserved by the
    # status/error templates' dynamic kwargs, so the chrome tokens use the
    # `_color` suffix to avoid duplicate-keyword collisions in render_template.
    "chrome_bg": Color.CHROME_BG,
    "surface": Color.SURFACE,
    "surface2": Color.SURFACE_2,
    "border_color": Color.BORDER,
    "text_color": Color.TEXT,
    "text_muted": Color.TEXT_MUTED,
    "accent": Color.ACCENT,
    "accent2": Color.ACCENT_2,
    "scrim": Color.SCRIM,
    "red": Color.RED_600,
    "green": Color.GREEN_600,
}


@cache
def _read_template(name: str) -> str:
    return (TEMPLATES_DIR / f"{name}.html").read_text(encoding="utf-8")


def _substitute(body: str, ctx: dict) -> str:
    """Replace each ``{{key}}`` in ``body`` with ``str(ctx[key])``, one pass
    per key in insertion order. Callers pass style tokens first and dynamic
    (already `html.escape`'d) data last, so escaped text inserted late is never
    re-scanned for placeholders."""
    for key, val in ctx.items():
        body = body.replace("{{" + key + "}}", str(val))
    return body


def render_template(name: str, /, **ctx: object) -> str:
    """Render ``data/templates/<name>.html``, substituting ``{{key}}`` slots.

    Style tokens come from ``STYLE_CTX`` (spread by the caller); dynamic text
    must be `html.escape`'d by the caller before being passed in. The raw
    template text is cached (``_read_template``); substitution runs per call.
    """
    return _substitute(_read_template(name), ctx)


def _load_disclaimer(path: Path, **placeholders: str) -> str:
    """Load a standalone `data/*.html` disclaimer and substitute its
    ``{{key}}`` slots. Thin wrapper over `_substitute` (the disclaimers live
    directly under `data/`, not `data/templates/`)."""
    if not path.exists():
        return ""
    return _substitute(path.read_text(encoding="utf-8"), placeholders)


def _load_weekly_commentary() -> str:
    if not WEEKLY_COMMENTARY_PATH.exists():
        return render_template("weekly_commentary_fallback", **STYLE_CTX)
    return WEEKLY_COMMENTARY_PATH.read_text(encoding="utf-8")


def _render_weekly_commentary(body_html: str, as_of: date) -> str:
    return render_template(
        "weekly_commentary",
        **STYLE_CTX,
        as_of=as_of.isoformat(),
        body_html=body_html,
    )


def _superlative_value_color(sentiment: str) -> str:
    """Sentiment → value color for the dark superlative cards.

    Reuses the shared green/red sentiment palette but maps ``neutral`` to the
    bright chrome text token (the shared ``Sentiment.NEUTRAL`` is brand navy,
    which is illegible on the dark surface)."""
    if sentiment == "neutral":
        return str(Color.TEXT)
    return _sentiment_color(sentiment)


def _render_superlative_cards(cards: list[dict]) -> str:
    return "".join(
        render_template(
            "superlative_card",
            **STYLE_CTX,
            color=_superlative_value_color(c.get("sentiment", "neutral")),
            label=html.escape(c["label"]),
            value=html.escape(c["value"]),
            name=html.escape(c.get("name", "")),
            ticker=html.escape(c["ticker"]),
            detail=html.escape(c.get("detail", "")),
        )
        for c in cards
    )


def _render_launch_cards(cards: list[dict]) -> str:
    if not cards:
        return render_template(
            "launch_empty",
            **STYLE_CTX,
            message=html.escape("No new launches in the past 30 days."),
        )
    return "".join(
        render_template(
            "launch_card",
            **STYLE_CTX,
            name=html.escape(c.get("name", "")),
            ticker=html.escape(c["ticker"]),
            meta=html.escape(c.get("meta", "")),
            live_date=html.escape(c["live_date"]),
            days_ago=html.escape(str(c["days_ago"])),
            since_return=html.escape(c["since_return"]),
        )
        for c in cards
    )


def _render_highlights(superlatives: list[dict], launches: list[dict]) -> str:
    """Two-section highlights: left = monthly superlatives, right = new launches.

    Returns ``""`` when there is nothing to show yet (initial empty widget /
    no data), so the commentary block collapses cleanly."""
    if not superlatives and not launches:
        return ""
    return render_template(
        "highlights_two_col",
        **STYLE_CTX,
        superlatives=_render_superlative_cards(superlatives),
        launches=_render_launch_cards(launches),
    )


def _render_error(message: str) -> str:
    return render_template(
        "error_box",
        **STYLE_CTX,
        bg=StatusTone.ERROR.bg,
        border=StatusTone.ERROR.border,
        fg=StatusTone.ERROR.fg,
        message=html.escape(message),
    )
