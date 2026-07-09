from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from finfact_io.config import PathLike, resolve_ashare_daily_dir
from finfact_io.readers.csv import read_csv_file

DEFAULT_OUTPUT_DIR = Path("data") / "listing_board_current_reference"
STOCK_LIST_FILE = "股票列表.csv"
DELISTED_STOCK_FILE = "退市股票列表.csv"
DIMENSION_STANDARD = "A_SHARE_LISTING_BOARD"
REFERENCE_MODE = "static_current_reference"

STOCK_COLUMNS = (
    "TS代码",
    "股票代码",
    "股票名称",
    "地域",
    "所属行业",
    "市场类型",
    "交易所代码",
    "上市状态",
    "上市日期",
    "退市日期",
)

BOARD_TAXONOMY = (
    {
        "listing_board_code": "MAIN",
        "listing_board": "主板",
        "board_order": 1,
        "valid_exchange_codes": "SSE,SZSE",
        "description": "Shanghai and Shenzhen main boards",
    },
    {
        "listing_board_code": "CHINEXT",
        "listing_board": "创业板",
        "board_order": 2,
        "valid_exchange_codes": "SZSE",
        "description": "Shenzhen ChiNext board",
    },
    {
        "listing_board_code": "STAR",
        "listing_board": "科创板",
        "board_order": 3,
        "valid_exchange_codes": "SSE",
        "description": "Shanghai STAR Market",
    },
    {
        "listing_board_code": "BSE",
        "listing_board": "北交所",
        "board_order": 4,
        "valid_exchange_codes": "BSE",
        "description": "Beijing Stock Exchange",
    },
)

BOARD_CODE_BY_NAME = {row["listing_board"]: row["listing_board_code"] for row in BOARD_TAXONOMY}
BOARD_ORDER_BY_CODE = {row["listing_board_code"]: row["board_order"] for row in BOARD_TAXONOMY}
VALID_EXCHANGES_BY_BOARD = {
    row["listing_board_code"]: set(str(row["valid_exchange_codes"]).split(",")) for row in BOARD_TAXONOMY
}
EXCHANGE_BY_SUFFIX = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}


@dataclass(frozen=True)
class ListingBoardReferenceBuildReport:
    output_dir: Path
    row_counts: dict[str, int]
    files: dict[str, Path]


