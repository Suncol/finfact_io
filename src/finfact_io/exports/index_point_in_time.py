from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd

from finfact_io.config import DEFAULT_INDEX_DATA_DIR, PathLike
from finfact_io.errors import FinfactError
from finfact_io.store import FinfactStore

AsofPolicy = Literal["next_trading_day", "same_day"]


@dataclass(frozen=True)
class IndexDatasetSpec:
    dataset: str
    index_code: str
    index_name: str
    expected_member_count: int
    constituent_provider: Literal["sse", "szse", "csi"]
    total_return_candidates: tuple[str, ...] = ()
    default_output_dir: Path = Path("data")


@dataclass(frozen=True)
class IndexPointInTimeBuildReport:
    output_dir: Path
    row_counts: dict[str, int]
    files: dict[str, Path]


CSI300_SPEC = IndexDatasetSpec(
    dataset="csi300",
    index_code="000300.SH",
    index_name="沪深300",
    expected_member_count=300,
    constituent_provider="sse",
    total_return_candidates=("h00300.CSI",),
    default_output_dir=Path("data") / "csi300",
)

CSI500_SPEC = IndexDatasetSpec(
    dataset="csi500",
    index_code="000905.SH",
    index_name="中证500",
    expected_member_count=500,
    constituent_provider="sse",
    total_return_candidates=("h00905.CSI",),
    default_output_dir=Path("data") / "csi500",
)

CSI1000_SPEC = IndexDatasetSpec(
    dataset="csi1000",
    index_code="000852.SH",
    index_name="中证1000",
    expected_member_count=1000,
    constituent_provider="sse",
    total_return_candidates=("h00852.SH", "h00852.CSI"),
    default_output_dir=Path("data") / "csi1000",
)

CSI2000_SPEC = IndexDatasetSpec(
    dataset="csi2000",
    index_code="932000.CSI",
    index_name="中证2000",
    expected_member_count=2000,
    constituent_provider="csi",
    total_return_candidates=("932000CNY010.CSI",),
    default_output_dir=Path("data") / "csi2000",
)


def build_csi300_dataset(
    *,
    index_data_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    include_daily_asof: bool = True,
    asof_policy: AsofPolicy = "next_trading_day",
) -> IndexPointInTimeBuildReport:
    return build_index_point_in_time_dataset(
        CSI300_SPEC,
        index_data_dir=index_data_dir,
        output_dir=output_dir,
        start=start,
        end=end,
        include_daily_asof=include_daily_asof,
        asof_policy=asof_policy,
    )


def build_csi500_dataset(
    *,
    index_data_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    include_daily_asof: bool = True,
    asof_policy: AsofPolicy = "next_trading_day",
) -> IndexPointInTimeBuildReport:
    return build_index_point_in_time_dataset(
        CSI500_SPEC,
        index_data_dir=index_data_dir,
        output_dir=output_dir,
        start=start,
        end=end,
        include_daily_asof=include_daily_asof,
        asof_policy=asof_policy,
    )


def build_csi1000_dataset(
    *,
    index_data_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    include_daily_asof: bool = True,
    asof_policy: AsofPolicy = "next_trading_day",
) -> IndexPointInTimeBuildReport:
    return build_index_point_in_time_dataset(
        CSI1000_SPEC,
        index_data_dir=index_data_dir,
        output_dir=output_dir,
        start=start,
        end=end,
        include_daily_asof=include_daily_asof,
        asof_policy=asof_policy,
    )


def build_csi2000_dataset(
    *,
    index_data_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    include_daily_asof: bool = True,
    asof_policy: AsofPolicy = "next_trading_day",
) -> IndexPointInTimeBuildReport:
    return build_index_point_in_time_dataset(
        CSI2000_SPEC,
        index_data_dir=index_data_dir,
        output_dir=output_dir,
        start=start,
        end=end,
        include_daily_asof=include_daily_asof,
        asof_policy=asof_policy,
    )


