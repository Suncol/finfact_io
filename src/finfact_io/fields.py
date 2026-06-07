from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

FIELD_UNITS_RAW: dict[str, str] = {
    "成交量(手)": "手",
    "成交额(千元)": "千元",
    "成交量(万股)": "万股",
    "成交额(万元)": "万元",
    "总股本(股)": "股",
    "流通股本(股)": "股",
    "自由流通股本(股)": "股",
    "总股本(万股)": "万股",
    "流通股本(万股)": "万股",
    "自由流通股本(万股)": "万股",
    "总市值(元)": "元",
    "流通市值(元)": "元",
    "总市值(万元)": "万元",
    "流通市值(万元)": "万元",
    "权重": "%",
}

STOCK_ALIASES: dict[str, str] = {
    "TS代码": "symbol",
    "股票代码": "stock_code",
    "股票名称": "name",
    "地域": "region",
    "所属行业": "industry",
    "股票全称": "full_name",
    "英文全称": "english_name",
    "拼音缩写": "pinyin",
    "市场类型": "market_type",
    "交易所代码": "exchange_code",
    "交易货币": "currency",
    "上市状态": "status",
    "上市日期": "list_date",
    "退市日期": "delist_date",
    "沪深港通标的": "connect_target",
    "实控人名称": "controller_name",
    "实控人企业性质": "controller_type",
}

CALENDAR_ALIASES: dict[str, str] = {
    "交易所": "exchange",
    "日期": "date",
    "是否交易": "is_open",
    "上一个交易日": "previous_trade_date",
}

DAILY_METRIC_ALIASES: dict[str, str] = {
    "股票代码": "symbol",
    "交易日期": "trade_date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "昨收价": "previous_close",
    "涨跌额": "change",
    "涨跌幅": "pct_change",
    "成交量(手)": "volume",
    "成交额(千元)": "amount",
    "换手率": "turnover_rate",
    "换手率(自由流通股)": "free_float_turnover_rate",
    "量比": "volume_ratio",
    "市盈率": "pe",
    "市盈率TTM": "pe_ttm",
    "市净率": "pb",
    "市销率": "ps",
    "市销率TTM": "ps_ttm",
    "股息率": "dividend_yield",
    "股息率TTM": "dividend_yield_ttm",
    "总股本(万股)": "total_share_capital",
    "流通股本(万股)": "float_share_capital",
    "自由流通股本(万股)": "free_float_share_capital",
    "总市值(万元)": "total_market_cap",
    "流通市值(万元)": "float_market_cap",
}

TECHNICAL_FACTOR_ALIASES: dict[str, str] = {
    **{
        key: value
        for key, value in DAILY_METRIC_ALIASES.items()
        if key
        not in {
            "昨收价",
            "涨跌额",
            "涨跌幅",
            "换手率",
            "换手率(自由流通股)",
            "市盈率",
            "市盈率TTM",
            "市净率",
            "市销率",
            "市销率TTM",
            "股息率",
            "股息率TTM",
            "总股本(万股)",
            "流通股本(万股)",
            "自由流通股本(万股)",
            "总市值(万元)",
            "流通市值(万元)",
        }
    },
    "涨跌幅(%)": "pct_change",
    "换手率(%)": "turnover_rate",
    "复权因子": "adjustment_factor",
    "复权类型": "adjustment",
}

INDEX_BASIC_INFO_ALIASES: dict[str, str] = {
    "指数代码": "index_code",
    "简称": "name",
    "市场": "market",
    "发布方": "publisher",
    "指数类别": "category",
    "基期": "base_date",
    "基点": "base_point",
    "发布日期": "publish_date",
}

INDEX_BAR_ALIASES: dict[str, str] = {
    "指数代码": "index_code",
    "交易日期": "trade_date",
    "频率": "freq",
    "收盘点位": "close",
    "开盘点位": "open",
    "最高点位": "high",
    "最低点位": "low",
    "昨日收盘点": "previous_close",
    "涨跌点": "change",
    "涨跌幅(%)": "pct_change",
    "成交量(手)": "volume_lot",
    "成交额(千元)": "amount_thousand_yuan",
}

INDEX_MARKET_METRIC_ALIASES: dict[str, str] = {
    "指数代码": "index_code",
    "交易日期": "trade_date",
    "总市值(元)": "total_market_cap_yuan",
    "流通市值(元)": "float_market_cap_yuan",
    "总股本(股)": "total_share_shares",
    "流通股本(股)": "float_share_shares",
    "自由流通股本(股)": "free_float_share_shares",
    "换手率": "turnover_rate",
    "换手率(自由流通)": "free_float_turnover_rate",
    "市盈率": "pe",
    "市盈率TTM": "pe_ttm",
    "市净率": "pb",
}

