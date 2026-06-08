from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from finfact_io.exports.index_point_in_time import (
    CSI1000_SPEC,
    build_csi300_dataset,
    build_csi500_dataset,
    build_csi1000_dataset,
    build_csi2000_dataset,
    build_index_point_in_time_dataset,
)


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


def constituent_header() -> str:
    return "指数代码,成分股票代码,交易日期,权重\n"


def constituent_rows(index_code: str, date: str, count: int, *, weight: float | None = None) -> str:
    row_weight = 100.0 / count if weight is None else weight
    return "".join(
        f"{index_code},{code:06d}.SZ,{date},{row_weight:.8f}\n"
        for code in range(1, count + 1)
    )


def build_multi_index_root(root: Path) -> Path:
    basic_header = "指数代码,简称,市场,发布方,指数类别,基期,基点,发布日期\n"
    write_csv(
        root / "指数基本信息_上交所指数.csv",
        basic_header
        + "000300.SH,沪深300,SSE,中证指数有限公司,规模指数,20041231,1000,20050408\n"
        + "000905.SH,中证500,SSE,中证指数有限公司,规模指数,20041231,1000,20070115\n"
        + "000852.SH,中证1000,SSE,中证指数有限公司,规模指数,20041231,1000,20141017\n",
    )
    write_csv(
        root / "指数基本信息_中证指数.csv",
        basic_header
        + "932000.CSI,中证2000,CSI,中证指数有限公司,规模指数,20131231,1000,20230811\n"
        + "h00300.CSI,300收益,CSI,中证指数有限公司,规模指数,20041231,1000,20050408\n"
        + "h00905.CSI,500收益,CSI,中证指数有限公司,规模指数,20041231,1000,20070115\n"
        + "932000CNY010.CSI,中证2000全收益,CSI,中证指数有限公司,规模指数,20131231,1000,20230811\n",
    )
    write_zip_csv(
        root / "指数日线行情.zip",
        {
            "000300.SH.csv": index_bar_header()
            + "000300.SH,20260102,100,99,101,98,98,2,2.0408,1000,2000\n"
            + "000300.SH,20260105,101,100,102,99,100,1,1.0000,1100,2100\n",
            "000905.SH.csv": index_bar_header()
            + "000905.SH,20260102,200,199,201,198,198,2,1.0101,1000,2000\n"
            + "000905.SH,20260105,202,200,203,199,200,2,1.0000,1100,2100\n",
            "000852.SH.csv": index_bar_header()
            + "000852.SH,20260102,300,299,301,298,298,2,0.6711,1000,2000\n"
            + "000852.SH,20260105,303,300,304,299,300,3,1.0000,1100,2100\n",
            "932000.CSI.csv": index_bar_header()
            + "932000.CSI,20260102,400,399,401,398,398,2,0.5025,1000,2000\n"
            + "932000.CSI,20260105,404,400,405,399,400,4,1.0000,1100,2100\n",
            "h00300.CSI.csv": index_bar_header()
            + "h00300.CSI,20260102,1000,999,1001,998,998,2,0.2004,900,1900\n"
            + "h00300.CSI,20260105,1005,1000,1006,999,1000,5,0.5000,910,1910\n",
            "h00905.CSI.csv": index_bar_header()
            + "h00905.CSI,20260102,2000,1999,2001,1998,1998,2,0.1001,900,1900\n"
            + "h00905.CSI,20260105,2010,2000,2011,1999,2000,10,0.5000,910,1910\n",
        },
    )
    write_csv(
        root / "增量数据" / "指数日线行情" / "2026-01" / "20260106_指数日线行情.csv",
        index_bar_header()
        + "000300.SH,20260106,102,101,103,100,101,1,0.9901,1200,2200\n"
        + "000905.SH,20260106,204,202,205,201,202,2,0.9901,1200,2200\n"
        + "000852.SH,20260106,306,303,307,302,303,3,0.9901,1200,2200\n"
        + "932000.CSI,20260106,408,404,409,403,404,4,0.9901,1200,2200\n",
    )
    write_zip_csv(
        root / "上交所指数成分" / "上交所指数成分_20251231.zip",
        {
            "000300.SH.csv": constituent_header()
            + constituent_rows("000300.SH", "20251231", 300),
            "000905.SH.csv": constituent_header()
            + constituent_rows("000905.SH", "20251231", 500),
            "000852.SH.csv": constituent_header()
            + "000852.SH,000001.SZ,20251231,40\n"
            + "000852.SH,000002.SZ,20251231,30\n"
            + "000852.SH,000003.SZ,20251231,30\n",
        },
    )
    write_zip_csv(
        root / "上交所指数成分" / "上交所指数成分_20260105.zip",
        {
            "000852.SH.csv": constituent_header()
            + constituent_rows("000852.SH", "20260105", 1001),
        },
    )
    write_zip_csv(
        root / "中证指数成分" / "中证指数成分_20251231.zip",
        {
            "932000.CSI.csv": constituent_header()
            + constituent_rows("932000.CSI", "20251231", 2000),
        },
    )
    return root