def build_index_point_in_time_dataset(
    spec: IndexDatasetSpec,
    *,
    index_data_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    include_daily_asof: bool = True,
    asof_policy: AsofPolicy = "next_trading_day",
) -> IndexPointInTimeBuildReport:
    if asof_policy not in {"next_trading_day", "same_day"}:
        raise ValueError("asof_policy must be one of: 'next_trading_day', 'same_day'")
    if spec.expected_member_count <= 0:
        raise ValueError("expected_member_count must be positive.")

    root = Path(index_data_dir).expanduser() if index_data_dir is not None else DEFAULT_INDEX_DATA_DIR
    target = Path(output_dir).expanduser() if output_dir is not None else spec.default_output_dir
    target.mkdir(parents=True, exist_ok=True)

    store = FinfactStore(index_data_dir=root)
    daily, total_return_info = _build_index_daily(store, spec, start=start, end=end)
    raw_snapshots = store.constituents.index_member_snapshots(
        spec.index_code,
        provider=spec.constituent_provider,
        start=start,
        end=end,
        columns="standard",
        include_source=True,
    )
    snapshots, snapshot_meta, asof_source = _build_snapshot_tables(raw_snapshots, spec)

    paths = {
        "index_daily.csv": target / "index_daily.csv",
        "constituent_weights_snapshots.csv": target / "constituent_weights_snapshots.csv",
        "data_quality.csv": target / "data_quality.csv",
        "manifest.json": target / "manifest.json",
        "README.md": target / "README.md",
    }
    daily.to_csv(paths["index_daily.csv"], index=False)
    snapshot_index, snapshot_member_rows = _write_partitioned_snapshots(
        paths["constituent_weights_snapshots.csv"],
        target / "constituent_weights_snapshots",
        snapshots=snapshots,
    )

    row_counts: dict[str, int] = {
        "index_daily": len(daily),
        "constituent_weights_snapshots": len(snapshot_index),
        "constituent_weights_snapshot_members": snapshot_member_rows,
    }
    asof_index: pd.DataFrame | None = None
    asof_member_rows: int | None = None
    if include_daily_asof:
        asof_path = target / "constituent_weights_daily_asof.csv"
        paths["constituent_weights_daily_asof.csv"] = asof_path
        asof_index, asof_member_rows = _write_daily_asof(
            asof_path,
            target / "constituent_weights_daily_asof",
            spec=spec,
            index_daily=daily,
            snapshots=asof_source,
            snapshot_meta=snapshot_meta,
            asof_policy=asof_policy,
        )
        row_counts["constituent_weights_daily_asof"] = len(asof_index)
        row_counts["constituent_weights_daily_asof_members"] = asof_member_rows

    quality = _build_quality_table(
        spec=spec,
        daily=daily,
        snapshot_index=snapshot_index,
        snapshot_meta=snapshot_meta,
        daily_asof_index=asof_index,
        total_return_available=bool(total_return_info["available"]),
        daily_asof_rows=asof_member_rows,
    )
    quality.to_csv(paths["data_quality.csv"], index=False)
    row_counts["data_quality"] = len(quality)

    manifest = _build_manifest(
        spec=spec,
        source_root=root,
        output_dir=target,
        files=paths,
        row_counts=row_counts,
        daily=daily,
        snapshot_meta=snapshot_meta,
        total_return_info=total_return_info,
        asof_policy=asof_policy,
        include_daily_asof=include_daily_asof,
    )
    paths["manifest.json"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["README.md"].write_text(_build_readme(spec, manifest), encoding="utf-8")
    return IndexPointInTimeBuildReport(output_dir=target, row_counts=row_counts, files=paths)


def _build_index_daily(
    store: FinfactStore,
    spec: IndexDatasetSpec,
    *,
    start: str | pd.Timestamp | None,
    end: str | pd.Timestamp | None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    bars = store.index.bars(
        spec.index_code,
        freq="day",
        source="combined",
        start=start,
        end=end,
        columns="standard",
        include_source=True,
    )
    total_return, total_return_info = _load_total_return(store, spec, start=start, end=end)
    if total_return_info["available"]:
        bars = bars.merge(total_return, on="trade_date", how="left")
    else:
        bars = bars.copy()
        bars["total_return"] = pd.NA

    result = pd.DataFrame(
        {
            "date": _format_date_series(bars["trade_date"]),
            "index_code": bars["index_code"],
            "index_name": spec.index_name,
            "open": bars["open"],
            "high": bars["high"],
            "low": bars["low"],
            "close": bars["close"],
            "previous_close": bars["previous_close"],
            "return": bars["pct_change"] / 100,
            "return_pct": bars["pct_change"],
            "total_return": bars["total_return"],
            "total_return_available": bool(total_return_info["available"]),
            "volume": bars["volume_lot"],
            "volume_unit": "手",
            "amount": bars["amount_thousand_yuan"],
            "amount_unit": "千元",
            "source_kind": bars.get("_source_kind", pd.NA),
            "source_path": bars.get("_source_path", pd.NA),
            "source_member": bars.get("_source_member", pd.NA),
        }
    )
    return result.reset_index(drop=True), total_return_info


def _load_total_return(
    store: FinfactStore,
    spec: IndexDatasetSpec,
    *,
    start: str | pd.Timestamp | None,
    end: str | pd.Timestamp | None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if not spec.total_return_candidates:
        return pd.DataFrame(columns=["trade_date", "total_return"]), {
            "code": None,
            "candidates": [],
            "available": False,
            "reason": "no total return candidates configured",
        }

    errors: list[str] = []
    for code in spec.total_return_candidates:
        try:
            total_return = store.index.bars(
                code,
                freq="day",
                source="combined",
                start=start,
                end=end,
                columns="standard",
            )
        except FinfactError as exc:
            errors.append(f"{code}: {exc}")
            continue

        if total_return.empty:
            errors.append(f"{code}: total return bars returned no rows")
            continue

        return total_return[["trade_date", "close"]].rename(columns={"close": "total_return"}), {
            "code": code,
            "candidates": list(spec.total_return_candidates),
            "available": True,
            "reason": None,
        }

    return pd.DataFrame(columns=["trade_date", "total_return"]), {
        "code": spec.total_return_candidates[0],
        "candidates": list(spec.total_return_candidates),
        "available": False,
        "reason": "; ".join(errors),
    }


def _build_snapshot_tables(
    raw: pd.DataFrame,
    spec: IndexDatasetSpec,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = raw.copy()
    if "snapshot_date" not in work.columns:
        work["snapshot_date"] = work["trade_date"]
    work["snapshot_date"] = pd.to_datetime(work["snapshot_date"])
    work["trade_date"] = pd.to_datetime(work["trade_date"])

    meta = (
        work.groupby("snapshot_date", dropna=False)
        .agg(member_count=("member_symbol", "size"), weight_sum=("weight", "sum"))
        .reset_index()
    )
    meta["quality_status"] = meta.apply(lambda row: _snapshot_quality(row, spec), axis=1)

    enriched = work.merge(meta, on="snapshot_date", how="left")
    asof_source = enriched[
        [
            "snapshot_date",
            "index_code",
            "member_symbol",
            "weight",
            "quality_status",
            "member_count",
            "weight_sum",
        ]
    ].copy()

    result = pd.DataFrame(
        {
            "date": _format_date_series(enriched["trade_date"]),
            "index_code": enriched["index_code"],
            "member_symbol": enriched["member_symbol"],
            "weight": enriched["weight"],
            "weight_unit": "%",
            "snapshot_date": _format_date_series(enriched["snapshot_date"]),
            "provider": spec.constituent_provider,
            "quality_status": enriched["quality_status"],
            "member_count": enriched["member_count"],
            "weight_sum": enriched["weight_sum"],
            "source_path": enriched.get("_source_path", pd.NA),
            "source_member": enriched.get("_source_member", pd.NA),
        }
    )
    return result.reset_index(drop=True), meta.reset_index(drop=True), asof_source


def _write_partitioned_snapshots(
    index_path: Path,
    partition_dir: Path,
    *,
    snapshots: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    _prepare_partition_dir(partition_dir)
    index_rows: list[dict[str, object]] = []
    member_rows = 0
    for date_value, group in snapshots.groupby("date", sort=True):
        date_text = str(date_value)
        file_name = f"{date_text}.csv"
        relative_path = f"{partition_dir.name}/{file_name}"
        group = group.reset_index(drop=True)
        group.to_csv(partition_dir / file_name, index=False)
        member_rows += len(group)
        first = group.iloc[0]
        index_rows.append(
            {
                "date": date_text,
                "file_path": relative_path,
                "rows": len(group),
                "index_code": first["index_code"],
                "snapshot_date": first["snapshot_date"],
                "provider": first["provider"],
                "quality_status": first["quality_status"],
                "member_count": int(first["member_count"]),
                "weight_sum": float(first["weight_sum"]),
                "duplicate_member_rows": int(group.duplicated(["member_symbol"]).sum()),
            }
        )

    index = pd.DataFrame(index_rows)
    index.to_csv(index_path, index=False)
    return index, member_rows


def _snapshot_quality(row: pd.Series, spec: IndexDatasetSpec) -> str:
    member_count = int(row["member_count"])
    weight_sum = float(row["weight_sum"])
    if member_count >= spec.expected_member_count and 95 <= weight_sum <= 105:
        return "complete"
    return "incomplete"


def _write_daily_asof(
    index_path: Path,
    partition_dir: Path,
    *,
    spec: IndexDatasetSpec,
    index_daily: pd.DataFrame,
    snapshots: pd.DataFrame,
    snapshot_meta: pd.DataFrame,
    asof_policy: AsofPolicy,
) -> tuple[pd.DataFrame, int]:
    _prepare_partition_dir(partition_dir)
    index_columns = [
        "date",
        "file_path",
        "rows",
        "index_code",
        "weight_snapshot_date",
        "effective_date",
        "days_since_snapshot",
        "quality_status",
        "weight_sum",
        "duplicate_member_rows",
    ]
    columns = [
        "date",
        "index_code",
        "member_symbol",
        "weight",
        "weight_unit",
        "weight_snapshot_date",
        "effective_date",
        "days_since_snapshot",
        "quality_status",
    ]
    trade_dates = pd.to_datetime(index_daily["date"]).drop_duplicates().sort_values().reset_index(drop=True)
    effective = _effective_snapshot_table(snapshot_meta, trade_dates=trade_dates, asof_policy=asof_policy)
    if effective.empty or trade_dates.empty:
        index = pd.DataFrame(columns=index_columns)
        index.to_csv(index_path, index=False)
        return index, 0

    mapping = pd.merge_asof(
        pd.DataFrame({"date": trade_dates}),
        effective.sort_values("effective_date"),
        left_on="date",
        right_on="effective_date",
        direction="backward",
    ).dropna(subset=["snapshot_date"])

    groups = {
        pd.Timestamp(snapshot_date): group.reset_index(drop=True)
        for snapshot_date, group in snapshots.groupby("snapshot_date")
    }
    row_count = 0
    index_rows: list[dict[str, object]] = []
    for row in mapping.itertuples(index=False):
        snapshot_date = pd.Timestamp(row.snapshot_date)
        group = groups.get(snapshot_date)
        if group is None or group.empty:
            continue
        chunk = pd.DataFrame(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "index_code": spec.index_code,
                "member_symbol": group["member_symbol"],
                "weight": group["weight"],
                "weight_unit": "%",
                "weight_snapshot_date": snapshot_date.strftime("%Y-%m-%d"),
                "effective_date": pd.Timestamp(row.effective_date).strftime("%Y-%m-%d"),
                "days_since_snapshot": (pd.Timestamp(row.date) - snapshot_date).days,
                "quality_status": group["quality_status"],
            }
        )
        date_text = row.date.strftime("%Y-%m-%d")
        file_name = f"{date_text}.csv"
        relative_path = f"{partition_dir.name}/{file_name}"
        chunk.to_csv(partition_dir / file_name, columns=columns, index=False)
        first = chunk.iloc[0]
        index_rows.append(
            {
                "date": date_text,
                "file_path": relative_path,
                "rows": len(chunk),
                "index_code": spec.index_code,
                "weight_snapshot_date": first["weight_snapshot_date"],
                "effective_date": first["effective_date"],
                "days_since_snapshot": int(first["days_since_snapshot"]),
                "quality_status": first["quality_status"],
                "weight_sum": float(chunk["weight"].sum()),
                "duplicate_member_rows": int(chunk.duplicated(["member_symbol"]).sum()),
            }
        )
        row_count += len(chunk)

    index = pd.DataFrame(index_rows, columns=index_columns)
    index.to_csv(index_path, index=False)
    return index, row_count


def _prepare_partition_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _effective_snapshot_table(
    snapshot_meta: pd.DataFrame,
    *,
    trade_dates: pd.Series,
    asof_policy: AsofPolicy,
) -> pd.DataFrame:
    rows: list[dict[str, pd.Timestamp]] = []
    for snapshot_date in snapshot_meta["snapshot_date"].sort_values():
        snapshot_date = pd.Timestamp(snapshot_date)
        if asof_policy == "same_day":
            eligible = trade_dates[trade_dates >= snapshot_date]
        else:
            eligible = trade_dates[trade_dates > snapshot_date]
        if eligible.empty:
            continue
        rows.append({"snapshot_date": snapshot_date, "effective_date": pd.Timestamp(eligible.iloc[0])})
    return pd.DataFrame(rows)


def _build_quality_table(
    *,
    spec: IndexDatasetSpec,
    daily: pd.DataFrame,
    snapshot_index: pd.DataFrame,
    snapshot_meta: pd.DataFrame,
    daily_asof_index: pd.DataFrame | None,
    total_return_available: bool,
    daily_asof_rows: int | None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    duplicate_dates = int(daily.duplicated(["date", "index_code"]).sum())
    rows.append(
        {
            "dataset": "index_daily",
            "check": "unique_daily_key",
            "status": "pass" if duplicate_dates == 0 else "fail",
            "severity": "error" if duplicate_dates else "info",
            "affected_date": pd.NA,
            "observed_value": duplicate_dates,
            "detail": "duplicate (date, index_code) rows",
        }
    )
    if not total_return_available:
        rows.append(
            {
                "dataset": "index_daily",
                "check": "total_return_unavailable",
                "status": "warning",
                "severity": "warning",
                "affected_date": pd.NA,
                "observed_value": ",".join(spec.total_return_candidates),
                "detail": "no usable total return day bars were found",
            }
        )

    snapshot_duplicate_rows = int(snapshot_index["duplicate_member_rows"].sum()) if not snapshot_index.empty else 0
    rows.append(
        {
            "dataset": "constituent_weights_snapshots",
            "check": "snapshot_duplicate_members",
            "status": "pass" if snapshot_duplicate_rows == 0 else "fail",
            "severity": "info" if snapshot_duplicate_rows == 0 else "error",
            "affected_date": pd.NA,
            "observed_value": snapshot_duplicate_rows,
            "detail": "duplicate member_symbol rows within each snapshot date",
        }
    )
    complete_snapshots = snapshot_index[snapshot_index["quality_status"] == "complete"]
    bad_snapshot_weights = complete_snapshots[
        ~complete_snapshots["weight_sum"].between(95, 105, inclusive="both")
    ]
    rows.append(
        {
            "dataset": "constituent_weights_snapshots",
            "check": "snapshot_complete_weight_sum",
            "status": "pass" if bad_snapshot_weights.empty else "fail",
            "severity": "info" if bad_snapshot_weights.empty else "error",
            "affected_date": _join_dates(bad_snapshot_weights["date"]) if not bad_snapshot_weights.empty else pd.NA,
            "observed_value": len(bad_snapshot_weights),
            "detail": "complete snapshot dates must have total weight between 95 and 105 percent",
        }
    )
    bad_snapshot_counts = complete_snapshots[complete_snapshots["member_count"] < spec.expected_member_count]
    rows.append(
        {
            "dataset": "constituent_weights_snapshots",
            "check": "snapshot_complete_member_count",
            "status": "pass" if bad_snapshot_counts.empty else "fail",
            "severity": "info" if bad_snapshot_counts.empty else "error",
            "affected_date": _join_dates(bad_snapshot_counts["date"]) if not bad_snapshot_counts.empty else pd.NA,
            "observed_value": len(bad_snapshot_counts),
            "detail": f"complete snapshot dates must have at least {spec.expected_member_count} members",
        }
    )
    for row in snapshot_meta[snapshot_meta["quality_status"] != "complete"].itertuples(index=False):
        rows.append(
            {
                "dataset": "constituent_weights_snapshots",
                "check": "incomplete_constituent_snapshot",
                "status": "warning",
                "severity": "warning",
                "affected_date": pd.Timestamp(row.snapshot_date).strftime("%Y-%m-%d"),
                "observed_value": int(row.member_count),
                "detail": f"member_count={int(row.member_count)}, weight_sum={float(row.weight_sum):.6g}",
            }
        )

    if daily_asof_index is not None:
        daily_duplicate_rows = (
            int(daily_asof_index["duplicate_member_rows"].sum()) if not daily_asof_index.empty else 0
        )
        rows.append(
            {
                "dataset": "constituent_weights_daily_asof",
                "check": "daily_asof_duplicate_members",
                "status": "pass" if daily_duplicate_rows == 0 else "fail",
                "severity": "info" if daily_duplicate_rows == 0 else "error",
                "affected_date": pd.NA,
                "observed_value": daily_duplicate_rows,
                "detail": "duplicate member_symbol rows within each daily as-of date",
            }
        )
        complete_asof = daily_asof_index[daily_asof_index["quality_status"] == "complete"]
        bad_asof_weights = complete_asof[
            ~complete_asof["weight_sum"].between(95, 105, inclusive="both")
        ]
        rows.append(
            {
                "dataset": "constituent_weights_daily_asof",
                "check": "daily_asof_complete_weight_sum",
                "status": "pass" if bad_asof_weights.empty else "fail",
                "severity": "info" if bad_asof_weights.empty else "error",
                "affected_date": _join_dates(bad_asof_weights["date"]) if not bad_asof_weights.empty else pd.NA,
                "observed_value": len(bad_asof_weights),
                "detail": "complete daily as-of dates must have total weight between 95 and 105 percent",
            }
        )
        bad_asof_counts = complete_asof[complete_asof["rows"] < spec.expected_member_count]
        rows.append(
            {
                "dataset": "constituent_weights_daily_asof",
                "check": "daily_asof_complete_member_count",
                "status": "pass" if bad_asof_counts.empty else "fail",
                "severity": "info" if bad_asof_counts.empty else "error",
                "affected_date": _join_dates(bad_asof_counts["date"]) if not bad_asof_counts.empty else pd.NA,
                "observed_value": len(bad_asof_counts),
                "detail": f"complete daily as-of dates must have at least {spec.expected_member_count} members",
            }
        )
    if daily_asof_rows is not None:
        rows.append(
            {
                "dataset": "constituent_weights_daily_asof",
                "check": "daily_asof_generated",
                "status": "pass" if daily_asof_rows > 0 else "warning",
                "severity": "info" if daily_asof_rows > 0 else "warning",
                "affected_date": pd.NA,
                "observed_value": daily_asof_rows,
                "detail": "rows generated by point-in-time as-of expansion",
            }
        )
    return pd.DataFrame(rows)


def _join_dates(series: pd.Series, *, limit: int = 10) -> str:
    values = [str(item) for item in series.dropna().astype("string").head(limit).tolist()]
    suffix = ",..." if len(series.dropna()) > limit else ""
    return ",".join(values) + suffix


def _build_manifest(
    *,
    spec: IndexDatasetSpec,
    source_root: Path,
    output_dir: Path,
    files: dict[str, Path],
    row_counts: dict[str, int],
    daily: pd.DataFrame,
    snapshot_meta: pd.DataFrame,
    total_return_info: dict[str, object],
    asof_policy: AsofPolicy,
    include_daily_asof: bool,
) -> dict[str, object]:
    file_meta = {}
    for name, path in files.items():
        if name.endswith(".csv"):
            key = name.removesuffix(".csv")
        else:
            key = name
        item: dict[str, object] = {
            "path": str(path),
            "rows": row_counts.get(key),
        }
        if key == "constituent_weights_snapshots":
            item.update(
                {
                    "layout": "date_index",
                    "partitioned_by": "date",
                    "partition_dir": str(output_dir / "constituent_weights_snapshots"),
                    "partition_files": row_counts.get("constituent_weights_snapshots"),
                    "member_rows": row_counts.get("constituent_weights_snapshot_members"),
                }
            )
        elif key == "constituent_weights_daily_asof":
            item.update(
                {
                    "layout": "date_index",
                    "partitioned_by": "date",
                    "partition_dir": str(output_dir / "constituent_weights_daily_asof"),
                    "partition_files": row_counts.get("constituent_weights_daily_asof"),
                    "member_rows": row_counts.get("constituent_weights_daily_asof_members"),
                }
            )
        file_meta[name] = item

    caveats = []
    if not total_return_info["available"]:
        code = total_return_info.get("code") or ",".join(spec.total_return_candidates)
        caveats.append(f"total_return is empty because {code} day bars were not available locally.")
    incomplete_count = int((snapshot_meta["quality_status"] != "complete").sum())
    if incomplete_count:
        caveats.append(f"{incomplete_count} constituent snapshots are marked incomplete.")

    return {
        "dataset": spec.dataset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "index_code": spec.index_code,
        "index_name": spec.index_name,
        "expected_member_count": spec.expected_member_count,
        "constituent_provider": spec.constituent_provider,
        "price_coverage": {
            "start": daily["date"].min() if not daily.empty else None,
            "end": daily["date"].max() if not daily.empty else None,
            "rows": len(daily),
        },
        "constituent_coverage": {
            "start": _format_date_value(snapshot_meta["snapshot_date"].min()) if not snapshot_meta.empty else None,
            "end": _format_date_value(snapshot_meta["snapshot_date"].max()) if not snapshot_meta.empty else None,
            "snapshots": len(snapshot_meta),
        },
        "total_return": total_return_info,
        "point_in_time": {
            "daily_asof_generated": include_daily_asof,
            "asof_policy": asof_policy,
            "asof_policy_description": (
                "snapshot weights become usable on the next available trading day"
                if asof_policy == "next_trading_day"
                else "snapshot weights become usable on the snapshot trading day"
            ),
        },
        "files": file_meta,
        "caveats": caveats,
    }


def _build_readme(spec: IndexDatasetSpec, manifest: dict[str, object]) -> str:
    return f"""# {spec.index_name}数据目录

本目录由对应的 `scripts/build_{spec.dataset}_dataset.py` 生成，主指数代码为 `{spec.index_code}`。

## 文件

- `index_daily.csv`: 日频指数行情与收益率，`return` 为小数收益率，`return_pct` 为原始百分比。
- `constituent_weights_snapshots.csv`: 快照日期索引；每行指向 `constituent_weights_snapshots/YYYY-MM-DD.csv`。
- `constituent_weights_snapshots/`: 原始月度/快照成分股权重，每个快照日一个 CSV。
- `constituent_weights_daily_asof.csv`: 日频 as-of 日期索引；每行指向 `constituent_weights_daily_asof/YYYY-MM-DD.csv`。
- `constituent_weights_daily_asof/`: 按 point-in-time 规则展开后的成分股权重，每个交易日一个 CSV。
- `data_quality.csv`: 可诊断的数据质量检查。
- `manifest.json`: 生成时间、来源、覆盖范围、行数和 caveats。

## Point-in-time 口径

当前 as-of 策略为 `{manifest["point_in_time"]["asof_policy"]}`：
{manifest["point_in_time"]["asof_policy_description"]}。

## 已知限制

`total_return` 会使用配置中的候选全收益指数；如果本地未发现可用日线行情则留空。
成分快照完整性按预期成员数 `{spec.expected_member_count}` 和权重和区间 `[95, 105]` 标记，需结合 `quality_status` 和 `data_quality.csv` 使用。
"""


def _format_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime("%Y-%m-%d")


def _format_date_value(value: object) -> str | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")
