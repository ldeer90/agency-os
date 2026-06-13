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

from agency_bigquery.agent_ops import (  # noqa: E402
    agent_run_activity_entry,
    build_agent_run_row,
    load_agent_permissions,
    mark_agent_run_completed,
    mark_agent_run_started,
    promise_tracker_output,
    utc_now_iso,
    validate_permissions_safe_default,
)
from agency_bigquery.agent_logging import log_agent_output  # noqa: E402
from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_STAGING_DIR = PROJECT_ROOT / "data" / "comms_memory" / "staging"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "agent_runs" / "promise_tracker"
DEFAULT_AGENT_RUN_INDEX = PROJECT_ROOT / "data" / "agent_runs" / "index.json"
DEFAULT_ACTIVE_RUN_DIR = PROJECT_ROOT / "data" / "agent_runs" / "active"


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Env file does not exist: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key not in SAFE_ENV_KEYS:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if key == "GOOGLE_APPLICATION_CREDENTIALS":
            credential_path = Path(os.path.expanduser(os.path.expandvars(cleaned)))
            if not credential_path.is_absolute():
                credential_path = path.parent / credential_path
            cleaned = str(credential_path.resolve())
        os.environ[key] = cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the dry-run SEO Agency OS Promise Tracker.")
    parser.add_argument("--input-jsonl", action="append", help="Local summarized comms JSONL. Defaults to the latest staged file.")
    parser.add_argument("--from-bigquery", action="store_true", help="Read summarized comms from agency_reporting.client_comms_attention through the capped runner.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--permissions", default=str(PROJECT_ROOT / "config" / "permissions.yaml"), help="Path to permissions YAML.")
    parser.add_argument("--run-id", default=None, help="Optional run ID. Defaults to a UUID hex.")
    parser.add_argument("--automation-id", default=os.environ.get("SEO_AGENCY_OS_AUTOMATION_ID"), help="Optional automation/workflow ID to carry into local run metadata.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum summarized comms rows to review.")
    parser.add_argument("--output-json", help="Output path. Defaults to data/agent_runs/promise_tracker/<run_id>.json.")
    parser.add_argument("--write-bigquery", action="store_true", help="Explicitly log validated run/findings/actions to BigQuery.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify agent operating tables before BigQuery logging.")
    parser.add_argument("--allow-local-context-live-log", action="store_true", help="Allow BigQuery logging from local JSONL context for controlled tests.")
    return parser.parse_args()


