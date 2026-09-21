"""The Platform card's colours key to one rule (v0.9.30 fix).

Two functions computed "the colour-key value of each point": the charts keyed
off the **level's name** (`color_values`), the palette builder off the path's
**depth**. They agreed only while the card was based at the root. v0.9.27
based it at a solution, so every point sat at depth 1 — the palette was built
for the *parent* (`ARP`) while the charts looked up the *label* (`Equity`),
every lookup missed, and both the Scatter and the Strip drew one grey trace.
"""

from __future__ import annotations

import pandas as pd
from src.layout.platform import CURATED_COLOR_LEVEL, _colors_for
from src.layout.platform_charts import color_values
from src.style import ASSET_CLASS_COLORS, ASSET_CLASS_FALLBACK_COLOR


def _points(paths: list[tuple[str, ...]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "path": paths,
            "label": [p[-1] for p in paths],
            "name": [p[-1] for p in paths],
            "value": [1.0] * len(paths),
            "count": [1] * len(paths),
            "leaf": [False] * len(paths),
        }
    )


def test_the_palette_is_keyed_by_what_the_charts_look_up():
    """The regression in one assertion: every key a chart asks for must be in
    the palette the builder produced, at any depth."""
    for paths, key in (
        ([("ARP",), ("Smart Beta",)], "solution"),
        ([("ARP", "Equity"), ("ARP", "FX")], "asset_class"),
        ([("ARP", "Equity", "AI"), ("ARP", "Equity", "Clean")], "category"),
    ):
        points = _points(paths)
        palette = _colors_for(points, key)
        asked = [str(v) for v in color_values(points, key)]
        missing = [a for a in asked if a not in palette]
        assert not missing, f"{key}: {missing} not in {sorted(palette)}"


def test_points_below_the_root_get_distinct_colours():
    points = _points([("ARP", "Equity", "AI"), ("ARP", "Equity", "Clean")])
    palette = _colors_for(points, "category")
    assert len(set(palette.values())) == 2


def test_the_curated_identity_colours_apply_at_the_asset_class_level():
    """`ASSET_CLASS_COLORS` is keyed by asset class. The builder curated at
    `analytics_levels()[0]`, which stopped being asset class when `solution`
    took the lead in v0.9.25 — so the identity colours applied nowhere."""
    assert CURATED_COLOR_LEVEL == "asset_class"
    points = _points([("ARP", "Equity"), ("ARP", "Fixed Income")])
    palette = _colors_for(points, CURATED_COLOR_LEVEL)
    assert palette["Equity"] == ASSET_CLASS_COLORS["Equity"]
    assert palette["Fixed Income"] == ASSET_CLASS_COLORS["Fixed Income"]


def test_no_point_falls_back_to_grey_at_any_depth():
    for paths, key in (
        ([("ARP", "Equity")], "asset_class"),
        ([("ARP", "Equity", "AI")], "category"),
        ([("ARP", "Equity", "AI", "Momentum")], "family"),
    ):
        palette = _colors_for(_points(paths), key)
        assert ASSET_CLASS_FALLBACK_COLOR not in palette.values(), key
