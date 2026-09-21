"""The Platform drill: paths through the analytics hierarchy, and the
aggregation every chart and the points table read.

One state (`layout.drill.Drill`) decides *where* the user is; this module
decides *what is drawn there*. Three pure functions over a per-ticker frame:
`node_paths` turns metadata into a path per ticker, `drill_points` groups any
numeric leaf frame to the current depth, and `color_key` names the level the
colours should key to. Charts differ only in the leaf frame they hand in.

A node is a **path**, never a bare label. In the sample catalog *Emerging
Markets* sits under two asset classes and *S&P US Sector* under two
categories, so a label alone would merge two unrelated groups into one point
and average across them (#331 decision 15).
"""

from __future__ import annotations

import pandas as pd

from ..config import DRILL_LEAF_LEVEL, analytics_levels, drill_levels

#: What a level's missing values are bucketed as, matching the renderer's own
#: treatment of a level the metadata does not carry.
OTHER = "Other"


def node_paths(
    meta: pd.DataFrame, levels: tuple[str, ...] | None = None
) -> pd.DataFrame:
    """One row per ticker, one column per level — the ticker's path.

    Indexed by ticker, columns in `ANALYTICS_LEVELS` order. A level the
    metadata lacks, or a blank value in one, is bucketed as "Other" so every
    ticker has a full path: a partial feed still draws, and a path is never
    ragged, which is what lets `drill_points` group on a fixed-width prefix.
    """
    keys = tuple(levels) if levels is not None else analytics_levels()
    if meta.empty or "ticker" not in meta.columns:
        return pd.DataFrame(columns=list(keys), index=pd.Index([], name="ticker"))
    frame = meta.set_index("ticker")
    out = pd.DataFrame(index=frame.index)
    for level in keys:
        column = (
            frame[level]
            if level in frame.columns
            else pd.Series(pd.NA, index=frame.index)
        )
        out[level] = column.astype("object").where(
            column.notna() & (column != ""), OTHER
        )
    return out


def drill_points(
    leaves: pd.DataFrame,
    paths: pd.DataFrame,
    *,
    scope: tuple[str, ...] = (),
    level: str | None = None,
) -> pd.DataFrame:
    """Aggregate ``leaves`` to one row per node at ``level``, inside ``scope``.

    ``leaves`` is any per-ticker frame of numeric columns — the Scatter's
    ``value`` / ``x`` / ``z``, or the Strip's dates × tickers **transposed** to
    tickers × dates. Every numeric column is averaged **equal-weight** over the
    node's members (#331 decision 18), which for the Strip is exactly the
    equal-weight basket's daily return and for the betas is exact over the same
    sample.

    ``scope`` is a path prefix; ``level`` the depth to group at, defaulting to
    the first drill stop. At the leaf level each row is one ticker and no
    grouping happens, so a strategy's value is its own.

    Returns ``path`` (the tuple), ``label`` (the node's last segment — the
    ticker at the leaf), ``count`` (members), ``leaf`` (whether the row IS a
    strategy) and the averaged numeric columns, indexed by ticker at the leaf
    level and by node label above it.

    ``leaf`` is carried rather than inferred, because neither of the two
    things a caller might infer it from actually works. ``count == 1`` is a
    single-member *group* as often as a strategy — 16 of the shipped catalog's
    17 root points are one-member categories — and the path is no help either,
    since a family node and a ticker under it are both three segments deep.
    Routing a click on either would open a category in Single Strategy.

    Any regime mask belongs to the caller and must already be applied to
    ``leaves``: a group's value is the mean of its members' bucket values, not
    the bucket value of their mean.
    """
    keys = list(analytics_levels())
    stop = level or drill_levels()[0]
    depth = len(keys) if stop == DRILL_LEAF_LEVEL else keys.index(stop) + 1
    is_leaf = stop == DRILL_LEAF_LEVEL
    numeric = leaves.select_dtypes("number")
    if numeric.empty or paths.empty:
        return pd.DataFrame(
            columns=["path", "label", "count", "leaf", *numeric.columns]
        )

    joined = numeric.join(paths, how="inner")
    for position, value in enumerate(scope):
        joined = joined[joined[keys[position]] == value]
    if joined.empty:
        return pd.DataFrame(
            columns=["path", "label", "count", "leaf", *numeric.columns]
        )

    prefix = keys[:depth]
    if stop == DRILL_LEAF_LEVEL:
        out = joined[list(numeric.columns)].copy()
        out["path"] = [tuple(row) for row in joined[prefix].to_numpy()]
        out["label"] = joined.index
        out["count"] = 1
    else:
        grouped = joined.groupby(prefix, dropna=False, sort=False)
        out = grouped[list(numeric.columns)].mean()
        out["count"] = grouped.size()
        out = out.reset_index()
        out["path"] = [tuple(row) for row in out[prefix].to_numpy()]
        out["label"] = out[prefix[-1]]
        out = out.drop(columns=prefix).set_index("label", drop=False)
        out.index.name = None
    out["leaf"] = is_leaf
    return out[["path", "label", "count", "leaf", *numeric.columns]]


def color_key(
    scope: tuple[str, ...] = (),
    level: str | None = None,
    levels: tuple[str, ...] | None = None,
) -> str:
    """The level the drawn points' colours should key to.

    The coarsest level beneath ``scope`` that still varies among the points:
    at the root that is the hierarchy's first level (asset class — the
    category points' parents), and below the root it is the points' own level.

    *Settled against keeping asset-class colour at every depth: a key that
    stops varying stops informing, and the point of narrowing is to tell the
    members apart* (#331 decision 17). This is that rule, spelled once, for
    the Scatter, the Strip and the table to read.
    """
    keys = tuple(levels) if levels is not None else analytics_levels()
    if not scope:
        return keys[0]
    return level or drill_levels()[0]