def test_build_index_point_in_time_dataset_uses_spec_provider_and_total_return(tmp_path: Path) -> None:
    source = build_multi_index_root(tmp_path / "source")
    output = tmp_path / "csi300"

    report = build_csi300_dataset(index_data_dir=source, output_dir=output)

    assert report.row_counts["index_daily"] == 3
    assert report.row_counts["constituent_weights_snapshots"] == 1
    assert report.row_counts["constituent_weights_snapshot_members"] == 300
    assert report.row_counts["constituent_weights_daily_asof"] == 3
    assert report.row_counts["constituent_weights_daily_asof_members"] == 900

    daily = pd.read_csv(output / "index_daily.csv")
    assert list(daily["date"]) == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert set(daily["index_name"]) == {"沪深300"}
    assert daily.loc[daily["date"] == "2026-01-02", "total_return"].item() == 1000
    assert set(daily["total_return_available"]) == {True}

    snapshots = pd.read_csv(output / "constituent_weights_snapshots.csv")
    assert snapshots.iloc[0]["provider"] == "sse"
    assert snapshots.iloc[0]["member_count"] == 300
    assert snapshots.iloc[0]["quality_status"] == "complete"

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"] == "csi300"
    assert manifest["index_code"] == "000300.SH"
    assert manifest["expected_member_count"] == 300
    assert manifest["constituent_provider"] == "sse"
    assert manifest["total_return"]["code"] == "h00300.CSI"
    assert manifest["total_return"]["available"] is True


def test_build_csi2000_dataset_reads_csi_provider_and_warns_missing_total_return(tmp_path: Path) -> None:
    source = build_multi_index_root(tmp_path / "source")
    output = tmp_path / "csi2000"

    report = build_csi2000_dataset(index_data_dir=source, output_dir=output)

    assert report.row_counts["index_daily"] == 3
    assert report.row_counts["constituent_weights_snapshot_members"] == 2000
    assert report.row_counts["constituent_weights_daily_asof_members"] == 6000

    snapshots = pd.read_csv(output / "constituent_weights_snapshots.csv")
    assert snapshots.iloc[0]["provider"] == "csi"
    assert snapshots.iloc[0]["member_count"] == 2000
    assert snapshots.iloc[0]["quality_status"] == "complete"

    quality = pd.read_csv(output / "data_quality.csv")
    assert (
        quality.loc[quality["check"] == "total_return_unavailable", "status"].item()
        == "warning"
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"] == "csi2000"
    assert manifest["index_code"] == "932000.CSI"
    assert manifest["constituent_provider"] == "csi"
    assert manifest["total_return"]["available"] is False


def test_csi1000_quality_uses_expected_member_count_not_fixed_900_threshold(tmp_path: Path) -> None:
    source = build_multi_index_root(tmp_path / "source")
    output = tmp_path / "csi1000"

    build_csi1000_dataset(index_data_dir=source, output_dir=output)

    snapshots = pd.read_csv(output / "constituent_weights_snapshots.csv")
    statuses = snapshots.set_index("date")["quality_status"].to_dict()
    assert statuses["2025-12-31"] == "incomplete"
    assert statuses["2026-01-05"] == "complete"

    quality = pd.read_csv(output / "data_quality.csv")
    incomplete = quality[quality["check"] == "incomplete_constituent_snapshot"]
    assert list(incomplete["affected_date"]) == ["2025-12-31"]


def test_wrapper_builders_set_default_dataset_names(tmp_path: Path) -> None:
    source = build_multi_index_root(tmp_path / "source")

    csi500 = build_csi500_dataset(index_data_dir=source, output_dir=tmp_path / "out500")
    csi1000 = build_index_point_in_time_dataset(
        CSI1000_SPEC,
        index_data_dir=source,
        output_dir=tmp_path / "out1000",
        include_daily_asof=False,
    )

    assert (tmp_path / "out500" / "manifest.json").is_file()
    assert csi500.row_counts["constituent_weights_snapshot_members"] == 500
    assert csi1000.row_counts["constituent_weights_snapshots"] == 2
    assert "constituent_weights_daily_asof" not in csi1000.row_counts
