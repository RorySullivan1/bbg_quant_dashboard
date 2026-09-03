"""The editable benchmark selector and ticker normalization (#192).

The entry UX for #189. A plain `W.Combobox` could not be dropped in where the
`W.Dropdown` was:

- its ``options`` trait is a tuple of **plain strings**, so it cannot carry the
  ``(label, ticker)`` pairs the catalog source needs (#191); and
- its ``value`` is the raw text, so half-typed input would flow straight into
  the compute layer, which reads ``bench_dd.value`` as a ticker in a dozen
  places.

``BenchmarkSelect`` therefore wraps a Combobox behind the surface the app
already reads — ``options`` pairs in, a **resolved ticker** out — the same
trick `CheckboxMultiSelect` plays for `SelectMultiple`.

Two properties carry most of the risk and are pinned hardest here: a commit is
a deliberate act (never a keystroke), and an unknown ticker is refused rather
than silently selected with no data behind it. The refusal is temporary — #193
supplies the `on_commit` hook that fetches — so the seam is tested, not just
the current default.
"""

from __future__ import annotations

import ipywidgets as W
import pytest
from src.config import BENCHMARK_TICKERS, DEFAULT_BENCHMARK
from src.layout import build_app
from src.layout.benchmarks import BenchmarkRegistry, BenchmarkSelect, normalize_ticker

# --------------------------------------------------------------------------
# normalize_ticker
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("spx", "SPX Index"),  # the common case: no suffix typed
        ("SPX", "SPX Index"),
        ("SPX Index", "SPX Index"),  # already correct — unchanged
        ("spx index", "SPX Index"),  # suffix case normalized
        ("SPX INDEX", "SPX Index"),
        ("  spx   index  ", "SPX Index"),  # whitespace collapsed
        ("aapl equity", "AAPL Equity"),  # an explicit suffix is preserved…
        ("spx us equity", "SPX US Equity"),  # …including a multi-word root
        ("eur curncy", "EUR Curncy"),
        ("", ""),  # empty stays empty, never " Index"
        ("   ", ""),
    ],
)
def test_normalize_ticker(typed, expected):
    assert normalize_ticker(typed) == expected


def test_normalization_is_what_makes_case_variants_dedupe():
    # `spx` and `SPX Index` must land on one registry entry, not two.
    reg = BenchmarkRegistry([])
    assert reg.add(normalize_ticker("spx")) is True
    assert reg.add(normalize_ticker("SPX Index")) is False
    assert reg.tickers == ["SPX Index"]


def test_an_explicit_suffix_is_never_rewritten_to_index():
    # " Equity" names a different security; silently making it " Index" would
    # fetch the wrong thing.
    assert normalize_ticker("aapl equity").endswith(" Equity")


# --------------------------------------------------------------------------
# BenchmarkSelect
# --------------------------------------------------------------------------


def _make(**kwargs) -> BenchmarkSelect:
    sel = BenchmarkSelect(**kwargs)
    sel.options = [("A Index", "A Index"), ("X Index — Ex", "X Index")]
    return sel


def test_commits_only_on_a_deliberate_action_not_per_keystroke():
    # `continuous_update=False` is the mechanism: the inner Combobox syncs on
    # Enter or blur only, so typing never re-renders or fetches.
    sel = _make()
    assert sel._box.continuous_update is False


def test_accepts_input_that_is_not_in_the_list():
    # The whole point of the combobox over a Dropdown.
    sel = _make()
    assert sel._box.ensure_option is False


def test_shows_the_label_for_the_current_ticker():
    sel = _make(default="X Index")
    assert sel.value == "X Index"
    assert sel.label == "X Index — Ex"  # the catalog label, not the raw ticker


def test_picking_a_label_resolves_to_its_ticker():
    sel = _make()
    sel.value = "A Index"

    sel._box.value = "X Index — Ex"  # as if picked from the list

    assert sel.value == "X Index"


def test_freehand_entry_is_normalized_then_selected():
    sel = _make()
    sel.value = "A Index"

    sel._box.value = "  x   index "  # freehand, sloppy

    assert sel.value == "X Index"


def test_an_unknown_ticker_is_refused_by_default():
    # Selecting a ticker with no data behind it is worse than refusing it, so
    # until #193 can fetch, the box reverts and the selection is unchanged.
    sel = _make()
    sel.value = "A Index"

    sel._box.value = "nope"

    assert sel.value == "A Index"
    assert sel.label == "A Index"  # the text reverted too, not left dangling


