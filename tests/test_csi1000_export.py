from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from finfact_io.exports.csi1000 import build_csi1000_dataset


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


def complete_constituent_rows(date: str) -> str:
    rows = [
        f"000852.SH,{symbol},{date},0.10\n"
        for symbol in ["000001.SZ", "000003.SZ"]
    ]
    rows.extend(
        f"000852.SH,{code:06d}.SZ,{date},0.10\n"
        for code in range(10, 1008)
    )
    return "".join(rows)


def build_csi1000_root(root: Path) -> Path:
    write_csv(
        root / "指数基本信息_上交所指数.csv",
        (
            "指数代码,简称,市场,发布方,指数类别,基期,基点,发布日期\n"
            "000852.SH,中证1000,SSE,中证指数有限公司,规模指数,20041231,1000,20141017\n"
            "h00852.SH,中证1000全收益,SSE,中证指数有限公司,规模指数,20041231,1000,20141017\n"
        ),
    )
    write_zip_csv(
        root / "指数日线行情.zip",
        {
            "000852.SH.csv": index_bar_header()
            + "000852.SH,20260102,100,99,101,98,98,2,2.0408,1000,2000\n"
            + "000852.SH,20260105,101,100,102,99,100,1,1.0000,1100,2100\n",
        },
    )
    write_csv(
        root / "增量数据" / "指数日线行情" / "2026-01" / "20260105_指数日线行情.csv",
        index_bar_header()
        + "000852.SH,20260105,102,101,103,100,100,2,2.0000,1200,2200\n"
        + "000852.SH,20260106,104,103,105,102,102,2,1.9608,1300,2300\n",
    )
    write_zip_csv(
        root / "上交所指数成分" / "上交所指数成分_20251231.zip",
        {
            "000852.SH.csv": constituent_header()
            + "000852.SH,000001.SZ,20251231,0.10\n"
            + "000852.SH,000002.SZ,20251231,0.20\n",
        },
    )
    write_zip_csv(
        root / "上交所指数成分" / "上交所指数成分_20260105.zip",
        {
            "000852.SH.csv": constituent_header() + complete_constituent_rows("20260105"),
        },
    )
    return root


def test_build_csi1000_dataset_writes_prices_snapshots_asof_and_quality(tmp_path: Path) -> None:
    index_root = build_csi1000_root(tmp_path / "source")
    output_dir = tmp_path / "out"

    report = build_csi1000_dataset(index_data_dir=index_root, output_dir=output_dir)

    assert report.row_counts["index_daily"] == 3
    assert report.row_counts["constituent_weights_snapshots"] == 2
    assert report.row_counts["constituent_weights_snapshot_members"] == 1002
    assert report.row_counts["constituent_weights_daily_asof"] == 3
    assert report.row_counts["constituent_weights_daily_asof_members"] == 1004
    assert (output_dir / "README.md").is_file()

    daily = pd.read_csv(output_dir / "index_daily.csv")
    assert list(daily["date"]) == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert daily.loc[daily["date"] == "2026-01-05", "close"].item() == 102
    assert daily.loc[daily["date"] == "2026-01-05", "source_kind"].item() == "incremental"
    assert daily.loc[daily["date"] == "2026-01-06", "return"].item() == 0.019608
    assert daily["total_return"].isna().all()
    assert set(daily["total_return_available"]) == {False}
    assert set(daily["volume_unit"]) == {"手"}
    assert set(daily["amount_unit"]) == {"千元"}

    snapshots = pd.read_csv(output_dir / "constituent_weights_snapshots.csv")
    assert set(snapshots["date"]) == {"2025-12-31", "2026-01-05"}
    assert set(snapshots["file_path"]) == {
        "constituent_weights_snapshots/2025-12-31.csv",
        "constituent_weights_snapshots/2026-01-05.csv",
    }
    assert snapshots["duplicate_member_rows"].sum() == 0
    assert (
        snapshots.loc[snapshots["date"] == "2025-12-31", "quality_status"].unique().tolist()
        == ["incomplete"]
    )
    assert (
        snapshots.loc[snapshots["date"] == "2026-01-05", "quality_status"].unique().tolist()
        == ["complete"]
    )
    snapshot_rows = pd.read_csv(output_dir / "constituent_weights_snapshots" / "2026-01-05.csv")
    assert len(snapshot_rows) == 1000
    assert {"000001.SZ", "000003.SZ"}.issubset(set(snapshot_rows["member_symbol"]))

    daily_asof_index = pd.read_csv(output_dir / "constituent_weights_daily_asof.csv")
    assert set(daily_asof_index["date"]) == {"2026-01-02", "2026-01-05", "2026-01-06"}
    assert set(daily_asof_index["file_path"]) == {
        "constituent_weights_daily_asof/2026-01-02.csv",
        "constituent_weights_daily_asof/2026-01-05.csv",
        "constituent_weights_daily_asof/2026-01-06.csv",
    }
    assert daily_asof_index["duplicate_member_rows"].sum() == 0
    jan5 = pd.read_csv(output_dir / "constituent_weights_daily_asof" / "2026-01-05.csv")
    jan6 = pd.read_csv(output_dir / "constituent_weights_daily_asof" / "2026-01-06.csv")
    assert set(jan5["member_symbol"]) == {"000001.SZ", "000002.SZ"}
    assert set(jan5["weight_snapshot_date"]) == {"2025-12-31"}
    assert {"000001.SZ", "000003.SZ"}.issubset(set(jan6["member_symbol"]))
    assert len(jan6) == 1000
    assert set(jan6["weight_snapshot_date"]) == {"2026-01-05"}

    quality = pd.read_csv(output_dir / "data_quality.csv")
    assert {
        "total_return_unavailable",
        "incomplete_constituent_snapshot",
        "snapshot_duplicate_members",
        "snapshot_complete_weight_sum",
        "snapshot_complete_member_count",
        "daily_asof_duplicate_members",
        "daily_asof_complete_weight_sum",
        "daily_asof_complete_member_count",
    }.issubset(set(quality["check"]))
    assert (
        quality.loc[quality["check"] == "snapshot_duplicate_members", "status"].item()
        == "pass"
    )
    assert (
        quality.loc[quality["check"] == "daily_asof_duplicate_members", "status"].item()
        == "pass"
    )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["index_code"] == "000852.SH"
    assert manifest["total_return"]["available"] is False
    assert manifest["point_in_time"]["asof_policy"] == "next_trading_day"
    assert manifest["files"]["index_daily.csv"]["rows"] == 3
    assert manifest["files"]["constituent_weights_snapshots.csv"]["rows"] == 2
    assert manifest["files"]["constituent_weights_snapshots.csv"]["member_rows"] == 1002
    assert manifest["files"]["constituent_weights_daily_asof.csv"]["rows"] == 3
    assert manifest["files"]["constituent_weights_daily_asof.csv"]["member_rows"] == 1004
