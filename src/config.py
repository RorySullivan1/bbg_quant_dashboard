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

# Solution values that count as "Alternative Risk Premia" — compared
# case-insensitively against the metadata `solution` column. The dataset
# currently uses the short form "ARP"; the long form is kept here so the
# filter survives a future JSON rename.
ARP_SOLUTION_VALUES = frozenset({"arp", "alternative risk premia"})
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
    "BBG6040 Index",  # Bloomberg 60/40
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

# Regime indicators for the v0.8.5 Platform "Regime Analysis" section. Like the
# benchmarks/factors, these ride the *single* startup fetch and are excluded
# from ARP-universe views (the `reindex(columns=meta["ticker"])` drops them).
# Only the Volatility regime (VIX buckets) is wired this cycle; Trend /
# Liquidity / Rate-level are scaffolded (ticker=None) and leave the charts on
# the unconditioned all-days view until a later version supplies them.
VIX_TICKER = "VIX Index"
REGIME_TICKERS: list[str] = [VIX_TICKER]

# Tickers whose mock series must be an absolute *level* (not a compounding
# price) so the absolute buckets below actually partition the off-terminal
# mock — see `_mock_prices` in `src/bql_client.py`.
LEVEL_INDICATOR_TICKERS: frozenset[str] = frozenset({VIX_TICKER})

_REGIME_INF = float("inf")
# regime label -> {"ticker": indicator ticker or None, "buckets": [(label, low,
# high), ...]} over the indicator's daily level, each a half-open [low, high)
# range (±inf for the open ends). Populated only for Volatility this cycle; the
# scaffolded regimes carry no ticker and no buckets.
REGIME_SPECS: dict[str, dict] = {
    "Volatility": {
        "ticker": VIX_TICKER,
        "buckets": [
            ("VIX < 15", -_REGIME_INF, 15.0),
            ("15 ≤ VIX < 25", 15.0, 25.0),
            ("25 ≤ VIX < 35", 25.0, 35.0),
            ("VIX ≥ 35", 35.0, _REGIME_INF),
        ],
    },
    "Trend": {"ticker": None, "buckets": []},
    "Liquidity": {"ticker": None, "buckets": []},
    "Rate-level": {"ticker": None, "buckets": []},
}
