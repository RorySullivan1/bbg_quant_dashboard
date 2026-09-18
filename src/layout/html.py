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
import re
from collections.abc import Sequence
from functools import cache
from pathlib import Path

import pandas as pd

from ..commentary import CommentaryNote, LaunchCard
from ..config import (
    NEW_LAUNCH_DAYS,
    PROFILE_CARD_FIELDS,
    TEMPLATES_DIR,
    catalog_field,
    field_label,
)
from ..style import (
    CATALOG_HEADER_ROW_HEIGHT,
    CATALOG_TABLE_HEIGHT,
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
    # The Platform row's height — the table's box and the rail's, one value.
    "table_height": CATALOG_TABLE_HEIGHT,
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


def _render_empty_card(message: str) -> str:
    """The dashed "there is nothing here" box both bulletin boards fall back to.

    One template (`empty_card`, named `launch_empty` until #307) because the box
    has never had anything launch-specific in it, and a board reached by a
    deliberate click must say it is empty rather than render blank — which is
    equally true of the notes and of the launches.
    """
    return render_template("empty_card", **STYLE_CTX, message=html.escape(message))


#: Splits a note's text into paragraphs. A blank line — with any trailing
#: whitespace on it — separates them; a single newline does not, so a wrapped
#: sentence stays one paragraph.
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _render_note_paragraphs(text: str) -> str:
    """A note's plain text as `<p>`s, escaped.

    **Escape first, then split.** The note is plain text by contract (#304), so
    a `<b>` in it is shown as typed rather than interpreted — the notes are
    authored data, and a board that renders data as markup is a board that
    renders whatever the data says. Escaping after the split would work equally
    well; escaping first makes it impossible to add a branch later that forgets.

    Blank chunks are dropped, so a stray run of blank lines does not emit an
    empty paragraph.
    """
    escaped = html.escape(text)
    chunks = (chunk.strip() for chunk in _PARAGRAPH_BREAK.split(escaped))
    return "".join(f"<p>{chunk}</p>" for chunk in chunks if chunk)


def _render_commentary_notes(notes: Sequence[CommentaryNote]) -> str:
    """The Commentary board: one card per note, in the order given.

    The order is the loader's — `load_commentary_notes` sorts newest first —
    and is not re-imposed here: two places deciding what "newest" means is how
    they come to disagree.

    Each note dates itself, which is why nothing here takes a `today`: the
    board used to stamp one date across the whole thing (#304).
    """
    if not notes:
        return render_template(
            "notes_board",
            **STYLE_CTX,
            cards=_render_empty_card(
                "No commentary yet — add a note to data/commentary.json."
            ),
        )
    cards = "".join(
        render_template(
            "commentary_card",
            **STYLE_CTX,
            title=html.escape(note.title),
            date=html.escape(note.date.isoformat()),
            paragraphs=_render_note_paragraphs(note.text),
        )
        for note in notes
    )
    return render_template("notes_board", **STYLE_CTX, cards=cards)


def _fmt_since_return(value: float | None) -> str:
    """A launch card's since-launch return, or an em dash when there isn't one.

    The builder returns None rather than a placeholder string, so the choice of
    what "no return yet" looks like stays here with the rest of the presentation.
    """
    return "—" if value is None else f"{value:+.1%}"


def _render_launch_cards(cards: list[LaunchCard]) -> str:
    if not cards:
        return _render_empty_card(
            f"No new launches in the past {NEW_LAUNCH_DAYS} days."
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

    **No `<h3>New Launches</h3>` since #307:** the section is titled "QIS
    Bulletin" and the chip that opened this board is still lit, so a heading
    here would be the third thing naming it. The muted caption stays — it is
    the only place the launch window is stated, and it reads `NEW_LAUNCH_DAYS`
    rather than re-spelling it, so widening the window re-captions the board on
    its own.
    """
    return render_template(
        "launches_board",
        **STYLE_CTX,
        subtitle=html.escape(f"Live in the past {NEW_LAUNCH_DAYS} days"),
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
