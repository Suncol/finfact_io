from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

from finfact_io.fields import standardize_columns, with_unit_metadata
from finfact_io.readers.csv import parse_date_value

ColumnMode = Literal["raw", "standard"]
SourceMode = Literal["historical", "incremental", "combined"]


def filter_date_range(
    df: pd.DataFrame,
    date_column: str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    start_date = parse_date_value(start)
    end_date = parse_date_value(end)
    filtered = df
    if start_date is not None:
        filtered = filtered[filtered[date_column] >= start_date]
    if end_date is not None:
        filtered = filtered[filtered[date_column] <= end_date]
    return filtered


def add_source_columns(
    df: pd.DataFrame,
    *,
    source_path: Path,
    source_kind: str,
    source_member: str | None = None,
) -> pd.DataFrame:
    with_source = df.copy()
    with_source["_source_path"] = str(source_path)
    with_source["_source_member"] = source_member or pd.NA
    with_source["_source_kind"] = source_kind
    return with_source


def finalize_columns(df: pd.DataFrame, *, dataset: str, columns: ColumnMode) -> pd.DataFrame:
    if columns == "raw":
        return with_unit_metadata(df)
    if columns == "standard":
        return standardize_columns(df, dataset)
    raise ValueError("columns must be one of: 'raw', 'standard'")


def combine_prefer_incremental(
    historical: pd.DataFrame,
    incremental: pd.DataFrame,
    *,
    key_columns: list[str],
) -> pd.DataFrame:
    if historical.empty:
        return incremental.reset_index(drop=True)
    if incremental.empty:
        return historical.reset_index(drop=True)

    left = historical.copy()
    right = incremental.copy()
    left["_source_priority"] = 0
    right["_source_priority"] = 1
    combined = pd.concat([left, right], ignore_index=True)
    combined = combined.sort_values([*key_columns, "_source_priority"])
    combined = combined.drop_duplicates(subset=key_columns, keep="last")
    combined = combined.drop(columns=["_source_priority"])
    return combined.sort_values(key_columns).reset_index(drop=True)
