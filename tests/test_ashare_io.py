from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from finfact_io import FinfactStore
from finfact_io.errors import (
    CsvEncodingError,
    CsvEncodingWarning,
    SchemaError,
    ZipMemberNotFoundError,
)
from finfact_io.readers.csv import read_csv_file


def write_csv(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def write_zip_csv(path: Path, members: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, text in members.items():
            archive.writestr(member, text.encode("utf-8-sig"))


def csv_row(values: list[object]) -> str:
    return ",".join("" if value is None else str(value) for value in values) + "\n"


def build_ashare_root(root: Path) -> Path:
    write_csv(
        root / "股票列表.csv",
        (
            "TS代码,股票代码,股票名称,地域,所属行业,股票全称,英文全称,拼音缩写,"
            "市场类型,交易所代码,交易货币,上市状态,上市日期,退市日期,沪深港通标的,"
            "实控人名称,实控人企业性质\n"
            "000001.SZ,000001,平安银行,深圳,银行,平安银行股份有限公司,"
            "Ping An Bank,PAYH,主板,SZSE,CNY,上市,19910403,,是,,\n"
        ),
    )
    write_csv(
        root / "退市股票列表.csv",
        (
            "TS代码,股票代码,股票名称,地域,所属行业,股票全称,英文全称,拼音缩写,"
            "市场类型,交易所代码,交易货币,上市状态,上市日期,退市日期,沪深港通标的,"
            "实控人名称,实控人企业性质\n"
            "000003.SZ,000003,PT金田A(退),,,,,,,SZSE,CNY,退市,19910703,20020614,,,\n"
        ),
    )
    write_csv(
        root / "交易日历.csv",
        (
            "交易所,日期,是否交易,上一个交易日\n"
            "SSE,2024-01-01,休市,2023-12-29\n"
            "SSE,2024-01-02,交易,2023-12-29\n"
            "SZSE,2024-01-02,交易,2023-12-29\n"
        ),
    )
    daily_header = (
        "股票代码,交易日期,开盘价,最高价,最低价,收盘价,昨收价,涨跌额,涨跌幅,"
        "成交量(手),成交额(千元),换手率,换手率(自由流通股),量比,市盈率,"
        "市盈率TTM,市净率,市销率,市销率TTM,股息率,股息率TTM,总股本(万股),"
        "流通股本(万股),自由流通股本(万股),总市值(万元),流通市值(万元)\n"
    )
    write_zip_csv(
        root / "每日指标.zip",
        {
            "000001.SZ.csv": daily_header
            + (
                "000001.SZ,20240102,10,11,9,10.5,10,0.5,5,100,200,1,2,,,"
                "12.3,1.1,2,2.1,,,1000,800,700,100000,80000\n"
                "000001.SZ,2024-01-03,10.5,12,10,11,10.5,0.5,4.76,110,210,1.1,"
                "2.1,1.2,8,13,1.2,2.2,2.3,,,1000,800,700,110000,88000\n"
            ),
            "000002.SZ.csv": daily_header
            + "000002.SZ,20240102,1,1,1,1,1,0,0,1,1,,,,,,,,,,,,,,,\n",
        },
    )
    factor_header = (
        "股票代码,交易日期,开盘价,最高价,最低价,收盘价,成交量(手),成交额(千元),"
        "涨跌幅(%),换手率(%),量比,复权因子,MA5,MA10,MA20,MA60,EMA5,EMA10,"
        "EMA20,EMA60,MACD_DIF,MACD_DEA,MACD,RSI6,RSI12,RSI24,KDJ_K,KDJ_D,"
        "KDJ_J,BOLL_UPPER,BOLL_MID,BOLL_LOWER,ATR,OBV,连涨天数,连跌天数,"
        "阶段新高天数,阶段新低天数\n"
    )
    write_zip_csv(
        root / "技术因子_前复权.zip",
        {
            "000001.SZ.csv": factor_header
            + csv_row(
                [
                    "000001.SZ",
                    "20240102",
                    1,
                    2,
                    1,
                    1.5,
                    100,
                    200,
                    5,
                    1,
                    None,
                    0.1,
                    *([None] * 21),
                    100,
                    1,
                    0,
                    1,
                    0,
                ]
            )
        },
    )
    write_zip_csv(
        root / "技术因子_后复权.zip",
        {
            "000001.SZ.csv": factor_header
            + csv_row(
                [
                    "000001.SZ",
                    "20240102",
                    10,
                    20,
                    10,
                    15,
                    100,
                    200,
                    5,
                    1,
                    None,
                    10,
                    *([None] * 21),
                    100,
                    1,
                    0,
                    1,
                    0,
                ]
            )
        },
    )
    write_csv(root / "增量数据" / "每日指标" / "2024-01" / "broken.csv", "not,a,real,dataset\n")
    return root


def test_initialize_indexes_archives_without_using_increment_dir(tmp_path: Path) -> None:
    root = build_ashare_root(tmp_path)
    report = FinfactStore(ashare_daily_dir=root).ashare.initialize()

    assert report.archive_mode == "lazy"
    assert report.required_files["每日指标.zip"] is True
    assert report.zip_archives["daily_metrics"].member_count == 2
    assert report.zip_archives["technical_factors_qfq"].member_count == 1
    assert "增量数据" not in str(report)


def test_stock_lists_and_calendar_keep_codes_and_filter_dates(tmp_path: Path) -> None:
    root = build_ashare_root(tmp_path)
    ashare = FinfactStore(ashare_daily_dir=root).ashare

    stocks = ashare.stocks(include_delisted=True, columns="standard")
    calendar = ashare.trading_calendar(
        exchange="SSE",
        start="2024-01-02",
        end="2024-01-02",
        is_open=True,
    )

    assert stocks.loc[0, "symbol"] == "000001.SZ"
    assert stocks.loc[0, "stock_code"] == "000001"
    assert list(stocks["status"]) == ["上市", "退市"]
    assert len(calendar) == 1
    assert calendar.iloc[0]["交易所"] == "SSE"
    assert calendar.iloc[0]["日期"] == pd.Timestamp("2024-01-02")


def test_daily_metrics_reads_zip_member_filters_dates_and_preserves_missing_values(
    tmp_path: Path,
) -> None:
    root = build_ashare_root(tmp_path)
    df = FinfactStore(ashare_daily_dir=root).ashare.daily_metrics(
        "000001.SZ",
        start="2024-01-02",
        end="2024-01-02",
        include_source=True,
    )

    assert len(df) == 1
    assert df.iloc[0]["股票代码"] == "000001.SZ"
    assert df.iloc[0]["交易日期"] == pd.Timestamp("2024-01-02")
    assert pd.isna(df.iloc[0]["市盈率"])
    assert df.iloc[0]["_source_kind"] == "zip"
    assert df.iloc[0]["_source_member"] == "000001.SZ.csv"


def test_technical_factors_selects_adjustment_and_standardizes_columns(tmp_path: Path) -> None:
    root = build_ashare_root(tmp_path)
    ashare = FinfactStore(ashare_daily_dir=root).ashare

    qfq = ashare.technical_factors("000001.SZ", adjustment="qfq", columns="standard")
    hfq = ashare.technical_factors("000001.SZ", adjustment="hfq", columns="standard")

    assert qfq.iloc[0]["adjustment"] == "qfq"
    assert hfq.iloc[0]["adjustment"] == "hfq"
    assert qfq.iloc[0]["close"] == 1.5
    assert hfq.iloc[0]["close"] == 15
    assert qfq.attrs["field_units"]["amount"] == "千元"
    assert qfq.attrs["field_units"]["volume"] == "手"


def test_gb18030_fallback_emits_warning(tmp_path: Path) -> None:
    path = tmp_path / "gb.csv"
    write_csv(path, "股票代码,股票名称\n000001.SZ,平安银行\n", encoding="gb18030")

    with pytest.warns(CsvEncodingWarning):
        df = read_csv_file(path)

    assert df.iloc[0]["股票名称"] == "平安银行"


def test_encoding_failure_raises_diagnostic_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(CsvEncodingError, match="bad.csv"):
        read_csv_file(path, encodings=("utf-8-sig",))


def test_missing_zip_member_error_includes_symbol(tmp_path: Path) -> None:
    root = build_ashare_root(tmp_path)

    with pytest.raises(ZipMemberNotFoundError, match="999999.SZ"):
        FinfactStore(ashare_daily_dir=root).ashare.daily_metrics("999999.SZ")


def test_missing_required_columns_raise_schema_error(tmp_path: Path) -> None:
    root = build_ashare_root(tmp_path)
    write_zip_csv(root / "每日指标.zip", {"000001.SZ.csv": "股票代码,收盘价\n000001.SZ,10\n"})

    with pytest.raises(SchemaError, match="交易日期"):
        FinfactStore(ashare_daily_dir=root).ashare.daily_metrics("000001.SZ")
