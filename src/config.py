from pathlib import Path

LOOKBACK_YEARS = 5
NEW_LAUNCH_DAYS = 90
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indexdb.json"

# Solution values that count as "Alternative Risk Premia" — compared
# case-insensitively against the metadata `solution` column. The dataset
# currently uses the short form "ARP"; the long form is kept here so the
# filter survives a future JSON rename.
ARP_SOLUTION_VALUES = frozenset({"arp", "alternative risk premia"})
WEEKLY_COMMENTARY_PATH = REPO_ROOT / "data" / "weekly_commentary.html"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"
