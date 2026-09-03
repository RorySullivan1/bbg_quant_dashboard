"""Catalog indices offered as a second benchmark source (#191).

Every catalog index already rides the single startup fetch, so benchmarking one
strategy against another is a *slice of data already in hand* — no BQL, no
validation, and no new failure modes. That is what makes this the first
shippable slice of #189, ahead of the arbitrary-ticker plumbing.

The three properties worth pinning, all of them easy to break later:

- **No fetch.** Selecting a catalog benchmark must stay a re-slice, per the
  "live controls slice, never fetch" contract.
- **The ARP scoping is untouched.** Benchmarks are deliberately excluded from
  universe views via ``reindex(columns=meta["ticker"])``. A catalog index used
  as a benchmark is still a *universe member* and must keep appearing in the
  all-catalog grid and the highlights — it must not be routed through the
  benchmark-exclusion path just because someone benchmarked against it.
- **Self-comparison is degenerate, not broken.** A strategy benchmarked
  against itself is allowed; it yields correlation 1.0 and beta 1.0 rather
  than an exception.
"""

from __future__ import annotations

import ipywidgets as W
import numpy as np
import pytest
import src.bql_client as bc
import src.layout.builder as builder_mod
from src.config import BENCHMARK_TICKERS, DEFAULT_BENCHMARK
from src.data import load_metadata
from src.layout import build_app
from src.layout.benchmarks import BenchmarkRegistry


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _walk(child)


def _option_values(dd: W.Dropdown) -> list:
    return [o[1] if isinstance(o, tuple) else o for o in dd.options]


def _option_labels(dd: W.Dropdown) -> list:
    return [o[0] if isinstance(o, tuple) else o for o in dd.options]


def _click(app, description: str) -> None:
    next(
        w
        for w in _walk(app)
        if isinstance(w, W.Button) and w.description == description
    ).click()


def _benchmark_selectors(app) -> list[W.Dropdown]:
    return [
        w
        for w in _walk(app)
        if isinstance(w, W.Dropdown) and DEFAULT_BENCHMARK in _option_values(w)
    ]


@pytest.fixture
def captured_state(monkeypatch):
    """The `DashboardState` that `build_app` builds for itself."""
    created = []
    real = builder_mod.DashboardState

    def factory(*args, **kwargs):
        state = real(*args, **kwargs)
        created.append(state)
        return state

    monkeypatch.setattr(builder_mod, "DashboardState", factory)
    return created


# --------------------------------------------------------------------------
# Registry-level: the catalog is a second, distinguishable source
# --------------------------------------------------------------------------


def test_catalog_entries_follow_the_benchmarks():
    reg = BenchmarkRegistry(["A Index"])
    reg.set_catalog([("X Index — Ex", "X Index")])

    opts = reg.options(include_catalog=True)
    # Curated first, so the familiar benchmarks stay at the top of the list.
    assert opts == [("A Index", "A Index"), ("X Index — Ex", "X Index")]


def test_catalog_and_benchmarks_are_visually_distinguishable():
    # Benchmarks label as the bare ticker, catalog entries carry the index
    # name — so the two sources read differently without needing a separator
    # row (which a Dropdown would render as a selectable option).
    reg = BenchmarkRegistry(["A Index"])
    reg.set_catalog([("X Index — Ex", "X Index")])

    labels = [label for label, _ in reg.options(include_catalog=True)]
    assert labels == ["A Index", "X Index — Ex"]


def test_a_ticker_that_is_both_appears_once():
    # The same value twice in a Dropdown makes its selection ambiguous.
    reg = BenchmarkRegistry(["A Index"])
    reg.set_catalog(
        [("A Index — Also curated", "A Index"), ("X Index — Ex", "X Index")]
    )

    values = [v for _, v in reg.options(include_catalog=True)]
    assert values == ["A Index", "X Index"]
    assert values.count("A Index") == 1


def test_set_catalog_is_idempotent_and_does_not_churn():
    reg = BenchmarkRegistry(["A Index"])
    entries = [("X Index — Ex", "X Index")]
    reg.set_catalog(entries)
    calls = {"n": 0}
    reg.on_change(lambda: calls.__setitem__("n", calls["n"] + 1))

    reg.set_catalog(list(entries))  # same content, fresh list

    assert calls["n"] == 0


def test_catalog_selection_survives_a_catalog_refresh():
    # `build_app` re-sets the catalog after the startup prune. A selector
    # sitting on a catalog ticker that is still live must not be moved.
    reg = BenchmarkRegistry(["A Index"])
    reg.set_catalog([("X Index — Ex", "X Index"), ("Y Index — Why", "Y Index")])
    dd = reg.register(W.Dropdown(), include_catalog=True)
    dd.value = "Y Index"

    reg.set_catalog([("X Index — Ex", "X Index"), ("Y Index — Why", "Y Index")])
    assert dd.value == "Y Index"

    # Only a ticker that actually dropped out may move the selection.
    reg.set_catalog([("X Index — Ex", "X Index")])
    assert dd.value != "Y Index"


