from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from finfact_io.datasets.common import ColumnMode, add_source_columns, finalize_columns
from finfact_io.errors import DataFileNotFoundError, DataRootNotFoundError, ZipMemberNotFoundError
from finfact_io.readers.csv import parse_date_value
from finfact_io.readers.zip_csv import ZipCsvReader

Provider = Literal["auto", "sse", "szse", "csi"]
MatchMode = Literal["exact", "previous"]
ValidationMode = Literal["none", "sample", "full"]

PROVIDER_DIRS: dict[str, str] = {
    "sse": "上交所指数成分",
    "szse": "深交所指数成分",
    "csi": "中证指数成分",
}

REQUIRED_COLUMNS = ("指数代码", "成分股票代码", "交易日期", "权重")


@dataclass(frozen=True)
class ConstituentProviderReport:
    provider: str
    zip_count: int
    first_snapshot: pd.Timestamp | None
    latest_snapshot: pd.Timestamp | None


@dataclass(frozen=True)
class ConstituentsInitializationReport:
    root: Path
    validation: str
    providers: dict[str, ConstituentProviderReport]


class ConstituentsStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def initialize(self, *, validation: ValidationMode = "sample") -> ConstituentsInitializationReport:
        if validation not in {"none", "sample", "full"}:
            raise ValueError("validation must be one of: 'none', 'sample', 'full'")
        self._require_root()
        reports: dict[str, ConstituentProviderReport] = {}
        for provider in PROVIDER_DIRS:
            snapshots = self._provider_snapshots(provider)
            reports[provider] = ConstituentProviderReport(
                provider=provider,
                zip_count=len(snapshots),
                first_snapshot=min(snapshots) if snapshots else None,
                latest_snapshot=max(snapshots) if snapshots else None,
            )
        return ConstituentsInitializationReport(root=self.root, validation=validation, providers=reports)

    def index_members(
        self,
        index_code: str,
        *,
        date: str | pd.Timestamp,
        provider: Provider = "auto",
        match: MatchMode = "exact",
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        if match not in {"exact", "previous"}:
            raise ValueError("match must be one of: 'exact', 'previous'")
        providers = list(PROVIDER_DIRS) if provider == "auto" else [provider]
        unknown = [item for item in providers if item not in PROVIDER_DIRS]
        if unknown:
            raise ValueError(f"Unknown constituent provider: {unknown}")

        requested = parse_date_value(date)
        if requested is None:
            raise ValueError("date is required for index_members")

        errors: list[str] = []
        for provider_name in providers:
            candidates = self._candidate_snapshots(provider_name, requested=requested, match=match)
            for snapshot_date, zip_path in candidates:
                reader = ZipCsvReader(zip_path)
                try:
                    member = reader.resolve_member(index_code)
                except ZipMemberNotFoundError as exc:
                    errors.append(str(exc))
                    continue
                df = reader.read_member(member, required_columns=REQUIRED_COLUMNS)
                if include_source:
                    df = add_source_columns(df, source_path=zip_path, source_member=member, source_kind="zip")
                return finalize_columns(df.reset_index(drop=True), dataset="index_constituents", columns=columns)

        detail = "; ".join(errors[-3:]) if errors else "no matching snapshot zip"
        raise DataFileNotFoundError(
            f"Index constituents not found for {index_code!r} on {requested.date()} "
            f"with provider={provider!r}, match={match!r}: {detail}"
        )

    def index_member_snapshots(
        self,
        index_code: str,
        *,
        provider: Provider = "auto",
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        columns: ColumnMode = "raw",
        include_source: bool = False,
    ) -> pd.DataFrame:
        provider_name = self._resolve_history_provider(index_code, provider=provider)
        start_date = parse_date_value(start)
        end_date = parse_date_value(end)
        frames: list[pd.DataFrame] = []
        skipped: list[str] = []

        for snapshot_date, zip_path in sorted(self._provider_snapshots(provider_name).items()):
            if start_date is not None and snapshot_date < start_date:
                continue
            if end_date is not None and snapshot_date > end_date:
                continue

            reader = ZipCsvReader(zip_path)
            try:
                member = reader.resolve_member(index_code)
            except ZipMemberNotFoundError:
                skipped.append(zip_path.name)
                continue

            df = reader.read_member(member, required_columns=REQUIRED_COLUMNS)
            df = df.copy()
            df["快照日期"] = snapshot_date
            if include_source:
                df = add_source_columns(df, source_path=zip_path, source_member=member, source_kind="zip")
            frames.append(df)

        if not frames:
            detail = f"; skipped {len(skipped)} snapshots without member" if skipped else ""
            raise DataFileNotFoundError(
                f"Index constituent snapshots not found for {index_code!r} "
                f"with provider={provider!r}{detail}"
            )

        result = pd.concat(frames, ignore_index=True)
        return finalize_columns(result.reset_index(drop=True), dataset="index_constituents", columns=columns)

    def snapshot_manifest(
        self,
        *,
        provider: Provider = "auto",
        index_code: str | None = None,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        providers = list(PROVIDER_DIRS) if provider == "auto" else [provider]
        unknown = [item for item in providers if item not in PROVIDER_DIRS]
        if unknown:
            raise ValueError(f"Unknown constituent provider: {unknown}")

        start_date = parse_date_value(start)
        end_date = parse_date_value(end)
        rows: list[dict[str, object]] = []
        for provider_name in providers:
            for snapshot_date, zip_path in sorted(self._provider_snapshots(provider_name).items()):
                if start_date is not None and snapshot_date < start_date:
                    continue
                if end_date is not None and snapshot_date > end_date:
                    continue
                member_name = self._find_member_name(zip_path, index_code) if index_code is not None else pd.NA
                rows.append(
                    {
                        "provider": provider_name,
                        "snapshot_date": snapshot_date,
                        "zip_path": str(zip_path),
                        "has_index_member": isinstance(member_name, str) if index_code is not None else pd.NA,
                        "member_name": member_name,
                    }
                )
        return pd.DataFrame(rows).sort_values(["provider", "snapshot_date"]).reset_index(drop=True)

    def _candidate_snapshots(
        self,
        provider: str,
        *,
        requested: pd.Timestamp,
        match: str,
    ) -> list[tuple[pd.Timestamp, Path]]:
        snapshots = self._provider_snapshots(provider)
        if match == "exact":
            path = snapshots.get(requested)
            return [(requested, path)] if path is not None else []
        candidates = [(snapshot, path) for snapshot, path in snapshots.items() if snapshot <= requested]
        return sorted(candidates, key=lambda item: item[0], reverse=True)

    def _provider_snapshots(self, provider: str) -> dict[pd.Timestamp, Path]:
        directory = self.root / PROVIDER_DIRS[provider]
        if not directory.is_dir():
            return {}
        snapshots: dict[pd.Timestamp, Path] = {}
        for path in sorted(directory.glob("*.zip")):
            match = re.search(r"_(\d{8})\.zip$", path.name)
            if match is None:
                continue
            snapshot_date = parse_date_value(match.group(1))
            if snapshot_date is not None:
                snapshots[snapshot_date] = path
        return snapshots

    def _resolve_history_provider(self, index_code: str, *, provider: Provider) -> str:
        if provider != "auto":
            if provider not in PROVIDER_DIRS:
                raise ValueError(f"Unknown constituent provider: {provider!r}")
            return provider

        counts: dict[str, int] = {}
        for provider_name in PROVIDER_DIRS:
            count = 0
            for zip_path in self._provider_snapshots(provider_name).values():
                if isinstance(self._find_member_name(zip_path, index_code), str):
                    count += 1
            counts[provider_name] = count

        provider_name, count = max(counts.items(), key=lambda item: item[1])
        if count == 0:
            raise DataFileNotFoundError(
                f"Index constituent snapshots not found for {index_code!r} in any provider"
            )
        return provider_name

    def _find_member_name(self, zip_path: Path, index_code: str | None) -> str | object:
        if index_code is None:
            return pd.NA
        requested = index_code.strip()
        requested_member = requested if requested.endswith(".csv") else f"{requested}.csv"
        try:
            with zipfile.ZipFile(zip_path) as archive:
                members = tuple(name for name in archive.namelist() if name.endswith(".csv"))
        except FileNotFoundError:
            return pd.NA
        if requested_member in members:
            return requested_member
        casefold_map = {member.casefold(): member for member in members}
        return casefold_map.get(requested_member.casefold(), pd.NA)

    def _require_root(self) -> None:
        if not self.root.is_dir():
            raise DataRootNotFoundError(f"Index data root not found: {self.root}")
