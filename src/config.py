from pathlib import Path

LOOKBACK_YEARS = 3
NEW_LAUNCH_DAYS = 90
SHARPE_WINDOW = 63
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indices.json"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"
