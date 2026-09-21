"""The quant columns and the live re-slice (#345, #347).

Two claims the epic rests on, both of which were false before it:

**The number the user sees is the number the threshold compares.** The quant
metrics were nine thresholds typed against a table nobody could see; they are
columns now, and `QuantColumns` is the one place either reads.

**A pick reaches the analytics without a refetch.** `universe_prices` has held
every catalog series since the initial load, and `_render_selection` only
re-slices it — but the only path to it was *Refresh prices*, the button that
hits BQL.
"""

from __future__ import annotations

import pandas as pd
import pytest
import src.layout.app as appmod
from src.layout.app import DashboardApp
from src.layout.grids import _is_percent_col, _is_stat_col, _window_of
from src.layout.quant_columns import (
    BENCHMARK_METRICS,
    QUANT_METRICS,
    QuantColumns,
    quant_column_name,
)


@pytest.fixture
def app() -> DashboardApp:
    return DashboardApp(verbose=False)


# --- the quant columns --------------------------------------------------------


def test_every_quant_column_is_named_so_the_table_already_knows_it():
    """The whole reason for `"<window> <metric>"`: hidden by the Window chip,
    comparison-filtered, rendered as a number — with no new branches (#345)."""
    for metric in QUANT_METRICS:
        name = quant_column_name("1Y", metric)
        assert _window_of(name) == "1Y", f"{name} must follow the Window chip"
        assert _is_stat_col(name), f"{name} must get a comparison filter"


def test_the_fraction_columns_carry_the_percent_scale():
    """VaR and Jensen are stored as fractions and rendered as percentages, so
    a filter that did not carry the x100 would answer '>1' with everything."""
    assert _is_percent_col(quant_column_name("1Y", "VaR"))
    assert _is_percent_col(quant_column_name("1Y", "Jensen"))
    for ratio in ("Sortino", "Calmar", "Beta", "Treynor", "RSI"):
        assert not _is_percent_col(quant_column_name("1Y", ratio))


def test_the_basket_table_carries_the_seven_metrics_for_every_window(app):
    columns = list(app.basket_grid._display.columns)
    for metric in QUANT_METRICS:
        assert any(c.endswith(f" {metric}") for c in columns), f"{metric} missing"


def test_a_benchmark_change_moves_only_the_benchmark_metrics(app):
    frame = app._basket_quant_frame(pd.Index(app.meta["ticker"]))
    others = [c for c in frame.columns if not any(m in c for m in BENCHMARK_METRICS)]
    before_others = frame[others].copy()

    options = [
        o[1] if isinstance(o, tuple) else o for o in app.basket_benchmark_dd.options
    ]
    alternative = next(o for o in options if o != app.basket_benchmark_dd.value)
    app.basket_benchmark_dd.value = alternative

    after = app._basket_quant_frame(pd.Index(app.meta["ticker"]))
    pd.testing.assert_frame_equal(before_others, after[others])


def test_the_memo_is_invalidated_when_the_price_frame_is_rebound():
    """A refetch rebinds `arp_universe_prices`, so the memo cannot serve old
    entries against new prices. Held by reference, not by `id()`: CPython
    reuses addresses, and an `id()` match against a frame nobody holds would
    answer for the wrong prices."""
    columns = QuantColumns()
    idx = pd.bdate_range("2021-01-01", periods=400)
    first = pd.DataFrame({"A": range(400)}, index=idx, dtype=float) + 100
    second = first * 2

    a = columns.table(first, years=1.0, benchmark=None, benchmark_name=None)
    assert columns._source is first
    b = columns.table(second, years=1.0, benchmark=None, benchmark_name=None)
    assert columns._source is second
    assert a is not b


def test_an_empty_price_frame_yields_the_metric_columns_and_no_rows():
    out = QuantColumns().table(
        pd.DataFrame(), years=1.0, benchmark=None, benchmark_name=None
    )
    assert list(out.columns) == list(QUANT_METRICS)
    assert out.empty


# --- the live re-slice --------------------------------------------------------


