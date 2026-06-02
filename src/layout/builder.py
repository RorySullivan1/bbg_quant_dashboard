from __future__ import annotations

import time
import traceback
from datetime import date
from types import SimpleNamespace

import ipywidgets as W
import pandas as pd

from ..bql_client import _cache_path, fetch_prices
from ..commentary import build_highlights
from ..config import (
    ARP_SOLUTION_VALUES,
    BENCHMARK_TICKERS,
    DEFAULT_BENCHMARK,
    LEGAL_DISCLOSURE_PATH,
    LOOKBACK_YEARS,
    PERFORMANCE_DISCLAIMER_PATH,
)
from ..data import apply_filters, load_metadata, unique_values
from ..stats import (
    ann_beta,
    corr_matrix,
    cum_perf,
    daily_returns,
    drawdown_series,
    excess_cum_return,
    jensen_alpha,
    perf_table,
    quant_metrics_table,
    regime_corr_matrix,
    return_distribution_stats,
    rolling_beta,
    rolling_correlation,
    rolling_sharpe_zscore,
    sharpe_zscore,
    treynor_ratio,
    universe_perf,
    zscore_cross_section,
)
from ..style import (
    Color,
    FontSize,
    StatusTone,
)
from .charts import (
    _update_drawdown,
    _update_heatmap,
    _update_line,
    _update_outperformance,
    _update_return_dist,
    _update_rolling_ref,
    _update_scatter,
    _update_sharpe_line,
)
from .chrome import (
    _banner,
    _make_tab_button,
    _render_status,
    _status_banner,
    _style_tab_button,
)
from .filters import _checkbox_group, _q_row, _section_label, _ticker_options
from .grids import (
    _perf_grid,
    _universe_grid,
    _update_perf_grid,
    _update_universe_grid,
)
from .html import (
    _load_disclaimer,
    _load_weekly_commentary,
    _render_error,
    _render_highlights,
    _render_weekly_commentary,
)
from .panes import _make_analysis_pane


