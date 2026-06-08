from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from finfact_io.errors import DataFileNotFoundError, DataRootNotFoundError
from finfact_io.readers.csv import parse_date_value

DEFAULT_DATA_DIR = Path("data")

ASHARE_DAILY_DATASET = "ashare_daily_metrics"
CSI1000_DATASET = "csi1000"
SW_INDUSTRY_DATASET = "industry_sw_current_reference"
LISTING_BOARD_DATASET = "listing_board_current_reference"

DATE_COLUMNS = {
    "date",
    "trade_date",
    "snapshot_date",
    "weight_snapshot_date",
    "effective_date",
    "classification_snapshot_date",
    "list_date",
    "delist_date",
}

STRING_COLUMNS = {
    "stock_code",
    "stock_name",
    "symbol",
    "member_symbol",
    "index_code",
    "index_name",
    "file_path",
    "source_path",
    "source_kind",
    "source_member",
    "source_file",
    "quality_status",
    "status",
    "severity",
    "dataset",
    "check",
    "columns_hash",
    "weight_unit",
    "volume_unit",
    "amount_unit",
    "total_return_available",
    "industry_standard",
    "industry_level",
    "industry_code",
    "industry_name",
    "industry_level1_code",
    "industry_level1",
    "industry_level2_code",
    "industry_level2",
    "industry_level3_code",
    "industry_level3",
    "classification_mode",
    "classification_code",
    "parent_classification_code",
    "publishes_index",
    "classification_source",
    "taxonomy_source_status",
    "dimension_standard",
    "dimension_level",
    "dimension_code",
    "dimension_name",
    "listing_board_code",
    "listing_board",
    "exchange_code",
    "exchange_suffix",
    "listing_status",
    "source_list",
    "raw_region",
    "raw_industry",
    "reference_mode",
    "scope",
    "provider",
}