def _fetch_counter(monkeypatch) -> dict:
    calls = {"n": 0}
    original = appmod.fetch_prices

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(appmod, "fetch_prices", counted)
    return calls


def test_a_basket_change_re_renders_without_a_single_fetch(app, monkeypatch):
    calls = _fetch_counter(monkeypatch)
    app.basket.replace(list(app.basket_grid._tickers[:2]))
    assert app.state.cur_prep is not None
    assert calls["n"] == 0, "the cache already holds every price the basket needs"


def test_the_slice_runs_over_the_basket_window(app):
    app.basket.replace(list(app.basket_grid._tickers[:3]))
    window = app.state.basket_window
    assert window.start is not None
    assert app.state.cur_prep.win_start == window.start
    assert app.state.cur_prep.win_end == window.end


def test_the_readout_and_the_binding_marker_follow_the_basket(app):
    app.basket.replace(list(app.basket_grid._tickers[:3]))
    window = app.state.basket_window
    assert str(window.start.date()) in app.window_readout.value
    assert app.basket_cards._binding == window.binding_start


def test_an_emptied_basket_clears_the_slice_and_the_readout(app):
    app.basket.clear()
    assert app.state.cur_prep is None
    assert "Add strategies" in app.window_readout.value
    assert app.state.basket_window.start is None


def test_a_re_slice_is_deferred_while_a_refresh_is_running(app, monkeypatch):
    """Both write `state.cur_prep` and the panes, so they must not overlap."""
    armed: list = []
    monkeypatch.setattr(app, "_schedule_reslice", lambda: armed.append(1))
    app.refresh_inflight["running"] = True
    try:
        app._run_reslice()
    finally:
        app.refresh_inflight["running"] = False
    assert armed == [1], "the re-slice re-arms rather than running concurrently"


def test_refresh_re_slices_the_same_basket(app, monkeypatch):
    calls = _fetch_counter(monkeypatch)
    app.basket.replace(list(app.basket_grid._tickers[:2]))
    held = app.basket.value

    app.apply_btn.click()

    assert calls["n"] >= 1, "Refresh is the one control that fetches"
    assert app.basket.value == held, "Refresh never replaces the basket"


# --- what the code review caught ----------------------------------------------


def test_the_load_builds_the_selection_slice_exactly_once(monkeypatch):
    """Seeding the basket from `_default_selection` is a basket write like any
    other, so without suspending the debounce the load would build the slice
    twice — once for the write, once for the `_recompute` that follows — and
    the second would throw the first away."""
    from src.layout import selection

    calls = {"n": 0}
    original = selection.SelectionSlice.build

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(selection.SelectionSlice, "build", staticmethod(counted))
    DashboardApp(verbose=False)
    assert calls["n"] == 1


def test_a_refresh_builds_the_selection_slice_exactly_once(app, monkeypatch):
    from src.layout import selection

    calls = {"n": 0}
    original = selection.SelectionSlice.build

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(selection.SelectionSlice, "build", staticmethod(counted))
    app.apply_btn.click()
    assert calls["n"] == 1


def test_a_pruned_ticker_is_dropped_from_the_basket_by_a_refresh(app, monkeypatch):
    """A ticker the prune removes has no prices left. Leaving it in would hand
    `basket_window` an all-NaN column and collapse the overlap to nothing —
    the whole analysis breaking because one index went stale."""
    import src.layout.app as module

    held = list(app.basket_grid._tickers[:3])
    app.basket.replace(held)
    doomed = held[0]

    # The prune keeps only the columns that moved recently; flatten one so the
    # refetch's `active_columns` drops it.
    original = module.fetch_prices

    def with_a_stale_column(*args, **kwargs):
        prices, missing = original(*args, **kwargs)
        if doomed in prices.columns:
            prices[doomed] = 100.0  # flat -> stale
        return prices, missing

    monkeypatch.setattr(module, "fetch_prices", with_a_stale_column)
    app.apply_btn.click()

    assert doomed not in app.basket.value, "a pruned ticker must leave the basket"
    assert doomed not in [
        b.children[1].description for b in app.basket_cards.children if b.children
    ]
    assert set(app.basket.value) <= set(app.meta["ticker"])