def build_listing_board_reference_dataset(
    *,
    ashare_daily_dir: PathLike | None = None,
    output_dir: PathLike | None = None,
) -> ListingBoardReferenceBuildReport:
    source_root = resolve_ashare_daily_dir(ashare_daily_dir)
    target = Path(output_dir).expanduser() if output_dir is not None else DEFAULT_OUTPUT_DIR
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    listed = _read_stock_list(source_root / STOCK_LIST_FILE, source_list="listed")
    delisted = _read_stock_list(source_root / DELISTED_STOCK_FILE, source_list="delisted")
    source = pd.concat([listed, delisted], ignore_index=True)
    duplicate_source_stock_codes = int(source.loc[source.duplicated("stock_code", keep=False), "stock_code"].nunique())
    snapshot = _build_current_snapshot(source)
    taxonomy = _build_taxonomy()
    edges = _build_matrix_edges(snapshot)
    counts = _build_board_counts(snapshot, taxonomy)
    quality = _build_quality_table(
        snapshot=snapshot,
        taxonomy=taxonomy,
        edges=edges,
        counts=counts,
        duplicate_source_stock_codes=duplicate_source_stock_codes,
    )

    paths = {
        "current_snapshot.csv": target / "current_snapshot.csv",
        "listing_board_taxonomy.csv": target / "listing_board_taxonomy.csv",
        "listing_board_matrix_edges.csv": target / "listing_board_matrix_edges.csv",
        "board_counts.csv": target / "board_counts.csv",
        "data_quality.csv": target / "data_quality.csv",
        "manifest.json": target / "manifest.json",
        "README.md": target / "README.md",
    }
    snapshot.to_csv(paths["current_snapshot.csv"], index=False)
    taxonomy.to_csv(paths["listing_board_taxonomy.csv"], index=False)
    edges.to_csv(paths["listing_board_matrix_edges.csv"], index=False)
    counts.to_csv(paths["board_counts.csv"], index=False)
    quality.to_csv(paths["data_quality.csv"], index=False)

    row_counts = {
        "current_snapshot": len(snapshot),
        "listing_board_taxonomy": len(taxonomy),
        "listing_board_matrix_edges": len(edges),
        "board_counts": len(counts),
        "data_quality": len(quality),
    }
    manifest = _build_manifest(
        source_root=source_root,
        output_dir=target,
        row_counts=row_counts,
        files=paths,
        snapshot=snapshot,
        counts=counts,
        duplicate_source_stock_codes=duplicate_source_stock_codes,
    )
    paths["manifest.json"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["README.md"].write_text(_build_readme(manifest), encoding="utf-8")
    return ListingBoardReferenceBuildReport(output_dir=target, row_counts=row_counts, files=paths)


def _read_stock_list(path: Path, *, source_list: str) -> pd.DataFrame:
    df = read_csv_file(path, required_columns=STOCK_COLUMNS).copy()
    df = df.rename(
        columns={
            "TS代码": "stock_code",
            "股票名称": "stock_name",
            "地域": "raw_region",
            "所属行业": "raw_industry",
            "市场类型": "listing_board",
            "交易所代码": "exchange_code",
            "上市状态": "listing_status",
            "上市日期": "list_date",
            "退市日期": "delist_date",
        }
    )
    df["source_list"] = source_list
    df["source_file"] = path.name
    return df[
        [
            "stock_code",
            "stock_name",
            "raw_region",
            "raw_industry",
            "listing_board",
            "exchange_code",
            "listing_status",
            "list_date",
            "delist_date",
            "source_list",
            "source_file",
        ]
    ]


def _build_current_snapshot(source: pd.DataFrame) -> pd.DataFrame:
    ranked = source.copy()
    ranked["source_rank"] = ranked["source_list"].map({"listed": 0, "delisted": 1}).fillna(99)
    ranked = ranked.sort_values(["stock_code", "source_rank", "source_file"], kind="stable")
    ranked = ranked.drop_duplicates("stock_code", keep="first").copy()
    ranked["listing_board_code"] = ranked["listing_board"].map(BOARD_CODE_BY_NAME)
    ranked["board_order"] = ranked["listing_board_code"].map(BOARD_ORDER_BY_CODE)
    ranked["exchange_suffix"] = ranked["stock_code"].map(_exchange_suffix)
    ranked["dimension_standard"] = DIMENSION_STANDARD
    ranked["reference_mode"] = REFERENCE_MODE
    ranked["list_date"] = ranked["list_date"].map(_format_date_text)
    ranked["delist_date"] = ranked["delist_date"].map(_format_date_text)
    ranked["quality_status"] = ranked.apply(
        lambda row: "complete" if _row_is_complete(row) else "incomplete",
        axis=1,
    )
    columns = [
        "stock_code",
        "stock_name",
        "dimension_standard",
        "listing_board_code",
        "listing_board",
        "board_order",
        "exchange_code",
        "exchange_suffix",
        "listing_status",
        "list_date",
        "delist_date",
        "source_list",
        "raw_region",
        "raw_industry",
        "reference_mode",
        "source_file",
        "quality_status",
    ]
    return ranked.loc[:, columns].sort_values("stock_code").reset_index(drop=True)


def _row_is_complete(row: pd.Series) -> bool:
    board_code = row.get("listing_board_code")
    if pd.isna(board_code):
        return False
    return _exchange_is_consistent(
        board_code=str(board_code),
        exchange_code=row.get("exchange_code"),
        exchange_suffix=row.get("exchange_suffix"),
    )


def _build_taxonomy() -> pd.DataFrame:
    taxonomy = pd.DataFrame(BOARD_TAXONOMY)
    taxonomy.insert(0, "dimension_standard", DIMENSION_STANDARD)
    taxonomy["dimension_level"] = "listing_board"
    return taxonomy[
        [
            "dimension_standard",
            "dimension_level",
            "listing_board_code",
            "listing_board",
            "board_order",
            "valid_exchange_codes",
            "description",
        ]
    ]


def _build_matrix_edges(snapshot: pd.DataFrame) -> pd.DataFrame:
    complete = snapshot.dropna(subset=["listing_board_code"]).copy()
    return pd.DataFrame(
        {
            "stock_code": complete["stock_code"],
            "stock_name": complete["stock_name"],
            "dimension_standard": DIMENSION_STANDARD,
            "dimension_level": "listing_board",
            "dimension_code": complete["listing_board_code"],
            "dimension_name": complete["listing_board"],
            "membership": 1,
            "reference_mode": REFERENCE_MODE,
        }
    ).sort_values(["stock_code", "dimension_code"]).reset_index(drop=True)


def _build_board_counts(snapshot: pd.DataFrame, taxonomy: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for scope in ("all", "listed", "delisted"):
        scoped = snapshot if scope == "all" else snapshot[snapshot["source_list"] == scope]
        value_counts = scoped["listing_board_code"].value_counts(dropna=False).to_dict()
        for _, board in taxonomy.sort_values("board_order").iterrows():
            board_code = board["listing_board_code"]
            rows.append(
                {
                    "scope": scope,
                    "listing_board_code": board_code,
                    "listing_board": board["listing_board"],
                    "board_order": int(board["board_order"]),
                    "stock_count": int(value_counts.get(board_code, 0)),
                }
            )
    return pd.DataFrame(rows)


def _build_quality_table(
    *,
    snapshot: pd.DataFrame,
    taxonomy: pd.DataFrame,
    edges: pd.DataFrame,
    counts: pd.DataFrame,
    duplicate_source_stock_codes: int,
) -> pd.DataFrame:
    duplicate_snapshot_rows = int(snapshot.duplicated("stock_code").sum())
    missing_board_rows = int(snapshot["listing_board_code"].isna().sum())
    valid_codes = set(taxonomy["listing_board_code"])
    invalid_board_rows = int((~snapshot["listing_board_code"].dropna().isin(valid_codes)).sum())
    inconsistent_exchange_rows = int(
        snapshot.apply(
            lambda row: not _exchange_is_consistent(
                board_code=row["listing_board_code"],
                exchange_code=row["exchange_code"],
                exchange_suffix=row["exchange_suffix"],
            )
            if pd.notna(row["listing_board_code"])
            else False,
            axis=1,
        ).sum()
    )
    edge_duplicate_rows = int(edges.duplicated(["stock_code", "dimension_level"], keep=False).sum())
    expected_edge_rows = len(snapshot) - missing_board_rows
    counts_total = int(counts[counts["scope"] == "all"]["stock_count"].sum())
    rows = [
        _quality_row("current_snapshot_row_count", len(snapshot) > 0, len(snapshot), "current plus delisted stocks"),
        _quality_row("unique_stock_code", duplicate_snapshot_rows == 0, duplicate_snapshot_rows, "duplicate rows after source priority de-duplication"),
        _quality_row(
            "duplicate_source_stock_codes_resolved",
            duplicate_snapshot_rows == 0,
            duplicate_source_stock_codes,
            "duplicate source rows resolved with listed records preferred over delisted records",
        ),
        _quality_row("missing_listing_board", missing_board_rows == 0, missing_board_rows, "rows without a recognized listing board"),
        _quality_row("valid_listing_board_values", invalid_board_rows == 0, invalid_board_rows, "rows whose board code is outside taxonomy"),
        _quality_row("exchange_board_consistency", inconsistent_exchange_rows == 0, inconsistent_exchange_rows, "board, exchange code, and symbol suffix consistency checks"),
        _quality_row("matrix_edges_one_membership_per_stock", edge_duplicate_rows == 0 and len(edges) == expected_edge_rows, len(edges), "one listing-board membership edge per classified stock"),
        _quality_row("board_counts_sum_to_snapshot", counts_total == len(snapshot), counts_total, "all-board counts should sum to current snapshot row count"),
    ]
    return pd.DataFrame(rows)


def _build_manifest(
    *,
    source_root: Path,
    output_dir: Path,
    row_counts: dict[str, int],
    files: dict[str, Path],
    snapshot: pd.DataFrame,
    counts: pd.DataFrame,
    duplicate_source_stock_codes: int,
) -> dict[str, object]:
    all_counts = counts[counts["scope"] == "all"].sort_values("board_order")
    return {
        "dataset": "listing_board_current_reference",
        "description": "Static current reference for A-share listing board membership.",
        "dimension_standard": DIMENSION_STANDARD,
        "dimension_level": "listing_board",
        "reference_mode": REFERENCE_MODE,
        "historical_pit_listing_board": False,
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": {
            "listed_stock_file": str(source_root / STOCK_LIST_FILE),
            "delisted_stock_file": str(source_root / DELISTED_STOCK_FILE),
            "duplicate_policy": "listed records are preferred over delisted records for duplicate stock codes",
        },
        "row_counts": row_counts,
        "duplicate_source_stock_codes_resolved": duplicate_source_stock_codes,
        "listing_board_counts": all_counts[["listing_board_code", "listing_board", "stock_count"]].to_dict("records"),
        "files": {
            name: {"path": str(path), "rows": row_counts.get(name.removesuffix(".csv"))}
            for name, path in files.items()
            if name.endswith(".csv")
        },
        "quality_status_counts": snapshot["quality_status"].value_counts().to_dict(),
    }


def _build_readme(manifest: dict[str, object]) -> str:
    return f"""# A-share Listing Board Current Reference

This directory contains a static current reference for A-share listing board
membership.

Dimension standard: `{manifest["dimension_standard"]}`

Reference mode: `{manifest["reference_mode"]}`

This is an independent dimension from industry classification. Use
`listing_board_matrix_edges.csv` to build board exposure matrices such as
`B.T @ (w - b)`.
"""


def _quality_row(check: str, passed: bool, observed_value: object, detail: str) -> dict[str, object]:
    return {
        "dataset": "listing_board_current_reference",
        "check": check,
        "status": "pass" if passed else "fail",
        "severity": "info" if passed else "error",
        "observed_value": observed_value,
        "detail": detail,
    }


def _exchange_suffix(stock_code: object) -> str | pd.NA:
    if pd.isna(stock_code):
        return pd.NA
    text = str(stock_code)
    if "." not in text:
        return pd.NA
    return text.rsplit(".", 1)[-1]


def _exchange_is_consistent(*, board_code: object, exchange_code: object, exchange_suffix: object) -> bool:
    if pd.isna(board_code):
        return False
    code = str(board_code)
    exchange = None if pd.isna(exchange_code) else str(exchange_code)
    suffix = None if pd.isna(exchange_suffix) else str(exchange_suffix)
    valid_exchanges = VALID_EXCHANGES_BY_BOARD.get(code)
    if valid_exchanges is None or exchange not in valid_exchanges:
        return False
    if suffix is None:
        return False
    return EXCHANGE_BY_SUFFIX.get(suffix) == exchange


def _format_date_text(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if not text:
        return pd.NA
    dt = pd.to_datetime(text, errors="coerce")
    if pd.isna(dt):
        return text
    return dt.strftime("%Y-%m-%d")


def build_listing_board_matrix(edges: pd.DataFrame, *, stocks: Iterable[str] | None = None) -> pd.DataFrame:
    if stocks is None:
        stock_index = sorted(edges["stock_code"].dropna().astype(str).unique())
    else:
        stock_index = list(stocks)
    board_codes = [row["listing_board_code"] for row in BOARD_TAXONOMY]
    matrix = pd.DataFrame(0, index=stock_index, columns=board_codes, dtype=int)
    for _, row in edges.iterrows():
        stock_code = str(row["stock_code"])
        board_code = str(row["dimension_code"])
        if stock_code in matrix.index and board_code in matrix.columns:
            matrix.loc[stock_code, board_code] = int(row["membership"])
    return matrix
