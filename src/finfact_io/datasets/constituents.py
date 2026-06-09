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
AsofPolicy = Literal["next_trading_day", "same_day"]

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


@dataclass(frozen=True)
class IndexConstituentQualityReport:
    index_code: str
    provider: str
    expected_member_count: int
    first_available_snapshot_date: pd.Timestamp | None
    first_valid_snapshot_date: pd.Timestamp | None
    first_usable_trade_date: pd.Timestamp | None
    snapshots: pd.DataFrame


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

    def index_constituent_quality(
        self,
        index_code: str,
        *,
        expected_member_count: int,
        provider: Provider = "auto",
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        weight_sum_bounds: tuple[float, float] = (95.0, 105.0),
        asof_policy: AsofPolicy = "next_trading_day",
    ) -> IndexConstituentQualityReport:
        if expected_member_count <= 0:
            raise ValueError("expected_member_count must be positive")
        if asof_policy not in {"next_trading_day", "same_day"}:
            raise ValueError("asof_policy must be one of: 'next_trading_day', 'same_day'")
        lower_weight, upper_weight = weight_sum_bounds
        if lower_weight > upper_weight:
            raise ValueError("weight_sum_bounds lower bound must be <= upper bound")

        provider_name = self._resolve_history_provider(index_code, provider=provider)
        raw = self.index_member_snapshots(
            index_code,
            provider=provider_name,
            start=start,
            end=end,
            columns="standard",
            include_source=True,
        )
        snapshots = self._build_quality_snapshots(
            raw,
            expected_member_count=expected_member_count,
            weight_sum_bounds=(float(lower_weight), float(upper_weight)),
        )
        first_available = _first_timestamp(snapshots["snapshot_date"])
        valid = snapshots[snapshots["quality_status"] == "complete"]
        first_valid = _first_timestamp(valid["snapshot_date"]) if not valid.empty else None
        first_usable = (
            self._first_usable_trade_date(index_code, first_valid, asof_policy=asof_policy)
            if first_valid is not None
            else None
        )
        return IndexConstituentQualityReport(
            index_code=index_code,
            provider=provider_name,
            expected_member_count=expected_member_count,
            first_available_snapshot_date=first_available,
            first_valid_snapshot_date=first_valid,
            first_usable_trade_date=first_usable,
            snapshots=snapshots,
        )

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

    def _build_quality_snapshots(
        self,
        raw: pd.DataFrame,
        *,
        expected_member_count: int,
        weight_sum_bounds: tuple[float, float],
    ) -> pd.DataFrame:
        work = raw.copy()
        work["snapshot_date"] = pd.to_datetime(work["snapshot_date"])
        work["trade_date"] = pd.to_datetime(work["trade_date"])
        work["_weight_numeric"] = pd.to_numeric(work["weight"], errors="coerce")
        lower_weight, upper_weight = weight_sum_bounds

        rows: list[dict[str, object]] = []
        for snapshot_date, group in work.groupby("snapshot_date", sort=True, dropna=False):
            weights = group["_weight_numeric"]
            member_symbols = group["member_symbol"]
            member_count = int(len(group))
            distinct_member_count = int(member_symbols.nunique(dropna=True))
            duplicate_member_rows = int(member_symbols.duplicated().sum())
            weight_null_count = int(weights.isna().sum())
            weight_sum_pct = float(weights.sum(skipna=True))
            issue_codes = _quality_issue_codes(
                distinct_member_count=distinct_member_count,
                duplicate_member_rows=duplicate_member_rows,
                weight_null_count=weight_null_count,
                weight_sum_pct=weight_sum_pct,
                expected_member_count=expected_member_count,
                weight_sum_bounds=weight_sum_bounds,
            )
            first = group.iloc[0]
            rows.append(
                {
                    "snapshot_date": pd.Timestamp(snapshot_date),
                    "trade_date_min": pd.to_datetime(group["trade_date"]).min(),
                    "trade_date_max": pd.to_datetime(group["trade_date"]).max(),
                    "member_count": member_count,
                    "distinct_member_count": distinct_member_count,
                    "expected_member_count": expected_member_count,
                    "duplicate_member_rows": duplicate_member_rows,
                    "weight_sum_pct": weight_sum_pct,
                    "weight_sum_ratio": weight_sum_pct / 100,
                    "weight_sum_lower_bound_pct": lower_weight,
                    "weight_sum_upper_bound_pct": upper_weight,
                    "weight_null_count": weight_null_count,
                    "quality_status": "complete" if not issue_codes else "incomplete",
                    "issue_codes": ",".join(issue_codes),
                    "_source_path": first.get("_source_path", pd.NA),
                    "_source_member": first.get("_source_member", pd.NA),
                    "_source_kind": first.get("_source_kind", pd.NA),
                }
            )

        return pd.DataFrame(rows).sort_values("snapshot_date").reset_index(drop=True)

    def _first_usable_trade_date(
        self,
        index_code: str,
        snapshot_date: pd.Timestamp,
        *,
        asof_policy: AsofPolicy,
    ) -> pd.Timestamp | None:
        from finfact_io.errors import FinfactError
        from finfact_io.datasets.index import IndexDataStore

        try:
            bars = IndexDataStore(self.root).bars(
                index_code,
                freq="day",
                source="combined",
                columns="standard",
            )
        except FinfactError:
            return None

        if bars.empty or "trade_date" not in bars.columns:
            return None
        trade_dates = pd.to_datetime(bars["trade_date"]).dropna().drop_duplicates().sort_values()
        if asof_policy == "next_trading_day":
            usable = trade_dates[trade_dates > snapshot_date]
        else:
            usable = trade_dates[trade_dates >= snapshot_date]
        if usable.empty:
            return None
        return pd.Timestamp(usable.iloc[0])

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


def _first_timestamp(series: pd.Series) -> pd.Timestamp | None:
    values = pd.to_datetime(series).dropna()
    if values.empty:
        return None
    return pd.Timestamp(values.min())


def _quality_issue_codes(
    *,
    distinct_member_count: int,
    duplicate_member_rows: int,
    weight_null_count: int,
    weight_sum_pct: float,
    expected_member_count: int,
    weight_sum_bounds: tuple[float, float],
) -> list[str]:
    lower_weight, upper_weight = weight_sum_bounds
    issues: list[str] = []
    if distinct_member_count < expected_member_count:
        issues.append("low_member_count")
    if duplicate_member_rows > 0:
        issues.append("duplicate_members")
    if weight_null_count > 0:
        issues.append("invalid_weight")
    if weight_sum_pct < lower_weight:
        issues.append("low_weight_sum")
    elif weight_sum_pct > upper_weight:
        issues.append("high_weight_sum")
    return issues
