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
from ..stats import SINCE_INCEPTION, metric_unit
from ..style import (
    BETA_HEAT_BAND,
    CATALOG_HEADER_ROW_HEIGHT,
    CATALOG_TABLE_HEIGHT,
    CORR_HEAT_BAND,
    MISSING_DASH,
    RETURN_HEAT_BAND,
    SHARPE_HEAT_BAND,
    VOLADJ_HEAT_BAND,
    Color,
    Font,
    FontSize,
    HeatBand,
    StatusTone,
)
from .theme import _short_ticker

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
    # The diverging heat fills, for the HTML calendar's five step classes
    # (#366). The same tokens the ipydatagrid renderers pass to VegaExpr —
    # one palette, two stacks.
    "heat_pos_strong": Color.HEAT_POS_STRONG,
    "heat_pos_soft": Color.HEAT_POS_SOFT,
    "heat_neg_soft": Color.HEAT_NEG_SOFT,
    "heat_neg_strong": Color.HEAT_NEG_STRONG,
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


#: Said beside the ticker when the picked strategy has no row in the table
#: above — the filters are hiding it, and the card is the only thing on screen
#: that can say so (#363 dec. 2). The pick is deliberately *not* cleared: the
#: user named the strategy they want, and the table narrowing underneath it is
#: a separate act from choosing what to look at.
FILTERED_OUT_NOTE: str = "not shown by the current filters"


def _render_profile_card(row: pd.Series, *, shown: bool = True) -> str:
    """Render the Single Strategy metadata card from one ``meta`` row.

    Every field is `html.escape`'d and NA-safe (`_na` / `_fmt_date` → em dash), so
    a record missing a ``description`` / ``currency`` / ``live_date`` still
    renders cleanly.

    ``shown`` is whether the picked strategy has a row in the table above.
    False adds `FILTERED_OUT_NOTE` beside the ticker."""
    note = (
        ""
        if shown
        else f"<span style='color:{STYLE_CTX['text_muted']};font-family:"
        f"{STYLE_CTX['sans']};'> · {html.escape(FILTERED_OUT_NOTE)}</span>"
    )
    return render_template(
        "profile_card",
        **STYLE_CTX,
        name=html.escape(_na(row.get("name"))),
        ticker=html.escape(_na(row.get("ticker"))),
        note=note,
        meta_rows=_profile_meta_rows(row),
        description=html.escape(_na(row.get("description"))),
    )


#: What a cell shows when the metric is NaN — a window the strategy has not
#: lived through, or a benchmark-dependent metric with no benchmark. An em
#: dash rather than a blank, so an unserved window reads as answered.
METRICS_NA: str = "\u2014"


def _metric_cell(value: float, unit: str) -> str:
    """One number, at two decimals, in the unit the metric reads in.

    Two decimals for everything is v0.9.32's rule, arrived at because the
    itables renderer had been printing four of the quant metrics at full
    float precision in an 82px cell. The only thing that varies between
    metrics is the unit, which `STRATEGY_METRICS` declares once each.
    """
    if value is None or pd.isna(value):
        return f"<span class='bbg-metrics-na'>{METRICS_NA}</span>"
    text = html.escape(f"{value:.2%}" if unit == "percent" else f"{value:.2f}")
    # **Red for negative, and no green.** The Leaderboard puts sentiment on
    # its score because that board ranks, and a ranking has a direction. Half
    # of these rows do not: a high Vol is not good, and a negative Beta is a
    # fact about the strategy rather than a bad one. Colouring by sign alone
    # says what a terminal says — this number is below zero — and claims
    # nothing else.
    return f"<span class='bbg-metrics-neg'>{text}</span>" if value < 0 else text


