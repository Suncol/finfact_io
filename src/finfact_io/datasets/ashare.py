from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import pandas as pd

from finfact_io.errors import ArchiveModeError, DataFileNotFoundError, DataRootNotFoundError
from finfact_io.fields import DAILY_METRIC_ALIASES, standardize_columns, with_unit_metadata
from finfact_io.readers.csv import parse_date_value, read_csv_file
from finfact_io.readers.zip_csv import ZipCsvReader

ArchiveMode = Literal["lazy", "extract"]
ValidationMode = Literal["none", "sample", "full"]
ColumnMode = Literal["raw", "standard"]
Adjustment = Literal["qfq", "hfq"]

STOCK_LIST_FILE = "股票列表.csv"
DELISTED_STOCK_FILE = "退市股票列表.csv"
TRADING_CALENDAR_FILE = "交易日历.csv"
DAILY_METRICS_ARCHIVE = "每日指标.zip"
TECHNICAL_QFQ_ARCHIVE = "技术因子_前复权.zip"
TECHNICAL_HFQ_ARCHIVE = "技术因子_后复权.zip"

REQUIRED_TOP_FILES = (
    STOCK_LIST_FILE,
    DELISTED_STOCK_FILE,
    TRADING_CALENDAR_FILE,
    DAILY_METRICS_ARCHIVE,
    TECHNICAL_QFQ_ARCHIVE,
    TECHNICAL_HFQ_ARCHIVE,
)

STOCK_COLUMNS = ("TS代码", "股票代码", "股票名称", "上市状态")
CALENDAR_COLUMNS = ("交易所", "日期", "是否交易", "上一个交易日")
DAILY_METRIC_COLUMNS = ("股票代码", "交易日期")
TECHNICAL_FACTOR_COLUMNS = ("股票代码", "交易日期")
BUILT_DAILY_METRICS_DIR = Path("data") / "ashare_daily_metrics"
STANDARD_DAILY_METRIC_COLUMNS = tuple(DAILY_METRIC_ALIASES.values())


@dataclass(frozen=True)
class ZipArchiveReport:
    archive_name: str
    path: Path
    member_count: int
    sample_members: tuple[str, ...]
    columns: tuple[str, ...] | None = None
    extracted_to: Path | None = None


@dataclass(frozen=True)
class InitializationReport:
    root: Path
    archive_mode: str
    validation: str
    required_files: dict[str, bool]
    zip_archives: dict[str, ZipArchiveReport]
    warnings: tuple[str, ...] = ()


class AShareDailyStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def initialize(
        self,
        *,
        archive_mode: ArchiveMode = "lazy",
        validation: ValidationMode = "sample",
        cache_dir: str | Path | None = None,
        rebuild: bool = False,
    ) -> InitializationReport:
        self._validate_options(archive_mode=archive_mode, validation=validation)
        self._require_root()
        required_files = self._require_top_files()

        extracted_root = (
            self._extract_archives(cache_dir=cache_dir, rebuild=rebuild)
            if archive_mode == "extract"
            else None
        )

        zip_archives = {
            logical_name: self._archive_report(
                logical_name=logical_name,
                archive_name=archive_name,
                required_columns=required_columns,
                validation=validation,
                extracted_root=extracted_root,
            )
            for logical_name, archive_name, required_columns in self._archive_specs()
        }

        return InitializationReport(
            root=self.root,
            archive_mode=archive_mode,
            validation=validation,
            required_files=required_files,
            zip_archives=zip_archives,
        )

    def stocks(self, *, include_delisted: bool = False, columns: ColumnMode = "raw") -> pd.DataFrame:
        df = read_csv_file(self.root / STOCK_LIST_FILE, required_columns=STOCK_COLUMNS)
        if include_delisted:
            delisted = read_csv_file(self.root / DELISTED_STOCK_FILE, required_columns=STOCK_COLUMNS)
            df = pd.concat([df, delisted], ignore_index=True)
        return self._finalize_columns(df, dataset="stocks", columns=columns)

    def delisted_stocks(self, *, columns: ColumnMode = "raw") -> pd.DataFrame:
        df = read_csv_file(self.root / DELISTED_STOCK_FILE, required_columns=STOCK_COLUMNS)
        return self._finalize_columns(df, dataset="stocks", columns=columns)

    def trading_calendar(
        self,
        *,
        exchange: str | None = None,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        is_open: bool | None = None,
        columns: ColumnMode = "raw",
    ) -> pd.DataFrame:
        df = read_csv_file(self.root / TRADING_CALENDAR_FILE, required_columns=CALENDAR_COLUMNS)
        if exchange is not None:
            df = df[df["交易所"] == exchange]
        if is_open is not None:
            open_mask = df["是否交易"].isin(["交易", "1", "true", "True", "TRUE"])
            df = df[open_mask if is_open else ~open_mask]
        df = self._filter_date_range(df, "日期", start=start, end=end)
        return self._finalize_columns(df.reset_index(drop=True), dataset="calendar", columns=columns)

    def daily_metrics(
        self,
        symbol: str,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        member = self._symbol_member(symbol)
        archive = self.root / DAILY_METRICS_ARCHIVE
        df = ZipCsvReader(archive).read_member(member, required_columns=DAILY_METRIC_COLUMNS)
        df = self._filter_date_range(df, "交易日期", start=start, end=end)
        if include_source:
            df = self._add_source_columns(
                df,
                source_path=archive,
                source_member=member,
                source_kind="zip",
            )
        return self._finalize_columns(
            df.reset_index(drop=True),
            dataset="daily_metrics",
            columns=columns,
        )

    def available_daily_metric_dates(
        self,
        *,
        dataset_dir: str | Path = BUILT_DAILY_METRICS_DIR,
    ) -> pd.DataFrame:
        index_path = Path(dataset_dir).expanduser() / "daily_metrics.csv"
        if not index_path.is_file():
            raise DataFileNotFoundError(f"Built daily metrics index not found: {index_path}")
        index = pd.read_csv(
            index_path,
            dtype={
                "date": "string",
                "file_path": "string",
                "source_path": "string",
                "source_kind": "string",
                "columns_hash": "string",
                "quality_status": "string",
            },
        )
        index["date"] = pd.to_datetime(index["date"])
        return index.sort_values("date").reset_index(drop=True)

    def daily_metrics_by_date(
        self,
        date: str | pd.Timestamp,
        *,
        symbols: Sequence[str] | None = None,
        dataset_dir: str | Path = BUILT_DAILY_METRICS_DIR,
    ) -> pd.DataFrame:
        target_date = parse_date_value(date)
        if target_date is None:
            raise ValueError("date must be a valid date")
        dataset_root = Path(dataset_dir).expanduser()
        index = self.available_daily_metric_dates(dataset_dir=dataset_root)
        matched = index[index["date"] == target_date]
        if matched.empty:
            raise DataFileNotFoundError(f"Built daily metrics file not found for {target_date.date()}")
        path = dataset_root / str(matched.iloc[0]["file_path"])
        df = self._read_built_daily_metrics_file(path)
        if symbols is not None:
            symbol_set = {symbol.strip() for symbol in symbols}
            df = df[df["symbol"].isin(symbol_set)]
        return df.reset_index(drop=True)

    def daily_metrics_date_range(
        self,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        *,
        symbols: Sequence[str] | None = None,
        dataset_dir: str | Path = BUILT_DAILY_METRICS_DIR,
    ) -> pd.DataFrame:
        start_date = parse_date_value(start)
        end_date = parse_date_value(end)
        if start_date is None or end_date is None:
            raise ValueError("start and end must be valid dates")
        dataset_root = Path(dataset_dir).expanduser()
        index = self.available_daily_metric_dates(dataset_dir=dataset_root)
        index = index[(index["date"] >= start_date) & (index["date"] <= end_date)]
        frames = [
            self.daily_metrics_by_date(
                row["date"],
                symbols=symbols,
                dataset_dir=dataset_root,
            )
            for _, row in index.iterrows()
        ]
        if not frames:
            return pd.DataFrame(columns=STANDARD_DAILY_METRIC_COLUMNS)
        return pd.concat(frames, ignore_index=True).sort_values(["trade_date", "symbol"]).reset_index(drop=True)

    def technical_factors(
        self,
        symbol: str,
        *,
        adjustment: Adjustment = "qfq",
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        archive_name = self._technical_archive_name(adjustment)
        archive = self.root / archive_name
        member = self._symbol_member(symbol)
        df = ZipCsvReader(archive).read_member(member, required_columns=TECHNICAL_FACTOR_COLUMNS)
        df = self._filter_date_range(df, "交易日期", start=start, end=end)
        df = df.copy()
        df["复权类型"] = adjustment
        if include_source:
            df = self._add_source_columns(
                df,
                source_path=archive,
                source_member=member,
                source_kind="zip",
            )
        return self._finalize_columns(
            df.reset_index(drop=True),
            dataset="technical_factors",
            columns=columns,
        )

    def _require_root(self) -> None:
        if not self.root.is_dir():
            raise DataRootNotFoundError(f"A-share daily data root not found: {self.root}")

    def _require_top_files(self) -> dict[str, bool]:
        required_files = {name: (self.root / name).is_file() for name in REQUIRED_TOP_FILES}
        missing = [name for name, exists in required_files.items() if not exists]
        if missing:
            raise DataFileNotFoundError(f"Missing required A-share data files in {self.root}: {missing}")
        return required_files

    def _archive_report(
        self,
        *,
        logical_name: str,
        archive_name: str,
        required_columns: tuple[str, ...],
        validation: ValidationMode,
        extracted_root: Path | None,
    ) -> ZipArchiveReport:
        path = self.root / archive_name
        reader = ZipCsvReader(path)
        members = reader.list_csv_members()
        columns: tuple[str, ...] | None = None

        if validation == "sample" and members:
            sample = reader.read_member(members[0], required_columns=required_columns)
            columns = tuple(sample.columns)
        elif validation == "full":
            for index, member in enumerate(members):
                sample = reader.read_member(member, required_columns=required_columns)
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
        cache_root = self._resolve_cache_root(cache_dir)
        extracted_root = cache_root / "finfact_io" / "ashare_daily" / self._root_cache_key()
        self._ensure_private_cache(extracted_root)
        if rebuild and extracted_root.exists():
            shutil.rmtree(extracted_root)
        extracted_root.mkdir(parents=True, exist_ok=True)

        for logical_name, archive_name, _required_columns in self._archive_specs():
            target = extracted_root / logical_name
            if target.exists() and not rebuild:
                continue
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(self.root / archive_name) as archive:
                archive.extractall(target)
        return extracted_root

    def _resolve_cache_root(self, cache_dir: str | Path | None) -> Path:
        if cache_dir is not None:
            return Path(cache_dir).expanduser().resolve()
        return (Path.home() / ".cache").resolve()

    def _ensure_private_cache(self, extracted_root: Path) -> None:
        source_root = self.root.resolve()
        if extracted_root == source_root or source_root in extracted_root.parents:
            raise ArchiveModeError(
                f"Refusing to extract archives inside source data directory: {source_root}"
            )

    def _root_cache_key(self) -> str:
        digest = hashlib.sha256(str(self.root.resolve()).encode("utf-8")).hexdigest()[:12]
        return f"{self.root.name}-{digest}"

    def _archive_specs(self) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
        return (
            ("daily_metrics", DAILY_METRICS_ARCHIVE, DAILY_METRIC_COLUMNS),
            ("technical_factors_qfq", TECHNICAL_QFQ_ARCHIVE, TECHNICAL_FACTOR_COLUMNS),
            ("technical_factors_hfq", TECHNICAL_HFQ_ARCHIVE, TECHNICAL_FACTOR_COLUMNS),
        )

    def _technical_archive_name(self, adjustment: str) -> str:
        if adjustment == "qfq":
            return TECHNICAL_QFQ_ARCHIVE
        if adjustment == "hfq":
            return TECHNICAL_HFQ_ARCHIVE
        raise ValueError("adjustment must be one of: 'qfq', 'hfq'")

    def _validate_options(self, *, archive_mode: str, validation: str) -> None:
        if archive_mode not in {"lazy", "extract"}:
            raise ArchiveModeError("archive_mode must be one of: 'lazy', 'extract'")
        if validation not in {"none", "sample", "full"}:
            raise ArchiveModeError("validation must be one of: 'none', 'sample', 'full'")

    def _symbol_member(self, symbol: str) -> str:
        normalized = symbol.strip()
        return normalized if normalized.endswith(".csv") else f"{normalized}.csv"

    def _filter_date_range(
        self,
        df: pd.DataFrame,
        date_column: str,
        *,
        start: str | pd.Timestamp | None,
        end: str | pd.Timestamp | None,
    ) -> pd.DataFrame:
        start_date = parse_date_value(start)
        end_date = parse_date_value(end)
        filtered = df
        if start_date is not None:
            filtered = filtered[filtered[date_column] >= start_date]
        if end_date is not None:
            filtered = filtered[filtered[date_column] <= end_date]
        return filtered

    def _add_source_columns(
        self,
        df: pd.DataFrame,
        *,
        source_path: Path,
        source_member: str,
        source_kind: str,
    ) -> pd.DataFrame:
        with_source = df.copy()
        with_source["_source_path"] = str(source_path)
        with_source["_source_member"] = source_member
        with_source["_source_kind"] = source_kind
        return with_source

    def _read_built_daily_metrics_file(self, path: Path) -> pd.DataFrame:
        if not path.is_file():
            raise DataFileNotFoundError(f"Built daily metrics file not found: {path}")
        df = pd.read_csv(path, dtype={"symbol": "string"})
        missing = [column for column in STANDARD_DAILY_METRIC_COLUMNS if column not in df.columns]
        if missing:
            raise DataFileNotFoundError(f"Built daily metrics file is missing columns {missing}: {path}")
        df = df.loc[:, list(STANDARD_DAILY_METRIC_COLUMNS)].copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    def _finalize_columns(self, df: pd.DataFrame, *, dataset: str, columns: ColumnMode) -> pd.DataFrame:
        if columns == "raw":
            return with_unit_metadata(df)
        if columns == "standard":
            return standardize_columns(df, dataset)
        raise ValueError("columns must be one of: 'raw', 'standard'")
