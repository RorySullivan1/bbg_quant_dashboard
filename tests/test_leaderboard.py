"""The `Leaderboard` widget (v0.9.20, #288).

The board is a fixed grid of permanent slots that `update` / `clear` rewrite,
so these tests pin the two things that structure buys: a slot count that does
not move with the data, and a click contract that holds for a filled row, a
blank one, and a board with nothing wired to it.

Rendering is not asserted (a widget's appearance is not unit-testable, per
`testing_notes.md`); what is asserted is the state the renderer reads —
descriptions, tooltips, the value colour and each row's visibility.
"""

from __future__ import annotations

import pytest
from src.commentary import LeaderboardColumn, LeaderboardRow
from src.config import LEADERBOARD_ROWS, RANKABLE_METRICS
from src.layout.leaderboard import Leaderboard
from src.style import Color, Sentiment


def _row(
    rank: int,
    ticker: str,
    value: float,
    sentiment: Sentiment,
    score: float | None = None,
) -> LeaderboardRow:
    # A row carries both numbers since #310: the score it is ranked by and the
    # raw metric that score was computed from. These widget tests are about the
    # slots and the click routing, so the score defaults to tracking the value.
    score = value if score is None else score
    return LeaderboardRow(
        rank=rank,
        ticker=ticker,
        name=f"Name {ticker.split()[0]}",
        score=score,
        score_text=f"{score:+.2f}",
        value=value,
        text=f"{value:+.2f}",
        sentiment=sentiment,
    )


def _column(metric: str, label: str, *, top: int = 3, bottom: int = 3):
    tops = tuple(
        _row(i + 1, f"T{i}{metric[:1].upper()} Index", 5.0 - i, Sentiment.POSITIVE)
        for i in range(top)
    )
    bottoms = tuple(
        _row(50 + i, f"B{i}{metric[:1].upper()} Index", -1.0 - i, Sentiment.NEGATIVE)
        for i in range(bottom)
    )
    return LeaderboardColumn(metric=metric, label=label, top=tops, bottom=bottoms)


def _full_board(**kw) -> tuple[LeaderboardColumn, ...]:
    return tuple(_column(metric, label, **kw) for metric, label in RANKABLE_METRICS)


def _visible(slot) -> bool:
    return slot.root.layout.visibility == "visible"


# ---- structure -------------------------------------------------------------


def test_board_has_a_column_per_metric_with_fixed_slots():
    board = Leaderboard()

    assert list(board.columns) == [metric for metric, _ in RANKABLE_METRICS]
    for (metric, label), column in zip(
        RANKABLE_METRICS, board.columns.values(), strict=True
    ):
        assert column.metric == metric
        # The title is rendered from the declared label, not re-spelled here.
        assert label in column.title_w.value
        assert len(column.slots) == 2 * LEADERBOARD_ROWS
        # Title + top block + divider + bottom block.
        assert len(column.root.children) == 2 * LEADERBOARD_ROWS + 2


def test_a_new_board_is_blank_and_titles_nothing_itself():
    # Since #306 the board carries no title of its own: `section_panel` heads
    # the section and the Window chips say which window is on screen, so a
    # `Ranking · Past Month` line here would be a third voice saying it.
    board = Leaderboard()

    assert not hasattr(board, "title_w")
    for column in board.columns.values():
        assert all(slot.shown is None for slot in column.slots)
        assert not any(_visible(slot) for slot in column.slots)


# ---- update / clear --------------------------------------------------------


def test_update_fills_every_slot():
    board = Leaderboard()
    board.update(_full_board())

    for column in board.columns.values():
        assert all(_visible(slot) for slot in column.slots)
        top = column.slots[0]
        assert top.rank.description == "1"
        assert top.ticker.description == top.shown
        # `Rank | Ticker | Score (value)` since #306: the score leads the
        # numbers because it is what the column is ranked by, and the raw value
        # it was computed from follows in parentheses.
        assert top.score.description == "+5.00"
        assert top.value.description == "(+5.00)"
        assert top.score.style.text_color == Sentiment.POSITIVE.value
        assert top.value.style.text_color is None  # muted by its class
        # Every cell carries the strategy name, so the hover works anywhere.
        assert all("Name" in cell.tooltip for cell in top.cells)
        # The bottom block keeps its true catalog ranks.
        assert [s.rank.description for s in column.slots[LEADERBOARD_ROWS:]] == [
            str(50 + i) for i in range(LEADERBOARD_ROWS)
        ]


def test_clear_blanks_the_slots():
    board = Leaderboard()
    board.update(_full_board())
    board.clear()

    for column in board.columns.values():
        for slot in column.slots:
            assert slot.shown is None
            assert not _visible(slot)
            assert all(cell.description == "" for cell in slot.cells)
            assert slot.value.style.text_color is None


def test_a_short_column_hides_its_tail_slots_rather_than_dropping_them():
    board = Leaderboard()
    board.update(_full_board(top=LEADERBOARD_ROWS, bottom=1))

    for column in board.columns.values():
        assert len(column.slots) == 2 * LEADERBOARD_ROWS  # nothing removed
        assert all(_visible(s) for s in column.slots[:LEADERBOARD_ROWS])
        # The bottom block fills from its first slot; the rest blank in place.
        assert _visible(column.slots[LEADERBOARD_ROWS])
        assert not any(_visible(s) for s in column.slots[LEADERBOARD_ROWS + 1 :])


def test_update_with_no_columns_blanks_a_filled_board():
    """An empty universe must not leave the previous window's rows on screen
    while the chips claim a different window."""
    board = Leaderboard()
    board.update(_full_board())
    board.update(())

    for column in board.columns.values():
        assert not any(_visible(slot) for slot in column.slots)