def latest_staging_files() -> list[Path]:
    if not DEFAULT_STAGING_DIR.exists():
        return []
    files = sorted(DEFAULT_STAGING_DIR.glob("client_comms_weekly_summaries_*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:1]


def read_jsonl(paths: list[Path], limit: int) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{path}: line {line_number}: invalid JSON: {exc}") from exc
                row.setdefault("source", str(path))
                row.setdefault("source_table", "local_staged_comms_summary")
                rows.append(row)
                if len(rows) >= limit:
                    return rows
    return rows


def read_bigquery_rows(config: BigQueryCostConfig, *, limit: int):
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    sql = f"""
SELECT
  week_start,
  week_end,
  client_slug,
  client_name,
  channel,
  category,
  summary,
  recommended_action,
  owner_hint,
  due_hint,
  signal_type IN ('waiting_on_us', 'stale_followup') AS needs_reply,
  signal_type = 'client_blocker' AS blocked,
  signal_type = 'waiting_on_client' AS waiting_on_client,
  signal_type = 'waiting_on_us' AS waiting_on_us,
  signal_type = 'stale_followup' AS stale_followup,
  severity AS urgency,
  CAST(NULL AS STRING) AS sentiment,
  source_event_count,
  thread_ref_hash,
  thread_status,
  latest_event_at,
  'agency_reporting.client_comms_attention' AS source_table
FROM `{config.project_id}.{config.reporting_dataset}.client_comms_attention`
ORDER BY week_start DESC, CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, client_slug
LIMIT {int(limit)}
"""
    _, rows = runner.run_query(sql, purpose="promise-tracker: read summarized comms attention")
    return [dict(row) for row in rows]


def write_bigquery_output(config: BigQueryCostConfig, output: dict, run_row: dict, *, ensure_tables: bool) -> dict:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    return log_agent_output(
        client,
        config,
        run_row=run_row,
        findings=output["findings"],
        actions=output["actions"],
        dry_run=False,
        ensure_tables_first=ensure_tables,
        batch_id=run_row["run_id"],
        purpose="promise-tracker: log validated operating output",
    )


def main() -> int:
    args = parse_args()
    permissions = load_agent_permissions(Path(args.permissions))
    validate_permissions_safe_default(permissions)
    if args.write_bigquery and not args.from_bigquery and not args.allow_local_context_live_log:
        raise SystemExit("--write-bigquery requires --from-bigquery, or --allow-local-context-live-log for controlled local tests")
    run_id = args.run_id or uuid4().hex
    started_at = utc_now_iso()
    automation_id = args.automation_id

    if args.load_env:
        load_env_file(Path(args.load_env))
    config = BigQueryCostConfig.from_file(args.config)

    if args.from_bigquery:
        comms_rows = read_bigquery_rows(config, limit=args.limit)
        input_sources = ["agency_reporting.client_comms_attention"]
        mode = "bigquery"
    else:
        input_paths = [Path(path) for path in args.input_jsonl] if args.input_jsonl else latest_staging_files()
        if not input_paths:
            raise SystemExit(f"No input JSONL files found in {DEFAULT_STAGING_DIR}")
        comms_rows = read_jsonl(input_paths, args.limit)
        input_sources = [str(path) for path in input_paths]
        mode = "local_jsonl"

    output_path = Path(args.output_json) if args.output_json else DEFAULT_OUTPUT_DIR / f"{run_id}.json"
    mark_agent_run_started(
        DEFAULT_AGENT_RUN_INDEX,
        DEFAULT_ACTIVE_RUN_DIR,
        agent_run_activity_entry(
            run_id=run_id,
            automation_id=automation_id,
            agent_id="promise_tracker",
            agent_name="Promise Tracker",
            started_at=started_at,
            status="running",
            mode=mode,
            prompt_version="promise_tracker/v001",
            input_sources=input_sources,
            output_path=str(output_path),
            run_json_path=str(output_path),
            dry_run=not args.write_bigquery,
        ),
    )

    output = promise_tracker_output(comms_rows, run_id=run_id, created_at=started_at, limit=args.limit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True, default=str), encoding="utf-8")

    completed_at = utc_now_iso()
    run_row = build_agent_run_row(
        run_id=run_id,
        agent_id="promise_tracker",
        agent_name="Promise Tracker",
        started_at=started_at,
        completed_at=completed_at,
        status="succeeded",
        mode=mode,
        prompt_version="promise_tracker/v001",
        context_id=None,
        input_sources=input_sources,
        output_path=str(output_path),
        findings_count=len(output["findings"]),
        actions_count=len(output["actions"]),
        dry_run=not args.write_bigquery,
        automation_id=automation_id,
        bigquery_write_status="succeeded" if args.write_bigquery else "dry_run",
    )
    output["run_log"] = run_row
    output["automation_id"] = automation_id
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True, default=str), encoding="utf-8")

    loaded = None
    if args.write_bigquery:
        if not permissions.allow_bigquery_logging:
            raise SystemExit("BigQuery logging is disabled in permissions.yaml")
        loaded = write_bigquery_output(config, output, run_row, ensure_tables=args.ensure_tables)
    mark_agent_run_completed(
        DEFAULT_AGENT_RUN_INDEX,
        DEFAULT_ACTIVE_RUN_DIR,
        agent_run_activity_entry(
            run_id=run_id,
            automation_id=automation_id,
            agent_id="promise_tracker",
            agent_name="Promise Tracker",
            started_at=started_at,
            completed_at=completed_at,
            status="succeeded",
            mode=mode,
            prompt_version="promise_tracker/v001",
            input_sources=input_sources,
            output_path=str(output_path),
            run_json_path=str(output_path),
            findings_count=len(output["findings"]),
            actions_count=len(output["actions"]),
            dry_run=not args.write_bigquery,
            bigquery_logged=bool(loaded),
        ),
    )

    print(
        json.dumps(
            {
                "status": "succeeded",
                "run_id": run_id,
                "automation_id": automation_id,
                "dry_run": not args.write_bigquery,
                "rows_reviewed": output["metrics"]["rows_reviewed"],
                "promises_found": output["metrics"]["promises_found"],
                "actions_suggested": output["metrics"]["actions_suggested"],
                "output_json": str(output_path),
                "bigquery_loaded": loaded,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
