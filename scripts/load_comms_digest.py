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
    build_comms_reporting_marts,
    parse_comms_summary_jsonl,
    utc_now_iso,
)
from agency_bigquery.capped_query_runner import CappedBigQueryRunner
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig
from agency_bigquery.schema import ensure_comms_memory_tables


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_RETENTION_MONTHS = 13


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
    parser = argparse.ArgumentParser(description="Validate and load summarized client comms memory JSONL into BigQuery.")
    parser.add_argument("--input-jsonl", required=True, help="Path to staged summary-only JSONL from the comms summarizer.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--run-id", default=None, help="Optional digest run ID. Defaults to a generated UUID hex.")
    parser.add_argument("--week-start", required=True, help="Digest week start date, YYYY-MM-DD.")
    parser.add_argument("--week-end", required=True, help="Digest week end date, YYYY-MM-DD.")
    parser.add_argument("--channels", default="monday,gmail,outlook", help="Comma-separated channels scanned.")
    parser.add_argument("--summarizer-agent", default="codex-comms-activity-digest", help="Agent/workflow that produced the summaries.")
    parser.add_argument("--summarizer-model", default="gpt-5.4-mini", help="Model that produced the summaries.")
    parser.add_argument("--retention-months", type=int, default=DEFAULT_RETENTION_MONTHS, help="Comms memory retention window.")
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


def build_run_row(
    *,
    run_id: str,
    created_at: str,
    loaded_at: str | None,
    week_start: str,
    week_end: str,
    channels: list[str],
    summarizer_agent: str,
    summarizer_model: str,
    status: str,
    source_event_count: int,
    summary_rows: int,
    rejected_rows: int,
    validation_errors: list[str],
    staging_path: Path,
    retention_months: int,
) -> dict:
    return {
        "run_id": run_id,
        "created_at": created_at,
        "loaded_at": loaded_at,
        "week_start": week_start,
        "week_end": week_end,
        "channels_json": channels,
        "summarizer_agent": summarizer_agent,
        "summarizer_model": summarizer_model,
        "status": status,
        "source_event_count": source_event_count,
        "summary_rows": summary_rows,
        "rejected_rows": rejected_rows,
        "validation_errors_json": validation_errors or None,
        "staging_path": str(staging_path),
        "retention_months": retention_months,
    }


def enforce_retention(runner: CappedBigQueryRunner, config: BigQueryCostConfig, retention_months: int) -> None:
    project = config.project_id
    memory = config.memory_dataset
    for table in ("client_comms_weekly_summaries", "client_comms_digest_runs"):
        sql = f"""
DELETE FROM `{project}.{memory}.{table}`
WHERE week_start < DATE_SUB(CURRENT_DATE(), INTERVAL {retention_months} MONTH)
"""
        runner.run_query(sql, purpose=f"comms-memory: enforce {retention_months}-month retention on {table}")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_jsonl)
    if not input_path.exists():
        print(f"Input JSONL does not exist: {input_path}", file=sys.stderr)
        return 2
    if args.retention_months < 1:
        print("--retention-months must be at least 1", file=sys.stderr)
        return 2

    run_id = args.run_id or uuid4().hex
    created_at = utc_now_iso()
    channels = [channel.strip().lower() for channel in args.channels.split(",") if channel.strip()]
    try:
        rows = parse_comms_summary_jsonl(
            input_path,
            run_id=run_id,
            created_at=created_at,
            default_week_start=args.week_start,
            default_week_end=args.week_end,
            default_summarizer_model=args.summarizer_model,
        )
    except ValueError as exc:
        print(json.dumps({"status": "validation_failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 3

    source_event_count = sum(int(row["source_event_count"]) for row in rows)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "validated",
                    "run_id": run_id,
                    "summary_rows": len(rows),
                    "source_event_count": source_event_count,
                    "week_start": args.week_start,
                    "week_end": args.week_end,
                    "channels": channels,
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
    ensure_comms_memory_tables(client, config)
    summaries_table = config.table_id(config.memory_dataset, "client_comms_weekly_summaries")
    runs_table = config.table_id(config.memory_dataset, "client_comms_digest_runs")

    loaded_rows = load_rows(client, summaries_table, rows, location=config.default_location)
    loaded_at = utc_now_iso()
    run_row = build_run_row(
        run_id=run_id,
        created_at=created_at,
        loaded_at=loaded_at,
        week_start=args.week_start,
        week_end=args.week_end,
        channels=channels,
        summarizer_agent=args.summarizer_agent,
        summarizer_model=args.summarizer_model,
        status="succeeded",
        source_event_count=source_event_count,
        summary_rows=loaded_rows,
        rejected_rows=0,
        validation_errors=[],
        staging_path=input_path,
        retention_months=args.retention_months,
    )
    load_rows(client, runs_table, [run_row], location=config.default_location)

    runner = CappedBigQueryRunner(client, config)
    enforce_retention(runner, config, args.retention_months)
    mart_statuses = build_comms_reporting_marts(runner, config)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "run_id": run_id,
                "summary_rows": loaded_rows,
                "source_event_count": source_event_count,
                "mart_statuses": {
                    "client_comms_attention": mart_statuses.get("client_comms_attention"),
                    "client_comms_history": mart_statuses.get("client_comms_history"),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
