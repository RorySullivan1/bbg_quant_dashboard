"""Loading and filtering the local index catalog.

Reads `data/indexdb.json` and reshapes it into a tidy DataFrame keyed by
ticker. What each JSON column is called, what it is called internally, and how
it is displayed all come from `CATALOG_SCHEMA` (`src/config.py`) — this module
resolves the feed against that schema rather than knowing any column name of
its own. `apply_filters` is the single place categorical metadata filtering
happens; the quantitative (price-derived) filters live with the UI, since they
need the fetched prices.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

from .config import CATALOG_SCHEMA, DATA_PATH, filterable_fields

#: Columns the loader derives itself, so they never count as unknown feed keys.
_DERIVED_COLUMNS = frozenset({"ticker", "ticker_short"})

META_COLUMNS = ["ticker"] + [field.key for field in CATALOG_SCHEMA]


def _rename_from_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Rename the feed's columns to their internal keys via the schema.

    Each field takes the first of its `sources` aliases actually present, so a
    feed may mix canonical and legacy keys. Both a legacy alias and an
    unrecognised key warn once — a stale or extended feed degrades to a working
    app rather than a `KeyError` at startup, but it says so.
    """
    present = set(df.columns)
    rename: dict[str, str] = {}
    legacy: list[str] = []

    for field in CATALOG_SCHEMA:
        for position, source in enumerate(field.sources):
            if source in present:
                rename[source] = field.key
                if position:
                    legacy.append(f"{source!r} (use {field.sources[0]!r})")
                break

    if legacy:
        warnings.warn(
            "Catalog feed uses legacy column names: " + ", ".join(sorted(legacy)),
            stacklevel=3,
        )

    unknown = sorted(present - set(rename) - _DERIVED_COLUMNS)
    if unknown:
        warnings.warn(
            "Catalog feed has columns not in CATALOG_SCHEMA, ignoring: "
            + ", ".join(repr(key) for key in unknown),
            stacklevel=3,
        )

    return df.rename(columns=rename)


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

    df = _rename_from_schema(df)
    df["ticker"] = df["ticker_short"].astype(str).str.strip() + " Index"

    for field in CATALOG_SCHEMA:
        if field.key not in df.columns:
            df[field.key] = pd.NA

    for field in CATALOG_SCHEMA:
        if field.role == "date":
            df[field.key] = pd.to_datetime(
                df[field.key].astype(str).str.replace(r"\D", "", regex=True),
                format="%Y%m%d",
                errors="coerce",
            )

    return df[META_COLUMNS].reset_index(drop=True)


def unique_values(df: pd.DataFrame, column: str) -> list[str]:
    return sorted(df[column].dropna().astype(str).unique().tolist())


def apply_filters(
    df: pd.DataFrame,
    filters: Mapping[str, Sequence[str]] | None = None,
    *,
    live_date_min: pd.Timestamp | None = None,
    live_date_max: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Rows matching every categorical filter, keyed by internal field name.

    `filters` maps a schema field key to the values to keep; an empty or absent
    value list leaves that dimension unfiltered. Keying by field rather than by
    a fixed kwarg per dimension means adding or renaming a dimension is a schema
    edit, not a signature change.
    """
    allowed = {field.key for field in filterable_fields()}
    mask = pd.Series(True, index=df.index)

    for key, values in (filters or {}).items():
        if key not in allowed:
            raise KeyError(f"{key!r} is not a filterable catalog field")
        if not values:
            continue
        mask &= df[key].isin(list(values))

    if live_date_min is not None:
        mask &= df["live_date"] >= pd.Timestamp(live_date_min)
    if live_date_max is not None:
        mask &= df["live_date"] <= pd.Timestamp(live_date_max)
    return df.loc[mask].reset_index(drop=True)
