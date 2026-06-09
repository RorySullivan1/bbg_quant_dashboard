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

# Short metric windows (trading days) for the v0.7.0 Platform z-score views.
# The treemap sizes by z(6M Sharpe, lookback) and colors by z(1W Sharpe,
# lookback); the grid z-score column offers 1M / 3M / 6M as the short window.
WEEK_WINDOW = 5  # ~1 week  (treemap color window)
MONTH_WINDOW = 21  # ~1 month
QUARTER_WINDOW = 63  # ~3 months
HALF_YEAR_WINDOW = 126  # ~6 months (treemap size window)

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
