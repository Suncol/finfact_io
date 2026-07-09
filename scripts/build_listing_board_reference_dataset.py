from __future__ import annotations

import argparse
from pathlib import Path

from finfact_io.exports.listing_board_reference import (
    build_listing_board_reference_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the static A-share listing-board reference dataset."
    )
    parser.add_argument(
        "--ashare-daily-dir",
        default=None,
        help=(
            "A-share daily data root. Defaults to FINFACT_ASHARE_DAILY_DIR, "
            "then FINFACT_RAW_DATA_DIR/A股数据_每日指标, then the package default."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Defaults to data/listing_board_current_reference.",
    )
    args = parser.parse_args()

    report = build_listing_board_reference_dataset(
        ashare_daily_dir=args.ashare_daily_dir,
        output_dir=args.output_dir,
    )
    print(f"Output directory: {Path(report.output_dir).resolve()}")
    for name, count in report.row_counts.items():
        print(f"{name}: {count} rows")


if __name__ == "__main__":
    main()
