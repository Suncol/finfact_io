#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from finfact_io.exports.index_point_in_time import build_csi500_dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a point-in-time CSI 500 data directory from local index data.",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=None,
        help=(
            "Index data root. Defaults to FINFACT_INDEX_DATA_DIR, "
            "then FINFACT_RAW_DATA_DIR/指数数据, then the package default."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "csi500",
        help="Output directory. Defaults to ./data/csi500.",
    )
    parser.add_argument("--start", default=None, help="Optional start date, YYYY-MM-DD or YYYYMMDD.")
    parser.add_argument("--end", default=None, help="Optional end date, YYYY-MM-DD or YYYYMMDD.")
    parser.add_argument(
        "--asof-policy",
        choices=("next_trading_day", "same_day"),
        default="next_trading_day",
        help="When a constituent snapshot becomes usable for point-in-time expansion.",
    )
    parser.add_argument(
        "--no-daily-asof",
        action="store_true",
        help="Skip the large daily as-of constituent weight file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_csi500_dataset(
        index_data_dir=args.index_dir,
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        include_daily_asof=not args.no_daily_asof,
        asof_policy=args.asof_policy,
    )
    print(f"Output directory: {report.output_dir}")
    for name, rows in report.row_counts.items():
        print(f"{name}: {rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
