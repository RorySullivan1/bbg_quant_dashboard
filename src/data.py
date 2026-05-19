import json
from pathlib import Path

import pandas as pd

from .config import DATA_PATH

META_COLUMNS = [
    "ticker",
    "name",
    "asset_class",
    "category",
    "family",
    "theme",
    "live_date",
]


def load_metadata(path: Path | str = DATA_PATH) -> pd.DataFrame:
    with open(path) as f:
        records = json.load(f)
    df = pd.DataFrame.from_records(records, columns=META_COLUMNS)
    df["live_date"] = pd.to_datetime(df["live_date"])
    return df


def unique_values(df: pd.DataFrame, column: str) -> list[str]:
    return sorted(df[column].dropna().unique().tolist())


def apply_filters(
    df: pd.DataFrame,
    asset_classes: list[str] | None = None,
    categories: list[str] | None = None,
    families: list[str] | None = None,
    themes: list[str] | None = None,
    live_date_min: pd.Timestamp | None = None,
    live_date_max: pd.Timestamp | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if asset_classes:
        mask &= df["asset_class"].isin(asset_classes)
    if categories:
        mask &= df["category"].isin(categories)
    if families:
        mask &= df["family"].isin(families)
    if themes:
        mask &= df["theme"].isin(themes)
    if live_date_min is not None:
        mask &= df["live_date"] >= pd.Timestamp(live_date_min)
    if live_date_max is not None:
        mask &= df["live_date"] <= pd.Timestamp(live_date_max)
    return df.loc[mask].reset_index(drop=True)
