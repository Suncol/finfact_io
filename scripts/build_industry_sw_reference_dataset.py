from __future__ import annotations

import argparse
from pathlib import Path

from finfact_io.exports.industry_sw_reference import (
    SW_REFERENCE_SNAPSHOT_DATE,
    build_industry_sw_reference_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the static SW2021 current industry reference dataset."
    )
    parser.add_argument("--index-data-dir", default=None)
    parser.add_argument("--ashare-daily-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--snapshot-date", default=SW_REFERENCE_SNAPSHOT_DATE)
    args = parser.parse_args()

    report = build_industry_sw_reference_dataset(
        index_data_dir=args.index_data_dir,
        ashare_daily_dir=args.ashare_daily_dir,
        output_dir=args.output_dir,
        snapshot_date=args.snapshot_date,
    )
    print(f"Output directory: {Path(report.output_dir).resolve()}")
    for name, count in report.row_counts.items():
        print(f"{name}: {count} rows")


if __name__ == "__main__":
    main()
