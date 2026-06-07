from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from finfact_io import FinfactStore


def write_csv(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def write_zip_csv(path: Path, members: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, text in members.items():
            archive.writestr(member, text.encode("utf-8-sig"))


def index_bar_header() -> str:
    return (
        "指数代码,交易日期,收盘点位,开盘点位,最高点位,最低点位,"
        "昨日收盘点,涨跌点,涨跌幅(%),成交量(手),成交额(千元)\n"
    )


def sw_daily_header() -> str:
    return (
        "指数代码,交易日期,行业名称,开盘点位,最高点位,最低点位,收盘点位,"
        "涨跌点位,涨跌幅,成交量(万股),成交额(万元),市盈率,市净率,"
        "流通市值(万元),总市值(万元)\n"
    )


def citic_daily_header() -> str:
    return (
        "指数代码,交易日期,开盘点位,最高点位,最低点位,收盘点位,"
        "昨日收盘点位,涨跌点位,涨跌幅,成交量(万股),成交额(万元)\n"
    )


def market_metrics_header() -> str:
    return (
        "指数代码,交易日期,总市值(元),流通市值(元),总股本(股),流通股本(股),"
        "自由流通股本(股),换手率,换手率(自由流通),市盈率,市盈率TTM,市净率\n"
    )


def build_index_root(root: Path) -> Path:
    basic_header = "指数代码,简称,市场,发布方,指数类别,基期,基点,发布日期\n"
    basic_rows = {
        "MSCI指数": "105653.MI,MSCI俄罗斯,MSCI,MSCI指数,规模指数,19941230,100,19961201\n",
        "上交所指数": "000001.SH,上证指数,SSE,中证指数有限公司,综合指数,19901219,100,19910715\n",
        "中证指数": "000300.SH,沪深300,CSI,中证指数有限公司,规模指数,20041231,1000,20050408\n",
        "中金指数": "100000.CIC,中金综合,CICC,中国国际金融股份有限公司,主题指数,,,20150311\n",
        "其他指数": "SP500-101010.SPI,标普能源,SPI,S&P,行业指数,19991231,1000,20000101\n",
        "深交所指数": "399001.SZ,深证成指,SZSE,深圳证券交易所,规模指数,19940720,1000,19950123\n",
        "申万指数": "801010.SI,农林牧渔,SW,申银万国指数,行业指数,19991230,1000,20000104\n",
    }
    for source, row in basic_rows.items():
        write_csv(root / f"指数基本信息_{source}.csv", basic_header + row)

    write_zip_csv(
        root / "指数日线行情.zip",
        {
            "000300.SH.csv": index_bar_header()
            + "000300.SH,20260101,100,99,101,98,99,1,1.01,1000,2000\n"
            + "000300.SH,20260102,101,100,102,99,100,1,1,1100,2100\n",
            "h00300.CSI.csv": index_bar_header()
            + "H00300.CSI,20260101,88,87,89,86,87,1,1.15,900,1900\n",
        },
    )
    write_zip_csv(
        root / "指数周线行情.zip",
        {"000300.SH.csv": index_bar_header() + "000300.SH,20260102,101,99,102,98,100,1,1,5000,9000\n"},
    )
    write_zip_csv(
        root / "指数月线行情.zip",
        {"000300.SH.csv": index_bar_header() + "000300.SH,20260131,111,99,112,98,100,11,11,9000,19000\n"},
    )

    write_csv(
        root / "大盘指数每日指标" / "沪深300.csv",
        market_metrics_header()
        + "000300.SH,20260101,100000000,80000000,1000000,800000,700000,1,2,10,9,1\n"
        + "000300.SH,20260102,100000001,80000001,1000000,800000,700000,1,2,10,9,1\n",
    )

    write_zip_csv(
        root / "申万行业日线行情.zip",
        {
            "801010.SI.csv": sw_daily_header()
            + "801010.SI,20260101,农林牧渔,10,11,9,10.5,0.5,5,12,34,20,2,5000,9000\n"
            + "801010.SI,20260102,农林牧渔,11,12,10,11.5,1,9,13,35,21,2.1,5100,9100\n"
        },
    )
    write_zip_csv(
        root / "中信行业日线行情.zip",
        {
            "CI005001.CI.csv": citic_daily_header()
            + "CI005001.CI,20260101,20,21,19,20.5,20,0.5,2.5,14,36\n"
        },
    )

    classification_header = "指数代码,行业名称,行业分级,行业代码,是否发布指数,父级代码,分类来源\n"
    write_csv(
        root / "申万行业分类" / "申万行业分类_L1_SW2021.csv",
        classification_header + "801010.SI,农林牧渔,L1,110000,是,0,SW2021\n",
    )
    write_csv(
        root / "申万行业分类" / "申万行业分类_L2_SW2021.csv",
        classification_header + "801011.SI,林业Ⅱ,L2,110100,是,110000,SW2021\n",
    )
    write_csv(
        root / "申万行业分类" / "申万行业分类_L3_SW2021.csv",
        classification_header + "850131.SI,林业Ⅲ,L3,110101,是,110100,SW2021\n",
    )

    citic_class_header = "指数代码,行业名称,行业分级,行业代码,是否发布指数,父级代码\n"
    write_csv(
        root / "中信行业分类" / "中信行业分类_行业层级表.csv",
        citic_class_header
        + "CI005001.CI,石油石化,L1,CI005001.CI,是,0\n"
        + "CI005101.CI,石油开采Ⅱ,L2,CI005101.CI,是,CI005001.CI\n",
    )
    write_csv(
        root / "中信行业分类" / "中信行业分类_成分股_全部_CITIC.csv",
        (
            "一级行业代码,一级行业名称,二级行业代码,二级行业名称,"
            "三级行业代码,三级行业名称,股票代码,股票名称,纳入日期,剔除日期,是否最新\n"
            "CI005001.CI,石油石化,CI005101.CI,石油开采Ⅱ,CI005201.CI,石油开采Ⅲ,600777.SH,*ST新潮,20170301,,Y\n"
            "CI005001.CI,石油石化,CI005101.CI,石油开采Ⅱ,CI005202.CI,油气服务Ⅲ,600777.SH,*ST新潮,20200101,,Y\n"
        ),
    )

    write_csv(
        root / "申万行业成分_每日更新" / "2026-01" / "申万行业成分_20260102.csv",
        (
            "一级行业代码,一级行业名称,二级行业代码,二级行业名称,"
            "三级行业代码,三级行业名称,股票代码,股票名称,纳入日期,剔除日期\n"
            "801010.SI,农林牧渔,801011.SI,林业Ⅱ,850131.SI,林业Ⅲ,000592.SZ,平潭发展,20091009,\n"
        ),
    )

    write_zip_csv(
        root / "上交所指数成分" / "上交所指数成分_20251231.zip",
        {"000001.SH.csv": "指数代码,成分股票代码,交易日期,权重\n000001.SH,601288.SH,20251231,3.3\n"},
    )
    write_zip_csv(
        root / "中证指数成分" / "中证指数成分_20260131.zip",
        {"000300.SH.csv": "指数代码,成分股票代码,交易日期,权重\n000300.SH,600519.SH,20260131,5.5\n"},
    )

    write_csv(
        root / "增量数据" / "指数日线行情" / "2026-01" / "20260102_指数日线行情.csv",
        index_bar_header()
        + "000300.SH,20260102,102,100,103,99,101,1,0.99,1200,2200\n"
        + "000300.SH,20260103,103,102,104,101,102,1,0.98,1300,2300\n",
    )
    write_csv(
        root / "增量数据" / "大盘指数每日指标" / "2026-01" / "20260102_指数日线行情.csv",
        market_metrics_header()
        + "000300.SH,20260102,100000002,80000002,1000000,800000,700000,1,2,10,9,1\n",
    )
    write_csv(
        root / "增量数据" / "申万行业日线行情" / "2026-01" / "20260102_指数日线行情.csv",
        sw_daily_header() + "801010.SI,20260102,农林牧渔,12,13,11,12.5,1,8,15,37,22,2.2,5200,9200\n",
    )
    write_csv(
        root / "增量数据" / "中信行业日线行情" / "2026-01" / "20260102_指数日线行情.csv",
        citic_daily_header() + "CI005001.CI,20260102,21,22,20,21.5,20.5,1,4.9,15,38\n",
    )
    return root


def test_store_exposes_index_namespaces_and_basic_info(tmp_path: Path) -> None:
    root = build_index_root(tmp_path)
    store = FinfactStore(index_data_dir=root)

    info = store.index.basic_info(source="csi", columns="standard", include_source=True)

    assert list(info["index_code"]) == ["000300.SH"]
    assert info.iloc[0]["base_date"] == pd.Timestamp("2004-12-31")
    assert info.iloc[0]["source_group"] == "csi"
    assert info.iloc[0]["_source_kind"] == "csv"


def test_index_bars_reads_casefold_members_and_combines_incremental(tmp_path: Path) -> None:
    root = build_index_root(tmp_path)
    index = FinfactStore(index_data_dir=root).index

    casefold = index.bars("H00300.CSI", freq="day")
    combined = index.bars("000300.SH", freq="day", source="combined", include_source=True, columns="standard")

    assert casefold.iloc[0]["指数代码"] == "H00300.CSI"
    assert list(combined["trade_date"]) == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-02"),
        pd.Timestamp("2026-01-03"),
    ]
    assert combined.loc[combined["trade_date"] == pd.Timestamp("2026-01-02"), "close"].item() == 102
    assert combined.loc[combined["trade_date"] == pd.Timestamp("2026-01-02"), "_source_kind"].item() == "incremental"
    assert combined.attrs["field_units"]["amount_thousand_yuan"] == "千元"
    assert combined.attrs["field_units"]["volume_lot"] == "手"


def test_available_indices_lists_data_presence_without_conflating_sources(tmp_path: Path) -> None:
    root = build_index_root(tmp_path)
    index = FinfactStore(index_data_dir=root).index

    historical_day = index.available_indices(
        dataset="bars",
        freq="day",
        source="historical",
        columns="standard",
        include_source=True,
    )
    incremental_day = index.available_indices(
        dataset="bars",
        freq="day",
        source="incremental",
        columns="standard",
    )
    market_metrics = index.available_indices(dataset="market_metrics", columns="standard")
    all_indices = index.available_indices(columns="standard")

    assert set(historical_day["index_code"]) == {"000300.SH", "h00300.CSI"}
    h_row = historical_day[historical_day["index_code"] == "h00300.CSI"].iloc[0]
    assert h_row["has_day_bars"] is True
    assert h_row["has_market_metrics"] is False
    assert h_row["_source_member"] == "h00300.CSI.csv"

    assert set(incremental_day["index_code"]) == {"000300.SH"}
    assert incremental_day.iloc[0]["source"] == "incremental"

    assert list(market_metrics["index_code"]) == ["000300.SH"]
    assert market_metrics.iloc[0]["has_market_metrics"] is True

    rows = all_indices.set_index("index_code")
    assert rows.loc["000300.SH", "has_basic_info"] is True
    assert rows.loc["000300.SH", "has_day_bars"] is True
    assert rows.loc["000300.SH", "has_week_bars"] is True
    assert rows.loc["000300.SH", "has_month_bars"] is True
    assert rows.loc["000300.SH", "has_market_metrics"] is True
    assert rows.loc["h00300.CSI", "has_basic_info"] is False
    assert rows.loc["h00300.CSI", "has_day_bars"] is True
    assert rows.loc["105653.MI", "has_basic_info"] is True
    assert rows.loc["105653.MI", "has_day_bars"] is False


def test_market_metrics_maps_code_to_chinese_file_and_keeps_yuan_units(tmp_path: Path) -> None:
    root = build_index_root(tmp_path)
    df = FinfactStore(index_data_dir=root).index.market_metrics(
        "000300.SH",
        source="combined",
        columns="standard",
        include_source=True,
    )

    assert list(df["trade_date"]) == [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")]
    assert df.loc[df["trade_date"] == pd.Timestamp("2026-01-02"), "total_market_cap_yuan"].item() == 100000002
    assert df.loc[df["trade_date"] == pd.Timestamp("2026-01-01"), "_source_kind"].item() == "csv"
    assert df.attrs["field_units"]["total_market_cap_yuan"] == "元"


def test_industry_daily_and_classification_keep_sw_and_citic_distinct(tmp_path: Path) -> None:
    root = build_index_root(tmp_path)
    industry = FinfactStore(index_data_dir=root).industry

    sw = industry.daily("sw", "801010.SI", source="combined", columns="standard")
    citic = industry.daily("citic", "CI005001.CI", source="combined", columns="standard")
    sw_l2 = industry.classification("sw", level="L2", columns="standard")
    citic_all = industry.classification("citic", columns="standard")

    assert "pe" in sw.columns
    assert "pe" not in citic.columns
    assert sw.loc[sw["trade_date"] == pd.Timestamp("2026-01-02"), "close"].item() == 12.5
    assert sw.attrs["field_units"]["total_market_cap_10k_yuan"] == "万元"
    assert sw_l2.iloc[0]["industry_code"] == "110100"
    assert citic_all.iloc[1]["parent_code"] == "CI005001.CI"


def test_industry_members_preserve_snapshot_and_multi_membership(tmp_path: Path) -> None:
    root = build_index_root(tmp_path)
    industry = FinfactStore(index_data_dir=root).industry

    sw_members = industry.sw_members(date="2026-01-03", match="previous", columns="standard")
    citic_members = industry.citic_members(columns="standard")

    assert sw_members.iloc[0]["snapshot_date"] == pd.Timestamp("2026-01-02")
    assert sw_members.iloc[0]["symbol"] == "000592.SZ"
    assert len(citic_members[citic_members["symbol"] == "600777.SH"]) == 2
    assert set(citic_members["is_latest"]) == {"Y"}


def test_constituents_members_resolve_provider_and_previous_snapshot(tmp_path: Path) -> None:
    root = build_index_root(tmp_path)
    constituents = FinfactStore(index_data_dir=root).constituents

    df = constituents.index_members(
        "000300.SH",
        date="2026-02-01",
        provider="auto",
        match="previous",
        columns="standard",
        include_source=True,
    )

    assert df.iloc[0]["index_code"] == "000300.SH"
    assert df.iloc[0]["member_symbol"] == "600519.SH"
    assert df.iloc[0]["trade_date"] == pd.Timestamp("2026-01-31")
    assert df.iloc[0]["_source_kind"] == "zip"
