#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agent_logging import log_agent_output  # noqa: E402
from agency_bigquery.agent_ops import (  # noqa: E402
    build_agent_run_row,
    complete_agent_run_lifecycle,
    fail_agent_run_lifecycle,
    stable_hash,
    start_agent_run_lifecycle,
    utc_now_iso,
)
from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig, bytes_to_human  # noqa: E402
from agency_bigquery.specialist_agents import (  # noqa: E402
    SPECIALIST_AGENT_CONFIGS,
    context_pack_for_output,
    output_for_agent,
)


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_AGENT_RUN_INDEX = PROJECT_ROOT / "data" / "agent_runs" / "index.json"
DEFAULT_ACTIVE_RUN_DIR = PROJECT_ROOT / "data" / "agent_runs" / "active"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "system_admin"
EXPECTED_DATASETS = ("agency_control", "agency_staging", "agency_memory", "agency_reporting")
EXPECTED_TABLES = {
    "agency_control": ("cost_checks", "ingestion_runs"),
    "agency_memory": ("client_health_assets", "seo_client_memory_summaries"),
    "agency_reporting": ("client_health_check", "reporting_readiness", "ops_drift_summary"),
}


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
    parser = argparse.ArgumentParser(description="Run the read-only AgencyOS System Admin Agent.")
    parser.add_argument("--from-bigquery", action="store_true", help="Read live system health context through capped BigQuery queries.")
    parser.add_argument("--write-bigquery", action="store_true", help="Log validated run/context/findings/actions to BigQuery. BigQuery-context runs log on completion by default unless --dry-run is used.")
    parser.add_argument("--dry-run", action="store_true", help="Local/report-only mode. Use with --from-bigquery to read live context without writing completion metadata.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify operating tables before BigQuery logging.")
    parser.add_argument("--automation-id", default=os.environ.get("SEO_AGENCY_OS_AUTOMATION_ID"), help="Optional automation ID.")
    parser.add_argument("--run-id", default=None, help="Optional run ID. Defaults to a UUID hex.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--output-json", help="Output path for validated run JSON.")
    parser.add_argument("--output-md", help="Output path for markdown report.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows per live check area.")
    return parser.parse_args()


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_row(
    *,
    category: str,
    name: str,
    status: str,
    summary: str,
    source: str,
    details: dict | None = None,
    client_slug: str = "agency-system",
    finding_type: str | None = None,
    severity: str | None = None,
    recommended_action: str | None = None,
    observed_at: str | None = None,
    priority: str | None = None,
) -> dict:
    payload = {
        "client_slug": client_slug,
        "check_category": category,
        "check_name": name,
        "check_status": status,
        "summary": summary,
        "source": source,
        "details": details or {},
        "observed_at": observed_at,
        "finding_type": finding_type,
        "severity": severity,
        "recommended_action": recommended_action,
        "priority": priority,
    }
    payload["source_ref_hash"] = stable_hash(payload)
    return payload


