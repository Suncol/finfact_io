from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

RAW_DATA_ENV = "FINFACT_RAW_DATA_DIR"
ASHARE_DAILY_ENV = "FINFACT_ASHARE_DAILY_DIR"
INDEX_DATA_ENV = "FINFACT_INDEX_DATA_DIR"
ASHARE_DAILY_SUBDIR = Path("A股数据_每日指标")
INDEX_DATA_SUBDIR = Path("指数数据")
DEFAULT_RAW_DATA_DIR = Path("/data/A-share/raw_data_tb")
DEFAULT_ASHARE_DAILY_DIR = DEFAULT_RAW_DATA_DIR / ASHARE_DAILY_SUBDIR
DEFAULT_INDEX_DATA_DIR = DEFAULT_RAW_DATA_DIR / INDEX_DATA_SUBDIR
PathLike: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]


def resolve_path(value: PathLike | None, env_var: str, default: Path) -> Path:
    if value is not None:
        return Path(value).expanduser()
    env_value = os.environ.get(env_var)
    if env_value:
        return Path(env_value).expanduser()
    return default


def resolve_raw_data_dir(value: PathLike | None = None) -> Path:
    return resolve_path(value, RAW_DATA_ENV, DEFAULT_RAW_DATA_DIR)


def resolve_ashare_daily_dir(
    value: PathLike | None = None,
    *,
    raw_data_dir: PathLike | None = None,
) -> Path:
    return _resolve_dataset_dir(
        value,
        env_var=ASHARE_DAILY_ENV,
        raw_data_dir=raw_data_dir,
        subdir=ASHARE_DAILY_SUBDIR,
    )


def resolve_index_data_dir(
    value: PathLike | None = None,
    *,
    raw_data_dir: PathLike | None = None,
) -> Path:
    return _resolve_dataset_dir(
        value,
        env_var=INDEX_DATA_ENV,
        raw_data_dir=raw_data_dir,
        subdir=INDEX_DATA_SUBDIR,
    )


def _resolve_dataset_dir(
    value: PathLike | None,
    *,
    env_var: str,
    raw_data_dir: PathLike | None,
    subdir: Path,
) -> Path:
    if value is not None:
        return Path(value).expanduser()
    env_value = os.environ.get(env_var)
    if env_value:
        return Path(env_value).expanduser()
    return resolve_raw_data_dir(raw_data_dir) / subdir


@dataclass(frozen=True)
class FinfactConfig:
    raw_data_dir: Path
    ashare_daily_dir: Path
    index_data_dir: Path

    @classmethod
    def from_values(
        cls,
        ashare_daily_dir: PathLike | None = None,
        index_data_dir: PathLike | None = None,
        raw_data_dir: PathLike | None = None,
    ) -> "FinfactConfig":
        resolved_raw_data_dir = resolve_raw_data_dir(raw_data_dir)
        return cls(
            raw_data_dir=resolved_raw_data_dir,
            ashare_daily_dir=resolve_ashare_daily_dir(
                ashare_daily_dir,
                raw_data_dir=resolved_raw_data_dir,
            ),
            index_data_dir=resolve_index_data_dir(
                index_data_dir,
                raw_data_dir=resolved_raw_data_dir,
            ),
        )
