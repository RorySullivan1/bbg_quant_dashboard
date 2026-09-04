"""Tunable constants for the dashboard: windows, thresholds, paths, and tickers.

Values here are read at import by `src/stats/`, `src/layout/`, and
`src/bql_client.py`; nothing in this module computes or fetches.

Two conventions govern the ticker lists at the bottom of the file:

1. **They ride the single startup BQL fetch.** `BENCHMARK_TICKERS`,
   `FACTOR_TICKERS`, and `REGIME_TICKERS` are appended to the universe request
   rather than fetched separately, so adding a ticker costs no extra BQL call.
2. **They are excluded from ARP-universe views.** The all-catalog grid and the
   highlights cards reindex to the metadata tickers, which drops them; they
   surface only in the correlation, beta, factor, and regime views.

Because `bql_client` fetches only `px_last`, anything here described as a
"premium" is a total-return *spread*, not a true excess-of-risk-free premium.
"""

from pathlib import Path

LOOKBACK_YEARS = 5
NEW_LAUNCH_DAYS = 30
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)

#: Trailing window (trading days, ~1 month) for the monthly "Market
#: Superlatives" board, computed whole-catalog from the already-fetched prices.
SUPERLATIVE_WINDOW_DAYS = 21

#: Hard cap on the Multi-Strategy selection. Analysis over the selected set is
#: O(n²) in the number of picks, so the picker is bounded to keep it fast and
#: the heatmaps legible; a further pick is rejected with an error popup.
#: See `CheckboxMultiSelect(max_selected=...)`.
MAX_SELECTED_STRATEGIES = 25

# Short metric windows (trading days) for the Platform z-score views.
WEEK_WINDOW = 5
MONTH_WINDOW = 21
QUARTER_WINDOW = 63
HALF_YEAR_WINDOW = 126

#: Shared window options and day → label map, so the superlatives toggle, the
#: sunburst Z-score control, and the Quantitative Z-Score window agree without
#: re-spelling the list at each widget.
SHORT_WINDOW_OPTIONS: list[tuple[str, int]] = [
    ("1W", WEEK_WINDOW),
    ("1M", MONTH_WINDOW),
    ("3M", QUARTER_WINDOW),
    ("6M", HALF_YEAR_WINDOW),
]
WINDOW_LABELS: dict[int, str] = {
    WEEK_WINDOW: "Past Week",
    MONTH_WINDOW: "Past Month",
    QUARTER_WINDOW: "Past Quarter",
    HALF_YEAR_WINDOW: "Past 6 Months",
}

# Quantitative-filter defaults (Multi-Strategy "Quantitative" filter).
VAR_CONFIDENCE = 0.95  # historical daily VaR confidence level
RSI_WINDOW = 14  # Wilder RSI lookback in trading days

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indexdb.json"
WEEKLY_COMMENTARY_PATH = REPO_ROOT / "data" / "weekly_commentary.html"
PERFORMANCE_DISCLAIMER_PATH = REPO_ROOT / "data" / "performance_disclaimer.html"
LEGAL_DISCLOSURE_PATH = REPO_ROOT / "data" / "legal_disclosure.html"
TEMPLATES_DIR = REPO_ROOT / "data" / "templates"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"

#: On-disk parquet tier of the price cache, one file per `end` date.
CACHE_DIR = REPO_ROOT / "data" / ".cache"
#: How stale a same-day disk cache may be before it counts as a miss.
CACHE_TTL_HOURS = 12

#: Benchmarks the user added at runtime. A sibling of the catalog rather than a
#: file under `CACHE_DIR`: the cache is semantically deletable at any time and
#: user configuration is not. Gitignored, so one user's benchmarks are never
#: committed and shipped to everyone.
USER_BENCHMARKS_PATH = REPO_ROOT / "data" / "user_benchmarks.json"

#: Tickers per BQL request. The startup fetch is batched because a single
#: request for hundreds of tickers over a multi-year window risks BQL's
#: per-request row and wall-clock limits. Tune purely for throughput against
#: those limits: it is the per-ticker retry pass, not this size, that stops one
#: bad ticker blanking the load (batch-level isolation isolates nothing when the
#: universe fits in one batch).
BQL_BATCH_SIZE = 100
BQL_MAX_RETRIES = 2  # extra attempts per batch after the first (so up to 3 tries)
BQL_RETRY_BACKOFF_S = 1.0  # base backoff; attempt n waits BACKOFF * 2**n seconds

#: A user-added benchmark whose history starts more than this many days after
#: the lookback window opens is accepted but flagged — a partial series is
#: usable for correlation and beta, but the user should know the comparison does
#: not span the whole window rather than wondering why a chart starts late.
BENCHMARK_SHORT_HISTORY_DAYS = 30

#: Solution values making up the dashboard universe, compared case-insensitively
#: against the metadata `solution` column. Both spellings of Alternative Risk
#: Premia are kept so the filter survives a future JSON rename, and "risk
#: management" is forward-compatible (no records carry it yet). Plain "Beta"
#: stays excluded.
UNIVERSE_SOLUTION_VALUES = frozenset(
    {"arp", "alternative risk premia", "smart beta", "risk management"}
)

