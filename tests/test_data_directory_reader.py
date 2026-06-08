from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from finfact_io.data_directory import DataDirectoryReader
from finfact_io.errors import DataFileNotFoundError, DataRootNotFoundError


def write_csv(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_generated_data_root(root: Path) -> Path:
    ashare = root / "ashare_daily_metrics"
    write_json(
        ashare / "manifest.json",
        {"dataset": "ashare_daily_metrics", "date_range": {"start": "2024-01-02", "end": "2024-01-03"}},
    )
    write_csv(
        ashare / "data_quality.csv",
        "dataset,check,status,severity,observed_value,detail\nashare_daily_metrics,row_count,pass,info,3,ok\n",
    )
    write_csv(
        ashare / "schema.csv",
        "raw_column,standard_column,unit,dtype,nullable,description\n股票代码,symbol,,string,True,code\n",
    )
    write_csv(
        ashare / "daily_metrics.csv",
        (
            "date,file_path,rows,unique_symbols,duplicate_key_rows,source_path,source_kind,columns_hash,quality_status\n"
            "2024-01-02,daily_metrics/2024-01/2024-01-02.csv,2,2,0,source,incremental,abc,pass\n"
            "2024-01-03,daily_metrics/2024-01/2024-01-03.csv,1,1,0,source,incremental,abc,pass\n"
        ),
    )
    write_csv(
        ashare / "daily_metrics" / "2024-01" / "2024-01-02.csv",
        (
            "symbol,trade_date,open,close,amount\n"
            "000001.SZ,2024-01-02,10,11,100\n"
            "688001.SH,2024-01-02,20,21,200\n"
        ),
    )
    write_csv(
        ashare / "daily_metrics" / "2024-01" / "2024-01-03.csv",
        "symbol,trade_date,open,close,amount\n000001.SZ,2024-01-03,11,12,150\n",
    )

    csi = root / "csi1000"
    write_json(csi / "manifest.json", {"dataset": "csi1000", "index_code": "000852.SH"})
    write_csv(
        csi / "data_quality.csv",
        "dataset,check,status,severity,affected_date,observed_value,detail\ncsi1000,row_count,pass,info,,2,ok\n",
    )
    write_csv(
        csi / "index_daily.csv",
        (
            "date,index_code,index_name,open,high,low,close,previous_close,return,return_pct,total_return,total_return_available,volume,volume_unit,amount,amount_unit,source_kind,source_path,source_member\n"
            "2024-01-02,000852.SH,中证1000,100,101,99,101,100,0.01,1,,False,10,手,20,千元,zip,path,member\n"
            "2024-01-03,000852.SH,中证1000,101,102,100,102,101,0.0099,0.99,,False,11,手,22,千元,zip,path,member\n"
        ),
    )
    write_csv(
        csi / "constituent_weights_snapshots.csv",
        (
            "date,file_path,rows,index_code,snapshot_date,provider,quality_status,member_count,weight_sum,duplicate_member_rows\n"
            "2023-12-29,constituent_weights_snapshots/2023-12-29.csv,2,000852.SH,2023-12-29,sse,complete,2,100,0\n"
        ),
    )
    write_csv(
        csi / "constituent_weights_snapshots" / "2023-12-29.csv",
        (
            "date,index_code,member_symbol,weight,weight_unit,snapshot_date,provider,quality_status,member_count,weight_sum,source_path,source_member\n"
            "2023-12-29,000852.SH,000001.SZ,60,%,2023-12-29,sse,complete,2,100,path,member\n"
            "2023-12-29,000852.SH,688001.SH,40,%,2023-12-29,sse,complete,2,100,path,member\n"
        ),
    )
    write_csv(
        csi / "constituent_weights_daily_asof.csv",
        (
            "date,file_path,rows,index_code,weight_snapshot_date,effective_date,days_since_snapshot,quality_status,weight_sum,duplicate_member_rows\n"
            "2024-01-02,constituent_weights_daily_asof/2024-01-02.csv,2,000852.SH,2023-12-29,2024-01-02,4,complete,100,0\n"
            "2024-01-03,constituent_weights_daily_asof/2024-01-03.csv,1,000852.SH,2023-12-29,2024-01-02,5,incomplete,60,0\n"
        ),
    )
    write_csv(
        csi / "constituent_weights_daily_asof" / "2024-01-02.csv",
        (
            "date,index_code,member_symbol,weight,weight_unit,weight_snapshot_date,effective_date,days_since_snapshot,quality_status\n"
            "2024-01-02,000852.SH,000001.SZ,60,%,2023-12-29,2024-01-02,4,complete\n"
            "2024-01-02,000852.SH,688001.SH,40,%,2023-12-29,2024-01-02,4,complete\n"
        ),
    )
    write_csv(
        csi / "constituent_weights_daily_asof" / "2024-01-03.csv",
        "date,index_code,member_symbol,weight,weight_unit,weight_snapshot_date,effective_date,days_since_snapshot,quality_status\n2024-01-03,000852.SH,000001.SZ,60,%,2023-12-29,2024-01-02,5,incomplete\n",
    )

    csi300 = root / "csi300"
    write_json(csi300 / "manifest.json", {"dataset": "csi300", "index_code": "000300.SH"})
    write_csv(
        csi300 / "data_quality.csv",
        "dataset,check,status,severity,affected_date,observed_value,detail\ncsi300,row_count,pass,info,,2,ok\n",
    )
    write_csv(
        csi300 / "index_daily.csv",
        (
            "date,index_code,index_name,open,high,low,close,previous_close,return,return_pct,total_return,total_return_available,volume,volume_unit,amount,amount_unit,source_kind,source_path,source_member\n"
            "2024-01-02,000300.SH,沪深300,100,101,99,101,100,0.01,1,1001,True,10,手,20,千元,zip,path,member\n"
            "2024-01-03,000300.SH,沪深300,101,102,100,102,101,0.0099,0.99,1010,True,11,手,22,千元,zip,path,member\n"
        ),
    )
    write_csv(
        csi300 / "constituent_weights_snapshots.csv",
        (
            "date,file_path,rows,index_code,snapshot_date,provider,quality_status,member_count,weight_sum,duplicate_member_rows\n"
            "2023-12-29,constituent_weights_snapshots/2023-12-29.csv,2,000300.SH,2023-12-29,sse,complete,300,100,0\n"
        ),
    )
    write_csv(
        csi300 / "constituent_weights_snapshots" / "2023-12-29.csv",
        (
            "date,index_code,member_symbol,weight,weight_unit,snapshot_date,provider,quality_status,member_count,weight_sum,source_path,source_member\n"
            "2023-12-29,000300.SH,000001.SZ,55,%,2023-12-29,sse,complete,300,100,path,member\n"
            "2023-12-29,000300.SH,688001.SH,45,%,2023-12-29,sse,complete,300,100,path,member\n"
        ),
    )
    write_csv(
        csi300 / "constituent_weights_daily_asof.csv",
        (
            "date,file_path,rows,index_code,weight_snapshot_date,effective_date,days_since_snapshot,quality_status,weight_sum,duplicate_member_rows\n"
            "2024-01-02,constituent_weights_daily_asof/2024-01-02.csv,2,000300.SH,2023-12-29,2024-01-02,4,complete,100,0\n"
            "2024-01-03,constituent_weights_daily_asof/2024-01-03.csv,2,000300.SH,2023-12-29,2024-01-02,5,complete,100,0\n"
        ),
    )
    write_csv(
        csi300 / "constituent_weights_daily_asof" / "2024-01-02.csv",
        (
            "date,index_code,member_symbol,weight,weight_unit,weight_snapshot_date,effective_date,days_since_snapshot,quality_status\n"
            "2024-01-02,000300.SH,000001.SZ,55,%,2023-12-29,2024-01-02,4,complete\n"
            "2024-01-02,000300.SH,688001.SH,45,%,2023-12-29,2024-01-02,4,complete\n"
        ),
    )
    write_csv(
        csi300 / "constituent_weights_daily_asof" / "2024-01-03.csv",
        (
            "date,index_code,member_symbol,weight,weight_unit,weight_snapshot_date,effective_date,days_since_snapshot,quality_status\n"
            "2024-01-03,000300.SH,000001.SZ,55,%,2023-12-29,2024-01-02,5,complete\n"
            "2024-01-03,000300.SH,688001.SH,45,%,2023-12-29,2024-01-02,5,complete\n"
        ),
    )

    industry = root / "industry_sw_current_reference"
    write_json(industry / "manifest.json", {"dataset": "industry_sw_current_reference", "classification_mode": "static_current_reference"})
    write_csv(
        industry / "data_quality.csv",
        "dataset,check,status,severity,affected_date,observed_value,detail\nindustry,row_count,pass,info,,2,ok\n",
    )
    write_csv(
        industry / "current_snapshot.csv",
        (
            "stock_code,stock_name,industry_standard,industry_level1_code,industry_level1,industry_level2_code,industry_level2,industry_level3_code,industry_level3,effective_date,classification_snapshot_date,classification_mode,source_file,quality_status\n"
            "000001.SZ,平安银行,SW2021,801780.SI,银行,801782.SI,股份制银行Ⅱ,851911.SI,股份制银行Ⅲ,19910403,2026-06-03,static_current_reference,source,complete\n"
            "688001.SH,华兴源创,SW2021,801080.SI,电子,801081.SI,半导体,850811.SI,半导体设备,20190722,2026-06-03,static_current_reference,source,complete\n"
        ),
    )
    write_csv(
        industry / "industry_taxonomy.csv",
        (
            "industry_standard,industry_level,industry_code,industry_name,classification_code,parent_classification_code,publishes_index,classification_source,taxonomy_source_status,source_file\n"
            "SW2021,L1,801780.SI,银行,410000,0,是,SW2021,official,source\n"
            "SW2021,L1,801080.SI,电子,270000,0,是,SW2021,official,source\n"
        ),
    )
    write_csv(
        industry / "industry_matrix_edges.csv",
        (
            "stock_code,stock_name,industry_standard,industry_level,industry_code,industry_name,membership,classification_snapshot_date,classification_mode\n"
            "000001.SZ,平安银行,SW2021,L1,801780.SI,银行,1,2026-06-03,static_current_reference\n"
            "688001.SH,华兴源创,SW2021,L1,801080.SI,电子,1,2026-06-03,static_current_reference\n"
        ),
    )

    board = root / "listing_board_current_reference"
    write_json(board / "manifest.json", {"dataset": "listing_board_current_reference", "reference_mode": "static_current_reference"})
    write_csv(
        board / "data_quality.csv",
        "dataset,check,status,severity,observed_value,detail\nboard,row_count,pass,info,2,ok\n",
    )
    write_csv(
        board / "current_snapshot.csv",
        (
            "stock_code,stock_name,dimension_standard,listing_board_code,listing_board,board_order,exchange_code,exchange_suffix,listing_status,list_date,delist_date,source_list,raw_region,raw_industry,reference_mode,source_file,quality_status\n"
            "000001.SZ,平安银行,A_SHARE_LISTING_BOARD,MAIN,主板,1,SZSE,SZ,上市,1991-04-03,,listed,深圳,银行,static_current_reference,股票列表.csv,complete\n"
            "688001.SH,华兴源创,A_SHARE_LISTING_BOARD,STAR,科创板,3,SSE,SH,上市,2019-07-22,,listed,江苏,专用机械,static_current_reference,股票列表.csv,complete\n"
        ),
    )
    write_csv(
        board / "listing_board_taxonomy.csv",
        (
            "dimension_standard,dimension_level,listing_board_code,listing_board,board_order,valid_exchange_codes,description\n"
            "A_SHARE_LISTING_BOARD,listing_board,MAIN,主板,1,\"SSE,SZSE\",main\n"
            "A_SHARE_LISTING_BOARD,listing_board,STAR,科创板,3,SSE,star\n"
        ),
    )
    write_csv(
        board / "listing_board_matrix_edges.csv",
        (
            "stock_code,stock_name,dimension_standard,dimension_level,dimension_code,dimension_name,membership,reference_mode\n"
            "000001.SZ,平安银行,A_SHARE_LISTING_BOARD,listing_board,MAIN,主板,1,static_current_reference\n"
            "688001.SH,华兴源创,A_SHARE_LISTING_BOARD,listing_board,STAR,科创板,1,static_current_reference\n"
        ),
    )
    write_csv(
        board / "board_counts.csv",
        "scope,listing_board_code,listing_board,board_order,stock_count\nall,MAIN,主板,1,1\nall,STAR,科创板,3,1\nlisted,MAIN,主板,1,1\nlisted,STAR,科创板,3,1\n",
    )
    return root


def test_generic_manifest_quality_and_missing_dataset_errors(tmp_path: Path) -> None:
    data_root = build_generated_data_root(tmp_path / "data")
    reader = DataDirectoryReader(data_root)

    assert reader.dataset_path("ashare_daily_metrics") == data_root / "ashare_daily_metrics"
    assert reader.manifest("ashare_daily_metrics")["dataset"] == "ashare_daily_metrics"
    assert reader.quality("ashare_daily_metrics").iloc[0]["status"] == "pass"

    with pytest.raises(DataRootNotFoundError):
        DataDirectoryReader(tmp_path / "missing").dataset_path("ashare_daily_metrics")
    with pytest.raises(DataFileNotFoundError):
        reader.read_csv("ashare_daily_metrics", "missing.csv")


def test_reads_ashare_daily_metrics_by_date_range_and_symbols(tmp_path: Path) -> None:
    reader = DataDirectoryReader(build_generated_data_root(tmp_path / "data"))

    dates = reader.ashare_daily_dates()
    assert list(dates["date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]

    jan2 = reader.ashare_daily_by_date("2024-01-02", symbols=["688001.SH"])
    assert list(jan2["symbol"]) == ["688001.SH"]
    assert jan2.iloc[0]["trade_date"] == pd.Timestamp("2024-01-02")
    assert jan2.iloc[0]["close"] == 21

    ranged = reader.ashare_daily_range("2024-01-02", "2024-01-03", symbols=["000001.SZ"])
    assert list(ranged["trade_date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert list(ranged["close"]) == [11, 12]
    assert list(reader.ashare_daily_schema()["standard_column"]) == ["symbol"]


def test_reads_csi1000_index_and_partitioned_weights(tmp_path: Path) -> None:
    reader = DataDirectoryReader(build_generated_data_root(tmp_path / "data"))

    index_daily = reader.csi1000_index_daily(start="2024-01-03")
    assert list(index_daily["date"]) == [pd.Timestamp("2024-01-03")]
    assert index_daily.iloc[0]["index_code"] == "000852.SH"

    snapshot_weights = reader.csi1000_weights_by_snapshot("2023-12-29", members=["688001.SH"])
    assert list(snapshot_weights["member_symbol"]) == ["688001.SH"]
    assert snapshot_weights.iloc[0]["weight"] == 40

    asof = reader.csi1000_weights_by_date("2024-01-02")
    assert len(asof) == 2
    ranged = reader.csi1000_weights_range("2024-01-02", "2024-01-03", members=["000001.SZ"])
    assert list(ranged["date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert len(reader.csi1000_daily_asof_dates()) == 2


def test_reads_generic_index_dataset_and_keeps_csi1000_wrappers(tmp_path: Path) -> None:
    reader = DataDirectoryReader(build_generated_data_root(tmp_path / "data"))

    index_daily = reader.index_daily("csi300", start="2024-01-03")
    assert list(index_daily["index_code"]) == ["000300.SH"]
    assert index_daily.iloc[0]["total_return"] == 1010

    snapshots = reader.index_weight_snapshots("csi300")
    assert list(snapshots["date"]) == [pd.Timestamp("2023-12-29")]
    assert snapshots.iloc[0]["member_count"] == 300

    snapshot_weights = reader.index_weights_by_snapshot("csi300", "2023-12-29", members=["688001.SH"])
    assert list(snapshot_weights["member_symbol"]) == ["688001.SH"]
    assert snapshot_weights.iloc[0]["weight"] == 45

    asof_dates = reader.index_daily_asof_dates("csi300")
    assert list(asof_dates["date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]

    asof = reader.index_weights_by_date("csi300", "2024-01-02")
    assert len(asof) == 2
    ranged = reader.index_weights_range("csi300", "2024-01-02", "2024-01-03", members=["000001.SZ"])
    assert list(ranged["date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]

    assert reader.csi1000_index_daily().equals(reader.index_daily("csi1000"))
    assert reader.csi1000_weight_snapshots().equals(reader.index_weight_snapshots("csi1000"))


def test_reads_dimensions_joins_stocks_and_builds_matrices(tmp_path: Path) -> None:
    reader = DataDirectoryReader(build_generated_data_root(tmp_path / "data"))

    industry = reader.sw_industry_snapshot(symbols=["000001.SZ"])
    assert list(industry["industry_level1"]) == ["银行"]
    assert list(reader.sw_industry_taxonomy(level="L1")["industry_code"]) == ["801780.SI", "801080.SI"]

    board = reader.listing_board_snapshot(symbols=["688001.SH"])
    assert list(board["listing_board_code"]) == ["STAR"]
    assert reader.listing_board_counts(scope="all")["stock_count"].sum() == 2

    joined = reader.join_stock_dimensions(["000001.SZ", "688001.SH", "999999.SZ"])
    assert list(joined["stock_code"]) == ["000001.SZ", "688001.SH", "999999.SZ"]
    assert joined.loc[joined["stock_code"] == "000001.SZ", "industry_level1"].item() == "银行"
    assert joined.loc[joined["stock_code"] == "688001.SH", "listing_board_code"].item() == "STAR"
    assert pd.isna(joined.loc[joined["stock_code"] == "999999.SZ", "listing_board_code"].item())

    industry_matrix = reader.sw_industry_matrix(level="L1", stocks=["000001.SZ", "688001.SH", "999999.SZ"])
    assert list(industry_matrix.index) == ["000001.SZ", "688001.SH", "999999.SZ"]
    assert industry_matrix.loc["000001.SZ", "801780.SI"] == 1
    assert industry_matrix.loc["999999.SZ"].sum() == 0

    board_matrix = reader.listing_board_matrix(stocks=["000001.SZ", "688001.SH", "999999.SZ"])
    assert list(board_matrix.columns) == ["MAIN", "STAR"]
    assert board_matrix.loc["688001.SH", "STAR"] == 1
    assert board_matrix.loc["999999.SZ"].sum() == 0
