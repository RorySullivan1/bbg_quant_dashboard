"""All-catalog commentary: the authored notes, the ranked leaderboard and the
New Launches cards.

The notes are *read* (`data/commentary.json`); the other two are *computed*
from the already-fetched price frame and the catalog metadata —
no BQL call of its own. The leaderboard ranks the whole catalog over a trailing
window on four metrics (return, Sharpe, Calmar, Sortino) and keeps the top and
bottom few of each; launch cards pick out indices that went live within
`NEW_LAUNCH_DAYS`.

Both builders return frozen dataclasses (`LeaderboardColumn` / `LeaderboardRow`
/ `LaunchCard`), so the field set lives here and the widgets in `layout/` read
attributes rather than guessing at dict keys with `.get()` defaults. Values
that are *presentation* — the launch date's format, the em dash for a return
that cannot be computed — are left to those renderers; this module returns a
`date` and a `float | None`.

The v0.8.x Market Superlatives board (16 single-winner cards over technical
indicators) was retired in v0.9.20 (#291) when the leaderboard replaced it. Its
metrics all live on in `src/stats/`; only the card builder went.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    COMMENTARY_PATH,
    LAUNCH_CARD_META_FIELDS,
    LEADERBOARD_ROWS,
    LEADERBOARD_WINDOW_DAYS,
    NEW_LAUNCH_DAYS,
    RANKABLE_METRICS,
    SCORE_SAMPLE_DAYS,
    TRADING_DAYS_PER_YEAR,
)
from .stats import (
    ann_sharpe,
    calmar_ratio,
    daily_returns,
    period_return,
    rolling_metric_zscore,
    sortino_ratio,
)
from .style import Sentiment


@dataclass(frozen=True)
class CommentaryNote:
    """One authored note in the QIS Bulletin (#304).

    `text` is **plain text**, carried verbatim: the escaping and the
    blank-line-to-paragraph split belong to the renderer, the way `LaunchCard`
    leaves its em dash to `_fmt_since_return`. A note dates itself, so the
    board no longer stamps every note with today.
    """

    title: str
    date: date
    text: str


def _parse_note(raw: object) -> CommentaryNote | None:
    """One entry to a `CommentaryNote`, or None if it is not one.

    Unknown keys pass without comment, so a field added later cannot break an
    older build reading a newer file.
    """
    if not isinstance(raw, dict):
        return None
    title, text, iso = raw.get("title"), raw.get("text"), raw.get("date")
    if not isinstance(title, str) or not isinstance(text, str):
        return None
    if not isinstance(iso, str):
        return None
    try:
        when = date.fromisoformat(iso)
    except ValueError:
        return None
    return CommentaryNote(title=title, date=when, text=text)


def load_commentary_notes(
    path: Path | str = COMMENTARY_PATH,
) -> list[CommentaryNote]:
    """The authored notes, newest first, or `[]` if there are none to load.

    Runs while the app is being built, so like `UserBenchmarkStore.load` it
    must not raise for any reason: a missing file, an unreadable one, malformed
    JSON and the wrong top-level shape all mean "no notes".

    **A missing file is silent; anything else says so.** A catalog with no
    commentary yet is an ordinary state, while a file that exists and cannot be
    read is a mistake someone wants to hear about. A single malformed note is
    skipped rather than voiding the file — one typo in an old note must not
    take today's note off the screen — and the warning names it so it can be
    fixed.

    Ties keep file order: the sort is stable, so two notes dated the same day
    read in the order they were written.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []  # no commentary yet — a normal state, not a fault
    except Exception as exc:  # noqa: BLE001 — a bad read must not block startup
        warnings.warn(
            f"Could not read {path} ({exc}); the bulletin will show no notes.",
            stacklevel=2,
        )
        return []

    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — malformed JSON is not fatal
        warnings.warn(
            f"{path} is not valid JSON ({exc}); the bulletin will show no notes.",
            stacklevel=2,
        )
        return []

    if not isinstance(parsed, list):
        warnings.warn(
            f"{path} does not hold a list of notes; the bulletin will show no notes.",
            stacklevel=2,
        )
        return []

    notes: list[CommentaryNote] = []
    for position, entry in enumerate(parsed):
        note = _parse_note(entry)
        if note is None:
            warnings.warn(
                f"Skipping note {position} in {path}: a note needs a string "
                '"title", a string "text", and an ISO-8601 "date".',
                stacklevel=2,
            )
            continue
        notes.append(note)

    return sorted(notes, key=lambda note: note.date, reverse=True)


@dataclass(frozen=True)
class LaunchCard:
    """One New Launch: an index that went live within `NEW_LAUNCH_DAYS`.

    `since_return` is the simple cumulative return since `live_date`, or None
    when the window holds too little history to compute one — the renderer
    decides what that looks like on screen.
    """

    name: str
    ticker: str
    meta: str
    live_date: date
    days_ago: int
    since_return: float | None


@dataclass(frozen=True)
class LeaderboardRow:
    """One ranked index in a leaderboard column.

    `rank` is the index's true 1-based position across the whole catalog for
    that metric, so a bottom row reads e.g. "52" of 54 rather than "3rd from
    last".

    The row carries **two** numbers (#310). `score` is the metric z-scored
    against its own rolling history, and it is what the column is ranked by —
    a column of raw numbers lists whoever is biggest, not who is unusual, and a
    6M Sharpe of 1.8 means different things for a vol-carry index and a trend
    index. `value` is that raw metric, kept so the row can show what the score
    was computed from. Each has its own formatter here, because they differ per
    column (percent for the window return, two decimals for the ratios) and the
    widget should not re-derive either.

    `sentiment` follows the **score**: it is what the row is ranked and read by.
    """

    rank: int
    ticker: str
    name: str
    score: float
    score_text: str
    value: float
    text: str
    sentiment: Sentiment


@dataclass(frozen=True)
class LeaderboardColumn:
    """One metric's ranking: the top rows and the bottom rows of the catalog.

    Both tuples run in rank order (rank 1 first; the catalog's last index
    last). They never share a ticker — a small catalog yields a short `bottom`
    rather than a repeated row.
    """

    metric: str
    label: str
    top: tuple[LeaderboardRow, ...]
    bottom: tuple[LeaderboardRow, ...]


def _sign_sentiment(value: float) -> Sentiment:
    if value > 0:
        return Sentiment.POSITIVE
    if value < 0:
        return Sentiment.NEGATIVE
    return Sentiment.NEUTRAL


def _rank_column(
    metric: str,
    label: str,
    scores: pd.Series,
    values: pd.Series,
    *,
    fmt: Callable[[float], str],
    name_of: Callable[[str], str],
    rows: int,
) -> LeaderboardColumn:
    """Rank by `scores` and keep the first and last `rows` entries.

    The rank is by the **score** — the z-score against the metric's own
    history, and the number the row leads with — so rank 1 is the most unusual
    reading rather than merely the biggest (#310, superseding #286's raw-value
    ranking). `values` rides along for display and never decides an order.

    An index needs both numbers to appear: NaN and infinite values on either
    side (a ratio whose denominator degenerated, a sample too short or too flat
    to standardize against) are excluded before ranking. Ties resolve by ticker
    so the board is deterministic run to run.
    """
    clean = scores.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    raw = values.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    clean = clean.loc[clean.index.intersection(raw.index)]
    # Sort by ticker first, then a stable sort by score, so equal scores keep
    # ticker order — the tie-break — without a second sort key.
    ranked = clean.sort_index().sort_values(ascending=False, kind="stable")

    def row(position: int) -> LeaderboardRow:
        ticker = str(ranked.index[position])
        score = float(ranked.iloc[position])
        value = float(raw.loc[ticker])
        return LeaderboardRow(
            rank=position + 1,
            ticker=ticker,
            name=name_of(ticker),
            score=score,
            score_text=f"{score:+.2f}",
            value=value,
            text=fmt(value),
            sentiment=_sign_sentiment(score),
        )

    n = len(ranked)
    top = tuple(row(i) for i in range(min(rows, n)))
    # The bottom block starts after the top block even when the catalog is too
    # small for both, so no ticker appears twice.
    bottom = tuple(row(i) for i in range(max(rows, n - rows), n))
    return LeaderboardColumn(metric=metric, label=label, top=top, bottom=bottom)


def build_leaderboard(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    window_days: int = LEADERBOARD_WINDOW_DAYS,
    rows: int = LEADERBOARD_ROWS,
    history_returns: pd.DataFrame | None = None,
) -> tuple[LeaderboardColumn, ...]:
    """Whole-catalog top / bottom `rows` on return, Sharpe, Calmar and Sortino,
    each **ranked by its z-score against its own history** (#310).

    Every column is scoped to the trailing ``window_days``: the return is the
    simple window return (``period_return``, not annualized), and the three
    ratios take ``years = window_days / TRADING_DAYS_PER_YEAR``, so all four
    columns agree on what "past month" means. Those raw values are what a row
    displays; what it is **ranked** by is `rolling_metric_zscore` of the same
    metric at the same window, standardized over
    ``SCORE_SAMPLE_DAYS`` of that metric's own rolling history.

    ``prices`` is the **whole fetched frame**, not a window of it: the score's
    sample needs the depth, and the raw metrics are unaffected because every
    one of them slices internally (``period_return`` tails by count, the ratios
    go through ``_slice_last_years``). ``returns`` is the ``window_returns``
    tail of it, for the ratios; pass ``history_returns`` — the catalog's full
    daily returns — so the four scorers do not each re-derive them.

    Computed from the fetched frames only, no BQL. An empty catalog yields an
    empty tuple; a metric with no scorable index yields a column with no rows.
    """
    if prices.empty or returns.empty:
        return ()

    name_lookup = meta.set_index("ticker")["name"].to_dict() if not meta.empty else {}

    def name_of(ticker: str) -> str:
        return name_lookup.get(ticker, ticker)

    # Two decimals, like every other number in a table (v0.9.32): the
    # Leaderboard is a table of four columns, and a `+1.2%` beside a `0.84`
    # read as two different kinds of precision for no reason anyone could
    # name.
    def pct(v: float) -> str:
        return f"{v:+.2%}"

    def num2(v: float) -> str:
        return f"{v:.2f}"

    years = window_days / TRADING_DAYS_PER_YEAR
    series_by_metric: dict[str, tuple[pd.Series, Callable[[float], str]]] = {
        "return": (period_return(prices, window_days=window_days), pct),
        "sharpe": (ann_sharpe(returns, prices, years), num2),
        "calmar": (calmar_ratio(prices, years), num2),
        "sortino": (sortino_ratio(returns, prices, years), num2),
    }

    def score_for(metric: str) -> pd.Series:
        """The metric at this window, z-scored against its own history.

        A frame too short to yield a rolling series at all scores nothing
        rather than raising — the board then has no rows, which is the same
        outcome as a metric that is NaN everywhere.
        """
        try:
            return rolling_metric_zscore(
                prices,
                metric=metric,
                window=window_days,
                zscore_window=SCORE_SAMPLE_DAYS,
                returns=history_returns,
            )
        except (IndexError, ValueError):
            return pd.Series(np.nan, index=prices.columns, dtype=float)

    return tuple(
        _rank_column(
            metric,
            label,
            score_for(metric),
            series_by_metric[metric][0],
            fmt=series_by_metric[metric][1],
            name_of=name_of,
            rows=rows,
        )
        for metric, label in RANKABLE_METRICS
    )


def window_returns(
    prices: pd.DataFrame, *, window_days: int = LEADERBOARD_WINDOW_DAYS
) -> pd.DataFrame:
    """Daily returns over just the trailing span ``build_leaderboard`` needs.

    Every returns-based column tails to ``window_days``, and the deepest reach
    is the Sharpe column's ``ann_volatility``, which slices returns to its
    ~``window_days``-trading-day date window. Deriving returns from the full
    multi-year price history is therefore wasted work. This returns
    ``daily_returns`` over a price tail that is a strict superset of every
    returns-based metric's window — including one extra leading row so the
    oldest kept return is computed against its true prior price — so feeding it
    to ``build_leaderboard`` yields an identical board to feeding the
    full-history returns, without the whole-history ``pct_change``.

    (Named ``superlative_returns`` until v0.9.20 #291, when the board it was
    written for was retired and the leaderboard inherited the tail.)
    """
    if prices.empty:
        return prices
    end = prices.index.max()
    reach_days = int(window_days / TRADING_DAYS_PER_YEAR * 365.25)
    n_reach = int((prices.index >= end - timedelta(days=reach_days)).sum())
    # +1 price row so the oldest kept return has its true prior; and at least
    # window_days + 1 rows for the count-based (``.tail(window_days)``) metrics.
    n_slice = max(n_reach + 1, window_days + 1)
    return daily_returns(prices.tail(n_slice))


def build_launch_cards(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of: date | None = None,
    new_launch_days: int = NEW_LAUNCH_DAYS,
) -> list[LaunchCard]:
    """New-launch cards (newest-first) with metadata for the right panel.

    ``meta`` joins `LAUNCH_CARD_META_FIELDS` with " · "; ``since_return`` is the
    simple cumulative return since the index's live date (not annualized — a
    3-week-old index annualizes to nonsense, and anchoring at the first fetched
    observation would fold in any pre-launch backtest history), or None when the
    fetched window holds too little history to compute one. Returns an empty
    list when no launches fall within ``new_launch_days``.
    """
    as_of = as_of or date.today()
    if meta.empty:
        return []
    cutoff = pd.Timestamp(as_of) - timedelta(days=new_launch_days)
    recent = meta[meta["live_date"] >= cutoff].sort_values("live_date", ascending=False)
    if recent.empty:
        return []

    cards: list[LaunchCard] = []
    for _, row in recent.iterrows():
        ticker = row["ticker"]
        live = pd.Timestamp(row["live_date"])
        days_ago = (pd.Timestamp(as_of) - live).days

        since_return: float | None = None
        if not prices.empty and ticker in prices.columns:
            # Anchor at the launch date: the fetched window predates the index
            # (mock fills the whole range; real BQL carries backtest history),
            # so iloc[0] of the raw series is not the launch level.
            col = prices[ticker].dropna()
            col = col[col.index >= live]
            if len(col) >= 2:
                since_return = float(col.iloc[-1] / col.iloc[0] - 1.0)

        meta_bits = " · ".join(
            str(row.get(k))
            for k in LAUNCH_CARD_META_FIELDS
            if pd.notna(row.get(k)) and str(row.get(k))
        )
        cards.append(
            LaunchCard(
                name=row["name"],
                ticker=ticker,
                meta=meta_bits,
                live_date=live.date(),
                days_ago=int(days_ago),
                since_return=since_return,
            )
        )
    return cards