INDUSTRY_SW_DAILY_ALIASES: dict[str, str] = {
    "指数代码": "index_code",
    "交易日期": "trade_date",
    "行业名称": "industry_name",
    "开盘点位": "open",
    "最高点位": "high",
    "最低点位": "low",
    "收盘点位": "close",
    "涨跌点位": "change",
    "涨跌幅": "pct_change",
    "成交量(万股)": "volume_10k_shares",
    "成交额(万元)": "amount_10k_yuan",
    "市盈率": "pe",
    "市净率": "pb",
    "流通市值(万元)": "float_market_cap_10k_yuan",
    "总市值(万元)": "total_market_cap_10k_yuan",
}

INDUSTRY_CITIC_DAILY_ALIASES: dict[str, str] = {
    "指数代码": "index_code",
    "交易日期": "trade_date",
    "开盘点位": "open",
    "最高点位": "high",
    "最低点位": "low",
    "收盘点位": "close",
    "昨日收盘点位": "previous_close",
    "涨跌点位": "change",
    "涨跌幅": "pct_change",
    "成交量(万股)": "volume_10k_shares",
    "成交额(万元)": "amount_10k_yuan",
}

INDUSTRY_CLASSIFICATION_ALIASES: dict[str, str] = {
    "体系": "system",
    "指数代码": "index_code",
    "行业名称": "industry_name",
    "行业分级": "level",
    "行业代码": "industry_code",
    "是否发布指数": "publishes_index",
    "父级代码": "parent_code",
    "分类来源": "classification_source",
}

SW_INDUSTRY_MEMBER_ALIASES: dict[str, str] = {
    "快照日期": "snapshot_date",
    "一级行业代码": "l1_industry_code",
    "一级行业名称": "l1_industry_name",
    "二级行业代码": "l2_industry_code",
    "二级行业名称": "l2_industry_name",
    "三级行业代码": "l3_industry_code",
    "三级行业名称": "l3_industry_name",
    "股票代码": "symbol",
    "股票名称": "name",
    "纳入日期": "in_date",
    "剔除日期": "out_date",
}

CITIC_INDUSTRY_MEMBER_ALIASES: dict[str, str] = {
    "一级行业代码": "l1_industry_code",
    "一级行业名称": "l1_industry_name",
    "二级行业代码": "l2_industry_code",
    "二级行业名称": "l2_industry_name",
    "三级行业代码": "l3_industry_code",
    "三级行业名称": "l3_industry_name",
    "股票代码": "symbol",
    "股票名称": "name",
    "纳入日期": "in_date",
    "剔除日期": "out_date",
    "是否最新": "is_latest",
}

INDEX_CONSTITUENT_ALIASES: dict[str, str] = {
    "指数代码": "index_code",
    "成分股票代码": "member_symbol",
    "交易日期": "trade_date",
    "快照日期": "snapshot_date",
    "权重": "weight",
}

AVAILABLE_INDEX_ALIASES: dict[str, str] = {
    "指数代码": "index_code",
    "数据集": "dataset",
    "频率": "freq",
    "来源": "source",
    "信息来源": "source_group",
    "有基本信息": "has_basic_info",
    "有日线行情": "has_day_bars",
    "有周线行情": "has_week_bars",
    "有月线行情": "has_month_bars",
    "有市场指标": "has_market_metrics",
}

DATASET_ALIASES: dict[str, Mapping[str, str]] = {
    "stocks": STOCK_ALIASES,
    "calendar": CALENDAR_ALIASES,
    "daily_metrics": DAILY_METRIC_ALIASES,
    "technical_factors": TECHNICAL_FACTOR_ALIASES,
    "index_basic_info": INDEX_BASIC_INFO_ALIASES,
    "index_bars": INDEX_BAR_ALIASES,
    "index_market_metrics": INDEX_MARKET_METRIC_ALIASES,
    "industry_sw_daily": INDUSTRY_SW_DAILY_ALIASES,
    "industry_citic_daily": INDUSTRY_CITIC_DAILY_ALIASES,
    "industry_classification": INDUSTRY_CLASSIFICATION_ALIASES,
    "industry_sw_members": SW_INDUSTRY_MEMBER_ALIASES,
    "industry_citic_members": CITIC_INDUSTRY_MEMBER_ALIASES,
    "index_constituents": INDEX_CONSTITUENT_ALIASES,
    "available_indices": AVAILABLE_INDEX_ALIASES,
}


def with_unit_metadata(df: pd.DataFrame, aliases: Mapping[str, str] | None = None) -> pd.DataFrame:
    field_units: dict[str, str] = {}
    for raw_name, unit in FIELD_UNITS_RAW.items():
        if raw_name not in df.columns:
            continue
        name = aliases.get(raw_name, raw_name) if aliases is not None else raw_name
        field_units[name] = unit
    df.attrs["field_units"] = field_units
    return df


def standardize_columns(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    aliases = DATASET_ALIASES[dataset]
    standardized = df.rename(columns={raw: name for raw, name in aliases.items() if raw in df.columns})
    field_units: dict[str, str] = {}
    for raw_name, unit in FIELD_UNITS_RAW.items():
        if raw_name in df.columns:
            field_units[aliases.get(raw_name, raw_name)] = unit
    standardized.attrs["field_units"] = field_units
    return standardized
