#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agency_ops_ingestion import (
    build_roadmap_reporting_marts,
    parse_roadmap_item_jsonl,
    roadmap_source_rows_from_items,
    utc_now_iso,
)
from agency_bigquery.capped_query_runner import CappedBigQueryRunner
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig
from agency_bigquery.schema import ensure_roadmap_memory_tables


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
    parser = argparse.ArgumentParser(description="Validate and load sanitized client roadmap items into BigQuery.")
    parser.add_argument("--input-jsonl", required=True, help="Path to staged summary-only roadmap JSONL.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--run-id", default=None, help="Optional roadmap run ID. Defaults to a generated UUID hex.")
    parser.add_argument("--planned-month", help="Default planned month for rows without planned_month, YYYY-MM or YYYY-MM-DD.")
    parser.add_argument("--source-type", default="manual", help="Default source type for rows without source_type.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print counts without writing to BigQuery.")
    return parser.parse_args()


def load_rows(client, table_id: str, rows: list[dict], *, location: str, write_disposition: str = "WRITE_APPEND") -> int:
    if not rows:
        return 0
    from google.cloud import bigquery

    job_config = bigquery.LoadJobConfig(write_disposition=write_disposition)
    job = client.load_table_from_json(rows, table_id, job_config=job_config, location=location)
    job.result()
    return len(rows)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_jsonl)
    if not input_path.exists():
        print(f"Input JSONL does not exist: {input_path}", file=sys.stderr)
        return 2

    run_id = args.run_id or uuid4().hex
    ingested_at = utc_now_iso()
    try:
        items = parse_roadmap_item_jsonl(
            input_path,
            run_id=run_id,
            ingested_at=ingested_at,
            default_planned_month=args.planned_month,
            default_source_type=args.source_type,
        )
    except ValueError as exc:
        print(json.dumps({"status": "validation_failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 3

    sources = roadmap_source_rows_from_items(items)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "validated",
                    "run_id": run_id,
                    "roadmap_items": len(items),
                    "roadmap_sources": len(sources),
                    "clients": sorted({item["client_slug"] for item in items}),
                    "periods": sorted({item["period_id"] for item in items}),
                },
                indent=2,
            )
        )
        return 0

    if args.load_env:
        load_env_file(Path(args.load_env))

    try:
        from google.cloud import bigquery
    except ModuleNotFoundError:
        print("google-cloud-bigquery is not installed. Run: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    config = BigQueryCostConfig.from_file(args.config)
    client = bigquery.Client(project=config.project_id)
    ensure_roadmap_memory_tables(client, config)
    sources_table = config.table_id(config.memory_dataset, "client_roadmap_sources")
    items_table = config.table_id(config.memory_dataset, "client_roadmap_items")

    loaded_sources = load_rows(client, sources_table, sources, location=config.default_location)
    loaded_items = load_rows(client, items_table, items, location=config.default_location)

    runner = CappedBigQueryRunner(client, config)
    mart_statuses = build_roadmap_reporting_marts(runner, config)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "run_id": run_id,
                "roadmap_items": loaded_items,
                "roadmap_sources": loaded_sources,
                "mart_statuses": mart_statuses,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
