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

import ipywidgets as W
import traitlets

from ..config import BENCHMARK_TICKERS

# Bloomberg security-type suffixes, lower-cased for matching. A ticker the user
# types without one is assumed to be an index — every curated benchmark is —
# but an explicit suffix is preserved, because " Equity"/" Curncy"/… name a
# genuinely different security and silently rewriting one to " Index" would
# fetch the wrong thing.
_SUFFIXES: tuple[str, ...] = (
    "index",
    "equity",
    "curncy",
    "comdty",
    "govt",
    "corp",
    "mtge",
    "pfd",
    "muni",
)
_DEFAULT_SUFFIX = "Index"


def normalize_ticker(text: str) -> str:
    """Normalize typed text into a Bloomberg ticker, or ``""`` if it is empty.

    Users type ``spx``, not ``SPX Index``, but every BQL call needs the
    security-type suffix. So: collapse whitespace, upper-case the root, and
    append ``" Index"`` when no recognized suffix is present. An explicit
    suffix is kept and title-cased to Bloomberg's own form.

    Case- and space-insensitive by construction, which is what makes ``spx``
    and ``SPX Index`` dedupe to one registry entry rather than two.
    """
    parts = str(text).split()
    if not parts:
        return ""
    if len(parts) > 1 and parts[-1].lower() in _SUFFIXES:
        root, suffix = parts[:-1], parts[-1].lower()
    else:
        root, suffix = parts, _DEFAULT_SUFFIX.lower()
    return f"{' '.join(root).upper()} {suffix.capitalize()}"


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
        # Decides whether a ticker nobody has heard of is usable (#193). None
        # until `build_app` installs one — without it an unknown ticker is
        # refused, which is the right default for any caller that cannot fetch.
        self._resolver: Callable[[str], bool] | None = None

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

    def set_resolver(self, resolver: Callable[[str], bool] | None) -> None:
        """Install the callable that decides whether an unknown ticker is usable.

        ``resolver(ticker)`` returns ``True`` once the ticker's prices are in
        the cache and it is safe to select. It owns reporting its own failures
        — the registry deliberately knows nothing about the error surface.
        """
        self._resolver = resolver

    def request(self, ticker: str) -> bool:
        """Decide whether a selector may commit ``ticker``.

        A ticker already offered — curated, previously added, or a catalog
        index — is accepted with no round trip. Anything else goes to the
        resolver, and is added to the benchmark list (reaching every selector)
        only once the resolver confirms it has data. With no resolver
        installed, unknown tickers are refused.
        """
        if ticker in self._tickers:
            return True
        if any(value == ticker for _, value in self._catalog):
            return True
        if self._resolver is None:
            return False
        if not self._resolver(ticker):
            return False
        self.add(ticker)
        return True

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
        # A selector that can accept typed input routes its unknown-ticker
        # decision back through the registry (#193). Duck-typed so the registry
        # stays usable with a plain Dropdown.
        set_handler = getattr(widget, "set_commit_handler", None)
        if set_handler is not None:
            set_handler(self.request)
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


