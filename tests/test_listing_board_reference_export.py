from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from finfact_io import FinfactStore
from finfact_io.exports.listing_board_reference import build_listing_board_reference_dataset


STOCK_HEADER = (
    "TS代码,股票代码,股票名称,地域,所属行业,股票全称,英文全称,拼音缩写,"
    "市场类型,交易所代码,交易货币,上市状态,上市日期,退市日期,沪深港通标的,"
    "实控人名称,实控人企业性质\n"
)


def write_csv(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def build_listing_board_root(root: Path) -> Path:
    write_csv(
        root / "股票列表.csv",
        STOCK_HEADER
        + "000001.SZ,000001,平安银行,深圳,银行,平安银行股份有限公司,Ping An Bank,PAYH,主板,SZSE,CNY,上市,19910403,,是,,\n"
        + "300001.SZ,300001,特锐德,山东,电气设备,青岛特锐德电气股份有限公司,TGOOD,TRD,创业板,SZSE,CNY,上市,20091030,,否,,\n"
        + "688001.SH,688001,华兴源创,江苏,专用机械,苏州华兴源创科技股份有限公司,HYC, HXYC,科创板,SSE,CNY,上市,20190722,,否,,\n"
        + "920001.BJ,920001,北交样本,北京,软件服务,北交样本股份有限公司,BSE Sample,BJYB,北交所,BSE,CNY,上市,20211115,,否,,\n",
    )
    write_csv(
        root / "退市股票列表.csv",
        STOCK_HEADER
        + "000001.SZ,000001,平安银行旧记录,深圳,银行,平安银行股份有限公司,Ping An Bank,PAYH,主板,SZSE,CNY,退市,19910403,19991231,否,,\n"
        + "000003.SZ,000003,PT金田A,深圳,综合,金田实业股份有限公司,Jintian,JT,主板,SZSE,CNY,退市,19910703,20020614,否,,\n"
        + "300002.SZ,300002,神州泰岳,北京,软件服务,北京神州泰岳软件股份有限公司,Ultrapower,SZTY,创业板,SZSE,CNY,退市,20091030,20200101,否,,\n"
        + "688002.SH,688002,睿创微纳,山东,半导体,烟台睿创微纳技术股份有限公司,Raytron,RCWN,科创板,SSE,CNY,退市,20190722,20230101,否,,\n"
        + "430001.BJ,430001,世纪瑞尔,北京,运输设备,北京世纪瑞尔技术股份有限公司,Century Real,SJRE,北交所,BSE,CNY,退市,20110101,20220101,否,,\n",
    )
    return root


def test_build_listing_board_reference_dataset_writes_snapshot_taxonomy_edges_and_quality(tmp_path: Path) -> None:
    source_root = build_listing_board_root(tmp_path / "source")
    output_dir = tmp_path / "out"

    report = build_listing_board_reference_dataset(
        ashare_daily_dir=source_root,
        output_dir=output_dir,
    )

    assert report.row_counts == {
        "current_snapshot": 8,
        "listing_board_taxonomy": 4,
        "listing_board_matrix_edges": 8,
        "board_counts": 12,
        "data_quality": 8,
    }

    snapshot = pd.read_csv(output_dir / "current_snapshot.csv")
    assert list(snapshot["stock_code"]) == [
        "000001.SZ",
        "000003.SZ",
        "300001.SZ",
        "300002.SZ",
        "430001.BJ",
        "688001.SH",
        "688002.SH",
        "920001.BJ",
    ]
    assert snapshot.set_index("stock_code").loc["000001.SZ", "source_list"] == "listed"
    assert snapshot.set_index("stock_code").loc["000001.SZ", "stock_name"] == "平安银行"
    assert set(snapshot["reference_mode"]) == {"static_current_reference"}
    assert set(snapshot["dimension_standard"]) == {"A_SHARE_LISTING_BOARD"}
    assert set(snapshot["quality_status"]) == {"complete"}

    board_by_code = snapshot.set_index("stock_code")["listing_board_code"].to_dict()
    assert board_by_code == {
        "000001.SZ": "MAIN",
        "000003.SZ": "MAIN",
        "300001.SZ": "CHINEXT",
        "300002.SZ": "CHINEXT",
        "430001.BJ": "BSE",
        "688001.SH": "STAR",
        "688002.SH": "STAR",
        "920001.BJ": "BSE",
    }

    taxonomy = pd.read_csv(output_dir / "listing_board_taxonomy.csv")
    assert list(taxonomy["listing_board_code"]) == ["MAIN", "CHINEXT", "STAR", "BSE"]
    assert list(taxonomy["listing_board"]) == ["主板", "创业板", "科创板", "北交所"]

    edges = pd.read_csv(output_dir / "listing_board_matrix_edges.csv")
    assert len(edges) == 8
    assert set(edges["dimension_level"]) == {"listing_board"}
    assert set(edges["membership"]) == {1}
    assert edges.groupby(["stock_code", "dimension_level"]).size().max() == 1

    counts = pd.read_csv(output_dir / "board_counts.csv")
    total_counts = counts[counts["scope"] == "all"].set_index("listing_board_code")["stock_count"].to_dict()
    assert total_counts == {"MAIN": 2, "CHINEXT": 2, "STAR": 2, "BSE": 2}
    listed_counts = counts[counts["scope"] == "listed"].set_index("listing_board_code")["stock_count"].to_dict()
    assert listed_counts == {"MAIN": 1, "CHINEXT": 1, "STAR": 1, "BSE": 1}
    delisted_counts = counts[counts["scope"] == "delisted"].set_index("listing_board_code")["stock_count"].to_dict()
    assert delisted_counts == {"MAIN": 1, "CHINEXT": 1, "STAR": 1, "BSE": 1}

    quality = pd.read_csv(output_dir / "data_quality.csv")
    assert set(quality["status"]) == {"pass"}
    quality_by_check = quality.set_index("check")
    assert str(quality_by_check.loc["unique_stock_code", "observed_value"]) == "0"
    assert str(quality_by_check.loc["duplicate_source_stock_codes_resolved", "observed_value"]) == "1"
    assert str(quality_by_check.loc["missing_listing_board", "observed_value"]) == "0"
    assert str(quality_by_check.loc["exchange_board_consistency", "observed_value"]) == "0"

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"] == "listing_board_current_reference"
    assert manifest["dimension_standard"] == "A_SHARE_LISTING_BOARD"
    assert manifest["reference_mode"] == "static_current_reference"
    assert manifest["historical_pit_listing_board"] is False
    assert manifest["source_policy"]["listed_stock_file"].endswith("股票列表.csv")
    assert manifest["files"]["current_snapshot.csv"]["rows"] == 8


def test_listing_board_store_reads_built_reference_and_filters_symbols(tmp_path: Path) -> None:
    source_root = build_listing_board_root(tmp_path / "source")
    output_dir = tmp_path / "out"
    build_listing_board_reference_dataset(
        ashare_daily_dir=source_root,
        output_dir=output_dir,
    )
    listing_board = FinfactStore(ashare_daily_dir=source_root).listing_board

    snapshot = listing_board.current_snapshot(dataset_dir=output_dir, symbols=["688001.SH", "920001.BJ"])
    assert list(snapshot["stock_code"]) == ["688001.SH", "920001.BJ"]
    assert list(snapshot["listing_board_code"]) == ["STAR", "BSE"]

    edges = listing_board.matrix_edges(dataset_dir=output_dir, symbols=["000001.SZ"])
    assert list(edges["dimension_code"]) == ["MAIN"]

    taxonomy = listing_board.taxonomy(dataset_dir=output_dir)
    assert list(taxonomy["listing_board_code"]) == ["MAIN", "CHINEXT", "STAR", "BSE"]

    counts = listing_board.board_counts(dataset_dir=output_dir)
    assert counts[counts["scope"] == "all"]["stock_count"].sum() == 8
