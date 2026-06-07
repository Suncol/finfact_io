from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from finfact_io import FinfactStore
from finfact_io.exports.ashare_daily_metrics import build_ashare_daily_metrics_dataset


DAILY_HEADER = (
    "股票代码,交易日期,开盘价,最高价,最低价,收盘价,昨收价,涨跌额,涨跌幅,"
    "成交量(手),成交额(千元),换手率,换手率(自由流通股),量比,市盈率,"
    "市盈率TTM,市净率,市销率,市销率TTM,股息率,股息率TTM,总股本(万股),"
    "流通股本(万股),自由流通股本(万股),总市值(万元),流通市值(万元)\n"
)


STANDARD_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "previous_close",
    "change",
    "pct_change",
    "volume",
    "amount",
    "turnover_rate",
    "free_float_turnover_rate",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dividend_yield",
    "dividend_yield_ttm",
    "total_share_capital",
    "float_share_capital",
    "free_float_share_capital",
    "total_market_cap",
    "float_market_cap",
]


def write_csv(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def write_zip_csv(path: Path, members: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, text in members.items():
            archive.writestr(member, text.encode("utf-8-sig"))


def build_ashare_daily_metrics_root(root: Path) -> Path:
    write_csv(
        root / "股票列表.csv",
        (
            "TS代码,股票代码,股票名称,地域,所属行业,股票全称,英文全称,拼音缩写,"
            "市场类型,交易所代码,交易货币,上市状态,上市日期,退市日期,沪深港通标的,"
            "实控人名称,实控人企业性质\n"
            "000001.SZ,000001,平安银行,深圳,银行,平安银行股份有限公司,"
            "Ping An Bank,PAYH,主板,SZSE,CNY,上市,19910403,,是,,\n"
            "000002.SZ,000002,万科A,深圳,房地产,万科企业股份有限公司,"
            "Vanke,VANKE,主板,SZSE,CNY,上市,19910129,,是,,\n"
        ),
    )
    write_csv(
        root / "退市股票列表.csv",
        (
            "TS代码,股票代码,股票名称,地域,所属行业,股票全称,英文全称,拼音缩写,"
            "市场类型,交易所代码,交易货币,上市状态,上市日期,退市日期,沪深港通标的,"
            "实控人名称,实控人企业性质\n"
        ),
    )
    write_csv(
        root / "交易日历.csv",
        (
            "交易所,日期,是否交易,上一个交易日\n"
            "SSE,2024-01-02,交易,2023-12-29\n"
            "SSE,2024-01-03,交易,2024-01-02\n"
            "SSE,2024-01-04,休市,2024-01-03\n"
        ),
    )
    write_csv(
        root / "增量数据" / "每日指标" / "2024-01" / "20240102.csv",
        DAILY_HEADER
        + "000001.SZ,20240102,10,11,9,10.5,10,0.5,5,100,200,1,2,,,"
        "12.3,1.1,2,2.1,,,1000,800,700,100000,80000\n"
        + "000002.SZ,20240102,20,21,19,20.5,20,0.5,2.5,300,400,3,4,1.2,"
        "8,9,1.3,2.2,2.3,0.5,0.6,2000,1800,1700,200000,180000\n",
    )
    write_csv(
        root / "增量数据" / "每日指标" / "2024-01" / "20240103.csv",
        DAILY_HEADER
        + "000001.SZ,20240103,10.5,12,10,11,10.5,0.5,4.76,110,210,1.1,"
        "2.1,1.2,8,13,1.2,2.2,2.3,,,1000,800,700,110000,88000\n",
    )
    write_csv(
        root / "增量数据" / "每日指标" / "2024-01" / "20240104.csv",
        DAILY_HEADER
        + "000001.SZ,20240104,11,12,10,11.5,11,0.5,4.55,120,220,1.2,"
        "2.2,1.3,8,13,1.2,2.2,2.3,,,1000,800,700,115000,92000\n",
    )
    write_zip_csv(
        root / "每日指标.zip",
        {
            "000001.SZ.csv": DAILY_HEADER
            + "000001.SZ,20240102,10,11,9,10.5,10,0.5,5,100,200,1,2,,,"
            "12.3,1.1,2,2.1,,,1000,800,700,100000,80000\n",
        },
    )
    return root


def test_build_ashare_daily_metrics_dataset_writes_standard_daily_files(tmp_path: Path) -> None:
    source_root = build_ashare_daily_metrics_root(tmp_path / "source")
    output_dir = tmp_path / "out"

    report = build_ashare_daily_metrics_dataset(
        ashare_daily_dir=source_root,
        output_dir=output_dir,
        start="2024-01-02",
        end="2024-01-04",
    )

    assert report.row_counts["daily_metrics"] == 2
    assert report.row_counts["daily_metric_rows"] == 3
    assert not (output_dir / "daily_metrics" / "2024-01" / "20240102.csv").exists()
    assert not (output_dir / "daily_metrics" / "2024-01" / "2024-01-04.csv").exists()

    jan2 = pd.read_csv(output_dir / "daily_metrics" / "2024-01" / "2024-01-02.csv")
    assert list(jan2.columns) == STANDARD_COLUMNS
    assert list(jan2["symbol"]) == ["000001.SZ", "000002.SZ"]
    assert set(jan2["trade_date"]) == {"2024-01-02"}
    assert pd.isna(jan2.loc[jan2["symbol"] == "000001.SZ", "pe"].item())
    assert jan2.loc[jan2["symbol"] == "000002.SZ", "amount"].item() == 400

    index = pd.read_csv(output_dir / "daily_metrics.csv")
    assert list(index["date"]) == ["2024-01-02", "2024-01-03"]
    assert list(index["rows"]) == [2, 1]
    assert list(index["duplicate_key_rows"]) == [0, 0]
    assert set(index["quality_status"]) == {"pass"}

    schema = pd.read_csv(output_dir / "schema.csv")
    units = schema.set_index("standard_column")["unit"].to_dict()
    assert units["amount"] == "千元"
    assert units["total_market_cap"] == "万元"
    assert set(schema["standard_column"]) == set(STANDARD_COLUMNS)

    quality = pd.read_csv(output_dir / "data_quality.csv")
    assert set(quality["status"]) == {"pass"}
    quality_by_check = quality.set_index("check")
    assert str(quality_by_check.loc["generated_dates_within_calendar", "observed_value"]) == "0"
    assert str(quality_by_check.loc["non_trading_source_files_excluded", "observed_value"]) == "1"
    assert {
        "daily_file_count",
        "date_range_coverage",
        "generated_dates_within_calendar",
        "non_trading_source_files_excluded",
        "filename_matches_trade_date",
        "columns_match_schema",
        "duplicate_symbol_trade_date",
        "symbol_is_string",
        "sample_zip_reconciliation",
    }.issubset(set(quality["check"]))

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["column_mode"] == "standard_english"
    assert manifest["date_range"] == {"start": "2024-01-02", "end": "2024-01-03"}
    assert manifest["source_policy"]["primary"] == "incremental_daily_files"
    assert manifest["files"]["daily_metrics.csv"]["rows"] == 2


def test_ashare_store_queries_built_daily_metrics_by_date_range_and_symbols(tmp_path: Path) -> None:
    source_root = build_ashare_daily_metrics_root(tmp_path / "source")
    output_dir = tmp_path / "out"
    build_ashare_daily_metrics_dataset(
        ashare_daily_dir=source_root,
        output_dir=output_dir,
        start="2024-01-02",
        end="2024-01-03",
    )
    ashare = FinfactStore(ashare_daily_dir=source_root).ashare

    dates = ashare.available_daily_metric_dates(dataset_dir=output_dir)
    assert list(dates["date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]

    jan2 = ashare.daily_metrics_by_date(
        "2024-01-02",
        symbols=["000002.SZ"],
        dataset_dir=output_dir,
    )
    assert list(jan2["symbol"]) == ["000002.SZ"]
    assert jan2.iloc[0]["trade_date"] == pd.Timestamp("2024-01-02")

    ranged = ashare.daily_metrics_date_range(
        "2024-01-02",
        "2024-01-03",
        symbols=["000001.SZ"],
        dataset_dir=output_dir,
    )
    assert list(ranged["trade_date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert set(ranged["symbol"]) == {"000001.SZ"}
