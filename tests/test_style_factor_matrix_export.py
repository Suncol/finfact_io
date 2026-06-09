from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from finfact_io.exports.style_factor_matrix import (
    StyleIndexMembershipSpec,
    build_style_factor_matrix_dataset,
)


def write_csv(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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
    write_csv(
        root / "industry_matrix_edges.csv",
        (
            "stock_code,stock_name,industry_standard,industry_level,industry_code,industry_name,"
            "membership,classification_snapshot_date,classification_mode\n"
            "000001.SZ,平安银行,SW2021,L1,801010.SI,银行,1,2026-06-03,static_current_reference\n"
            "000002.SZ,万科A,SW2021,L1,801020.SI,地产,1,2026-06-03,static_current_reference\n"
            "000003.SZ,测试股,SW2021,L1,801030.SI,制造,1,2026-06-03,static_current_reference\n"
        ),
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": "industry_sw_current_reference",
                "industry_standard": "SW2021",
                "classification_snapshot_date": "2026-06-03",
                "classification_mode": "static_current_reference",
                "historical_pit_industry": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def test_build_style_factor_matrix_uses_intersected_start_asof_members_and_cap_transforms(tmp_path: Path) -> None:
    data_dir = build_generated_data_dir(tmp_path / "data")
    output_dir = tmp_path / "style_matrix"

    report = build_style_factor_matrix_dataset(
        data_dir=data_dir,
        output_dir=output_dir,
        index_specs=(
            StyleIndexMembershipSpec("csi300", "csi300", "000300.SH", expected_member_count=2),
            StyleIndexMembershipSpec("csi500", "csi500", "000905.SH", expected_member_count=2),
            StyleIndexMembershipSpec("csi1000", "csi1000", "000852.SH", expected_member_count=1),
            StyleIndexMembershipSpec("csi2000", "csi2000", "932000.CSI", expected_member_count=2),
        ),
    )

    assert report.date_range == ("2026-01-05", "2026-01-06")
    assert report.row_counts["style_factor_rows"] == 6

    index = pd.read_csv(output_dir / "style_factor_matrix.csv")
    assert list(index["date"]) == ["2026-01-05", "2026-01-06"]
    assert list(index["rows"]) == [3, 3]

    jan5 = pd.read_csv(output_dir / "style_factor_matrix" / "2026-01" / "2026-01-05.csv")
    assert set(jan5.columns).issuperset(
        {
            "trade_date",
            "symbol",
            "industry_code",
            "industry_name",
            "industry_classification_snapshot_date",
            "industry_classification_mode",
            "industry_sw_l1_801010_SI",
            "industry_sw_l1_801020_SI",
            "industry_sw_l1_801030_SI",
            "in_csi300",
            "in_csi500",
            "in_csi1000",
            "in_csi2000",
            "total_market_cap_10k_yuan",
            "total_market_cap_rank",
            "total_market_cap_rank_pct",
            "total_market_cap_log10",
        }
    )
    by_symbol = jan5.set_index("symbol")
    assert by_symbol.loc["000001.SZ", "in_csi300"] == 1
    assert by_symbol.loc["000001.SZ", "in_csi500"] == 0
    assert by_symbol.loc["000001.SZ", "in_csi2000"] == 1
    assert by_symbol.loc["000002.SZ", "in_csi300"] == 1
    assert by_symbol.loc["000002.SZ", "in_csi500"] == 1
    assert by_symbol.loc["000003.SZ", "in_csi1000"] == 1
    assert by_symbol.loc["000001.SZ", "industry_sw_l1_801010_SI"] == 1
    assert by_symbol.loc["000003.SZ", "industry_sw_l1_801030_SI"] == 1
    assert set(jan5["industry_classification_snapshot_date"]) == {"2026-06-03"}
    assert set(jan5["industry_classification_mode"]) == {"static_current_reference"}
    assert by_symbol.loc["000001.SZ", "total_market_cap_rank"] == 1
    assert by_symbol.loc["000002.SZ", "total_market_cap_rank"] == 2
    assert pd.isna(by_symbol.loc["000003.SZ", "total_market_cap_rank"])
    assert by_symbol.loc["000001.SZ", "total_market_cap_log10"] == 2
    assert by_symbol.loc["000002.SZ", "total_market_cap_log10"] == 4

    schema = pd.read_csv(output_dir / "schema.csv")
    assert schema.set_index("column").loc["total_market_cap_10k_yuan", "unit"] == "万元"
    assert schema.set_index("column").loc["in_csi300", "role"] == "index_membership_dummy"

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["date_range"] == {"start": "2026-01-05", "end": "2026-01-06"}
    assert manifest["data_dir"] == str(data_dir)
    assert "ashare_daily_root" not in manifest
    assert "index_data_root" not in manifest
    assert manifest["availability"]["index_membership"]["csi2000"]["first_usable_date"] == "2026-01-05"
    assert manifest["availability"]["index_membership"]["csi300"]["dataset"] == "csi300"
    assert manifest["industry_reference"]["historical_pit_industry"] is False
    assert manifest["industry_reference"]["classification_snapshot_date"] == "2026-06-03"


def test_build_style_factor_matrix_raises_when_date_intersection_is_empty(tmp_path: Path) -> None:
    data_dir = build_generated_data_dir(tmp_path / "data")

    try:
        build_style_factor_matrix_dataset(
            data_dir=data_dir,
            output_dir=tmp_path / "out",
            start="2026-01-02",
            end="2026-01-02",
            index_specs=(
                StyleIndexMembershipSpec("csi300", "csi300", "000300.SH", expected_member_count=2),
                StyleIndexMembershipSpec("csi500", "csi500", "000905.SH", expected_member_count=2),
                StyleIndexMembershipSpec("csi1000", "csi1000", "000852.SH", expected_member_count=1),
                StyleIndexMembershipSpec("csi2000", "csi2000", "932000.CSI", expected_member_count=2),
            ),
        )
    except Exception as exc:
        assert "No style factor matrix dates" in str(exc)
    else:
        raise AssertionError("Expected an empty date intersection error")


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
            "2026-01-05": ["000002.SZ", "000003.SZ"],
            "2026-01-06": ["000002.SZ", "000003.SZ"],
        },
    )
    build_generated_index_dataset(
        root / "csi1000",
        dataset="csi1000",
        index_code="000852.SH",
        members_by_date={
            "2026-01-05": ["000003.SZ"],
            "2026-01-06": ["000003.SZ"],
        },
    )
    build_generated_index_dataset(
        root / "csi2000",
        dataset="csi2000",
        index_code="932000.CSI",
        members_by_date={
            "2026-01-05": ["000001.SZ", "000003.SZ"],
            "2026-01-06": ["000001.SZ", "000003.SZ"],
        },
    )
    build_static_industry_reference(root / "industry_sw_current_reference")
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
            f"{date_text},{relative},{len(members)},{index_code},2026-01-02,2026-01-05,3,complete,100.0,0\n"
        )
    write_csv(
        root / "constituent_weights_daily_asof.csv",
        "date,file_path,rows,index_code,weight_snapshot_date,effective_date,days_since_snapshot,"
        "quality_status,weight_sum,duplicate_member_rows\n"
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