def local_check_rows(config: BigQueryCostConfig, *, created_at: str) -> list[dict]:
    rows: list[dict] = []
    config_ok = (
        config.project_id == "seo-agency-work"
        and config.default_location == "australia-southeast1"
        and config.pricing_mode == "on_demand"
        and config.normal_query_cap_bytes <= 1_073_741_824
        and config.admin_override_query_cap_bytes <= 10_737_418_240
        and config.dry_run_required
    )
    rows.append(
        check_row(
            category="cost_guardrails",
            name="local_cost_config",
            status="ok" if config_ok else "failed",
            summary="Local BigQuery cost guardrail config matches the expected AgencyOS defaults."
            if config_ok
            else "Local BigQuery cost guardrail config differs from the expected AgencyOS defaults.",
            source="config/bigquery_cost_guardrails.json",
            details={
                "project_id": config.project_id,
                "default_location": config.default_location,
                "pricing_mode": config.pricing_mode,
                "normal_query_cap": bytes_to_human(config.normal_query_cap_bytes),
                "admin_query_cap": bytes_to_human(config.admin_override_query_cap_bytes),
                "dry_run_required": config.dry_run_required,
            },
            severity="high",
            recommended_action="Review config/bigquery_cost_guardrails.json before running live warehouse checks.",
            observed_at=created_at,
        )
    )

    if DEFAULT_AGENT_RUN_INDEX.exists():
        try:
            index = json.loads(DEFAULT_AGENT_RUN_INDEX.read_text(encoding="utf-8"))
            runs = index.get("runs") if isinstance(index, dict) else index
            run_count = len(runs) if isinstance(runs, list) else 0
            rows.append(
                check_row(
                    category="agent_runs",
                    name="local_run_index",
                    status="ok",
                    summary=f"Local agent run index is readable with {run_count} indexed run(s).",
                    source=str(DEFAULT_AGENT_RUN_INDEX.relative_to(PROJECT_ROOT)),
                    details={"runs": run_count},
                    observed_at=created_at,
                )
            )
            failed_recent = [
                run for run in (runs or [])
                if isinstance(run, dict) and str(run.get("status") or "").lower() == "failed"
            ][:10]
            for run in failed_recent:
                rows.append(
                    check_row(
                        category="agent_runs",
                        name=f"failed_run:{run.get('agent_id') or 'agent'}",
                        status="failed",
                        summary=f"{run.get('agent_id') or 'An agent'} has a failed indexed run that needs review.",
                        source=str(DEFAULT_AGENT_RUN_INDEX.relative_to(PROJECT_ROOT)),
                        details={
                            "run_id": run.get("run_id"),
                            "agent_id": run.get("agent_id"),
                            "started_at": run.get("started_at"),
                            "error_class": type(run.get("error_message")).__name__ if run.get("error_message") else None,
                        },
                        finding_type="system_admin_failed_agent_run",
                        severity="medium",
                        recommended_action="Review the indexed failed run output and rerun the affected dry-run workflow after fixing the cause.",
                        observed_at=run.get("completed_at") or run.get("started_at") or created_at,
                    )
                )
        except json.JSONDecodeError:
            rows.append(
                check_row(
                    category="agent_runs",
                    name="local_run_index",
                    status="failed",
                    summary="Local agent run index is not valid JSON.",
                    source=str(DEFAULT_AGENT_RUN_INDEX.relative_to(PROJECT_ROOT)),
                    severity="high",
                    recommended_action="Repair or regenerate data/agent_runs/index.json before relying on local agent activity.",
                    observed_at=created_at,
                )
            )
    else:
        rows.append(
            check_row(
                category="agent_runs",
                name="local_run_index",
                status="missing",
                summary="Local agent run index does not exist yet.",
                source=str(DEFAULT_AGENT_RUN_INDEX.relative_to(PROJECT_ROOT)),
                severity="low",
                recommended_action="Run an AgencyOS agent once to create the local run index.",
                observed_at=created_at,
            )
        )

    now = parse_datetime(created_at) or datetime.now()
    if DEFAULT_ACTIVE_RUN_DIR.exists():
        for marker_path in sorted(DEFAULT_ACTIVE_RUN_DIR.glob("*.json")):
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                marker = {"agent_id": marker_path.stem, "started_at": None}
            started = parse_datetime(marker.get("started_at"))
            stale = started is None or now - started.replace(tzinfo=now.tzinfo) > timedelta(hours=6)
            if stale:
                rows.append(
                    check_row(
                        category="agent_runs",
                        name=f"stale_active_marker:{marker.get('agent_id') or marker_path.stem}",
                        status="stale",
                        summary=f"Active run marker for {marker.get('agent_id') or marker_path.stem} appears stale or unreadable.",
                        source=str(marker_path.relative_to(PROJECT_ROOT)),
                        details={"run_id": marker.get("run_id"), "started_at": marker.get("started_at")},
                        finding_type="system_admin_stale_agent_marker",
                        severity="medium",
                        recommended_action="Inspect the active marker and confirm whether the run is still alive before deleting or rerunning anything.",
                        observed_at=marker.get("started_at") or created_at,
                    )
                )
    return rows