def _render_strategy_metrics(
    frame: pd.DataFrame, *, benchmark: str | None = None
) -> str:
    """The Single Strategy metrics table, as one styled HTML block (#366).

    `frame` is `stats.strategy_metrics`' output: the metric names down, the
    windows plus since-inception across. Rendering is the whole job here —
    every number is already computed, and nothing in this table sorts,
    scrolls or takes a click, which is why it is HTML rather than the two
    `ipydatagrid` canvases it replaced.

    `benchmark` names what Beta and Correlation are measured against. It goes
    in the corner cell, where the metric column meets the window row, because
    those two rows are the only ones it qualifies and a caption under the
    table would sit further from them than the header does.
    """
    if frame.empty:
        return ""
    corner = f"vs {html.escape(benchmark)}" if benchmark else "&nbsp;"
    headers = "".join(
        (
            f"<th class='bbg-metrics-si'>{html.escape(str(col))}</th>"
            if col == SINCE_INCEPTION
            else f"<th>{html.escape(str(col))}</th>"
        )
        for col in frame.columns
    )
    rows = []
    for metric in frame.index:
        unit = metric_unit(str(metric))
        cells = "".join(
            (
                f"<td class='bbg-metrics-si'>{_metric_cell(frame.loc[metric, col], unit)}</td>"
                if col == SINCE_INCEPTION
                else f"<td>{_metric_cell(frame.loc[metric, col], unit)}</td>"
            )
            for col in frame.columns
        )
        rows.append(f"<tr><th>{html.escape(str(metric))}</th>{cells}</tr>")
    return render_template(
        "strategy_metrics",
        **STYLE_CTX,
        corner=corner,
        headers=headers,
        rows="".join(rows),
    )


#: Which diverging band a calendar `kind`'s month cells are read on, and the
#: unit they read in. The bands are `style.py`'s, shared with the ipydatagrid
#: renderers so the two stacks cannot disagree about where neutral ends.
_CALENDAR_CELL_BANDS: dict[str, tuple[HeatBand, str]] = {
    "absolute": (RETURN_HEAT_BAND, "percent"),
    "outperformance": (RETURN_HEAT_BAND, "percent"),
    "vol_adjusted": (VOLADJ_HEAT_BAND, "ratio"),
    "beta": (BETA_HEAT_BAND, "ratio"),
    "correlation": (CORR_HEAT_BAND, "ratio"),
}

#: Per summary column: its band (None = no ramp) and its unit. **Vol has no
#: band** — a red→green ramp there would claim a good/bad axis volatility does
#: not have, which is the same call the metrics table makes by using no green
#: at all.
_CALENDAR_SUMMARY_BANDS: dict[str, tuple[HeatBand | None, str]] = {
    "Return": (RETURN_HEAT_BAND, "percent"),
    "Bench": (RETURN_HEAT_BAND, "percent"),
    "Excess": (RETURN_HEAT_BAND, "percent"),
    "Vol": (None, "percent"),
    "Sharpe": (SHARPE_HEAT_BAND, "ratio"),
    "Bench Sharpe": (SHARPE_HEAT_BAND, "ratio"),
    "Beta": (BETA_HEAT_BAND, "ratio"),
    "Correlation": (CORR_HEAT_BAND, "ratio"),
}

#: The heat class for each step of a band, strongest-negative first. Classes
#: rather than inline backgrounds, so the colours stay in `app_css.html` with
#: every other token — the cell carries *which step*, not which hex.
_HEAT_CLASSES: tuple[str, ...] = (
    "bbg-heat-neg2",
    "bbg-heat-neg1",
    "",
    "bbg-heat-pos1",
    "bbg-heat-pos2",
)


def _heat_class(value: float, band: HeatBand | None) -> str:
    """Which heat step `value` falls in, as a CSS class (empty = neutral)."""
    if band is None or value is None or pd.isna(value):
        return ""
    step = sum(1 for edge in band if value >= edge)
    return _HEAT_CLASSES[step]


def _calendar_cell(value: float, band: HeatBand | None, unit: str) -> str:
    """One calendar cell: its shaded `<td>`, or a dash when empty."""
    if value is None or pd.isna(value):
        return f"<td class='bbg-cal-na'>{MISSING_DASH}</td>"
    text = html.escape(f"{value:.2%}" if unit == "percent" else f"{value:.2f}")
    css = _heat_class(value, band)
    return f"<td class='{css}'>{text}</td>" if css else f"<td>{text}</td>"


#: The gap between the readout's metric column and its values, in characters.
#: The annotation is drawn in the chart's mono font, so padding aligns the
#: values into a column the way the HTML table's `text-align: right` does —
#: added to the **longest label present** rather than to a fixed width, which
#: `Return (cumulative)` (19 characters against a 12-wide column) overflowed.
_READOUT_LABEL_GAP: int = 2


