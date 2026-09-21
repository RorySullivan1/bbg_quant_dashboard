"""Platform-tab chart factories + updaters.

Standalone visuals for the Platform tab — the factor-beta scatter, the
asset-class sunburst, and the regime views — as distinct from the analysis
panes (`panes.py` / `charts.py`), which belong to the Multi-Strategy tab.

Every figure follows the same two-part shape: a factory builds it once, and an
updater mutates it in place inside a `fig.batch_update()` block. Updaters
compute from the already-fetched price cache, so no chart here issues a BQL
call.

`PlatformAnalytics` (#219) owns the analytics card: the three figures, the tab
pills, their control columns, and the lazy-render state. It used to be a
twenty-field `SimpleNamespace` assembled in `build_app` and handed back to
twelve free functions declared `(state, meta, pa)` — a class with its `self`
passed by hand.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING

import ipywidgets as W
import pandas as pd

from ..config import (
    CATALOG_SCORE_MIN_SAMPLE_DAYS,
    DEFAULT_RANKING_METRIC,
    DRILL_LEAF_LEVEL,
    DRILL_ROOT_LABEL,
    REGIME_SPECS,
    SCORE_SAMPLE_DAYS,
    STRIP_DAYS,
    TRADING_DAYS_PER_YEAR,
    LevelRegime,
    TercileRegime,
    analytics_levels,
    drill_level_label,
    drill_levels,
    rankable_metric_chips,
    stat_window_years,
    stat_windows,
    universe_grid_default_window,
)
from ..stats import (
    color_key,
    daily_returns,
    drill_points,
    equity_risk_premium,
    icicle_frame,
    node_paths,
    recent_daily_returns,
    regime_factor_frame,
    regime_mask,
    rolling_autocorr,
    rolling_metric_zscore,
    tercile_bounds,
    term_premium,
)
from ..style import ANALYTICS_CHART_SHARE, ANALYTICS_HEIGHT, ANALYTICS_TABLE_SHARE
from .drill import Drill, next_stop
from .grids import ChartPointsGrid, zscore_column_name
from .html import STYLE_CTX, render_template
from .platform_charts import (
    IcicleChart,
    RegimeFactorScatter,
    StripChart,
    asset_class_colors,
    group_colors,
)
from .rails import Breadcrumb, ChipGroup, RailSection, control_bar, drill_bar
from .theme import _short_ticker

if TYPE_CHECKING:
    # No cycle today, but `state.py` is one import away from reaching this
    # module, and the annotation never needs the symbol at runtime. Guarded
    # like `filter_panel` / `single_strategy`, where the cycle is real.
    from .state import DashboardState


def _regime_window_mask(
    indicator: pd.Series | None,
    index: pd.Index,
    low: float | None,
    high: float | None,
) -> pd.Series:
    """Boolean mask over ``index``: the regime bucket, or all-True when there's
    no indicator / no bucket (a scaffolded regime → unconditioned all-days view).
    """
    if indicator is None or indicator.empty or low is None or high is None:
        return pd.Series(True, index=index)
    return regime_mask(indicator.reindex(index), low, high)


@contextmanager
def _guard_render(state: DashboardState, label: str):
    """Route any exception raised in the block into ``state.init_errors`` labeled
    with ``label`` — the shared error handling for the Platform render functions
    (a failed chart records its traceback in the commentary block rather than
    breaking the whole render)."""
    try:
        yield
    except Exception:
        state.init_errors.append(f"{label} failed:\n{traceback.format_exc()}")


def _with_names(points: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Give each point the display name its hover and the table should show.

    A strategy takes its catalog name; a group is named by its own label,
    because a group has no name beyond what it is.
    """
    if points.empty:
        return points.assign(name=pd.Series(dtype=object))
    names = (
        meta.set_index("ticker")["name"]
        if {"ticker", "name"} <= set(meta.columns)
        else pd.Series(dtype=object)
    )
    out = points.copy()
    out["name"] = [
        names.get(label, _short_ticker(str(label))) if count == 1 else str(label)
        for label, count in zip(out["label"], out["count"], strict=True)
    ]
    return out


def _color_values_of(points: pd.DataFrame) -> list[str]:
    """The colour-key value of each point: its parent at the root, else itself."""
    depth = max(len(points["path"].iloc[0]) - 1, 0)
    if depth == 0:
        return [str(v) for v in points["label"]]
    return [str(p[0]) if len(p) else "Other" for p in points["path"]]


