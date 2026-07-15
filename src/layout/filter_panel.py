"""A reusable catalog-filter panel (v0.9.12).

Lifts the Multi-Strategy tab's filter UI into a self-contained factory so the
Single Strategy tab can reuse the same look and behaviour: a **"Filters"**
accordion whose right panel is a pill bar (Asset Class / Category / Theme /
Return Type / Characteristics / Quantitative) over a swappable value-list, plus
**Clear section** / **Clear all** buttons. The four categorical dimensions are
checkbox groups; **Characteristics** is a launch-date range + a Currency
dropdown; **Quantitative** is the nine per-metric ``≥`` / ``≤`` threshold rows
(Sharpe / Sortino / Calmar / Beta / Treynor / Jensen / VaR / RSI / Z-Score),
mirroring the Multi-Strategy panel exactly (same widgets, same `_quant_keep`
logic).

Unlike the Multi-Strategy panel this factory is **selection-agnostic**: it only
answers "which tickers match the current filter state" via ``matching(meta,
state)``; the caller decides what to do with the result (the Single Strategy tab
narrows its single-select picker and re-renders **live** on every input change —
there is no Refresh-prices button). Every user-adjustable input is exposed in
``.inputs`` so the caller can ``observe(...)`` them; the Clear buttons are wired
internally and simply reset those inputs, which fires the caller's observers.

No BQL and no new runtime deps: the quant threshold filter reads the already
fetched ``state.arp_universe_prices`` / ``state.universe_prices`` caches, exactly
like the Multi-Strategy ``_quant_keep``.
"""

from __future__ import annotations

from types import SimpleNamespace

import ipywidgets as W
import pandas as pd

from ..config import (
    BENCHMARK_TICKERS,
    DEFAULT_BENCHMARK,
    HALF_YEAR_WINDOW,
    MONTH_WINDOW,
    QUARTER_WINDOW,
    TRADING_DAYS_PER_YEAR,
    WEEK_WINDOW,
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
from .chrome import _make_tab_button, _style_tab_button
from .filters import _checkbox_group, _q_row, _section_label

# Pill labels, in bar order. The four categorical dimensions map to a metadata
# column; Characteristics / Quantitative are special views built below.
_CATEGORICAL: tuple[tuple[str, str], ...] = (
    ("Asset Class", "asset_class"),
    ("Category", "category"),
    ("Theme", "theme"),
    ("Return Type", "return_type"),
)


def make_filter_panel(meta: pd.DataFrame) -> SimpleNamespace:
    """Build the reusable filter accordion and its ``matching`` reducer.

    Returns a ``SimpleNamespace`` with:

    - ``root`` — the "Filters" ``Accordion`` widget to drop into a tab.
    - ``inputs`` — every user-adjustable input widget (checkboxes, date pickers,
      currency + quant dropdowns, quant operator/value boxes) for the caller to
      ``observe(..., names="value")``.
    - ``matching(meta, state)`` — the tickers passing the current filter state,
      as a ``pd.Index`` (categorical + characteristics via ``apply_filters``,
      then the quant thresholds via the cached prices on ``state``).
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
        return W.Dropdown(
            options=BENCHMARK_TICKERS,
            value=DEFAULT_BENCHMARK,
            layout=W.Layout(width="200px"),
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
        options=[
            ("1W", WEEK_WINDOW),
            ("1M", MONTH_WINDOW),
            ("3M", QUARTER_WINDOW),
            ("6M", HALF_YEAR_WINDOW),
        ],
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
    action_row = W.HBox(
        [clear_section_btn, clear_all_btn],
        layout=W.Layout(width="100%", margin="0 0 6px 0"),
    )

    right_panel = W.VBox(
        [action_row, filter_header_row, filter_content],
        layout=W.Layout(width="100%"),
    )
    filters_accordion = W.Accordion(
        children=[right_panel],
        titles=("Filters",),
        selected_index=0,
        layout=W.Layout(width="100%"),
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

    def _quant_keep(candidates: pd.Index, state: object) -> pd.Index:
        """Narrow ``candidates`` to tickers passing every active quant threshold.

        Mirrors the Multi-Strategy ``_quant_keep``: the metric table is computed
        from the cached ARP prices, with Beta / Treynor / Jensen overwritten per
        their own benchmark dropdowns (from the full ``universe_prices`` cache),
        and the Z-Score column derived on demand over its own window. AND across
        thresholds. No thresholds / empty cache → every candidate is kept.
        """
        thresholds = _quant_thresholds()
        arp = getattr(state, "arp_universe_prices", None)
        if not thresholds or arp is None or arp.empty:
            return candidates
        prices = arp.reindex(columns=candidates).dropna(how="all", axis=1)
        if prices.shape[1] == 0:
            return candidates
        universe = getattr(state, "universe_prices", None)
        if universe is None:
            universe = pd.DataFrame()
        years = quant.period_dd.value
        rets = daily_returns(prices)
        qt = quant_metrics_table(prices, None, years, returns=rets)
        qt["Beta"] = ann_beta(rets, universe.get(quant.bench_dd["Beta"].value), years)
        qt["Treynor"] = treynor_ratio(
            rets, prices, universe.get(quant.bench_dd["Treynor"].value), years
        )
        qt["Jensen"] = jensen_alpha(
            rets, prices, universe.get(quant.bench_dd["Jensen"].value), years
        )
        if "Z" in thresholds:
            z_metric = quant.z_metric_dd.value
            z_years = quant.z_window_dd.value / TRADING_DAYS_PER_YEAR
            z_bench = (
                universe.get(quant.bench_dd[z_metric].value)
                if z_metric in quant.bench_dd
                else None
            )
            zt = quant_metrics_table(prices, z_bench, z_years, returns=rets)
            qt["Z"] = zscore_cross_section(zt[z_metric])
        keep = qt.index
        for name, (op, value) in thresholds.items():
            col = qt[name]
            mask = col >= value if op == "≥" else col <= value
            keep = keep.intersection(qt.index[mask])
        return keep

    def matching(meta: pd.DataFrame, state: object) -> pd.Index:
        """Tickers passing the current filter state, as a ``pd.Index``.

        Applies the categorical + Characteristics filters via ``apply_filters``,
        then the quant thresholds via the cached prices on ``state``. Preserves
        ``meta`` row order.
        """
        filtered = apply_filters(
            meta,
            asset_classes=cat_widgets["asset_class"].get(),
            categories=cat_widgets["category"].get(),
            themes=cat_widgets["theme"].get(),
            return_types=cat_widgets["return_type"].get(),
            currencies=currency_get(),
            live_date_min=live_min.value,
            live_date_max=live_max.value,
        )
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
        inputs=inputs,
        matching=matching,
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
