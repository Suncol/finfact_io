from __future__ import annotations

import json
import math
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence

import pandas as pd

from finfact_io.config import PathLike
from finfact_io.data_directory import ASHARE_DAILY_DATASET, DEFAULT_DATA_DIR, SW_INDUSTRY_DATASET, DataDirectoryReader
from finfact_io.errors import DataFileNotFoundError, SchemaError
from finfact_io.fields import FIELD_UNITS_RAW
from finfact_io.readers.csv import parse_date_value

AsofPolicy = Literal["next_trading_day", "same_day"]

DEFAULT_OUTPUT_DIR = Path("data") / "style_factor_matrix"
MARKET_CAP_RAW_COLUMN = "总市值(万元)"
MARKET_CAP_STANDARD_COLUMN = "total_market_cap"


@dataclass(frozen=True)
class StyleIndexMembershipSpec:
    name: str
    dataset: str
    index_code: str
    expected_member_count: int
    flag_column: str | None = None

    @property
    def output_column(self) -> str:
        return self.flag_column or f"in_{self.name}"


@dataclass(frozen=True)
class StyleFactorMatrixBuildReport:
    output_dir: Path
    date_range: tuple[str, str]
    row_counts: dict[str, int]
    files: dict[str, Path]


DEFAULT_INDEX_SPECS: tuple[StyleIndexMembershipSpec, ...] = (
    StyleIndexMembershipSpec("csi300", "csi300", "000300.SH", 300),
    StyleIndexMembershipSpec("csi500", "csi500", "000905.SH", 500),
    StyleIndexMembershipSpec("csi1000", "csi1000", "000852.SH", 1000),
    StyleIndexMembershipSpec("csi2000", "csi2000", "932000.CSI", 2000),
)

INDUSTRY_CURRENT_REQUIRED_COLUMNS = (
    "stock_code",
    "stock_name",
    "industry_standard",
    "industry_level1_code",
    "industry_level1",
    "industry_level2_code",
    "industry_level2",
    "industry_level3_code",
    "industry_level3",
    "classification_snapshot_date",
    "classification_mode",
)