def read_bigquery_rows(config: BigQueryCostConfig, *, limit: int) -> list[dict]:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    project = config.project_id
    control = config.control_dataset
    reporting = config.reporting_dataset
    region = f"region-{config.default_location}"
    rows: list[dict] = []

    _, dataset_result = runner.run_query(
        f"""
SELECT schema_name
FROM `{project}.{region}`.INFORMATION_SCHEMA.SCHEMATA
WHERE schema_name IN ({", ".join(repr(item) for item in EXPECTED_DATASETS)})
ORDER BY schema_name
""",
        purpose="system-admin-agent: verify expected datasets",
    )
    present_datasets = {dict(row).get("schema_name") for row in dataset_result}
    for dataset in EXPECTED_DATASETS:
        rows.append(
            check_row(
                category="bigquery_schema",
                name=f"dataset:{dataset}",
                status="ok" if dataset in present_datasets else "missing",
                summary=f"BigQuery dataset {dataset} is present." if dataset in present_datasets else f"BigQuery dataset {dataset} is missing.",
                source=f"{project}.{region}.INFORMATION_SCHEMA.SCHEMATA",
                severity="high",
                recommended_action="Run the approved schema plan/ensure workflow only after reviewing the missing dataset.",
            )
        )

    _, table_result = runner.run_query(
        f"""
SELECT table_schema, table_name
FROM `{project}.{region}`.INFORMATION_SCHEMA.TABLES
WHERE table_schema IN ({", ".join(repr(item) for item in EXPECTED_TABLES)})
ORDER BY table_schema, table_name
""",
        purpose="system-admin-agent: verify expected tables",
    )
    present_tables = {(dict(row).get("table_schema"), dict(row).get("table_name")) for row in table_result}
    for dataset, table_names in EXPECTED_TABLES.items():
        for table_name in table_names:
            present = (dataset, table_name) in present_tables
            rows.append(
                check_row(
                    category="bigquery_schema",
                    name=f"table:{dataset}.{table_name}",
                    status="ok" if present else "missing",
                    summary=f"BigQuery table {dataset}.{table_name} is present." if present else f"BigQuery table {dataset}.{table_name} is missing.",
                    source=f"{project}.{region}.INFORMATION_SCHEMA.TABLES",
                    severity="high",
                    recommended_action="Review the missing table against the approved schema manager before creating or changing warehouse tables.",
                )
            )

    _, ingestion_result = runner.run_query(
        f"""
SELECT source_id, status, started_at, completed_at, rows_loaded, destination_table
FROM `{project}.{control}.ingestion_runs`
ORDER BY started_at DESC
LIMIT {int(limit)}
""",
        purpose="system-admin-agent: review recent ingestion runs",
    )
    ingestion_rows = [dict(row) for row in ingestion_result]
    if not ingestion_rows:
        rows.append(
            check_row(
                category="ingestion",
                name="recent_ingestion_runs",
                status="missing",
                summary="No recent ingestion run rows were found.",
                source=f"{project}.{control}.ingestion_runs",
                severity="high",
                recommended_action="Run the local dry-run parser, then an approved live ingestion only if the dry run passes.",
            )
        )
    for run in ingestion_rows[:25]:
        status = str(run.get("status") or "").lower()
        if status not in {"succeeded", "success", "completed"}:
            rows.append(
                check_row(
                    category="ingestion",
                    name=f"ingestion:{run.get('source_id')}",
                    status="failed",
                    summary=f"Recent ingestion run for {run.get('source_id')} finished with status {run.get('status')}.",
                    source=f"{project}.{control}.ingestion_runs",
                    details={"destination_table": run.get("destination_table"), "rows_loaded": run.get("rows_loaded")},
                    finding_type="system_admin_ingestion_gap",
                    severity="high",
                    recommended_action="Review the ingestion run locally and rerun the approved dry-run checks before any live reload.",
                    observed_at=str(run.get("completed_at") or run.get("started_at") or ""),
                )
            )

    _, cost_result = runner.run_query(
        f"""
SELECT logged_at, purpose, status, estimated_bytes, cap_bytes, admin_cap_10gb, error_class
FROM `{project}.{control}.{config.cost_checks_table}`
ORDER BY logged_at DESC
LIMIT {int(limit)}
""",
        purpose="system-admin-agent: review recent cost checks",
    )
    for row in [dict(item) for item in cost_result]:
        status = str(row.get("status") or "").lower()
        if status in {"blocked", "failed"}:
            rows.append(
                check_row(
                    category="cost_guardrails",
                    name=f"cost_check:{row.get('purpose')}",
                    status="over_cap" if status == "blocked" else "failed",
                    summary=f"Recent capped query for {row.get('purpose')} was {status}.",
                    source=f"{project}.{control}.{config.cost_checks_table}",
                    details={
                        "estimated_bytes": row.get("estimated_bytes"),
                        "cap_bytes": row.get("cap_bytes"),
                        "admin_cap_10gb": row.get("admin_cap_10gb"),
                        "error_class": row.get("error_class"),
                    },
                    finding_type="system_admin_cost_guardrail_event",
                    severity="high",
                    recommended_action="Treat blocked cost checks as a working guardrail; narrow the query or review the failed query path before rerunning.",
                    observed_at=str(row.get("logged_at") or ""),
                )
            )

    _, health_result = runner.run_query(
        f"""
SELECT client_slug, client_name, snapshot_date,
  has_drive_root, has_drive_root_verified,
  has_roadmap_route, has_roadmap_folder_verified, has_roadmap_files, has_roadmap_content_validated,
  has_ga4_property, has_ga4_access,
  has_search_console, has_search_console_access,
  has_se_ranking, has_se_ranking_access
FROM `{project}.{reporting}.client_health_check`
QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
ORDER BY client_slug
LIMIT {int(limit)}
""",
        purpose="system-admin-agent: review route versus verified health gaps",
    )
    health_rows = [dict(item) for item in health_result]
    if not health_rows:
        rows.append(
            check_row(
                category="dashboard_data_health",
                name="client_health_snapshot",
                status="missing",
                summary="The dashboard client-health query returned no latest snapshot rows.",
                source=f"{project}.{reporting}.client_health_check",
                severity="high",
                recommended_action="Review the latest agency-memory ingestion and reporting mart build before trusting dashboard health views.",
            )
        )
    else:
        latest_snapshot = max(str(row.get("snapshot_date") or "") for row in health_rows)
        rows.append(
            check_row(
                category="dashboard_data_health",
                name="client_health_snapshot",
                status="ok",
                summary=f"Dashboard client-health snapshot is available for {latest_snapshot}.",
                source=f"{project}.{reporting}.client_health_check",
                details={"latest_snapshot_date": latest_snapshot, "rows_checked": len(health_rows)},
                observed_at=latest_snapshot,
            )
        )
    for row in health_rows:
        route_gaps = []
        checks = (
            ("has_drive_root", "has_drive_root_verified", "Drive root metadata verification"),
            ("has_roadmap_route", "has_roadmap_folder_verified", "roadmap folder verification"),
            ("has_roadmap_files", "has_roadmap_content_validated", "roadmap content validation"),
            ("has_ga4_property", "has_ga4_access", "GA4 API access verification"),
            ("has_search_console", "has_search_console_access", "Search Console API access verification"),
            ("has_se_ranking", "has_se_ranking_access", "SE Ranking API access verification"),
        )
        for route_field, verified_field, label in checks:
            if row.get(route_field) is True and row.get(verified_field) is not True:
                route_gaps.append(label)
        if route_gaps:
            rows.append(
                check_row(
                    category="client_health",
                    name=f"route_verification:{row.get('client_slug')}",
                    status="warn",
                    summary=f"{row.get('client_name') or row.get('client_slug')} has route/config evidence that still needs verification: {', '.join(route_gaps)}.",
                    source=f"{project}.{reporting}.client_health_check",
                    details={"route_verification_gaps": route_gaps, "snapshot_date": row.get("snapshot_date")},
                    client_slug=str(row.get("client_slug") or "agency-system"),
                    finding_type="route_verification_gap",
                    severity="medium",
                    recommended_action="Run the relevant approved read-only verification workflow; do not treat route/config evidence as proven access or content health.",
                    observed_at=str(row.get("snapshot_date") or ""),
                )
            )

    return rows


