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

from ..commentary import LaunchCard
from ..config import (
    NEW_LAUNCH_DAYS,
    PROFILE_CARD_FIELDS,
    TEMPLATES_DIR,
    WEEKLY_COMMENTARY_PATH,
    catalog_field,
    field_label,
)
from ..style import (
    CATALOG_HEADER_ROW_HEIGHT,
    CATALOG_TABLE_MAX_HEIGHT,
    Color,
    Font,
    FontSize,
    StatusTone,
)

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
    # Group-header bands, level 0 (brightest) → 3. Level 0 *is* the accent, so
    # it is mapped rather than duplicated as its own token.
    "group_band0": Color.ACCENT,
    "group_band1": Color.GROUP_BAND_1,
    "group_band2": Color.GROUP_BAND_2,
    "group_band3": Color.GROUP_BAND_3,
    # The catalog header's label-row height, which is also the sticky offset
    # of the filter row beneath it (#285) — one value, used by both rules, so
    # they cannot drift apart and leave the filter row covering the labels.
    "filter_row_top": CATALOG_HEADER_ROW_HEIGHT,
    # The Platform row's height: the table's scroll cap and the rails' cap are
    # the same value, so the three containers stand level.
    "table_max_height": CATALOG_TABLE_MAX_HEIGHT,
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


def _render_launches(cards: list[LaunchCard]) -> str:
    """The New Launches board: the launch cards under a titled section.

    Split out of the retired two-section highlights renderer for the switchable
    commentary pane (v0.9.20, #289), which shows this board on its own rather
    than beside the superlative cards. Unlike that renderer it never returns
    `""` — the pane that mounts it is reached by a deliberate click, so an
    empty board must say there is nothing rather than leave the pane blank.
    `_render_launch_cards` supplies that message.

    The subtitle reads `NEW_LAUNCH_DAYS` rather than re-spelling the window, so
    widening the launch window retitles the board on its own.
    """
    return render_template(
        "launches_board",
        **STYLE_CTX,
        title=html.escape("New Launches"),
        subtitle=html.escape(f"· live in the past {NEW_LAUNCH_DAYS} days"),
        cards=_render_launch_cards(cards),
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
