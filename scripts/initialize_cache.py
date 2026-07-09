#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from finfact_io import FinfactStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_CACHE_DIR = PROJECT_ROOT / ".cache"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize finfact-io local data roots and build archive caches.",
    )
    parser.add_argument(
        "--ashare-dir",
        type=Path,
        default=None,
        help=(
            "A-share daily data root. Defaults to FINFACT_ASHARE_DAILY_DIR, "
            "then FINFACT_RAW_DATA_DIR/A股数据_每日指标, then the package default."
        ),
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
        "--cache-dir",
        type=Path,
        default=None,
        help=f"Cache root for extracted archives. Defaults to {DEFAULT_PROJECT_CACHE_DIR}.",
    )
    parser.add_argument(
        "--validation",
        choices=("none", "sample", "full"),
        default="sample",
        help="Validation depth for CSV headers while initializing.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild existing extracted cache directories.",
    )
    parser.add_argument(
        "--skip-ashare",
        action="store_true",
        help="Skip A-share daily data initialization.",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip index bars, industry daily, and constituents initialization.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cache_dir = args.cache_dir if args.cache_dir is not None else DEFAULT_PROJECT_CACHE_DIR
    store = FinfactStore(
        ashare_daily_dir=args.ashare_dir,
        index_data_dir=args.index_dir,
    )

    print(f"Cache root: {cache_dir.expanduser().resolve()}")

    if not args.skip_ashare:
        ashare_report = store.ashare.initialize(
            archive_mode="extract",
            validation=args.validation,
            cache_dir=cache_dir,
            rebuild=args.rebuild,
        )
        print(
            "A-share daily cache: "
            f"root={ashare_report.root} "
            f"archives={len(ashare_report.zip_archives)} "
            f"members={sum(report.member_count for report in ashare_report.zip_archives.values())}"
        )
        for logical_name, report in ashare_report.zip_archives.items():
            print(f"  - {logical_name}: {report.member_count} members -> {report.extracted_to}")

    if not args.skip_index:
        index_report = store.index.initialize(
            archive_mode="extract",
            validation=args.validation,
            cache_dir=cache_dir,
            rebuild=args.rebuild,
        )
        print(
            "Index bars cache: "
            f"root={index_report.root} "
            f"archives={len(index_report.zip_archives)} "
            f"members={sum(report.member_count for report in index_report.zip_archives.values())}"
        )
        for freq, report in index_report.zip_archives.items():
            print(f"  - {freq}: {report.member_count} members -> {report.extracted_to}")

        industry_report = store.industry.initialize(
            archive_mode="extract",
            validation=args.validation,
            cache_dir=cache_dir,
            rebuild=args.rebuild,
        )
        print(
            "Industry daily cache: "
            f"root={industry_report.root} "
            f"sw_members={industry_report.sw_daily_members} "
            f"citic_members={industry_report.citic_daily_members} "
            f"sw_member_snapshots={industry_report.sw_member_snapshots}"
        )

        constituents_report = store.constituents.initialize(validation=args.validation)
        provider_summary = ", ".join(
            f"{provider}={report.zip_count}"
            for provider, report in constituents_report.providers.items()
        )
        print(
            "Index constituents manifest: "
            f"root={constituents_report.root} providers=({provider_summary})"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
