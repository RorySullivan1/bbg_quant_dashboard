"""The commentary block's ranked leaderboard (v0.9.20, #288).

Four columns — one per `RANKABLE_METRICS` entry — each listing the catalog's
top and bottom few indices as `rank · ticker · value` rows over the window the
board is titled with. **One at 1D** (v0.9.40): the window's metrics come from
`config.leaderboard_metrics`, and the columns it does not offer are hidden. Clicking a row hands its ticker to `on_pick`, the same
contract `UniverseGrid` uses to open a strategy in the Single Strategy tab: a
click with no `on_pick` wired, or on a slot that is currently blank, does
nothing.

The object owns its widgets and rewrites them in place (`update` / `clear`),
per the v0.9.17 rule that a table is an object rather than a factory paired
with a loose updater. It holds no catalog metadata: `update` takes the already
built `LeaderboardColumn`s, so a re-pointed catalog cannot leave a stale frame
behind an attribute (#242).

**Why a row is four buttons and not one.** An ipywidgets `Button` renders its
`description` as a single text node, so the whole label takes one colour — but
a row needs four treatments: a dimmed rank, the ticker in the primary text
colour, the **score** coloured by its sentiment, and the raw value it was
computed from, muted, in parentheses. A row is therefore an `HBox` of four
buttons that CSS draws as one continuous strip, with the hover coming off the
row container (`.bbg-lb-row:hover`) so all four light up together, and all four
wired to the same handler so any part of the row navigates. Drawing the rank as
a `W.HTML` instead would be one widget fewer and a dead strip inside a row
whose whole point is that it is clickable.

The score leads the numbers because it is what the column is ranked by (#310);
the value rides behind it so a reader can see what was standardized.
"""

from __future__ import annotations

import html
from collections.abc import Callable

import ipywidgets as W

from ..commentary import LeaderboardColumn, LeaderboardRow
from ..config import LEADERBOARD_ROWS, RANKABLE_METRICS
from ..style import Color, Sentiment
from .html import STYLE_CTX, render_template


def _value_color(sentiment: Sentiment) -> str:
    """Sentiment → a row's value colour on the dark surface.

    Reuses the shared green/red sentiment palette but maps ``NEUTRAL`` to the
    bright chrome text token: the shared ``Sentiment.NEUTRAL`` is brand navy,
    which is illegible here.

    Takes the enum member, not its name. `Sentiment` is a `StrEnum` over *color*
    values, so a member's string form is a hex code — feeding one to
    `_sentiment_color`, which looks up by member *name*, would miss and silently
    return neutral for every row.

    (Lived in `html.py` as `_superlative_value_color` until v0.9.20 #291, when
    the cards it was written for were retired and the leaderboard, its only
    remaining caller, took it in.)
    """
    if sentiment is Sentiment.NEUTRAL:
        return str(Color.TEXT)
    return str(sentiment.value)


#: Cell widths. The ticker cell flexes; the rank, score and value cells are
#: fixed so the four columns' numbers line up vertically regardless of ticker
#: length.
_RANK_WIDTH = "32px"
_SCORE_WIDTH = "52px"
_VALUE_WIDTH = "62px"
_ROW_HEIGHT = "22px"


class _RowSlot:
    """One leaderboard row: three buttons that read, and click, as one row.

    A slot is permanent — filling and blanking rewrite it rather than building
    or dropping widgets — so the four columns keep a fixed height and a blanked
    row leaves a gap instead of collapsing the board. `shown` is the ticker the
    slot currently displays, and `None` when it is blank; it is the guard that
    makes a click on a blank slot a no-op.
    """

    def __init__(self, *, notify: Callable[[str], None]) -> None:
        self._notify = notify
        self.shown: str | None = None
        self.rank = self._cell("bbg-lb-rank", width=_RANK_WIDTH)
        self.ticker = self._cell("bbg-lb-ticker", width="auto", flex="1 1 auto")
        self.score = self._cell("bbg-lb-score", width=_SCORE_WIDTH)
        self.value = self._cell("bbg-lb-value", width=_VALUE_WIDTH)
        self.cells = (self.rank, self.ticker, self.score, self.value)
        self.root = W.HBox(
            list(self.cells),
            layout=W.Layout(width="100%", align_items="center"),
        )
        self.root.add_class("bbg-lb-row")
        for cell in self.cells:
            cell.on_click(self._clicked)
        self.blank()

    @staticmethod
    def _cell(css_class: str, *, width: str, flex: str | None = None) -> W.Button:
        btn = W.Button(
            layout=W.Layout(width=width, height=_ROW_HEIGHT, padding="0", flex=flex)
        )
        btn.add_class("bbg-lb-cell")
        btn.add_class(css_class)
        return btn

    def _clicked(self, _btn: W.Button) -> None:
        if self.shown is not None:
            self._notify(self.shown)

    def fill(self, row: LeaderboardRow) -> None:
        self.shown = row.ticker
        self.rank.description = str(row.rank)
        self.ticker.description = row.ticker
        self.score.description = row.score_text
        # Parenthesized so the two numbers cannot be misread as one figure and
        # its change: the score is the reading, the value is what it was
        # computed from.
        self.value.description = f"({row.text})"
        tooltip = f"{row.name} ({row.ticker})"
        for cell in self.cells:
            cell.tooltip = tooltip
        # The one per-row inline style: the colour is data, so it cannot come
        # from the stylesheet the way the rank and ticker colours do. It sits
        # on the **score**, which is what the row is ranked and read by (#310),
        # while the raw value stays muted by its own class. Neutral maps to
        # bright chrome text, not the shared brand navy, which is illegible on
        # the dark surface.
        self.score.style.text_color = _value_color(row.sentiment)
        self.root.layout.visibility = "visible"

    def blank(self) -> None:
        self.shown = None
        for cell in self.cells:
            cell.description = ""
            cell.tooltip = ""
        self.score.style.text_color = None
        # Hidden, not undisplayed: an unused slot still occupies its row, so a
        # short column does not pull the divider and the rows below it upward.
        self.root.layout.visibility = "hidden"