#: Curated benchmarks for the Rolling Correlation and Rolling Beta views.
BENCHMARK_TICKERS: list[str] = [
    "SPTR Index",  # S&P 500 Total Return
    "SPXFP Index",  # S&P 500 (equity factor-leg reference)
    "MXWO Index",  # MSCI World
    "LBUSTRUU Index",  # Bloomberg US Aggregate
    "BCOM Index",  # Bloomberg Commodity
    "BMADM64 Index",  # Bloomberg 60/40
    "BSLRP Index",  # Bloomberg systematic risk premia
    "BSLMARP Index",  # Bloomberg multi-asset risk premia
    "BSLXAC Index",  # Bloomberg cross-asset carry
    "BSLXACV Index",  # Bloomberg cross-asset carry/value
    "BSLXAV Index",  # Bloomberg cross-asset value
    "BSLXAT Index",  # Bloomberg cross-asset trend (also TREND_TICKER)
]
DEFAULT_BENCHMARK = "SPTR Index"

# Factor proxies for the Platform factor-beta scatter:
#   equity risk premium ≈ equity TR return − short-rate TR return
#   term premium        ≈ long-Treasury TR return − short-rate TR return
# The equity leg reuses a benchmark, so only the rate/bond proxies and the trend
# index are new tickers — hence FACTOR_TICKERS lists just those three.
EQUITY_FACTOR_TICKER = "SPXFP Index"  # equity proxy (also in BENCHMARK_TICKERS)
LONG_TREASURY_TICKER = "LUTLTRUU Index"  # Bloomberg US Long Treasury TR
SHORT_RATE_TICKER = "LD12TRUU Index"  # Bloomberg US Treasury 1–3M Bills TR
#: The scatter's 3D z-axis is each strategy's β to this index's returns
#: directly, not to a short-rate spread like the two premia above.
TREND_TICKER = "BSLXAT Index"  # Bloomberg cross-asset trend
FACTOR_TICKERS: list[str] = [LONG_TREASURY_TICKER, SHORT_RATE_TICKER, TREND_TICKER]

# Indicator tickers for the Platform "Regime Analysis" section.
VIX_TICKER = "VIX Index"
#: Regional risk-free overnight rates for the Rate-level regime's region dropdown.
RATE_LEVEL_TICKERS: list[tuple[str, str]] = [
    ("US (FEDL01)", "FEDL01 Index"),  # US fed funds effective rate
    ("EU (EONIA)", "EONIA Index"),  # euro overnight rate
    ("JP (MUTKCALM)", "MUTKCALM Index"),  # Japan call rate
]
REGIME_TICKERS: list[str] = [
    VIX_TICKER,
    *(t for _, t in RATE_LEVEL_TICKERS),
]

#: Mock shapes for indicator tickers whose off-terminal series must be an
#: absolute *level* rather than a compounding price, so the regime buckets
#: actually partition the mock. Maps ticker -> (mean, vol, lo, hi) for a clipped
#: mean-reverting level; see `_mock_prices` in `src/bql_client.py`.
LEVEL_INDICATOR_MOCK: dict[str, tuple[float, float, float, float]] = {
    VIX_TICKER: (18.0, 1.5, 9.0, 60.0),  # VIX-like, hovers ~18
    **{t: (2.0, 0.10, 0.0, 8.0) for _, t in RATE_LEVEL_TICKERS},  # short rates
}

_REGIME_INF = float("inf")
#: Regime label -> spec, in one of two bucket modes. "level" applies fixed
#: half-open [low, high) buckets to the indicator's raw daily level (±inf for
#: the open ends). "*_tercile" computes the indicator series live (see builder)
#: and splits it into thirds at its 1/3 and 2/3 quantiles, carrying
#: `bucket_labels` as (display, key) pairs.
#:
#: A tercile regime's indicator source is chosen by a dropdown, populated either
#: from a literal `selector` list of (label, ticker) or, via
#: `selector_source`, from the live benchmark registry at render time — a
#: benchmark added at runtime has to appear in the Trend picker too, so that
#: list cannot be frozen here at import. See
#: `platform._regime_selector_options`.
REGIME_SPECS: dict[str, dict] = {
    "Volatility": {
        "mode": "level",
        "ticker": VIX_TICKER,
        "buckets": [
            ("VIX < 15", -_REGIME_INF, 15.0),
            ("15 ≤ VIX < 25", 15.0, 25.0),
            ("VIX ≥ 25", 25.0, _REGIME_INF),
        ],
    },
    "Trend": {
        "mode": "autocorr_tercile",
        "selector_source": "benchmarks",
        "autocorr_window": 21,  # rolling window for benchmark-return autocorrelation
        "bucket_labels": [
            ("Low (mean-reverting)", "low"),
            ("Middle", "mid"),
            ("High (trending)", "high"),
        ],
    },
    "Rate-level": {
        "mode": "level_tercile",
        "selector": list(RATE_LEVEL_TICKERS),
        "bucket_labels": [
            ("Low rates", "low"),
            ("Middle", "mid"),
            ("High rates", "high"),
        ],
    },
}
