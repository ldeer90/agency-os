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

from agency_bigquery.agent_logging import log_agent_output, log_langfuse_trace_link  # noqa: E402
from agency_bigquery.agent_ops import (  # noqa: E402
    build_agent_run_row,
    build_context_pack,
    complete_agent_run_lifecycle,
    fail_agent_run_lifecycle,
    start_agent_run_lifecycle,
    utc_now_iso,
)
from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.langfuse_tracing import (  # noqa: E402
    LANGFUSE_BASE_URL_ENV,
    LANGFUSE_CAPTURE_PAYLOADS_ENV,
    LANGFUSE_ENABLED_ENV,
    LANGFUSE_HOST_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
    emit_agent_trace,
)
from agency_bigquery.seo_automation_catalog import (  # noqa: E402
    DEFAULT_SEO_AUTOMATION_ROOT,
    build_client_memory_summary_rows,
    build_workflow_catalog_rows,
    seo_workflow_router_output,
)


SAFE_ENV_KEYS = {
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    LANGFUSE_BASE_URL_ENV,
    LANGFUSE_CAPTURE_PAYLOADS_ENV,
    LANGFUSE_ENABLED_ENV,
    LANGFUSE_HOST_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
}
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "agent_runs" / "seo_workflow_router"
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
    parser = argparse.ArgumentParser(description="Route a request to a safe SEO Automation workflow wrapper.")
    parser.add_argument("--request", default="Review SEO Automation workflow readiness and suggest next actions.", help="Request text to route.")
    parser.add_argument("--seo-automation-root", default=str(DEFAULT_SEO_AUTOMATION_ROOT), help="SEO Automation repo root for local dry-runs.")
    parser.add_argument("--from-bigquery", action="store_true", help="Read catalog/client memory from BigQuery through the capped runner.")
    parser.add_argument("--write-bigquery", action="store_true", help="Log validated findings/actions/run/context to BigQuery. BigQuery-context runs log on completion by default unless --dry-run is used.")
    parser.add_argument("--dry-run", action="store_true", help="Local/report-only mode. Use with --from-bigquery to read live context without writing completion metadata.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify operating tables before BigQuery logging.")
    parser.add_argument("--automation-id", default=os.environ.get("SEO_AGENCY_OS_AUTOMATION_ID"), help="Optional automation ID.")
    parser.add_argument("--client-slug", help="Limit routing to one client slug.")
    parser.add_argument("--run-id", default=None, help="Optional run ID. Defaults to a UUID hex.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows to read per input table.")
    parser.add_argument("--output-json", help="Output path for validated run JSON.")
    return parser.parse_args()


def read_bigquery_rows(config: BigQueryCostConfig, *, limit: int, client_slug: str | None) -> tuple[list[dict], list[dict]]:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    workflow_sql = f"""
SELECT *
FROM `{config.project_id}.{config.memory_dataset}.seo_workflow_catalog`
WHERE active = TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY workflow_id ORDER BY synced_at DESC) = 1
ORDER BY family, workflow_id
LIMIT {int(limit)}
"""
    client_filter = f"WHERE client_slug = '{client_slug.replace(chr(39), '')}'" if client_slug else ""
    client_sql = f"""
SELECT *
FROM `{config.project_id}.{config.memory_dataset}.seo_client_memory_summaries`
{client_filter}
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY synced_at DESC) = 1
ORDER BY client_slug
LIMIT {int(limit)}
"""
    _, workflow_rows = runner.run_query(workflow_sql, purpose="seo-workflow-router: read workflow catalog")
    _, client_rows = runner.run_query(client_sql, purpose="seo-workflow-router: read client memory summaries")
    return [dict(row) for row in workflow_rows], [dict(row) for row in client_rows]


