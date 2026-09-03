"""Tests for the Single Strategy "Filters" accordion (v0.9.12).

Covers the reusable ``make_filter_panel`` reducer (``matching`` over the
categorical / Characteristics / Quantitative state), the Clear buttons, that the
Single Strategy tab embeds the panel and exposes ``.filters``, and the live
end-to-end narrowing of the single-select picker through ``build_app`` (toggling
a filter box re-narrows the picker without a Refresh-prices button).
"""

from __future__ import annotations

from types import SimpleNamespace

import ipywidgets as W
import pandas as pd
from src.layout import build_app
from src.layout.filter_panel import make_filter_panel
from src.layout.single_strategy import make_single_strategy_panel


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index", "CCC Index"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "asset_class": ["Equity", "Fixed Income", "Commodity"],
            "category": ["X", "Y", "Z"],
            "theme": ["T1", "T2", "T3"],
            "return_type": ["Total", "Total", "Excess"],
            "currency": ["USD", "EUR", "USD"],
            "live_date": pd.to_datetime(["2010-03-15", pd.NaT, "2015-07-01"]),
            "description": ["Alpha desc", pd.NA, "Charlie desc"],
        }
    )


def _empty_state() -> SimpleNamespace:
    """A state with no cached prices — the quant filter is a no-op against it."""
    return SimpleNamespace(
        arp_universe_prices=pd.DataFrame(), universe_prices=pd.DataFrame()
    )


def _check(checks: list[W.Checkbox], value: str) -> None:
    next(c for c in checks if c.description == value).value = True


def _walk(w):
    yield w
    for child in getattr(w, "children", ()):
        yield from _walk(child)


# --- structure ---------------------------------------------------------------


def test_make_filter_panel_structure():
    panel = make_filter_panel(_meta())
    assert isinstance(panel.root, W.Accordion)
    assert panel.root.titles == ("Filters",)
    assert callable(panel.matching)
    # Every categorical checkbox is an observable input.
    for cb in (*panel.asset_checks, *panel.cat_checks, *panel.theme_checks):
        assert cb in panel.inputs
    # The quant operator + value boxes and dropdowns are inputs too.
    assert panel.currency_dd in panel.inputs
    assert panel.quant.period_dd in panel.inputs


def test_single_strategy_panel_embeds_filters():
    ss = make_single_strategy_panel(_meta())
    assert hasattr(ss, "filters")
    # The "Filters" accordion is the first child of the tab and is a two-column
    # panel: the strategy picker + benchmark controls on the left, the filter
    # criteria (the panel's right_panel) on the right.
    accordion = ss.root.children[0]
    assert isinstance(accordion, W.Accordion)
    assert accordion.titles == ("Filters",)
    filter_box = accordion.children[0]
    left, right = filter_box.children
    assert ss.picker in left.children  # picker lives in the left column
    assert ss.bench_dd in left.children
    assert ss.bench_chk in left.children
    assert right is ss.filters.right_panel  # criteria on the right


# --- matching reducer --------------------------------------------------------


def test_matching_empty_returns_all():
    meta = _meta()
    panel = make_filter_panel(meta)
    got = panel.matching(meta, _empty_state())
    assert list(got) == list(meta["ticker"])


def test_matching_categorical_asset_class():
    meta = _meta()
    panel = make_filter_panel(meta)
    _check(panel.asset_checks, "Equity")
    assert list(panel.matching(meta, _empty_state())) == ["AAA Index"]


def test_matching_currency():
    meta = _meta()
    panel = make_filter_panel(meta)
    panel.currency_dd.value = "EUR"
    assert list(panel.matching(meta, _empty_state())) == ["BBB Index"]


def test_matching_launch_date_min():
    meta = _meta()
    panel = make_filter_panel(meta)
    panel.live_min.value = pd.Timestamp("2012-01-01").date()
    # AAA (2010) excluded, BBB (NaT) excluded, CCC (2015) kept.
    assert list(panel.matching(meta, _empty_state())) == ["CCC Index"]


def test_matching_combines_dimensions_as_and():
    meta = _meta()
    panel = make_filter_panel(meta)
    _check(panel.asset_checks, "Equity")  # AAA
    panel.currency_dd.value = "EUR"  # BBB
    # No index is both Equity and EUR → empty.
    assert list(panel.matching(meta, _empty_state())) == []


# --- clear buttons -----------------------------------------------------------


def test_clear_all_resets_every_dimension():
    meta = _meta()
    panel = make_filter_panel(meta)
    _check(panel.asset_checks, "Equity")
    panel.currency_dd.value = "EUR"
    panel.live_min.value = pd.Timestamp("2012-01-01").date()
    panel.quant.specs["Sharpe"][1].value = "0.5"
    panel.clear_all_btn.click()
    assert all(not c.value for c in panel.asset_checks)
    assert panel.currency_dd.value == "All"
    assert panel.live_min.value is None
    assert panel.quant.specs["Sharpe"][1].value == ""
    assert list(panel.matching(meta, _empty_state())) == list(meta["ticker"])