def markdown_report(payload: dict, *, mode: str) -> str:
    output = payload["output"]
    run_log = payload["run_log"]
    findings = output.get("findings", [])
    metrics = output.get("metrics", {})
    lines = [
        f"# AgencyOS System Admin Sweep - {run_log.get('started_at')}",
        "",
        f"- Run ID: {run_log.get('run_id')}",
        f"- Mode: {mode}",
        f"- Findings: {len(findings)}",
        f"- Actions: {len(output.get('actions', []))}",
        f"- Rows reviewed: {metrics.get('rows_reviewed', 0)}",
        f"- Route verification gaps: {metrics.get('route_verification_gaps', 0)}",
        "",
        "## Findings",
    ]
    if not findings:
        lines.append("- No findings needing review.")
    else:
        for finding in findings:
            lines.append(
                f"- [{finding.get('severity')}] {finding.get('client_slug')}: "
                f"{finding.get('summary')} Recommended: {finding.get('recommended_action')}"
            )
    lines.extend(["", "## Safety", "- Read-only sweep. No repairs, external writes, publishing, moving, sharing, deleting, or credential changes were performed."])
    return "\n".join(lines) + "\n"


def run() -> int:
    args = parse_args()
    should_write_bigquery = (args.write_bigquery or args.from_bigquery) and not args.dry_run
    if should_write_bigquery and not args.from_bigquery:
        raise SystemExit("--write-bigquery requires --from-bigquery for system_admin_agent")
    run_id = args.run_id or uuid4().hex
    started_at = utc_now_iso()
    agent_config = SPECIALIST_AGENT_CONFIGS["system_admin_agent"]
    default_json_path = DEFAULT_OUTPUT_DIR / f"{run_id}.json"
    output_json = Path(args.output_json) if args.output_json else default_json_path
    output_md = Path(args.output_md) if args.output_md else output_json.with_suffix(".md")
    config = BigQueryCostConfig.from_file(args.config)
    mode = "local_context"

    start_agent_run_lifecycle(
        index_path=DEFAULT_AGENT_RUN_INDEX,
        active_dir=DEFAULT_ACTIVE_RUN_DIR,
        run_id=run_id,
        agent_id="system_admin_agent",
        automation_id=args.automation_id,
        agent_name=agent_config.agent_name,
        started_at=started_at,
        mode=mode,
        dry_run=not should_write_bigquery,
        prompt_version=agent_config.prompt_version,
        input_sources=["local_system_health"],
        output_path=str(output_json),
        run_json_path=str(output_json),
        brief_path=str(output_md),
    )

    try:
        if args.load_env:
            load_env_file(Path(args.load_env))

        rows = local_check_rows(config, created_at=started_at)
        if args.from_bigquery:
            rows.extend(read_bigquery_rows(config, limit=args.limit))
            mode = "bigquery"

        output = output_for_agent("system_admin_agent", rows, run_id=run_id, created_at=started_at)
        context_pack = context_pack_for_output(
            agent_id="system_admin_agent",
            run_id=run_id,
            created_at=started_at,
            rows=rows,
            output=output,
            client_slug=None,
        )
        run_row = build_agent_run_row(
            run_id=run_id,
            automation_id=args.automation_id,
            agent_id="system_admin_agent",
            agent_name=agent_config.agent_name,
            started_at=started_at,
            completed_at=utc_now_iso(),
            status="succeeded",
            mode=mode,
            prompt_version=agent_config.prompt_version,
            context_id=context_pack["context_id"],
            input_sources=context_pack["source_tables_json"],
            output_path=str(output_json),
            findings_count=len(output["findings"]),
            actions_count=len(output["actions"]),
            dry_run=not should_write_bigquery,
            bigquery_write_status="succeeded" if should_write_bigquery else "dry_run",
        )

        loaded = None
        if should_write_bigquery:
            from google.cloud import bigquery

            client = bigquery.Client(project=config.project_id)
            loaded = log_agent_output(
                client,
                config,
                run_row=run_row,
                findings=output["findings"],
                actions=output["actions"],
                context_pack=context_pack,
                dry_run=False,
                ensure_tables_first=args.ensure_tables,
                batch_id=run_id,
                purpose="system_admin_agent: log validated output",
            )

        payload = {
            "output": output,
            "run_log": {**run_row, "output_path": str(output_json)},
            "context_pack": context_pack,
            "check_rows": rows,
            "bigquery_loaded": loaded,
        }
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        output_md.write_text(markdown_report(payload, mode=mode), encoding="utf-8")

        complete_agent_run_lifecycle(
            index_path=DEFAULT_AGENT_RUN_INDEX,
            active_dir=DEFAULT_ACTIVE_RUN_DIR,
            run_row=run_row,
            output_path=str(output_json),
            run_json_path=str(output_json),
            brief_path=str(output_md),
            bigquery_logged=bool(loaded),
        )
    except Exception as exc:
        fail_agent_run_lifecycle(
            index_path=DEFAULT_AGENT_RUN_INDEX,
            active_dir=DEFAULT_ACTIVE_RUN_DIR,
            run_id=run_id,
            agent_id="system_admin_agent",
            agent_name=agent_config.agent_name,
            started_at=started_at,
            mode=mode,
            exc=exc,
            dry_run=not should_write_bigquery,
            automation_id=args.automation_id,
            prompt_version=agent_config.prompt_version,
            output_path=str(output_json),
            run_json_path=str(output_json),
            brief_path=str(output_md),
        )
        raise

    print(
        json.dumps(
            {
                "status": "succeeded",
                "run_id": run_id,
                "agent_id": "system_admin_agent",
                "dry_run": not should_write_bigquery,
                "mode": mode,
                "findings": len(output["findings"]),
                "actions": len(output["actions"]),
                "output_json": str(output_json),
                "output_md": str(output_md),
                "bigquery_loaded": loaded,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
