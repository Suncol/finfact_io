from __future__ import annotations

import argparse
from pathlib import Path

from finfact_io.exports.ashare_daily_metrics import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    build_ashare_daily_metrics_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build all A-share daily metrics organized by trading day."
    )
    parser.add_argument("--ashare-daily-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--start", default=DEFAULT_START_DATE)
    parser.add_argument("--end", default=DEFAULT_END_DATE)
    args = parser.parse_args()

    report = build_ashare_daily_metrics_dataset(
        ashare_daily_dir=args.ashare_daily_dir,
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
    )
    print(f"Output directory: {Path(report.output_dir).resolve()}")
    for name, count in report.row_counts.items():
        print(f"{name}: {count} rows")


if __name__ == "__main__":
    main()