def _colors_for(points: pd.DataFrame, key: str) -> dict[str, str]:
    """The palette for the points shown.

    Curated only when the key is the hierarchy's first level — that is where
    the asset-class identity colours belong, and a family called "Momentum"
    has no claim on Equity's blue.
    """
    if points.empty:
        return {}
    values = _color_values_of(points)
    if key == analytics_levels()[0]:
        return asset_class_colors(values)
    return group_colors(values)


def regime_bucket_options(regime_type: str) -> list[tuple[str, object]]:
    """Bucket-dropdown options for a regime: ``(label, (low, high))`` for the
    fixed-level mode, ``(label, tercile_key)`` for the tercile modes."""
    spec = REGIME_SPECS[regime_type]
    if isinstance(spec, LevelRegime):
        return [(label, (low, high)) for label, low, high in spec.buckets]
    return [(label, key) for label, key in spec.bucket_labels]


def _window_days(label: str) -> int:
    """A stats-window label (`"6M"`, `"1Y"`) as a trading-day count.

    The table's Window chips carry labels, because that is what decides which
    performance columns are visible; the scorer wants a count of rows. One
    conversion, here, rather than the same product spelled at the call site and
    again in whatever reads it next — and `stat_window_years` is what keeps
    `"6M"` half a year instead of six (#324).
    """
    return round(stat_window_years(label) * TRADING_DAYS_PER_YEAR)


