"""The Platform drill aggregation (#332, epic #331).

One state decides where the user is; `src/stats/drill.py` decides what is
drawn there. These tests pin the three rules the charts and the points table
all depend on:

- a node is a **path**, so a label repeated under two parents is two points;
- a group's value is the **equal-weight mean** of its members;
- the colour key is the coarsest level beneath the scope that still varies.

The shipped mock catalog cannot test the second one at depth. Grouping it to
family yields 18 nodes for 18 tickers — every family is a singleton, so a
"mean" there is a mean of one and would pass against a broken implementation.
The aggregation fixtures below are therefore synthetic and deliberately
lumpy: one family with three members, one category with two families. The
mock catalog is still used for the path-splitting cases, which it does carry.
"""

from __future__ import annotations

import pandas as pd
import pytest
from src import config as cfg
from src.stats import color_key, drill_points, node_paths


@pytest.fixture
def lumpy_meta() -> pd.DataFrame:
    """A catalog with real group sizes: 3-member family, 2-family category."""
    return pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "D", "E"],
            "asset_class": ["Equity", "Equity", "Equity", "Equity", "Fixed Income"],
            "category": ["Momentum", "Momentum", "Momentum", "Value", "Credit"],
            "family": ["Fast", "Fast", "Fast", "Cheap", "IG"],
        }
    )


@pytest.fixture
def lumpy_leaves() -> pd.DataFrame:
    """Per-ticker numeric leaves, values picked so means are exact in binary."""
    return pd.DataFrame(
        {"value": [1.0, 2.0, 6.0, 4.0, 8.0], "x": [0.5, 1.5, 2.5, 3.5, 4.5]},
        index=["A", "B", "C", "D", "E"],
    )


def test_a_node_is_a_path_not_a_label(lumpy_meta):
    """A label under two parents is two nodes, never one averaged blob."""
    meta = pd.concat(
        [
            lumpy_meta,
            pd.DataFrame(
                {
                    "ticker": ["F"],
                    "asset_class": ["Fixed Income"],
                    # The sample catalog's real case: Emerging Markets sits
                    # under two asset classes.
                    "category": ["Momentum"],
                    "family": ["Fast"],
                }
            ),
        ],
        ignore_index=True,
    )
    paths = node_paths(meta)
    assert paths.loc["A"].tolist() == ["Equity", "Momentum", "Fast"]
    assert paths.loc["F"].tolist() == ["Fixed Income", "Momentum", "Fast"]

    leaves = pd.DataFrame({"value": [1.0] * 6}, index=list("ABCDEF"))
    points = drill_points(leaves, paths, level="category")
    momentum = points[points["label"] == "Momentum"]
    assert len(momentum) == 2, "one Momentum per asset class, not one merged node"
    assert set(momentum["path"]) == {
        ("Equity", "Momentum"),
        ("Fixed Income", "Momentum"),
    }


def test_a_group_point_is_the_equal_weight_mean_of_its_members(
    lumpy_leaves, lumpy_meta
):
    """Hand-computed over a three-member family — the case the mock cannot make."""
    paths = node_paths(lumpy_meta)
    points = drill_points(
        lumpy_leaves, paths, scope=("Equity", "Momentum"), level="family"
    )
    fast = points.loc["Fast"]
    assert fast["count"] == 3
    assert fast["value"] == pytest.approx((1.0 + 2.0 + 6.0) / 3)
    assert fast["x"] == pytest.approx((0.5 + 1.5 + 2.5) / 3)


def test_every_numeric_column_is_averaged_and_nothing_else_is(lumpy_leaves, lumpy_meta):
    """The Scatter hands in value/x/z, the Strip five dates — one rule for both."""
    paths = node_paths(lumpy_meta)
    points = drill_points(lumpy_leaves, paths, level="category")
    assert list(points.columns) == ["path", "label", "count", "value", "x"]
    assert points.loc["Momentum", "value"] == pytest.approx(3.0)
    assert points.loc["Value", "count"] == 1


