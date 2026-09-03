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
        # Catalog indices offered as a *second* source (#191): (label, ticker)
        # pairs, already fetched at startup, so selecting one costs no BQL.
        self._catalog: list[tuple[str, str]] = []
        # (widget, labeled, include_catalog) triples. The two flags select the
        # option shape and whether the catalog source is offered.
        self._selectors: list[tuple[Any, bool, bool]] = []
        self._callbacks: list[Callable[[], None]] = []

    # --- reading -----------------------------------------------------------

    @property
    def tickers(self) -> list[str]:
        """A copy of the current benchmark list, in display order."""
        return list(self._tickers)

    @property
    def catalog(self) -> list[tuple[str, str]]:
        """A copy of the catalog options, as ``(label, ticker)`` pairs."""
        return list(self._catalog)

    def options(self, *, labeled: bool = False, include_catalog: bool = False) -> list:
        """The current options in a selector's shape.

        ``labeled`` returns ``(label, ticker)`` pairs with the suffix stripped —
        the compact form the Trend-regime source picker uses.

        ``include_catalog`` appends the catalog indices after the benchmarks.
        It implies a labeled shape, because a catalog entry carries its index
        *name*; the benchmarks keep their full ticker as their label there, so
        the two sources stay visually distinct (bare ticker vs. ticker + name)
        and the curated ones stay first. `set_catalog` guarantees no ticker
        appears in both, which would make a dropdown value ambiguous.
        """
        if include_catalog:
            return [(t, t) for t in self._tickers] + list(self._catalog)
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

    def set_catalog(self, entries: Iterable[tuple[str, str]]) -> None:
        """Replace the catalog-index source and refresh the selectors using it.

        Called once the metadata is known and **again after the startup prune**,
        since `build_app` re-points `meta` to the live catalog — a stale or
        flat index makes a poor benchmark, so the offered set should follow the
        pruned list rather than the full one.

        Entries already present as benchmarks are dropped: the same ticker in a
        dropdown twice makes its value ambiguous.
        """
        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for label, ticker in entries:
            if ticker in self._tickers or ticker in seen:
                continue
            seen.add(ticker)
            deduped.append((label, ticker))
        if deduped == self._catalog:
            return
        self._catalog = deduped
        self._broadcast()

    # --- subscribing -------------------------------------------------------

    def register(
        self, widget: Any, *, labeled: bool = False, include_catalog: bool = False
    ) -> Any:
        """Bind ``widget``'s options to this registry and populate them now.

        Use for selectors that show benchmarks and nothing else. A selector
        whose options are context-dependent (the Trend/Rate-level regime source
        dropdown) must use :meth:`on_change` instead, so the registry never
        overwrites options belonging to another context.

        ``include_catalog`` also offers the catalog indices — right for the
        analysis-pane and quant-filter benchmark selectors, wrong for the
        Trend-regime source picker, where a strategy's own autocorrelation is
        not a market trend indicator.

        Returns the widget, so callers can register inline at construction.
        """
        self._selectors.append((widget, labeled, include_catalog))
        self._apply(widget, labeled, include_catalog)
        return widget

    def on_change(self, callback: Callable[[], None]) -> None:
        """Run ``callback()`` after every change, following the widget updates."""
        self._callbacks.append(callback)

    # --- internals ---------------------------------------------------------

    def _apply(self, widget: Any, labeled: bool, include_catalog: bool) -> None:
        # Save and restore around the options assignment rather than trusting
        # the widget to preserve it: for a (label, value) option list the
        # traitlet compares against the *values*, and the reset-to-first
        # behaviour on a miss differs across ipywidgets versions. Restoring
        # explicitly makes "a change never moves an existing selection" true
        # here rather than dependent on the widget library.
        previous = getattr(widget, "value", None)
        options = self.options(labeled=labeled, include_catalog=include_catalog)
        widget.options = options
        # Check against this widget's own option values, not just the benchmark
        # list: a selector showing the catalog can legitimately be sitting on a
        # catalog ticker.
        if previous in [o[1] if isinstance(o, tuple) else o for o in options]:
            widget.value = previous

    def _broadcast(self) -> None:
        for widget, labeled, include_catalog in self._selectors:
            self._apply(widget, labeled, include_catalog)
        for callback in self._callbacks:
            callback()