def test_update_matches_columns_by_metric_not_by_position():
    board = Leaderboard()
    only_sortino = (_column("sortino", "Sortino"),)
    board.update(only_sortino)

    for metric, column in board.columns.items():
        filled = any(_visible(slot) for slot in column.slots)
        assert filled is (metric == "sortino")


def test_neutral_values_take_the_bright_chrome_text_not_brand_navy():
    """`Sentiment.NEUTRAL` is brand navy, which is illegible on the dark
    surface — the board remaps it the way the dark cards do."""
    board = Leaderboard()
    neutral = LeaderboardColumn(
        metric="sharpe",
        label="Sharpe",
        top=(_row(1, "AAA Index", 0.0, Sentiment.NEUTRAL),),
        bottom=(),
    )
    board.update((neutral,))

    slot = board.columns["sharpe"].slots[0]
    # The colour sits on the score, not the value: #310 made sentiment follow
    # the score, which is what the row is ranked and read by.
    assert slot.score.style.text_color == str(Color.TEXT)
    assert slot.value.style.text_color is None
    assert slot.value.style.text_color != str(Sentiment.NEUTRAL.value)


# ---- the click contract ----------------------------------------------------


@pytest.mark.parametrize("cell_name", ["rank", "ticker", "score", "value"])
def test_clicking_any_cell_of_a_filled_row_picks_that_row_once(cell_name):
    picked: list[str] = []
    board = Leaderboard(on_pick=picked.append)
    board.update(_full_board())

    slot = board.columns["calmar"].slots[0]
    getattr(slot, cell_name).click()

    assert picked == [slot.shown]


def test_clicking_a_blank_slot_does_nothing():
    picked: list[str] = []
    board = Leaderboard(on_pick=picked.append)
    board.update(_full_board(top=1, bottom=0))

    blank = board.columns["return"].slots[-1]
    assert blank.shown is None
    for cell in blank.cells:
        cell.click()

    assert picked == []


def test_clicking_a_cleared_row_does_nothing():
    picked: list[str] = []
    board = Leaderboard(on_pick=picked.append)
    board.update(_full_board())
    board.clear()

    board.columns["return"].slots[0].ticker.click()

    assert picked == []


def test_a_board_with_no_on_pick_swallows_the_click():
    board = Leaderboard()
    board.update(_full_board())

    board.columns["sharpe"].slots[0].ticker.click()  # must not raise


def test_a_refilled_row_picks_its_new_ticker():
    """Slots are permanent, so a stale ticker behind a re-rendered row would
    route a click to whatever the previous window showed."""
    picked: list[str] = []
    board = Leaderboard(on_pick=picked.append)
    board.update(_full_board())
    first = board.columns["return"].slots[0].shown

    replacement = LeaderboardColumn(
        metric="return",
        label="Return",
        top=(_row(1, "ZZZ Index", 9.0, Sentiment.POSITIVE),),
        bottom=(),
    )
    board.update((replacement,))
    board.columns["return"].slots[0].ticker.click()

    assert picked == ["ZZZ Index"]
    assert first != "ZZZ Index"


# --- the day window (v0.9.40) -------------------------------------------------


def _hidden(board: Leaderboard) -> set[str]:
    return {m for m, c in board.columns.items() if c.root.layout.display == "none"}


def test_a_window_hides_the_columns_it_does_not_offer():
    """At 1D only Return is defined. The other three are **hidden**, not
    blanked — three empty columns under their titles would read as a board
    that failed to load."""
    from src.config import DAY_WINDOW, leaderboard_metrics

    board = Leaderboard()
    board.update(
        (_column("return", "Return"),), metrics=leaderboard_metrics(DAY_WINDOW)
    )
    assert _hidden(board) == {"sharpe", "calmar", "sortino"}
    # The one it does show is filled.
    assert any(_visible(slot) for slot in board.columns["return"].slots)


def test_the_hidden_columns_come_back_on_a_wider_window():
    from src.config import DAY_WINDOW, WEEK_WINDOW, leaderboard_metrics

    board = Leaderboard()
    board.update(
        (_column("return", "Return"),), metrics=leaderboard_metrics(DAY_WINDOW)
    )
    board.update(_full_board(), metrics=leaderboard_metrics(WEEK_WINDOW))
    assert _hidden(board) == set()


def test_an_offered_metric_with_no_rows_shows_its_title_rather_than_vanishing():
    """Why `metrics` is passed rather than inferred from `columns`: a metric
    the window offers can still come back with nothing scorable, and that
    column should stand empty under its title, not disappear."""
    board = Leaderboard()
    board.update((_column("return", "Return"),))  # default: all four offered
    assert _hidden(board) == set()
    assert not any(_visible(slot) for slot in board.columns["sharpe"].slots)


def test_clear_restores_all_four_columns():
    """An empty board is still the four-metric board, not a one-day one."""
    from src.config import DAY_WINDOW, leaderboard_metrics

    board = Leaderboard()
    board.update(
        (_column("return", "Return"),), metrics=leaderboard_metrics(DAY_WINDOW)
    )
    board.clear()
    assert _hidden(board) == set()


def test_only_return_is_defined_over_a_single_observation():
    """The rule, in config, that the builder and the board both read."""
    from src.config import DAY_WINDOW, leaderboard_metrics

    assert [m for m, _ in leaderboard_metrics(DAY_WINDOW)] == ["return"]
    # Every wider window the board offers ranks all four, in their order.
    from src.config import LEADERBOARD_WINDOW_OPTIONS

    for _label, days in LEADERBOARD_WINDOW_OPTIONS:
        if days > DAY_WINDOW:
            assert leaderboard_metrics(days) == RANKABLE_METRICS