def test_clear_section_only_clears_active_dimension():
    meta = _meta()
    panel = make_filter_panel(meta)
    _check(panel.asset_checks, "Equity")
    panel.currency_dd.value = "EUR"
    panel.activate_filter("Asset Class")
    panel.clear_section_btn.click()
    # Asset Class cleared, but the Characteristics currency is untouched.
    assert all(not c.value for c in panel.asset_checks)
    assert panel.currency_dd.value == "EUR"


# --- quantitative threshold filter (plumbing via extreme thresholds) ---------


def _quant_state(multiyear_prices, benchmark) -> SimpleNamespace:
    universe = pd.concat([multiyear_prices, benchmark.to_frame()], axis=1)
    return SimpleNamespace(
        arp_universe_prices=multiyear_prices, universe_prices=universe
    )


def test_matching_quant_threshold_passes_all_when_loose(multiyear_prices, benchmark):
    meta = _meta()  # tickers align with multiyear_prices columns
    panel = make_filter_panel(meta)
    op, box = panel.quant.specs["Sharpe"]
    op.value = "≥"
    box.value = "-1000000"  # every ticker clears it
    got = panel.matching(meta, _quant_state(multiyear_prices, benchmark))
    assert set(got) == set(multiyear_prices.columns)


def test_matching_quant_threshold_excludes_all_when_impossible(
    multiyear_prices, benchmark
):
    meta = _meta()
    panel = make_filter_panel(meta)
    op, box = panel.quant.specs["Sharpe"]
    op.value = "≥"
    box.value = "1000000"  # no ticker clears it
    got = panel.matching(meta, _quant_state(multiyear_prices, benchmark))
    assert list(got) == []


def test_matching_quant_le_operator(multiyear_prices, benchmark):
    meta = _meta()
    panel = make_filter_panel(meta)
    op, box = panel.quant.specs["Sharpe"]
    op.value = "≤"
    box.value = "1000000"  # every ticker is ≤ a huge number
    got = panel.matching(meta, _quant_state(multiyear_prices, benchmark))
    assert set(got) == set(multiyear_prices.columns)


def test_quant_table_is_memoized_across_repeats_and_toggles(
    multiyear_prices, benchmark, monkeypatch
):
    # v0.9.13 #167: the whole-catalog quant table is memoized, so a repeated
    # match, or a categorical toggle (changing candidates but not the metric
    # params), re-masks the cached table instead of recomputing it — while a
    # cache refresh (new arp frame) invalidates it.
    import src.layout.filter_panel as fp

    calls = {"n": 0}
    real = fp.quant_metrics_table

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(fp, "quant_metrics_table", counting)

    meta = _meta()
    panel = make_filter_panel(meta)
    state = _quant_state(multiyear_prices, benchmark)
    op, box = panel.quant.specs["Sharpe"]
    op.value = "≥"
    box.value = "-1000000"  # loose threshold, every ticker clears it

    r1 = panel.matching(meta, state)
    after_first = calls["n"]
    assert after_first >= 1  # the first match computed the table

    r2 = panel.matching(meta, state)  # identical params → memo hit
    assert calls["n"] == after_first
    assert list(r1) == list(r2)

    _check(panel.asset_checks, "Equity")  # narrows candidates, same metric params
    panel.matching(meta, state)
    assert calls["n"] == after_first  # candidate-independent table → still cached

    state.arp_universe_prices = multiyear_prices.copy()  # a Refresh replaces the frame
    panel.matching(meta, state)
    assert calls["n"] > after_first  # new frame identity → recomputed


# --- live end-to-end narrowing through build_app -----------------------------


def _single_panel(app):
    """Activate the Single Strategy tab and return its mounted panel."""
    tab_bar = app.children[4]
    single_btn = next(
        b
        for b in _walk(tab_bar)
        if isinstance(b, W.Button) and b.description == "Single Strategy"
    )
    single_btn.click()
    return app.children[5].children[0]


def test_single_strategy_filter_live_narrows_picker():
    app = build_app(verbose=False)
    panel = _single_panel(app)
    picker = next(
        w
        for w in _walk(panel)
        if isinstance(w, W.Dropdown) and w.description == "Strategy"
    )
    accordion = next(w for w in _walk(panel) if isinstance(w, W.Accordion))
    # The accordion's left column also holds the "Show benchmark" toggle; a
    # filter checkbox is any other checkbox (a categorical filter value).
    checks = [
        w
        for w in _walk(accordion)
        if isinstance(w, W.Checkbox) and w.description != "Show benchmark"
    ]
    assert checks, "the Filters accordion should carry categorical checkboxes"

    n_all = len(picker.options)
    values_all = {o[1] if isinstance(o, tuple) else o for o in picker.options}
    option_vals = lambda: {  # noqa: E731
        o[1] if isinstance(o, tuple) else o for o in picker.options
    }

    checks[0].value = True  # toggle one categorical box → live re-narrow
    assert len(picker.options) <= n_all
    assert option_vals() <= values_all
    # Selection invariant: a still-matching strategy stays selected (or nothing
    # matched → None), never a stale ticker outside the narrowed options.
    assert picker.value is None or picker.value in option_vals()

    checks[0].value = False  # unchecking restores the full catalog
    assert len(picker.options) == n_all