class PlatformAnalytics:
    """The Platform tab's analytics card: three charts behind three pill-tabs.

    Owns its widgets (figures, pills, per-tab control columns, the shared
    lookback) and its **lazy-render state** — `active_analytics` is the visible
    tab, `fresh` the set already drawn against current data. Only the visible
    chart is computed on load or Refresh; the hidden two draw on first
    activation, and a data or lookback change marks all three stale and
    re-draws only the visible one (v0.9.13 #168).

    **`meta` stays a per-call argument rather than an attribute.** `build_app`
    re-points its `meta` to the recent-performance-pruned catalog after each
    load, so an attribute set at construction would go stale — silently, since
    a stale catalog still renders, just with the pruned indices back. Passing it
    makes that impossible. (The observers wired in `wire` do capture the `meta`
    they were given, which is the pre-existing behaviour tracked in #242.)

    `state` *is* held: it is one mutable object whose contents change in place,
    so a reference is always current.
    """

    def __init__(
        self,
        state: DashboardState,
        *,
        z_metric_chips: ChipGroup,
        window_chips: ChipGroup,
        on_open_strategy: Callable[[str], None] | None = None,
    ) -> None:
        self.state = state
        # The all-catalog grid's ranking controls live with the table, not in
        # the card, but drive `render_universe_grid` — so they are passed in,
        # not built. The injection has survived two restyles unchanged
        # (dropdowns → chips in #279, rail → table bar in #325), because
        # `ChipGroup` carries the same `.value` / `.label` / `.observe` surface
        # a dropdown does — `.label` in particular, which names the z column.
        #
        # `window_chips` is the **table's** Window, the one that also decides
        # which performance columns are visible. Since #324 there is no second
        # window and no lookback: the score is measured over the period the row
        # is being read at, against a fixed `SCORE_SAMPLE_DAYS` sample.
        self.z_metric_chips = z_metric_chips
        #: How a strategy row leaves the card. The app passes the same
        #: method the catalog table and the leaderboard use, so the three
        #: entry points into Single Strategy cannot diverge (#286's rule).
        self._on_open_strategy = on_open_strategy
        self.window_chips = window_chips
        #: Resolved at fire time, never captured (#242). `wire` sets it.
        self._current_meta: Callable[[], pd.DataFrame] | None = None

        self.icicle = IcicleChart(on_drill=self._drill_from_chart)
        self.scatter = RegimeFactorScatter(on_drill=self._drill_from_chart)
        self.strip = StripChart(on_drill=self._drill_from_chart)

        # --- the Chart view bar (#333) ---------------------------------------
        #
        # The card's own chips over the table's own option lists: the two
        # surfaces can be read at different windows but cannot OFFER different
        # things (#331 decision 1). Nothing here spells a label — Metric comes
        # from `RANKABLE_METRICS`, Window from `stat_windows()`, Level from
        # `drill_levels()` — so a relabelling reaches the card for free.
        self.chart_chips = ChipGroup(
            [("Icicle", "icicle"), ("Scatter", "scatter"), ("Strip", "strip")],
            value="icicle",
            row=True,
        )
        self.metric_chips = ChipGroup(
            rankable_metric_chips(), value=DEFAULT_RANKING_METRIC, row=True
        )
        self.card_window_chips = ChipGroup(
            [label for label, _ in stat_windows()],
            value=universe_grid_default_window(),
            row=True,
        )

        self.regime_type_chips = ChipGroup(list(REGIME_SPECS.keys()), row=True)
        # Source stays a dropdown: its options are the live benchmark registry
        # or a region list, and a dropdown is the right control for a long list
        # (#331 decision 13, #302's reasoning).
        self.regime_selector_dd = W.Dropdown(
            options=[("\u2014", "")],
            value="",
            description="Source",
            style={"description_width": "60px"},
            layout=W.Layout(width="240px"),
        )
        _init_buckets = regime_bucket_options(self.regime_type_chips.value)
        self.regime_bucket_chips = ChipGroup(
            _init_buckets, value=_init_buckets[0][1], row=True
        )
        regime_controls = W.VBox(
            [self.regime_type_chips, self.regime_selector_dd, self.regime_bucket_chips],
            layout=W.Layout(width="auto"),
        )

        # The universe filter. The card draws ONE solution at a time (v0.9.27):
        # the root used to be every solution at once, which is a cell per
        # solution and no way to say which one you came to look at. Populated
        # from the drawn universe on first render, because the catalog is not
        # loaded yet here.
        self.solution_chips = ChipGroup([("\u2014", "")], row=True)
        #: Set while the chips are repopulated from the universe, so their own
        #: observer does not re-enter and re-render mid-render.
        self._syncing_solution = False

        # Solution is the base, not a stop, so it is not on offer here.
        self.level_chips = ChipGroup(
            [(drill_level_label(key), key) for key in drill_levels()[1:]],
            value=drill_levels()[1],
            row=True,
        )
        self.breadcrumb = Breadcrumb(on_pick=self._on_breadcrumb)

        self.bar = control_bar(
            RailSection("Chart", self.chart_chips),
            RailSection("Metric", self.metric_chips),
            RailSection("Window", self.card_window_chips),
            RailSection("Regime", regime_controls),
            RailSection("Solution", self.solution_chips),
            title="Chart view",
        )
        # The drill is a position, not a setting, so it gets its own line
        # below rather than two more sections on the bar — and the breadcrumb
        # leads it, because "where am I" reads before "how deep".
        self.drill_bar = drill_bar(
            RailSection("Scope", self.breadcrumb),
            RailSection("Level", self.level_chips),
        )

        #: Chart key -> the figure (or placeholder) it mounts.
        self.analytics_tabs = {
            "icicle": self.icicle.fig,
            "scatter": self.scatter.fig,
            "strip": self.strip.fig,
        }

        # Chart beside its own points, both at ONE fixed height (#331 dec. 7).
        # Stretching is the wrong tool here for `CATALOG_TABLE_HEIGHT`'s reason
        # (#298): whichever box held more content would set the row, so a long
        # points list would grow the chart and a tall chart would stretch a
        # three-row table.
        #
        # `flex: 1 1 0%` **and** `min-width: 0` on the chart, the #280 pair: a
        # flex item will not shrink below its content without the second, so a
        # wide legend would push the table off the row instead of fitting.
        self.chart_box = W.Box(
            [self.icicle.fig],
            layout=W.Layout(
                flex=f"1 1 {ANALYTICS_CHART_SHARE}",
                width="100%",
                min_width="0",
                height=ANALYTICS_HEIGHT,
            ),
        )
        self.points_grid = ChartPointsGrid(on_pick=self._pick_point)
        points_box = W.Box(
            [self.points_grid.widget],
            layout=W.Layout(
                flex=f"1 1 {ANALYTICS_TABLE_SHARE}",
                width="100%",
                min_width="0",
                height=ANALYTICS_HEIGHT,
            ),
        )
        analytics_body = W.HBox(
            [self.chart_box, points_box],
            layout=W.Layout(width="100%", align_items="stretch"),
        )

        self.card = W.VBox(
            [
                W.HTML(
                    render_template(
                        "grid_header", **STYLE_CTX, text="Platform analytics"
                    )
                ),
                self.bar,
                self.drill_bar,
                analytics_body,
            ],
            layout=W.Layout(width="100%"),
        )
        self.card.add_class("bbg-card")
        # A back-reference so a test (and a future sibling panel) can reach the
        # controller from the widget tree without counting child indices, which
        # move whenever the card is restyled.
        self.card._analytics = self

        #: Where the user is. One object, replaced wholesale through
        #: `set_drill`, read by every chart and (from #337) the points table.
        self.drill = Drill()
        #: Set while `set_drill` repaints the Level chips and the breadcrumb,
        #: so their own observers do not re-enter it and render twice.
        self._syncing_drill = False

        #: Lazy-render state: the visible chart, and those drawn against the
        #: current data.
        self.active_analytics: str = "icicle"
        self.fresh: set[str] = set()
        self._sync_sections()

    def _restale_scatter(self) -> None:
        """A regime control changed: the Scatter is stale, redraw it if shown.

        Only the Scatter reads the regime, so this stales one chart rather
        than all three — but it must stale it even while hidden, or selecting
        it later would show the previous bucket.
        """
        self.fresh.discard("scatter")
        if self.active_analytics == "scatter" and self._current_meta is not None:
            self._render_tab(self._current_meta(), "scatter")

    def _pick_point(self, row: pd.Series) -> None:
        """A points-table row: narrow on a group, open a strategy (#331 dec. 19).

        The row's **`leaf` flag** routes it. Neither of the two things that
        could be inferred instead works: `count == 1` is a one-member *group*
        as often as a strategy — 16 of the shipped catalog's 17 root points
        are one-member categories — and a family node and a ticker under it
        are both three path segments deep. Either inference would clear the
        user's filters and then hand a category name to a ticker dropdown.
        """
        if bool(row["leaf"]):
            if self._on_open_strategy is not None:
                self._on_open_strategy(str(row["label"]))
        else:
            self._drill_from_chart(tuple(row["path"]))

    def render_points(self) -> None:
        """Show the active chart's own points beside it.

        Runs after every chart render, so every drill change reaches it for
        free: a marker click, a Level chip, a breadcrumb segment and the
        icicle's own zoom all re-render the visible chart.
        """
        chart = {
            "icicle": self.icicle,
            "scatter": self.scatter,
            "strip": self.strip,
        }[self.active_analytics]
        level = (
            DRILL_LEAF_LEVEL if self.active_analytics == "icicle" else self.drill.level
        )
        self.points_grid.update(
            chart.points(),
            level_label=drill_level_label(level),
            value_label=chart.value_label,
            fmt=chart.value_format,
        )

    # --- the drill ------------------------------------------------------------

    @property
    def solution(self) -> str:
        """The solution the card is filtered to — the drill's base."""
        return str(self.solution_chips.value or "")

    def _sync_solution_chips(self, meta: pd.DataFrame) -> None:
        """Offer the solutions the drawn universe actually contains.

        Built from the universe rather than from `UNIVERSE_SOLUTION_VALUES`,
        which is what the universe is filtered *by* and not what survived: the
        catalog carries a `Beta` solution the analytics universe excludes, and
        a chip for it would draw an empty chart.
        """
        prices = self.state.arp_universe_prices
        if prices.empty or not {"ticker", "solution"} <= set(meta.columns):
            return
        inside = meta[meta["ticker"].isin(prices.columns)]
        values = sorted({str(v) for v in inside["solution"].dropna() if str(v)})
        if not values or [v for _, v in self.solution_chips.options] == values:
            return
        keep = self.solution if self.solution in values else values[0]
        self._syncing_solution = True
        try:
            self.solution_chips.set_options([(v, v) for v in values], value=keep)
        finally:
            self._syncing_solution = False
        self.set_drill((keep,), next_stop((keep,)))

    def _on_solution(self, _change=None) -> None:
        """A Solution chip re-bases the drill and redraws."""
        if self._syncing_solution:
            return
        base = (self.solution,)
        self.set_drill(base, next_stop(base))
        self._render_current()

    def set_drill(self, scope: tuple[str, ...], level: str) -> None:
        """The one writer of `self.drill`.

        Every entry point — a Level chip, a breadcrumb segment, and from
        #334-#337 a marker click, an icicle zoom and a table row — lands here,
        so no chart can hold a private focus (#331 decision 15). Repaints the
        two controls that display the state with their observers suppressed,
        then re-renders the visible chart once.
        """
        # Clamp to a level the chips actually offer. `solution` is a base
        # rather than a stop since v0.9.27, so it is off the chip row — but
        # `next_stop(())` still names it, and assigning it raised inside the
        # breadcrumb's callback, where a raise surfaces as a dead control
        # rather than as an error anyone can act on. The one setter is where
        # the drill and its displays are made to agree, so it is where this
        # belongs.
        offered = [value for _, value in self.level_chips.options]
        if offered and level not in offered:
            level = offered[0]
        self.drill = Drill(scope=tuple(scope), level=level)
        self._syncing_drill = True
        try:
            self.level_chips.value = self.drill.level
            # A pinned solution IS the root, so the breadcrumb names it and
            # shows only what lies below. With none pinned — before the first
            # render populates the chips — the whole scope is shown under the
            # generic root, or the first segment would silently vanish.
            if self.solution:
                self.breadcrumb.root_label = self.solution
                self.breadcrumb.set_path(self.drill.scope[1:])
            else:
                self.breadcrumb.root_label = DRILL_ROOT_LABEL
                self.breadcrumb.set_path(self.drill.scope)
        finally:
            self._syncing_drill = False

    def narrow_to(self, path: tuple[str, ...]) -> None:
        """Move into ``path`` and show its children — what a click means.

        Clamped to the pinned solution: the Icicle's click-to-zoom-out walks
        one segment off the path, and from the base that would be the whole
        catalog again — out of the filter the Solution chips say is applied.
        """
        path = tuple(path)
        if self.solution and not path:
            path = (self.solution,)
        moved = self.drill.narrowed_to(path)
        self.set_drill(moved.scope, moved.level)

    def _drill_from_chart(self, path: tuple[str, ...]) -> None:
        """A marker or icicle click: narrow, then redraw the visible chart.

        The same door a Level chip and a breadcrumb segment use, so no chart
        can hold a focus the others do not know about (#331 decision 15).
        """
        self.narrow_to(path)
        self._render_current()

    def _on_breadcrumb(self, prefix: tuple[str, ...]) -> None:
        """A breadcrumb segment: back to that prefix, at the stop below it.

        ``prefix`` is relative to the pinned solution, which the breadcrumb
        does not show as a segment, so the base goes back on here.
        """
        if self._syncing_drill:
            return
        self.narrow_to((self.solution, *prefix) if self.solution else prefix)
        self._render_current()

    def _on_level_chip(self, _change=None) -> None:
        """A Level chip sets the depth within the current scope."""
        if self._syncing_drill:
            return
        self.set_drill(self.drill.scope, self.level_chips.value)
        self._render_current()

    def _render_current(self) -> None:
        """Re-render the visible chart and mark the other two stale.

        Every control that reaches here — Metric, Window, a Level chip, a
        breadcrumb segment, a marker click — changes what **all three** charts
        would draw, but only one is on screen. Staling the hidden two is what
        makes `activate`'s `fresh` skip safe: without it, switching charts
        shows one drawn at the previous metric or the previous scope, with the
        bar above it describing something else.

        `_current_meta` is set by `wire`; before that the card has not been
        wired to a catalog and there is nothing to draw.
        """
        self.fresh.clear()
        if self._current_meta is not None:
            self._render_tab(self._current_meta(), self.active_analytics)

    # --- conditional sections -------------------------------------------------

    def _sync_sections(self) -> None:
        """Show only the sections the active chart reads (#331 decision 3).

        Hiding rather than rebuilding, so a chip keeps its selection across a
        chart switch: the Strip does not read Metric, but coming back to the
        Scatter should find the metric the user last chose still chosen.
        """
        # Keyed to `active_analytics`, not to the chip: the chip drives
        # `activate`, which sets it, so they agree in the app — and a direct
        # `activate` call stays self-consistent instead of syncing the sections
        # against whatever the chip happened to hold.
        chart = self.active_analytics
        self.bar.show("Regime", chart == "scatter")
        self.bar.show("Metric", chart != "strip")
        self.bar.show("Window", chart != "strip")
        # Scope shows on every chart, the Icicle included. #331 hid it there
        # because the Icicle "zooms itself" — but its zoom IS the drill now,
        # so hiding the breadcrumb left the one chart that can narrow without
        # any way to see where it had got to or to climb back out.
        self.drill_bar.show("Scope", True)
        # Level still hides on the Icicle, which draws every level at once:
        # there is no single depth for a chip to select.
        self.drill_bar.show("Level", chart != "icicle")

    # --- per-chart renders ----------------------------------------------------

    def render_universe_grid(self, meta: pd.DataFrame) -> None:
        """Render the all-catalog grid with the ranking column the current
        Metric and Window chips describe.

        The score is the selected metric over the selected window, standardized
        against `SCORE_SAMPLE_DAYS` of that metric's own rolling history — a
        fixed sample, so the column is comparable to itself across windows and
        to the Leaderboard beside it (#324). A ticker that cannot supply
        `CATALOG_SCORE_MIN_SAMPLE_DAYS` of that sample scores NaN and renders a
        dash rather than being standardized against the little it has.

        Reads the cached perf table (``state.universe_up``) and computes only
        the ranking column live from the already-fetched
        ``arp_universe_prices`` — no BQL, no recompute.
        """
        state = self.state
        if state.arp_universe_prices.empty:
            return
        with _guard_render(state, "all-catalog grid z-score render"):
            window_label = self.window_chips.value
            zcol = rolling_metric_zscore(
                state.arp_universe_prices,
                metric=self.z_metric_chips.value,
                window=_window_days(window_label),
                zscore_window=SCORE_SAMPLE_DAYS,
                min_sample=CATALOG_SCORE_MIN_SAMPLE_DAYS,
                returns=state.universe_rets,
            )
            state.universe_grid.update(
                meta,
                state.universe_up,
                zcol=zcol,
                zname=zscore_column_name(self.z_metric_chips.label, window_label),
            )

    def render_icicle(self, meta: pd.DataFrame) -> None:
        """Draw the hierarchy from the Metric / Window chips, live from cache."""
        state = self.state
        if state.arp_universe_prices.empty:
            return
        with _guard_render(state, "icicle render"):
            metric = self.metric_chips.value
            names = (
                meta.set_index("ticker")["name"]
                if {"ticker", "name"} <= set(meta.columns)
                else None
            )
            frame = icicle_frame(
                state.arp_universe_prices,
                meta,
                metric=metric,
                window=_window_days(self.card_window_chips.value),
                returns=state.universe_rets,
            )
            # Only the pinned solution's subtree reaches the trace. Handing it
            # the whole catalog and relying on `level` to show one branch left
            # the others one plotly zoom-out away, which would walk out of the
            # filter the chips say is applied.
            base = analytics_levels()[0]
            if self.solution and base in frame.columns:
                frame = frame[frame[base] == self.solution]
            self.icicle.update(
                frame,
                metric=metric,
                metric_label=(
                    f"{self.card_window_chips.label} {self.metric_chips.label}"
                ),
                names=names,
                scope=self.drill.scope,
            )

    def render_scatter(self, meta: pd.DataFrame) -> None:
        """One scatter for the regime view and the factor view (#331 dec. 10).

        They were two charts answering halves of one question. Betas and the
        metric are now measured over the same sample — the Window's days
        restricted to the regime bucket — so Y is the metric, X the
        term-premium β and Z the equity-risk-premium β over one set of days.

        The mask is applied to the **leaves**, before the drill aggregates
        them, so a category's point is the mean of its members' bucket values
        rather than the bucket value of their mean (#331 decision 18).
        """
        state = self.state
        if state.arp_universe_prices.empty or state.universe_prices.empty:
            return
        with _guard_render(state, "regime factor scatter render"):
            rets = state.universe_rets
            if rets is None or rets.empty:
                rets = daily_returns(state.arp_universe_prices)
            rets = rets.tail(_window_days(self.card_window_chips.value))

            low, high = self.resolve_regime_bucket()
            mask = _regime_window_mask(self.regime_indicator(), rets.index, low, high)
            erp = equity_risk_premium(state.universe_prices).reindex(rets.index)
            tp = term_premium(state.universe_prices).reindex(rets.index)

            metric = self.metric_chips.value
            points = _with_names(
                drill_points(
                    regime_factor_frame(rets, mask, erp, tp, metric=metric),
                    node_paths(meta),
                    scope=self.drill.scope,
                    level=self.drill.level,
                ),
                meta,
            )
            key = color_key(self.drill.scope, self.drill.level)
            self.scatter.update(
                points,
                metric=metric,
                metric_label=(
                    f"{self.card_window_chips.label} {self.metric_chips.label}"
                ),
                color_key=key,
                colors=_colors_for(points, key),
            )

    def render_strip(self, meta: pd.DataFrame) -> None:
        """Five dates of 1D returns at the current drill, live from cache.

        Reads neither Metric nor Window: its metric is the 1D return and its
        window is `STRIP_DAYS` (#331 decision 12). A change to either therefore
        must not redraw it, which the bar enforces by hiding both.
        """
        state = self.state
        if state.arp_universe_prices.empty:
            return
        with _guard_render(state, "strip render"):
            recent = recent_daily_returns(
                state.arp_universe_prices,
                days=STRIP_DAYS,
                returns=state.universe_rets,
            )
            if recent.empty:
                self.strip.clear()
                return
            points = _with_names(
                drill_points(
                    recent.T,  # dates x tickers -> tickers x dates
                    node_paths(meta),
                    scope=self.drill.scope,
                    level=self.drill.level,
                ),
                meta,
            )
            key = color_key(self.drill.scope, self.drill.level)
            self.strip.update(
                points,
                list(recent.index),
                color_key=key,
                colors=_colors_for(points, key),
            )

    # --- regime resolution ----------------------------------------------------

    def regime_indicator(self) -> pd.Series | None:
        """The regime indicator series from the cache, per the active regime's
        shape, or None when its ticker(s) are absent (-> unconditioned view)."""
        spec = REGIME_SPECS.get(self.regime_type_chips.value)
        if spec is None:
            return None
        prices = self.state.universe_prices
        if isinstance(spec, TercileRegime) and spec.kind == "autocorr":
            ticker = self.regime_selector_dd.value
            if not ticker or ticker not in prices.columns:
                return None
            rets = daily_returns(prices[[ticker]])[ticker]
            return rolling_autocorr(rets, window=spec.autocorr_window)
        # Both remaining shapes read a raw level; only the ticker's source
        # differs — a tercile regime's comes from its dropdown, a level
        # regime's is fixed.
        ticker = (
            spec.ticker
            if isinstance(spec, LevelRegime)
            else self.regime_selector_dd.value
        )
        if not ticker or ticker not in prices.columns:
            return None
        return prices[ticker]

    def resolve_regime_bucket(self) -> tuple[float | None, float | None]:
        """The ``(low, high)`` bounds for the active bucket. Fixed-level regimes
        read the tuple off the bucket dropdown; tercile regimes derive it from
        the live indicator's 1/3 & 2/3 quantiles over the lookback.
        ``(None, None)`` when no indicator is available."""
        spec = REGIME_SPECS.get(self.regime_type_chips.value)
        if isinstance(spec, LevelRegime):
            low, high = self.regime_bucket_chips.value
            return (low, high)
        indicator = self.regime_indicator()
        if indicator is None:
            return (None, None)
        return tercile_bounds(
            indicator.tail(_window_days(self.card_window_chips.value)),
            self.regime_bucket_chips.value,
        )

    def regime_selector_options(self) -> list[tuple[str, object]]:
        """The indicator-source options for the active regime, ``(label, ticker)``.

        Trend sources its list from the **live** benchmark registry rather than
        one frozen into `REGIME_SPECS` at import, so a benchmark added at
        runtime is offered here too. Rate-level carries a literal `selector`;
        a fixed-level regime has one ticker and so offers no source at all."""
        spec = REGIME_SPECS.get(self.regime_type_chips.value)
        if not isinstance(spec, TercileRegime):
            return []
        if spec.selector_source == "benchmarks":
            return self.state.benchmarks.options(labeled=True)
        return list(spec.selector)

    def sync_regime_controls(self) -> None:
        """Repopulate the bucket dropdown for the active regime and show / hide
        the indicator-source dropdown.

        Also re-run on a benchmark-registry change, so this keeps the current
        source **selected** whenever it survives into the new option list.
        Switching regime type still falls back to the first option, since the
        old value belongs to a different domain (a benchmark ticker is not a
        rate region)."""
        selector = self.regime_selector_options()
        if selector:
            previous = self.regime_selector_dd.value
            values = [value for _, value in selector]
            self.regime_selector_dd.options = selector
            self.regime_selector_dd.value = (
                previous if previous in values else selector[0][1]
            )
            self.regime_selector_dd.layout.display = ""
        else:
            self.regime_selector_dd.layout.display = "none"
        options = regime_bucket_options(self.regime_type_chips.value)
        # Preserve the active bucket across a registry change for the same reason.
        prev_bucket = self.regime_bucket_chips.value
        bucket_values = [value for _, value in options]
        self.regime_bucket_chips.set_options(
            options,
            value=prev_bucket if prev_bucket in bucket_values else options[0][1],
        )

    # --- lazy tab rendering ---------------------------------------------------

    def _render_tab(self, meta: pd.DataFrame, which: str) -> None:
        """Render one analytics tab and mark it fresh."""
        self._sync_solution_chips(meta)
        renderer = {
            "icicle": self.render_icicle,
            "scatter": self.render_scatter,
            "strip": self.render_strip,
        }[which]
        renderer(meta)
        self.fresh.add(which)
        # The table reads whatever the chart just drew, so it follows every
        # render rather than being driven separately from each control.
        if which == self.active_analytics:
            self.render_points()

    def render_active(self, meta: pd.DataFrame) -> None:
        """Render whichever tab is shown — called on load and Refresh so only
        the visible chart is computed, not all three."""
        self._render_tab(meta, self.active_analytics)

    def invalidate(self, meta: pd.DataFrame) -> None:
        """Mark every tab stale (the data or shared lookback changed) and
        re-render only the visible one; the hidden two re-render lazily when
        next activated."""
        self.fresh.clear()
        self.render_active(meta)

    def activate(self, meta: pd.DataFrame, which: str) -> None:
        """Switch to chart ``which``: render it first if it isn't fresh (lazy
        first-view), show the sections it reads, and swap the figure.

        The Chart chips paint their own active state, so unlike the pill row
        they replace there is nothing to restyle here."""
        self.active_analytics = which
        if which not in self.fresh:
            self._render_tab(meta, which)
        self._sync_sections()
        self.chart_box.children = (self.analytics_tabs[which],)
        self.render_points()

    # --- wiring ---------------------------------------------------------------

    def wire(self, current_meta: Callable[[], pd.DataFrame]) -> None:
        """Wire every observer: the table's ranking Metric, and the card's own
        Chart / Metric / Window / Regime / Level controls. Each re-renders live
        from the cache, no BQL.

        Takes a **callable**, not a frame (#242). `build_app` re-points its
        `meta` to the recent-performance-pruned catalog after every load, so an
        observer that captured the frame it was wired with would redraw from the
        *pre-prune* catalog — putting the stale indices the prune removed back
        into the grid. Resolving it at fire time makes that impossible, and
        needs nothing remembered at the prune sites.
        """
        self._current_meta = current_meta

        # Only the Metric is wired here. The Window has a second job — which
        # performance columns are visible — so `DashboardApp._on_window_change`
        # owns it and does both, the way it owns the grouping chips (#324).
        self.z_metric_chips.observe(
            lambda _c: self.render_universe_grid(current_meta()), names="value"
        )

        self.chart_chips.observe(
            lambda c: self.activate(current_meta(), c["new"]), names="value"
        )

        def _on_regime_type(_change=None):
            self.sync_regime_controls()
            self.fresh.discard("scatter")
            if self.active_analytics == "scatter":
                self._render_tab(current_meta(), "scatter")

        self.regime_type_chips.observe(_on_regime_type, names="value")
        self.regime_selector_dd.observe(
            lambda _c: self._restale_scatter(), names="value"
        )
        self.regime_bucket_chips.observe(
            lambda _c: self._restale_scatter(), names="value"
        )

        # Metric and Window re-render the visible chart and **stale the other
        # two**. `activate` skips a chart that is still `fresh`, so without
        # this a switch would show a chart drawn at the previous metric while
        # the chips above it said otherwise.
        for chips in (self.metric_chips, self.card_window_chips):
            chips.observe(lambda _c: self._render_current(), names="value")

        self.level_chips.observe(self._on_level_chip, names="value")
        self.solution_chips.observe(self._on_solution, names="value")

        self.sync_regime_controls()

        # A benchmark added at runtime has to reach the Trend regime's source
        # dropdown too. That widget can't `register` with the registry: it is
        # shared with the Rate-level regime, whose options are regions, so the
        # registry would overwrite them whenever Rate-level was the active
        # regime. Re-syncing instead repopulates it only while Trend is active,
        # and preserves the current selection.
        self.state.benchmarks.on_change(self.sync_regime_controls)