def _render_span_readout(frame: pd.DataFrame, *, benchmark: str | None = None) -> str:
    """The zoom readout drawn **inside** the cumulative chart (#380).

    `frame` is `stats.span_metrics`' output — one `value` column indexed by
    metric, with `start` / `end` / `days` / `annualized` on `.attrs`.

    This returns **annotation text, not a widget**: ipywidgets cannot overlay
    HTML on a figure, and Plotly annotations accept a small HTML subset
    (`<br>`, `<b>`, `<span style>`), which is enough for a headed column of
    numbers. Spaces collapse in that subset, so the metric column is padded
    with `&nbsp;` rather than with spaces.

    It reads `metric_unit` and `_metric_cell`'s two-decimal rule through the
    same helpers the table below the chart uses, so the panel and the table
    cannot disagree about how a number is written.
    """
    if frame is None or frame.empty:
        return ""
    start, end = frame.attrs.get("start"), frame.attrs.get("end")
    days = int(frame.attrs.get("days") or 0)
    annualized = bool(frame.attrs.get("annualized"))

    span = (
        f"{start:%Y-%m-%d} \u2192 {end:%Y-%m-%d}"
        if start is not None and end is not None
        else ""
    )
    # Say which regime the numbers are in, so a missing Sharpe reads as a
    # decision rather than as a gap (#380).
    basis = "annualized" if annualized else "cumulative, &lt; 1Y"
    head = f"<b>{html.escape(span)}</b>" if span else ""
    if head:
        head += f"&nbsp;&middot;&nbsp;{days}d&nbsp;&middot;&nbsp;{basis}"

    lines = [head] if head else []
    width = max((len(str(m)) for m in frame.index), default=0) + _READOUT_LABEL_GAP
    for metric, value in frame["value"].items():
        unit = metric_unit(str(metric))
        if value is None or pd.isna(value):
            text = METRICS_NA
        else:
            text = f"{value:.2%}" if unit == "percent" else f"{value:.2f}"
            if value < 0:
                # The table's rule: red for negative, and no green (#366) —
                # and the table's own `{{red}}`, which is solid. The `HEAT_*`
                # reds carry an alpha suffix, and an 8-digit hex inside an
                # annotation's inline style is at the mercy of the SVG text
                # renderer where the CSS class below the chart is not.
                text = f"<span style='color:{Color.RED_600.value}'>{text}</span>"
        label = html.escape(str(metric))
        pad = "&nbsp;" * max(width - len(str(metric)), 1)
        lines.append(f"{label}{pad}{text}")

    if benchmark:
        lines.append(
            f"<span style='color:{Color.TEXT_MUTED.value}'>"
            f"vs {html.escape(_short_ticker(benchmark))}</span>"
        )
    return "<br>".join(lines)


def _render_calendar(table: pd.DataFrame, *, kind: str) -> str:
    """The monthly-return calendar, as one styled HTML block (#366).

    `table` is `stats.calendar_return_table`'s frame — years down, Jan…Dec
    across, then the `kind`'s summary columns. Oldest year on top, each cell
    shaded on the band its `kind` reads on.

    **The heatmap survived the grid.** #363 decision 4 left its fate open, to
    be settled against the terminal: it is the one thing on this tab a desk
    reads at a glance, and the metrics table does not replace it — that table
    is summary statistics and this is the path they came from. What went is
    the `ipydatagrid` canvas under it, whose dark theme has to be re-asserted
    on every write (#223) for a grid that never sorts, scrolls sideways or
    takes a click. The summary columns are set off by a rule, as the metrics
    table sets off since-inception, because they are annual aggregates
    sitting beside twelve monthly cells.
    """
    if table is None or table.empty:
        return ""
    frame = table.sort_index(ascending=True)
    month_band, month_unit = _CALENDAR_CELL_BANDS[kind]
    summary = [c for c in frame.columns if c in _CALENDAR_SUMMARY_BANDS]
    first_summary = summary[0] if summary else None

    def _edge(col: object) -> str:
        return " bbg-cal-edge" if col == first_summary else ""

    headers = "".join(
        (
            f"<th class='{_edge(col).strip()}'>{html.escape(str(col))}</th>"
            if _edge(col)
            else f"<th>{html.escape(str(col))}</th>"
        )
        for col in frame.columns
    )
    rows = []
    for year in frame.index:
        cells = []
        for col in frame.columns:
            band, unit = _CALENDAR_SUMMARY_BANDS.get(col, (month_band, month_unit))
            cell = _calendar_cell(frame.loc[year, col], band, unit)
            if _edge(col):
                cell = cell.replace("<td class='", "<td class='bbg-cal-edge ", 1)
                if "bbg-cal-edge" not in cell:
                    cell = cell.replace("<td>", "<td class='bbg-cal-edge'>", 1)
            cells.append(cell)
        label = html.escape(str(int(year)))
        rows.append(f"<tr><th>{label}</th>{''.join(cells)}</tr>")
    return render_template(
        "calendar",
        **STYLE_CTX,
        headers=headers,
        rows="".join(rows),
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
