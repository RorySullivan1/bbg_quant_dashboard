"""The Multi-Strategy selection, as one object.

The tab's selection used to be a `CheckboxMultiSelect`'s `value` tuple, with
the cap guarded in three places — the list widget rejected a toggle, the app
popped the toast, a third observer redrew the count — and the picker itself
doubling as the store. Epic #341 makes the selection its own thing: `Basket`
holds an ordered ticker tuple and the cap, and the grid, the cards and the
analytics are all *views* of it.

`Basket` presents the surface `state.ticker_w` presented — `.value` read and
assign, `.observe(handler, names="value")` — so the callers that already read
a selection off a widget (`_render_selection`, `_default_selection`, the
Single Strategy hand-off) keep working unchanged. What it does **not** present
is `options`: a basket is a set of tickers, not a list of choices, and the
thing that decides what can be chosen is the table's frame.

**Why the table cannot be the store.** itables rebuilds the `ITable` on every
options change (`destroy()` then `new`), so a row *position* means nothing
across a filter, a Group by change or a window switch. The basket is what
survives those, and the grid re-derives its ticks from it after each rebuild.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import ipywidgets as W
import pandas as pd
import traitlets

from ..config import MAX_SELECTED_STRATEGIES
from ..stats import BasketWindow
from ..style import ASSET_CLASS_FALLBACK_COLOR, BASKET_TAG_WIDTH
from .platform_charts import asset_class_colors
from .theme import _short_ticker


@dataclass(frozen=True)
class BasketResult:
    """What a write attempted, and whether it happened.

    Returned by every mutating call so a caller can turn a rejection into the
    limit popup without re-deriving the counts. `shown` is the size the basket
    *would* have reached, which is what the message needs — "32 shown, the cap
    is 25" tells the user how much to narrow by; "rejected" does not.
    """

    accepted: bool
    shown: int
    cap: int


class Basket(traitlets.HasTraits):
    """The selected strategies: an ordered, duplicate-free ticker tuple.

    **Every write checks the cap before assigning `value`**, so a rejected
    write leaves the basket untouched and fires no observer — the grid does not
    re-tick, the cards do not redraw, and the analytics do not re-slice for a
    change that did not happen. `value` itself is validated too, so there is no
    back door: a direct assignment over the cap raises rather than quietly
    seating 26 names that the correlation work is O(n²) in.

    Order is insertion order. A removed ticker leaves the tuple; re-adding
    appends rather than restoring its old position, because the cards are drawn
    in basket order and a ticker reappearing in the middle of the strip reads
    as a different card moving.
    """

    value = traitlets.Tuple()

    def __init__(self, cap: int = MAX_SELECTED_STRATEGIES, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cap = cap

    @traitlets.validate("value")
    def _validate_value(self, proposal):
        """Dedup, and refuse an over-cap assignment.

        The methods below check the cap themselves so they can *report* a
        rejection rather than raise; this is the floor under them, for the
        assignment that does not go through one.
        """
        tickers = _dedup(proposal["value"])
        if len(tickers) > self.cap:
            raise traitlets.TraitError(
                f"basket holds at most {self.cap} strategies, got {len(tickers)}"
            )
        return tickers

    # --- reads ----------------------------------------------------------------

    def __contains__(self, ticker: str) -> bool:
        return ticker in self.value

    def __len__(self) -> int:
        return len(self.value)

    @property
    def room(self) -> int:
        """How many more will fit."""
        return self.cap - len(self.value)

    # --- writes ---------------------------------------------------------------

    def add(self, tickers: str | Iterable[str]) -> BasketResult:
        """Append the ones not already held, or reject the whole request.

        **All or nothing.** A group header worth 8 rows with 3 seats left adds
        none of them: seating the first 3 in table order would be the app
        choosing a subset of what the user asked for, silently and by a rule
        nobody stated. The rejection carries the count so the message can say
        what to narrow by.
        """
        wanted = _dedup((*self.value, *_as_tuple(tickers)))
        if len(wanted) > self.cap:
            return BasketResult(accepted=False, shown=len(wanted), cap=self.cap)
        if wanted != self.value:
            self.value = wanted
        return BasketResult(accepted=True, shown=len(wanted), cap=self.cap)

    def remove(self, tickers: str | Iterable[str]) -> BasketResult:
        """Drop the ones held; ignore the ones that are not."""
        drop = set(_as_tuple(tickers))
        kept = tuple(t for t in self.value if t not in drop)
        if kept != self.value:
            self.value = kept
        return BasketResult(accepted=True, shown=len(kept), cap=self.cap)

    def toggle(self, ticker: str) -> BasketResult:
        """Membership, flipped — what a row click means."""
        if ticker in self.value:
            return self.remove(ticker)
        return self.add(ticker)

    def replace(self, tickers: Iterable[str]) -> BasketResult:
        """Set the basket to exactly ``tickers``, in the order given."""
        wanted = _dedup(_as_tuple(tickers))
        if len(wanted) > self.cap:
            return BasketResult(accepted=False, shown=len(wanted), cap=self.cap)
        if wanted != self.value:
            self.value = wanted
        return BasketResult(accepted=True, shown=len(wanted), cap=self.cap)

    def clear(self) -> BasketResult:
        """Empty it — what *Clear all* means."""
        return self.replace(())


def _as_tuple(tickers: str | Iterable[str]) -> tuple[str, ...]:
    """One ticker or many, as a tuple.

    A bare string is iterable, so without this `add("SPX Index")` would seat
    one ticker per character.
    """
    if isinstance(tickers, str):
        return (tickers,)
    return tuple(str(t) for t in tickers)


def _dedup(tickers: Iterable[str]) -> tuple[str, ...]:
    """Order-preserving dedup, keeping the first occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for ticker in tickers:
        text = str(ticker)
        if text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)


