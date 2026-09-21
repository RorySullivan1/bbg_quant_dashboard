"""The Platform analytics card's three charts (epic #331).

Siblings of `charts.py`'s Multi-Strategy figures, kept apart because they
answer a different question: those draw a chosen basket over time, these draw
the whole catalog at one moment, grouped by the drill.

Each is a `Chart` (#223) — it builds its own `FigureWidget` and updates it —
and each also exposes **`points()`**, the frame it drew, plus the label its
value column should carry. That is what lets one points table sit beside
whichever chart is active without knowing which one it is (#331 decision 5):
the table reads `points()`, never a figure's traces.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..config import STRIP_DAYS, analytics_levels
from ..stats import compounded_return
from ..style import (
    ASSET_CLASS_COLORS,
    ASSET_CLASS_FALLBACK_COLOR,
    LINE_PALETTE,
    Color,
)
from .charts import Chart
from .theme import _chart_layout, _h_ref, _short_ticker

#: Path separator inside a node id. The id is the path, so the same label under
#: two parents stays two cells — the reason `stats.drill.node_paths` exists.
PATH_SEP = " / "

#: The diverging ramp: red below zero, neutral at it, green above.
_RAMP = [
    [0.0, Color.RED_600.value],
    [0.5, Color.SLATE_500.value],
    [1.0, Color.GREEN_600.value],
]

#: Where the colour range is clipped, as a percentile of |value| over the
#: leaves. A single outlier otherwise flattens every other cell to the middle
#: of the ramp; the fixed ±2 this replaces was a z-score's range, which a raw
#: Sharpe or a raw return has no reason to share.
_RANGE_PERCENTILE = 95


def symmetric_range(values: pd.Series) -> tuple[float, float]:
    """``(-limit, +limit)`` from the data, clipped at `_RANGE_PERCENTILE`.

    Symmetric about zero because the ramp is diverging and its midpoint means
    "average": an asymmetric range would put zero somewhere off-centre and
    colour a flat strategy as though it were good or bad.
    """
    clean = pd.Series(values).dropna().abs()
    if clean.empty:
        return (-1.0, 1.0)
    limit = float(np.percentile(clean, _RANGE_PERCENTILE))
    if not np.isfinite(limit) or limit <= 0:
        limit = float(clean.max()) or 1.0
    return (-limit, limit)


def value_format(metric: str) -> str:
    """The d3 format a metric's numbers are read in."""
    return ".2%" if metric == "return" else ".2f"


def group_colors(
    keys: Iterable[str], *, curated: Mapping[str, str] | None = None
) -> dict[str, str]:
    """A distinct colour per key, deterministic in sorted order.

    The generalization of the asset-class-only helper this replaces. The drill
    re-keys the colours at every depth — asset class at the root, family inside
    a category, strategy inside a family (#331 decision 17) — so the palette
    has to serve keys that are not asset classes at all.

    ``curated`` wins where it has an entry, which is how asset classes keep
    their identity colours at the root. Everything else takes the next unused
    `LINE_PALETTE` colour, and **cycles** once the palette runs out rather than
    collapsing onto the fallback: a family larger than the palette should still
    draw distinguishable neighbours, and the legend and hover name every point
    whatever the hue. The fallback survives for a key the cycle cannot reach.
    """
    mapping = dict(curated or {})
    used = set(mapping.values())
    spare = [c for c in LINE_PALETTE if c not in used]
    out: dict[str, str] = {}
    unmapped = 0
    for key in sorted({str(k) for k in keys}):
        if key in mapping:
            out[key] = mapping[key]
            continue
        if spare:
            out[key] = spare[unmapped % len(spare)]
            unmapped += 1
        else:
            out[key] = ASSET_CLASS_FALLBACK_COLOR
    return out


def asset_class_colors(classes: Iterable[str]) -> dict[str, str]:
    """`group_colors` with the curated asset-class map — the root's colours."""
    return group_colors(classes, curated=ASSET_CLASS_COLORS)