class BenchmarkSelect(W.HBox):
    """A benchmark selector that also accepts a ticker the user types (#192).

    Wraps a ``W.Combobox`` but exposes the surface the app already reads — an
    ``options`` trait of ``(label, value)`` pairs and a ``value`` trait holding
    a **resolved ticker** — so every existing `bench_dd.value` read and
    ``observe(..., names="value")`` keeps working unchanged. Same reason
    ``CheckboxMultiSelect`` wraps checkboxes behind a ``SelectMultiple``
    surface.

    A raw ``Combobox`` could not be dropped in directly:

    - its ``options`` trait is a tuple of **plain strings**, so it cannot carry
      the ``(label, ticker)`` pairs the catalog source needs (#191); and
    - its ``value`` is the raw text, which would put half-typed input straight
      into the compute layer.

    So the text box holds *display labels* and this widget resolves a committed
    label back to its ticker, falling back to :func:`normalize_ticker` for
    anything typed freehand.

    **Commit, not keystroke.** ``continuous_update=False`` means the inner
    Combobox syncs only on Enter or blur, so typing never re-renders or fetches
    — only a deliberate commit does.

    ``on_commit`` decides whether a ticker that is not currently an option is
    acceptable. It receives the normalized ticker and returns ``True`` to
    accept. The default rejects, reverting the box: without it an unknown
    ticker would select something with no data behind it. #193 replaces it with
    the delta-fetch, which is the piece that makes arbitrary tickers real.
    """

    options = traitlets.Any(())  # list[(label, value)] | list[value]
    value = traitlets.Unicode("")  # the resolved ticker, never raw text

    def __init__(
        self,
        description: str = "Benchmark",
        *,
        default: str = "",
        width: str = "320px",
        on_commit: Callable[[str], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._on_commit = on_commit
        self._by_label: dict[str, str] = {}
        self._guard = False

        self._box = W.Combobox(
            placeholder="Ticker",
            ensure_option=False,  # the whole point: accept what isn't listed
            continuous_update=False,  # commit on Enter/blur, never per keystroke
            description=description,
            style={"description_width": "80px" if description else "0px"},
            layout=W.Layout(width=width),
        )
        self._box.add_class("bbg-benchmark-select")
        self.children = (self._box,)
        self.layout.width = width

        self.observe(self._render_options, names="options")
        self.observe(self._render_value, names="value")
        self._box.observe(self._on_text_commit, names="value")
        if default:
            self.value = default

    # --- the public surface ------------------------------------------------

    def set_commit_handler(self, on_commit: Callable[[str], bool] | None) -> None:
        """Install the hook consulted when a ticker is not currently an option.

        `BenchmarkRegistry.register` calls this, so a registered selector
        defers the decision to the registry (and thus to its resolver) rather
        than each selector carrying its own policy.
        """
        self._on_commit = on_commit

    @property
    def label(self) -> str:
        """The text currently shown — the display label, not the ticker."""
        return self._box.value

    # --- internals ---------------------------------------------------------

    def _pairs(self) -> list[tuple[str, str]]:
        out = []
        for opt in self.options or ():
            if isinstance(opt, tuple):
                out.append((str(opt[0]), opt[1]))
            else:
                out.append((str(opt), opt))
        return out

    def _render_options(self, *_) -> None:
        pairs = self._pairs()
        self._by_label = {label: value for label, value in pairs}
        self._guard = True
        try:
            self._box.options = [label for label, _ in pairs]
            # Re-show the current ticker under its (possibly new) label.
            self._show(self.value)
        finally:
            self._guard = False

    def _render_value(self, *_) -> None:
        if self._guard:
            return
        self._guard = True
        try:
            self._show(self.value)
        finally:
            self._guard = False

    def _show(self, ticker: str) -> None:
        for label, value in self._pairs():
            if value == ticker:
                self._box.value = label
                return
        self._box.value = ticker

    def _on_text_commit(self, _change) -> None:
        if self._guard:
            return
        text = self._box.value
        # A label picked from the list resolves directly; anything else is
        # freehand and gets normalized (`spx` → `SPX Index`).
        ticker = self._by_label.get(text) or normalize_ticker(text)

        if not ticker:  # cleared — put the current selection back
            self._guard = True
            try:
                self._show(self.value)
            finally:
                self._guard = False
            return

        known = ticker in {value for _, value in self._pairs()}
        if not known:
            accepted = self._on_commit(ticker) if self._on_commit else False
            if not accepted:
                # Revert: selecting a ticker with no data behind it is worse
                # than refusing it. #193 makes these acceptable by fetching.
                self._guard = True
                try:
                    self._show(self.value)
                finally:
                    self._guard = False
                return

        self._guard = True
        try:
            self.value = ticker
            self._show(ticker)
        finally:
            self._guard = False