# --- the strip ----------------------------------------------------------------


class WindowReadout(W.HTML):
    """The analysis window, as text: `2021-03-15 → 2026-09-18 · 5.5Y`.

    **Not a control.** Nothing observes it, and nothing on the tab can move the
    window except changing the basket (#341 dec. 12). It exists because the
    overlap used to be silently imposed by two date pickers whose bounds nobody
    explained; saying it out loud — and naming the member that sets the start —
    is what turns "why is this only 2 years?" into one click.
    """

    #: Shown before there is anything to measure, and when the members share no
    #: dates at all. Two different facts, so two different sentences.
    EMPTY: str = "Add strategies to set the window"
    NO_OVERLAP: str = "No overlapping history"

    def __init__(self) -> None:
        super().__init__("")
        self.add_class("bbg-window-readout")
        self.update(BasketWindow(None, None), empty=True)

    def update(self, window: BasketWindow, *, empty: bool = False) -> None:
        if window.start is None or window.end is None:
            text = self.EMPTY if empty else self.NO_OVERLAP
            self.value = f"<span class='bbg-window-empty'>{html.escape(text)}</span>"
            return
        parts = [
            f"{window.start.date()} → {window.end.date()}",
            f"{window.years:.1f}Y",
        ]
        if window.binding_start:
            parts.append(f"start set by {_short_ticker(window.binding_start)}")
        self.value = (
            "<span class='bbg-window-text'>"
            + html.escape(" · ".join(parts))
            + "</span>"
        )


