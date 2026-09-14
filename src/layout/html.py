"""HTML rendering: the template loader and the card/disclaimer renderers.

Markup lives in `data/templates/*.html` rather than in Python strings, and
`render_template` substitutes `{{placeholder}}` values into it. `STYLE_CTX`
spreads the shared style tokens into every template context, so a color or font
change in `src/style.py` propagates to the templates without editing them.

Callers are responsible for escaping any user- or data-supplied text they pass
in; the substitution itself does not escape.
"""

from __future__ import annotations

import html
from datetime import date
from functools import cache
from pathlib import Path

import pandas as pd

from ..commentary import LaunchCard, SuperlativeCard
from ..config import (
    PROFILE_CARD_FIELDS,
    TEMPLATES_DIR,
    WEEKLY_COMMENTARY_PATH,
    catalog_field,
    field_label,
)
from ..style import Color, Font, FontSize, Sentiment, StatusTone

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
    # Dark technical chrome. `border`/`text` are reserved by the
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


def _superlative_value_color(sentiment: Sentiment) -> str:
    """Sentiment → value color for the dark superlative cards.

    Reuses the shared green/red sentiment palette but maps ``NEUTRAL`` to the
    bright chrome text token (the shared ``Sentiment.NEUTRAL`` is brand navy,
    which is illegible on the dark surface).

    Takes the enum member, not its name: `Sentiment` is a `StrEnum` over *color*
    values, so a member's string form is a hex code — feeding one to
    `_sentiment_color`, which looks up by member *name*, would miss and silently
    return neutral for every card.
    """
    if sentiment is Sentiment.NEUTRAL:
        return str(Color.TEXT)
    return str(sentiment.value)


def _render_superlative_cards(cards: list[SuperlativeCard]) -> str:
    return "".join(
        render_template(
            "superlative_card",
            **STYLE_CTX,
            color=_superlative_value_color(c.sentiment),
            label=html.escape(c.label),
            value=html.escape(c.value),
            name=html.escape(c.name),
            ticker=html.escape(c.ticker),
            description=html.escape(c.description),
        )
        for c in cards
    )


def _fmt_since_return(value: float | None) -> str:
    """A launch card's since-launch return, or an em dash when there isn't one.

    The builder returns None rather than a placeholder string, so the choice of
    what "no return yet" looks like stays here with the rest of the presentation.
    """
    return "—" if value is None else f"{value:+.1%}"


def _render_launch_cards(cards: list[LaunchCard]) -> str:
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
            name=html.escape(c.name),
            ticker=html.escape(c.ticker),
            meta=html.escape(c.meta),
            live_date=html.escape(c.live_date.isoformat()),
            days_ago=html.escape(str(c.days_ago)),
            since_return=html.escape(_fmt_since_return(c.since_return)),
        )
        for c in cards
    )


def _render_highlights(
    superlatives: list[SuperlativeCard],
    launches: list[LaunchCard],
    *,
    window_label: str = "Past Month",
) -> str:
    """Two-section highlights: left = window superlatives, right = new launches.

    ``window_label`` (e.g. "Past Week"/"Past Month") titles the Superlatives
    board to match the live window toggle. Returns ``""`` when there is nothing
    to show yet (initial empty widget / no data), so the commentary block
    collapses cleanly."""
    if not superlatives and not launches:
        return ""
    return render_template(
        "highlights_two_col",
        **STYLE_CTX,
        window_label=html.escape(window_label),
        superlatives=_render_superlative_cards(superlatives),
        launches=_render_launch_cards(launches),
    )


def _na(value: object) -> str:
    """Display helper: ``None`` / ``NA`` / blank → an em dash, else the text."""
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or "—"


def _fmt_date(value: object) -> str:
    """Display helper: a date / timestamp → ``YYYY-MM-DD``; ``NaT`` / blank → em
    dash. Tolerates strings and anything `pd.to_datetime` can parse."""
    if value is None:
        return "—"
    try:
        ts = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return _na(value)
    if pd.isna(ts):
        return "—"
    return ts.strftime("%Y-%m-%d")


def _profile_meta_rows(row: pd.Series) -> str:
    """The profile card's label/value grid cells, one pair per configured field.

    `render_template` substitutes `{{key}}` and nothing else — it has no loop —
    so a schema-driven row list has to be assembled here and passed as one
    pre-rendered block. Labels come from `field_label`; a `date`-role field is
    formatted rather than str()'d, and every value stays NA-safe.
    """
    cells = []
    for key in PROFILE_CARD_FIELDS:
        value = (
            _fmt_date(row.get(key))
            if catalog_field(key).role == "date"
            else _na(row.get(key))
        )
        cells.append(
            f"<span style='color:{STYLE_CTX['text_muted']};'>"
            f"{html.escape(field_label(key))}</span>"
            f"<span style='color:{STYLE_CTX['text_color']};'>"
            f"{html.escape(value)}</span>"
        )
    return "\n    ".join(cells)


def _render_profile_card(row: pd.Series) -> str:
    """Render the Single Strategy metadata card from one ``meta`` row.

    Every field is `html.escape`'d and NA-safe (`_na` / `_fmt_date` → em dash), so
    a record missing a ``description`` / ``currency`` / ``live_date`` still
    renders cleanly."""
    return render_template(
        "profile_card",
        **STYLE_CTX,
        name=html.escape(_na(row.get("name"))),
        ticker=html.escape(_na(row.get("ticker"))),
        meta_rows=_profile_meta_rows(row),
        description=html.escape(_na(row.get("description"))),
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