def main() -> int:
    args = parse_args()
    should_write_bigquery = (args.write_bigquery or args.from_bigquery) and not args.dry_run
    if should_write_bigquery and not args.from_bigquery:
        raise SystemExit("--write-bigquery requires --from-bigquery for SEO workflow router")
    run_id = args.run_id or uuid4().hex
    started_at = utc_now_iso()
    config = BigQueryCostConfig.from_file(args.config)
    mode = "bigquery" if args.from_bigquery else "local_context"
    output_path = Path(args.output_json) if args.output_json else DEFAULT_OUTPUT_DIR / f"{run_id}.json"

    start_agent_run_lifecycle(
        index_path=DEFAULT_AGENT_RUN_INDEX,
        active_dir=DEFAULT_ACTIVE_RUN_DIR,
        run_id=run_id,
        agent_id="seo_workflow_router",
        automation_id=args.automation_id,
        agent_name="SEO Workflow Router",
        started_at=started_at,
        mode=mode,
        dry_run=not should_write_bigquery,
        prompt_version="seo_workflow_router/v001",
        input_sources=["agency_memory.seo_workflow_catalog", "agency_memory.seo_client_memory_summaries"],
        output_path=str(output_path),
        run_json_path=str(output_path),
    )

    try:
        if args.load_env:
            load_env_file(Path(args.load_env))
        if args.from_bigquery:
            workflow_rows, client_rows = read_bigquery_rows(config, limit=args.limit, client_slug=args.client_slug)
        else:
            workflow_rows = build_workflow_catalog_rows(root=Path(args.seo_automation_root), run_id=run_id)
            client_rows = build_client_memory_summary_rows(root=Path(args.seo_automation_root), run_id=run_id, only_client_slug=args.client_slug)
        output = seo_workflow_router_output(
            request_text=args.request,
            workflow_rows=workflow_rows,
            client_rows=client_rows,
            run_id=run_id,
            created_at=started_at,
            client_slug=args.client_slug,
        )
        context_pack = build_context_pack(
            agent_id="seo_workflow_router",
            run_id=run_id,
            created_at=started_at,
            task_type="seo_workflow_routing",
            source_tables=["agency_memory.seo_workflow_catalog", "agency_memory.seo_client_memory_summaries"],
            client_slug=args.client_slug,
            sections={"request": args.request, "metrics": output.get("metrics", {})},
        )
        run_row = build_agent_run_row(
            run_id=run_id,
            automation_id=args.automation_id,
            agent_id="seo_workflow_router",
            agent_name="SEO Workflow Router",
            started_at=started_at,
            completed_at=utc_now_iso(),
            status="succeeded",
            mode=mode,
            prompt_version="seo_workflow_router/v001",
            context_id=context_pack["context_id"],
            input_sources=context_pack["source_tables_json"],
            output_path=str(output_path),
            findings_count=len(output["findings"]),
            actions_count=len(output["actions"]),
            dry_run=not should_write_bigquery,
            bigquery_write_status="succeeded" if should_write_bigquery else "dry_run",
        )
        loaded = None
        bq_client = None
        if should_write_bigquery:
            from google.cloud import bigquery

            bq_client = bigquery.Client(project=config.project_id)
            loaded = log_agent_output(
                bq_client,
                config,
                run_row=run_row,
                findings=output["findings"],
                actions=output["actions"],
                context_pack=context_pack,
                dry_run=False,
                ensure_tables_first=args.ensure_tables,
                batch_id=run_id,
                purpose="seo-workflow-router: log validated output",
            )
        langfuse_trace = emit_agent_trace(
            run_row=run_row,
            findings=output["findings"],
            actions=output["actions"],
            context_pack=context_pack,
            bigquery_project=config.project_id,
            bigquery_dataset=config.control_dataset,
        )
        langfuse_link = log_langfuse_trace_link(
            bq_client,
            config,
            run_row=run_row,
            trace_result=langfuse_trace,
            dry_run=not should_write_bigquery,
            ensure_tables_first=args.ensure_tables,
            batch_id=run_id,
            purpose="seo-workflow-router: log langfuse trace link",
        )
        payload = {
            **output,
            "run_log": run_row,
            "context_pack": context_pack,
            "bigquery_loaded": loaded,
            "langfuse_trace": langfuse_trace.__dict__,
            "langfuse_link_loaded": langfuse_link.__dict__ if langfuse_link else None,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        complete_agent_run_lifecycle(
            index_path=DEFAULT_AGENT_RUN_INDEX,
            active_dir=DEFAULT_ACTIVE_RUN_DIR,
            run_row=run_row,
            output_path=str(output_path),
            run_json_path=str(output_path),
            bigquery_logged=bool(loaded),
        )
    except Exception as exc:
        fail_agent_run_lifecycle(
            index_path=DEFAULT_AGENT_RUN_INDEX,
            active_dir=DEFAULT_ACTIVE_RUN_DIR,
            run_id=run_id,
            agent_id="seo_workflow_router",
            agent_name="SEO Workflow Router",
            started_at=started_at,
            mode=mode,
            exc=exc,
            dry_run=not should_write_bigquery,
            automation_id=args.automation_id,
            prompt_version="seo_workflow_router/v001",
            output_path=str(output_path),
            run_json_path=str(output_path),
        )
        raise
    print(
        json.dumps(
            {
                "status": "succeeded",
                "run_id": run_id,
                "dry_run": not should_write_bigquery,
                "findings": len(output["findings"]),
                "actions": len(output["actions"]),
                "output_json": str(output_path),
                "bigquery_loaded": loaded,
                "langfuse_trace": langfuse_trace.__dict__,
                "langfuse_link_loaded": langfuse_link.__dict__ if langfuse_link else None,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