class BasketCards(W.Box):
    """The basket as a wrapping row of cards, one per member (#346).

    The selection used to be readable only as ticks in a 240px scroller and a
    count that said `12/25` — so "which twelve" meant scrolling a list looking
    for marks, and a pick the filters had hidden was in the set but nowhere on
    screen. A card is the answer to both: it exists whether or not the table
    has a row for it.

    Each card is a ticker button, a muted name, an asset-class colour tag and
    an **×**. Clicking the ticker opens that strategy in Single Strategy —
    through the *same* callable the catalog grid and the leaderboard use, so
    the ways in cannot diverge (#286's rule) — and **×** removes it.

    `meta` is a **callable provider**, never an attribute: the app re-points it
    to the pruned catalog after every load, so a held frame goes stale
    silently (#242).
    """

    def __init__(
        self,
        basket: Basket,
        meta: Callable[[], pd.DataFrame],
        *,
        on_open: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(layout=W.Layout(width="100%", flex_flow="row wrap"))
        self.add_class("bbg-basket-cards")
        self.basket = basket
        self._meta = meta
        self._on_open = on_open
        #: The member binding the window's start, marked so the readout and the
        #: card point at each other.
        self._binding: str | None = None
        self.basket.observe(lambda _c: self.render(), names="value")
        self.render()

    def set_binding(self, ticker: str | None) -> None:
        """Mark (or unmark) the member that sets the analysis start."""
        if ticker != self._binding:
            self._binding = ticker
            self.render()

    def render(self) -> None:
        """Rebuild the cards, in basket order."""
        if not self.basket.value:
            placeholder = W.HTML(
                "<span class='bbg-basket-empty'>"
                "Tick rows or a group above, or Select all shown"
                "</span>"
            )
            self.children = (placeholder,)
            return
        meta = self._meta()
        names, classes = _card_lookups(meta)
        palette = asset_class_colors(sorted({c for c in classes.values() if c}))
        self.children = tuple(
            self._card(ticker, names, classes, palette) for ticker in self.basket.value
        )

    def _card(self, ticker, names, classes, palette) -> W.Box:
        """`[TICKER] x` — and nothing else (v0.9.30).

        The first cut carried a colour tag, the ticker, the strategy's **name**
        and the x. Real names are long, so the name pushed the x off the end of
        the card and it stopped rendering at all. A card is an entry in a list
        of what is selected, not a row of metadata — the table above it has the
        names, and the tooltip carries one for the card.

        The asset-class colour is a **block down the card's leading edge**
        (v0.9.31), not the 3px hairline it started as — the point of the colour
        is to tell one card from another at a glance, and a hairline reads as
        trim. It is still a border rather than a child, so it costs no width
        and cannot displace the x. The binding marker keeps a thin accent edge
        on the other three sides, which cannot be confused with it.
        """
        colour = palette.get(classes.get(ticker, ""), ASSET_CLASS_FALLBACK_COLOR)
        open_btn = W.Button(description=_short_ticker(ticker))
        open_btn.add_class("bbg-basket-ticker")
        name = str(names.get(ticker, "") or "")
        open_btn.tooltip = f"{name} - open in Single Strategy" if name else ticker
        if self._on_open is not None:
            open_btn.on_click(lambda _b, t=ticker: self._on_open(t))

        remove = W.Button(description="\u00d7")
        remove.add_class("bbg-basket-remove")
        remove.tooltip = f"Remove {ticker}"
        remove.on_click(lambda _b, t=ticker: self.basket.remove(t))

        card = W.Box(
            [open_btn, remove],
            layout=W.Layout(border_left=f"{BASKET_TAG_WIDTH} solid {colour}"),
        )
        card.add_class("bbg-basket-card")
        if ticker == self._binding:
            # Tooltips do not reach a Box, so the marker is the class alone;
            # the readout beside the strip names the member in words.
            card.add_class("bbg-basket-binding")
        return card


def _card_lookups(meta: pd.DataFrame) -> tuple[dict, dict]:
    """Ticker -> name and ticker -> asset class, from whatever `meta` holds."""
    if meta.empty or "ticker" not in meta.columns:
        return {}, {}
    names = dict(zip(meta["ticker"], meta.get("name", meta["ticker"]), strict=False))
    classes = (
        dict(zip(meta["ticker"], meta["asset_class"], strict=False))
        if "asset_class" in meta.columns
        else {}
    )
    return names, {k: str(v) if pd.notna(v) else "" for k, v in classes.items()}