def build_style_factor_matrix_dataset(
    *,
    data_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    index_specs: Sequence[StyleIndexMembershipSpec] = DEFAULT_INDEX_SPECS,
    industry_level: Literal["L1", "L2", "L3"] = "L1",
    asof_policy: AsofPolicy = "next_trading_day",
) -> StyleFactorMatrixBuildReport:
    if not index_specs:
        raise ValueError("index_specs must contain at least one index membership spec")
    if industry_level not in {"L1", "L2", "L3"}:
        raise ValueError("industry_level must be one of: 'L1', 'L2', 'L3'")
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
            "No style factor matrix dates after intersecting generated A-share daily metrics, "
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

    industry_reference, industry_meta = _load_static_industry_reference(
        reader,
        level=industry_level,
    )
    industry_codes = sorted(industry_reference["industry_code"].dropna().astype(str).unique())
    industry_dummy_columns = [_industry_dummy_column(industry_level, code) for code in industry_codes]
    index_dummy_columns = [spec.output_column for spec in index_specs]

    matrix_dir = target / "style_factor_matrix"
    _prepare_partition_dir(matrix_dir)

    index_rows: list[dict[str, object]] = []
    total_rows = 0
    total_missing_market_cap = 0
    total_unclassified = 0
    duplicate_key_rows = 0

    ashare_dataset_path = reader.dataset_path(ASHARE_DAILY_DATASET)
    for row in selected_daily_index.itertuples(index=False):
        trade_date = pd.Timestamp(row.date)
        source_path = ashare_dataset_path / str(row.file_path)
        daily_metrics = reader.ashare_daily_by_date(trade_date)
        chunk = _build_matrix_for_date(
            trade_date=trade_date,
            daily_metrics=daily_metrics,
            industry_reference=industry_reference,
            industry_codes=industry_codes,
            industry_dummy_columns=industry_dummy_columns,
            index_specs=index_specs,
            index_memberships=index_memberships,
        )
        month_dir = matrix_dir / trade_date.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        output_path = month_dir / f"{trade_date.strftime('%Y-%m-%d')}.csv"
        chunk.to_csv(output_path, index=False)

        missing_market_cap = int(chunk["total_market_cap_10k_yuan"].isna().sum())
        unclassified = int(chunk["industry_code"].isna().sum())
        duplicate_rows = int(chunk.duplicated(["symbol", "trade_date"], keep=False).sum())
        total_rows += len(chunk)
        total_missing_market_cap += missing_market_cap
        total_unclassified += unclassified
        duplicate_key_rows += duplicate_rows
        index_rows.append(
            {
                "date": trade_date.strftime("%Y-%m-%d"),
                "file_path": str(output_path.relative_to(target)),
                "rows": len(chunk),
                "unique_symbols": int(chunk["symbol"].nunique(dropna=True)),
                "missing_market_cap_rows": missing_market_cap,
                "unclassified_industry_rows": unclassified,
                "duplicate_key_rows": duplicate_rows,
                "source_path": str(source_path),
                "source_kind": "generated_ashare_daily_metrics",
            }
        )

    matrix_index = pd.DataFrame(index_rows)
    schema = _build_schema(
        industry_dummy_columns=industry_dummy_columns,
        index_dummy_columns=index_dummy_columns,
        industry_level=industry_level,
    )
    quality = _build_quality_table(
        matrix_index=matrix_index,
        index_availability=index_availability,
        industry_meta=industry_meta,
        total_missing_market_cap=total_missing_market_cap,
        total_unclassified=total_unclassified,
        duplicate_key_rows=duplicate_key_rows,
    )

    paths = {
        "style_factor_matrix.csv": target / "style_factor_matrix.csv",
        "schema.csv": target / "schema.csv",
        "data_quality.csv": target / "data_quality.csv",
        "manifest.json": target / "manifest.json",
        "README.md": target / "README.md",
    }
    matrix_index.to_csv(paths["style_factor_matrix.csv"], index=False)
    schema.to_csv(paths["schema.csv"], index=False)
    quality.to_csv(paths["data_quality.csv"], index=False)

    first_date = str(matrix_index.iloc[0]["date"])
    last_date = str(matrix_index.iloc[-1]["date"])
    row_counts = {
        "style_factor_matrix": len(matrix_index),
        "style_factor_rows": total_rows,
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
        index_availability=index_availability,
        industry_meta=industry_meta,
        industry_level=industry_level,
        industry_dummy_columns=industry_dummy_columns,
        index_dummy_columns=index_dummy_columns,
        asof_policy=asof_policy,
        requested_start=requested_start,
        requested_end=requested_end,
        effective_start=effective_start,
    )
    paths["manifest.json"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["README.md"].write_text(_build_readme(manifest), encoding="utf-8")

    return StyleFactorMatrixBuildReport(
        output_dir=target,
        date_range=(first_date, last_date),
        row_counts=row_counts,
        files=paths,
    )


def _select_generated_daily_index(
    reader: DataDirectoryReader,
    *,
    index_specs: Sequence[StyleIndexMembershipSpec],
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
                f"style factor matrix requested asof_policy={asof_policy!r}"
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
            "flag_column": spec.output_column,
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
    index_specs: Sequence[StyleIndexMembershipSpec],
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


def _load_static_industry_reference(
    reader: DataDirectoryReader,
    *,
    level: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    current = reader.sw_industry_snapshot()
    missing = set(INDUSTRY_CURRENT_REQUIRED_COLUMNS).difference(current.columns)
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
        "industry_standard": manifest.get("industry_standard", _single_non_null(current.get("industry_standard"))),
        "classification_snapshot_date": manifest.get(
            "classification_snapshot_date",
            _single_non_null(current.get("classification_snapshot_date")),
        ),
        "classification_mode": manifest.get(
            "classification_mode",
            _single_non_null(current.get("classification_mode")),
        ),
        "historical_pit_industry": bool(manifest.get("historical_pit_industry", False)),
        "rows": int(len(reference)),
    }
    return reference, meta


def _single_non_null(series: pd.Series | None) -> object:
    if series is None:
        return None
    values = series.dropna().astype(str).unique()
    if len(values) == 0:
        return None
    return values[0]


def _build_matrix_for_date(
    *,
    trade_date: pd.Timestamp,
    daily_metrics: pd.DataFrame,
    industry_reference: pd.DataFrame,
    industry_codes: Sequence[str],
    industry_dummy_columns: Sequence[str],
    index_specs: Sequence[StyleIndexMembershipSpec],
    index_memberships: dict[str, dict[str, set[str]]],
) -> pd.DataFrame:
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
            "total_market_cap_10k_yuan": pd.to_numeric(
                standard[MARKET_CAP_STANDARD_COLUMN],
                errors="coerce",
            ),
        }
    )
    result = result.merge(industry_reference, on="symbol", how="left")

    for code, column in zip(industry_codes, industry_dummy_columns, strict=True):
        result[column] = (result["industry_code"].astype(str) == code).astype("int8")

    for spec in index_specs:
        members = index_memberships.get(spec.name, {}).get(date_text, set())
        result[spec.output_column] = result["symbol"].astype(str).isin(members).astype("int8")

    cap = result["total_market_cap_10k_yuan"]
    positive_cap = cap.where(cap > 0)
    result["total_market_cap_rank"] = cap.rank(method="average", ascending=True)
    result["total_market_cap_rank_pct"] = cap.rank(method="average", ascending=True, pct=True)
    result["total_market_cap_log10"] = positive_cap.map(_log10_or_na)
    result = result.sort_values("symbol").reset_index(drop=True)

    ordered = [
        "trade_date",
        "symbol",
        "industry_code",
        "industry_name",
        "industry_classification_snapshot_date",
        "industry_classification_mode",
        *industry_dummy_columns,
        *[spec.output_column for spec in index_specs],
        "total_market_cap_10k_yuan",
        "total_market_cap_rank",
        "total_market_cap_rank_pct",
        "total_market_cap_log10",
    ]
    return result.loc[:, ordered]


