"""The benchmark registry and its broadcast to every selector (#190).

Before this, each benchmark selector was constructed with
``options=BENCHMARK_TICKERS`` — a snapshot taken at build time — so there was
no way to add a benchmark once ``build_app`` had returned. These tests pin the
two guarantees that make the rest of the epic possible: a registry change
reaches **every** selector (including the Trend-regime source dropdown, which
is shared with Rate-level and so can't simply register), and it never disturbs
a selection the user has already made.

The app-level tests drive the UI to reach each selector (only the Platform tab
is mounted at build; the filter rows sit behind a "Quantitative" pill), collect
what they find, then assert every collected selector picked the addition up —
so a new pane or filter row is covered automatically rather than needing the
test updated.
"""

from __future__ import annotations

import ipywidgets as W
import pytest
import src.layout.builder as builder_mod
from src.config import BENCHMARK_TICKERS, DEFAULT_BENCHMARK
from src.layout import build_app
from src.layout.benchmarks import BenchmarkRegistry, benchmark_label

NEW = "TESTBM Index"


# --------------------------------------------------------------------------
# Registry unit behaviour
# --------------------------------------------------------------------------


def test_registry_defaults_to_the_curated_list():
    assert BenchmarkRegistry().tickers == list(BENCHMARK_TICKERS)


def test_registry_dedupes_and_preserves_order():
    reg = BenchmarkRegistry(["B Index", "A Index", "B Index"])
    assert reg.tickers == ["B Index", "A Index"]


def test_add_appends_and_reports_novelty():
    reg = BenchmarkRegistry(["A Index"])
    assert reg.add("B Index") is True
    assert reg.tickers == ["A Index", "B Index"]
    # A duplicate add is a no-op, so a repeated add can't churn the UI.
    assert reg.add("B Index") is False
    assert reg.tickers == ["A Index", "B Index"]


def test_duplicate_add_touches_no_widget():
    reg = BenchmarkRegistry(["A Index"])
    dd = reg.register(W.Dropdown())
    calls = {"n": 0}
    reg.on_change(lambda: calls.__setitem__("n", calls["n"] + 1))

    assert reg.add("A Index") is False
    assert calls["n"] == 0
    assert list(dd.options) == ["A Index"]


def test_register_populates_immediately_and_on_add():
    reg = BenchmarkRegistry(["A Index"])
    dd = reg.register(W.Dropdown())
    assert list(dd.options) == ["A Index"]

    reg.add("B Index")
    assert list(dd.options) == ["A Index", "B Index"]


def test_labeled_registration_uses_label_value_pairs():
    reg = BenchmarkRegistry(["A Index", "B Equity"])
    dd = reg.register(W.Dropdown(options=["A Index"], value="A Index"), labeled=True)
    assert list(dd.options) == [("A", "A Index"), ("B Equity", "B Equity")]
    # The value stays the ticker, not the label.
    assert dd.value == "A Index"


def test_register_does_not_invent_a_selection():
    # A widget with no valid value keeps whatever the widget library chose;
    # the registry only ever *preserves* a selection, it never makes one up.
    reg = BenchmarkRegistry(["A Index"])
    dd = reg.register(W.Dropdown())
    assert list(dd.options) == ["A Index"]


def test_benchmark_label_strips_only_the_index_suffix():
    # Stripping " Equity" too would make two different securities read alike.
    assert benchmark_label("SPTR Index") == "SPTR"
    assert benchmark_label("AAPL Equity") == "AAPL Equity"


def test_add_never_moves_an_existing_selection():
    reg = BenchmarkRegistry(["A Index", "B Index"])
    plain = reg.register(W.Dropdown())
    labeled = reg.register(W.Dropdown(), labeled=True)
    plain.value = "B Index"
    labeled.value = "B Index"

    reg.add("C Index")

    assert plain.value == "B Index"
    assert labeled.value == "B Index"


def test_on_change_callbacks_run_after_the_widget_updates():
    reg = BenchmarkRegistry(["A Index"])
    dd = reg.register(W.Dropdown())
    seen = []
    reg.on_change(lambda: seen.append(list(dd.options)))

    reg.add("B Index")

    # The callback must observe the *updated* options — the regime re-sync
    # relies on reading current state, not state mid-update.
    assert seen == [["A Index", "B Index"]]


def test_contains_and_options_shapes():
    reg = BenchmarkRegistry(["A Index"])
    assert "A Index" in reg
    assert "Z Index" not in reg
    assert reg.options() == ["A Index"]
    assert reg.options(labeled=True) == [("A", "A Index")]


# --------------------------------------------------------------------------
# App-level wiring
# --------------------------------------------------------------------------
#
# `build_app` mounts only the Platform tab; the other tabs' widgets exist but
# are swapped into the tree on demand, and each filter panel's benchmark rows
# sit behind its "Quantitative" pill. So the helpers below drive the UI to the
# state a user would have to reach to see a given selector, and accumulate what
# they find — the selectors are the same objects across mounts.


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _option_values(dd: W.Dropdown) -> list:
    """A dropdown's option *values*, for both the plain and (label, value) shapes."""
    return [o[1] if isinstance(o, tuple) else o for o in dd.options]