def test_the_scope_filters_before_the_grouping(lumpy_leaves, lumpy_meta):
    paths = node_paths(lumpy_meta)
    inside = drill_points(lumpy_leaves, paths, scope=("Equity",), level="category")
    assert set(inside["label"]) == {"Momentum", "Value"}
    assert "Credit" not in set(inside["label"]), "Fixed Income is out of scope"


def test_the_leaf_level_is_one_row_per_ticker(lumpy_leaves, lumpy_meta):
    paths = node_paths(lumpy_meta)
    points = drill_points(
        lumpy_leaves, paths, scope=("Equity", "Momentum", "Fast"), level="ticker"
    )
    assert list(points.index) == ["A", "B", "C"]
    assert (points["count"] == 1).all()
    # A strategy's value is its own, not an average of itself.
    assert points.loc["C", "value"] == pytest.approx(6.0)
    assert points.loc["C", "path"] == ("Equity", "Momentum", "Fast")


def test_a_missing_level_is_bucketed_so_a_path_is_never_ragged(lumpy_meta):
    """A partial feed still draws; a ragged path would break prefix grouping."""
    meta = lumpy_meta.drop(columns=["family"])
    paths = node_paths(meta)
    assert (paths["family"] == "Other").all()
    assert list(paths.columns) == list(cfg.analytics_levels())


def test_colour_keys_to_the_points_shown():
    """#331 decision 17 — a key that stops varying stops informing."""
    # At the root the points are categories; their parents are what differ.
    assert color_key(scope=(), level="category") == "asset_class"
    # Inside a category every point is a family, so family is the key.
    assert color_key(scope=("Equity", "Momentum"), level="family") == "family"
    assert color_key(scope=("Equity", "Momentum", "Fast"), level="ticker") == "ticker"


def test_empty_inputs_return_the_columns_rather_than_raising(lumpy_meta):
    paths = node_paths(lumpy_meta)
    empty = drill_points(pd.DataFrame(), paths, level="category")
    assert list(empty.columns) == ["path", "label", "count"]
    # A scope that matches nothing is a legitimate state: the user narrowed,
    # then changed the regime bucket out from under it.
    nothing = drill_points(
        pd.DataFrame({"value": [1.0]}, index=["A"]), paths, scope=("Nowhere",)
    )
    assert nothing.empty


def test_the_shipped_catalog_s_repeated_labels_draw_as_two_nodes_each():
    """The two cases #331 decision 15 names, pinned against the real catalog.

    They are why a node is a path. Each splits into exactly two nodes and each
    of those holds one ticker — which is precisely why they cannot also serve
    as the aggregation test above.
    """
    from src.data import load_metadata

    meta = load_metadata()
    paths = node_paths(meta)
    leaves = pd.DataFrame({"value": 1.0}, index=paths.index)

    categories = drill_points(leaves, paths, level="category")
    emerging = categories[categories["label"] == "Emerging Markets"]
    assert len(emerging) == 2
    assert {p[0] for p in emerging["path"]} == {"Equity", "Fixed Income"}

    families = drill_points(leaves, paths, level="family")
    sectors = families[families["label"] == "S&P US Sector"]
    assert len(sectors) == 2
    assert {p[1] for p in sectors["path"]} == {"Technology", "Energy"}


def test_the_shipped_catalog_cannot_test_aggregation_at_the_family_level():
    """Guards the reason the fixtures above are synthetic.

    If the catalog ever grows a multi-member family this fails, and the
    aggregation tests could then also be pinned against real data — which is
    worth knowing rather than discovering by writing a test that silently
    proves nothing.
    """
    from src.data import load_metadata

    paths = node_paths(load_metadata())
    leaves = pd.DataFrame({"value": 1.0}, index=paths.index)
    families = drill_points(leaves, paths, level="family")
    assert (families["count"] == 1).all(), (
        "a family now holds more than one strategy — the synthetic fixtures in "
        "this module could be replaced with the real catalog"
    )
