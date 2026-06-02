from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from ..config import WEEKLY_COMMENTARY_PATH
from ..style import Color, Font, FontSize, StatusTone
from .theme import _sentiment_color


def _load_weekly_commentary() -> str:
    if not WEEKLY_COMMENTARY_PATH.exists():
        return (
            f"<p style='color:{Color.SLATE_500};margin:0;'>"
            "No weekly commentary yet — create <code>data/weekly_commentary.html</code> "
            "to populate this section."
            "</p>"
        )
    return WEEKLY_COMMENTARY_PATH.read_text(encoding="utf-8")


def _load_disclaimer(path: Path, **placeholders: str) -> str:
    if not path.exists():
        return ""
    body = path.read_text(encoding="utf-8")
    for key, val in placeholders.items():
        body = body.replace("{{" + key + "}}", val)
    return body


def _render_weekly_commentary(body_html: str, as_of: date) -> str:
    return (
        f"<div style='font-family:{Font.SANS};font-size:{FontSize.BODY};"
        f"line-height:1.5;border:1px solid {Color.SLATE_200};border-radius:6px;"
        f"padding:14px 16px;background:{Color.SLATE_50};'>"
        "<div style='display:flex;align-items:baseline;gap:10px;margin-bottom:6px;'>"
        f"<h3 style='margin:0;font-size:{FontSize.H3};color:{Color.BRAND_NAVY};'>"
        "Weekly Commentary</h3>"
        f"<span style='font-size:{FontSize.CAPTION};color:{Color.SLATE_500};'>"
        f"as of {as_of.isoformat()}</span>"
        "</div>"
        f"<div>{body_html}</div>"
        "</div>"
    )


def _render_highlights(cards: list[dict]) -> str:
    if not cards:
        return ""
    tiles = []
    for c in cards:
        color = _sentiment_color(c.get("sentiment", "neutral"))
        label = html.escape(c["label"])
        value = html.escape(c["value"])
        ticker = html.escape(c["ticker"])
        name = html.escape(c.get("name", ""))
        tiles.append(
            f"<div style='border:1px solid {Color.SLATE_200};border-radius:6px;"
            f"padding:10px 12px;background:{Color.WHITE};'>"
            f"<div style='font-size:{FontSize.MICRO};font-weight:600;"
            "letter-spacing:0.05em;text-transform:uppercase;"
            f"color:{Color.SLATE_500};margin-bottom:4px;'>{label}</div>"
            f"<div style='font-size:{FontSize.DISPLAY};font-weight:600;"
            f"color:{color};line-height:1.1;'>{value}</div>"
            f"<div style='font-size:{FontSize.LABEL};color:{Color.BRAND_NAVY};"
            f"margin-top:4px;'>{name}</div>"
            f"<div style='font-size:{FontSize.CAPTION};color:{Color.SLATE_500};"
            f"font-family:{Font.MONO};'>{ticker}</div>"
            "</div>"
        )
    return (
        f"<div style='font-family:{Font.SANS};'>"
        f"<h3 style='margin:14px 0 8px 0;font-size:{FontSize.H3};"
        f"color:{Color.BRAND_NAVY};'>"
        f"Key Highlights <span style='font-weight:400;font-size:{FontSize.CAPTION};"
        f"color:{Color.SLATE_500};'>(all-catalog)</span>"
        "</h3>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;'>"
        + "".join(tiles)
        + "</div></div>"
    )


def _render_error(message: str) -> str:
    return (
        f"<div style='font-family:{Font.SANS};font-size:{FontSize.SMALL};"
        f"background:{StatusTone.ERROR.bg};border:1px solid {StatusTone.ERROR.border};"
        f"color:{StatusTone.ERROR.fg};padding:12px 16px;border-radius:4px;'>"
        "<h3 style='margin:0 0 8px 0;'>Recompute failed</h3>"
        f"<pre style='white-space:pre-wrap;margin:0;'>{html.escape(message)}</pre>"
        "</div>"
    )
