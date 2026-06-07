from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from finfact_io.errors import DataFileNotFoundError

BUILT_LISTING_BOARD_DIR = Path("data") / "listing_board_current_reference"


class ListingBoardStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def current_snapshot(
        self,
        *,
        dataset_dir: str | Path = BUILT_LISTING_BOARD_DIR,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        df = _read_dataset_csv(dataset_dir, "current_snapshot.csv")
        if symbols is not None:
            symbol_set = {symbol.strip() for symbol in symbols}
            df = df[df["stock_code"].isin(symbol_set)]
        return df.reset_index(drop=True)

    def taxonomy(
        self,
        *,
        dataset_dir: str | Path = BUILT_LISTING_BOARD_DIR,
    ) -> pd.DataFrame:
        return _read_dataset_csv(dataset_dir, "listing_board_taxonomy.csv")

    def matrix_edges(
        self,
        *,
        dataset_dir: str | Path = BUILT_LISTING_BOARD_DIR,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        df = _read_dataset_csv(dataset_dir, "listing_board_matrix_edges.csv")
        if symbols is not None:
            symbol_set = {symbol.strip() for symbol in symbols}
            df = df[df["stock_code"].isin(symbol_set)]
        return df.reset_index(drop=True)

    def board_counts(
        self,
        *,
        dataset_dir: str | Path = BUILT_LISTING_BOARD_DIR,
    ) -> pd.DataFrame:
        return _read_dataset_csv(dataset_dir, "board_counts.csv")


def _read_dataset_csv(dataset_dir: str | Path, filename: str) -> pd.DataFrame:
    path = Path(dataset_dir).expanduser() / filename
    if not path.is_file():
        raise DataFileNotFoundError(f"Listing board reference file not found: {path}")
    return pd.read_csv(path, dtype={"stock_code": "string", "dimension_code": "string"})
