from pathlib import Path

LOOKBACK_YEARS = 5
NEW_LAUNCH_DAYS = 30
# Trailing window (trading days) for the v0.8.0 monthly "Market Superlatives"
# board — ~1 month. The superlative cards are computed whole-catalog over this
# window from the already-fetched prices (no extra BQL call).
SUPERLATIVE_WINDOW_DAYS = 21
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)

# Short metric windows (trading days) for the Platform z-score views.
# The sunburst's Z-score control offers 1W / 1M / 3M / 6M (default 1W Sharpe);
# the all-catalog grid z-score column offers 1M / 3M / 6M.
WEEK_WINDOW = 5  # ~1 week  (sunburst default window)
MONTH_WINDOW = 21  # ~1 month
QUARTER_WINDOW = 63  # ~3 months
HALF_YEAR_WINDOW = 126  # ~6 months

# The shared 1W / 1M / 3M / 6M window option list (superlatives toggle, sunburst
# Z-score window, Quantitative Z-Score window) and the window-day → prose-label
# map for the highlights board title, so these aren't re-spelled at each widget.
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

# Price cache for the single startup BQL fetch. Two tiers: an in-memory
# session cache (checked first, so a read-only filesystem is never required)
# backed by a best-effort on-disk parquet cache keyed by the `end` date (one
# file per trading day). `CACHE_TTL_HOURS` bounds how stale a same-day disk
# cache can be before it's treated as a miss. If the parquet directory is
# unwritable, the disk tier is skipped and the in-memory cache carries the
# session (see `src/bql_client.py`).
CACHE_DIR = REPO_ROOT / "data" / ".cache"
CACHE_TTL_HOURS = 12

# The startup BQL fetch is issued in ticker batches rather than one whole-
# universe request: a single request for hundreds of tickers over a multi-year
# window risks BQL's per-request row / wall-clock limits, and a single
# unresolvable ticker would otherwise fail the entire load. Each batch is
# retried with exponential backoff and, if it still fails, degrades to NaN
# columns so the rest of the catalog still loads (see `src/bql_client.py`).
BQL_BATCH_SIZE = 100  # tickers per BQL request
BQL_MAX_RETRIES = 2  # extra attempts per batch after the first (so up to 3 tries)
BQL_RETRY_BACKOFF_S = 1.0  # base backoff; attempt n waits BACKOFF * 2**n seconds

# Solution values that make up the dashboard universe — compared
# case-insensitively against the metadata `solution` column. Covers Alternative
# Risk Premia (short "ARP" / long form, kept so the filter survives a future JSON
# rename) plus Smart Beta and Risk Management; plain "Beta" stays excluded.
# "risk management" is forward-compatible (no records carry it yet).
UNIVERSE_SOLUTION_VALUES = frozenset(
    {"arp", "alternative risk premia", "smart beta", "risk management"}
)
WEEKLY_COMMENTARY_PATH = REPO_ROOT / "data" / "weekly_commentary.html"
PERFORMANCE_DISCLAIMER_PATH = REPO_ROOT / "data" / "performance_disclaimer.html"
LEGAL_DISCLOSURE_PATH = REPO_ROOT / "data" / "legal_disclosure.html"
TEMPLATES_DIR = REPO_ROOT / "data" / "templates"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"

# Benchmarks fetched alongside the ARP universe in the single startup BQL
# call. Used by the Rolling Correlation and Rolling Beta tabs only — never
# shown in the all-catalog grid or the highlights cards.
BENCHMARK_TICKERS: list[str] = [
    "SPX Index",  # S&P 500
    "MXWO Index",  # MSCI World
    "LBUSTRUU Index",  # Bloomberg US Aggregate
    "BCOM Index",  # Bloomberg Commodity
    "BMADM64 Index",  # Bloomberg 60/40
    # Bloomberg systematic risk-premia / cross-asset strategy benchmarks.
    "BSLRP Index",  # Bloomberg systematic risk premia
    "BSLMARP Index",  # Bloomberg multi-asset risk premia
    "BSLXAC Index",  # Bloomberg cross-asset carry
    "BSLXACV Index",  # Bloomberg cross-asset carry/value
    "BSLXAV Index",  # Bloomberg cross-asset value
    "BSLXAT Index",  # Bloomberg cross-asset trend (also TREND_TICKER)
]
DEFAULT_BENCHMARK = "SPX Index"

