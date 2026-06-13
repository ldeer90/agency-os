#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agent_ops import (  # noqa: E402
    agent_activity_for_date,
    agent_run_activity_entry,
    build_agent_run_row,
    build_context_pack,
    daily_brief_markdown,
    load_agent_permissions,
    mark_agent_run_completed,
    mark_agent_run_started,
    normalize_action,
    normalize_finding,
    promise_tracker_output,
    task_hygiene_issues,
    utc_now_iso,
    validate_agent_output,
    validate_permissions_safe_default,
)
from agency_bigquery.agent_logging import log_agent_output  # noqa: E402
from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.seo_automation_catalog import (  # noqa: E402
    build_client_memory_summary_rows,
    client_readiness_rows,
    opportunity_rows_from_context,
)


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_COMMS_STAGING_DIR = PROJECT_ROOT / "data" / "comms_memory" / "staging"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "daily"
DEFAULT_RUN_DIR = PROJECT_ROOT / "data" / "agent_runs" / "agency_supervisor"
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
    parser = argparse.ArgumentParser(description="Run the dry-run SEO Agency OS Daily Agency Brief.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Brief date, YYYY-MM-DD.")
    parser.add_argument("--from-bigquery", action="store_true", help="Read operating context from reporting marts through the capped runner.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--permissions", default=str(PROJECT_ROOT / "config" / "permissions.yaml"), help="Path to permissions YAML.")
    parser.add_argument("--promise-json", help="Existing Promise Tracker output JSON.")
    parser.add_argument("--client-health-json", help="Local client health rows JSON for dry-run/testing.")
    parser.add_argument("--delivery-json", help="Local delivery rows JSON for dry-run/testing.")
    parser.add_argument("--output-md", help="Markdown output path. Defaults to reports/daily/YYYY-MM-DD-agency-brief.md.")
    parser.add_argument("--run-id", default=None, help="Optional run ID. Defaults to a UUID hex.")
    parser.add_argument("--automation-id", default=os.environ.get("SEO_AGENCY_OS_AUTOMATION_ID"), help="Optional automation/workflow ID to carry into local run metadata.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows per input area.")
    parser.add_argument("--write-bigquery", action="store_true", help="Explicitly log validated run/context/findings/actions to BigQuery.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify agent operating tables before BigQuery logging.")
    parser.add_argument("--allow-local-context-live-log", action="store_true", help="Allow BigQuery logging from local context files for controlled tests.")
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_comms_staging_file() -> Path | None:
    if not DEFAULT_COMMS_STAGING_DIR.exists():
        return None
    files = sorted(DEFAULT_COMMS_STAGING_DIR.glob("client_comms_weekly_summaries_*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def read_jsonl(path: Path, limit: int) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}: line {line_number}: invalid JSON: {exc}") from exc
            row.setdefault("source_table", "local_staged_comms_summary")
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def read_bigquery_context(config: BigQueryCostConfig, *, limit: int) -> dict[str, list[dict]]:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    project = config.project_id
    reporting = config.reporting_dataset
    queries = {
        "client_health": f"""
SELECT snapshot_date, client_slug, client_name, health_status, health_score, critical_missing_assets, missing_required_assets, missing_required_json
FROM `{project}.{reporting}.client_health_check`
QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
ORDER BY CASE health_status WHEN 'critical_missing' THEN 1 WHEN 'needs_attention' THEN 2 WHEN 'partial' THEN 3 ELSE 4 END, client_slug
LIMIT {int(limit)}
""",
        "delivery_items": f"""
SELECT snapshot_date, client_slug, board_name, group_title, item_name, status, normalized_status, owner, due_date
FROM `{project}.{reporting}.client_task_status`
WHERE COALESCE(normalized_status, 'Not Started') != 'Done'
  AND (
    due_date IS NULL
    OR due_date < CURRENT_DATE()
    OR owner IS NULL
    OR client_slug IS NULL
  )
ORDER BY due_date IS NULL, due_date, client_slug, item_name
LIMIT {int(limit)}
""",
        "comms": f"""
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
FROM `{project}.{reporting}.client_comms_attention`
ORDER BY week_start DESC, CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, client_slug
LIMIT {int(limit)}
""",
        "seo_readiness": f"""
SELECT generated_at, client_slug, client_name, readiness_status, missing_inputs_json, recommended_workflow_id, recommended_agent_id, evidence_json
FROM `{project}.{reporting}.seo_workflow_readiness`
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug, source_ref_hash ORDER BY generated_at DESC) = 1
ORDER BY CASE readiness_status WHEN 'blocked' THEN 1 WHEN 'needs_attention' THEN 2 ELSE 3 END, client_slug
LIMIT {int(limit)}
""",
        "seo_opportunities": f"""
SELECT generated_at, client_slug, client_name, opportunity_type, workflow_id, priority, summary, recommended_action, evidence_json
FROM `{project}.{reporting}.seo_opportunity_queue`
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug, workflow_id, source_ref_hash ORDER BY generated_at DESC) = 1
ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, client_slug, workflow_id
LIMIT {int(limit)}
""",
        "seo_workflow_summaries": f"""
SELECT completed_at, client_slug, workflow_id, agent_id, status, summary
FROM `{project}.{config.memory_dataset}.seo_workflow_run_summaries`
ORDER BY completed_at DESC, client_slug, workflow_id
LIMIT {int(limit)}
""",
    }
    context: dict[str, list[dict]] = {}
    for key, sql in queries.items():
        _, rows = runner.run_query(sql, purpose=f"daily-agency-brief: read {key}")
        context[key] = [dict(row) for row in rows]
    return context


def local_context(args: argparse.Namespace) -> dict[str, list[dict]]:
    client_health = read_json(Path(args.client_health_json)) if args.client_health_json else []
    delivery_items = read_json(Path(args.delivery_json)) if args.delivery_json else []
    comms_file = latest_comms_staging_file()
    comms = read_jsonl(comms_file, args.limit) if comms_file else []
    seo_client_rows = build_client_memory_summary_rows(run_id=args.run_id or "local-daily-brief")
    seo_readiness = client_readiness_rows(seo_client_rows)
    seo_opportunities = opportunity_rows_from_context(client_rows=seo_client_rows)
    return {
        "client_health": client_health,
        "delivery_items": delivery_items,
        "comms": comms,
        "seo_readiness": seo_readiness,
        "seo_opportunities": seo_opportunities,
        "seo_workflow_summaries": [],
    }


def daily_findings_and_actions(context: dict[str, list[dict]], *, run_id: str, created_at: str) -> tuple[list[dict], list[dict]]:
    findings: list[dict] = []
    actions: list[dict] = []
    for row in context.get("client_health", []):
        if not row.get("client_slug"):
            continue
        status = str(row.get("health_status") or "").lower()
        if status not in {"critical_missing", "needs_attention", "partial", "red", "amber"}:
            continue
        evidence = [{"source": "agency_reporting.client_health_check", "client_slug": row.get("client_slug"), "snapshot_date": row.get("snapshot_date"), "health_status": row.get("health_status")}]
        finding = normalize_finding(
            {
                "client_slug": row.get("client_slug"),
                "finding_type": "client_health",
                "severity": "high" if status == "critical_missing" else "medium",
                "summary": f"Client health needs attention: {row.get('health_status')}",
                "evidence": evidence,
                "source_tables": ["agency_reporting.client_health_check"],
                "recommended_action": "Review missing client health assets before relying on this client in daily workflows.",
                "confidence_score": 0.85,
                "qa_status": "needs_review",
            },
            run_id=run_id,
            agent_id="agency_supervisor",
            created_at=created_at,
        )
        action = normalize_action(
            {
                "client_slug": row.get("client_slug"),
                "finding_id": finding["finding_id"],
                "action_type": "client_health_review",
                "target_system": "codex",
                "recommended_action": "Review and backfill missing client health assets.",
                "priority": "high" if status == "critical_missing" else "medium",
                "status": "suggested",
                "requires_approval": False,
                "evidence": evidence,
            },
            run_id=run_id,
            agent_id="agency_supervisor",
            created_at=created_at,
        )
        findings.append(finding)
        actions.append(action)

    hygiene_by_client: dict[str, list[dict]] = defaultdict(list)
    for row in context.get("delivery_items", []):
        hygiene_issues = task_hygiene_issues(row, today=date.today())
        if not hygiene_issues:
            continue
        client_slug = row.get("client_slug") or "unmapped-monday"
        hygiene_by_client[str(client_slug)].append({**row, "hygiene_issues": hygiene_issues})

    for client_slug, rows in sorted(hygiene_by_client.items()):
        issue_counts = Counter(issue for row in rows for issue in row["hygiene_issues"])
        top_issues = ", ".join(f"{issue}={count}" for issue, count in issue_counts.most_common(5))
        examples = [
            {
                "item_name": row.get("item_name"),
                "due_date": row.get("due_date"),
                "status": row.get("normalized_status") or row.get("status"),
                "hygiene_issues": row["hygiene_issues"],
            }
            for row in rows[:5]
        ]
        evidence = [
            {
                "source": "agency_reporting.client_task_status",
                "client_slug": client_slug,
                "task_count": len(rows),
                "issue_counts": dict(issue_counts),
                "examples": examples,
            }
        ]
        finding = normalize_finding(
            {
                "client_slug": client_slug,
                "finding_type": "monday_hygiene",
                "severity": "medium" if any(issue in issue_counts for issue in ("missing_client_mapping", "stale_or_overdue_due_date", "non_client_board_mapping")) else "low",
                "summary": f"Possible Monday hygiene issues across {len(rows)} task row(s): {top_issues}",
                "evidence": evidence,
                "source_tables": ["agency_reporting.client_task_status"],
                "recommended_action": "Review grouped Monday task metadata before treating these rows as delivery risk.",
                "confidence_score": 0.9,
                "qa_status": "needs_review",
            },
            run_id=run_id,
            agent_id="agency_supervisor",
            created_at=created_at,
        )
        action = normalize_action(
            {
                "client_slug": client_slug,
                "finding_id": finding["finding_id"],
                "action_type": "monday_hygiene_review",
                "target_system": "codex",
                "recommended_action": "Review grouped Monday hygiene issues and decide whether source tasks need cleanup.",
                "priority": "medium" if finding["severity"] == "medium" else "low",
                "status": "needs_review",
                "requires_approval": False,
                "evidence": evidence,
            },
            run_id=run_id,
            agent_id="agency_supervisor",
            created_at=created_at,
        )
        findings.append(finding)
        actions.append(action)
    return findings, actions


def write_bigquery_output(config: BigQueryCostConfig, output: dict, run_row: dict, context_pack: dict, *, ensure_tables: bool) -> dict:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    return log_agent_output(
        client,
        config,
        run_row=run_row,
        context_pack=context_pack,
        findings=output["findings"],
        actions=output["actions"],
        dry_run=False,
        ensure_tables_first=ensure_tables,
        batch_id=run_row["run_id"],
        purpose="daily-agency-brief: log validated operating output",
    )


def main() -> int:
    args = parse_args()
    permissions = load_agent_permissions(Path(args.permissions))
    validate_permissions_safe_default(permissions)
    if args.write_bigquery and not args.from_bigquery and not args.allow_local_context_live_log:
        raise SystemExit("--write-bigquery requires --from-bigquery, or --allow-local-context-live-log for controlled local tests")
    brief_date = date.fromisoformat(args.date)
    run_id = args.run_id or uuid4().hex
    started_at = utc_now_iso()
    automation_id = args.automation_id
    mode = "bigquery" if args.from_bigquery else "local_context"
    output_md = Path(args.output_md) if args.output_md else DEFAULT_OUTPUT_DIR / f"{brief_date.isoformat()}-agency-brief.md"
    run_json = DEFAULT_RUN_DIR / f"{run_id}.json"

    if args.load_env:
        load_env_file(Path(args.load_env))
    config = BigQueryCostConfig.from_file(args.config)
    mark_agent_run_started(
        DEFAULT_AGENT_RUN_INDEX,
        DEFAULT_ACTIVE_RUN_DIR,
        agent_run_activity_entry(
            run_id=run_id,
            automation_id=automation_id,
            agent_id="agency_supervisor",
            agent_name="Agency Supervisor",
            started_at=started_at,
            status="running",
            mode=mode,
            prompt_version="agency_supervisor/v001",
            input_sources=[
                "agency_reporting.client_health_check",
                "agency_reporting.client_task_status",
                "agency_reporting.client_comms_attention",
            ],
            output_path=str(output_md),
            run_json_path=str(run_json),
            brief_path=str(output_md),
            dry_run=not args.write_bigquery,
        ),
    )

    context = read_bigquery_context(config, limit=args.limit) if args.from_bigquery else local_context(args)
    if args.promise_json:
        promise_output = read_json(Path(args.promise_json))
    else:
        promise_output = promise_tracker_output(context.get("comms", []), run_id=run_id, created_at=started_at, limit=args.limit)

    daily_findings, daily_actions = daily_findings_and_actions(context, run_id=run_id, created_at=started_at)
    output = validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "agency_supervisor",
            "created_at": started_at,
            "summary": "Daily agency brief generated from approved operating context.",
            "findings": [*daily_findings, *promise_output.get("findings", [])],
            "actions": [*daily_actions, *promise_output.get("actions", [])],
        }
    )
    context_pack = build_context_pack(
        agent_id="agency_supervisor",
        run_id=run_id,
        created_at=started_at,
        task_type="daily_agency_brief",
        source_tables=[
            "agency_reporting.client_health_check",
            "agency_reporting.client_task_status",
            "agency_reporting.client_comms_attention",
            "agency_reporting.seo_workflow_readiness",
            "agency_reporting.seo_opportunity_queue",
            "agency_memory.seo_workflow_run_summaries",
        ],
        sections={
            "client_health": context.get("client_health", []),
            "delivery_items": context.get("delivery_items", []),
            "seo_readiness": context.get("seo_readiness", []),
            "seo_opportunities": context.get("seo_opportunities", []),
            "promise_summary": promise_output.get("metrics", {}),
            "agent_summary": {"findings": len(output["findings"]), "actions": len(output["actions"])},
        },
    )

    completed_at = utc_now_iso()
    run_row = build_agent_run_row(
        run_id=run_id,
        automation_id=automation_id,
        agent_id="agency_supervisor",
        agent_name="Agency Supervisor",
        started_at=started_at,
        completed_at=completed_at,
        status="succeeded",
        mode=mode,
        prompt_version="agency_supervisor/v001",
        context_id=context_pack["context_id"],
        input_sources=context_pack["source_tables_json"],
        output_path=str(output_md),
        findings_count=len(output["findings"]),
        actions_count=len(output["actions"]),
        dry_run=not args.write_bigquery,
        bigquery_write_status="succeeded" if args.write_bigquery else "dry_run",
    )
    output["run_log"] = run_row
    output["context_pack"] = context_pack
    output["automation_id"] = automation_id

    loaded = None
    if args.write_bigquery:
        if not permissions.allow_bigquery_logging:
            raise SystemExit("BigQuery logging is disabled in permissions.yaml")
        loaded = write_bigquery_output(config, output, run_row, context_pack, ensure_tables=args.ensure_tables)
    mark_agent_run_completed(
        DEFAULT_AGENT_RUN_INDEX,
        DEFAULT_ACTIVE_RUN_DIR,
        agent_run_activity_entry(
            run_id=run_id,
            automation_id=automation_id,
            agent_id="agency_supervisor",
            agent_name="Agency Supervisor",
            started_at=started_at,
            completed_at=completed_at,
            status="succeeded",
            mode=mode,
            prompt_version="agency_supervisor/v001",
            context_id=context_pack["context_id"],
            input_sources=context_pack["source_tables_json"],
            output_path=str(output_md),
            run_json_path=str(run_json),
            brief_path=str(output_md),
            findings_count=len(output["findings"]),
            actions_count=len(output["actions"]),
            dry_run=not args.write_bigquery,
            bigquery_logged=bool(loaded),
        ),
    )
    activity = agent_activity_for_date(DEFAULT_AGENT_RUN_INDEX, DEFAULT_ACTIVE_RUN_DIR, brief_date)
    markdown = daily_brief_markdown(
        brief_date=brief_date,
        client_health=context.get("client_health", []),
        delivery_items=context.get("delivery_items", []),
        promise_output=promise_output,
        recent_findings=daily_findings,
        recent_actions=daily_actions,
        seo_readiness=context.get("seo_readiness", []),
        seo_opportunities=context.get("seo_opportunities", []),
        seo_workflow_summaries=context.get("seo_workflow_summaries", []),
        activity=activity,
    )
    output["activity"] = activity
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(markdown, encoding="utf-8")
    run_json.parent.mkdir(parents=True, exist_ok=True)
    run_json.write_text(json.dumps(output, indent=2, sort_keys=True, default=str), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "succeeded",
                "run_id": run_id,
                "automation_id": automation_id,
                "dry_run": not args.write_bigquery,
                "brief": str(output_md),
                "run_json": str(run_json),
                "findings": len(output["findings"]),
                "actions": len(output["actions"]),
                "bigquery_loaded": loaded,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
