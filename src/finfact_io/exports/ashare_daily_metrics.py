from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from finfact_io.config import PathLike, resolve_ashare_daily_dir
from finfact_io.fields import DAILY_METRIC_ALIASES, FIELD_UNITS_RAW, standardize_columns
from finfact_io.readers.csv import parse_date_value, read_csv_file, read_csv_bytes

DEFAULT_OUTPUT_DIR = Path("data") / "ashare_daily_metrics"
DEFAULT_START_DATE = "1990-12-19"
DEFAULT_END_DATE = "2026-06-03"
INCREMENTAL_DAILY_DIR = Path("增量数据") / "每日指标"
DAILY_METRICS_ARCHIVE = "每日指标.zip"

RAW_DAILY_METRIC_COLUMNS = tuple(DAILY_METRIC_ALIASES.keys())
STANDARD_DAILY_METRIC_COLUMNS = tuple(DAILY_METRIC_ALIASES.values())


@dataclass(frozen=True)
class AShareDailyMetricsBuildReport:
    output_dir: Path
    row_counts: dict[str, int]
    files: dict[str, Path]


def build_ashare_daily_metrics_dataset(
    *,
    ashare_daily_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = DEFAULT_START_DATE,
    end: str | pd.Timestamp | None = DEFAULT_END_DATE,
) -> AShareDailyMetricsBuildReport:
    source_root = resolve_ashare_daily_dir(ashare_daily_dir)
    target = Path(output_dir).expanduser() if output_dir is not None else DEFAULT_OUTPUT_DIR
    target.mkdir(parents=True, exist_ok=True)
    daily_dir = target / "daily_metrics"
    if daily_dir.exists():
        shutil.rmtree(daily_dir)
    daily_dir.mkdir(parents=True, exist_ok=True)

    start_ts = parse_date_value(start)
    end_ts = parse_date_value(end)
    expected_trading_dates = _trading_calendar_dates(source_root, start=start_ts, end=end_ts)
    source_files, excluded_non_trading_dates = _list_incremental_daily_files(
        source_root,
        start=start_ts,
        end=end_ts,
        allowed_dates=expected_trading_dates,
    )
    schema = _build_schema()
    columns_hash = _columns_hash(STANDARD_DAILY_METRIC_COLUMNS)

    index_rows: list[dict[str, object]] = []
    filename_mismatch_files = 0
    column_mismatch_files = 0
    total_duplicate_rows = 0
    symbols_without_suffix = 0
    total_rows = 0

    for trade_date, source_path in source_files:
        raw = read_csv_file(source_path, required_columns=RAW_DAILY_METRIC_COLUMNS)
        standard = standardize_columns(raw, "daily_metrics")
        standard = standard.loc[:, list(STANDARD_DAILY_METRIC_COLUMNS)].copy()

        trade_date_text = trade_date.strftime("%Y-%m-%d")
        date_values = pd.to_datetime(standard["trade_date"]).dt.strftime("%Y-%m-%d")
        filename_matches = bool((date_values == trade_date_text).all())
        if not filename_matches:
            filename_mismatch_files += 1
        if tuple(standard.columns) != STANDARD_DAILY_METRIC_COLUMNS:
            column_mismatch_files += 1

        standard["symbol"] = standard["symbol"].astype("string")
        standard["trade_date"] = date_values
        standard = standard.sort_values("symbol").reset_index(drop=True)
        duplicate_key_rows = int(standard.duplicated(["symbol", "trade_date"], keep=False).sum())
        total_duplicate_rows += duplicate_key_rows
        has_exchange_suffix = standard["symbol"].astype(str).str.contains(".", regex=False)
        symbols_without_suffix += int((~has_exchange_suffix).sum())
        total_rows += len(standard)

        month_dir = daily_dir / trade_date.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        output_path = month_dir / f"{trade_date_text}.csv"
        standard.to_csv(output_path, index=False)

        quality_status = (
            "pass"
            if filename_matches and duplicate_key_rows == 0 and tuple(standard.columns) == STANDARD_DAILY_METRIC_COLUMNS
            else "fail"
        )
        index_rows.append(
            {
                "date": trade_date_text,
                "file_path": str(output_path.relative_to(target)),
                "rows": len(standard),
                "unique_symbols": int(standard["symbol"].nunique()),
                "duplicate_key_rows": duplicate_key_rows,
                "source_path": str(source_path),
                "source_kind": "incremental_daily_file",
                "columns_hash": columns_hash,
                "quality_status": quality_status,
            }
        )

    daily_index = pd.DataFrame(index_rows)
    paths = {
        "daily_metrics.csv": target / "daily_metrics.csv",
        "schema.csv": target / "schema.csv",
        "data_quality.csv": target / "data_quality.csv",
        "manifest.json": target / "manifest.json",
        "README.md": target / "README.md",
    }
    daily_index.to_csv(paths["daily_metrics.csv"], index=False)
    schema.to_csv(paths["schema.csv"], index=False)
    quality = _build_quality_table(
        source_root=source_root,
        daily_index=daily_index,
        start=start_ts,
        end=end_ts,
        expected_trading_dates=expected_trading_dates,
        excluded_non_trading_dates=excluded_non_trading_dates,
        filename_mismatch_files=filename_mismatch_files,
        column_mismatch_files=column_mismatch_files,
        total_duplicate_rows=total_duplicate_rows,
        symbols_without_suffix=symbols_without_suffix,
    )
    quality.to_csv(paths["data_quality.csv"], index=False)

    row_counts = {
        "daily_metrics": len(daily_index),
        "daily_metric_rows": total_rows,
        "schema": len(schema),
        "data_quality": len(quality),
    }
    sample_reconciliation = _sample_zip_reconciliation(
        source_root=source_root,
        target=target,
        daily_index=daily_index,
    )
    _replace_quality_row(paths["data_quality.csv"], sample_reconciliation)
    quality = pd.read_csv(paths["data_quality.csv"])
    row_counts["data_quality"] = len(quality)

    manifest = _build_manifest(
        source_root=source_root,
        output_dir=target,
        row_counts=row_counts,
        files=paths,
        daily_index=daily_index,
        start=start_ts,
        end=end_ts,
    )
    paths["manifest.json"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["README.md"].write_text(_build_readme(manifest), encoding="utf-8")

    return AShareDailyMetricsBuildReport(output_dir=target, row_counts=row_counts, files=paths)


def _list_incremental_daily_files(
    root: Path,
    *,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    allowed_dates: set[str] | None = None,
) -> tuple[list[tuple[pd.Timestamp, Path]], list[str]]:
    daily_root = root / INCREMENTAL_DAILY_DIR
    files: list[tuple[pd.Timestamp, Path]] = []
    excluded_non_trading_dates: list[str] = []
    for path in sorted(daily_root.glob("*/*.csv")):
        if not path.stem.isdigit() or len(path.stem) != 8:
            continue
        trade_date = parse_date_value(path.stem)
        if trade_date is None:
            continue
        if start is not None and trade_date < start:
            continue
        if end is not None and trade_date > end:
            continue
        trade_date_text = trade_date.strftime("%Y-%m-%d")
        if allowed_dates is not None and trade_date_text not in allowed_dates:
            excluded_non_trading_dates.append(trade_date_text)
            continue
        files.append((trade_date, path))
    return files, excluded_non_trading_dates


def _build_schema() -> pd.DataFrame:
    descriptions = {
        "symbol": "A-share stock code with exchange suffix",
        "trade_date": "Trading date",
        "open": "Open price",
        "high": "High price",
        "low": "Low price",
        "close": "Close price",
        "previous_close": "Previous close price",
        "change": "Price change",
        "pct_change": "Percent change",
        "volume": "Trading volume",
        "amount": "Trading amount",
        "turnover_rate": "Turnover rate",
        "free_float_turnover_rate": "Free-float turnover rate",
        "volume_ratio": "Volume ratio",
        "pe": "Price earnings ratio",
        "pe_ttm": "TTM price earnings ratio",
        "pb": "Price book ratio",
        "ps": "Price sales ratio",
        "ps_ttm": "TTM price sales ratio",
        "dividend_yield": "Dividend yield",
        "dividend_yield_ttm": "TTM dividend yield",
        "total_share_capital": "Total share capital",
        "float_share_capital": "Float share capital",
        "free_float_share_capital": "Free-float share capital",
        "total_market_cap": "Total market capitalization",
        "float_market_cap": "Float market capitalization",
    }
    rows: list[dict[str, object]] = []
    for raw_column, standard_column in DAILY_METRIC_ALIASES.items():
        rows.append(
            {
                "raw_column": raw_column,
                "standard_column": standard_column,
                "unit": FIELD_UNITS_RAW.get(raw_column, ""),
                "dtype": "string" if standard_column in {"symbol", "trade_date"} else "float64",
                "nullable": True,
                "description": descriptions.get(standard_column, ""),
            }
        )
    return pd.DataFrame(rows)


def _build_quality_table(
    *,
    source_root: Path,
    daily_index: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    expected_trading_dates: set[str] | None,
    excluded_non_trading_dates: list[str],
    filename_mismatch_files: int,
    column_mismatch_files: int,
    total_duplicate_rows: int,
    symbols_without_suffix: int,
) -> pd.DataFrame:
    date_set = set(daily_index["date"].astype(str)) if not daily_index.empty else set()
    expected_dates = expected_trading_dates
    missing_calendar_days = len(expected_dates - date_set) if expected_dates is not None else 0
    extra_generated_days = len(date_set - expected_dates) if expected_dates is not None else 0
    start_text = _format_date(start)
    end_text = _format_date(end)
    first_date = daily_index["date"].min() if not daily_index.empty else None
    last_date = daily_index["date"].max() if not daily_index.empty else None
    expected_first_date = min(expected_dates) if expected_dates else None
    expected_last_date = max(expected_dates) if expected_dates else None
    if expected_dates is None:
        date_range_coverage_passed = (
            missing_calendar_days == 0
            and (start is None or first_date == start_text)
            and (end is None or last_date == end_text)
        )
    else:
        date_range_coverage_passed = (
            missing_calendar_days == 0
            and (not expected_dates or (first_date == expected_first_date and last_date == expected_last_date))
        )
    excluded_sample = ",".join(excluded_non_trading_dates[:10])
    excluded_detail = "source files outside SSE trading calendar are excluded from generated daily files"
    if excluded_sample:
        excluded_detail += f"; sample={excluded_sample}"
    rows = [
        _quality_row("daily_file_count", len(daily_index) > 0, len(daily_index), "daily metric files generated"),
        _quality_row(
            "date_range_coverage",
            date_range_coverage_passed,
            (
                f"first={first_date}, last={last_date}, expected_first={expected_first_date}, "
                f"expected_last={expected_last_date}, missing_calendar_days={missing_calendar_days}"
            ),
            "generated date files should cover requested SSE trading dates",
        ),
        _quality_row(
            "generated_dates_within_calendar",
            extra_generated_days == 0,
            extra_generated_days,
            "generated date files should not include non-trading SSE calendar dates",
        ),
        _quality_row(
            "non_trading_source_files_excluded",
            True,
            len(excluded_non_trading_dates),
            excluded_detail,
            severity="warning" if excluded_non_trading_dates else "info",
        ),
        _quality_row(
            "filename_matches_trade_date",
            filename_mismatch_files == 0,
            filename_mismatch_files,
            "files where trade_date values differ from the filename date",
        ),
        _quality_row(
            "columns_match_schema",
            column_mismatch_files == 0,
            column_mismatch_files,
            "files whose standardized columns differ from schema.csv",
        ),
        _quality_row(
            "duplicate_symbol_trade_date",
            total_duplicate_rows == 0,
            total_duplicate_rows,
            "duplicate (symbol, trade_date) rows across daily files",
        ),
        _quality_row(
            "symbol_is_string",
            symbols_without_suffix == 0,
            symbols_without_suffix,
            "symbols without an exchange suffix after standardization",
        ),
        _quality_row(
            "latest_date_available",
            len(daily_index) > 0,
            daily_index["date"].max() if not daily_index.empty else None,
            "latest generated daily metric date",
        ),
        _quality_row(
            "sample_zip_reconciliation",
            True,
            "pending",
            "sample row reconciles with 每日指标.zip",
        ),
    ]
    return pd.DataFrame(rows)


def _sample_zip_reconciliation(*, source_root: Path, target: Path, daily_index: pd.DataFrame) -> dict[str, object]:
    archive_path = source_root / DAILY_METRICS_ARCHIVE
    if not archive_path.is_file() or daily_index.empty:
        return _quality_row(
            "sample_zip_reconciliation",
            False,
            "unavailable",
            f"archive unavailable or no generated rows: {archive_path}",
            severity="warning",
        )
    with zipfile.ZipFile(archive_path) as archive:
        for _, index_row in daily_index.head(10).iterrows():
            daily = _read_standard_daily_csv(target / index_row["file_path"])
            for _, sample_row in daily.head(10).iterrows():
                member = f"{sample_row['symbol']}.csv"
                if member not in archive.namelist():
                    continue
                zip_df = read_csv_bytes(
                    archive.read(member),
                    source=f"{archive_path}:{member}",
                    required_columns=RAW_DAILY_METRIC_COLUMNS,
                )
                standard_zip = standardize_columns(zip_df, "daily_metrics")
                standard_zip = standard_zip.loc[:, list(STANDARD_DAILY_METRIC_COLUMNS)].copy()
                standard_zip["trade_date"] = pd.to_datetime(standard_zip["trade_date"]).dt.strftime("%Y-%m-%d")
                matched = standard_zip[
                    (standard_zip["symbol"].astype(str) == str(sample_row["symbol"]))
                    & (standard_zip["trade_date"].astype(str) == str(sample_row["trade_date"]))
                ]
                if matched.empty:
                    continue
                left = sample_row.loc[list(STANDARD_DAILY_METRIC_COLUMNS)]
                right = matched.iloc[0].loc[list(STANDARD_DAILY_METRIC_COLUMNS)]
                equal = _rows_equal(left, right)
                return _quality_row(
                    "sample_zip_reconciliation",
                    equal,
                    f"{sample_row['symbol']}@{sample_row['trade_date']}",
                    "sample generated row reconciles with 每日指标.zip",
                )
    return _quality_row(
        "sample_zip_reconciliation",
        False,
        "no_comparable_sample",
        "no generated sample row was found in 每日指标.zip",
        severity="warning",
    )


def _replace_quality_row(path: Path, replacement: dict[str, object]) -> None:
    quality = pd.read_csv(path)
    quality = quality[quality["check"] != replacement["check"]]
    quality = pd.concat([quality, pd.DataFrame([replacement])], ignore_index=True)
    quality.to_csv(path, index=False)


def _rows_equal(left: pd.Series, right: pd.Series) -> bool:
    for column in STANDARD_DAILY_METRIC_COLUMNS:
        left_value = left[column]
        right_value = right[column]
        if pd.isna(left_value) and pd.isna(right_value):
            continue
        if column == "trade_date":
            if str(left_value) != str(right_value):
                return False
            continue
        if column == "symbol":
            if str(left_value) != str(right_value):
                return False
            continue
        left_numeric = pd.to_numeric(pd.Series([left_value]), errors="coerce").iloc[0]
        right_numeric = pd.to_numeric(pd.Series([right_value]), errors="coerce").iloc[0]
        if pd.isna(left_numeric) and pd.isna(right_numeric):
            continue
        if abs(float(left_numeric) - float(right_numeric)) > 1e-9:
            return False
    return True


def _trading_calendar_dates(
    source_root: Path,
    *,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> set[str] | None:
    calendar_path = source_root / "交易日历.csv"
    if not calendar_path.is_file():
        return None
    calendar = read_csv_file(calendar_path, required_columns=("交易所", "日期", "是否交易"))
    calendar = calendar[(calendar["交易所"] == "SSE") & (calendar["是否交易"] == "交易")]
    calendar_dates = pd.to_datetime(calendar["日期"])
    if start is not None:
        calendar = calendar[calendar_dates >= start]
        calendar_dates = calendar_dates[calendar_dates >= start]
    if end is not None:
        calendar = calendar[calendar_dates <= end]
        calendar_dates = calendar_dates[calendar_dates <= end]
    return set(calendar_dates.dt.strftime("%Y-%m-%d"))


def _read_standard_daily_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"symbol": "string"})
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    return df


