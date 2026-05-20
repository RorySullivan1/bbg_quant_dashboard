from pathlib import Path

LOOKBACK_YEARS = 5
NEW_LAUNCH_DAYS = 90
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)
# Cap the up-front universe fetch so we don't ask BQL for 70 years of daily
# data on indices with very old live dates. SI metrics are computed over
# whatever range we successfully fetch.
MAX_UNIVERSE_LOOKBACK_YEARS = 20

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indexdb.json"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"
