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

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..config import analytics_levels
from ..style import Color
from .charts import Chart
from .theme import _chart_layout, _short_ticker

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
            return pd.DataFrame(columns=["path", "label", "name", "value", "count"])
        paths = [tuple(row) for row in inside[levels].to_numpy()]
        lookup = names if names is not None else pd.Series(dtype=object)
        return pd.DataFrame(
            {
                "path": paths,
                "label": list(inside.index),
                "name": [lookup.get(t, _short_ticker(t)) for t in inside.index],
                "value": inside["value"].to_numpy(),
                "count": 1,
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
        """Turn a clicked cell's id back into a path and narrow to it."""
        if self._on_drill is None or not getattr(points, "point_inds", None):
            return
        index = points.point_inds[0]
        node_id = self.fig.data[0].ids[index]
        self._on_drill(tuple(node_id.split(PATH_SEP)))

    def clear(self) -> None:
        with self.fig.batch_update():
            self.fig.data = ()
        self._points = pd.DataFrame(columns=["path", "label", "name", "value", "count"])
