from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

ASHARE_DAILY_ENV = "FINFACT_ASHARE_DAILY_DIR"
INDEX_DATA_ENV = "FINFACT_INDEX_DATA_DIR"
DEFAULT_ASHARE_DAILY_DIR = Path("/Users/sun/Downloads/A股数据_每日指标")
DEFAULT_INDEX_DATA_DIR = Path("/Users/sun/Downloads/指数数据")
PathLike: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]


def resolve_path(value: PathLike | None, env_var: str, default: Path) -> Path:
    if value is not None:
        return Path(value).expanduser()
    env_value = os.environ.get(env_var)
    if env_value:
        return Path(env_value).expanduser()
    return default


@dataclass(frozen=True)
class FinfactConfig:
    ashare_daily_dir: Path
    index_data_dir: Path

    @classmethod
    def from_values(
        cls,
        ashare_daily_dir: PathLike | None = None,
        index_data_dir: PathLike | None = None,
    ) -> "FinfactConfig":
        return cls(
            ashare_daily_dir=resolve_path(
                ashare_daily_dir,
                ASHARE_DAILY_ENV,
                DEFAULT_ASHARE_DAILY_DIR,
            ),
            index_data_dir=resolve_path(
                index_data_dir,
                INDEX_DATA_ENV,
                DEFAULT_INDEX_DATA_DIR,
            ),
        )
