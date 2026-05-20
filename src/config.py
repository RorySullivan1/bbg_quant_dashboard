from pathlib import Path

LOOKBACK_YEARS = 5
NEW_LAUNCH_DAYS = 90
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indexdb.json"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"