class IcicleChart(Chart):
    """The catalog's hierarchy, sized by count and coloured by mean metric.

    Replaces the sunburst, which sized its arcs by |z| — the gross magnitude of
    the very quantity colour already encoded, so a ring's shares said nothing.
    Here **every leaf counts 1** and `branchvalues="total"`, which makes a
    cell's width its share of *strategies* at every level: "how many strategies
    are in this group" is a question the catalog does not otherwise answer
    visually (#331 decision 8).

    Colour is the leaf's raw metric, averaged up each level, on a diverging
    ramp centred at zero with a range taken from the data.
    """

    def __init__(self, *, on_drill=None) -> None:
        self._on_drill = on_drill
        self._points = pd.DataFrame()
        self._value_label = ""
        self._metric = "sharpe"
        #: The scope this trace was drawn at, so a click can tell "into a
        #: child" from "out of the node I am already in".
        self._scope: tuple[str, ...] = ()
        super().__init__()

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            layout=_chart_layout(title="", margin=dict(t=44, b=10, l=10, r=10))
        )

    @property
    def value_label(self) -> str:
        """What the points table should head this chart's value column."""
        return self._value_label

    @property
    def value_format(self) -> str:
        return value_format(self._metric)

    def points(self) -> pd.DataFrame:
        """The leaves drawn, as the shared `path` / `label` / `name` / `value`
        / `count` frame. The icicle shows every level at once, so its points
        are the strategies rather than a drill depth's nodes."""
        return self._points

    def update(
        self,
        frame: pd.DataFrame,
        *,
        metric: str,
        metric_label: str,
        names: pd.Series | None = None,
        scope: tuple[str, ...] = (),
    ) -> None:
        """Draw `stats.icicle_frame`'s output.

        ``frame`` carries one column per `analytics_levels()` entry plus
        ``value``; ``names`` maps ticker to display name for the points table.
        """
        self._metric = metric
        self._value_label = metric_label
        self._scope = tuple(scope)
        levels = list(analytics_levels())
        frame = frame.dropna(subset=["value"])
        if frame.empty:
            self.clear()
            return
        frame = frame.copy()
        for level in levels:
            frame[level] = frame[level].fillna("Other").astype(str)

        ids: list[str] = []
        labels: list[str] = []
        parents: list[str] = []
        values: list[float] = []
        colors: list[float] = []

        def _emit(group: pd.DataFrame, depth: int, parent_id: str) -> float:
            """One subtree, depth-first and bottom-up.

            A node's value is the count its children actually reported, not a
            second aggregation of the same rows, so `branchvalues="total"`
            holds exactly at every level however many there are.
            """
            if depth == len(levels):
                for ticker, row in group.iterrows():
                    ids.append(f"{parent_id}{PATH_SEP}{ticker}")
                    labels.append(_short_ticker(ticker))
                    parents.append(parent_id)
                    values.append(1.0)
                    colors.append(float(row["value"]))
                return float(len(group))

            total = 0.0
            for value, sub in group.groupby(levels[depth]):
                node_id = f"{parent_id}{PATH_SEP}{value}" if parent_id else str(value)
                subtotal = _emit(sub, depth + 1, node_id)
                ids.append(node_id)
                labels.append(str(value))
                parents.append(parent_id)
                values.append(subtotal)
                colors.append(float(sub["value"].mean()))
                total += subtotal
            return total

        _emit(frame, 0, "")
        low, high = symmetric_range(frame["value"])

        icicle = go.Icicle(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            maxdepth=len(levels),
            # **The drill's zoom, re-asserted on every redraw.** Plotly zooms
            # client-side when a cell is clicked, but the click also re-renders
            # this trace from the kernel — and a trace built without `level`
            # renders at the root, which snapped the chart straight back to the
            # whole catalog while the table and the Level chips (driven from
            # the same `Drill`) correctly showed the narrowed view. Setting it
            # from the scope is what makes the client-side zoom and the kernel
            # state the same thing rather than two that race.
            level=PATH_SEP.join(scope),
            # Horizontal: the hierarchy reads left to right and the labels sit
            # along the reading direction, which a vertical tiling turns on its
            # side at the depths that matter most.
            tiling=dict(orientation="h"),
            marker=dict(
                colors=colors,
                colorscale=_RAMP,
                cmid=0,
                cmin=low,
                cmax=high,
                line=dict(width=1, color=Color.CHART_BG.value),
                showscale=True,
                colorbar=dict(title=dict(text=metric_label)),
            ),
            customdata=[[c] for c in values],
            hovertemplate=(
                "%{label}<br>"
                + f"{metric_label} "
                + "%{color:"
                + value_format(metric)
                + "}<br>%{customdata[0]:.0f} strategies<extra></extra>"
            ),
        )
        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.add_traces([icicle])
        self._attach_click()
        self._points = self._leaf_points(frame, levels, names, scope)

    def _leaf_points(
        self,
        frame: pd.DataFrame,
        levels: list[str],
        names: pd.Series | None,
        scope: tuple[str, ...],
    ) -> pd.DataFrame:
        """The strategies under ``scope``, in the shared points shape."""
        inside = frame
        for position, value in enumerate(scope):
            inside = inside[inside[levels[position]] == value]
        if inside.empty:
            return pd.DataFrame(
                columns=["path", "label", "name", "value", "count", "leaf"]
            )
        paths = [tuple(row) for row in inside[levels].to_numpy()]
        lookup = names if names is not None else pd.Series(dtype=object)
        return pd.DataFrame(
            {
                "path": paths,
                "label": list(inside.index),
                "name": [lookup.get(t, _short_ticker(t)) for t in inside.index],
                "value": inside["value"].to_numpy(),
                "count": 1,
                "leaf": True,
            },
            index=list(inside.index),
        )

    def _attach_click(self) -> None:
        """Route a cell click into the shared drill.

        Plotly zooms the icicle client-side whatever happens here; this is what
        tells the *kernel*, so the scatter, the strip and the points table
        follow the same zoom (#331 decision 9). **Gated**: if the callback does
        not reach the kernel under Voila the icicle still follows the drill set
        from the Level chips and the breadcrumb, it just cannot set it.
        """
        if self._on_drill is None or not self.fig.data:
            return
        trace = self.fig.data[0]
        if not hasattr(trace, "on_click"):  # pragma: no cover - plotly shape
            return
        trace.on_click(self._clicked)

    def _clicked(self, _trace, points, _state) -> None:
        """Turn a clicked cell's id back into a path and narrow to it.

        A **ticker** cell is ignored. Its id carries the ticker as a fourth
        segment, which is one deeper than the hierarchy the scope addresses,
        so narrowing to it would raise — and a strategy has no children to
        narrow into anyway. The points row is the way into Single Strategy.
        """
        if self._on_drill is None or not getattr(points, "point_inds", None):
            return
        index = points.point_inds[0]
        path = tuple(self.fig.data[0].ids[index].split(PATH_SEP))
        if len(path) > len(analytics_levels()):
            return
        if path == self._scope:
            # Plotly's own icicle zooms OUT when you click the cell you are
            # already inside. Following it keeps the chart's behaviour the one
            # the user expects from the widget, and gives the drill a way up
            # that is not the breadcrumb.
            path = path[:-1]
        self._on_drill(path)

    def clear(self) -> None:
        with self.fig.batch_update():
            self.fig.data = ()
        self._points = pd.DataFrame(columns=["path", "label", "name", "value", "count"])