def _build_manifest(
    *,
    source_root: Path,
    output_dir: Path,
    row_counts: dict[str, int],
    files: dict[str, Path],
    daily_index: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> dict[str, object]:
    return {
        "dataset": "ashare_daily_metrics",
        "description": "All A-share daily metrics organized by trading day with standard English columns.",
        "column_mode": "standard_english",
        "date_range": {
            "start": daily_index["date"].min() if not daily_index.empty else _format_date(start),
            "end": daily_index["date"].max() if not daily_index.empty else _format_date(end),
        },
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "source_policy": {
            "primary": "incremental_daily_files",
            "primary_path": str(source_root / INCREMENTAL_DAILY_DIR),
            "zip_archive": str(source_root / DAILY_METRICS_ARCHIVE),
            "zip_usage": "sample_reconciliation_only",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            name: {"path": str(path), "rows": row_counts.get(name.removesuffix(".csv"))}
            for name, path in files.items()
            if name.endswith(".csv")
        },
        "daily_metrics_partitioning": "daily_metrics/YYYY-MM/YYYY-MM-DD.csv",
    }


def _build_readme(manifest: dict[str, object]) -> str:
    return f"""# A-share Daily Metrics

This directory contains all A-share daily metrics organized by trading day.

Date range: {manifest["date_range"]["start"]} to {manifest["date_range"]["end"]}

The physical files use standard English columns and are partitioned as:

`daily_metrics/YYYY-MM/YYYY-MM-DD.csv`

`daily_metrics.csv` is the date index. The source is
`增量数据/每日指标`; `每日指标.zip` is used only for sample reconciliation.
"""


def _quality_row(
    check: str,
    passed: bool,
    observed_value: object,
    detail: str,
    *,
    severity: str | None = None,
) -> dict[str, object]:
    status = "pass" if passed else "fail"
    return {
        "dataset": "ashare_daily_metrics",
        "check": check,
        "status": status,
        "severity": severity or ("info" if passed else "error"),
        "observed_value": observed_value,
        "detail": detail,
    }


def _columns_hash(columns: Iterable[str]) -> str:
    return hashlib.sha256(",".join(columns).encode("utf-8")).hexdigest()[:16]


def _format_date(value: pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d")
