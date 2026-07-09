from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from finfact_io.config import PathLike, resolve_ashare_daily_dir, resolve_index_data_dir
from finfact_io.errors import DataFileNotFoundError, SchemaError
from finfact_io.readers.csv import parse_date_value, read_csv_file

SW_REFERENCE_SNAPSHOT_DATE = "2026-06-03"
SW_INDUSTRY_STANDARD = "SW2021"
STATIC_REFERENCE_MODE = "static_current_reference"
DEFAULT_OUTPUT_DIR = Path("data") / "industry_sw_current_reference"

SW_CLASSIFICATION_DIR = "申万行业分类"
SW_MEMBERS_DIR = "申万行业成分_每日更新"
SW_MEMBER_REQUIRED_COLUMNS = (
    "一级行业代码",
    "一级行业名称",
    "二级行业代码",
    "二级行业名称",
    "三级行业代码",
    "三级行业名称",
    "股票代码",
    "股票名称",
    "纳入日期",
)
SW_TAXONOMY_REQUIRED_COLUMNS = (
    "指数代码",
    "行业名称",
    "行业分级",
    "行业代码",
    "是否发布指数",
    "父级代码",
    "分类来源",
)


@dataclass(frozen=True)
class IndustrySwReferenceBuildReport:
    output_dir: Path
    row_counts: dict[str, int]
    files: dict[str, Path]


