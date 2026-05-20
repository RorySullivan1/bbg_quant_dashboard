from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import DATA_PATH

# Map raw JSON column names (camel-case from indexdb.json) to internal snake_case.
COLUMN_MAP = {
    "Name": "name",
    "AssetClass": "asset_class",
    "IndexFamilyName": "category",
    "Theme": "theme",
    "Solution": "solution",
    "ReturnType": "return_type",
    "LiveDate": "live_date",
}

META_COLUMNS = ["ticker"] + list(COLUMN_MAP.values())


def load_metadata(path: Path | str = DATA_PATH) -> pd.DataFrame:
    """Load the index catalog from indexdb.json.

    The JSON is expected to be orient="index" — i.e. a dict keyed by the
    short ticker (without the " Index" suffix). We append " Index" so the
    resulting ticker is the BQL identifier.
    """
    with open(path) as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        df = pd.DataFrame.from_dict(raw, orient="index")
        df.index.name = "ticker_short"
        df = df.reset_index()
    elif isinstance(raw, list):
        df = pd.DataFrame.from_records(raw)
        if "ticker_short" not in df.columns and "ticker" in df.columns:
            df = df.rename(columns={"ticker": "ticker_short"})
    else:
        raise ValueError(f"Unsupported JSON top-level type: {type(raw)}")

    df = df.rename(columns=COLUMN_MAP)
    df["ticker"] = df["ticker_short"].astype(str).str.strip() + " Index"

    for col in COLUMN_MAP.values():
        if col not in df.columns:
            df[col] = pd.NA

    df["live_date"] = pd.to_datetime(df["live_date"], errors="coerce")
    return df[META_COLUMNS].reset_index(drop=True)


def unique_values(df: pd.DataFrame, column: str) -> list[str]:
    return sorted(df[column].dropna().astype(str).unique().tolist())


def apply_filters(
    df: pd.DataFrame,
    asset_classes: list[str] | None = None,
    categories: list[str] | None = None,
    themes: list[str] | None = None,
    solutions: list[str] | None = None,
    return_types: list[str] | None = None,
    live_date_min: pd.Timestamp | None = None,
    live_date_max: pd.Timestamp | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if asset_classes:
        mask &= df["asset_class"].isin(asset_classes)
    if categories:
        mask &= df["category"].isin(categories)
    if themes:
        mask &= df["theme"].isin(themes)
    if solutions:
        mask &= df["solution"].isin(solutions)
    if return_types:
        mask &= df["return_type"].isin(return_types)
    if live_date_min is not None:
        mask &= df["live_date"] >= pd.Timestamp(live_date_min)
    if live_date_max is not None:
        mask &= df["live_date"] <= pd.Timestamp(live_date_max)
    return df.loc[mask].reset_index(drop=True)
