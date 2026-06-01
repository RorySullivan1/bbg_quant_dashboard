from pathlib import Path

LOOKBACK_YEARS = 5
NEW_LAUNCH_DAYS = 30
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indexdb.json"

# On-disk parquet cache for the single startup BQL fetch. Keyed by the
# `end` date (one file per trading day). `CACHE_TTL_HOURS` bounds how
# stale a same-day cache can be before it's treated as a miss.
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
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"

# Benchmarks fetched alongside the ARP universe in the single startup BQL
# call. Used by the Rolling Correlation and Rolling Beta tabs only — never
# shown in the all-catalog grid or the highlights cards.
BENCHMARK_TICKERS: list[str] = [
    "SPX Index",       # S&P 500
    "MXWO Index",      # MSCI World
    "LBUSTRUU Index",  # Bloomberg US Aggregate
    "BCOM Index",      # Bloomberg Commodity
    "BBG6040 Index",   # Bloomberg 60/40
]
DEFAULT_BENCHMARK = "SPX Index"
