from __future__ import annotations

from functools import cached_property

from finfact_io.config import FinfactConfig, PathLike
from finfact_io.datasets.ashare import AShareDailyStore
from finfact_io.datasets.constituents import ConstituentsStore
from finfact_io.datasets.index import IndexDataStore
from finfact_io.datasets.industry import IndustryDataStore
from finfact_io.datasets.listing_board import ListingBoardStore


class FinfactStore:
    def __init__(
        self,
        ashare_daily_dir: PathLike | None = None,
        index_data_dir: PathLike | None = None,
        *,
        raw_data_dir: PathLike | None = None,
    ) -> None:
        self.config = FinfactConfig.from_values(
            ashare_daily_dir=ashare_daily_dir,
            index_data_dir=index_data_dir,
            raw_data_dir=raw_data_dir,
        )

    @cached_property
    def ashare(self) -> AShareDailyStore:
        return AShareDailyStore(self.config.ashare_daily_dir)

    @cached_property
    def index(self) -> IndexDataStore:
        return IndexDataStore(self.config.index_data_dir)

    @cached_property
    def industry(self) -> IndustryDataStore:
        return IndustryDataStore(self.config.index_data_dir)

    @cached_property
    def constituents(self) -> ConstituentsStore:
        return ConstituentsStore(self.config.index_data_dir)

    @cached_property
    def listing_board(self) -> ListingBoardStore:
        return ListingBoardStore(self.config.ashare_daily_dir)