def test_the_regime_source_does_not_offer_the_catalog():
    # A strategy's own autocorrelation is not a market trend indicator, and the
    # catalog would swamp the picker.
    reg = BenchmarkRegistry(["A Index"])
    reg.set_catalog([("X Index — Ex", "X Index")])

    values = [v for _, v in reg.options(labeled=True)]
    assert values == ["A Index"]


# --------------------------------------------------------------------------
# App-level
# --------------------------------------------------------------------------


@pytest.fixture
def captured_registry(monkeypatch):
    created: list[BenchmarkRegistry] = []
    real = builder_mod.BenchmarkRegistry

    def factory(*args, **kwargs):
        registry = real(*args, **kwargs)
        created.append(registry)
        return registry

    monkeypatch.setattr(builder_mod, "BenchmarkRegistry", factory)
    return created


def test_every_benchmark_selector_offers_the_catalog(captured_registry):
    app = build_app(verbose=False)
    (registry,) = captured_registry
    _click(app, "Multi-Strategy")

    selectors = _benchmark_selectors(app)
    assert selectors
    offered = [t for _, t in registry.catalog]
    assert offered, "the catalog source is empty — nothing to benchmark against"

    for dd in selectors:
        values = _option_values(dd)
        # Curated benchmarks are still all there, and still first…
        assert values[: len(BENCHMARK_TICKERS)] == list(BENCHMARK_TICKERS)
        # …followed by every catalog index.
        assert values[len(BENCHMARK_TICKERS) :] == offered


def test_default_benchmark_is_unchanged():
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    for dd in _benchmark_selectors(app):
        assert dd.value == DEFAULT_BENCHMARK


def test_curated_benchmarks_keep_their_bare_ticker_label():
    # The curated rows must look exactly as they did before the catalog
    # source existed — only the added rows carry a name.
    app = build_app(verbose=False)
    _click(app, "Multi-Strategy")

    dd = _benchmark_selectors(app)[0]
    labels = _option_labels(dd)
    assert labels[: len(BENCHMARK_TICKERS)] == list(BENCHMARK_TICKERS)


def test_selecting_a_catalog_benchmark_issues_no_fetch(monkeypatch, captured_registry):
    calls = {"n": 0}
    real = bc.fetch_prices

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(builder_mod, "fetch_prices", counting)

    app = build_app(verbose=False)
    (registry,) = captured_registry
    assert calls["n"] == 1  # the one startup fetch
    _click(app, "Multi-Strategy")
    after_load = calls["n"]

    target = registry.catalog[0][1]
    for dd in _benchmark_selectors(app):
        dd.value = target

    # Selecting a catalog benchmark is a re-slice of the cache, never a fetch.
    assert calls["n"] == after_load


def test_catalog_benchmark_stays_in_the_universe_views(
    captured_registry, captured_state
):
    # Benchmarks are scoped out of universe views by
    # `reindex(columns=meta["ticker"])`. A catalog index chosen as a benchmark
    # is still a universe member, so picking it must not remove it from the
    # all-catalog grid or the highlights.
    app = build_app(verbose=False)
    (registry,) = captured_registry
    (state,) = captured_state
    _click(app, "Multi-Strategy")

    target = registry.catalog[0][1]
    assert target in state.arp_universe_prices.columns

    for dd in _benchmark_selectors(app):
        dd.value = target

    assert target in state.arp_universe_prices.columns
    # The mechanism that keeps it there: it stays a *catalog* row and never
    # migrates into the benchmark list, which is what the exclusion keys off.
    assert target not in registry.tickers
    assert target in [t for _, t in registry.catalog]


def test_catalog_is_pruned_to_the_live_dashboard_universe(
    captured_registry, captured_state
):
    # `build_app` re-sets the catalog from the pruned `meta` after the startup
    # load — a stale or flat index makes a poor benchmark — and `meta` is the
    # solution-filtered dashboard universe, not the raw catalog file.
    build_app(verbose=False)
    (registry,) = captured_registry
    (state,) = captured_state

    offered = {t for _, t in registry.catalog}
    assert offered
    assert offered <= set(state.arp_universe_prices.columns)
    assert offered <= set(load_metadata()["ticker"])


# --------------------------------------------------------------------------
# Self-comparison is degenerate, not broken
# --------------------------------------------------------------------------


def test_benchmarking_a_strategy_against_itself_is_degenerate_not_an_error(
    multiyear_prices,
):
    from src.stats import ann_beta, daily_returns

    rets = daily_returns(multiyear_prices)
    col = rets.columns[0]
    series = rets[col]

    # Allowed, and self-evidently degenerate rather than an exception: perfect
    # correlation, unit beta, zero excess return.
    assert series.corr(series) == pytest.approx(1.0)
    assert ann_beta(rets[[col]], series, 1.0)[col] == pytest.approx(1.0)
    assert np.allclose((series - series).dropna(), 0.0)
