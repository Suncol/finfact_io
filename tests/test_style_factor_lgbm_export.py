from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

from finfact_io.exports.style_factor_lgbm import StyleIndexDatasetSpec, build_lgbm_style_factor_dataset


_HELPERS_PATH = Path(__file__).with_name("test_style_factor_matrix_export.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("style_factor_matrix_test_helpers", _HELPERS_PATH)
if _HELPERS_SPEC is None or _HELPERS_SPEC.loader is None:
    raise RuntimeError(f"Unable to load fixture helpers from {_HELPERS_PATH}")
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

write_csv = _HELPERS.write_csv

TEST_INDEX_SPECS = (
    StyleIndexDatasetSpec("hs300", "csi300", "000300.SH", expected_member_count=2),
    StyleIndexDatasetSpec("csi500", "csi500", "000905.SH", expected_member_count=1),
    StyleIndexDatasetSpec("csi1000", "csi1000", "000852.SH", expected_member_count=1),
    StyleIndexDatasetSpec("csi2000", "csi2000", "932000.CSI", expected_member_count=1),
)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_build_lgbm_style_factor_dataset_writes_compact_categorical_features(tmp_path: Path) -> None:
    data_dir = build_generated_data_dir(tmp_path / "data")
    output_dir = tmp_path / "style_lgbm"

    report = build_lgbm_style_factor_dataset(
        data_dir=data_dir,
        output_dir=output_dir,
        index_specs=TEST_INDEX_SPECS,
    )

    assert report.date_range == ("2026-01-05", "2026-01-06")
    assert report.row_counts["lgbm_style_factor_rows"] == 6

    daily_index = pd.read_csv(output_dir / "lgbm_style_factors.csv")
    assert list(daily_index["date"]) == ["2026-01-05", "2026-01-06"]
    assert list(daily_index["rows"]) == [3, 3]

    jan5 = pd.read_csv(output_dir / "lgbm_style_factors" / "2026-01" / "2026-01-05.csv")
    assert list(jan5.columns) == [
        "trade_date",
        "symbol",
        "industry_l1_code_id",
        "listing_board_id",
        "size_tier",
        "total_market_cap_rank_pct",
    ]
    forbidden_columns = {
        "total_market_cap_10k_yuan",
        "total_market_cap_rank",
        "total_market_cap_log10",
        "in_hs300",
        "in_csi500",
        "in_csi1000",
        "in_csi2000",
    }
    assert forbidden_columns.isdisjoint(jan5.columns)
    assert not any(column.startswith("industry_sw_l1_") for column in jan5.columns)

    by_symbol = jan5.set_index("symbol")
    assert by_symbol.loc["000001.SZ", "industry_l1_code_id"] == 1
    assert by_symbol.loc["000002.SZ", "industry_l1_code_id"] == 2
    assert by_symbol.loc["000003.SZ", "industry_l1_code_id"] == 3
    assert by_symbol.loc["000001.SZ", "listing_board_id"] == 1
    assert by_symbol.loc["000002.SZ", "listing_board_id"] == 1
    assert by_symbol.loc["000003.SZ", "listing_board_id"] == 1
    assert by_symbol.loc["000001.SZ", "size_tier"] == 1
    assert by_symbol.loc["000002.SZ", "size_tier"] == 1
    assert by_symbol.loc["000003.SZ", "size_tier"] == 2
    assert by_symbol.loc["000001.SZ", "total_market_cap_rank_pct"] == 0.5
    assert by_symbol.loc["000002.SZ", "total_market_cap_rank_pct"] == 1.0
    assert pd.isna(by_symbol.loc["000003.SZ", "total_market_cap_rank_pct"])

    categories = pd.read_csv(output_dir / "category_mappings.csv")
    category_keys = set(zip(categories["feature"], categories["category_id"]))
    assert ("industry_l1_code_id", 0) in category_keys
    assert ("industry_l1_code_id", 1) in category_keys
    assert ("listing_board_id", 1) in category_keys
    assert ("listing_board_id", 4) in category_keys
    assert ("size_tier", 0) in category_keys
    assert ("size_tier", 4) in category_keys
    board_names = categories[categories["feature"] == "listing_board_id"].set_index("category_id")["category_label"]
    assert board_names.loc[1] == "主板"
    assert board_names.loc[2] == "创业板"
    assert board_names.loc[3] == "科创板"
    assert board_names.loc[4] == "北交所"
    size_names = categories[categories["feature"] == "size_tier"].set_index("category_id")["category_label"]
    assert size_names.loc[1] == "沪深300"
    assert size_names.loc[4] == "中证2000"

    schema = pd.read_csv(output_dir / "schema.csv")
    roles = schema.set_index("column")["role"].to_dict()
    assert roles == {
        "trade_date": "key",
        "symbol": "key",
        "industry_l1_code_id": "categorical_feature",
        "listing_board_id": "categorical_feature",
        "size_tier": "ordered_categorical_feature",
        "total_market_cap_rank_pct": "numeric_style_factor",
    }

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"] == "lgbm_style_factors"
    assert manifest["date_range"] == {"start": "2026-01-05", "end": "2026-01-06"}
    assert manifest["data_dir"] == str(data_dir)
    assert "ashare_daily_root" not in manifest
    assert "index_data_root" not in manifest
    assert manifest["categorical_features"] == ["industry_l1_code_id", "listing_board_id", "size_tier"]
    assert manifest["feature_columns"] == [
        "industry_l1_code_id",
        "listing_board_id",
        "size_tier",
        "total_market_cap_rank_pct",
    ]
    assert manifest["market_cap"]["included_transforms"] == ["daily_cross_section_rank_pct"]
    assert manifest["market_cap"]["excluded_transforms"] == ["raw", "rank", "log10"]
    assert manifest["index_membership"]["encoding"] == "single_ordered_size_tier"
    assert manifest["index_membership"]["availability"]["hs300"]["dataset"] == "csi300"
    assert manifest["stock_universe"]["include_bse"] is False
    assert manifest["listing_board_reference"]["historical_pit_listing_board"] is False
    assert manifest["risk_notes"]["short_sample_start"] == "2026-01-05"
    assert manifest["industry_reference"]["historical_pit_industry"] is False


def test_build_lgbm_style_factor_dataset_raises_when_date_intersection_is_empty(tmp_path: Path) -> None:
    data_dir = build_generated_data_dir(tmp_path / "data")

    try:
        build_lgbm_style_factor_dataset(
            data_dir=data_dir,
            output_dir=tmp_path / "out",
            start="2026-01-02",
            end="2026-01-02",
            index_specs=TEST_INDEX_SPECS,
        )
    except Exception as exc:
        assert "No LGBM style factor dates" in str(exc)
    else:
        raise AssertionError("Expected an empty date intersection error")


def test_build_lgbm_style_factor_dataset_excludes_bse_by_default_and_can_include_it(tmp_path: Path) -> None:
    data_dir = build_generated_data_dir(tmp_path / "data")
    append_bse_daily_metric_rows(data_dir)
    append_bse_industry_reference(data_dir / "industry_sw_current_reference")

    default_report = build_lgbm_style_factor_dataset(
        data_dir=data_dir,
        output_dir=tmp_path / "default_no_bse",
        index_specs=TEST_INDEX_SPECS,
    )
    assert default_report.row_counts["lgbm_style_factor_rows"] == 6
    default_jan5 = pd.read_csv(tmp_path / "default_no_bse" / "lgbm_style_factors" / "2026-01" / "2026-01-05.csv")
    assert "920001.BJ" not in set(default_jan5["symbol"])
    default_manifest = json.loads((tmp_path / "default_no_bse" / "manifest.json").read_text(encoding="utf-8"))
    assert default_manifest["stock_universe"]["include_bse"] is False
    assert default_manifest["stock_universe"]["excluded_board_codes"] == ["BSE"]

    include_report = build_lgbm_style_factor_dataset(
        data_dir=data_dir,
        output_dir=tmp_path / "include_bse",
        include_bse=True,
        index_specs=TEST_INDEX_SPECS,
    )
    assert include_report.row_counts["lgbm_style_factor_rows"] == 8
    include_jan5 = pd.read_csv(tmp_path / "include_bse" / "lgbm_style_factors" / "2026-01" / "2026-01-05.csv")
    by_symbol = include_jan5.set_index("symbol")
    assert by_symbol.loc["920001.BJ", "listing_board_id"] == 4
    assert by_symbol.loc["920001.BJ", "size_tier"] == 0
    include_manifest = json.loads((tmp_path / "include_bse" / "manifest.json").read_text(encoding="utf-8"))
    assert include_manifest["stock_universe"]["include_bse"] is True
    assert include_manifest["stock_universe"]["excluded_board_codes"] == []


def build_generated_data_dir(root: Path) -> Path:
    build_generated_ashare_daily_metrics(root / "ashare_daily_metrics")
    build_generated_index_dataset(
        root / "csi300",
        dataset="csi300",
        index_code="000300.SH",
        members_by_date={
            "2026-01-05": ["000001.SZ", "000002.SZ"],
            "2026-01-06": ["000001.SZ", "000002.SZ"],
        },
    )
    build_generated_index_dataset(
        root / "csi500",
        dataset="csi500",
        index_code="000905.SH",
        members_by_date={
            "2026-01-05": ["000003.SZ"],
            "2026-01-06": ["000003.SZ"],
        },
    )
    build_generated_index_dataset(
        root / "csi1000",
        dataset="csi1000",
        index_code="000852.SH",
        members_by_date={
            "2026-01-05": ["300001.SZ"],
            "2026-01-06": ["300001.SZ"],
        },
    )
    build_generated_index_dataset(
        root / "csi2000",
        dataset="csi2000",
        index_code="932000.CSI",
        members_by_date={
            "2026-01-05": ["688001.SH"],
            "2026-01-06": ["688001.SH"],
        },
    )
    build_static_industry_reference(root / "industry_sw_current_reference")
    build_static_listing_board_reference(root / "listing_board_current_reference")
    return root


def build_generated_ashare_daily_metrics(root: Path) -> None:
    rows = {
        "2026-01-02": [
            ("000001.SZ", "100"),
            ("000002.SZ", "10000"),
        ],
        "2026-01-05": [
            ("000001.SZ", "100"),
            ("000002.SZ", "10000"),
            ("000003.SZ", ""),
        ],
        "2026-01-06": [
            ("000001.SZ", "121"),
            ("000002.SZ", "10000"),
            ("000003.SZ", "1000"),
        ],
    }
    index_rows = []
    for date_text, members in rows.items():
        month = date_text[:7]
        relative = f"daily_metrics/{month}/{date_text}.csv"
        body = "symbol,trade_date,total_market_cap\n" + "".join(
            f"{symbol},{date_text},{market_cap}\n" for symbol, market_cap in members
        )
        write_csv(root / relative, body)
        index_rows.append(
            f"{date_text},{relative},{len(members)},{len(members)},0,/generated/{date_text}.csv,generated_daily_file,hash,pass\n"
        )
    write_csv(
        root / "daily_metrics.csv",
        "date,file_path,rows,unique_symbols,duplicate_key_rows,source_path,source_kind,columns_hash,quality_status\n"
        + "".join(index_rows),
    )
    write_json(
        root / "manifest.json",
        {
            "dataset": "ashare_daily_metrics",
            "column_mode": "standard_english",
            "date_range": {"start": "2026-01-02", "end": "2026-01-06"},
        },
    )


def build_generated_index_dataset(
    root: Path,
    *,
    dataset: str,
    index_code: str,
    members_by_date: dict[str, list[str]],
) -> None:
    index_rows = []
    for date_text, members in members_by_date.items():
        relative = f"constituent_weights_daily_asof/{date_text}.csv"
        weight = 100 / len(members)
        body = (
            "date,index_code,member_symbol,weight,weight_unit,weight_snapshot_date,"
            "effective_date,days_since_snapshot,quality_status\n"
        )
        body += "".join(
            f"{date_text},{index_code},{symbol},{weight},%,2026-01-02,2026-01-05,3,complete\n"
            for symbol in members
        )
        write_csv(root / relative, body)
        index_rows.append(
            f"{date_text},{relative},{len(members)},{index_code},2026-01-02,2026-01-05,3,complete,100.0,0,{len(members)}\n"
        )
    write_csv(
        root / "constituent_weights_daily_asof.csv",
        "date,file_path,rows,index_code,weight_snapshot_date,effective_date,days_since_snapshot,"
        "quality_status,weight_sum,duplicate_member_rows,member_count\n"
        + "".join(index_rows),
    )
    write_json(
        root / "manifest.json",
        {
            "dataset": dataset,
            "index_code": index_code,
            "point_in_time": {
                "daily_asof_generated": True,
                "asof_policy": "next_trading_day",
            },
        },
    )


def build_static_industry_reference(root: Path) -> Path:
    write_csv(
        root / "current_snapshot.csv",
        (
            "stock_code,stock_name,industry_standard,industry_level1_code,industry_level1,"
            "industry_level2_code,industry_level2,industry_level3_code,industry_level3,"
            "effective_date,classification_snapshot_date,classification_mode,source_file,quality_status\n"
            "000001.SZ,平安银行,SW2021,801010.SI,银行,801011.SI,银行II,801012.SI,银行III,"
            "2020-01-01,2026-06-03,static_current_reference,/snapshot.csv,complete\n"
            "000002.SZ,万科A,SW2021,801020.SI,地产,801021.SI,地产II,801022.SI,地产III,"
            "2020-01-01,2026-06-03,static_current_reference,/snapshot.csv,complete\n"
            "000003.SZ,测试股,SW2021,801030.SI,制造,801031.SI,制造II,801032.SI,制造III,"
            "2020-01-01,2026-06-03,static_current_reference,/snapshot.csv,complete\n"
        ),
    )
    write_json(
        root / "manifest.json",
        {
            "dataset": "industry_sw_current_reference",
            "industry_standard": "SW2021",
            "classification_snapshot_date": "2026-06-03",
            "classification_mode": "static_current_reference",
            "historical_pit_industry": False,
        },
    )
    return root


def build_static_listing_board_reference(root: Path) -> Path:
    write_csv(
        root / "current_snapshot.csv",
        (
            "stock_code,stock_name,dimension_standard,listing_board_code,listing_board,board_order,"
            "exchange_code,exchange_suffix,listing_status,list_date,delist_date,source_list,"
            "raw_region,raw_industry,reference_mode,source_file,quality_status\n"
            "000001.SZ,平安银行,A_SHARE_LISTING_BOARD,MAIN,主板,1,SZSE,SZ,上市,1991-04-03,,listed,"
            "深圳,银行,static_current_reference,股票列表.csv,complete\n"
            "000002.SZ,万科A,A_SHARE_LISTING_BOARD,MAIN,主板,1,SZSE,SZ,上市,1991-01-29,,listed,"
            "深圳,房地产,static_current_reference,股票列表.csv,complete\n"
            "000003.SZ,测试股,A_SHARE_LISTING_BOARD,MAIN,主板,1,SZSE,SZ,上市,1991-01-29,,listed,"
            "深圳,制造,static_current_reference,股票列表.csv,complete\n"
            "300001.SZ,创业样本,A_SHARE_LISTING_BOARD,CHINEXT,创业板,2,SZSE,SZ,上市,2009-10-30,,listed,"
            "深圳,制造,static_current_reference,股票列表.csv,complete\n"
            "688001.SH,科创样本,A_SHARE_LISTING_BOARD,STAR,科创板,3,SSE,SH,上市,2019-07-22,,listed,"
            "上海,制造,static_current_reference,股票列表.csv,complete\n"
            "920001.BJ,北交样本,A_SHARE_LISTING_BOARD,BSE,北交所,4,BSE,BJ,上市,2021-11-15,,listed,"
            "北京,制造,static_current_reference,股票列表.csv,complete\n"
        ),
    )
    write_json(
        root / "manifest.json",
        {
            "dataset": "listing_board_current_reference",
            "dimension_standard": "A_SHARE_LISTING_BOARD",
            "reference_mode": "static_current_reference",
            "historical_pit_listing_board": False,
            "row_counts": {"current_snapshot": 6},
        },
    )
    return root


def append_bse_daily_metric_rows(data_dir: Path) -> None:
    ashare_root = data_dir / "ashare_daily_metrics"
    for date_text, cap in (("2026-01-05", "500"), ("2026-01-06", "600")):
        path = ashare_root / "daily_metrics" / "2026-01" / f"{date_text}.csv"
        with path.open("a", encoding="utf-8-sig") as handle:
            handle.write(f"920001.BJ,{date_text},{cap}\n")
    index = pd.read_csv(ashare_root / "daily_metrics.csv")
    index.loc[index["date"].isin(["2026-01-05", "2026-01-06"]), ["rows", "unique_symbols"]] = 4
    index.to_csv(ashare_root / "daily_metrics.csv", index=False)


def append_bse_industry_reference(root: Path) -> None:
    path = root / "current_snapshot.csv"
    with path.open("a", encoding="utf-8-sig") as handle:
        handle.write(
            "920001.BJ,北交样本,SW2021,801030.SI,制造,801031.SI,制造II,801032.SI,制造III,"
            "2020-01-01,2026-06-03,static_current_reference,/snapshot.csv,complete\n"
        )