class RegimeFactorScatter(Chart):
    """The regime view and the factor view, merged into one 3D scatter.

    They were two charts answering halves of one question: both per-strategy
    scatters coloured by asset class, one with the regime filter and no factor
    axes, the other with the axes and no filter. Here **Y is the metric over
    the Window, X the term-premium β and Z the equity-risk-premium β**, all
    measured over the same sample — the Window's days restricted to the regime
    bucket (#331 decision 10).

    The points are whatever the drill says: one marker per category at the
    root, per family inside a category, per strategy inside a family, each the
    equal-weight mean of its members.
    """

    def __init__(self, *, on_drill=None) -> None:
        self._on_drill = on_drill
        self._points = pd.DataFrame()
        self._value_label = ""
        self._metric = "sharpe"
        super().__init__()

    def _build(self) -> go.FigureWidget:
        """The scene, with the origin drawn by the axes rather than by planes.

        The translucent `Mesh3d` zero planes this replaces dimmed the markers
        behind them — the thing the chart is for. A scene axis takes no paper
        shape, but it does take its own `zeroline`, wall `line` and `gridcolor`,
        which is enough to carry the origin without covering anything.
        `aspectmode="cube"` keeps the three axes comparable.
        """
        return go.FigureWidget(
            layout=_chart_layout(
                title="",
                showlegend=True,
                legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
                # `align` and `showarrow` are all a 3D scene offers here —
                # there is no anchor property to put the label on one side of
                # the marker, so the template above keeps it small instead.
                hoverlabel=dict(align="left", namelength=-1, showarrow=False),
                scene=dict(
                    aspectmode="cube",
                    xaxis=_scene_axis("Term-premium β"),
                    yaxis=_scene_axis(""),
                    zaxis=_scene_axis("Equity risk-premium β"),
                ),
            )
        )

    @property
    def value_label(self) -> str:
        return self._value_label

    @property
    def value_format(self) -> str:
        return value_format(self._metric)

    def points(self) -> pd.DataFrame:
        return self._points

    def update(
        self,
        points: pd.DataFrame,
        *,
        metric: str,
        metric_label: str,
        color_key: str,
        colors: Mapping[str, str],
    ) -> None:
        """Draw the aggregated frame `stats.drill.drill_points` returned.

        ``colors`` maps each colour-key value to its hue and ``color_key`` names
        the level they key to, so the chart never decides either — that rule
        lives once, in `stats.drill.color_key` (#331 decision 17).
        """
        self._metric = metric
        self._value_label = metric_label
        self._points = points
        if points.empty:
            self.clear()
            return

        fmt = value_format(metric)
        traces = []
        for key, group in points.groupby(_color_values(points, color_key)):
            counts = group["count"].to_numpy()
            traces.append(
                go.Scatter3d(
                    mode="markers",
                    name=str(key),
                    x=group["x"].to_numpy(),
                    y=group["value"].to_numpy(),
                    z=group["z"].to_numpy(),
                    marker=dict(
                        # A group's marker grows with how many strategies it
                        # stands for; a strategy is always the base size.
                        size=_marker_sizes(counts),
                        color=colors.get(str(key), ASSET_CLASS_FALLBACK_COLOR),
                        line=dict(width=0),
                    ),
                    customdata=np.column_stack(
                        [
                            group["name"].astype(str).to_numpy(),
                            [_members_note(c) for c in counts],
                            [_path_key(p) for p in group["path"]],
                            group["leaf"].to_numpy(),
                        ]
                    ),
                    # Three short lines, not five. A 3D scene gives no anchor
                    # for the hover label, so its FOOTPRINT is the only lever
                    # on how much of the cloud it hides — and the betas read
                    # perfectly well side by side on one line.
                    hovertemplate=(
                        "<b>%{customdata[0]}</b>"
                        + f"<br>{metric_label} "
                        + "%{y:"
                        + fmt
                        + "}%{customdata[1]}"
                        "<br>β term %{x:.2f} · equity %{z:.2f}<extra></extra>"
                    ),
                )
            )

        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.add_traces(traces)
            self.fig.layout.scene.yaxis.title.text = metric_label
            self.fig.layout.scene.yaxis.tickformat = fmt
        self._attach_clicks()

    def _attach_clicks(self) -> None:
        """Every trace narrows on click, not just the first."""
        if self._on_drill is None:
            return
        for trace in self.fig.data:
            if hasattr(trace, "on_click"):  # pragma: no branch
                trace.on_click(self._clicked)

    def _clicked(self, trace, points, _state) -> None:
        """Narrow to the clicked marker's path.

        At the leaf level a click does nothing: a strategy has no children, and
        the table row beside the chart is the way into Single Strategy. The
        **flag** decides that, not the count — a one-member category has a
        count of 1 too, and on the shipped catalog nearly every root marker is
        one, so a count test would make the chart undrillable.
        """
        if self._on_drill is None or not getattr(points, "point_inds", None):
            return
        index = points.point_inds[0]
        row = trace.customdata[index]
        if _is_leaf(row[3]):
            return
        self._on_drill(tuple(str(row[2]).split(PATH_SEP)))

    def clear(self) -> None:
        with self.fig.batch_update():
            self.fig.data = ()
        self._points = pd.DataFrame()


