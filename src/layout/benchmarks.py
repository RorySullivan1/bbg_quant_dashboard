"""The live benchmark set, and the selectors that display it (#190).

Every benchmark selector in the app is built from one factory
(``panes._make_benchmark_dropdown``) with ``options=BENCHMARK_TICKERS`` — a
module constant read **at widget-construction time**. That makes the benchmark
list effectively frozen once ``build_app`` returns: appending to the constant
afterwards changes nothing already on screen, because each widget holds its own
snapshot of the options.

``BenchmarkRegistry`` is the one mutable owner of that list. Selectors
*register* with it instead of snapshotting a constant, so adding a benchmark
updates every one of them at once. The selectors it feeds:

- both Multi-Strategy analysis panes and both Single-Strategy analysis panes,
- the Single-Strategy shared benchmark selector,
- the Beta / Treynor / Jensen rows in each of the two filter panels,
- and — via :meth:`on_change`, not :meth:`register` — the Platform Trend-regime
  indicator-source dropdown, which is shared with the Rate-level regime and so
  only shows benchmarks while Trend is the active regime.

This module owns the registry only. Entry UX, fetching an added ticker, and
persistence are separate concerns (#192 / #193 / #194); with nothing added, a
registry-backed app renders exactly as a constant-backed one did.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from ..config import BENCHMARK_TICKERS


def benchmark_label(ticker: str) -> str:
    """Display label for a benchmark ticker — the bare code, suffix stripped.

    Matches the labels the Trend-regime selector has always used
    (``t.replace(" Index", "")``), so option text is unchanged for the curated
    tickers. A ticker carrying a different suffix (e.g. ``" Equity"``) keeps it,
    since stripping only ``" Index"`` would make two different securities read
    identically.
    """
    return ticker.replace(" Index", "")


class BenchmarkRegistry:
    """The live benchmark ticker list plus the selectors showing it.

    Order-preserving and deduped, mirroring how ``build_app`` assembles
    ``fetch_tickers`` with ``dict.fromkeys``. Registered selectors are updated
    in place on every change, and **keep their current value** whenever that
    value is still available — adding an unrelated benchmark must never move a
    selector the user has already set.
    """

    def __init__(self, tickers: Iterable[str] | None = None) -> None:
        base = BENCHMARK_TICKERS if tickers is None else tickers
        self._tickers: list[str] = list(dict.fromkeys(base))
        # (widget, labeled) pairs. `labeled` selects the option shape: plain
        # ticker strings (the benchmark dropdowns) or (label, ticker) pairs.
        self._selectors: list[tuple[Any, bool]] = []
        self._callbacks: list[Callable[[], None]] = []

    # --- reading -----------------------------------------------------------

    @property
    def tickers(self) -> list[str]:
        """A copy of the current benchmark list, in display order."""
        return list(self._tickers)

    def options(self, *, labeled: bool = False) -> list:
        """The current options in a selector's shape — see ``labeled``."""
        if labeled:
            return [(benchmark_label(t), t) for t in self._tickers]
        return list(self._tickers)

    def __contains__(self, ticker: object) -> bool:
        return ticker in self._tickers

    # --- writing -----------------------------------------------------------

    def add(self, ticker: str) -> bool:
        """Append ``ticker`` and refresh every selector.

        Returns ``True`` when it was actually new; a duplicate is a no-op that
        returns ``False`` without touching any widget, so a repeated add can't
        churn the UI.
        """
        if ticker in self._tickers:
            return False
        self._tickers.append(ticker)
        self._broadcast()
        return True

    # --- subscribing -------------------------------------------------------

    def register(self, widget: Any, *, labeled: bool = False) -> Any:
        """Bind ``widget``'s options to this registry and populate them now.

        Use for selectors that show benchmarks and nothing else. A selector
        whose options are context-dependent (the Trend/Rate-level regime source
        dropdown) must use :meth:`on_change` instead, so the registry never
        overwrites options belonging to another context.

        Returns the widget, so callers can register inline at construction.
        """
        self._selectors.append((widget, labeled))
        self._apply(widget, labeled)
        return widget

    def on_change(self, callback: Callable[[], None]) -> None:
        """Run ``callback()`` after every change, following the widget updates."""
        self._callbacks.append(callback)

    # --- internals ---------------------------------------------------------

    def _apply(self, widget: Any, labeled: bool) -> None:
        # Save and restore around the options assignment rather than trusting
        # the widget to preserve it: for a (label, value) option list the
        # traitlet compares against the *values*, and the reset-to-first
        # behaviour on a miss differs across ipywidgets versions. Restoring
        # explicitly makes "adding never moves an existing selection" true here
        # rather than dependent on the widget library.
        previous = getattr(widget, "value", None)
        widget.options = self.options(labeled=labeled)
        if previous in self._tickers:
            widget.value = previous

    def _broadcast(self) -> None:
        for widget, labeled in self._selectors:
            self._apply(widget, labeled)
        for callback in self._callbacks:
            callback()