class DataDirectoryReader:
    """Read generated datasets from the local data/ directory."""

    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir).expanduser()

    def dataset_path(self, dataset: str) -> Path:
        if not self.data_dir.is_dir():
            raise DataRootNotFoundError(f"Generated data directory not found: {self.data_dir}")
        path = self.data_dir / dataset
        if not path.is_dir():
            raise DataRootNotFoundError(f"Generated dataset directory not found: {path}")
        return path

    def manifest(self, dataset: str) -> dict[str, object]:
        path = self.dataset_path(dataset) / "manifest.json"
        if not path.is_file():
            raise DataFileNotFoundError(f"Generated dataset manifest not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def quality(self, dataset: str) -> pd.DataFrame:
        return self.read_csv(dataset, "data_quality.csv")

    def read_csv(self, dataset: str, filename: str | Path) -> pd.DataFrame:
        path = self.dataset_path(dataset) / filename
        if not path.is_file():
            raise DataFileNotFoundError(f"Generated dataset CSV not found: {path}")
        return _read_generated_csv(path)

    def ashare_daily_dates(self) -> pd.DataFrame:
        index = self.read_csv(ASHARE_DAILY_DATASET, "daily_metrics.csv")
        return index.sort_values("date").reset_index(drop=True)

    def ashare_daily_schema(self) -> pd.DataFrame:
        return self.read_csv(ASHARE_DAILY_DATASET, "schema.csv")

    def ashare_daily_by_date(
        self,
        date: str | pd.Timestamp,
        *,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        row = self._partition_row(
            ASHARE_DAILY_DATASET,
            "daily_metrics.csv",
            date,
            date_column="date",
        )
        df = self.read_csv(ASHARE_DAILY_DATASET, str(row["file_path"]))
        return _filter_symbols(df, column="symbol", symbols=symbols)

    def ashare_daily_range(
        self,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        *,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        index = _filter_date_range(self.ashare_daily_dates(), "date", start=start, end=end)
        frames = [self.ashare_daily_by_date(row["date"], symbols=symbols) for _, row in index.iterrows()]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).sort_values(["trade_date", "symbol"]).reset_index(drop=True)

    def index_daily(
        self,
        dataset: str,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        df = self.read_csv(dataset, "index_daily.csv")
        return _filter_date_range(df, "date", start=start, end=end).reset_index(drop=True)

    def index_weight_snapshots(self, dataset: str) -> pd.DataFrame:
        df = self.read_csv(dataset, "constituent_weights_snapshots.csv")
        return df.sort_values("date").reset_index(drop=True)

    def index_weights_by_snapshot(
        self,
        dataset: str,
        date: str | pd.Timestamp,
        *,
        members: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        row = self._partition_row(
            dataset,
            "constituent_weights_snapshots.csv",
            date,
            date_column="date",
        )
        df = self.read_csv(dataset, str(row["file_path"]))
        return _filter_symbols(df, column="member_symbol", symbols=members)

    def index_daily_asof_dates(self, dataset: str) -> pd.DataFrame:
        df = self.read_csv(dataset, "constituent_weights_daily_asof.csv")
        return df.sort_values("date").reset_index(drop=True)

    def index_weights_by_date(
        self,
        dataset: str,
        date: str | pd.Timestamp,
        *,
        members: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        row = self._partition_row(
            dataset,
            "constituent_weights_daily_asof.csv",
            date,
            date_column="date",
        )
        df = self.read_csv(dataset, str(row["file_path"]))
        return _filter_symbols(df, column="member_symbol", symbols=members)

    def index_weights_range(
        self,
        dataset: str,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        *,
        members: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        index = _filter_date_range(self.index_daily_asof_dates(dataset), "date", start=start, end=end)
        frames = [
            self.index_weights_by_date(dataset, row["date"], members=members)
            for _, row in index.iterrows()
        ]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).sort_values(["date", "member_symbol"]).reset_index(drop=True)

    def csi1000_index_daily(
        self,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        return self.index_daily(CSI1000_DATASET, start=start, end=end)

    def csi1000_weight_snapshots(self) -> pd.DataFrame:
        return self.index_weight_snapshots(CSI1000_DATASET)

    def csi1000_weights_by_snapshot(
        self,
        date: str | pd.Timestamp,
        *,
        members: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return self.index_weights_by_snapshot(CSI1000_DATASET, date, members=members)

    def csi1000_daily_asof_dates(self) -> pd.DataFrame:
        return self.index_daily_asof_dates(CSI1000_DATASET)

    def csi1000_weights_by_date(
        self,
        date: str | pd.Timestamp,
        *,
        members: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return self.index_weights_by_date(CSI1000_DATASET, date, members=members)

    def csi1000_weights_range(
        self,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        *,
        members: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return self.index_weights_range(CSI1000_DATASET, start, end, members=members)

    def sw_industry_snapshot(self, *, symbols: Sequence[str] | None = None) -> pd.DataFrame:
        df = self.read_csv(SW_INDUSTRY_DATASET, "current_snapshot.csv")
        return _filter_symbols(df, column="stock_code", symbols=symbols)

    def sw_industry_taxonomy(self, *, level: str | None = None) -> pd.DataFrame:
        df = self.read_csv(SW_INDUSTRY_DATASET, "industry_taxonomy.csv")
        if level is not None:
            df = df[df["industry_level"] == level]
        return df.reset_index(drop=True)

    def sw_industry_matrix_edges(
        self,
        *,
        symbols: Sequence[str] | None = None,
        level: str | None = None,
    ) -> pd.DataFrame:
        df = self.read_csv(SW_INDUSTRY_DATASET, "industry_matrix_edges.csv")
        if level is not None:
            df = df[df["industry_level"] == level]
        return _filter_symbols(df, column="stock_code", symbols=symbols)

    def sw_industry_matrix(
        self,
        *,
        level: str,
        stocks: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        edges = self.sw_industry_matrix_edges(level=level)
        codes = _ordered_unique(edges["industry_code"])
        return self.matrix_from_edges(
            edges,
            stock_column="stock_code",
            code_column="industry_code",
            membership_column="membership",
            stocks=stocks,
            columns=codes,
        )

    def listing_board_snapshot(self, *, symbols: Sequence[str] | None = None) -> pd.DataFrame:
        df = self.read_csv(LISTING_BOARD_DATASET, "current_snapshot.csv")
        return _filter_symbols(df, column="stock_code", symbols=symbols)

    def listing_board_taxonomy(self) -> pd.DataFrame:
        return self.read_csv(LISTING_BOARD_DATASET, "listing_board_taxonomy.csv")

    def listing_board_matrix_edges(self, *, symbols: Sequence[str] | None = None) -> pd.DataFrame:
        df = self.read_csv(LISTING_BOARD_DATASET, "listing_board_matrix_edges.csv")
        return _filter_symbols(df, column="stock_code", symbols=symbols)

    def listing_board_counts(self, *, scope: str | None = None) -> pd.DataFrame:
        df = self.read_csv(LISTING_BOARD_DATASET, "board_counts.csv")
        if scope is not None:
            df = df[df["scope"] == scope]
        return df.reset_index(drop=True)

    def listing_board_matrix(self, *, stocks: Sequence[str] | None = None) -> pd.DataFrame:
        edges = self.listing_board_matrix_edges()
        taxonomy = self.listing_board_taxonomy()
        codes = list(taxonomy.sort_values("board_order")["listing_board_code"].astype(str))
        return self.matrix_from_edges(
            edges,
            stock_column="stock_code",
            code_column="dimension_code",
            membership_column="membership",
            stocks=stocks,
            columns=codes,
        )

    def join_stock_dimensions(
        self,
        symbols: Sequence[str],
        *,
        include_industry: bool = True,
        include_listing_board: bool = True,
    ) -> pd.DataFrame:
        result = pd.DataFrame({"stock_code": list(symbols)})
        if include_industry:
            industry = self.sw_industry_snapshot()
            result = result.merge(industry, on="stock_code", how="left")
        if include_listing_board:
            board = self.listing_board_snapshot()
            board_columns = [
                "stock_code",
                "listing_board_code",
                "listing_board",
                "exchange_code",
                "exchange_suffix",
                "listing_status",
                "list_date",
                "delist_date",
                "source_list",
            ]
            if "stock_name" not in result.columns:
                board_columns.insert(1, "stock_name")
            result = result.merge(board[board_columns], on="stock_code", how="left")
        return result

    def matrix_from_edges(
        self,
        edges: pd.DataFrame,
        *,
        stock_column: str,
        code_column: str,
        membership_column: str = "membership",
        stocks: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        if stocks is None:
            stock_index = _ordered_unique(edges[stock_column])
        else:
            stock_index = list(stocks)
        if columns is None:
            dimension_columns = _ordered_unique(edges[code_column])
        else:
            dimension_columns = list(columns)
        matrix = pd.DataFrame(0, index=stock_index, columns=dimension_columns, dtype=int)
        for _, row in edges.iterrows():
            stock = row[stock_column]
            code = row[code_column]
            if pd.isna(stock) or pd.isna(code):
                continue
            stock_text = str(stock)
            code_text = str(code)
            if stock_text in matrix.index and code_text in matrix.columns:
                value = row[membership_column]
                matrix.loc[stock_text, code_text] = 0 if pd.isna(value) else int(value)
        return matrix

    def _partition_row(
        self,
        dataset: str,
        index_filename: str,
        date: str | pd.Timestamp,
        *,
        date_column: str,
    ) -> pd.Series:
        target_date = parse_date_value(date)
        if target_date is None:
            raise ValueError("date must be a valid date")
        index = self.read_csv(dataset, index_filename)
        matched = index[index[date_column] == target_date]
        if matched.empty:
            raise DataFileNotFoundError(f"No generated partition for {dataset} on {target_date.date()}")
        return matched.iloc[0]


def _read_generated_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={column: "string" for column in STRING_COLUMNS})
    for column in DATE_COLUMNS.intersection(df.columns):
        df[column] = pd.to_datetime(df[column], errors="coerce")
    return df


def _filter_symbols(
    df: pd.DataFrame,
    *,
    column: str,
    symbols: Sequence[str] | None,
) -> pd.DataFrame:
    if symbols is None:
        return df.reset_index(drop=True)
    symbol_set = {symbol.strip() for symbol in symbols}
    return df[df[column].isin(symbol_set)].reset_index(drop=True)


def _filter_date_range(
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


def _ordered_unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if pd.isna(value):
            continue
        text = str(value)
        if text not in seen:
            result.append(text)
            seen.add(text)
    return result
