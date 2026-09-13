"""Tests for the metadata loader (`src/data.py`).

Two concerns: the v0.9.0 `description` field (exposed, and NA-safe when a
record omits the key), and the v0.9.15 declarative catalog schema — alias
resolution, the warnings a non-conforming feed raises, and `apply_filters`
keyed by internal field name.
"""

from __future__ import annotations

import json
import warnings

import pandas as pd
import pytest
from src.config import (
    CATALOG_SCHEMA,
    CLASSIFICATION_TIERS,
    CatalogField,
    catalog_field,
    field_label,
    filterable_fields,
    tier_fields,
)
from src.data import META_COLUMNS, _rename_from_schema, apply_filters, load_metadata

#: The columns `load_metadata` produces, in order. Pinned so a schema edit that
#: adds, drops or reorders a field has to say so here. `family` and `category`
#: are the re-keyed tiers: before the re-key this list read `category`, `theme`
#: — the same two positions, which is exactly why a half-done rename would have
#: gone unnoticed.
_EXPECTED_META_COLUMNS = [
    "ticker",
    "name",
    "asset_class",
    "family",
    "category",
    "solution",
    "return_type",
    "live_date",
    "currency",
    "description",
]


def _write(tmp_path, raw: dict) -> str:
    path = tmp_path / "indexdb.json"
    path.write_text(json.dumps(raw))
    return path


# --- schema ---------------------------------------------------------------


def test_meta_columns_match_the_expected_order():
    assert META_COLUMNS == _EXPECTED_META_COLUMNS


def test_description_field_is_registered():
    """The v0.9.0 `Description` -> `description` mapping survives the refactor."""
    assert catalog_field("description").sources[0] == "Description"


def test_field_label_reads_the_schema():
    assert field_label("asset_class") == "Asset Class"
    assert field_label("return_type") == "Return Type"


def test_catalog_field_rejects_an_unknown_key():
    with pytest.raises(KeyError):
        catalog_field("not_a_field")


def test_tier_fields_are_ordered_top_to_leaf():
    assert tuple(f.key for f in tier_fields()) == CLASSIFICATION_TIERS
    assert all(f.role == "tier" for f in tier_fields())


def test_filterable_fields_exclude_dates_and_free_text():
    keys = {f.key for f in filterable_fields()}
    assert "live_date" not in keys  # role "date": has its own min/max arguments
    assert "description" not in keys and "name" not in keys  # role "text"
    assert {"asset_class", "family", "category", "solution"} <= keys


# --- alias resolution -----------------------------------------------------


def test_canonical_feed_warns_about_nothing():
    df = pd.DataFrame({f.sources[0]: ["x"] for f in CATALOG_SCHEMA})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        renamed = _rename_from_schema(df)
    assert list(renamed.columns) == [f.key for f in CATALOG_SCHEMA]


def test_legacy_alias_lands_in_the_right_column_with_one_warning(monkeypatch):
    """A field takes its first present alias; a non-canonical one warns once."""
    schema = (
        CatalogField("family", ("Family", "IndexFamilyName"), "Family", "tier"),
        CatalogField("name", ("Name",), "Name", "text"),
    )
    monkeypatch.setattr("src.data.CATALOG_SCHEMA", schema)

    legacy = pd.DataFrame({"IndexFamilyName": ["Carry"], "Name": ["A"]})
    with pytest.warns(UserWarning, match="legacy column names") as caught:
        renamed = _rename_from_schema(legacy)
    assert len(caught) == 1
    assert renamed["family"].tolist() == ["Carry"]

    canonical = pd.DataFrame({"Family": ["Carry"], "Name": ["A"]})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _rename_from_schema(canonical)["family"].tolist() == ["Carry"]


def test_canonical_wins_when_both_aliases_are_present(monkeypatch):
    schema = (CatalogField("family", ("Family", "IndexFamilyName"), "Family", "tier"),)
    monkeypatch.setattr("src.data.CATALOG_SCHEMA", schema)

    both = pd.DataFrame({"Family": ["new"], "IndexFamilyName": ["old"]})
    with pytest.warns(UserWarning, match="not in CATALOG_SCHEMA"):
        renamed = _rename_from_schema(both)
    assert renamed["family"].tolist() == ["new"]