def _log10_or_na(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    return math.log10(float(value))


def _industry_dummy_column(level: str, industry_code: str) -> str:
    safe_code = re.sub(r"[^0-9A-Za-z]+", "_", industry_code).strip("_")
    return f"industry_sw_{level.lower()}_{safe_code}"


def _build_schema(
    *,
    industry_dummy_columns: Sequence[str],
    index_dummy_columns: Sequence[str],
    industry_level: str,
) -> pd.DataFrame:
    rows = [
        _schema_row("trade_date", "key", "Trading date", ""),
        _schema_row("symbol", "key", "A-share stock code with exchange suffix", ""),
        _schema_row("industry_code", "industry_label", f"Static SW2021 {industry_level} industry code", ""),
        _schema_row("industry_name", "industry_label", f"Static SW2021 {industry_level} industry name", ""),
        _schema_row(
            "industry_classification_snapshot_date",
            "metadata",
            "Static industry reference snapshot date",
            "",
        ),
        _schema_row("industry_classification_mode", "metadata", "Industry classification mode", ""),
    ]
    rows.extend(
        _schema_row(column, "industry_dummy", "Static SW2021 industry one-hot dummy", "")
        for column in industry_dummy_columns
    )
    rows.extend(
        _schema_row(column, "index_membership_dummy", "Point-in-time index membership one-hot dummy", "")
        for column in index_dummy_columns
    )
    rows.extend(
        [
            _schema_row(
                "total_market_cap_10k_yuan",
                "numeric_style_factor",
                "Raw total market capitalization from A-share daily metrics",
                FIELD_UNITS_RAW[MARKET_CAP_RAW_COLUMN],
            ),
            _schema_row(
                "total_market_cap_rank",
                "numeric_style_factor",
                "Cross-sectional ascending rank of total_market_cap_10k_yuan",
                "",
            ),
            _schema_row(
                "total_market_cap_rank_pct",
                "numeric_style_factor",
                "Cross-sectional ascending percentile rank of total_market_cap_10k_yuan",
                "",
            ),
            _schema_row(
                "total_market_cap_log10",
                "numeric_style_factor",
                "Base-10 log of positive total_market_cap_10k_yuan",
                "",
            ),
        ]
    )
    return pd.DataFrame(rows)


def _schema_row(column: str, role: str, description: str, unit: str) -> dict[str, object]:
    return {
        "column": column,
        "role": role,
        "unit": unit,
        "nullable": role not in {"key", "industry_dummy", "index_membership_dummy"},
        "description": description,
    }


def _build_quality_table(
    *,
    matrix_index: pd.DataFrame,
    index_availability: dict[str, dict[str, object]],
    industry_meta: dict[str, object],
    total_missing_market_cap: int,
    total_unclassified: int,
    duplicate_key_rows: int,
) -> pd.DataFrame:
    rows = [
        _quality_row(
            "daily_file_count",
            len(matrix_index) > 0,
            len(matrix_index),
            "style factor matrix daily files generated",
        ),
        _quality_row(
            "duplicate_symbol_trade_date",
            duplicate_key_rows == 0,
            duplicate_key_rows,
            "duplicate (symbol, trade_date) rows in generated daily files",
        ),
        _quality_row(
            "market_cap_available",
            total_missing_market_cap == 0,
            total_missing_market_cap,
            "rows with missing total_market_cap_10k_yuan",
            severity_if_fail="warning",
        ),
        _quality_row(
            "industry_classification_available",
            total_unclassified == 0,
            total_unclassified,
            "rows without a static SW industry classification",
            severity_if_fail="warning",
        ),
        _quality_row(
            "static_industry_reference_declared",
            industry_meta.get("historical_pit_industry") is False,
            industry_meta.get("classification_mode"),
            "industry reference should be explicitly static, not point-in-time historical",
        ),
        _quality_row(
            "data_only_source_declared",
            True,
            "generated_data_directory",
            "all inputs are read from generated data/ datasets rather than raw download directories",
            severity_if_fail="warning",
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
        "dataset": "style_factor_matrix",
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
    index_availability: dict[str, dict[str, object]],
    industry_meta: dict[str, object],
    industry_level: str,
    industry_dummy_columns: Sequence[str],
    index_dummy_columns: Sequence[str],
    asof_policy: AsofPolicy,
    requested_start: pd.Timestamp | None,
    requested_end: pd.Timestamp | None,
    effective_start: pd.Timestamp,
) -> dict[str, object]:
    clean_availability = {
        name: {key: value for key, value in item.items() if key != "first_usable_date_ts"}
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
    }
    for name, item in clean_availability.items():
        dataset = item.get("dataset")
        if dataset is not None:
            source_datasets[str(dataset)] = {
                "path": str(reader.dataset_path(str(dataset))),
                "role": "point_in_time_index_membership",
                "index_code": item.get("index_code"),
                "flag_column": item.get("flag_column"),
            }
    return {
        "dataset": "style_factor_matrix",
        "description": "Daily A-share style factor matrix for tree-model inputs.",
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
        "point_in_time": {
            "index_membership_asof_policy": asof_policy,
            "index_membership_source": "generated_constituent_weights_daily_asof",
            "industry_membership": "static_current_reference",
        },
        "availability": {"index_membership": clean_availability},
        "industry_reference": industry_meta,
        "features": {
            "industry_level": industry_level,
            "industry_dummy_columns": list(industry_dummy_columns),
            "index_dummy_columns": list(index_dummy_columns),
            "market_cap": {
                "raw_column": MARKET_CAP_RAW_COLUMN,
                "output_column": "total_market_cap_10k_yuan",
                "unit": FIELD_UNITS_RAW[MARKET_CAP_RAW_COLUMN],
                "transforms": ["rank_ascending", "rank_pct_ascending", "log10_positive"],
            },
        },
        "files": {
            name: {
                "path": str(path),
                "rows": row_counts.get(name.removesuffix(".csv")),
            }
            for name, path in files.items()
            if name.endswith(".csv")
        },
        "usage_note": (
            "Join by (trade_date, symbol). Industry dummies use the current static SW reference; "
            "they are not historical point-in-time industry memberships."
        ),
    }


def _build_readme(manifest: dict[str, object]) -> str:
    start = manifest["date_range"]["start"]
    end = manifest["date_range"]["end"]
    snapshot_date = manifest["industry_reference"].get("classification_snapshot_date")
    return f"""# Style Factor Matrix

This directory contains daily A-share style factor matrices from {start} to {end}.
It is built only from generated datasets under `{manifest["data_dir"]}`.

Each partitioned daily CSV is keyed by `(trade_date, symbol)` and contains:

- static SW industry one-hot columns from the current reference snapshot dated {snapshot_date};
- point-in-time CSI 300/500/1000/2000 membership one-hot columns;
- total market capitalization in 万元 plus ascending rank, percentile rank, and log10.

The industry columns intentionally use the static current reference exported in
`data/industry_sw_current_reference`. They are not historical point-in-time
industry memberships.
"""


def _format_optional_date(value: pd.Timestamp | None) -> object:
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _prepare_partition_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