def build_app(verbose: bool = True) -> W.VBox:
    t0 = time.perf_counter()

    def _log(msg: str) -> None:
        if verbose:
            print(f"[{time.perf_counter() - t0:6.2f}s] {msg}", flush=True)

    meta = load_metadata()
    meta = meta[
        meta["solution"].astype(str).str.lower().isin(ARP_SOLUTION_VALUES)
    ].reset_index(drop=True)
    _log(f"loaded metadata: {len(meta)} tickers")

    asset_content, asset_get, asset_checks = _checkbox_group(
        unique_values(meta, "asset_class")
    )
    cat_content, cat_get, cat_checks = _checkbox_group(unique_values(meta, "category"))
    theme_content, theme_get, theme_checks = _checkbox_group(
        unique_values(meta, "theme")
    )
    ret_content, ret_get, ret_checks = _checkbox_group(
        unique_values(meta, "return_type")
    )

    live_min = W.DatePicker(layout=W.Layout(width="160px"))
    live_max = W.DatePicker(layout=W.Layout(width="160px"))

    # Currency lives under Characteristics; "All" = no currency filter.
    currency_dd = W.Dropdown(
        options=["All"] + unique_values(meta, "currency"),
        value="All",
        description="Currency",
        style={"description_width": "70px"},
        layout=W.Layout(width="240px"),
    )

    def currency_get() -> list[str]:
        return [] if currency_dd.value == "All" else [currency_dd.value]

    # Quantitative filter — each metric row is [label] [≥/≤ dropdown] [value],
    # with an inline parameter dropdown where relevant (Beta → benchmark,
    # Z-Score → base metric). Ratios are computed from the already-fetched
    # prices (no new BQL). Value is a Text box parsed to float, so a blank box
    # means "no filter"; 0 stays a valid threshold.
    q_period = W.Dropdown(
        options=[("1Y", 1), ("3Y", 3), ("5Y", 5)],
        value=1,
        description="Period",
        style={"description_width": "55px"},
        layout=W.Layout(width="150px"),
    )

    def _bench_dd() -> W.Dropdown:
        return W.Dropdown(
            options=BENCHMARK_TICKERS,
            value=DEFAULT_BENCHMARK,
            layout=W.Layout(width="200px"),
        )

    # Each benchmark-based metric gets its own benchmark dropdown.
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
            [W.HTML("<div style='padding:0 6px;'>of</div>"), q_z_metric],
            layout=W.Layout(align_items="center"),
        ),
    )
    quant = SimpleNamespace(
        period_dd=q_period,
        z_metric_dd=q_z_metric,
        # Each benchmark-based metric carries its own benchmark dropdown.
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
        # metric name -> (operator dropdown, value box)
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

    search_w = W.Text(
        placeholder="Search ticker or name…",
        layout=W.Layout(width="100%"),
    )
    # The SelectMultiple fills 100% of a flex holder (built below) that grows to
    # the bottom of the left panel, which the parent HBox stretches to the
    # filter panel's height. A plain `flex` on the select itself isn't honored,
    # but `height="100%"` inside a grown holder is — so it reaches the bottom.
    ticker_w = W.SelectMultiple(
        options=_ticker_options(meta),
        value=tuple(meta["ticker"].head(5)),
        layout=W.Layout(width="100%", height="100%"),
    )

    apply_btn = W.Button(
        description="Refresh prices",
        layout=W.Layout(flex="1 1 auto"),
    )
    # Green so the primary refresh action stands out from the secondary clear
    # buttons. Colour comes from the centralized style token, not button_style.
    apply_btn.style.button_color = Color.GREEN_600
    apply_btn.style.text_color = Color.WHITE
    clear_section_btn = W.Button(
        description="Clear section",
        tooltip="Clear the active filter's selections",
        layout=W.Layout(width="auto"),
    )
    clear_all_btn = W.Button(
        description="Clear all",
        tooltip="Clear all filters and the search box",
        layout=W.Layout(width="auto"),
    )
    status_w = _status_banner()

    def _set_status(text: str, tone: StatusTone = StatusTone.INFO) -> None:
        status_w.value = _render_status(text, tone=tone)

    def _format_loaded(
        df: pd.DataFrame, source: str, elapsed: float
    ) -> tuple[str, StatusTone]:
        n_tickers = df.shape[1]
        n_days = df.shape[0]
        if source == "cache":
            mtime = _cache_path(today).stat().st_mtime
            stamp = time.strftime("%H:%M · %m-%d", time.localtime(mtime))
            return (
                f"Loaded {n_tickers} indices · {n_days} trading days from cache ({stamp})",
                StatusTone.SUCCESS,
            )
        src_label = "BQL" if source == "bql" else "mock prices"
        return (
            f"Loaded {n_tickers} indices · {n_days} trading days · "
            f"fetched from {src_label} in {elapsed:.1f}s",
            StatusTone.SUCCESS,
        )

    # Left: the strategies picker — search box above the dropdown.
    # Holder grows to fill the left panel's free vertical space; the dropdown
    # fills the holder, so it reaches the bottom of the container regardless of
    # the (stretched) panel height.
    ticker_holder = W.Box(
        [ticker_w],
        layout=W.Layout(
            width="100%",
            flex="1 1 auto",
            min_height="220px",
            display="flex",
        ),
    )
    left_panel = W.VBox(
        [_section_label("Strategies"), search_w, ticker_holder],
        layout=W.Layout(
            width="38%",
            padding="8px",
            border=f"1px solid {Color.SLATE_200}",
            display="flex",
            flex_flow="column",
        ),
    )

    # Right: filter panel — Refresh prices on top, then a pill header bar whose
    # buttons swap which filter dimension's values are shown below.
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

    quant_view = W.VBox(
        [
            W.HBox([q_period], layout=W.Layout(width="100%", align_items="center")),
            *quant.rows,
        ],
        layout=W.Layout(width="100%", padding="2px 4px"),
    )

    filter_views: dict[str, W.Widget] = {
        "Asset Class": asset_content,
        "Category": cat_content,
        "Theme": theme_content,
        "Return Type": ret_content,
        "Characteristics": characteristics_view,
        "Quantitative": quant_view,
    }
    filter_btns = {
        label: _make_tab_button(label, active=(i == 0), width="auto", height="32px")
        for i, label in enumerate(filter_views)
    }
    filter_header_row = W.HBox(
        list(filter_btns.values()),
        layout=W.Layout(
            width="100%",
            flex_flow="row wrap",
            margin="2px 0 6px 0",
        ),
    )
    filter_content = W.Box(
        [filter_views["Asset Class"]],
        layout=W.Layout(width="100%", min_height="250px"),
    )

    # The currently visible filter dimension — drives "Clear section".
    active_filter = ["Asset Class"]

    def _activate_filter(label: str) -> None:
        active_filter[0] = label
        for lbl, btn in filter_btns.items():
            _style_tab_button(btn, active=(lbl == label))
        filter_content.children = (filter_views[label],)

    for label, btn in filter_btns.items():
        btn.on_click(lambda _b, lbl=label: _activate_filter(lbl))

    # Maps each checkbox-based filter dimension to its checkboxes. The
    # Characteristics view clears its date range instead. Clearing a value
    # widget fires its `_on_filter_change` observer, so the dropdown re-narrows
    # automatically — no manual recompute needed.
    filter_checks = {
        "Asset Class": asset_checks,
        "Category": cat_checks,
        "Theme": theme_checks,
        "Return Type": ret_checks,
    }

    def _clear_quant() -> None:
        for op, box in quant.specs.values():
            box.value = ""
            op.value = "≥"

    def _clear_section(_b=None) -> None:
        label = active_filter[0]
        if label == "Characteristics":
            live_min.value = None
            live_max.value = None
            currency_dd.value = "All"
        elif label == "Quantitative":
            _clear_quant()
        else:
            for c in filter_checks[label]:
                c.value = False

    def _clear_all(_b=None) -> None:
        for checks in filter_checks.values():
            for c in checks:
                c.value = False
        live_min.value = None
        live_max.value = None
        currency_dd.value = "All"
        _clear_quant()
        search_w.value = ""

    clear_section_btn.on_click(_clear_section)
    clear_all_btn.on_click(_clear_all)

    action_row = W.HBox(
        [apply_btn, clear_section_btn, clear_all_btn],
        layout=W.Layout(width="100%", margin="0 0 6px 0"),
    )

    right_panel = W.VBox(
        [action_row, filter_header_row, filter_content],
        layout=W.Layout(
            width="60%",
            padding="8px",
            border=f"1px solid {Color.SLATE_200}",
        ),
    )
    filter_box = W.HBox(
        [left_panel, right_panel],
        layout=W.Layout(width="100%", align_items="stretch"),
    )
    # The whole filter UI — the Strategies multi-select on the left and the
    # filter options on the right — collapses under a "Filters" accordion,
    # expanded by default.
    filters_accordion = W.Accordion(
        children=[filter_box],
        titles=("Filters",),
        selected_index=0,
        layout=W.Layout(width="100%"),
    )

    weekly_w = W.HTML(
        _render_weekly_commentary(_load_weekly_commentary(), date.today())
    )
    highlights_w = W.HTML(_render_highlights([]))
    universe_grid = _universe_grid()

    pane_left = _make_analysis_pane("left")
    pane_right = _make_analysis_pane("right")
    analysis_pane_row = W.HBox(
        [pane_left.root, pane_right.root],
        layout=W.Layout(width="100%", align_items="stretch"),
    )

    selected_perf_grid = _perf_grid()
    selected_perf_header = W.HTML(
        f"<div style='font-weight:600;font-size:{FontSize.BODY};"
        "margin:8px 12px 4px 12px;'>"
        "Selected-strategy performance"
        "</div>"
    )
    selected_perf_section = W.VBox(
        [selected_perf_header, selected_perf_grid],
        layout=W.Layout(width="100%", padding="4px 0 8px 0"),
    )

    commentary_box = W.VBox(
        [weekly_w, highlights_w],
        layout=W.Layout(width="100%", padding="12px 16px"),
    )

    universe_header = W.HTML(
        f"<div style='font-weight:600;font-size:{FontSize.BODY};"
        "margin:8px 12px 4px 12px;'>"
        "All-catalog performance"
        "</div>"
    )
    platform_panel = W.VBox(
        [universe_header, universe_grid],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )
    selected_panel = W.VBox(
        [filters_accordion, selected_perf_section, analysis_pane_row],
        layout=W.Layout(width="100%", padding="4px 8px 12px 8px"),
    )

    platform_btn = _make_tab_button("Platform", active=True)
    selected_btn = _make_tab_button("Multi-Strategy Analysis", active=False)
    top_tab_bar = W.HBox(
        [platform_btn, selected_btn],
        layout=W.Layout(
            width="100%",
            padding="10px 16px 4px 16px",
            border_bottom=f"1px solid {Color.SLATE_200}",
        ),
    )
    top_tab_content = W.Box(
        [platform_panel],
        layout=W.Layout(width="100%"),
    )

    def _activate_tab(which: str) -> None:
        is_platform = which == "platform"
        _style_tab_button(platform_btn, active=is_platform)
        _style_tab_button(selected_btn, active=not is_platform)
        top_tab_content.children = (platform_panel if is_platform else selected_panel,)

    platform_btn.on_click(lambda _b: _activate_tab("platform"))
    selected_btn.on_click(lambda _b: _activate_tab("selected"))

    # Single BQL fetch at app-load time, bounded by LOOKBACK_YEARS. A wider
    # fetch (e.g. back to oldest live date) is too slow on the terminal — the
    # SI column in the all-catalog grid is therefore bounded by this window.
    today = date.today()
    universe_start = (pd.Timestamp(today) - pd.DateOffset(years=LOOKBACK_YEARS)).date()

    universe_prices: pd.DataFrame = pd.DataFrame()
    init_errors: list[str] = []
    # Benchmarks ride along on the single startup fetch so the Rolling
    # Correlation / Rolling Beta tabs can slice them from the same cache.
    # They are excluded from the ARP-universe grid and the highlights cards
    # via reindex(columns=meta["ticker"]).
    fetch_tickers = list(meta["ticker"]) + list(BENCHMARK_TICKERS)
    _set_status(
        f"Fetching prices for {len(fetch_tickers)} indices ({universe_start} → {today})…",
        tone=StatusTone.INFO,
    )
    t_fetch = time.perf_counter()
    try:
        universe_prices, fetch_source = fetch_prices(
            fetch_tickers, universe_start, today
        )
        fetch_elapsed = time.perf_counter() - t_fetch
        text, tone = _format_loaded(universe_prices, fetch_source, fetch_elapsed)
        _set_status(text, tone=tone)
    except Exception:
        _set_status("Load failed — see error below", tone=StatusTone.ERROR)
        init_errors.append(
            f"Universe fetch ({universe_start} → {today}) failed:\n"
            f"{traceback.format_exc()}"
        )

    if not universe_prices.empty:
        # ARP universe view of the cache — used for the all-catalog grid and
        # the whole-catalog highlights so benchmark columns never leak in.
        arp_universe_prices = universe_prices.reindex(columns=meta["ticker"])
        t_perf = time.perf_counter()
        try:
            up = universe_perf(arp_universe_prices)
            _log(f"universe_perf computed in {time.perf_counter() - t_perf:.2f}s")
            t_grid = time.perf_counter()
            _update_universe_grid(universe_grid, meta, up)
            _log(f"universe grid populated in {time.perf_counter() - t_grid:.2f}s")
        except Exception:
            init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
    else:
        arp_universe_prices = pd.DataFrame()

    def _quant_thresholds() -> dict[str, tuple[str, float]]:
        """Active quant filters as `{metric: (operator, value)}`; blank = off."""
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

    def _quant_keep(candidates: pd.Index) -> pd.Index:
        """Tickers (among `candidates`) passing the active ≥/≤ thresholds.

        Metrics are computed from the already-fetched ARP prices — no BQL. If
        the cache is empty or no thresholds are set, every candidate passes.
        """
        thresholds = _quant_thresholds()
        if not thresholds or arp_universe_prices.empty:
            return candidates
        prices = arp_universe_prices.reindex(columns=candidates).dropna(
            how="all", axis=1
        )
        if prices.shape[1] == 0:
            return candidates
        years = quant.period_dd.value
        # Non-benchmark metrics from the shared table; the benchmark-based ones
        # (Beta / Treynor / Jensen) are recomputed each against its own dropdown.
        qt = quant_metrics_table(prices, None, years)
        rets = daily_returns(prices)
        qt["Beta"] = ann_beta(
            rets, universe_prices.get(quant.bench_dd["Beta"].value), years
        )
        qt["Treynor"] = treynor_ratio(
            rets, prices, universe_prices.get(quant.bench_dd["Treynor"].value), years
        )
        qt["Jensen"] = jensen_alpha(
            rets, prices, universe_prices.get(quant.bench_dd["Jensen"].value), years
        )
        if "Z" in thresholds:
            qt["Z"] = zscore_cross_section(qt[quant.z_metric_dd.value])
        keep = qt.index
        for name, (op, value) in thresholds.items():
            col = qt[name]
            mask = col >= value if op == "≥" else col <= value
            keep = keep.intersection(qt.index[mask])
        return keep

    def _on_filter_change(_change=None):
        filtered = apply_filters(
            meta,
            asset_classes=asset_get(),
            categories=cat_get(),
            themes=theme_get(),
            return_types=ret_get(),
            currencies=currency_get(),
            live_date_min=live_min.value,
            live_date_max=live_max.value,
        )
        query = (search_w.value or "").strip().lower()
        if query:
            mask = filtered["ticker"].str.lower().str.contains(
                query, regex=False
            ) | filtered["name"].str.lower().str.contains(query, regex=False)
            visible = filtered.loc[mask]
        else:
            visible = filtered

        quant_keep = _quant_keep(pd.Index(visible["ticker"]))
        visible = visible.loc[visible["ticker"].isin(quant_keep)]

        selected = list(ticker_w.value)
        keep_selected = filtered.loc[filtered["ticker"].isin(selected)]
        combined = pd.concat([visible, keep_selected]).drop_duplicates(subset="ticker")
        combined = combined.sort_values("ticker").reset_index(drop=True)
        ticker_w.options = _ticker_options(combined)
        ticker_w.value = tuple(t for t in selected if t in combined["ticker"].values)

    for cb in (*asset_checks, *cat_checks, *theme_checks, *ret_checks):
        cb.observe(_on_filter_change, names="value")
    for w in (live_min, live_max, search_w, currency_dd):
        w.observe(_on_filter_change, names="value")
    quant_inputs = [q_period, q_z_metric, *quant.bench_dd.values()]
    for op, box in quant.specs.values():
        quant_inputs += [op, box]
    for w in quant_inputs:
        w.observe(_on_filter_change, names="value")

    def _clear_pane(pane: SimpleNamespace) -> None:
        _update_line(pane.line_fig, pd.DataFrame(), meta)
        _update_outperformance(
            pane.outperf_fig, pd.DataFrame(), meta, benchmark_label=""
        )
        _update_sharpe_line(pane.sharpe_fig, pd.DataFrame(), meta)
        _update_heatmap(pane.heat_fig, pd.DataFrame())
        _update_scatter(pane.scatter_fig, pd.DataFrame(), pd.DataFrame(), meta)
        _update_drawdown(pane.dd_fig, pd.DataFrame(), meta)
        _update_rolling_ref(
            pane.rcorr_fig,
            pd.DataFrame(),
            meta,
            title_prefix="Rolling Correlation",
            benchmark_label="",
        )
        _update_rolling_ref(
            pane.rbeta_fig,
            pd.DataFrame(),
            meta,
            title_prefix="Rolling Beta",
            benchmark_label="",
        )
        _update_return_dist(
            pane.retdist_fig,
            pane.retdist_stats_grid,
            pd.DataFrame(),
            pd.DataFrame(),
            meta,
        )

    def _render_pane(
        pane: SimpleNamespace,
        prep: SimpleNamespace,
        universe_window_start: pd.Timestamp,
        errors: list[str],
    ) -> None:
        _update_line(pane.line_fig, prep.perf, meta)
        _update_sharpe_line(pane.sharpe_fig, prep.sz_series, meta)
        _update_scatter(pane.scatter_fig, prep.sel_window, prep.rets, meta)
        _update_drawdown(pane.dd_fig, prep.dd, meta)
        _update_return_dist(
            pane.retdist_fig,
            pane.retdist_stats_grid,
            prep.rets,
            prep.rd_stats,
            meta,
        )

        # Correlation heatmap: optionally conditioned on a benchmark-return
        # regime, with the benchmark added to the matrix. Computed per-pane so
        # the two panes stay independent (like the rolling-corr/beta blocks).
        if pane.heat_regime_chk.value:
            hm_bench_ticker = pane.heat_dd.value
            try:
                hm_bench_prices = universe_prices.get(hm_bench_ticker)
                if hm_bench_prices is None or hm_bench_prices.dropna().empty:
                    raise ValueError(
                        f"No price data for benchmark {hm_bench_ticker!r}."
                    )
                hm_bench_window = hm_bench_prices.loc[
                    hm_bench_prices.index >= universe_window_start
                ]
                hm_bench_returns = daily_returns(hm_bench_window.to_frame()).iloc[:, 0]
                direction = "up" if pane.heat_dir.value == "Up" else "down"
                pct = pane.heat_pct.value / 100.0
                cm = regime_corr_matrix(
                    prep.rets,
                    hm_bench_returns,
                    pct,
                    direction=direction,
                    include_benchmark=True,
                )
                tail_lbl = "worst" if direction == "down" else "best"
                title = (
                    f"Correlation — {hm_bench_ticker} {tail_lbl} "
                    f"{pane.heat_pct.value}% days ({LOOKBACK_YEARS}Y)"
                )
                _update_heatmap(pane.heat_fig, cm, title=title)
            except Exception:
                errors.append(traceback.format_exc())
                _update_heatmap(pane.heat_fig, pd.DataFrame())
        else:
            _update_heatmap(
                pane.heat_fig,
                prep.cm,
                title=f"Correlation — {LOOKBACK_YEARS}Y daily returns",
            )

        rc_bench_ticker = pane.rcorr_dd.value
        try:
            rc_bench_prices = universe_prices.get(rc_bench_ticker)
            if rc_bench_prices is None or rc_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {rc_bench_ticker!r}.")
            rc_bench_window = rc_bench_prices.loc[
                rc_bench_prices.index >= universe_window_start
            ]
            rc_bench_returns = daily_returns(rc_bench_window.to_frame()).iloc[:, 0]
            rc = rolling_correlation(prep.rets, rc_bench_returns)
            _update_rolling_ref(
                pane.rcorr_fig,
                rc,
                meta,
                title_prefix="Rolling Correlation",
                benchmark_label=rc_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

        rb_bench_ticker = pane.rbeta_dd.value
        try:
            rb_bench_prices = universe_prices.get(rb_bench_ticker)
            if rb_bench_prices is None or rb_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {rb_bench_ticker!r}.")
            rb_bench_window = rb_bench_prices.loc[
                rb_bench_prices.index >= universe_window_start
            ]
            rb_bench_returns = daily_returns(rb_bench_window.to_frame()).iloc[:, 0]
            rb = rolling_beta(prep.rets, rb_bench_returns)
            _update_rolling_ref(
                pane.rbeta_fig,
                rb,
                meta,
                title_prefix="Rolling Beta",
                benchmark_label=rb_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

        # Outperformance: cumulative excess return vs the benchmark (prices,
        # not returns — every strategy series starts at 0).
        op_bench_ticker = pane.outperf_dd.value
        try:
            op_bench_prices = universe_prices.get(op_bench_ticker)
            if op_bench_prices is None or op_bench_prices.dropna().empty:
                raise ValueError(f"No price data for benchmark {op_bench_ticker!r}.")
            op_bench_window = op_bench_prices.loc[
                op_bench_prices.index >= universe_window_start
            ]
            oc = excess_cum_return(prep.sel_window, op_bench_window)
            _update_outperformance(
                pane.outperf_fig,
                oc,
                meta,
                benchmark_label=op_bench_ticker,
            )
        except Exception:
            errors.append(traceback.format_exc())

    def _recompute(_btn=None):
        highlights_html = ""
        # Surface any errors from the initial universe fetch so the user can
        # see what actually went wrong, not just the downstream "cache empty".
        for err in init_errors:
            highlights_html += _render_error(err)
        # Highlights are always whole-catalog (ARP only), regardless of selection.
        universe_window_start = pd.Timestamp(today) - pd.DateOffset(
            years=LOOKBACK_YEARS
        )
        try:
            if not arp_universe_prices.empty:
                universe_window = arp_universe_prices.loc[
                    arp_universe_prices.index >= universe_window_start
                ]
                if not universe_window.empty:
                    universe_rets = daily_returns(universe_window)
                    universe_sz = sharpe_zscore(universe_rets)
                    cards = build_highlights(
                        meta, universe_window, universe_rets, universe_sz
                    )
                    highlights_html += _render_highlights(cards)
        except Exception:
            highlights_html += _render_error(traceback.format_exc())

        pane_errors: list[str] = []
        try:
            tickers = list(ticker_w.value)
            if len(tickers) < 1:
                _update_perf_grid(selected_perf_grid, pd.DataFrame(), meta)
                _clear_pane(pane_left)
                _clear_pane(pane_right)
            elif universe_prices.empty:
                pane_errors.append(
                    "Universe price cache is empty — initial BQL fetch returned no rows."
                )
                _update_perf_grid(selected_perf_grid, pd.DataFrame(), meta)
                _clear_pane(pane_left)
                _clear_pane(pane_right)
            else:
                sel_full = universe_prices.reindex(columns=tickers)
                sel_window = sel_full.loc[sel_full.index >= universe_window_start]
                if sel_window.dropna(how="all").empty:
                    pane_errors.append(
                        f"No price data in the {LOOKBACK_YEARS}Y window for: {tickers}."
                    )
                    _update_perf_grid(selected_perf_grid, pd.DataFrame(), meta)
                    _clear_pane(pane_left)
                    _clear_pane(pane_right)
                else:
                    prep = SimpleNamespace(
                        sel_window=sel_window,
                        rets=daily_returns(sel_window),
                        perf=cum_perf(sel_window),
                        pt=perf_table(sel_window),
                        dd=drawdown_series(sel_window),
                    )
                    prep.sz_series = rolling_sharpe_zscore(prep.rets)
                    prep.cm = corr_matrix(prep.rets)
                    prep.rd_stats = return_distribution_stats(prep.rets)
                    _update_perf_grid(selected_perf_grid, prep.pt, meta)
                    _render_pane(pane_left, prep, universe_window_start, pane_errors)
                    _render_pane(pane_right, prep, universe_window_start, pane_errors)
        except Exception:
            pane_errors.append(traceback.format_exc())

        for err in pane_errors:
            highlights_html += _render_error(err)

        highlights_w.value = highlights_html or _render_highlights([])

    def _refresh_prices(_btn=None):
        nonlocal universe_prices, arp_universe_prices
        _set_status(
            f"Fetching prices for {len(fetch_tickers)} indices ({universe_start} → {today})…",
            tone=StatusTone.INFO,
        )
        t_refresh = time.perf_counter()
        try:
            universe_prices, source = fetch_prices(
                fetch_tickers, universe_start, today, use_cache=False
            )
        except Exception:
            _set_status("Load failed — see error below", tone=StatusTone.ERROR)
            init_errors.append(
                f"Universe refresh ({universe_start} → {today}) failed:\n"
                f"{traceback.format_exc()}"
            )
            _recompute()
            return
        elapsed = time.perf_counter() - t_refresh
        arp_universe_prices = universe_prices.reindex(columns=meta["ticker"])
        try:
            _update_universe_grid(
                universe_grid, meta, universe_perf(arp_universe_prices)
            )
        except Exception:
            init_errors.append(
                f"universe_perf computation failed:\n{traceback.format_exc()}"
            )
        text, tone = _format_loaded(universe_prices, source, elapsed)
        _set_status(text, tone=tone)
        _recompute()

    apply_btn.on_click(_refresh_prices)

    perf_disclaimer_w = W.HTML(
        _load_disclaimer(
            PERFORMANCE_DISCLAIMER_PATH,
            start_date=universe_start.isoformat(),
            end_date=today.isoformat(),
        ),
        layout=W.Layout(width="100%", padding="0 16px"),
    )
    legal_w = W.HTML(
        _load_disclaimer(LEGAL_DISCLOSURE_PATH),
        layout=W.Layout(width="100%", padding="0 16px 16px 16px"),
    )

    app = W.VBox(
        [
            _banner(),
            status_w,
            commentary_box,
            top_tab_bar,
            top_tab_content,
            perf_disclaimer_w,
            legal_w,
        ],
        layout=W.Layout(width="100%"),
    )

    t_initial = time.perf_counter()
    _recompute()
    _log(f"initial recompute (selected viz) in {time.perf_counter() - t_initial:.2f}s")
    _log(f"build_app TOTAL: {time.perf_counter() - t0:.2f}s")
    return app
