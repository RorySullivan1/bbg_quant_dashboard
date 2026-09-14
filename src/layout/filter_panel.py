"""A reusable catalog-filter panel, shared by Multi-Strategy and Single Strategy.

A **Filters** accordion whose right panel is a pill bar over a swappable
value-list, plus **Clear section** and **Clear all** buttons. The pills come
from the catalog schema (`filter_dimensions`): every filterable field that is
not claimed by Characteristics gets a checkbox group, captioned with its schema
label, tiers first. **Characteristics** is a launch-date range and a currency
dropdown; **Quantitative** is nine per-metric ``≥``/``≤`` threshold rows
(Sharpe / Sortino / Calmar / Beta / Treynor / Jensen / VaR / RSI / Z-Score).

The panel is **selection-agnostic**: it only answers "which tickers match the
current filter state" via ``matching(meta, state)`` and leaves the caller to
act on the result. Every user-adjustable input is exposed in ``.inputs`` for
the caller to ``observe(...)``; the Clear buttons are wired internally and
simply reset those inputs, which fires the caller's observers in turn.

Three objects rather than one bag of twenty attributes (#218):
`CategoricalFilter` per checkbox dimension, `QuantFilter` for the threshold
rows (which owns the memoised metric table added in #167 — previously closure
state nobody could inspect), and `FilterPanel` composing them with the
Characteristics widgets and the pill bar.

The quant threshold filter reads the already-fetched price caches on
``state``, so the panel issues no BQL call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import ipywidgets as W
import pandas as pd

from ..config import (
    MONTH_WINDOW,
    SHORT_WINDOW_OPTIONS,
    TRADING_DAYS_PER_YEAR,
    field_label,
    filter_dimensions,
)
from ..data import apply_filters, unique_values
from ..stats import (
    ann_beta,
    daily_returns,
    jensen_alpha,
    quant_metrics_table,
    treynor_ratio,
    zscore_cross_section,
)
from .benchmarks import BenchmarkRegistry
from .chrome import _make_tab_button, _style_tab_button
from .filters import _checkbox_group, _q_row, _section_label
from .panes import _make_benchmark_dropdown

if TYPE_CHECKING:
    # `state.py` reaches this module through its own imports, so a runtime
    # `from .state import DashboardState` raises ImportError on a partially
    # initialized module. The annotation needs the name, not the object.
    from .state import DashboardState

#: Filterable fields the **Characteristics** view owns instead of the pill bar:
#: `live_date` is a min/max range and `currency` a single dropdown, neither of
#: which is a checkbox group. Every other filterable field becomes a pill, so
#: adding a filterable column to `CATALOG_SCHEMA` lights one up on its own.
_CHARACTERISTICS_FIELDS: tuple[str, ...] = ("live_date", "currency")

#: The two views that are not a metadata column at all. Their keys are chosen so
#: they cannot collide with a schema field key, which lets one dict hold both
#: kinds of view and one `active` slot address either.
_CHARACTERISTICS = "@characteristics"
_QUANTITATIVE = "@quantitative"
_SPECIAL_VIEW_LABELS = {
    _CHARACTERISTICS: "Characteristics",
    _QUANTITATIVE: "Quantitative",
}


def _pill_fields() -> tuple[str, ...]:
    """Field keys getting a checkbox-group pill, in bar order.

    Read at call time, not at import, so a relabelled or re-ordered schema
    reaches a panel built afterwards.
    """
    return tuple(
        f.key for f in filter_dimensions() if f.key not in _CHARACTERISTICS_FIELDS
    )


def _view_label(key: str) -> str:
    """The pill caption for a view key — schema label, or the special view's."""
    return _SPECIAL_VIEW_LABELS.get(key) or field_label(key)


@dataclass
class CategoricalFilter:
    """One filter dimension: a scrollable checkbox group over its values.

    `get` is `_checkbox_group`'s reader, kept rather than re-implemented so the
    panel and the group cannot disagree about what "selected" means.
    """

    key: str
    content: W.Widget
    checks: list[W.Checkbox]
    get: Callable[[], list[str]]

    @classmethod
    def build(cls, key: str, values: list[str]) -> CategoricalFilter:
        content, getter, checks = _checkbox_group(values)
        return cls(key=key, content=content, checks=checks, get=getter)

    @property
    def label(self) -> str:
        """The pill caption — the schema's display label for this field."""
        return field_label(self.key)

    def selected(self) -> list[str]:
        """The ticked values; empty means this dimension is unfiltered."""
        return self.get()

    def clear(self) -> None:
        for cb in self.checks:
            cb.value = False


