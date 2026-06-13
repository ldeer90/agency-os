#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agency_ops_ingestion import AgencyOpsBigQueryIngestor, SourcePaths, collect_agency_ops_rows, source_registry_rows, today_iso, utc_now_iso
from agency_bigquery.cost_config import BigQueryCostConfig, DEFAULT_CONFIG_PATH
from scripts.validate_client_health_verifications import main as validate_client_health_verifications_main


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Env file does not exist: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in SAFE_ENV_KEYS:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if key == "GOOGLE_APPLICATION_CREDENTIALS":
            cleaned = str(Path(os.path.expanduser(os.path.expandvars(cleaned))))
        os.environ[key] = cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load Agency Ops Memory V1 snapshots into BigQuery.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--monday-hub-root", default=str(SourcePaths().monday_hub), help="monday-agency-hub root.")
    parser.add_argument("--seo-automation-root", default=str(SourcePaths().seo_automation), help="SEO Automation root.")
    parser.add_argument("--seo-reporting-root", default=str(SourcePaths().seo_reporting), help="seo-reporting-platform root.")
    parser.add_argument("--big-query-root", default=str(SourcePaths().big_query), help="Big Query control folder root.")
    parser.add_argument("--local-dry-run", action="store_true", help="Parse local sources and print row counts only.")
    parser.add_argument("--ensure-only", action="store_true", help="Create/verify BigQuery datasets and tables only.")
    parser.add_argument("--skip-marts", action="store_true", help="Load memory tables but skip reporting mart SQL.")
    parser.add_argument(
        "--skip-health-verification-preflight",
        action="store_true",
        help="Skip strict client-health verification manifest preflight. Use only for diagnostics.",
    )
    parser.add_argument(
        "--write-disposition",
        default="WRITE_TRUNCATE",
        choices=("WRITE_TRUNCATE", "WRITE_APPEND"),
        help="BigQuery load write disposition. Default is full-refresh/truncate for idempotent V1 loads.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.load_env:
        load_env_file(Path(args.load_env))

    config = BigQueryCostConfig.from_file(args.config)
    paths = SourcePaths(
        monday_hub=Path(args.monday_hub_root),
        seo_automation=Path(args.seo_automation_root),
        seo_reporting=Path(args.seo_reporting_root),
        big_query=Path(args.big_query_root),
    )

    if not args.ensure_only and not args.skip_health_verification_preflight:
        preflight_args = [
            "validate_client_health_verifications.py",
            "--monday-hub-root",
            str(paths.monday_hub),
            "--seo-automation-root",
            str(paths.seo_automation),
            "--seo-reporting-root",
            str(paths.seo_reporting),
            "--big-query-root",
            str(paths.big_query),
        ]
        old_argv = sys.argv
        try:
            sys.argv = preflight_args
            preflight_status = validate_client_health_verifications_main()
        finally:
            sys.argv = old_argv
        if preflight_status != 0:
            print(
                "Client health verification preflight failed. Refresh Drive/API verification manifests or use "
                "--skip-health-verification-preflight for diagnostics only.",
                file=sys.stderr,
            )
            return 5

    if args.local_dry_run:
        run_id = "local-dry-run"
        ingested_at = utc_now_iso()
        rows_by_table = collect_agency_ops_rows(paths, run_id=run_id, ingested_at=ingested_at, snapshot_date=today_iso())
        print(
            json.dumps(
                {
                    "status": "parsed",
                    "sources": len(source_registry_rows(paths, ingested_at)),
                    "table_counts": {table: len(rows) for table, rows in sorted(rows_by_table.items())},
                },
                indent=2,
            )
        )
        return 0

    try:
        from google.cloud import bigquery
    except ModuleNotFoundError:
        print("google-cloud-bigquery is not installed. Run: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    client = bigquery.Client(project=config.project_id)
    ingestor = AgencyOpsBigQueryIngestor(client, config, paths)
    try:
        if args.ensure_only:
            ingestor.ensure_tables()
            print(json.dumps({"status": "ensured", "project": config.project_id}, indent=2))
            return 0
        summary = ingestor.run(write_disposition=args.write_disposition, build_marts=not args.skip_marts)
    except Exception as exc:
        print(f"Agency ops ingestion failed: {type(exc).__name__}: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 4

    print(
        json.dumps(
            {
                "status": summary.status,
                "run_id": summary.run_id,
                "table_counts": summary.table_counts,
                "mart_statuses": summary.mart_statuses,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
