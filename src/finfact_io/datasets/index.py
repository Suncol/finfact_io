from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Literal

import pandas as pd

from finfact_io.datasets.common import (
    ColumnMode,
    SourceMode,
    add_source_columns,
    combine_prefer_incremental,
    filter_date_range,
    finalize_columns,
)
from finfact_io.errors import ArchiveModeError, DataFileNotFoundError, DataRootNotFoundError
from finfact_io.readers.csv import parse_date_value, read_csv_file
from finfact_io.readers.zip_csv import ZipCsvReader

ArchiveMode = Literal["lazy", "extract"]
ValidationMode = Literal["none", "sample", "full"]
Frequency = Literal["day", "week", "month"]
AvailableIndexDataset = Literal["all", "basic_info", "bars", "market_metrics"]
AvailableFrequency = Literal["all", "day", "week", "month"]

BASIC_INFO_FILES: dict[str, str] = {
    "msci": "指数基本信息_MSCI指数.csv",
    "sse": "指数基本信息_上交所指数.csv",
    "csi": "指数基本信息_中证指数.csv",
    "cicc": "指数基本信息_中金指数.csv",
    "other": "指数基本信息_其他指数.csv",
    "szse": "指数基本信息_深交所指数.csv",
    "sw": "指数基本信息_申万指数.csv",
}

BAR_ARCHIVES: dict[str, str] = {
    "day": "指数日线行情.zip",
    "week": "指数周线行情.zip",
    "month": "指数月线行情.zip",
}

MARKET_METRICS_DIR = "大盘指数每日指标"
INCREMENTAL_DIR = "增量数据"
INDEX_DAILY_INCREMENTAL_DIR = "指数日线行情"
MARKET_METRICS_INCREMENTAL_DIR = "大盘指数每日指标"

INDEX_BASIC_COLUMNS = ("指数代码", "简称", "市场", "发布方", "指数类别", "基期", "基点", "发布日期")
INDEX_BAR_COLUMNS = ("指数代码", "交易日期")
MARKET_METRIC_COLUMNS = ("指数代码", "交易日期")
AVAILABLE_COLUMNS = (
    "指数代码",
    "数据集",
    "频率",
    "来源",
    "信息来源",
    "有基本信息",
    "有日线行情",
    "有周线行情",
    "有月线行情",
    "有市场指标",
)
AVAILABILITY_FLAG_COLUMNS = (
    "有基本信息",
    "有日线行情",
    "有周线行情",
    "有月线行情",
    "有市场指标",
)


@dataclass(frozen=True)
class CsvFileReport:
    path: Path
    exists: bool
    columns: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ZipArchiveReport:
    archive_name: str
    path: Path
    member_count: int
    sample_members: tuple[str, ...]
    columns: tuple[str, ...] | None = None
    extracted_to: Path | None = None


@dataclass(frozen=True)
class IndexInitializationReport:
    root: Path
    archive_mode: str
    validation: str
    basic_info_files: dict[str, CsvFileReport]
    zip_archives: dict[str, ZipArchiveReport]
    market_metric_files: int


class IndexDataStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def initialize(
        self,
        *,
        archive_mode: ArchiveMode = "lazy",
        validation: ValidationMode = "sample",
        cache_dir: str | Path | None = None,
        rebuild: bool = False,
    ) -> IndexInitializationReport:
        self._validate_options(archive_mode=archive_mode, validation=validation)
        self._require_root()
        extracted_root = (
            self._extract_archives(cache_dir=cache_dir, rebuild=rebuild)
            if archive_mode == "extract"
            else None
        )

        basic_reports = {
            source: self._csv_report(self.root / filename, validation=validation)
            for source, filename in BASIC_INFO_FILES.items()
        }
        archive_reports = {
            freq: self._archive_report(
                logical_name=f"index_bars_{freq}",
                archive_name=archive_name,
                validation=validation,
                extracted_root=extracted_root,
            )
            for freq, archive_name in BAR_ARCHIVES.items()
        }
        return IndexInitializationReport(
            root=self.root,
            archive_mode=archive_mode,
            validation=validation,
            basic_info_files=basic_reports,
            zip_archives=archive_reports,
            market_metric_files=len(self._market_metric_paths_by_code),
        )

    def basic_info(
        self,
        source: str | None = None,
        *,
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        source_keys = [source] if source is not None else list(BASIC_INFO_FILES)
        unknown = [key for key in source_keys if key not in BASIC_INFO_FILES]
        if unknown:
            raise ValueError(f"Unknown index basic info source: {unknown}")

        frames: list[pd.DataFrame] = []
        for key in source_keys:
            path = self.root / BASIC_INFO_FILES[key]
            df = read_csv_file(path, required_columns=INDEX_BASIC_COLUMNS)
            df = df.copy()
            df["source_group"] = key
            if include_source:
                df = add_source_columns(df, source_path=path, source_kind="csv")
            frames.append(df)
        result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return finalize_columns(result.reset_index(drop=True), dataset="index_basic_info", columns=columns)

    def available_indices(
        self,
        *,
        dataset: AvailableIndexDataset = "all",
        freq: AvailableFrequency = "all",
        source: SourceMode = "combined",
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        if dataset not in {"all", "basic_info", "bars", "market_metrics"}:
            raise ValueError("dataset must be one of: 'all', 'basic_info', 'bars', 'market_metrics'")
        if freq not in {"all", "day", "week", "month"}:
            raise ValueError("freq must be one of: 'all', 'day', 'week', 'month'")
        if source not in {"historical", "incremental", "combined"}:
            raise ValueError("source must be one of: 'historical', 'incremental', 'combined'")

        if dataset == "basic_info":
            return self._finalize_available_indices(
                self._available_basic_info_rows(include_source=include_source),
                columns=columns,
            )
        if dataset == "bars":
            return self._finalize_available_indices(
                self._available_bar_rows(freq=freq, source=source, include_source=include_source),
                columns=columns,
            )
        if dataset == "market_metrics":
            return self._finalize_available_indices(
                self._available_market_metric_rows(source=source, include_source=include_source),
                columns=columns,
            )

        frames = [
            self._available_basic_info_rows(include_source=False),
            self._available_bar_rows(freq=freq, source=source, include_source=False),
            self._available_market_metric_rows(source=source, include_source=False),
        ]
        combined = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
        return self._finalize_available_indices(
            self._collapse_all_available_rows(combined, requested_source=source),
            columns=columns,
        )

    def bars(
        self,
        index_code: str,
        *,
        freq: Frequency = "day",
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        source: SourceMode = "historical",
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        if freq not in BAR_ARCHIVES:
            raise ValueError("freq must be one of: 'day', 'week', 'month'")
        if source not in {"historical", "incremental", "combined"}:
            raise ValueError("source must be one of: 'historical', 'incremental', 'combined'")
        if freq != "day" and source != "historical":
            raise ValueError("incremental index bars are only available for freq='day'")

        historical = (
            self._read_bar_historical(index_code, freq=freq, start=start, end=end, include_source=include_source)
            if source in {"historical", "combined"}
            else pd.DataFrame()
        )
        incremental = (
            self._read_incremental(
                INDEX_DAILY_INCREMENTAL_DIR,
                required_columns=INDEX_BAR_COLUMNS,
                codes=[index_code],
                start=start,
                end=end,
                freq=freq,
                include_source=include_source,
            )
            if source in {"incremental", "combined"}
            else pd.DataFrame()
        )

        if source == "combined":
            result = combine_prefer_incremental(
                historical,
                incremental,
                key_columns=["指数代码", "交易日期", "频率"],
            )
        else:
            result = historical if source == "historical" else incremental

        if not result.empty:
            result = result.sort_values(["交易日期", "指数代码"]).reset_index(drop=True)
        return finalize_columns(result, dataset="index_bars", columns=columns)

    def market_metrics(
        self,
        index_code: str,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        source: SourceMode = "historical",
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        if source not in {"historical", "incremental", "combined"}:
            raise ValueError("source must be one of: 'historical', 'incremental', 'combined'")

        historical = (
            self._read_market_metric_historical(
                index_code,
                start=start,
                end=end,
                include_source=include_source,
            )
            if source in {"historical", "combined"}
            else pd.DataFrame()
        )
        incremental = (
            self._read_incremental(
                MARKET_METRICS_INCREMENTAL_DIR,
                required_columns=MARKET_METRIC_COLUMNS,
                codes=[index_code],
                start=start,
                end=end,
                freq=None,
                include_source=include_source,
            )
            if source in {"incremental", "combined"}
            else pd.DataFrame()
        )
        if source == "combined":
            result = combine_prefer_incremental(
                historical,
                incremental,
                key_columns=["指数代码", "交易日期"],
            )
        else:
            result = historical if source == "historical" else incremental

        if not result.empty:
            result = result.sort_values(["交易日期", "指数代码"]).reset_index(drop=True)
        return finalize_columns(result, dataset="index_market_metrics", columns=columns)

    def _read_bar_historical(
        self,
        index_code: str,
        *,
        freq: str,
        start: str | pd.Timestamp | None,
        end: str | pd.Timestamp | None,
        include_source: bool,
    ) -> pd.DataFrame:
        archive = self.root / BAR_ARCHIVES[freq]
        reader = ZipCsvReader(archive)
        member = reader.resolve_member(index_code)
        df = reader.read_member(member, required_columns=INDEX_BAR_COLUMNS)
        df = filter_date_range(df, "交易日期", start=start, end=end)
        df = df.copy()
        df["频率"] = freq
        if include_source:
            df = add_source_columns(df, source_path=archive, source_member=member, source_kind="zip")
        return df.reset_index(drop=True)

    def _read_market_metric_historical(
        self,
        index_code: str,
        *,
        start: str | pd.Timestamp | None,
        end: str | pd.Timestamp | None,
        include_source: bool,
    ) -> pd.DataFrame:
        path = self._market_metric_paths_by_code.get(index_code)
        if path is None:
            raise DataFileNotFoundError(f"Index market metrics not found for {index_code!r} in {self.root}")
        df = read_csv_file(path, required_columns=MARKET_METRIC_COLUMNS)
        df = filter_date_range(df, "交易日期", start=start, end=end)
        if include_source:
            df = add_source_columns(df, source_path=path, source_kind="csv")
        return df.reset_index(drop=True)

    def _read_incremental(
        self,
        dataset_dir: str,
        *,
        required_columns: tuple[str, ...],
        codes: list[str],
        start: str | pd.Timestamp | None,
        end: str | pd.Timestamp | None,
        freq: str | None,
        include_source: bool,
    ) -> pd.DataFrame:
        root = self.root / INCREMENTAL_DIR / dataset_dir
        if not root.is_dir():
            return pd.DataFrame()

        requested_codes = set(codes)
        frames: list[pd.DataFrame] = []
        start_date = parse_date_value(start)
        end_date = parse_date_value(end)
        for path in sorted(root.glob("*/*.csv")):
            trade_date = _trade_date_from_incremental_path(path)
            if start_date is not None and trade_date < start_date:
                continue
            if end_date is not None and trade_date > end_date:
                continue
            df = read_csv_file(path, required_columns=required_columns)
            df = df[df["指数代码"].isin(requested_codes)]
            if df.empty:
                continue
            if freq is not None:
                df = df.copy()
                df["频率"] = freq
            if include_source:
                df = add_source_columns(df, source_path=path, source_kind="incremental")
            frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _available_basic_info_rows(self, *, include_source: bool) -> pd.DataFrame:
        info = self.basic_info(columns="raw", include_source=include_source)
        if info.empty:
            return self._empty_available_frame(include_source=include_source)

        result = pd.DataFrame(
            {
                "指数代码": info["指数代码"],
                "数据集": "basic_info",
                "频率": pd.NA,
                "来源": "basic_info",
                "信息来源": info["source_group"],
                "有基本信息": True,
                "有日线行情": False,
                "有周线行情": False,
                "有月线行情": False,
                "有市场指标": False,
            }
        )
        if include_source:
            result["_source_path"] = info.get("_source_path", pd.NA)
            result["_source_member"] = info.get("_source_member", pd.NA)
            result["_source_kind"] = info.get("_source_kind", pd.NA)
        return result.sort_values(["指数代码"]).reset_index(drop=True)

    def _available_bar_rows(
        self,
        *,
        freq: str,
        source: str,
        include_source: bool,
    ) -> pd.DataFrame:
        if source != "historical" and freq not in {"day", "all"}:
            raise ValueError("incremental index bars are only available for freq='day'")

        freqs = tuple(BAR_ARCHIVES) if freq == "all" else (freq,)
        rows: list[dict[str, object]] = []
        for item_freq in freqs:
            if source in {"historical", "combined"}:
                archive = self.root / BAR_ARCHIVES[item_freq]
                reader = ZipCsvReader(archive)
                for member in reader.list_csv_members():
                    rows.append(
                        self._available_row(
                            index_code=_code_from_member(member),
                            dataset="index_bars",
                            freq=item_freq,
                            source="historical",
                            has_day_bars=item_freq == "day",
                            has_week_bars=item_freq == "week",
                            has_month_bars=item_freq == "month",
                            source_path=archive if include_source else None,
                            source_member=member if include_source else None,
                            source_kind="zip" if include_source else None,
                        )
                    )

            if item_freq == "day" and source in {"incremental", "combined"}:
                for code, path in self._incremental_codes_by_first_path(
                    INDEX_DAILY_INCREMENTAL_DIR,
                    required_columns=INDEX_BAR_COLUMNS,
                ).items():
                    rows.append(
                        self._available_row(
                            index_code=code,
                            dataset="index_bars",
                            freq="day",
                            source="incremental",
                            has_day_bars=True,
                            has_week_bars=False,
                            has_month_bars=False,
                            source_path=path if include_source else None,
                            source_member=None,
                            source_kind="incremental" if include_source else None,
                        )
                    )

        return self._collapse_dataset_available_rows(
            pd.DataFrame(rows),
            group_columns=["指数代码", "数据集", "频率"],
            requested_source=source,
            include_source=include_source,
        )

    def _available_market_metric_rows(self, *, source: str, include_source: bool) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        if source in {"historical", "combined"}:
            for code, path in self._market_metric_paths_by_code.items():
                rows.append(
                    self._available_row(
                        index_code=code,
                        dataset="market_metrics",
                        freq=None,
                        source="historical",
                        has_market_metrics=True,
                        source_path=path if include_source else None,
                        source_member=None,
                        source_kind="csv" if include_source else None,
                    )
                )

        if source in {"incremental", "combined"}:
            for code, path in self._incremental_codes_by_first_path(
                MARKET_METRICS_INCREMENTAL_DIR,
                required_columns=MARKET_METRIC_COLUMNS,
            ).items():
                rows.append(
                    self._available_row(
                        index_code=code,
                        dataset="market_metrics",
                        freq=None,
                        source="incremental",
                        has_market_metrics=True,
                        source_path=path if include_source else None,
                        source_member=None,
                        source_kind="incremental" if include_source else None,
                    )
                )

        return self._collapse_dataset_available_rows(
            pd.DataFrame(rows),
            group_columns=["指数代码", "数据集"],
            requested_source=source,
            include_source=include_source,
        )

    def _incremental_codes_by_first_path(
        self,
        dataset_dir: str,
        *,
        required_columns: tuple[str, ...],
    ) -> dict[str, Path]:
        root = self.root / INCREMENTAL_DIR / dataset_dir
        if not root.is_dir():
            return {}
        result: dict[str, Path] = {}
        for path in sorted(root.glob("*/*.csv")):
            df = read_csv_file(path, required_columns=required_columns)
            if "指数代码" not in df.columns:
                continue
            for code in df["指数代码"].dropna().astype("string").unique():
                result.setdefault(str(code), path)
        return result

    def _available_row(
        self,
        *,
        index_code: str,
        dataset: str,
        freq: str | None,
        source: str,
        has_basic_info: bool = False,
        has_day_bars: bool = False,
        has_week_bars: bool = False,
        has_month_bars: bool = False,
        has_market_metrics: bool = False,
        source_group: str | None = None,
        source_path: Path | None = None,
        source_member: str | None = None,
        source_kind: str | None = None,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "指数代码": index_code,
            "数据集": dataset,
            "频率": freq if freq is not None else pd.NA,
            "来源": source,
            "信息来源": source_group if source_group is not None else pd.NA,
            "有基本信息": has_basic_info,
            "有日线行情": has_day_bars,
            "有周线行情": has_week_bars,
            "有月线行情": has_month_bars,
            "有市场指标": has_market_metrics,
        }
        if source_path is not None or source_member is not None or source_kind is not None:
            row["_source_path"] = str(source_path) if source_path is not None else pd.NA
            row["_source_member"] = source_member if source_member is not None else pd.NA
            row["_source_kind"] = source_kind if source_kind is not None else pd.NA
        return row

    def _collapse_dataset_available_rows(
        self,
        df: pd.DataFrame,
        *,
        group_columns: list[str],
        requested_source: str,
        include_source: bool,
    ) -> pd.DataFrame:
        if df.empty:
            return self._empty_available_frame(include_source=include_source)

        rows: list[dict[str, object]] = []
        for _key, group in df.groupby(group_columns, dropna=False, sort=True):
            first = group.iloc[0]
            sources = sorted(set(str(item) for item in group["来源"].dropna()))
            row = {column: first[column] for column in AVAILABLE_COLUMNS if column in group.columns}
            row["来源"] = "combined" if requested_source == "combined" and len(sources) > 1 else sources[0]
            for flag in AVAILABILITY_FLAG_COLUMNS:
                row[flag] = bool(group[flag].any())
            if include_source:
                if len(group) == 1:
                    row["_source_path"] = first.get("_source_path", pd.NA)
                    row["_source_member"] = first.get("_source_member", pd.NA)
                    row["_source_kind"] = first.get("_source_kind", pd.NA)
                else:
                    row["_source_path"] = pd.NA
                    row["_source_member"] = pd.NA
                    row["_source_kind"] = "combined"
            rows.append(row)
        return pd.DataFrame(rows)

    def _collapse_all_available_rows(self, df: pd.DataFrame, *, requested_source: str) -> pd.DataFrame:
        if df.empty:
            return self._empty_available_frame(include_source=False)

        rows: list[dict[str, object]] = []
        for code, group in df.groupby("指数代码", sort=True):
            source_groups = sorted(set(str(item) for item in group["信息来源"].dropna()))
            rows.append(
                {
                    "指数代码": code,
                    "数据集": "all",
                    "频率": "all",
                    "来源": requested_source,
                    "信息来源": ",".join(source_groups) if source_groups else pd.NA,
                    "有基本信息": bool(group["有基本信息"].any()),
                    "有日线行情": bool(group["有日线行情"].any()),
                    "有周线行情": bool(group["有周线行情"].any()),
                    "有月线行情": bool(group["有月线行情"].any()),
                    "有市场指标": bool(group["有市场指标"].any()),
                }
            )
        return pd.DataFrame(rows)

    def _empty_available_frame(self, *, include_source: bool) -> pd.DataFrame:
        columns = list(AVAILABLE_COLUMNS)
        if include_source:
            columns.extend(["_source_path", "_source_member", "_source_kind"])
        return pd.DataFrame(columns=columns)

    def _finalize_available_indices(self, df: pd.DataFrame, *, columns: ColumnMode) -> pd.DataFrame:
        result = df.copy()
        for column in AVAILABLE_COLUMNS:
            if column not in result.columns:
                result[column] = pd.NA
        for flag in AVAILABILITY_FLAG_COLUMNS:
            result[flag] = result[flag].fillna(False).map(bool).astype(object)
        result = result.sort_values(["指数代码", "数据集", "频率"], na_position="last").reset_index(drop=True)
        return finalize_columns(result, dataset="available_indices", columns=columns)

    @cached_property
    def _market_metric_paths_by_code(self) -> dict[str, Path]:
        metrics_dir = self.root / MARKET_METRICS_DIR
        if not metrics_dir.is_dir():
            return {}
        result: dict[str, Path] = {}
        for path in sorted(metrics_dir.glob("*.csv")):
            df = read_csv_file(path, required_columns=MARKET_METRIC_COLUMNS)
            if df.empty:
                continue
            code = str(df.iloc[0]["指数代码"])
            result[code] = path
        return result

    def _require_root(self) -> None:
        if not self.root.is_dir():
            raise DataRootNotFoundError(f"Index data root not found: {self.root}")

    def _csv_report(self, path: Path, *, validation: ValidationMode) -> CsvFileReport:
        exists = path.is_file()
        columns: tuple[str, ...] | None = None
        if exists and validation in {"sample", "full"}:
            columns = tuple(read_csv_file(path).columns)
        return CsvFileReport(path=path, exists=exists, columns=columns)

    def _archive_report(
        self,
        *,
        logical_name: str,
        archive_name: str,
        validation: ValidationMode,
        extracted_root: Path | None,
    ) -> ZipArchiveReport:
        path = self.root / archive_name
        reader = ZipCsvReader(path)
        members = reader.list_csv_members()
        columns: tuple[str, ...] | None = None
        if validation == "sample" and members:
            sample = reader.read_member(members[0], required_columns=INDEX_BAR_COLUMNS)
            columns = tuple(sample.columns)
        elif validation == "full":
            for index, member in enumerate(members):
                sample = reader.read_member(member, required_columns=INDEX_BAR_COLUMNS)
                if index == 0:
                    columns = tuple(sample.columns)
        return ZipArchiveReport(
            archive_name=archive_name,
            path=path,
            member_count=len(members),
            sample_members=members[:5],
            columns=columns,
            extracted_to=(extracted_root / logical_name) if extracted_root is not None else None,
        )

    def _extract_archives(self, *, cache_dir: str | Path | None, rebuild: bool) -> Path:
        cache_root = Path(cache_dir).expanduser().resolve() if cache_dir is not None else (Path.home() / ".cache").resolve()
        extracted_root = cache_root / "finfact_io" / "index_data" / self._root_cache_key()
        source_root = self.root.resolve()
        if extracted_root == source_root or source_root in extracted_root.parents:
            raise ArchiveModeError(f"Refusing to extract archives inside source data directory: {source_root}")
        if rebuild and extracted_root.exists():
            shutil.rmtree(extracted_root)
        extracted_root.mkdir(parents=True, exist_ok=True)
        for logical_name, archive_name in BAR_ARCHIVES.items():
            target = extracted_root / f"index_bars_{logical_name}"
            if target.exists() and not rebuild:
                continue
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(self.root / archive_name) as archive:
                archive.extractall(target)
        return extracted_root

    def _validate_options(self, *, archive_mode: str, validation: str) -> None:
        if archive_mode not in {"lazy", "extract"}:
            raise ArchiveModeError("archive_mode must be one of: 'lazy', 'extract'")
        if validation not in {"none", "sample", "full"}:
            raise ArchiveModeError("validation must be one of: 'none', 'sample', 'full'")

    def _root_cache_key(self) -> str:
        digest = hashlib.sha256(str(self.root.resolve()).encode("utf-8")).hexdigest()[:12]
        return f"{self.root.name}-{digest}"


def _trade_date_from_incremental_path(path: Path) -> pd.Timestamp:
    date_text = path.name.split("_", 1)[0]
    return parse_date_value(date_text) or pd.NaT


def _code_from_member(member: str) -> str:
    return Path(member).name.removesuffix(".csv")