def test_an_old_shape_feed_lands_each_tier_in_the_right_column(tmp_path):
    """The swap guard.

    The re-key is the one change in this epic that can ship wrong while every
    test still passes: the new external `Category` is the *old* `Theme`, and the
    old internal `category` was the *family*. Renaming the feed keys without the
    internal fields — or vice versa — silently transposes two dimensions, and
    every assertion that merely pins a string keeps passing because all the
    strings still exist. So assert the values, not the names: the family value
    must land in `family` and the category value in `category`.
    """
    old_shape = {
        "BSLXAC": {
            "Name": "Cross-Asset Carry",
            "AssetClass": "Multi-Asset",
            "IndexFamilyName": "Cross-Sectional Carry",  # → family
            "Theme": "Carry",  # → category
            "Solution": "Alternative Risk Premia",
            "ReturnType": "Excess",
            "Currency": "USD",
            "LiveDate": "2016-06-30",
            "Description": "x",
        }
    }
    with pytest.warns(UserWarning, match="legacy column names"):
        meta = load_metadata(_write(tmp_path, old_shape))

    row = meta.iloc[0]
    assert row["family"] == "Cross-Sectional Carry"
    assert row["category"] == "Carry"
    assert row["solution"] == "Alternative Risk Premia"


def test_the_shipped_catalog_is_new_shape_and_loads_silently():
    """`data/indexdb.json` carries no legacy keys, so loading warns about nothing."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        meta = load_metadata()
    assert {"family", "category", "solution"} <= set(meta.columns)
    assert meta["family"].notna().any() and meta["category"].notna().any()


def test_the_tier_order_is_class_category_family():
    assert CLASSIFICATION_TIERS == ("solution", "category", "family")


def test_unknown_feed_key_warns_and_is_dropped(tmp_path):
    raw = {"SPX": {"Name": "S&P 500", "Sector": "Broad"}}
    with pytest.warns(UserWarning, match="not in CATALOG_SCHEMA"):
        meta = load_metadata(_write(tmp_path, raw))
    assert "Sector" not in meta.columns
    assert list(meta.columns) == META_COLUMNS


# --- loading --------------------------------------------------------------


def test_load_metadata_exposes_description():
    """The real catalog loads with a populated `description` column."""
    meta = load_metadata()
    assert list(meta.columns) == META_COLUMNS
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
    meta = load_metadata(_write(tmp_path, raw))
    assert "description" in meta.columns
    assert pd.isna(meta.loc[0, "description"])


def test_date_role_field_is_coerced(tmp_path):
    raw = {"SPX": {"Name": "S&P 500", "LiveDate": "1957-03-04"}}
    meta = load_metadata(_write(tmp_path, raw))
    assert meta.loc[0, "live_date"] == pd.Timestamp("1957-03-04")
    assert meta.loc[0, "ticker"] == "SPX Index"


# --- apply_filters --------------------------------------------------------


def _catalog() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["A Index", "B Index", "C Index"],
            "asset_class": ["Equity", "Equity", "Rates"],
            "family": ["Carry", "Value", "Carry"],
            "category": ["Alt", "Alt", "Core"],
            "live_date": pd.to_datetime(["2020-01-01", "2021-01-01", "2022-01-01"]),
        }
    )


def test_filters_by_field_mapping():
    got = apply_filters(_catalog(), {"asset_class": ["Equity"], "family": ["Carry"]})
    assert got["ticker"].tolist() == ["A Index"]


def test_empty_and_absent_filters_leave_a_dimension_alone():
    df = _catalog()
    assert len(apply_filters(df, {"asset_class": []})) == 3
    assert len(apply_filters(df, {})) == 3
    assert len(apply_filters(df, None)) == 3


def test_live_date_bounds_still_apply():
    got = apply_filters(_catalog(), live_date_min=pd.Timestamp("2021-01-01"))
    assert got["ticker"].tolist() == ["B Index", "C Index"]


def test_unknown_filter_key_is_rejected():
    with pytest.raises(KeyError, match="not a filterable catalog field"):
        apply_filters(_catalog(), {"description": ["anything"]})