class QuantFilter:
    """The **Quantitative** view: nine per-metric ``>=``/``<=`` threshold rows.

    Owns the memoised metric table (v0.9.13 #167). It used to be closure state
    inside `make_filter_panel`, so nothing could inspect or reset it; here it is
    `_memo` plus the identity of the ARP frame it was computed from, which is
    what a Refresh invalidates.
    """

    #: Metric name -> the metric's own benchmark dropdown. Beta / Treynor /
    #: Jensen each carry an independent one.
    BENCH_METRICS = ("Beta", "Treynor", "Jensen")

    def __init__(self, *, registry: BenchmarkRegistry | None = None) -> None:
        self.period_dd = W.Dropdown(
            options=[("1Y", 1), ("3Y", 3), ("5Y", 5)],
            value=1,
            description="Period",
            style={"description_width": "70px"},
            layout=W.Layout(width="200px"),
        )

        def _bench() -> W.Dropdown:
            # The shared benchmark-dropdown factory (panes); no label, narrower.
            return _make_benchmark_dropdown(
                description="", width="200px", registry=registry
            )

        self.bench_dd = {name: _bench() for name in self.BENCH_METRICS}
        self.z_metric_dd = W.Dropdown(
            options=[
                "Sharpe",
                "Sortino",
                "Calmar",
                "Beta",
                "Treynor",
                "Jensen",
                "VaR",
                "RSI",
            ],
            value="Sharpe",
            layout=W.Layout(width="120px"),
        )
        self.z_window_dd = W.Dropdown(
            options=SHORT_WINDOW_OPTIONS,
            value=MONTH_WINDOW,
            layout=W.Layout(width="80px"),
        )

        sharpe_row, sharpe_op, q_sharpe = _q_row("Sharpe")
        sortino_row, sortino_op, q_sortino = _q_row("Sortino")
        calmar_row, calmar_op, q_calmar = _q_row("Calmar")
        beta_row, beta_op, q_beta = _q_row("Beta", trailing=self.bench_dd["Beta"])
        treynor_row, treynor_op, q_treynor = _q_row(
            "Treynor", trailing=self.bench_dd["Treynor"]
        )
        jensen_row, jensen_op, q_jensen = _q_row(
            "Jensen α", trailing=self.bench_dd["Jensen"]
        )
        var_row, var_op, q_var = _q_row("VaR %")
        rsi_row, rsi_op, q_rsi = _q_row("RSI")
        z_row, z_op, q_z = _q_row(
            "Z-Score",
            trailing=W.HBox(
                [
                    W.HTML("<div style='padding:0 6px;'>of</div>"),
                    self.z_metric_dd,
                    self.z_window_dd,
                ],
                layout=W.Layout(align_items="center"),
            ),
        )

        self.rows = [
            sharpe_row,
            sortino_row,
            calmar_row,
            beta_row,
            treynor_row,
            jensen_row,
            var_row,
            rsi_row,
            z_row,
        ]
        #: Keys match `quant_metrics_table` columns (note "Jensen"/"VaR"/"Z").
        self.specs = {
            "Sharpe": (sharpe_op, q_sharpe),
            "Sortino": (sortino_op, q_sortino),
            "Calmar": (calmar_op, q_calmar),
            "Beta": (beta_op, q_beta),
            "Treynor": (treynor_op, q_treynor),
            "Jensen": (jensen_op, q_jensen),
            "VaR": (var_op, q_var),
            "RSI": (rsi_op, q_rsi),
            "Z": (z_op, q_z),
        }
        self.view = W.VBox(
            [
                W.HBox(
                    [self.period_dd],
                    layout=W.Layout(width="100%", align_items="center"),
                ),
                *self.rows,
            ],
            layout=W.Layout(
                width="100%", padding="2px 4px", max_height="240px", overflow="auto"
            ),
        )

        # Quant metrics are candidate-independent, so the table is computed once
        # over the full ARP universe (keyed by period + the benchmark dropdowns)
        # and sliced per call — a threshold keystroke re-masks a cached table.
        # The Z column is memoized separately and cross-sectioned over the
        # current candidates, keeping its z-score candidate-relative.
        self._memo: dict = {}
        self._memo_arp_id: int | None = None

    @property
    def inputs(self) -> list[W.Widget]:
        """Every user-adjustable widget in this view, for the caller to observe."""
        out: list[W.Widget] = [self.period_dd, self.z_metric_dd, self.z_window_dd]
        out += list(self.bench_dd.values())
        for op, box in self.specs.values():
            out += [op, box]
        return out

    def clear(self) -> None:
        """Reset every row's operator *and* value.

        Both, so "Clear section" on Quantitative fully resets the row — matching
        the Multi-Strategy tab's clear behaviour (they had drifted).
        """
        for op, box in self.specs.values():
            op.value = "≥"
            box.value = ""

    def thresholds(self) -> dict[str, tuple[str, float]]:
        """Active filters as ``{metric: (operator, value)}``; blank = off."""
        out: dict[str, tuple[str, float]] = {}
        for name, (op, box) in self.specs.items():
            raw = (box.value or "").strip()
            if not raw:
                continue
            try:
                out[name] = (op.value, float(raw))
            except ValueError:
                continue
        return out

    @staticmethod
    def _universe_rets(state: DashboardState, arp: pd.DataFrame) -> pd.DataFrame:
        rets = getattr(state, "universe_rets", None)
        if rets is None or rets.empty:
            return daily_returns(arp)
        return rets

    def _full_table(self, state, arp, universe, years, beta_b, trey_b, jens_b):
        key = ("main", years, beta_b, trey_b, jens_b)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        rets = self._universe_rets(state, arp)
        qt = quant_metrics_table(arp, None, years, returns=rets)
        # Beta / Treynor / Jensen carry their own (independent) benchmark
        # dropdowns, so they can't share one beta here; the whole table is
        # memoized instead, so this runs once per (period, benchmarks) config.
        qt["Beta"] = ann_beta(rets, universe.get(beta_b), years)
        qt["Treynor"] = treynor_ratio(rets, arp, universe.get(trey_b), years)
        qt["Jensen"] = jensen_alpha(rets, arp, universe.get(jens_b), years)
        self._memo[key] = qt
        return qt

    def _z_raw(self, state, arp, universe, z_years, z_bench_name, z_metric):
        key = ("z", z_years, z_bench_name, z_metric)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        z_bench = universe.get(z_bench_name) if z_bench_name is not None else None
        zt = quant_metrics_table(
            arp, z_bench, z_years, returns=self._universe_rets(state, arp)
        )
        self._memo[key] = zt[z_metric]
        return zt[z_metric]

    def keep(self, candidates: pd.Index, state: DashboardState) -> pd.Index:
        """Narrow ``candidates`` to tickers passing every active threshold.

        The metric table is computed from the cached ARP prices, with Beta /
        Treynor / Jensen per their own benchmark dropdowns (from the full
        ``universe_prices`` cache), and the Z-Score column derived on demand over
        its own window. AND across thresholds. No thresholds / empty cache ->
        every candidate is kept. The per-ticker metrics are memoized over the
        whole catalog and sliced to the candidates here, so repeated filter
        changes re-mask a cached table rather than recomputing it.
        """
        thresholds = self.thresholds()
        arp = getattr(state, "arp_universe_prices", None)
        if not thresholds or arp is None or arp.empty:
            return candidates
        sub = arp.reindex(columns=list(candidates)).dropna(how="all", axis=1)
        if sub.shape[1] == 0:
            return candidates
        if self._memo_arp_id != id(arp):  # a Refresh replaced the cache frame
            self._memo.clear()
            self._memo_arp_id = id(arp)
        universe = getattr(state, "universe_prices", None)
        if universe is None:
            universe = pd.DataFrame()
        cand = sub.columns
        years = self.period_dd.value
        full = self._full_table(
            state,
            arp,
            universe,
            years,
            self.bench_dd["Beta"].value,
            self.bench_dd["Treynor"].value,
            self.bench_dd["Jensen"].value,
        )
        qt = full.loc[full.index.intersection(cand)].copy()
        if "Z" in thresholds:
            z_metric = self.z_metric_dd.value
            z_years = self.z_window_dd.value / TRADING_DAYS_PER_YEAR
            z_bench_name = (
                self.bench_dd[z_metric].value if z_metric in self.bench_dd else None
            )
            z_raw = self._z_raw(state, arp, universe, z_years, z_bench_name, z_metric)
            qt["Z"] = zscore_cross_section(z_raw.loc[z_raw.index.intersection(cand)])
        keep = qt.index
        for name, (op, value) in thresholds.items():
            col = qt[name]
            mask = col >= value if op == "≥" else col <= value
            keep = keep.intersection(qt.index[mask])
        return keep