# Factor proxies for the v0.7.0 Platform factor-beta scatter. Total-return
# index proxies that ride the *same* single startup fetch as the benchmarks
# (no second BQL call) and are excluded from the ARP-universe views exactly
# like the benchmarks. `bql_client` fetches only `px_last`, so the two
# "premia" are return spreads, not true excess-of-risk-free premia:
#   equity risk premium ≈ equity TR return − short-rate TR return
#   term premium        ≈ long-Treasury TR return − short-rate TR return
# The equity leg reuses SPX (already a benchmark); only the two rate/bond
# proxies below are *new* tickers, so `FACTOR_TICKERS` lists just those.
EQUITY_FACTOR_TICKER = "SPX Index"  # equity proxy (also in BENCHMARK_TICKERS)
LONG_TREASURY_TICKER = "LUTLTRUU Index"  # Bloomberg US Long Treasury TR
SHORT_RATE_TICKER = "LD12TRUU Index"  # Bloomberg US Treasury 1–3M Bills TR
# Trend factor (v0.7.1): the Bloomberg cross-asset trend index. The Platform
# factor scatter's 3D z-axis is each strategy's β to this index's *returns*
# directly (not a short-rate spread, unlike the two premia above).
TREND_TICKER = "BSLXAT Index"  # Bloomberg cross-asset trend
FACTOR_TICKERS: list[str] = [LONG_TREASURY_TICKER, SHORT_RATE_TICKER, TREND_TICKER]

# Regime indicators for the Platform "Regime Analysis" section. Like the
# benchmarks/factors, these ride the *single* startup fetch and are excluded
# from ARP-universe views (the `reindex(columns=meta["ticker"])` drops them).
# Each regime classifies the trailing days into buckets the catalog scatter is
# conditioned on:
#   - Volatility: fixed VIX-level buckets.
#   - Trend / Rate-level: terciles (low / middle / high thirds) of a
#     live-computed indicator series — see `src/stats/regime.py` + builder.
VIX_TICKER = "VIX Index"
# Regional risk-free overnight rates for the Rate-level regime (region dropdown).
RATE_LEVEL_TICKERS: list[tuple[str, str]] = [
    ("US (FEDL01)", "FEDL01 Index"),  # US fed funds effective rate
    ("EU (EONIA)", "EONIA Index"),  # euro overnight rate
    ("JP (MUTKCALM)", "MUTKCALM Index"),  # Japan call rate
]
REGIME_TICKERS: list[str] = [
    VIX_TICKER,
    *(t for _, t in RATE_LEVEL_TICKERS),
]

# Mock-price shapes for indicator tickers whose off-terminal series must be an
# absolute *level* (not a compounding price) so the regime buckets actually
# partition the mock. Maps ticker -> (mean, vol, lo, hi) for a clipped
# mean-reverting level — see `_mock_prices` in `src/bql_client.py`.
LEVEL_INDICATOR_MOCK: dict[str, tuple[float, float, float, float]] = {
    VIX_TICKER: (18.0, 1.5, 9.0, 60.0),  # VIX-like, hovers ~18
    **{t: (2.0, 0.10, 0.0, 8.0) for _, t in RATE_LEVEL_TICKERS},  # short rates
}

_REGIME_INF = float("inf")
# regime label -> spec. Two bucket *modes*:
#   - "level": fixed buckets over the indicator ticker's raw daily level, each a
#     half-open [low, high) range (±inf for the open ends).
#   - "*_tercile": the indicator series is computed live (see builder) and split
#     into low / middle / high thirds by its 1/3 & 2/3 quantiles.
# Tercile modes carry `bucket_labels` ((display, key) for the three thirds) and a
# `selector` list of (label, ticker) for a conditional indicator-source dropdown
# (benchmark for Trend, region for Rate-level); `autocorr_window` is the rolling
# window for the Trend benchmark-return autocorrelation.
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
        "selector": [(t.replace(" Index", ""), t) for t in BENCHMARK_TICKERS],
        "autocorr_window": 21,
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