def _scene_axis(title: str) -> dict:
    """One scene axis carrying the origin and its wall edge."""
    return dict(
        title=title,
        zeroline=True,
        zerolinecolor=Color.CHART_ZERO_LINE.value,
        zerolinewidth=3,
        showline=True,
        linecolor=Color.CHART_AXIS_LINE.value,
        linewidth=2,
        gridcolor=Color.CHART_GRID.value,
        backgroundcolor=Color.TRANSPARENT.value,
    )


def _color_values(points: pd.DataFrame, color_key: str) -> pd.Series:
    """The value each point is coloured by, per `stats.drill.color_key`.

    At the root the key is the hierarchy's first level, which for the points
    drawn there is their **parent** — the path's first segment. Below the
    root the key is the points' own level, so each point is its own key and
    the members can be told apart. *A key that stops varying stops informing*
    (#331 decision 17), which is what goes wrong if this reads the parent at
    every depth: a whole scope collapses to one colour and one legend entry.

    Read off the **path**, never by re-joining metadata, so the colour and the
    position always describe the same node.
    """
    if points.empty:
        return pd.Series(dtype=str)
    if color_key == analytics_levels()[0]:
        return points["path"].map(lambda p: str(p[0]) if len(p) else "Other")
    return points["label"].astype(str)


