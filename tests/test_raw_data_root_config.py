from __future__ import annotations

import json
from pathlib import Path

import finfact_io.config as config
from finfact_io import FinfactStore
from finfact_io.exports.ashare_daily_metrics import build_ashare_daily_metrics_dataset
from finfact_io.exports.index_point_in_time import build_csi300_dataset
from finfact_io.exports.listing_board_reference import build_listing_board_reference_dataset
from test_ashare_daily_metrics_export import build_ashare_daily_metrics_root
from test_index_point_in_time_export import build_multi_index_root
from test_listing_board_reference_export import build_listing_board_root


def test_defaults_are_derived_from_raw_data_root(monkeypatch) -> None:
    monkeypatch.delenv("FINFACT_RAW_DATA_DIR", raising=False)
    monkeypatch.delenv("FINFACT_ASHARE_DAILY_DIR", raising=False)
    monkeypatch.delenv("FINFACT_INDEX_DATA_DIR", raising=False)

    assert config.DEFAULT_RAW_DATA_DIR == Path("/data/A-share/raw_data_tb")
    assert config.DEFAULT_ASHARE_DAILY_DIR == config.DEFAULT_RAW_DATA_DIR / "A股数据_每日指标"
    assert config.DEFAULT_INDEX_DATA_DIR == config.DEFAULT_RAW_DATA_DIR / "指数数据"

    resolved = config.FinfactConfig.from_values()

    assert resolved.ashare_daily_dir == Path("/data/A-share/raw_data_tb/A股数据_每日指标")
    assert resolved.index_data_dir == Path("/data/A-share/raw_data_tb/指数数据")


def test_raw_data_env_derives_dataset_roots_and_specific_env_wins(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_root = tmp_path / "raw"
    custom_index = tmp_path / "custom-index"
    monkeypatch.setenv("FINFACT_RAW_DATA_DIR", str(raw_root))
    monkeypatch.setenv("FINFACT_INDEX_DATA_DIR", str(custom_index))
    monkeypatch.delenv("FINFACT_ASHARE_DAILY_DIR", raising=False)

    resolved = config.FinfactConfig.from_values()

    assert resolved.ashare_daily_dir == raw_root / "A股数据_每日指标"
    assert resolved.index_data_dir == custom_index


def test_finfact_store_accepts_raw_data_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FINFACT_RAW_DATA_DIR", raising=False)
    monkeypatch.delenv("FINFACT_ASHARE_DAILY_DIR", raising=False)
    monkeypatch.delenv("FINFACT_INDEX_DATA_DIR", raising=False)
    raw_root = tmp_path / "raw-data"

    store = FinfactStore(raw_data_dir=raw_root)

    assert store.config.ashare_daily_dir == raw_root / "A股数据_每日指标"
    assert store.config.index_data_dir == raw_root / "指数数据"


def test_export_builders_use_raw_data_env_when_specific_roots_are_omitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_root = tmp_path / "raw"
    ashare_root = raw_root / "A股数据_每日指标"
    index_root = raw_root / "指数数据"
    build_ashare_daily_metrics_root(ashare_root)
    build_multi_index_root(index_root)
    build_listing_board_root(ashare_root)
    monkeypatch.setenv("FINFACT_RAW_DATA_DIR", str(raw_root))
    monkeypatch.delenv("FINFACT_ASHARE_DAILY_DIR", raising=False)
    monkeypatch.delenv("FINFACT_INDEX_DATA_DIR", raising=False)

    ashare_report = build_ashare_daily_metrics_dataset(
        output_dir=tmp_path / "out-ashare",
        start="2024-01-02",
        end="2024-01-03",
    )
    index_report = build_csi300_dataset(
        output_dir=tmp_path / "out-csi300",
        include_daily_asof=False,
    )
    listing_report = build_listing_board_reference_dataset(
        output_dir=tmp_path / "out-listing",
    )

    ashare_manifest = json.loads((ashare_report.output_dir / "manifest.json").read_text(encoding="utf-8"))
    index_manifest = json.loads((index_report.output_dir / "manifest.json").read_text(encoding="utf-8"))
    listing_manifest = json.loads((listing_report.output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert ashare_manifest["source_root"] == str(ashare_root)
    assert index_manifest["source_root"] == str(index_root)
    assert listing_manifest["source_root"] == str(ashare_root)