class _MetricColumn:
    """One metric's column: a title, `rows` top slots, a divider, `rows` bottom
    slots. The divider is always drawn, so the top and bottom blocks stay
    visually separated even when one of them is short."""

    def __init__(
        self, metric: str, label: str, *, rows: int, notify: Callable[[str], None]
    ) -> None:
        self.metric = metric
        self.label = label
        self.rows = rows
        self.title_w = W.HTML(
            render_template(
                "leaderboard_column_title", **STYLE_CTX, text=html.escape(label)
            )
        )
        self.slots = [_RowSlot(notify=notify) for _ in range(2 * rows)]
        self.divider = W.Box([], layout=W.Layout(height="1px", margin="4px 0"))
        self.divider.add_class("bbg-lb-divider")
        self.root = W.VBox(
            [
                self.title_w,
                *(slot.root for slot in self.slots[:rows]),
                self.divider,
                *(slot.root for slot in self.slots[rows:]),
            ],
            layout=W.Layout(flex="1 1 0%", padding="0 8px", min_width="0"),
        )
        self.root.add_class("bbg-lb-col")

    def fill(self, column: LeaderboardColumn | None) -> None:
        """Write `column` into the slots, blanking whatever it does not reach.

        A column carrying fewer rows than the board has slots is the normal
        small-catalog case, not an error — the surplus slots blank and stay in
        place.
        """
        if column is None:
            self.blank()
            return
        # `strict=False` on the fills below is the point: a column may carry
        # fewer rows than the board has slots. The loops after each fill blank
        # whatever it did not reach.
        top = column.top[: self.rows]
        bottom = column.bottom[: self.rows]
        for slot, row in zip(self.slots[: self.rows], top, strict=False):
            slot.fill(row)
        for slot in self.slots[len(top) : self.rows]:
            slot.blank()
        for slot, row in zip(self.slots[self.rows :], bottom, strict=False):
            slot.fill(row)
        for slot in self.slots[self.rows + len(bottom) :]:
            slot.blank()

    def blank(self) -> None:
        for slot in self.slots:
            slot.blank()


class Leaderboard:
    """The four-column ranked board, mounted from `.root`.

    `on_pick` receives the ticker of a clicked row. It is optional so the board
    can be built and exercised without the app that routes the click.
    """

    def __init__(
        self,
        *,
        on_pick: Callable[[str], None] | None = None,
        rows: int = LEADERBOARD_ROWS,
    ) -> None:
        self._on_pick = on_pick
        self.rows = rows
        # No title of its own since #306: `section_panel` heads the section and
        # the Window chips beside it say which window is on screen, so a
        # `Ranking · Past Month` line here would be the third thing saying so.
        # Keyed by metric, in `RANKABLE_METRICS` order, so `update` can match
        # the columns it is handed by key rather than by position and the titles
        # are never re-spelled here.
        self.columns: dict[str, _MetricColumn] = {
            metric: _MetricColumn(metric, label, rows=rows, notify=self._pick)
            for metric, label in RANKABLE_METRICS
        }
        self.body = W.HBox(
            [column.root for column in self.columns.values()],
            layout=W.Layout(width="100%", align_items="flex-start"),
        )
        self.root = W.VBox([self.body], layout=W.Layout(width="100%", min_width="0"))
        # No `bbg-card`: the board sits inside `section_panel`'s box now, and
        # two bordered surfaces nested would draw two frames (#306).
        self.root.add_class("bbg-leaderboard")
        self.clear()

    def _pick(self, ticker: str) -> None:
        if self._on_pick is not None:
            self._on_pick(ticker)

    def update(
        self,
        columns: tuple[LeaderboardColumn, ...],
        *,
        metrics: tuple[tuple[str, str], ...] = RANKABLE_METRICS,
    ) -> None:
        """Rewrite every slot from `columns`, showing only `metrics`.

        Columns are matched by `metric`, so a short or reordered tuple fills
        what it names and blanks the rest — an empty tuple (an empty universe)
        blanks the whole board rather than leaving the last window's rows on
        screen while the chips claim a different one.

        **`metrics` is what the window offers, and the rest are hidden, not
        blanked** (v0.9.40). At 1D only Return is defined; three empty columns
        headed Sharpe, Calmar and Sortino would read as a board that failed to
        load. It is passed separately from `columns` rather than inferred from
        them because the two mean different things: a metric the window offers
        can still come back with no scorable rows, and that column should show
        its title over empty slots, not vanish.
        """
        shown = {metric for metric, _label in metrics}
        by_metric = {column.metric: column for column in columns}
        for metric, column in self.columns.items():
            column.root.layout.display = "" if metric in shown else "none"
            column.fill(by_metric.get(metric))

    def clear(self) -> None:
        """Blank every column and show all four — an empty board is still the
        four-metric board, not a one-day one."""
        for column in self.columns.values():
            column.root.layout.display = ""
            column.blank()
