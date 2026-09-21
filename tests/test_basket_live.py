"""The quant columns and the live re-slice (#345, #347).

Two claims the epic rests on, both of which were false before it:

**The number the user sees is the number the threshold compares.** The quant
metrics were nine thresholds typed against a table nobody could see; they are
columns now, and `QuantColumns` is the one place either reads.

**A pick reaches the analytics without a refetch.** `universe_prices` has held
every catalog series since the initial load, and `_render_selection` only
re-slices it — but the only path to it was *Refresh prices*, the button that
hits BQL. **That button is gone** (v0.9.30), so the tests that drove it went
with it; what is left is that a basket write renders, and renders once.
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


def test_no_quant_column_is_a_percent_column():
    """The two stored as fractions — VaR (a daily loss fraction) and Jensen
    alpha (annualized) — are exactly the two dropped in v0.9.30. What is left
    is four ratios, stored as they read, so nothing here needs the x100 the
    percent columns carry."""
    for metric in QUANT_METRICS:
        assert not _is_percent_col(quant_column_name("1Y", metric))


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


def test_a_re_slice_invalidates_the_benchmark_memo(app):
    """The memo is keyed to the **slice**, so a new selection invalidates all
    of it.

    `_recompute` had always cleared it; the debounced re-slice called
    `_render_selection` directly and skipped that, so a pane revisited after a
    selection change was served the chart memoised for the *previous* one —
    the right benchmark, the wrong strategies, and nothing on screen to say so.
    """
    app.basket.replace(list(app.basket_grid._tickers[:3]))
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return object()

    app.state.memo.get_or_compute(("sentinel",), compute)
    app.state.memo.get_or_compute(("sentinel",), compute)
    assert calls["n"] == 1, "the second read is a cache hit"

    app.basket.replace(list(app.basket_grid._tickers[:2]))

    app.state.memo.get_or_compute(("sentinel",), compute)
    assert calls["n"] == 2, "a selection change must empty the memo"
