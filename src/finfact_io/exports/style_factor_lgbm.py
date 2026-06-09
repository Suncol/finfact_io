from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence

import pandas as pd

from finfact_io.config import PathLike
from finfact_io.data_directory import (
    ASHARE_DAILY_DATASET,
    DEFAULT_DATA_DIR,
    LISTING_BOARD_DATASET,
    SW_INDUSTRY_DATASET,
    DataDirectoryReader,
)
from finfact_io.errors import DataFileNotFoundError, SchemaError
from finfact_io.exports.style_factor_matrix import _prepare_partition_dir
from finfact_io.fields import FIELD_UNITS_RAW
from finfact_io.readers.csv import parse_date_value

AsofPolicy = Literal["next_trading_day", "same_day"]

DEFAULT_OUTPUT_DIR = Path("data") / "lgbm_style_factors"
MARKET_CAP_RAW_COLUMN = "总市值(万元)"
MARKET_CAP_STANDARD_COLUMN = "total_market_cap"


@dataclass(frozen=True)
class LgbmStyleFactorBuildReport:
    output_dir: Path
    date_range: tuple[str, str]
    row_counts: dict[str, int]
    files: dict[str, Path]


@dataclass(frozen=True)
class StyleIndexDatasetSpec:
    name: str
    dataset: str
    index_code: str
    expected_member_count: int


DEFAULT_SIZE_TIER_SPECS: tuple[StyleIndexDatasetSpec, ...] = (
    StyleIndexDatasetSpec("hs300", "csi300", "000300.SH", 300),
    StyleIndexDatasetSpec("csi500", "csi500", "000905.SH", 500),
    StyleIndexDatasetSpec("csi1000", "csi1000", "000852.SH", 1000),
    StyleIndexDatasetSpec("csi2000", "csi2000", "932000.CSI", 2000),
)

SIZE_TIER_LABELS: dict[int, tuple[str, str]] = {
    0: ("not_in_size_indices", "均不在沪深300/中证500/中证1000/中证2000"),
    1: ("hs300", "沪深300"),
    2: ("csi500", "中证500"),
    3: ("csi1000", "中证1000"),
    4: ("csi2000", "中证2000"),
}

OUTPUT_COLUMNS = [
    "trade_date",
    "symbol",
    "industry_l1_code_id",
    "listing_board_id",
    "size_tier",
    "total_market_cap_rank_pct",
]
FEATURE_COLUMNS = [
    "industry_l1_code_id",
    "listing_board_id",
    "size_tier",
    "total_market_cap_rank_pct",
]
CATEGORICAL_FEATURES = ["industry_l1_code_id", "listing_board_id", "size_tier"]

LISTING_BOARD_REQUIRED_COLUMNS = (
    "stock_code",
    "listing_board_code",
    "listing_board",
    "board_order",
    "reference_mode",
)


