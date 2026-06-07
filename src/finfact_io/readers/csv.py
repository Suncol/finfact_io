from __future__ import annotations

import io
import warnings
from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd

from finfact_io.errors import (
    CsvEncodingError,
    CsvEncodingWarning,
    DataFileNotFoundError,
    SchemaError,
)

DEFAULT_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "gb18030")

DATE_COLUMNS = {
    "交易日期",
    "日期",
    "上市日期",
    "退市日期",
    "上一个交易日",
    "基期",
    "发布日期",
    "纳入日期",
    "剔除日期",
    "快照日期",
}
STRING_COLUMNS = {
    "TS代码",
    "股票代码",
    "指数代码",
    "成分股票代码",
    "股票名称",
    "简称",
    "市场",
    "发布方",
    "指数类别",
    "地域",
    "所属行业",
    "股票全称",
    "英文全称",
    "拼音缩写",
    "市场类型",
    "交易所代码",
    "交易货币",
    "上市状态",
    "沪深港通标的",
    "实控人名称",
    "实控人企业性质",
    "交易所",
    "是否交易",
    "行业名称",
    "行业分级",
    "行业代码",
    "是否发布指数",
    "父级代码",
    "分类来源",
    "一级行业代码",
    "一级行业名称",
    "二级行业代码",
    "二级行业名称",
    "三级行业代码",
    "三级行业名称",
    "_source_path",
    "_source_member",
    "_source_kind",
    "复权类型",
}


def read_csv_file(
    path: str | Path,
    *,
    encodings: Sequence[str] = DEFAULT_ENCODINGS,
    required_columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise DataFileNotFoundError(f"CSV file not found: {source}")
    return read_csv_bytes(
        source.read_bytes(),
        source=str(source),
        encodings=encodings,
        required_columns=required_columns,
    )


def read_csv_bytes(
    data: bytes,
    *,
    source: str,
    encodings: Sequence[str] = DEFAULT_ENCODINGS,
    required_columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    failures: list[str] = []
    for index, encoding in enumerate(encodings):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError as exc:
            failures.append(f"{encoding}: {exc}")
            continue

        if index > 0:
            warnings.warn(
                f"CSV {source} required fallback encoding {encoding}",
                CsvEncodingWarning,
                stacklevel=2,
            )
        return read_csv_text(
            text,
            source=source,
            encoding=encoding,
            required_columns=required_columns,
        )

    details = "; ".join(failures) if failures else "no encodings configured"
    raise CsvEncodingError(f"Unable to decode CSV {source}; tried {tuple(encodings)}. {details}")


def read_csv_text(
    text: str,
    *,
    source: str,
    encoding: str,
    required_columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.StringIO(text), dtype="string", keep_default_na=False)
    except Exception as exc:  # pandas includes parser context in the nested error.
        raise SchemaError(f"Unable to parse CSV {source}: {exc}") from exc

    df = df.replace("", pd.NA)
    validate_required_columns(df, required_columns, source=source)
    df = normalize_dataframe_types(df)
    df.attrs["source_encoding"] = encoding
    return df


def validate_required_columns(
    df: pd.DataFrame,
    required_columns: Iterable[str] | None,
    *,
    source: str,
) -> None:
    if required_columns is None:
        return
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise SchemaError(f"CSV {source} is missing required columns: {missing}")


def normalize_dataframe_types(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    for column in normalized.columns:
        if column in DATE_COLUMNS:
            normalized[column] = parse_date_series(normalized[column])
        elif column in STRING_COLUMNS:
            normalized[column] = normalized[column].astype("string")
        else:
            normalized[column] = maybe_numeric(normalized[column])
    return normalized


def parse_date_series(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

    non_null = values.notna()
    digit_dates = non_null & values.str.fullmatch(r"\d{8}").fillna(False)
    other_dates = non_null & ~digit_dates

    if digit_dates.any():
        result.loc[digit_dates] = pd.to_datetime(
            values.loc[digit_dates],
            format="%Y%m%d",
            errors="coerce",
        )
    if other_dates.any():
        result.loc[other_dates] = pd.to_datetime(values.loc[other_dates], errors="coerce")
    return result


def parse_date_value(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return pd.Timestamp(pd.to_datetime(text, format="%Y%m%d"))
    return pd.Timestamp(pd.to_datetime(text))


def maybe_numeric(series: pd.Series) -> pd.Series:
    non_null = series.dropna()
    if non_null.empty:
        return series

    converted = pd.to_numeric(series, errors="coerce")
    if converted.loc[non_null.index].notna().all():
        return converted
    return series.astype("string")
