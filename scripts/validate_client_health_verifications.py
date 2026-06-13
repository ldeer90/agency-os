#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agency_ops_ingestion import (  # noqa: E402
    SourcePaths,
    parse_client_health_assets,
    read_csv_rows,
    today_iso,
    utc_now_iso,
)


REQUIRED_VERIFIED_ASSETS = {
    "drive_root_verified",
    "drive_roadmap_folder_verified",
    "drive_roadmap_files",
    "drive_roadmap_content",
    "drive_content_folder_verified",
    "drive_reports_folder_verified",
    "ga4_access",
    "search_console_access",
    "se_ranking_access",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate that client-health verification manifests are populated before ingesting agency memory."
    )
    parser.add_argument("--monday-hub-root", default=str(SourcePaths().monday_hub), help="monday-agency-hub root.")
    parser.add_argument("--seo-automation-root", default=str(SourcePaths().seo_automation), help="SEO Automation root.")
    parser.add_argument("--seo-reporting-root", default=str(SourcePaths().seo_reporting), help="seo-reporting-platform root.")
    parser.add_argument("--big-query-root", default=str(SourcePaths().big_query), help="Big Query control folder root.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = SourcePaths(
        monday_hub=Path(args.monday_hub_root),
        seo_automation=Path(args.seo_automation_root),
        seo_reporting=Path(args.seo_reporting_root),
        big_query=Path(args.big_query_root),
    )
    board_rows = read_csv_rows(paths.monday_derived / "client_board_matrix.csv")
    rows = parse_client_health_assets(
        paths,
        board_rows,
        run_id="verification-preflight",
        ingested_at=utc_now_iso(),
        snapshot_date=today_iso(),
    )

    unknown_required = [
        {
            "client_slug": row["client_slug"],
            "client_name": row["client_name"],
            "asset_type": row["asset_type"],
            "verification_level": row.get("verification_level"),
            "verification_method": row.get("verification_method"),
            "notes": row.get("notes"),
        }
        for row in rows
        if row["asset_type"] in REQUIRED_VERIFIED_ASSETS and row["presence_status"] == "unknown"
    ]
    by_status: dict[str, int] = {}
    for row in rows:
        if row["asset_type"] not in REQUIRED_VERIFIED_ASSETS:
            continue
        key = f"{row['asset_type']}:{row['presence_status']}"
        by_status[key] = by_status.get(key, 0) + 1

    payload = {
        "status": "passed" if not unknown_required else "failed",
        "required_verified_assets": sorted(REQUIRED_VERIFIED_ASSETS),
        "unknown_required_count": len(unknown_required),
        "unknown_required": unknown_required,
        "status_counts": dict(sorted(by_status.items())),
    }
    print(json.dumps(payload, indent=None if args.json else 2))
    return 0 if not unknown_required else 1


if __name__ == "__main__":
    raise SystemExit(main())