class FilterPanel:
    """The **Filters** accordion: pill bar over a swappable value list.

    Composes a `CategoricalFilter` per schema dimension, the Characteristics
    widgets (launch-date range + currency), and a `QuantFilter`, and answers
    `matching(meta, state)`.

    The Single Strategy tab takes the default (`build_root=True`) and drops
    `root` straight in. The Multi-Strategy tab composes the pieces itself — it
    passes its **Refresh prices** button as `leading_actions` (prepended to the
    action row), a `right_panel_layout` (its 60%/bordered box), and
    `build_root=False`, then mounts `right_panel` beside its Strategies picker.
    """

    def __init__(
        self,
        meta: pd.DataFrame,
        *,
        leading_actions: tuple[W.Widget, ...] = (),
        right_panel_layout: W.Layout | None = None,
        build_root: bool = True,
        registry: BenchmarkRegistry | None = None,
    ) -> None:
        #: Field key -> its checkbox dimension, in pill-bar order.
        self.categoricals = {
            key: CategoricalFilter.build(key, unique_values(meta, key))
            for key in _pill_fields()
        }

        # --- Characteristics view (launch-date range + currency) -------------
        self.live_min = W.DatePicker(layout=W.Layout(width="160px"))
        self.live_max = W.DatePicker(layout=W.Layout(width="160px"))
        self.currency_dd = W.Dropdown(
            options=["All"] + unique_values(meta, "currency"),
            value="All",
            description="Currency",
            style={"description_width": "70px"},
            layout=W.Layout(width="240px"),
        )
        date_range_row = W.HBox(
            [
                self.live_min,
                W.HTML("<div style='padding:0 6px;font-size:16px;'>–</div>"),
                self.live_max,
            ],
            layout=W.Layout(width="100%", align_items="center"),
        )
        characteristics_view = W.VBox(
            [
                _section_label("Launch date"),
                date_range_row,
                _section_label("Currency"),
                self.currency_dd,
            ],
            layout=W.Layout(width="100%", padding="2px 4px"),
        )

        self.quant = QuantFilter(registry=registry)

        # --- Pill bar + swap container ---------------------------------------
        self._views: dict[str, W.Widget] = {
            **{key: cat.content for key, cat in self.categoricals.items()},
            _CHARACTERISTICS: characteristics_view,
            _QUANTITATIVE: self.quant.view,
        }
        self._buttons = {
            key: _make_tab_button(
                _view_label(key), active=(i == 0), width="auto", height="32px"
            )
            for i, key in enumerate(self._views)
        }
        self.header_row = W.HBox(
            list(self._buttons.values()),
            layout=W.Layout(width="100%", flex_flow="row wrap", margin="2px 0 6px 0"),
        )
        first_view = next(iter(self._views))
        self.content = W.Box(
            [self._views[first_view]],
            layout=W.Layout(width="100%", min_height="250px"),
        )
        #: The visible view, as a *key* rather than a caption — relabelling a
        #: dimension can't desync it from the buttons. Drives "Clear section".
        self.active_field = first_view
        for key, btn in self._buttons.items():
            btn.on_click(lambda _b, k=key: self.activate_filter(k))

        # --- Clear section / Clear all ---------------------------------------
        self.clear_section_btn = W.Button(
            description="Clear section",
            tooltip="Clear the active filter's selections",
            layout=W.Layout(width="auto"),
        )
        self.clear_all_btn = W.Button(
            description="Clear all",
            tooltip="Clear every filter",
            layout=W.Layout(width="auto"),
        )
        self.clear_section_btn.add_class("bbg-btn-secondary")
        self.clear_all_btn.add_class("bbg-btn-secondary")
        self.clear_section_btn.on_click(lambda _b=None: self.clear_section())
        self.clear_all_btn.on_click(lambda _b=None: self.clear_all())

        # Callers (Multi-Strategy) may prepend their own action (Refresh prices).
        action_row = W.HBox(
            [*leading_actions, self.clear_section_btn, self.clear_all_btn],
            layout=W.Layout(width="100%", margin="0 0 6px 0"),
        )
        self.right_panel = W.VBox(
            [action_row, self.header_row, self.content],
            layout=right_panel_layout or W.Layout(width="100%"),
        )
        self.root = (
            W.Accordion(
                children=[self.right_panel],
                titles=("Filters",),
                selected_index=0,
                layout=W.Layout(width="100%"),
            )
            if build_root
            else None
        )

    # --- views ----------------------------------------------------------------

    @property
    def pill_fields(self) -> tuple[str, ...]:
        """The categorical dimensions' field keys, in bar order."""
        return tuple(self.categoricals)

    @property
    def cat_checks(self) -> dict[str, list[W.Checkbox]]:
        """Field key -> its checkboxes, for callers and tests."""
        return {key: cat.checks for key, cat in self.categoricals.items()}

    @property
    def inputs(self) -> list[W.Widget]:
        """Every user-adjustable input, for the caller to ``observe``."""
        out: list[W.Widget] = []
        for cat in self.categoricals.values():
            out.extend(cat.checks)
        out += [self.live_min, self.live_max, self.currency_dd]
        out += self.quant.inputs
        return out

    def activate_filter(self, key: str) -> None:
        """Show view ``key`` and restyle the pills."""
        self.active_field = key
        for other, btn in self._buttons.items():
            _style_tab_button(btn, active=(other == key))
        self.content.children = (self._views[key],)

    # --- clearing -------------------------------------------------------------

    def _clear_characteristics(self) -> None:
        self.live_min.value = None
        self.live_max.value = None
        self.currency_dd.value = "All"

    def clear_section(self) -> None:
        """Clear only the visible view."""
        if self.active_field in self.categoricals:
            self.categoricals[self.active_field].clear()
        elif self.active_field == _CHARACTERISTICS:
            self._clear_characteristics()
        elif self.active_field == _QUANTITATIVE:
            self.quant.clear()

    def clear_all(self) -> None:
        """Clear every dimension, the Characteristics widgets, and the thresholds."""
        for cat in self.categoricals.values():
            cat.clear()
        self._clear_characteristics()
        self.quant.clear()

    # --- the reducer ----------------------------------------------------------

    def _currency(self) -> list[str]:
        return [] if self.currency_dd.value == "All" else [self.currency_dd.value]

    def apply_categorical(self, meta: pd.DataFrame) -> pd.DataFrame:
        """The metadata rows passing the categorical + Characteristics filters.

        The pure-metadata half of the filter (no prices / no quant), so callers
        that need the intermediate frame — e.g. to union back currently-selected
        rows before applying quant — can get it directly. Preserves ``meta`` row
        order.
        """
        return apply_filters(
            meta,
            {
                **{key: cat.selected() for key, cat in self.categoricals.items()},
                "currency": self._currency(),
            },
            live_date_min=self.live_min.value,
            live_date_max=self.live_max.value,
        )

    def matching(self, meta: pd.DataFrame, state: DashboardState) -> pd.Index:
        """Tickers passing the current filter state, as a ``pd.Index``.

        Composes `apply_categorical` (categorical + Characteristics) with the
        quant thresholds via the cached prices on ``state``. Preserves ``meta``
        row order.
        """
        filtered = self.apply_categorical(meta)
        keep = self.quant.keep(pd.Index(filtered["ticker"]), state)
        return pd.Index(filtered.loc[filtered["ticker"].isin(keep), "ticker"])


def make_filter_panel(
    meta: pd.DataFrame,
    *,
    leading_actions: tuple[W.Widget, ...] = (),
    right_panel_layout: W.Layout | None = None,
    build_root: bool = True,
    registry: BenchmarkRegistry | None = None,
) -> FilterPanel:
    """Build the reusable filter panel — a thin constructor wrapper.

    Kept so both tabs' call sites read the same as before `FilterPanel` existed.
    """
    return FilterPanel(
        meta,
        leading_actions=leading_actions,
        right_panel_layout=right_panel_layout,
        build_root=build_root,
        registry=registry,
    )