def _click(app, description: str) -> None:
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == description
    ).click()


def _all_benchmark_selectors(app) -> list[W.Dropdown]:
    """Every benchmark selector in the app, gathered by mounting each tab."""
    found: dict[int, W.Dropdown] = {}
    for tab in ("Multi-Strategy", "Single Strategy"):
        _click(app, tab)
        _click(app, "Quantitative")  # reveals the Beta/Treynor/Jensen rows
        for w in _walk(app):
            if isinstance(w, W.Dropdown) and DEFAULT_BENCHMARK in _option_values(w):
                found[id(w)] = w
    return list(found.values())


@pytest.fixture
def captured_registry(monkeypatch):
    """The `BenchmarkRegistry` that `build_app` creates for itself."""
    created: list[BenchmarkRegistry] = []
    real = builder_mod.BenchmarkRegistry

    def factory(*args, **kwargs):
        registry = real(*args, **kwargs)
        created.append(registry)
        return registry

    monkeypatch.setattr(builder_mod, "BenchmarkRegistry", factory)
    return created


def test_added_benchmark_reaches_every_selector(captured_registry):
    app = build_app()
    (registry,) = captured_registry

    selectors = _all_benchmark_selectors(app)
    # 4 per Multi-Strategy pane (x2), 1 per Single-Strategy pane (x2), the
    # Single-Strategy shared selector, and Beta/Treynor/Jensen in both filter
    # panels. Pinned as a floor so silent de-registration is caught without the
    # test going stale when a pane is added.
    assert len(selectors) >= 17

    registry.add(NEW)

    missing = [dd for dd in selectors if NEW not in _option_values(dd)]
    assert not missing, f"{len(missing)} of {len(selectors)} selectors missed the add"


def test_adding_a_benchmark_preserves_every_current_selection(captured_registry):
    app = build_app()
    (registry,) = captured_registry

    selectors = _all_benchmark_selectors(app)
    # Move each selector off the default, so a reset-to-first would be obvious.
    other = next(t for t in BENCHMARK_TICKERS if t != DEFAULT_BENCHMARK)
    for dd in selectors:
        dd.value = other

    registry.add(NEW)

    assert all(dd.value == other for dd in selectors)


def _regime_dropdowns(app) -> tuple[W.Dropdown, W.Dropdown]:
    """The regime type + indicator-source dropdowns, with the pill activated."""
    _click(app, "Platform")
    _click(app, "Regime analysis")
    type_dd = next(
        w
        for w in _walk(app)
        if isinstance(w, W.Dropdown) and "Trend" in _option_values(w)
    )
    source_dd = next(
        w for w in _walk(app) if isinstance(w, W.Dropdown) and w.description == "Source"
    )
    return type_dd, source_dd


def test_trend_regime_source_tracks_the_registry(captured_registry):
    # The Trend regime's indicator-source list used to be frozen into
    # REGIME_SPECS at import. Its widget is shared with Rate-level (whose
    # options are regions), so it is driven by an on_change re-sync rather than
    # by registering with the registry.
    app = build_app()
    (registry,) = captured_registry
    type_dd, source_dd = _regime_dropdowns(app)

    type_dd.value = "Trend"
    assert DEFAULT_BENCHMARK in _option_values(source_dd)

    chosen = next(t for t in BENCHMARK_TICKERS if t != DEFAULT_BENCHMARK)
    source_dd.value = chosen

    registry.add(NEW)

    assert NEW in _option_values(source_dd)
    assert source_dd.value == chosen  # the re-sync must not reset the source


def test_rate_level_regime_source_is_unaffected_by_benchmarks(captured_registry):
    # The shared widget must never be overwritten with benchmarks while a
    # regime that supplies its own selector is active.
    app = build_app()
    (registry,) = captured_registry
    type_dd, source_dd = _regime_dropdowns(app)

    type_dd.value = "Rate-level"
    regions = _option_values(source_dd)
    assert DEFAULT_BENCHMARK not in regions

    registry.add(NEW)

    assert _option_values(source_dd) == regions


def test_switching_regime_type_still_resets_the_source(captured_registry):
    # Value preservation is scoped to a registry change. Switching regime type
    # moves to a different domain, so falling back to the first option stays
    # the right behaviour.
    app = build_app()
    _ = captured_registry
    type_dd, source_dd = _regime_dropdowns(app)

    type_dd.value = "Trend"
    source_dd.value = next(t for t in BENCHMARK_TICKERS if t != DEFAULT_BENCHMARK)

    type_dd.value = "Rate-level"

    assert source_dd.value == _option_values(source_dd)[0]
