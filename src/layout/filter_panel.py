"""A reusable catalog-filter panel, shared by Multi-Strategy and Single Strategy.

A **Filters** accordion whose right panel is a pill bar (Asset Class /
Category / Theme / Return Type / Characteristics / Quantitative) over a
swappable value-list, plus **Clear section** and **Clear all** buttons. The
four categorical dimensions are checkbox groups; **Characteristics** is a
launch-date range and a currency dropdown; **Quantitative** is nine per-metric
``≥``/``≤`` threshold rows (Sharpe / Sortino / Calmar / Beta / Treynor /
Jensen / VaR / RSI / Z-Score).

The factory is **selection-agnostic**: it only answers "which tickers match the
current filter state" via ``matching(meta, state)`` and leaves the caller to
act on the result. Every user-adjustable input is exposed in ``.inputs`` for
the caller to ``observe(...)``; the Clear buttons are wired internally and
simply reset those inputs, which fires the caller's observers in turn.

The quant threshold filter reads the already-fetched price caches on
``state``, so the panel issues no BQL call.
"""

from __future__ import annotations

from types import SimpleNamespace

import ipywidgets as W
import pandas as pd

from ..config import (
    MONTH_WINDOW,
    SHORT_WINDOW_OPTIONS,
    TRADING_DAYS_PER_YEAR,
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

# Pill labels, in bar order. The four categorical dimensions map to a metadata
# column; Characteristics / Quantitative are special views built below.
_CATEGORICAL: tuple[tuple[str, str], ...] = (
    ("Asset Class", "asset_class"),
    ("Category", "category"),
    ("Theme", "theme"),
    ("Return Type", "return_type"),
)


def make_filter_panel(
    meta: pd.DataFrame,
    *,
    leading_actions: tuple[W.Widget, ...] = (),
    right_panel_layout: W.Layout | None = None,
    build_root: bool = True,
    registry: BenchmarkRegistry | None = None,
) -> SimpleNamespace:
    """Build the reusable filter panel and its ``matching`` reducer.

    The Single Strategy tab uses the default (``build_root=True``) and drops the
    returned ``root`` accordion straight in. The Multi-Strategy tab composes the
    pieces itself — it passes its **Refresh prices** button as ``leading_actions``
    (prepended to the action row), a ``right_panel_layout`` (its 60%/bordered
    box), and ``build_root=False``, then mounts ``right_panel`` beside its own
    Strategies picker.

    Returns a ``SimpleNamespace`` with:

    - ``root`` — the "Filters" ``Accordion`` (``None`` when ``build_root=False``).
    - ``right_panel`` / ``header_row`` / ``content`` — the composable view pieces
      (the action row + pill bar + swappable value list; the pill bar and the
      content box, for callers that build their own container).
    - ``inputs`` — every user-adjustable input widget (checkboxes, date pickers,
      currency + quant dropdowns, quant operator/value boxes) for the caller to
      ``observe(..., names="value")``.
    - ``apply_categorical(meta)`` — the metadata rows passing the categorical +
      Characteristics filters (a ``DataFrame``); ``quant_keep(candidates, state)``
      — the subset of ``candidates`` clearing the quant thresholds; and
      ``matching(meta, state)`` — the two composed (a ``pd.Index``).
    - the raw widget handles / getters (``asset_checks`` … ``quant``,
      ``currency_dd``, ``live_min`` / ``live_max``, ``clear_all_btn`` …) for
      tests and callers that need them.
    """
    # --- Categorical checkbox groups ------------------------------------------
    cat_widgets: dict[str, SimpleNamespace] = {}
    for _label, col in _CATEGORICAL:
        content, getter, checks = _checkbox_group(unique_values(meta, col))
        cat_widgets[col] = SimpleNamespace(content=content, get=getter, checks=checks)

    # --- Characteristics view (launch-date range + currency) ------------------
    live_min = W.DatePicker(layout=W.Layout(width="160px"))
    live_max = W.DatePicker(layout=W.Layout(width="160px"))
    currency_dd = W.Dropdown(
        options=["All"] + unique_values(meta, "currency"),
        value="All",
        description="Currency",
        style={"description_width": "70px"},
        layout=W.Layout(width="240px"),
    )

    def currency_get() -> list[str]:
        return [] if currency_dd.value == "All" else [currency_dd.value]

    date_range_row = W.HBox(
        [
            live_min,
            W.HTML("<div style='padding:0 6px;font-size:16px;'>–</div>"),
            live_max,
        ],
        layout=W.Layout(width="100%", align_items="center"),
    )
    characteristics_view = W.VBox(
        [
            _section_label("Launch date"),
            date_range_row,
            _section_label("Currency"),
            currency_dd,
        ],
        layout=W.Layout(width="100%", padding="2px 4px"),
    )

    # --- Quantitative view (per-metric ≥/≤ thresholds) ------------------------
    q_period = W.Dropdown(
        options=[("1Y", 1), ("3Y", 3), ("5Y", 5)],
        value=1,
        description="Period",
        style={"description_width": "70px"},
        layout=W.Layout(width="200px"),
    )

    def _bench_dd() -> W.Dropdown:
        # The shared benchmark-dropdown factory (panes); no label, narrower box.
        return _make_benchmark_dropdown(
            description="", width="200px", registry=registry
        )

    q_beta_bench = _bench_dd()
    q_treynor_bench = _bench_dd()
    q_jensen_bench = _bench_dd()
    q_z_metric = W.Dropdown(
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
    q_z_window = W.Dropdown(
        options=SHORT_WINDOW_OPTIONS,
        value=MONTH_WINDOW,
        layout=W.Layout(width="80px"),
    )

    sharpe_row, sharpe_op, q_sharpe = _q_row("Sharpe")
    sortino_row, sortino_op, q_sortino = _q_row("Sortino")
    calmar_row, calmar_op, q_calmar = _q_row("Calmar")
    beta_row, beta_op, q_beta = _q_row("Beta", trailing=q_beta_bench)
    treynor_row, treynor_op, q_treynor = _q_row("Treynor", trailing=q_treynor_bench)
    jensen_row, jensen_op, q_jensen = _q_row("Jensen α", trailing=q_jensen_bench)
    var_row, var_op, q_var = _q_row("VaR %")
    rsi_row, rsi_op, q_rsi = _q_row("RSI")
    z_row, z_op, q_z = _q_row(
        "Z-Score",
        trailing=W.HBox(
            [W.HTML("<div style='padding:0 6px;'>of</div>"), q_z_metric, q_z_window],
            layout=W.Layout(align_items="center"),
        ),
    )

    quant = SimpleNamespace(
        period_dd=q_period,
        z_metric_dd=q_z_metric,
        z_window_dd=q_z_window,
        bench_dd={
            "Beta": q_beta_bench,
            "Treynor": q_treynor_bench,
            "Jensen": q_jensen_bench,
        },
        rows=[
            sharpe_row,
            sortino_row,
            calmar_row,
            beta_row,
            treynor_row,
            jensen_row,
            var_row,
            rsi_row,
            z_row,
        ],
        # Keys match `quant_metrics_table` columns (note "Jensen"/"VaR"/"Z").
        specs={
            "Sharpe": (sharpe_op, q_sharpe),
            "Sortino": (sortino_op, q_sortino),
            "Calmar": (calmar_op, q_calmar),
            "Beta": (beta_op, q_beta),
            "Treynor": (treynor_op, q_treynor),
            "Jensen": (jensen_op, q_jensen),
            "VaR": (var_op, q_var),
            "RSI": (rsi_op, q_rsi),
            "Z": (z_op, q_z),
        },
    )
    quant_view = W.VBox(
        [
            W.HBox([q_period], layout=W.Layout(width="100%", align_items="center")),
            *quant.rows,
        ],
        layout=W.Layout(
            width="100%", padding="2px 4px", max_height="240px", overflow="auto"
        ),
    )

    # --- Pill bar + swap container --------------------------------------------
    filter_views: dict[str, W.Widget] = {
        "Asset Class": cat_widgets["asset_class"].content,
        "Category": cat_widgets["category"].content,
        "Theme": cat_widgets["theme"].content,
        "Return Type": cat_widgets["return_type"].content,
        "Characteristics": characteristics_view,
        "Quantitative": quant_view,
    }
    filter_btns = {
        label: _make_tab_button(label, active=(i == 0), width="auto", height="32px")
        for i, label in enumerate(filter_views)
    }
    filter_header_row = W.HBox(
        list(filter_btns.values()),
        layout=W.Layout(width="100%", flex_flow="row wrap", margin="2px 0 6px 0"),
    )
    filter_content = W.Box(
        [filter_views["Asset Class"]],
        layout=W.Layout(width="100%", min_height="250px"),
    )
    # The currently visible dimension drives "Clear section".
    active = SimpleNamespace(label="Asset Class")

    def _activate_filter(label: str) -> None:
        active.label = label
        for lbl, btn in filter_btns.items():
            _style_tab_button(btn, active=(lbl == label))
        filter_content.children = (filter_views[label],)

    for label, btn in filter_btns.items():
        btn.on_click(lambda _b, lbl=label: _activate_filter(lbl))

    # --- Clear section / Clear all --------------------------------------------
    def _clear_quant() -> None:
        # Reset both the operator (back to the ≥ default) and the value box, so
        # "Clear section" on Quantitative fully resets the row — matching the
        # Multi-Strategy tab's clear behaviour (they had drifted).
        for op, box in quant.specs.values():
            op.value = "≥"
            box.value = ""

    def _clear_characteristics() -> None:
        live_min.value = None
        live_max.value = None
        currency_dd.value = "All"

    def _clear_section(_b=None) -> None:
        label = active.label
        for lbl, col in _CATEGORICAL:
            if lbl == label:
                for cb in cat_widgets[col].checks:
                    cb.value = False
                return
        if label == "Characteristics":
            _clear_characteristics()
        elif label == "Quantitative":
            _clear_quant()

    def _clear_all(_b=None) -> None:
        for _label, col in _CATEGORICAL:
            for cb in cat_widgets[col].checks:
                cb.value = False
        _clear_characteristics()
        _clear_quant()

    clear_section_btn = W.Button(
        description="Clear section",
        tooltip="Clear the active filter's selections",
        layout=W.Layout(width="auto"),
    )
    clear_all_btn = W.Button(
        description="Clear all",
        tooltip="Clear every filter",
        layout=W.Layout(width="auto"),
    )
    clear_section_btn.add_class("bbg-btn-secondary")
    clear_all_btn.add_class("bbg-btn-secondary")
    clear_section_btn.on_click(_clear_section)
    clear_all_btn.on_click(_clear_all)
    # Callers (Multi-Strategy) may prepend their own action (Refresh prices).
    action_row = W.HBox(
        [*leading_actions, clear_section_btn, clear_all_btn],
        layout=W.Layout(width="100%", margin="0 0 6px 0"),
    )

    right_panel = W.VBox(
        [action_row, filter_header_row, filter_content],
        layout=right_panel_layout or W.Layout(width="100%"),
    )
    filters_accordion = (
        W.Accordion(
            children=[right_panel],
            titles=("Filters",),
            selected_index=0,
            layout=W.Layout(width="100%"),
        )
        if build_root
        else None
    )

    # --- Matching reducer (categorical + characteristics + quant) -------------
    def _quant_thresholds() -> dict[str, tuple[str, float]]:
        """Active quant filters as ``{metric: (operator, value)}``; blank = off."""
        out: dict[str, tuple[str, float]] = {}
        for name, (op, box) in quant.specs.items():
            raw = (box.value or "").strip()
            if not raw:
                continue
            try:
                out[name] = (op.value, float(raw))
            except ValueError:
                continue
        return out

    # Quant metrics are candidate-independent, so the table is computed once
    # over the full ARP universe (keyed by period + the benchmark dropdowns) and
    # sliced per call — a threshold keystroke re-masks a cached table. The Z
    # column is memoized separately and cross-sectioned over the current
    # candidates, keeping its z-score candidate-relative. Invalidated when a
    # Refresh replaces ``state.arp_universe_prices``.
    _quant_memo: dict = {}
    _quant_memo_arp: list = [None]

    def _quant_universe_rets(state: object, arp: pd.DataFrame) -> pd.DataFrame:
        rets = getattr(state, "universe_rets", None)
        if rets is None or rets.empty:
            return daily_returns(arp)
        return rets

    def _quant_full_table(state, arp, universe, years, beta_b, trey_b, jens_b):
        key = ("main", years, beta_b, trey_b, jens_b)
        cached = _quant_memo.get(key)
        if cached is not None:
            return cached
        rets = _quant_universe_rets(state, arp)
        qt = quant_metrics_table(arp, None, years, returns=rets)
        # Beta / Treynor / Jensen carry their own (independent) benchmark
        # dropdowns, so they can't share one beta here; the whole table is
        # memoized instead, so this runs once per (period, benchmarks) config.
        qt["Beta"] = ann_beta(rets, universe.get(beta_b), years)
        qt["Treynor"] = treynor_ratio(rets, arp, universe.get(trey_b), years)
        qt["Jensen"] = jensen_alpha(rets, arp, universe.get(jens_b), years)
        _quant_memo[key] = qt
        return qt

    def _quant_z_raw(state, arp, universe, z_years, z_bench_name, z_metric):
        key = ("z", z_years, z_bench_name, z_metric)
        cached = _quant_memo.get(key)
        if cached is not None:
            return cached
        z_bench = universe.get(z_bench_name) if z_bench_name is not None else None
        zt = quant_metrics_table(
            arp, z_bench, z_years, returns=_quant_universe_rets(state, arp)
        )
        _quant_memo[key] = zt[z_metric]
        return zt[z_metric]

    def _quant_keep(candidates: pd.Index, state: object) -> pd.Index:
        """Narrow ``candidates`` to tickers passing every active quant threshold.

        Mirrors the Multi-Strategy ``_quant_keep``: the metric table is computed
        from the cached ARP prices, with Beta / Treynor / Jensen per their own
        benchmark dropdowns (from the full ``universe_prices`` cache), and the
        Z-Score column derived on demand over its own window. AND across
        thresholds. No thresholds / empty cache → every candidate is kept. The
        per-ticker metrics are memoized over the whole catalog and sliced to the
        candidates here (see the memo above), so repeated filter changes re-mask
        a cached table rather than recomputing it.
        """
        thresholds = _quant_thresholds()
        arp = getattr(state, "arp_universe_prices", None)
        if not thresholds or arp is None or arp.empty:
            return candidates
        sub = arp.reindex(columns=list(candidates)).dropna(how="all", axis=1)
        if sub.shape[1] == 0:
            return candidates
        if _quant_memo_arp[0] != id(arp):  # a Refresh replaced the cache frame
            _quant_memo.clear()
            _quant_memo_arp[0] = id(arp)
        universe = getattr(state, "universe_prices", None)
        if universe is None:
            universe = pd.DataFrame()
        cand = sub.columns
        years = quant.period_dd.value
        full = _quant_full_table(
            state,
            arp,
            universe,
            years,
            quant.bench_dd["Beta"].value,
            quant.bench_dd["Treynor"].value,
            quant.bench_dd["Jensen"].value,
        )
        qt = full.loc[full.index.intersection(cand)].copy()
        if "Z" in thresholds:
            z_metric = quant.z_metric_dd.value
            z_years = quant.z_window_dd.value / TRADING_DAYS_PER_YEAR
            z_bench_name = (
                quant.bench_dd[z_metric].value if z_metric in quant.bench_dd else None
            )
            z_raw = _quant_z_raw(state, arp, universe, z_years, z_bench_name, z_metric)
            qt["Z"] = zscore_cross_section(z_raw.loc[z_raw.index.intersection(cand)])
        keep = qt.index
        for name, (op, value) in thresholds.items():
            col = qt[name]
            mask = col >= value if op == "≥" else col <= value
            keep = keep.intersection(qt.index[mask])
        return keep

    def apply_categorical(meta: pd.DataFrame) -> pd.DataFrame:
        """The metadata rows passing the categorical + Characteristics filters.

        The pure-metadata half of the filter (no prices / no quant), so callers
        that need the intermediate frame — e.g. to union back currently-selected
        rows before applying quant — can get it directly. Preserves ``meta`` row
        order.
        """
        return apply_filters(
            meta,
            asset_classes=cat_widgets["asset_class"].get(),
            categories=cat_widgets["category"].get(),
            themes=cat_widgets["theme"].get(),
            return_types=cat_widgets["return_type"].get(),
            currencies=currency_get(),
            live_date_min=live_min.value,
            live_date_max=live_max.value,
        )

    def matching(meta: pd.DataFrame, state: object) -> pd.Index:
        """Tickers passing the current filter state, as a ``pd.Index``.

        Composes ``apply_categorical`` (categorical + Characteristics) with the
        quant thresholds via the cached prices on ``state``. Preserves ``meta``
        row order.
        """
        filtered = apply_categorical(meta)
        keep = _quant_keep(pd.Index(filtered["ticker"]), state)
        return pd.Index(filtered.loc[filtered["ticker"].isin(keep), "ticker"])

    # Every user-adjustable input the caller observes for live narrowing.
    inputs: list[W.Widget] = []
    for _label, col in _CATEGORICAL:
        inputs.extend(cat_widgets[col].checks)
    inputs += [live_min, live_max, currency_dd, q_period, q_z_metric, q_z_window]
    inputs += [q_beta_bench, q_treynor_bench, q_jensen_bench]
    for _op, box in quant.specs.values():
        inputs += [_op, box]

    return SimpleNamespace(
        root=filters_accordion,
        right_panel=right_panel,
        header_row=filter_header_row,
        content=filter_content,
        inputs=inputs,
        matching=matching,
        apply_categorical=apply_categorical,
        quant_keep=_quant_keep,
        # Handles for tests / callers.
        asset_checks=cat_widgets["asset_class"].checks,
        cat_checks=cat_widgets["category"].checks,
        theme_checks=cat_widgets["theme"].checks,
        ret_checks=cat_widgets["return_type"].checks,
        currency_dd=currency_dd,
        live_min=live_min,
        live_max=live_max,
        quant=quant,
        clear_section_btn=clear_section_btn,
        clear_all_btn=clear_all_btn,
        activate_filter=_activate_filter,
    )