def _marker_sizes(counts: np.ndarray) -> np.ndarray:
    """Base size for a strategy, growing with the members a group stands for."""
    return 5.0 + 3.0 * np.sqrt(np.maximum(counts.astype(float), 1.0) - 1.0)


def _path_key(path) -> str:
    """A path as one string, so it survives a numpy `customdata` column."""
    return PATH_SEP.join(str(segment) for segment in path)


class StripChart(Chart):
    """Five dates of 1D returns, one marker per point per date.

    The card's other views are all six months or more; nothing on it could
    draw *this week*, which is what the QIS Bulletin talks about. X is a
    **categorical** axis of the last five trading dates, Y the 1D return.

    Built from `go.Scatter` with a computed jitter rather than the hidden-box
    construction a strip plot usually uses (#331 decision 12): a drillable
    marker needs a point index and `customdata` the kernel controls, which
    `go.Box`'s own point scatter does not give.

    Reads neither Metric nor Window — its metric is the 1D return and its
    window is five days — which is why the bar hides both while it is active.
    """

    #: How far a marker may sit from its date's centre, as a share of the
    #: column. Deterministic in the point's position, so a redraw does not
    #: reshuffle the cloud and read as movement in the data.
    JITTER = 0.28

    def __init__(self, *, on_drill=None) -> None:
        self._on_drill = on_drill
        self._points = pd.DataFrame()
        super().__init__()

    def _build(self) -> go.FigureWidget:
        return go.FigureWidget(
            layout=_chart_layout(
                title="",
                showlegend=True,
                legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
                hovermode="closest",
                # A numeric axis wearing the dates as tick labels, NOT a
                # categorical one: Plotly puts every marker of a category on
                # one line, so a group of ten strategies would draw as a
                # single dot. The jitter below needs somewhere to move to.
                xaxis=dict(title="", tickmode="array"),
                yaxis=dict(title="1D return", tickformat=".1%", zeroline=True),
            )
        )

    @property
    def value_label(self) -> str:
        """The table's column head: the five dots' honest single number."""
        return f"{STRIP_DAYS}D Return"

    @property
    def value_format(self) -> str:
        return ".2%"

    def points(self) -> pd.DataFrame:
        return self._points

    def update(
        self,
        points: pd.DataFrame,
        dates: Sequence,
        *,
        color_key: str,
        colors: Mapping[str, str],
    ) -> None:
        """Draw the aggregated frame, one column per date.

        ``points`` carries one column per date (the transposed daily returns,
        run through `drill_points`) plus `path` / `label` / `name` / `count`.
        Fewer than five dates draws what exists.
        """
        if points.empty or not len(dates):
            self.clear()
            return
        labels = [_date_label(d) for d in dates]
        keys = _color_values(points, color_key)
        # Jitter is assigned over ALL the points, not per trace, so two groups
        # drawn in different traces cannot land on the same spot.
        # Keyed by PATH, not by label: two nodes can share a label — the
        # shipped catalog has "S&P US Sector" under two categories — and
        # keying by label would draw them on top of each other.
        slot = {path: index for index, path in enumerate(points["path"])}

        traces = []
        for key, group in points.groupby(keys):
            xs: list[float] = []
            ys: list[float] = []
            custom: list[list] = []
            for offset, date in enumerate(dates):
                for _index, row in group.iterrows():
                    xs.append(offset + _jitter(slot[row["path"]], len(points)))
                    ys.append(float(row[date]))
                    custom.append(
                        [
                            str(row["name"]),
                            _members_note(row["count"]),
                            _path_key(row["path"]),
                            labels[offset],
                            bool(row["leaf"]),
                        ]
                    )
            traces.append(
                go.Scatter(
                    mode="markers",
                    name=str(key),
                    x=xs,
                    y=ys,
                    marker=dict(
                        size=8,
                        color=colors.get(str(key), ASSET_CLASS_FALLBACK_COLOR),
                        line=dict(width=0),
                    ),
                    customdata=custom,
                    hovertemplate=(
                        "<b>%{customdata[0]}</b>"
                        "<br>%{customdata[3]} %{y:.2%}%{customdata[1]}"
                        "<extra></extra>"
                    ),
                )
            )

        with self.fig.batch_update():
            self.fig.data = ()
            self.fig.add_traces(traces)
            self.fig.layout.shapes = (_h_ref(0.0),)
            self.fig.layout.xaxis.tickvals = list(range(len(dates)))
            self.fig.layout.xaxis.ticktext = labels
            self.fig.layout.xaxis.range = [-0.5, len(dates) - 0.5]
        self._attach_clicks()
        self._points = points.assign(value=compounded_return(points[list(dates)].T))

    def _attach_clicks(self) -> None:
        if self._on_drill is None:
            return
        for trace in self.fig.data:
            if hasattr(trace, "on_click"):  # pragma: no branch
                trace.on_click(self._clicked)

    def _clicked(self, trace, points, _state) -> None:
        if self._on_drill is None or not getattr(points, "point_inds", None):
            return
        row = trace.customdata[points.point_inds[0]]
        if _is_leaf(row[4]):
            return
        self._on_drill(tuple(str(row[2]).split(PATH_SEP)))

    def clear(self) -> None:
        with self.fig.batch_update():
            self.fig.data = ()
        self._points = pd.DataFrame()


