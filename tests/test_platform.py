"""Unit tests for the Platform-tab factor-beta scatter (v0.7.0 Workstream C+D).

`_update_factor_scatter` is exercised against a deterministic price frame
holding the factor proxy tickers plus a couple of strategies; the figure is a
real `go.FigureWidget`, so we assert on its trace data directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.layout.platform import _factor_beta_scatter, _update_factor_scatter
from src.layout.theme import _v_ref
from src.style import ASSET_CLASS_COLORS


def _universe(n: int = 400) -> pd.DataFrame:
    """Seeded prices: the three factor proxy tickers + two strategies."""
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(3)
    specs = {
        "SPX Index": (0.0004, 0.011),
        "LUTLTRUU Index": (0.0002, 0.005),
        "LD12TRUU Index": (0.00005, 0.0005),
        "AAA Index": (0.0003, 0.012),
        "BBB Index": (0.0002, 0.008),
    }
    return pd.DataFrame(
        {
            t: 100.0 * np.cumprod(1.0 + rng.normal(mu, sig, n))
            for t, (mu, sig) in specs.items()
        },
        index=idx,
    )


def _meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA Index", "BBB Index"],
            "asset_class": ["Equity", "Fixed Income"],
        }
    )


def test_v_ref_is_vertical_paper_height_line():
    shape = _v_ref(0.0)
    assert shape["type"] == "line"
    assert shape["xref"] == "x" and shape["x0"] == 0.0 and shape["x1"] == 0.0
    assert shape["yref"] == "paper" and shape["y0"] == 0 and shape["y1"] == 1


def test_update_factor_scatter_one_trace_per_asset_class():
    fig = _factor_beta_scatter()
    universe = _universe()
    arp = universe[["AAA Index", "BBB Index"]]
    _update_factor_scatter(
        fig, arp, universe, _meta(), years=1, title="Equity vs term-premium β — 1Y"
    )

    assert fig.layout.title.text == "Equity vs term-premium β — 1Y"
    # AAA → Equity, BBB → Fixed Income → one trace each.
    by_name = {tr.name: tr for tr in fig.data}
    assert set(by_name) == {"Equity", "Fixed Income"}
    assert by_name["Equity"].marker.color == ASSET_CLASS_COLORS["Equity"]
    assert by_name["Fixed Income"].marker.color == ASSET_CLASS_COLORS["Fixed Income"]
    # Each group has its single strategy plotted with finite betas.
    for tr in fig.data:
        assert len(tr.x) == 1 and len(tr.y) == 1
        assert np.isfinite(tr.x[0]) and np.isfinite(tr.y[0])


def test_update_factor_scatter_empty_clears_traces():
    fig = _factor_beta_scatter()
    _update_factor_scatter(
        fig, pd.DataFrame(), pd.DataFrame(), _meta(), years=1, title="empty"
    )
    assert fig.data == ()
    assert fig.layout.title.text == "empty"
