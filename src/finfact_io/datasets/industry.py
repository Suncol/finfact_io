from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from dataclasses import dataclass
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

ValidationMode = Literal["none", "sample", "full"]
ArchiveMode = Literal["lazy", "extract"]
IndustrySystem = Literal["sw", "citic"]

SW_DAILY_ARCHIVE = "申万行业日线行情.zip"
CITIC_DAILY_ARCHIVE = "中信行业日线行情.zip"
SW_CLASSIFICATION_DIR = "申万行业分类"
CITIC_CLASSIFICATION_DIR = "中信行业分类"
SW_MEMBERS_DIR = "申万行业成分_每日更新"
INCREMENTAL_DIR = "增量数据"
SW_DAILY_INCREMENTAL_DIR = "申万行业日线行情"
CITIC_DAILY_INCREMENTAL_DIR = "中信行业日线行情"

SW_DAILY_COLUMNS = ("指数代码", "交易日期")
CITIC_DAILY_COLUMNS = ("指数代码", "交易日期")
CLASSIFICATION_COLUMNS = ("指数代码", "行业名称", "行业分级", "行业代码", "是否发布指数", "父级代码")
SW_MEMBER_COLUMNS = ("一级行业代码", "一级行业名称", "二级行业代码", "二级行业名称", "三级行业代码", "股票代码", "纳入日期")
CITIC_MEMBER_FILE = "中信行业分类_成分股_全部_CITIC.csv"
CITIC_CLASSIFICATION_FILE = "中信行业分类_行业层级表.csv"


@dataclass(frozen=True)
class IndustryInitializationReport:
    root: Path
    archive_mode: str
    validation: str
    sw_daily_members: int
    citic_daily_members: int
    sw_member_snapshots: int
    classification_files: dict[str, bool]


class IndustryDataStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def initialize(
        self,
        *,
        archive_mode: ArchiveMode = "lazy",
        validation: ValidationMode = "sample",
        cache_dir: str | Path | None = None,
        rebuild: bool = False,
    ) -> IndustryInitializationReport:
        if archive_mode not in {"lazy", "extract"}:
            raise ArchiveModeError("archive_mode must be one of: 'lazy', 'extract'")
        if validation not in {"none", "sample", "full"}:
            raise ValueError("validation must be one of: 'none', 'sample', 'full'")
        self._require_root()
        if archive_mode == "extract":
            self._extract_archives(cache_dir=cache_dir, rebuild=rebuild)
        sw_reader = ZipCsvReader(self.root / SW_DAILY_ARCHIVE)
        citic_reader = ZipCsvReader(self.root / CITIC_DAILY_ARCHIVE)
        classification_files = {
            "sw_l1": (self.root / SW_CLASSIFICATION_DIR / "申万行业分类_L1_SW2021.csv").is_file(),
            "sw_l2": (self.root / SW_CLASSIFICATION_DIR / "申万行业分类_L2_SW2021.csv").is_file(),
            "sw_l3": (self.root / SW_CLASSIFICATION_DIR / "申万行业分类_L3_SW2021.csv").is_file(),
            "citic_tree": (self.root / CITIC_CLASSIFICATION_DIR / CITIC_CLASSIFICATION_FILE).is_file(),
            "citic_members": (self.root / CITIC_CLASSIFICATION_DIR / CITIC_MEMBER_FILE).is_file(),
        }
        return IndustryInitializationReport(
            root=self.root,
            archive_mode=archive_mode,
            validation=validation,
            sw_daily_members=len(sw_reader.list_csv_members()),
            citic_daily_members=len(citic_reader.list_csv_members()),
            sw_member_snapshots=len(self._sw_member_snapshots()),
            classification_files=classification_files,
        )

    def daily(
        self,
        system: IndustrySystem,
        code: str,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        source: SourceMode = "historical",
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        if system not in {"sw", "citic"}:
            raise ValueError("system must be one of: 'sw', 'citic'")
        if source not in {"historical", "incremental", "combined"}:
            raise ValueError("source must be one of: 'historical', 'incremental', 'combined'")

        historical = (
            self._read_daily_historical(system, code, start=start, end=end, include_source=include_source)
            if source in {"historical", "combined"}
            else pd.DataFrame()
        )
        incremental = (
            self._read_daily_incremental(system, code, start=start, end=end, include_source=include_source)
            if source in {"incremental", "combined"}
            else pd.DataFrame()
        )
        if source == "combined":
            result = combine_prefer_incremental(historical, incremental, key_columns=["指数代码", "交易日期"])
        else:
            result = historical if source == "historical" else incremental
        if not result.empty:
            result = result.sort_values(["交易日期", "指数代码"]).reset_index(drop=True)
        dataset = "industry_sw_daily" if system == "sw" else "industry_citic_daily"
        return finalize_columns(result, dataset=dataset, columns=columns)

    def classification(
        self,
        system: IndustrySystem,
        *,
        level: str | None = None,
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        if system == "sw":
            frames: list[pd.DataFrame] = []
            for filename in (
                "申万行业分类_L1_SW2021.csv",
                "申万行业分类_L2_SW2021.csv",
                "申万行业分类_L3_SW2021.csv",
            ):
                path = self.root / SW_CLASSIFICATION_DIR / filename
                df = read_csv_file(path, required_columns=CLASSIFICATION_COLUMNS)
                if include_source:
                    df = add_source_columns(df, source_path=path, source_kind="csv")
                frames.append(df)
            result = pd.concat(frames, ignore_index=True)
        elif system == "citic":
            path = self.root / CITIC_CLASSIFICATION_DIR / CITIC_CLASSIFICATION_FILE
            result = read_csv_file(path, required_columns=CLASSIFICATION_COLUMNS)
            if include_source:
                result = add_source_columns(result, source_path=path, source_kind="csv")
        else:
            raise ValueError("system must be one of: 'sw', 'citic'")

        result = result.copy()
        result["体系"] = system
        if level is not None:
            result = result[result["行业分级"] == level]
        return finalize_columns(result.reset_index(drop=True), dataset="industry_classification", columns=columns)

    def sw_members(
        self,
        *,
        date: str | pd.Timestamp | None = None,
        match: Literal["latest", "exact", "previous"] = "latest",
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        snapshots = self._sw_member_snapshots()
        if not snapshots:
            raise DataFileNotFoundError(f"No SW industry member snapshots found in {self.root / SW_MEMBERS_DIR}")
        snapshot_date = self._resolve_snapshot_date(snapshots, date=date, match=match)
        path = snapshots[snapshot_date]
        df = read_csv_file(path, required_columns=SW_MEMBER_COLUMNS)
        df = df.copy()
        df["快照日期"] = snapshot_date
        if include_source:
            df = add_source_columns(df, source_path=path, source_kind="csv")
        return finalize_columns(df.reset_index(drop=True), dataset="industry_sw_members", columns=columns)

    def citic_members(
        self,
        *,
        latest_only: bool = True,
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        path = self.root / CITIC_CLASSIFICATION_DIR / CITIC_MEMBER_FILE
        df = read_csv_file(path, required_columns=("股票代码", "三级行业代码", "纳入日期", "是否最新"))
        if latest_only:
            df = df[df["是否最新"] == "Y"]
        if include_source:
            df = add_source_columns(df, source_path=path, source_kind="csv")
        return finalize_columns(df.reset_index(drop=True), dataset="industry_citic_members", columns=columns)

    def members(self, system: IndustrySystem, **kwargs: object) -> pd.DataFrame:
        if system == "sw":
            return self.sw_members(**kwargs)
        if system == "citic":
            return self.citic_members(**kwargs)
        raise ValueError("system must be one of: 'sw', 'citic'")

    def _read_daily_historical(
        self,
        system: str,
        code: str,
        *,
        start: str | pd.Timestamp | None,
        end: str | pd.Timestamp | None,
        include_source: bool,
    ) -> pd.DataFrame:
        archive_name = SW_DAILY_ARCHIVE if system == "sw" else CITIC_DAILY_ARCHIVE
        required_columns = SW_DAILY_COLUMNS if system == "sw" else CITIC_DAILY_COLUMNS
        archive = self.root / archive_name
        reader = ZipCsvReader(archive)
        member = reader.resolve_member(code)
        df = reader.read_member(member, required_columns=required_columns)
        df = filter_date_range(df, "交易日期", start=start, end=end)
        if include_source:
            df = add_source_columns(df, source_path=archive, source_member=member, source_kind="zip")
        return df.reset_index(drop=True)

    def _read_daily_incremental(
        self,
        system: str,
        code: str,
        *,
        start: str | pd.Timestamp | None,
        end: str | pd.Timestamp | None,
        include_source: bool,
    ) -> pd.DataFrame:
        dataset_dir = SW_DAILY_INCREMENTAL_DIR if system == "sw" else CITIC_DAILY_INCREMENTAL_DIR
        required_columns = SW_DAILY_COLUMNS if system == "sw" else CITIC_DAILY_COLUMNS
        root = self.root / INCREMENTAL_DIR / dataset_dir
        if not root.is_dir():
            return pd.DataFrame()
        start_date = parse_date_value(start)
        end_date = parse_date_value(end)
        frames: list[pd.DataFrame] = []
        for path in sorted(root.glob("*/*.csv")):
            trade_date = _trade_date_from_incremental_path(path)
            if start_date is not None and trade_date < start_date:
                continue
            if end_date is not None and trade_date > end_date:
                continue
            df = read_csv_file(path, required_columns=required_columns)
            df = df[df["指数代码"] == code]
            if df.empty:
                continue
            if include_source:
                df = add_source_columns(df, source_path=path, source_kind="incremental")
            frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _sw_member_snapshots(self) -> dict[pd.Timestamp, Path]:
        root = self.root / SW_MEMBERS_DIR
        if not root.is_dir():
            return {}
        snapshots: dict[pd.Timestamp, Path] = {}
        for path in sorted(root.glob("*/*.csv")):
            match = re.fullmatch(r"申万行业成分_(\d{8})\.csv", path.name)
            if match is None:
                continue
            snapshot_date = parse_date_value(match.group(1))
            if snapshot_date is not None:
                snapshots[snapshot_date] = path
        return snapshots

    def _resolve_snapshot_date(
        self,
        snapshots: dict[pd.Timestamp, Path],
        *,
        date: str | pd.Timestamp | None,
        match: str,
    ) -> pd.Timestamp:
        if match not in {"latest", "exact", "previous"}:
            raise ValueError("match must be one of: 'latest', 'exact', 'previous'")
        if match == "latest" or date is None:
            return max(snapshots)
        requested = parse_date_value(date)
        if requested is None:
            return max(snapshots)
        if match == "exact":
            if requested not in snapshots:
                raise DataFileNotFoundError(f"SW industry member snapshot not found for {requested.date()}")
            return requested
        candidates = [snapshot for snapshot in snapshots if snapshot <= requested]
        if not candidates:
            raise DataFileNotFoundError(f"No SW industry member snapshot on or before {requested.date()}")
        return max(candidates)

    def _require_root(self) -> None:
        if not self.root.is_dir():
            raise DataRootNotFoundError(f"Index data root not found: {self.root}")

    def _extract_archives(self, *, cache_dir: str | Path | None, rebuild: bool) -> Path:
        cache_root = Path(cache_dir).expanduser().resolve() if cache_dir is not None else (Path.home() / ".cache").resolve()
        extracted_root = cache_root / "finfact_io" / "industry_data" / self._root_cache_key()
        source_root = self.root.resolve()
        if extracted_root == source_root or source_root in extracted_root.parents:
            raise ArchiveModeError(f"Refusing to extract archives inside source data directory: {source_root}")
        if rebuild and extracted_root.exists():
            shutil.rmtree(extracted_root)
        extracted_root.mkdir(parents=True, exist_ok=True)
        for logical_name, archive_name in {"sw_daily": SW_DAILY_ARCHIVE, "citic_daily": CITIC_DAILY_ARCHIVE}.items():
            target = extracted_root / logical_name
            if target.exists() and not rebuild:
                continue
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(self.root / archive_name) as archive:
                archive.extractall(target)
        return extracted_root

    def _root_cache_key(self) -> str:
        digest = hashlib.sha256(str(self.root.resolve()).encode("utf-8")).hexdigest()[:12]
        return f"{self.root.name}-{digest}"


def _trade_date_from_incremental_path(path: Path) -> pd.Timestamp:
    date_text = path.name.split("_", 1)[0]
    return parse_date_value(date_text) or pd.NaT