def build_lgbm_style_factor_dataset(
    *,
    data_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    include_bse: bool = False,
    index_specs: Sequence[StyleIndexDatasetSpec] = DEFAULT_SIZE_TIER_SPECS,
    asof_policy: AsofPolicy = "next_trading_day",
) -> LgbmStyleFactorBuildReport:
    if len(index_specs) != 4:
        raise ValueError("index_specs must contain exactly four ordered size tier specs")
    if asof_policy not in {"next_trading_day", "same_day"}:
        raise ValueError("asof_policy must be one of: 'next_trading_day', 'same_day'")

    data_root = Path(data_dir).expanduser() if data_dir is not None else DEFAULT_DATA_DIR
    reader = DataDirectoryReader(data_root)
    target = Path(output_dir).expanduser() if output_dir is not None else DEFAULT_OUTPUT_DIR
    target.mkdir(parents=True, exist_ok=True)

    requested_start = parse_date_value(start)
    requested_end = parse_date_value(end)
    selected_daily_index, index_availability = _select_generated_daily_index(
        reader,
        index_specs=index_specs,
        start=requested_start,
        end=requested_end,
        asof_policy=asof_policy,
    )
    if selected_daily_index.empty:
        first_index_date = max(
            (item["first_usable_date_ts"] for item in index_availability.values()),
            default=requested_start,
        )
        effective_start = max([date for date in [requested_start, first_index_date] if date is not None])
        raise DataFileNotFoundError(
            "No LGBM style factor dates after intersecting generated A-share daily metrics, "
            "complete generated index daily-asof membership, and requested range. "
            f"effective_start={_format_optional_date(effective_start)}"
        )
    effective_start = pd.Timestamp(selected_daily_index.iloc[0]["date"])

    selected_dates = [pd.Timestamp(value) for value in selected_daily_index["date"]]
    index_memberships = _build_index_memberships_from_generated(
        reader,
        index_specs=index_specs,
        trade_dates=selected_dates,
    )

    industry_reference, industry_meta = _load_static_industry_reference(reader, level="L1")
    industry_reference, category_mappings = _encode_industry_categories(industry_reference)
    listing_board_reference, listing_board_mappings, listing_board_meta = _load_static_listing_board_reference(reader)
    category_mappings = pd.concat(
        [category_mappings, listing_board_mappings, _size_tier_category_mappings(index_specs)],
        ignore_index=True,
    )

    partition_dir = target / "lgbm_style_factors"
    _prepare_partition_dir(partition_dir)

    index_rows: list[dict[str, object]] = []
    total_rows = 0
    total_missing_market_cap = 0
    total_unclassified_industry = 0
    total_unclassified_listing_board = 0
    total_bse_filtered_rows = 0
    total_size_tier_overlap_rows = 0
    duplicate_key_rows = 0

    ashare_dataset_path = reader.dataset_path(ASHARE_DAILY_DATASET)
    for row in selected_daily_index.itertuples(index=False):
        trade_date = pd.Timestamp(row.date)
        source_path = ashare_dataset_path / str(row.file_path)
        daily_metrics = reader.ashare_daily_by_date(trade_date)
        chunk, stats = _build_lgbm_features_for_date(
            trade_date=trade_date,
            daily_metrics=daily_metrics,
            industry_reference=industry_reference,
            listing_board_reference=listing_board_reference,
            include_bse=include_bse,
            index_specs=index_specs,
            index_memberships=index_memberships,
        )
        month_dir = partition_dir / trade_date.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        output_path = month_dir / f"{trade_date.strftime('%Y-%m-%d')}.csv"
        chunk.to_csv(output_path, index=False)

        total_rows += len(chunk)
        total_missing_market_cap += stats["missing_market_cap_rows"]
        total_unclassified_industry += stats["unclassified_industry_rows"]
        total_unclassified_listing_board += stats["unclassified_listing_board_rows"]
        total_bse_filtered_rows += stats["bse_filtered_rows"]
        total_size_tier_overlap_rows += stats["size_tier_overlap_rows"]
        duplicate_key_rows += stats["duplicate_key_rows"]
        index_rows.append(
            {
                "date": trade_date.strftime("%Y-%m-%d"),
                "file_path": str(output_path.relative_to(target)),
                "rows": len(chunk),
                "unique_symbols": int(chunk["symbol"].nunique(dropna=True)),
                **stats,
                "source_path": str(source_path),
                "source_kind": "generated_ashare_daily_metrics",
            }
        )

    daily_index = pd.DataFrame(index_rows)
    schema = _build_schema()
    quality = _build_quality_table(
        daily_index=daily_index,
        index_availability=index_availability,
        industry_meta=industry_meta,
        listing_board_meta=listing_board_meta,
        total_missing_market_cap=total_missing_market_cap,
        total_unclassified_industry=total_unclassified_industry,
        total_unclassified_listing_board=total_unclassified_listing_board,
        total_bse_filtered_rows=total_bse_filtered_rows,
        total_size_tier_overlap_rows=total_size_tier_overlap_rows,
        duplicate_key_rows=duplicate_key_rows,
        include_bse=include_bse,
    )

    paths = {
        "lgbm_style_factors.csv": target / "lgbm_style_factors.csv",
        "category_mappings.csv": target / "category_mappings.csv",
        "schema.csv": target / "schema.csv",
        "data_quality.csv": target / "data_quality.csv",
        "manifest.json": target / "manifest.json",
        "README.md": target / "README.md",
    }
    daily_index.to_csv(paths["lgbm_style_factors.csv"], index=False)
    category_mappings.to_csv(paths["category_mappings.csv"], index=False)
    schema.to_csv(paths["schema.csv"], index=False)
    quality.to_csv(paths["data_quality.csv"], index=False)

    first_date = str(daily_index.iloc[0]["date"])
    last_date = str(daily_index.iloc[-1]["date"])
    row_counts = {
        "lgbm_style_factors": len(daily_index),
        "lgbm_style_factor_rows": total_rows,
        "category_mappings": len(category_mappings),
        "schema": len(schema),
        "data_quality": len(quality),
    }
    manifest = _build_manifest(
        data_dir=data_root,
        reader=reader,
        output_dir=target,
        row_counts=row_counts,
        files=paths,
        date_range=(first_date, last_date),
        index_specs=index_specs,
        index_availability=index_availability,
        industry_meta=industry_meta,
        listing_board_meta=listing_board_meta,
        asof_policy=asof_policy,
        requested_start=requested_start,
        requested_end=requested_end,
        effective_start=effective_start,
        include_bse=include_bse,
    )
    paths["manifest.json"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["README.md"].write_text(_build_readme(manifest), encoding="utf-8")

    return LgbmStyleFactorBuildReport(
        output_dir=target,
        date_range=(first_date, last_date),
        row_counts=row_counts,
        files=paths,
    )


def _select_generated_daily_index(
    reader: DataDirectoryReader,
    *,
    index_specs: Sequence[StyleIndexDatasetSpec],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    asof_policy: AsofPolicy,
) -> tuple[pd.DataFrame, dict[str, dict[str, object]]]:
    daily_index = reader.ashare_daily_dates()
    if daily_index.empty:
        raise DataFileNotFoundError("Generated A-share daily_metrics.csv contains no dates")
    daily_index = daily_index.copy()
    daily_index["date"] = pd.to_datetime(daily_index["date"])
    if start is not None:
        daily_index = daily_index[daily_index["date"] >= start]
    if end is not None:
        daily_index = daily_index[daily_index["date"] <= end]

    date_sets: list[set[pd.Timestamp]] = [
        {pd.Timestamp(value).normalize() for value in daily_index["date"]}
    ]
    availability: dict[str, dict[str, object]] = {}
    for spec in index_specs:
        manifest = reader.manifest(spec.dataset)
        generated_policy = (
            manifest.get("point_in_time", {}).get("asof_policy")
            if isinstance(manifest.get("point_in_time"), dict)
            else None
        )
        if generated_policy is not None and generated_policy != asof_policy:
            raise SchemaError(
                f"Generated dataset {spec.dataset!r} has asof_policy={generated_policy!r}; "
                f"LGBM export requested asof_policy={asof_policy!r}"
            )
        asof_index = reader.index_daily_asof_dates(spec.dataset)
        complete = _complete_generated_index_dates(asof_index, expected_member_count=spec.expected_member_count)
        if complete.empty:
            raise DataFileNotFoundError(
                f"No complete generated daily-asof membership rows found for {spec.name} ({spec.dataset})"
            )

        complete_dates = {pd.Timestamp(value).normalize() for value in complete["date"]}
        date_sets.append(complete_dates)
        first_usable = pd.Timestamp(complete["date"].min()).normalize()
        latest_usable = pd.Timestamp(complete["date"].max()).normalize()
        availability[spec.name] = {
            "dataset": spec.dataset,
            "index_code": spec.index_code,
            "expected_member_count": spec.expected_member_count,
            "first_usable_date": first_usable.strftime("%Y-%m-%d"),
            "first_usable_date_ts": first_usable,
            "latest_usable_date": latest_usable.strftime("%Y-%m-%d"),
            "complete_daily_asof_count": int(len(complete)),
            "daily_asof_count": int(len(asof_index)),
            "asof_policy": generated_policy or asof_policy,
        }

    usable_dates = set.intersection(*date_sets) if date_sets else set()
    selected = daily_index[daily_index["date"].map(lambda value: pd.Timestamp(value).normalize() in usable_dates)]
    return selected.sort_values("date").reset_index(drop=True), availability


def _complete_generated_index_dates(
    asof_index: pd.DataFrame,
    *,
    expected_member_count: int,
) -> pd.DataFrame:
    required = {"date", "quality_status", "rows", "weight_sum"}
    missing = required.difference(asof_index.columns)
    if missing:
        raise SchemaError(f"Generated index daily-asof index is missing columns: {sorted(missing)}")
    work = asof_index.copy()
    work["date"] = pd.to_datetime(work["date"])
    work["_rows"] = pd.to_numeric(work["rows"], errors="coerce")
    work["_weight_sum"] = pd.to_numeric(work["weight_sum"], errors="coerce")
    complete = (
        work["quality_status"].astype(str).eq("complete")
        & (work["_rows"] >= expected_member_count)
        & work["_weight_sum"].between(95, 105, inclusive="both")
    )
    return work[complete].reset_index(drop=True)


def _build_index_memberships_from_generated(
    reader: DataDirectoryReader,
    *,
    index_specs: Sequence[StyleIndexDatasetSpec],
    trade_dates: Sequence[pd.Timestamp],
) -> dict[str, dict[str, set[str]]]:
    memberships: dict[str, dict[str, set[str]]] = {}
    for spec in index_specs:
        per_date: dict[str, set[str]] = {}
        for trade_date in trade_dates:
            date_text = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
            rows = reader.index_weights_by_date(spec.dataset, date_text)
            if "member_symbol" not in rows.columns:
                raise SchemaError(f"Generated dataset {spec.dataset!r} is missing member_symbol")
            if "index_code" in rows.columns:
                unexpected = rows["index_code"].dropna().astype(str)
                if not unexpected.empty and set(unexpected) != {spec.index_code}:
                    raise SchemaError(
                        f"Generated dataset {spec.dataset!r} contains index_code values "
                        f"{sorted(set(unexpected))}, expected {spec.index_code!r}"
                    )
            per_date[date_text] = set(rows["member_symbol"].dropna().astype(str))
        memberships[spec.name] = per_date
    return memberships


def _encode_industry_categories(industry_reference: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = industry_reference.copy()
    categories = (
        work[["industry_code", "industry_name"]]
        .dropna(subset=["industry_code"])
        .drop_duplicates("industry_code")
        .sort_values("industry_code")
        .reset_index(drop=True)
    )
    code_to_id = {str(row.industry_code): index + 1 for index, row in categories.iterrows()}
    work["industry_l1_code_id"] = (
        work["industry_code"].astype(str).map(code_to_id).fillna(0).astype("int64")
    )
    mapping_rows = [
        {
            "feature": "industry_l1_code_id",
            "category_id": 0,
            "category_value": "__UNCLASSIFIED__",
            "category_label": "未分类",
            "ordered": False,
        }
    ]
    for index, row in categories.iterrows():
        mapping_rows.append(
            {
                "feature": "industry_l1_code_id",
                "category_id": index + 1,
                "category_value": row["industry_code"],
                "category_label": row["industry_name"],
                "ordered": False,
            }
        )
    encoded = work[["symbol", "industry_l1_code_id"]].drop_duplicates("symbol", keep="last")
    return encoded.reset_index(drop=True), pd.DataFrame(mapping_rows)


def _load_static_industry_reference(
    reader: DataDirectoryReader,
    *,
    level: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if level not in {"L1", "L2", "L3"}:
        raise ValueError("level must be one of: 'L1', 'L2', 'L3'")
    current = reader.sw_industry_snapshot()
    required = {
        "stock_code",
        f"industry_level{level[1]}_code",
        f"industry_level{level[1]}",
        "classification_snapshot_date",
        "classification_mode",
    }
    missing = required.difference(current.columns)
    if missing:
        raise SchemaError(f"Generated SW industry current_snapshot.csv is missing columns: {sorted(missing)}")

    level_suffix = level[1]
    code_column = f"industry_level{level_suffix}_code"
    name_column = f"industry_level{level_suffix}"
    reference = pd.DataFrame(
        {
            "symbol": current["stock_code"].astype("string"),
            "industry_code": current[code_column].astype("string"),
            "industry_name": current[name_column].astype("string"),
            "industry_classification_snapshot_date": current["classification_snapshot_date"].astype("string"),
            "industry_classification_mode": current["classification_mode"].astype("string"),
        }
    )
    reference = reference.drop_duplicates("symbol", keep="last").sort_values("symbol").reset_index(drop=True)
    manifest = reader.manifest(SW_INDUSTRY_DATASET)
    dataset_path = reader.dataset_path(SW_INDUSTRY_DATASET)
    meta = {
        "path": str(dataset_path),
        "current_snapshot_path": str(dataset_path / "current_snapshot.csv"),
        "industry_level": level,
        "industry_standard": manifest.get("industry_standard", _single_value(current.get("industry_standard"))),
        "classification_snapshot_date": manifest.get(
            "classification_snapshot_date",
            _single_value(current.get("classification_snapshot_date")),
        ),
        "classification_mode": manifest.get("classification_mode", _single_value(current.get("classification_mode"))),
        "historical_pit_industry": bool(manifest.get("historical_pit_industry", False)),
        "rows": int(len(reference)),
    }
    return reference, meta


def _load_static_listing_board_reference(
    reader: DataDirectoryReader,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    current = reader.listing_board_snapshot()
    missing = set(LISTING_BOARD_REQUIRED_COLUMNS).difference(current.columns)
    if missing:
        raise SchemaError(f"Generated listing board current_snapshot.csv is missing columns: {sorted(missing)}")
    work = current.copy()
    work["listing_board_code"] = work["listing_board_code"].astype("string")
    work["board_order"] = pd.to_numeric(work["board_order"], errors="coerce")
    categories = (
        work[["listing_board_code", "listing_board", "board_order"]]
        .dropna(subset=["listing_board_code", "board_order"])
        .drop_duplicates("listing_board_code")
        .sort_values("board_order")
        .reset_index(drop=True)
    )
    code_to_id = {str(row.listing_board_code): int(row.board_order) for row in categories.itertuples(index=False)}
    work["listing_board_id"] = (
        work["listing_board_code"].astype(str).map(code_to_id).fillna(0).astype("int64")
    )
    reference = work[
        ["stock_code", "listing_board_code", "listing_board_id"]
    ].rename(columns={"stock_code": "symbol"})
    reference = reference.drop_duplicates("symbol", keep="last").sort_values("symbol").reset_index(drop=True)

    mapping_rows = [
        {
            "feature": "listing_board_id",
            "category_id": 0,
            "category_value": "__UNCLASSIFIED__",
            "category_label": "未分类",
            "ordered": False,
        }
    ]
    for row in categories.itertuples(index=False):
        mapping_rows.append(
            {
                "feature": "listing_board_id",
                "category_id": int(row.board_order),
                "category_value": row.listing_board_code,
                "category_label": row.listing_board,
                "ordered": False,
            }
        )

    manifest = reader.manifest(LISTING_BOARD_DATASET)
    dataset_path = reader.dataset_path(LISTING_BOARD_DATASET)
    meta = {
        "path": str(dataset_path),
        "current_snapshot_path": str(dataset_path / "current_snapshot.csv"),
        "dimension_standard": manifest.get("dimension_standard", _single_value(work.get("dimension_standard"))),
        "reference_mode": manifest.get("reference_mode", _single_value(work.get("reference_mode"))),
        "historical_pit_listing_board": bool(manifest.get("historical_pit_listing_board", False)),
        "rows": int(len(reference)),
    }
    return reference, pd.DataFrame(mapping_rows), meta


def _single_value(series: pd.Series | None) -> object:
    if series is None:
        return None
    values = series.dropna().astype(str).unique()
    if len(values) == 0:
        return None
    return values[0]


def _size_tier_category_mappings(index_specs: Sequence[StyleIndexDatasetSpec]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for tier_id, spec in enumerate(index_specs, start=1):
        value, label = SIZE_TIER_LABELS.get(tier_id, (spec.name, spec.name))
        rows.append(
            {
                "feature": "size_tier",
                "category_id": tier_id,
                "category_value": value,
                "category_label": label,
                "ordered": True,
            }
        )
    rows.insert(
        0,
        {
            "feature": "size_tier",
            "category_id": 0,
            "category_value": SIZE_TIER_LABELS[0][0],
            "category_label": SIZE_TIER_LABELS[0][1],
            "ordered": True,
        },
    )
    return pd.DataFrame(rows)


def _build_lgbm_features_for_date(
    *,
    trade_date: pd.Timestamp,
    daily_metrics: pd.DataFrame,
    industry_reference: pd.DataFrame,
    listing_board_reference: pd.DataFrame,
    include_bse: bool,
    index_specs: Sequence[StyleIndexDatasetSpec],
    index_memberships: dict[str, dict[str, set[str]]],
) -> tuple[pd.DataFrame, dict[str, int]]:
    required = {"symbol", "trade_date", MARKET_CAP_STANDARD_COLUMN}
    missing = required.difference(daily_metrics.columns)
    if missing:
        raise SchemaError(f"Generated A-share daily metrics partition is missing columns: {sorted(missing)}")
    date_text = trade_date.strftime("%Y-%m-%d")
    standard = daily_metrics.copy()
    standard = standard[pd.to_datetime(standard["trade_date"]).dt.strftime("%Y-%m-%d") == date_text].copy()
    result = pd.DataFrame(
        {
            "trade_date": date_text,
            "symbol": standard["symbol"].astype("string"),
            "_total_market_cap_10k_yuan": pd.to_numeric(
                standard[MARKET_CAP_STANDARD_COLUMN],
                errors="coerce",
            ),
        }
    )
    result = result.merge(industry_reference, on="symbol", how="left")
    result["industry_l1_code_id"] = result["industry_l1_code_id"].fillna(0).astype("int64")
    result = result.merge(listing_board_reference, on="symbol", how="left")
    result["listing_board_id"] = result["listing_board_id"].fillna(0).astype("int64")

    bse_mask = (
        (result["listing_board_code"].astype("string") == "BSE")
        | result["symbol"].astype(str).str.endswith(".BJ")
    ).fillna(False)
    bse_filtered_rows = int(bse_mask.sum()) if not include_bse else 0
    if not include_bse:
        result = result[~bse_mask].copy()

    size_tier, membership_count = _resolve_size_tier(
        result["symbol"].astype(str),
        trade_date=date_text,
        index_specs=index_specs,
        index_memberships=index_memberships,
    )
    result["size_tier"] = size_tier
    result["total_market_cap_rank_pct"] = result["_total_market_cap_10k_yuan"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    result = result.sort_values("symbol").reset_index(drop=True)
    duplicate_key_rows = int(result.duplicated(["symbol", "trade_date"], keep=False).sum())
    stats = {
        "missing_market_cap_rows": int(result["total_market_cap_rank_pct"].isna().sum()),
        "unclassified_industry_rows": int((result["industry_l1_code_id"] == 0).sum()),
        "unclassified_listing_board_rows": int((result["listing_board_id"] == 0).sum()),
        "bse_filtered_rows": bse_filtered_rows,
        "size_tier_overlap_rows": int((membership_count > 1).sum()),
        "duplicate_key_rows": duplicate_key_rows,
    }
    return result.loc[:, OUTPUT_COLUMNS], stats


def _resolve_size_tier(
    symbols: pd.Series,
    *,
    trade_date: str,
    index_specs: Sequence[StyleIndexDatasetSpec],
    index_memberships: dict[str, dict[str, set[str]]],
) -> tuple[pd.Series, pd.Series]:
    tier = pd.Series(0, index=symbols.index, dtype="int64")
    membership_count = pd.Series(0, index=symbols.index, dtype="int64")
    for tier_id, spec in enumerate(index_specs, start=1):
        members = index_memberships.get(spec.name, {}).get(trade_date, set())
        in_index = symbols.isin(members)
        membership_count = membership_count + in_index.astype("int64")
        tier = tier.mask((tier == 0) & in_index, tier_id)
    return tier.astype("int64"), membership_count.astype("int64")


def _build_schema() -> pd.DataFrame:
    rows = [
        {
            "column": "trade_date",
            "role": "key",
            "unit": "",
            "nullable": False,
            "lightgbm_categorical": False,
            "description": "Trading date",
        },
        {
            "column": "symbol",
            "role": "key",
            "unit": "",
            "nullable": False,
            "lightgbm_categorical": False,
            "description": "A-share stock code with exchange suffix",
        },
        {
            "column": "industry_l1_code_id",
            "role": "categorical_feature",
            "unit": "",
            "nullable": False,
            "lightgbm_categorical": True,
            "description": "Integer-coded static SW2021 L1 industry category",
        },
        {
            "column": "listing_board_id",
            "role": "categorical_feature",
            "unit": "",
            "nullable": False,
            "lightgbm_categorical": True,
            "description": "Integer-coded static listing board category: 1 main, 2 ChiNext, 3 STAR, 4 BSE",
        },
        {
            "column": "size_tier",
            "role": "ordered_categorical_feature",
            "unit": "",
            "nullable": False,
            "lightgbm_categorical": True,
            "description": "Ordered point-in-time size index tier: 0 none, 1 HS300, 2 CSI500, 3 CSI1000, 4 CSI2000",
        },
        {
            "column": "total_market_cap_rank_pct",
            "role": "numeric_style_factor",
            "unit": "",
            "nullable": True,
            "lightgbm_categorical": False,
            "description": "Daily cross-sectional ascending percentile rank of total market capitalization",
        },
    ]
    return pd.DataFrame(rows)


def _build_quality_table(
    *,
    daily_index: pd.DataFrame,
    index_availability: dict[str, dict[str, object]],
    industry_meta: dict[str, object],
    listing_board_meta: dict[str, object],
    total_missing_market_cap: int,
    total_unclassified_industry: int,
    total_unclassified_listing_board: int,
    total_bse_filtered_rows: int,
    total_size_tier_overlap_rows: int,
    duplicate_key_rows: int,
    include_bse: bool,
) -> pd.DataFrame:
    rows = [
        _quality_row("daily_file_count", len(daily_index) > 0, len(daily_index), "daily files generated"),
        _quality_row(
            "duplicate_symbol_trade_date",
            duplicate_key_rows == 0,
            duplicate_key_rows,
            "duplicate (symbol, trade_date) rows",
        ),
        _quality_row(
            "market_cap_rank_pct_available",
            total_missing_market_cap == 0,
            total_missing_market_cap,
            "rows with missing total_market_cap_rank_pct",
            severity_if_fail="warning",
        ),
        _quality_row(
            "industry_l1_category_available",
            total_unclassified_industry == 0,
            total_unclassified_industry,
            "rows assigned to industry_l1_code_id=0",
            severity_if_fail="warning",
        ),
        _quality_row(
            "listing_board_category_available",
            total_unclassified_listing_board == 0,
            total_unclassified_listing_board,
            "rows assigned to listing_board_id=0",
            severity_if_fail="warning",
        ),
        _quality_row(
            "bse_universe_policy_applied",
            True,
            total_bse_filtered_rows,
            "BSE rows filtered from the model universe when include_bse=False",
        ),
        _quality_row(
            "size_tier_overlap_rows",
            total_size_tier_overlap_rows == 0,
            total_size_tier_overlap_rows,
            "rows belonging to more than one ordered size tier; lowest tier id wins",
            severity_if_fail="warning",
        ),
        _quality_row(
            "static_industry_reference_declared",
            industry_meta.get("historical_pit_industry") is False,
            industry_meta.get("classification_mode"),
            "industry reference should be explicitly static for this export",
        ),
        _quality_row(
            "static_listing_board_reference_declared",
            listing_board_meta.get("historical_pit_listing_board") is False,
            listing_board_meta.get("reference_mode"),
            "listing board reference should be explicitly static for this export",
        ),
        _quality_row(
            "include_bse_parameter",
            isinstance(include_bse, bool),
            include_bse,
            "stock universe BSE inclusion parameter",
        ),
        _quality_row(
            "data_only_source_declared",
            True,
            "generated_data_directory",
            "all inputs are read from generated data/ datasets rather than raw download directories",
        ),
    ]
    for name, item in index_availability.items():
        rows.append(
            _quality_row(
                f"{name}_membership_first_usable_date",
                bool(item.get("first_usable_date")),
                item.get("first_usable_date"),
                "first trade date with complete point-in-time index membership",
            )
        )
    return pd.DataFrame(rows)


def _quality_row(
    check: str,
    passed: bool,
    observed_value: object,
    detail: str,
    *,
    severity_if_fail: str = "error",
) -> dict[str, object]:
    return {
        "dataset": "lgbm_style_factors",
        "check": check,
        "status": "pass" if passed else "warning" if severity_if_fail == "warning" else "fail",
        "severity": "info" if passed else severity_if_fail,
        "affected_date": pd.NA,
        "observed_value": observed_value,
        "detail": detail,
    }


def _build_manifest(
    *,
    data_dir: Path,
    reader: DataDirectoryReader,
    output_dir: Path,
    row_counts: dict[str, int],
    files: dict[str, Path],
    date_range: tuple[str, str],
    index_specs: Sequence[StyleIndexDatasetSpec],
    index_availability: dict[str, dict[str, object]],
    industry_meta: dict[str, object],
    listing_board_meta: dict[str, object],
    asof_policy: AsofPolicy,
    requested_start: pd.Timestamp | None,
    requested_end: pd.Timestamp | None,
    effective_start: pd.Timestamp,
    include_bse: bool,
) -> dict[str, object]:
    clean_availability = {
        name: {
            key: value
            for key, value in item.items()
            if key not in {"first_usable_date_ts"}
        }
        for name, item in index_availability.items()
    }
    source_datasets = {
        ASHARE_DAILY_DATASET: {
            "path": str(reader.dataset_path(ASHARE_DAILY_DATASET)),
            "role": "daily_stock_cross_section_and_market_cap",
        },
        SW_INDUSTRY_DATASET: {
            "path": str(reader.dataset_path(SW_INDUSTRY_DATASET)),
            "role": "static_industry_reference",
        },
        LISTING_BOARD_DATASET: {
            "path": str(reader.dataset_path(LISTING_BOARD_DATASET)),
            "role": "static_listing_board_reference",
        },
    }
    for spec in index_specs:
        source_datasets[spec.dataset] = {
            "path": str(reader.dataset_path(spec.dataset)),
            "role": "point_in_time_index_membership",
            "index_code": spec.index_code,
            "tier_name": spec.name,
        }
    size_tiers = [
        {
            "tier": 0,
            "name": SIZE_TIER_LABELS[0][0],
            "label": SIZE_TIER_LABELS[0][1],
            "index_code": None,
        }
    ]
    for tier_id, spec in enumerate(index_specs, start=1):
        value, label = SIZE_TIER_LABELS.get(tier_id, (spec.name, spec.name))
        size_tiers.append(
            {
                "tier": tier_id,
                "name": value,
                "label": label,
                "dataset": spec.dataset,
                "index_code": spec.index_code,
            }
        )

    return {
        "dataset": "lgbm_style_factors",
        "description": "Compact daily style features designed for LightGBM tree models.",
        "date_range": {"start": date_range[0], "end": date_range[1]},
        "requested_range": {
            "start": _format_optional_date(requested_start),
            "end": _format_optional_date(requested_end),
        },
        "effective_start": effective_start.strftime("%Y-%m-%d"),
        "data_dir": str(data_dir),
        "source_policy": "data_only_generated_datasets",
        "source_datasets": source_datasets,
        "output_dir": str(output_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": FEATURE_COLUMNS,
        "categorical_features": CATEGORICAL_FEATURES,
        "point_in_time": {
            "index_membership_asof_policy": asof_policy,
            "index_membership_source": "generated_constituent_weights_daily_asof",
            "industry_membership": "static_current_reference",
        },
        "industry_reference": industry_meta,
        "listing_board_reference": listing_board_meta,
        "industry_encoding": {
            "feature": "industry_l1_code_id",
            "encoding": "single_integer_category",
            "missing_category_id": 0,
            "mapping_file": str(files["category_mappings.csv"]),
        },
        "listing_board_encoding": {
            "feature": "listing_board_id",
            "encoding": "single_integer_category",
            "missing_category_id": 0,
            "mapping_file": str(files["category_mappings.csv"]),
        },
        "stock_universe": {
            "include_bse": include_bse,
            "excluded_board_codes": [] if include_bse else ["BSE"],
            "filter_applied_before_market_cap_rank_pct": True,
        },
        "index_membership": {
            "feature": "size_tier",
            "encoding": "single_ordered_size_tier",
            "tiers": size_tiers,
            "availability": clean_availability,
        },
        "market_cap": {
            "source_raw_column": MARKET_CAP_RAW_COLUMN,
            "source_unit": FIELD_UNITS_RAW[MARKET_CAP_RAW_COLUMN],
            "feature": "total_market_cap_rank_pct",
            "included_transforms": ["daily_cross_section_rank_pct"],
            "excluded_transforms": ["raw", "rank", "log10"],
        },
        "risk_notes": {
            "short_sample_start": effective_start.strftime("%Y-%m-%d"),
            "short_sample_reason": (
                "Requiring official CSI2000 membership makes the four-index intersection short; "
                "treat regime dependence as a first-order validation risk."
            ),
            "style_beta_warning": (
                "These features can let a tree model learn direct size/industry beta. "
                "Evaluate neutralized IC and consider neutralizing labels or raw alpha factors."
            ),
        },
        "files": {
            name: {
                "path": str(path),
                "rows": row_counts.get(name.removesuffix(".csv")),
            }
            for name, path in files.items()
            if name.endswith(".csv")
        },
    }


def _build_readme(manifest: dict[str, object]) -> str:
    return f"""# LGBM Style Factors

This directory contains compact daily style features from
{manifest["date_range"]["start"]} to {manifest["date_range"]["end"]}.
It is built only from generated datasets under `{manifest["data_dir"]}`.

The model-facing feature columns are:

- `industry_l1_code_id`, declared as a LightGBM categorical feature.
- `listing_board_id`, declared as a LightGBM categorical feature.
- `size_tier`, declared as a LightGBM categorical feature with ordered economic meaning.
- `total_market_cap_rank_pct`, the daily cross-sectional percentile rank of total market cap.

By default the stock universe excludes Beijing Stock Exchange (`BSE`) rows before
the daily market-cap percentile rank is calculated. Set `include_bse=True` when
building the export to include them.

The export intentionally excludes industry one-hot columns, separate index membership
flags, raw market cap, raw market-cap rank, and log10 market cap.
"""


def _format_optional_date(value: pd.Timestamp | None) -> object:
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")
