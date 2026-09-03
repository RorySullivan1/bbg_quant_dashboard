"""Tests for the metadata loader (`src/data.py`).

Covers the v0.9.0 `description` field: it is exposed by `load_metadata` and is
NA-safe (padded) when a record omits the key.
"""

from __future__ import annotations

import json

import pandas as pd
from src.data import COLUMN_MAP, load_metadata


def test_description_in_column_map():
    """The v0.9.0 `Description` -> `description` mapping is registered."""
    assert COLUMN_MAP.get("Description") == "description"


def test_load_metadata_exposes_description():
    """The real catalog loads with a populated `description` column."""
    meta = load_metadata()
    assert "description" in meta.columns
    # Every shipped record carries a (placeholder) description today.
    assert meta["description"].notna().all()


def test_description_is_na_safe_when_missing(tmp_path):
    """A record without a `Description` key pads to NA rather than failing."""
    raw = {
        "SPX": {
            "Name": "S&P 500",
            "AssetClass": "Equity",
            "LiveDate": "1957-03-04",
            # no "Description" key
        }
    }
    path = tmp_path / "indexdb.json"
    path.write_text(json.dumps(raw))

    meta = load_metadata(path)
    assert "description" in meta.columns
    assert pd.isna(meta.loc[0, "description"])