def test_on_commit_can_accept_an_unknown_ticker():
    # The seam #193 fills in: fetch the ticker, then accept it.
    seen: list[str] = []

    def accept(ticker: str) -> bool:
        seen.append(ticker)
        return True

    sel = BenchmarkSelect(on_commit=accept)
    sel.options = [("A Index", "A Index")]
    sel.value = "A Index"

    sel._box.value = "nope"

    assert sel.value == "NOPE Index"
    # The hook receives the *normalized* ticker, so #193 fetches what the user
    # will actually end up selecting.
    assert seen == ["NOPE Index"]


def test_on_commit_refusing_reverts():
    sel = BenchmarkSelect(on_commit=lambda _t: False)
    sel.options = [("A Index", "A Index")]
    sel.value = "A Index"

    sel._box.value = "nope"

    assert sel.value == "A Index"


def test_on_commit_is_not_consulted_for_a_known_ticker():
    # A curated benchmark must behave exactly as it did before — no hook, no
    # fetch, no round trip.
    calls: list[str] = []
    sel = BenchmarkSelect(on_commit=lambda t: calls.append(t) or True)
    sel.options = [("A Index", "A Index"), ("B Index", "B Index")]
    sel.value = "A Index"

    sel._box.value = "B Index"

    assert sel.value == "B Index"
    assert calls == []


def test_clearing_the_box_restores_the_current_selection():
    sel = _make()
    sel.value = "A Index"

    sel._box.value = ""

    assert sel.value == "A Index"
    assert sel.label == "A Index"


def test_value_change_notifies_observers_once():
    sel = _make()
    sel.value = "A Index"
    seen: list[str] = []
    sel.observe(lambda c: seen.append(c["new"]), names="value")

    sel._box.value = "X Index — Ex"

    assert seen == ["X Index"]


def test_a_refused_commit_notifies_nobody():
    sel = _make()
    sel.value = "A Index"
    seen: list[str] = []
    sel.observe(lambda c: seen.append(c["new"]), names="value")

    sel._box.value = "nope"

    assert seen == []


def test_relabelling_options_keeps_the_selection_and_updates_the_text():
    # The catalog is re-set after the startup prune; a label can change without
    # the underlying ticker changing.
    sel = _make()
    sel.value = "X Index"
    assert sel.label == "X Index — Ex"

    sel.options = [("A Index", "A Index"), ("X Index — Renamed", "X Index")]

    assert sel.value == "X Index"
    assert sel.label == "X Index — Renamed"


def test_registry_drives_the_selector():
    reg = BenchmarkRegistry(["A Index"])
    sel = reg.register(BenchmarkSelect(default="A Index"), include_catalog=True)

    reg.add("B Index")

    assert "B Index" in [v for _, v in sel.options]
    assert sel.value == "A Index"  # unmoved


# --------------------------------------------------------------------------
# App-level
# --------------------------------------------------------------------------


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _click(app, description: str) -> None:
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == description
    ).click()


def _selectors(app) -> list[BenchmarkSelect]:
    return [w for w in _walk(app) if isinstance(w, BenchmarkSelect)]


def test_every_benchmark_selector_is_editable():
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    _click(app, "Quantitative")

    selectors = _selectors(app)
    assert len(selectors) >= 11
    for sel in selectors:
        assert sel._box.ensure_option is False
        assert sel._box.continuous_update is False
        assert sel.value == DEFAULT_BENCHMARK


def test_the_width_variants_survive_the_swap():
    # The panes use 320px, the quant filter rows 200px, and the Single-Strategy
    # shared selector 100%. A composite that lost those would wreck the layout.
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")
    _click(app, "Quantitative")
    widths = {sel.layout.width for sel in _selectors(app)}
    assert {"320px", "200px"} <= widths

    _click(app, "Single Strategy")
    assert "100%" in {sel.layout.width for sel in _selectors(app)}


def test_picking_a_curated_benchmark_still_works_end_to_end():
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    other = next(t for t in BENCHMARK_TICKERS if t != DEFAULT_BENCHMARK)
    for sel in _selectors(app):
        sel._box.value = other

    assert all(sel.value == other for sel in _selectors(app))


def test_an_unknown_ticker_typed_into_the_live_app_is_refused():
    # Until #193 wires the delta fetch, a ticker the app has no prices for must
    # not become the selection.
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    sel = _selectors(app)[0]
    before = sel.value

    sel._box.value = "definitelynotaticker"

    assert sel.value == before
