from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from finfact_io.exports.industry_sw_reference import (
    build_industry_matrix,
    build_industry_sw_reference_dataset,
    calculate_active_exposure,
)


def write_csv(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def build_sw_reference_roots(tmp_path: Path) -> tuple[Path, Path]:
    index_root = tmp_path / "index"
    ashare_root = tmp_path / "ashare"

    taxonomy_header = "指数代码,行业名称,行业分级,行业代码,是否发布指数,父级代码,分类来源\n"
    write_csv(
        index_root / "申万行业分类" / "申万行业分类_L1_SW2021.csv",
        taxonomy_header
        + "801010.SI,农林牧渔,L1,110000,是,0,SW2021\n"
        + "801780.SI,银行,L1,410000,是,0,SW2021\n",
    )
    write_csv(
        index_root / "申万行业分类" / "申万行业分类_L2_SW2021.csv",
        taxonomy_header
        + "801011.SI,林业Ⅱ,L2,110300,否,110000,SW2021\n"
        + "801782.SI,股份制银行Ⅱ,L2,410200,是,410000,SW2021\n",
    )
    write_csv(
        index_root / "申万行业分类" / "申万行业分类_L3_SW2021.csv",
        taxonomy_header
        + "850131.SI,林业Ⅲ,L3,110301,否,110300,SW2021\n"
        + "851911.SI,股份制银行Ⅲ,L3,410201,是,410200,SW2021\n",
    )

    write_csv(
        index_root / "申万行业成分_每日更新" / "2026-06" / "申万行业成分_20260603.csv",
        (
            "一级行业代码,一级行业名称,二级行业代码,二级行业名称,"
            "三级行业代码,三级行业名称,股票代码,股票名称,纳入日期,剔除日期\n"
            "801780.SI,银行,801782.SI,股份制银行Ⅱ,851911.SI,股份制银行Ⅲ,000001.SZ,平安银行,19910403,\n"
            "801010.SI,农林牧渔,801011.SI,林业Ⅱ,850131.SI,林业Ⅲ,000592.SZ,平潭发展,20091009,\n"
        ),
    )

    write_csv(
        ashare_root / "股票列表.csv",
        (
            "TS代码,股票代码,股票名称,地域,所属行业,股票全称,英文全称,拼音缩写,"
            "市场类型,交易所代码,交易货币,上市状态,上市日期,退市日期,沪深港通标的,"
            "实控人名称,实控人企业性质\n"
            "000001.SZ,000001,平安银行,深圳,银行,平安银行股份有限公司,"
            "Ping An Bank,PAYH,主板,SZSE,CNY,上市,19910403,,是,,\n"
            "000592.SZ,000592,平潭发展,福建,农林牧渔,中福海峡(平潭)发展股份有限公司,"
            "Pingtan Marine,PTFZ,主板,SZSE,CNY,上市,19960327,,否,,\n"
        ),
    )
    write_csv(
        ashare_root / "退市股票列表.csv",
        (
            "TS代码,股票代码,股票名称,地域,所属行业,股票全称,英文全称,拼音缩写,"
            "市场类型,交易所代码,交易货币,上市状态,上市日期,退市日期,沪深港通标的,"
            "实控人名称,实控人企业性质\n"
        ),
    )
    return index_root, ashare_root


def test_build_industry_sw_reference_dataset_writes_single_lookup_and_edges(tmp_path: Path) -> None:
    index_root, ashare_root = build_sw_reference_roots(tmp_path)
    output_dir = tmp_path / "out"

    report = build_industry_sw_reference_dataset(
        index_data_dir=index_root,
        ashare_daily_dir=ashare_root,
        output_dir=output_dir,
    )

    assert report.row_counts == {
        "current_snapshot": 2,
        "industry_taxonomy": 6,
        "industry_matrix_edges": 6,
        "data_quality": 8,
    }
    assert not (output_dir / "daily_reference.csv").exists()
    assert not (output_dir / "daily_reference").exists()

    snapshot = pd.read_csv(output_dir / "current_snapshot.csv")
    assert list(snapshot["stock_code"]) == ["000001.SZ", "000592.SZ"]
    assert set(snapshot["industry_standard"]) == {"SW2021"}
    assert set(snapshot["classification_snapshot_date"]) == {"2026-06-03"}
    assert set(snapshot["classification_mode"]) == {"static_current_reference"}
    assert set(snapshot["quality_status"]) == {"complete"}

    edges = pd.read_csv(output_dir / "industry_matrix_edges.csv")
    assert len(edges) == 6
    assert set(edges["industry_level"]) == {"L1", "L2", "L3"}
    assert edges.groupby(["stock_code", "industry_level"]).size().max() == 1
    assert set(edges["membership"]) == {1}
    pingan_l1 = edges[(edges["stock_code"] == "000001.SZ") & (edges["industry_level"] == "L1")].iloc[0]
    assert pingan_l1["industry_code"] == "801780.SI"
    assert pingan_l1["industry_name"] == "银行"

    quality = pd.read_csv(output_dir / "data_quality.csv")
    assert set(quality["status"]) == {"pass"}

    assert {
        "current_snapshot_unique_stock",
        "current_snapshot_no_missing_l1_l2_l3",
        "current_snapshot_taxonomy_codes_exist",
        "current_snapshot_taxonomy_parent_consistent",
        "matrix_edges_one_membership_per_stock_level",
        "matrix_edges_expected_row_count",
        "listed_stock_coverage",
        "static_reference_mode_declared",
    } == set(quality["check"])

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["industry_standard"] == "SW2021"
    assert manifest["classification_snapshot_date"] == "2026-06-03"
    assert manifest["classification_mode"] == "static_current_reference"
    assert manifest["historical_pit_industry"] is False
    assert manifest["taxonomy_inferred_from_snapshot"]["count"] == 0
    assert manifest["files"]["current_snapshot.csv"]["rows"] == 2
    assert manifest["files"]["industry_matrix_edges.csv"]["rows"] == 6


def test_matrix_and_active_exposure_use_static_lookup_without_date_expansion(tmp_path: Path) -> None:
    index_root, ashare_root = build_sw_reference_roots(tmp_path)
    output_dir = tmp_path / "out"
    build_industry_sw_reference_dataset(
        index_data_dir=index_root,
        ashare_daily_dir=ashare_root,
        output_dir=output_dir,
    )
    edges = pd.read_csv(output_dir / "industry_matrix_edges.csv")

    matrix = build_industry_matrix(edges, stocks=["000001.SZ", "000592.SZ", "999999.SZ"], level="L1")

    assert list(matrix.index) == ["000001.SZ", "000592.SZ", "999999.SZ"]
    assert matrix.loc["000001.SZ", "801780.SI"] == 1
    assert matrix.loc["000592.SZ", "801010.SI"] == 1
    assert matrix.loc["999999.SZ"].sum() == 0

    exposure = calculate_active_exposure(
        edges,
        portfolio_weights={"000001.SZ": 0.60, "000592.SZ": 0.40},
        benchmark_weights={"000001.SZ": 0.50, "000592.SZ": 0.20, "999999.SZ": 0.30},
        level="L1",
        date="2020-01-02",
    )

    by_code = exposure.set_index("industry_code")
    assert by_code.loc["801780.SI", "active_exposure"] == 0.10
    assert by_code.loc["801010.SI", "active_exposure"] == 0.20
    assert set(exposure["date"]) == {"2020-01-02"}
    assert set(exposure["classification_snapshot_date"]) == {"2026-06-03"}
    assert set(exposure["classification_mode"]) == {"static_current_reference"}
    assert set(exposure["unclassified_benchmark_weight"]) == {0.30}


def test_build_augments_taxonomy_codes_that_exist_only_in_current_snapshot(tmp_path: Path) -> None:
    index_root, ashare_root = build_sw_reference_roots(tmp_path)
    output_dir = tmp_path / "out"
    write_csv(
        index_root / "申万行业分类" / "申万行业分类_L3_SW2021.csv",
        (
            "指数代码,行业名称,行业分级,行业代码,是否发布指数,父级代码,分类来源\n"
            "851911.SI,股份制银行Ⅲ,L3,410201,是,410200,SW2021\n"
        ),
    )

    build_industry_sw_reference_dataset(
        index_data_dir=index_root,
        ashare_daily_dir=ashare_root,
        output_dir=output_dir,
    )

    taxonomy = pd.read_csv(output_dir / "industry_taxonomy.csv")
    inferred = taxonomy[taxonomy["industry_code"] == "850131.SI"].iloc[0]
    assert inferred["industry_name"] == "林业Ⅲ"
    assert inferred["industry_level"] == "L3"
    assert str(inferred["parent_classification_code"]) == "110300"
    assert inferred["taxonomy_source_status"] == "snapshot_inferred"

    quality = pd.read_csv(output_dir / "data_quality.csv")
    assert set(quality["status"]) == {"pass"}

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["taxonomy_inferred_from_snapshot"]["count"] == 1
    assert manifest["taxonomy_inferred_from_snapshot"]["codes"][0]["industry_code"] == "850131.SI"