def _date_label(value) -> str:
    """A date as its column heading."""
    stamp = pd.Timestamp(value)
    return stamp.strftime("%d %b")


def _jitter(position: int, total: int) -> float:
    """A point's stable offset from its date's centre.

    Spread evenly across the column rather than drawn at random, so a redraw
    cannot reshuffle the cloud and read as movement in the data, and two
    points never overlap exactly. A single point sits on the centre line.
    """
    if total <= 1:
        return 0.0
    share = position / (total - 1) - 0.5
    return share * 2.0 * StripChart.JITTER


def _is_leaf(flag) -> bool:
    """Whether a `customdata` cell means "this row is a strategy".

    `np.column_stack` casts a mixed block to strings, so a boolean arrives as
    `"True"` / `"False"` rather than as a bool. Read through this rather than
    trusting truthiness — `bool("False")` is `True`, which would make every
    marker undrillable.
    """
    return str(flag).lower() in ("true", "1")


def _members_note(count) -> str:
    """ " · mean of N" for a group, and nothing at all for a strategy.

    A group's value is the equal-weight mean of its members, and the hover has
    to say so or the number reads as the node's own. It was `%{customdata[1]}`
    against the raw count, which rendered "1Y Sharpe 1.23 3" — a bare integer
    the reader has to guess at. A leaf gets an empty string rather than "mean
    of 1", which would be true and useless.
    """
    return f" · mean of {int(count)}" if int(count) > 1 else ""