def build_industry_sw_reference_dataset(
    *,
    index_data_dir: PathLike | None = None,
    ashare_daily_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    snapshot_date: str | pd.Timestamp = SW_REFERENCE_SNAPSHOT_DATE,
) -> IndustrySwReferenceBuildReport:
    source_root = resolve_index_data_dir(index_data_dir)
    ashare_root = resolve_ashare_daily_dir(ashare_daily_dir)
    target = Path(output_dir).expanduser() if output_dir is not None else DEFAULT_OUTPUT_DIR
    target.mkdir(parents=True, exist_ok=True)

    normalized_snapshot_date = _format_date_value(snapshot_date)
    source_file = _resolve_sw_snapshot_file(source_root, normalized_snapshot_date)
    raw_snapshot = read_csv_file(source_file, required_columns=SW_MEMBER_REQUIRED_COLUMNS)
    taxonomy = _load_sw_taxonomy(source_root)
    current_snapshot = _build_current_snapshot(
        raw_snapshot,
        source_file=source_file,
        snapshot_date=normalized_snapshot_date,
    )
    taxonomy = _augment_taxonomy_from_snapshot(taxonomy, current_snapshot, source_file=source_file)
    edges = _build_matrix_edges(current_snapshot)
    quality = _build_quality_table(
        current_snapshot=current_snapshot,
        taxonomy=taxonomy,
        edges=edges,
        ashare_root=ashare_root,
        snapshot_date=normalized_snapshot_date,
    )

    paths = {
        "current_snapshot.csv": target / "current_snapshot.csv",
        "industry_taxonomy.csv": target / "industry_taxonomy.csv",
        "industry_matrix_edges.csv": target / "industry_matrix_edges.csv",
        "data_quality.csv": target / "data_quality.csv",
        "manifest.json": target / "manifest.json",
        "README.md": target / "README.md",
    }
    current_snapshot.to_csv(paths["current_snapshot.csv"], index=False)
    taxonomy.to_csv(paths["industry_taxonomy.csv"], index=False)
    edges.to_csv(paths["industry_matrix_edges.csv"], index=False)
    quality.to_csv(paths["data_quality.csv"], index=False)

    row_counts = {
        "current_snapshot": len(current_snapshot),
        "industry_taxonomy": len(taxonomy),
        "industry_matrix_edges": len(edges),
        "data_quality": len(quality),
    }
    manifest = _build_manifest(
        source_root=source_root,
        ashare_root=ashare_root,
        source_file=source_file,
        output_dir=target,
        row_counts=row_counts,
        files=paths,
        taxonomy=taxonomy,
        snapshot_date=normalized_snapshot_date,
    )
    paths["manifest.json"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["README.md"].write_text(_build_readme(manifest), encoding="utf-8")
    return IndustrySwReferenceBuildReport(output_dir=target, row_counts=row_counts, files=paths)


def build_industry_matrix(
    edges: pd.DataFrame,
    *,
    stocks: Sequence[str] | None = None,
    level: str = "L1",
) -> pd.DataFrame:
    _validate_level(level)
    _require_columns(edges, ["stock_code", "industry_level", "industry_code", "membership"])
    selected = edges[edges["industry_level"] == level].copy()
    if selected.empty:
        return pd.DataFrame(index=list(stocks or []))

    selected["membership"] = pd.to_numeric(selected["membership"], errors="coerce").fillna(0)
    matrix = selected.pivot_table(
        index="stock_code",
        columns="industry_code",
        values="membership",
        aggfunc="max",
        fill_value=0,
    )
    matrix = matrix.reindex(columns=sorted(selected["industry_code"].dropna().unique()), fill_value=0)
    if stocks is not None:
        matrix = matrix.reindex(list(stocks), fill_value=0)
    return matrix.astype(int)


def calculate_active_exposure(
    edges: pd.DataFrame,
    *,
    portfolio_weights: Mapping[str, float] | pd.Series,
    benchmark_weights: Mapping[str, float] | pd.Series,
    level: str = "L1",
    date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    _validate_level(level)
    _require_columns(
        edges,
        [
            "stock_code",
            "industry_level",
            "industry_code",
            "industry_name",
            "membership",
            "classification_snapshot_date",
            "classification_mode",
        ],
    )
    portfolio = _weights_to_series(portfolio_weights)
    benchmark = _weights_to_series(benchmark_weights)
    stocks = list(dict.fromkeys([*portfolio.index.astype(str), *benchmark.index.astype(str)]))
    matrix = build_industry_matrix(edges, stocks=stocks, level=level).astype(float)
    portfolio = portfolio.reindex(stocks, fill_value=0.0)
    benchmark = benchmark.reindex(stocks, fill_value=0.0)
    active = portfolio - benchmark

    portfolio_by_industry = matrix.T.dot(portfolio)
    benchmark_by_industry = matrix.T.dot(benchmark)
    active_by_industry = matrix.T.dot(active)
    portfolio_counts = matrix.mul((portfolio != 0).astype(int), axis=0).sum(axis=0).astype(int)
    benchmark_counts = matrix.mul((benchmark != 0).astype(int), axis=0).sum(axis=0).astype(int)

    metadata = (
        edges[edges["industry_level"] == level][
            ["industry_code", "industry_name", "classification_snapshot_date", "classification_mode"]
        ]
        .drop_duplicates("industry_code")
        .set_index("industry_code")
        .reindex(matrix.columns)
    )
    unclassified = matrix.sum(axis=1) == 0
    result = pd.DataFrame(
        {
            "date": _format_optional_date(date),
            "industry_standard": SW_INDUSTRY_STANDARD,
            "industry_level": level,
            "industry_code": matrix.columns,
            "industry_name": metadata["industry_name"].to_numpy(),
            "portfolio_weight": portfolio_by_industry.reindex(matrix.columns).round(12).to_numpy(),
            "benchmark_weight": benchmark_by_industry.reindex(matrix.columns).round(12).to_numpy(),
            "active_exposure": active_by_industry.reindex(matrix.columns).round(12).to_numpy(),
            "portfolio_stock_count": portfolio_counts.reindex(matrix.columns).to_numpy(),
            "benchmark_stock_count": benchmark_counts.reindex(matrix.columns).to_numpy(),
            "unclassified_portfolio_weight": round(float(portfolio[unclassified].sum()), 12),
            "unclassified_benchmark_weight": round(float(benchmark[unclassified].sum()), 12),
            "classification_snapshot_date": metadata["classification_snapshot_date"].to_numpy(),
            "classification_mode": metadata["classification_mode"].to_numpy(),
        }
    )
    return result.reset_index(drop=True)


def _resolve_sw_snapshot_file(root: Path, snapshot_date: str) -> Path:
    compact = snapshot_date.replace("-", "")
    expected = root / SW_MEMBERS_DIR / snapshot_date[:7] / f"申万行业成分_{compact}.csv"
    if expected.is_file():
        return expected
    candidates = sorted((root / SW_MEMBERS_DIR).glob(f"*/申万行业成分_{compact}.csv"))
    if candidates:
        return candidates[0]
    raise DataFileNotFoundError(f"SW member snapshot not found for {snapshot_date}: {expected}")


def _load_sw_taxonomy(root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for filename in (
        "申万行业分类_L1_SW2021.csv",
        "申万行业分类_L2_SW2021.csv",
        "申万行业分类_L3_SW2021.csv",
    ):
        path = root / SW_CLASSIFICATION_DIR / filename
        raw = read_csv_file(path, required_columns=SW_TAXONOMY_REQUIRED_COLUMNS)
        frame = pd.DataFrame(
            {
                "industry_standard": SW_INDUSTRY_STANDARD,
                "industry_level": raw["行业分级"],
                "industry_code": raw["指数代码"],
                "industry_name": raw["行业名称"],
                "classification_code": raw["行业代码"],
                "parent_classification_code": raw["父级代码"],
                "publishes_index": raw["是否发布指数"],
                "classification_source": raw["分类来源"],
                "taxonomy_source_status": "official",
                "source_file": str(path),
            }
        )
        frames.append(frame)
    taxonomy = pd.concat(frames, ignore_index=True)
    return taxonomy.sort_values(["industry_level", "industry_code"]).reset_index(drop=True)


def _augment_taxonomy_from_snapshot(
    taxonomy: pd.DataFrame,
    current_snapshot: pd.DataFrame,
    *,
    source_file: Path,
) -> pd.DataFrame:
    existing_codes = set(taxonomy["industry_code"].dropna().astype(str))
    inferred_rows: list[dict[str, object]] = []
    level_specs = (
        ("L1", "industry_level1_code", "industry_level1", None),
        ("L2", "industry_level2_code", "industry_level2", "industry_level1_code"),
        ("L3", "industry_level3_code", "industry_level3", "industry_level2_code"),
    )
    for level, code_col, name_col, parent_code_col in level_specs:
        missing = current_snapshot[~current_snapshot[code_col].astype(str).isin(existing_codes)]
        if missing.empty:
            continue
        for _, row in missing.drop_duplicates(code_col).iterrows():
            industry_code = row[code_col]
            industry_name = row[name_col]
            parent_classification_code = "0"
            if parent_code_col is not None:
                parent_classification_code = _classification_code_for_industry(taxonomy, row[parent_code_col])
            same_name = _same_name_taxonomy_row(
                taxonomy,
                level=level,
                industry_name=industry_name,
                parent_classification_code=parent_classification_code,
            )
            classification_code = (
                same_name["classification_code"] if same_name is not None else pd.NA
            )
            publishes_index = same_name["publishes_index"] if same_name is not None else pd.NA
            classification_source = (
                same_name["classification_source"] if same_name is not None else SW_INDUSTRY_STANDARD
            )
            inferred_rows.append(
                {
                    "industry_standard": SW_INDUSTRY_STANDARD,
                    "industry_level": level,
                    "industry_code": industry_code,
                    "industry_name": industry_name,
                    "classification_code": classification_code,
                    "parent_classification_code": parent_classification_code,
                    "publishes_index": publishes_index,
                    "classification_source": classification_source,
                    "taxonomy_source_status": "snapshot_inferred",
                    "source_file": str(source_file),
                }
            )
            existing_codes.add(str(industry_code))
    if not inferred_rows:
        return taxonomy
    augmented = pd.concat([taxonomy, pd.DataFrame(inferred_rows)], ignore_index=True)
    return augmented.sort_values(["industry_level", "industry_code"]).reset_index(drop=True)


def _classification_code_for_industry(taxonomy: pd.DataFrame, industry_code: object) -> object:
    matches = taxonomy[taxonomy["industry_code"].astype(str) == str(industry_code)]
    if matches.empty:
        return pd.NA
    return matches.iloc[0]["classification_code"]


def _same_name_taxonomy_row(
    taxonomy: pd.DataFrame,
    *,
    level: str,
    industry_name: object,
    parent_classification_code: object,
) -> pd.Series | None:
    matches = taxonomy[
        (taxonomy["industry_level"].astype(str) == level)
        & (taxonomy["industry_name"].astype(str) == str(industry_name))
        & (taxonomy["parent_classification_code"].astype(str) == str(parent_classification_code))
    ]
    if matches.empty:
        return None
    return matches.iloc[0]


def _build_current_snapshot(
    raw: pd.DataFrame,
    *,
    source_file: Path,
    snapshot_date: str,
) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "stock_code": raw["股票代码"],
            "stock_name": raw["股票名称"],
            "industry_standard": SW_INDUSTRY_STANDARD,
            "industry_level1_code": raw["一级行业代码"],
            "industry_level1": raw["一级行业名称"],
            "industry_level2_code": raw["二级行业代码"],
            "industry_level2": raw["二级行业名称"],
            "industry_level3_code": raw["三级行业代码"],
            "industry_level3": raw["三级行业名称"],
            "effective_date": _format_date_series(raw["纳入日期"]),
            "classification_snapshot_date": snapshot_date,
            "classification_mode": STATIC_REFERENCE_MODE,
            "source_file": str(source_file),
        }
    )
    missing_industry = result[
        [
            "industry_level1_code",
            "industry_level1",
            "industry_level2_code",
            "industry_level2",
            "industry_level3_code",
            "industry_level3",
        ]
    ].isna().any(axis=1)
    result["quality_status"] = "complete"
    result.loc[missing_industry, "quality_status"] = "incomplete"
    return result.sort_values("stock_code").reset_index(drop=True)


def _build_matrix_edges(current_snapshot: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for level, code_col, name_col in (
        ("L1", "industry_level1_code", "industry_level1"),
        ("L2", "industry_level2_code", "industry_level2"),
        ("L3", "industry_level3_code", "industry_level3"),
    ):
        rows.append(
            pd.DataFrame(
                {
                    "stock_code": current_snapshot["stock_code"],
                    "stock_name": current_snapshot["stock_name"],
                    "industry_standard": current_snapshot["industry_standard"],
                    "industry_level": level,
                    "industry_code": current_snapshot[code_col],
                    "industry_name": current_snapshot[name_col],
                    "membership": 1,
                    "classification_snapshot_date": current_snapshot["classification_snapshot_date"],
                    "classification_mode": current_snapshot["classification_mode"],
                }
            )
        )
    return pd.concat(rows, ignore_index=True).sort_values(["stock_code", "industry_level"]).reset_index(drop=True)


def _build_quality_table(
    *,
    current_snapshot: pd.DataFrame,
    taxonomy: pd.DataFrame,
    edges: pd.DataFrame,
    ashare_root: Path,
    snapshot_date: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    duplicate_stocks = int(current_snapshot.duplicated("stock_code", keep=False).sum())
    rows.append(
        _quality_row(
            "current_snapshot_unique_stock",
            duplicate_stocks == 0,
            duplicate_stocks,
            "duplicate stock_code rows in current_snapshot.csv",
            affected_date=snapshot_date,
        )
    )

    industry_columns = [
        "industry_level1_code",
        "industry_level1",
        "industry_level2_code",
        "industry_level2",
        "industry_level3_code",
        "industry_level3",
    ]
    missing_industry = int(current_snapshot[industry_columns].isna().any(axis=1).sum())
    rows.append(
        _quality_row(
            "current_snapshot_no_missing_l1_l2_l3",
            missing_industry == 0,
            missing_industry,
            "rows with missing L1/L2/L3 industry code or name",
            affected_date=snapshot_date,
        )
    )

    taxonomy_codes = set(taxonomy["industry_code"].dropna().astype(str))
    missing_taxonomy = _missing_taxonomy_count(current_snapshot, taxonomy_codes)
    rows.append(
        _quality_row(
            "current_snapshot_taxonomy_codes_exist",
            missing_taxonomy == 0,
            missing_taxonomy,
            "snapshot industry codes absent from industry_taxonomy.csv",
            affected_date=snapshot_date,
        )
    )

    parent_inconsistent = _parent_inconsistency_count(current_snapshot, taxonomy)
    rows.append(
        _quality_row(
            "current_snapshot_taxonomy_parent_consistent",
            parent_inconsistent == 0,
            parent_inconsistent,
            "L2 parent must match L1 classification code; L3 parent must match L2 classification code",
            affected_date=snapshot_date,
        )
    )

    duplicate_edges = int(edges.duplicated(["stock_code", "industry_level"], keep=False).sum())
    rows.append(
        _quality_row(
            "matrix_edges_one_membership_per_stock_level",
            duplicate_edges == 0,
            duplicate_edges,
            "duplicate membership rows for the same stock_code and industry_level",
            affected_date=snapshot_date,
        )
    )

    expected_edges = len(current_snapshot) * 3
    rows.append(
        _quality_row(
            "matrix_edges_expected_row_count",
            len(edges) == expected_edges,
            f"{len(edges)}/{expected_edges}",
            "industry_matrix_edges.csv must contain one L1, one L2, and one L3 row per stock",
            affected_date=snapshot_date,
        )
    )

    rows.append(_listed_coverage_quality(current_snapshot, ashare_root=ashare_root, snapshot_date=snapshot_date))

    mode_ok = (
        set(current_snapshot["classification_snapshot_date"].dropna().astype(str)) == {snapshot_date}
        and set(current_snapshot["classification_mode"].dropna().astype(str)) == {STATIC_REFERENCE_MODE}
        and set(edges["classification_snapshot_date"].dropna().astype(str)) == {snapshot_date}
        and set(edges["classification_mode"].dropna().astype(str)) == {STATIC_REFERENCE_MODE}
    )
    rows.append(
        _quality_row(
            "static_reference_mode_declared",
            mode_ok,
            STATIC_REFERENCE_MODE if mode_ok else "invalid",
            "all records must declare the static current reference classification mode",
            affected_date=snapshot_date,
        )
    )
    return pd.DataFrame(rows)


def _quality_row(
    check: str,
    passed: bool,
    observed_value: object,
    detail: str,
    *,
    affected_date: str,
) -> dict[str, object]:
    return {
        "dataset": "industry_sw_current_reference",
        "check": check,
        "status": "pass" if passed else "fail",
        "severity": "info" if passed else "error",
        "affected_date": affected_date,
        "observed_value": observed_value,
        "detail": detail,
    }


def _listed_coverage_quality(
    current_snapshot: pd.DataFrame,
    *,
    ashare_root: Path,
    snapshot_date: str,
) -> dict[str, object]:
    stocks_file = ashare_root / "股票列表.csv"
    if not stocks_file.is_file():
        return {
            "dataset": "industry_sw_current_reference",
            "check": "listed_stock_coverage",
            "status": "warning",
            "severity": "warning",
            "affected_date": snapshot_date,
            "observed_value": "unavailable",
            "detail": f"listed stock file not found: {stocks_file}",
        }
    listed = read_csv_file(stocks_file, required_columns=("TS代码",))
    listed_codes = set(listed["TS代码"].dropna().astype(str))
    snapshot_codes = set(current_snapshot["stock_code"].dropna().astype(str))
    covered = len(listed_codes & snapshot_codes)
    missing = len(listed_codes - snapshot_codes)
    extra = len(snapshot_codes - listed_codes)
    return _quality_row(
        "listed_stock_coverage",
        missing == 0,
        f"{covered}/{len(listed_codes)}",
        f"current listed stocks covered by snapshot; missing={missing}, snapshot_extra_codes={extra}",
        affected_date=snapshot_date,
    )


def _missing_taxonomy_count(current_snapshot: pd.DataFrame, taxonomy_codes: set[str]) -> int:
    missing = 0
    for column in ("industry_level1_code", "industry_level2_code", "industry_level3_code"):
        in_taxonomy = current_snapshot[column].dropna().astype(str).isin(taxonomy_codes)
        missing += int((~in_taxonomy).sum())
    return missing


def _parent_inconsistency_count(current_snapshot: pd.DataFrame, taxonomy: pd.DataFrame) -> int:
    by_code = taxonomy.set_index("industry_code")
    inconsistent = 0
    for _, row in current_snapshot.iterrows():
        l1 = row["industry_level1_code"]
        l2 = row["industry_level2_code"]
        l3 = row["industry_level3_code"]
        if pd.isna(l1) or pd.isna(l2) or pd.isna(l3):
            inconsistent += 1
            continue
        if l1 not in by_code.index or l2 not in by_code.index or l3 not in by_code.index:
            inconsistent += 1
            continue
        l1_classification = by_code.loc[l1, "classification_code"]
        l2_classification = by_code.loc[l2, "classification_code"]
        l2_parent = by_code.loc[l2, "parent_classification_code"]
        l3_parent = by_code.loc[l3, "parent_classification_code"]
        if str(l2_parent) != str(l1_classification) or str(l3_parent) != str(l2_classification):
            inconsistent += 1
    return inconsistent


def _build_manifest(
    *,
    source_root: Path,
    ashare_root: Path,
    source_file: Path,
    output_dir: Path,
    row_counts: dict[str, int],
    files: dict[str, Path],
    taxonomy: pd.DataFrame,
    snapshot_date: str,
) -> dict[str, object]:
    inferred_taxonomy = taxonomy[taxonomy["taxonomy_source_status"] == "snapshot_inferred"]
    return {
        "dataset": "industry_sw_current_reference",
        "description": "Static SW2021 current industry lookup for historical exposure and constraint analysis.",
        "industry_standard": SW_INDUSTRY_STANDARD,
        "classification_snapshot_date": snapshot_date,
        "classification_mode": STATIC_REFERENCE_MODE,
        "historical_pit_industry": False,
        "taxonomy_inferred_from_snapshot": {
            "count": int(len(inferred_taxonomy)),
            "codes": inferred_taxonomy[
                [
                    "industry_level",
                    "industry_code",
                    "industry_name",
                    "classification_code",
                    "parent_classification_code",
                ]
            ].to_dict("records"),
        },
        "source_root": str(source_root),
        "ashare_daily_root": str(ashare_root),
        "source_file": str(source_file),
        "output_dir": str(output_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            name: {
                "path": str(path),
                "rows": row_counts.get(name.removesuffix(".csv"), None),
            }
            for name, path in files.items()
            if name.endswith(".csv")
        },
        "usage_note": (
            "Use this as a static 2026-06-03 SW2021 industry reference for all dates. "
            "It is not a historical point-in-time industry membership dataset."
        ),
    }


def _build_readme(manifest: dict[str, object]) -> str:
    snapshot_date = manifest["classification_snapshot_date"]
    return f"""# SW2021 Current Industry Reference

This directory contains a static SW2021 industry lookup based only on the
申万行业成分 snapshot dated {snapshot_date}.

The data is intended for historical industry exposure and constraint analysis
where every date uses the same current industry classification. It is not a
historical point-in-time industry membership dataset.

Files:

- `current_snapshot.csv`: one row per stock in the {snapshot_date} SW snapshot.
- `industry_taxonomy.csv`: SW2021 L1/L2/L3 industry taxonomy.
- `industry_matrix_edges.csv`: long-form L1/L2/L3 matrix memberships.
- `data_quality.csv`: validation checks for uniqueness, taxonomy consistency,
  listed-stock coverage, and static-reference metadata.
- `manifest.json`: machine-readable source and methodology metadata.

If the current snapshot contains an industry code absent from the official
taxonomy files, the snapshot code is preserved and added to
`industry_taxonomy.csv` with `taxonomy_source_status=snapshot_inferred`.
"""


def _weights_to_series(weights: Mapping[str, float] | pd.Series) -> pd.Series:
    series = weights.copy() if isinstance(weights, pd.Series) else pd.Series(weights, dtype="float64")
    series.index = series.index.astype(str)
    return pd.to_numeric(series, errors="coerce").fillna(0.0).groupby(level=0).sum()


def _validate_level(level: str) -> None:
    if level not in {"L1", "L2", "L3"}:
        raise ValueError("level must be one of: 'L1', 'L2', 'L3'")


def _require_columns(df: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise SchemaError(f"DataFrame is missing required columns: {missing}")


def _format_date_value(value: str | pd.Timestamp) -> str:
    parsed = parse_date_value(value)
    if parsed is None:
        raise ValueError("snapshot_date must be a valid date")
    return parsed.strftime("%Y-%m-%d")


def _format_optional_date(value: str | pd.Timestamp | None) -> object:
    if value is None:
        return pd.NA
    parsed = parse_date_value(value)
    return pd.NA if parsed is None else parsed.strftime("%Y-%m-%d")


def _format_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime("%Y-%m-%d")
