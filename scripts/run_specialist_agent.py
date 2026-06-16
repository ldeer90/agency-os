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
from agency_bigquery.seo_automation_catalog import DEFAULT_SEO_AUTOMATION_ROOT  # noqa: E402
from agency_bigquery.specialist_agents import (  # noqa: E402
    SPECIALIST_AGENT_CONFIGS,
    context_pack_for_output,
    local_client_rows,
    output_for_agent,
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a read-only AgencyOS specialist agent.")
    parser.add_argument("agent_id", choices=sorted(SPECIALIST_AGENT_CONFIGS), help="Specialist agent to run.")
    parser.add_argument("--seo-automation-root", default=str(DEFAULT_SEO_AUTOMATION_ROOT), help="SEO Automation repo root for local dry-runs.")
    parser.add_argument("--from-bigquery", action="store_true", help="Read context from BigQuery through the capped runner.")
    parser.add_argument("--write-bigquery", action="store_true", help="Log validated findings/actions/run/context to BigQuery. BigQuery-context runs log on completion by default unless --dry-run is used.")
    parser.add_argument("--dry-run", action="store_true", help="Local/report-only mode. Use with --from-bigquery to read live context without writing completion metadata.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify operating tables before BigQuery logging.")
    parser.add_argument("--automation-id", default=os.environ.get("SEO_AGENCY_OS_AUTOMATION_ID"), help="Optional automation ID.")
    parser.add_argument("--client-slug", help="Limit review to one client slug.")
    parser.add_argument("--run-id", default=None, help="Optional run ID. Defaults to a UUID hex.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows.")
    parser.add_argument("--output-json", help="Output path for validated run JSON.")
    return parser.parse_args(argv)


def _client_filter(client_slug: str | None, *, field: str = "client_slug") -> str:
    if not client_slug:
        return ""
    safe = client_slug.replace("'", "")
    return f"WHERE {field} = '{safe}'"


def read_bigquery_rows(agent_id: str, config: BigQueryCostConfig, *, limit: int, client_slug: str | None) -> list[dict]:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    project = config.project_id
    reporting = config.reporting_dataset
    memory = config.memory_dataset
    if agent_id == "performance_analyst":
        filter_sql = _client_filter(client_slug, field="c.client_slug")
        sql = f"""
SELECT c.client_slug, c.client_name, c.period_id, c.organic_sessions, c.organic_sessions_mom_pct,
       c.gsc_clicks, c.gsc_clicks_mom_pct, c.organic_revenue, c.organic_revenue_mom_pct,
       cov.coverage_status, cov.has_ga4, cov.has_search_console, cov.has_se_ranking,
       'agency_reporting.client_monthly_comparison' AS source_table
FROM `{project}.{reporting}.client_monthly_comparison` c
LEFT JOIN `{project}.{reporting}.client_monthly_reporting_coverage` cov
USING (client_slug, period_id)
{filter_sql if filter_sql else ""}
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.client_slug ORDER BY c.month_start DESC) = 1
ORDER BY c.client_slug
LIMIT {int(limit)}
"""
    elif agent_id == "drive_filing_readback_agent":
        filter_sql = _client_filter(client_slug)
        sql = f"""
SELECT client_slug, client_name, snapshot_date, has_drive_root, has_drive_root_verified,
       has_reports_route, has_reports_folder_verified, has_content_route, has_content_folder_verified,
       has_roadmap_route, has_roadmap_folder_verified, has_roadmap_files, has_roadmap_content_validated,
       missing_required_json, 'agency_reporting.client_health_check' AS source_table
FROM `{project}.{reporting}.client_health_check`
{filter_sql}
QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
ORDER BY client_slug
LIMIT {int(limit)}
"""
    elif agent_id == "se_ranking_hygiene_agent":
        filter_sql = _client_filter(client_slug)
        sql = f"""
SELECT client_slug, client_name, snapshot_date, has_se_ranking, has_se_ranking_access,
       missing_required_json, 'agency_reporting.client_health_check' AS source_table
FROM `{project}.{reporting}.client_health_check`
{filter_sql}
QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
ORDER BY client_slug
LIMIT {int(limit)}
"""
    elif agent_id == "reporting_portal_qa_agent":
        filter_sql = _client_filter(client_slug, field="r.client_slug")
        sql = f"""
SELECT r.client_slug, r.client_name, r.readiness_status, r.latest_report_month,
       cov.period_id, cov.coverage_status, cov.has_ga4, cov.has_search_console, cov.has_se_ranking, cov.has_ai_referrals,
       'agency_reporting.reporting_readiness' AS source_table
FROM `{project}.{reporting}.reporting_readiness` r
LEFT JOIN `{project}.{reporting}.client_monthly_reporting_coverage` cov
ON r.client_slug = cov.client_slug
{filter_sql}
QUALIFY ROW_NUMBER() OVER (PARTITION BY r.client_slug ORDER BY cov.period_id DESC NULLS LAST) = 1
ORDER BY r.client_slug
LIMIT {int(limit)}
"""
    elif agent_id == "technical_audit_agent":
        filter_sql = _client_filter(client_slug)
        sql = f"""
SELECT
  s.client_slug,
  s.client_name,
  s.domain,
  s.workflow_profile,
  s.sidecar_path,
  s.timeline_path,
  c.crawl_id,
  c.crawl_date,
  c.crawl_trigger,
  c.crawler,
  c.crawl_status,
  c.pages_crawled,
  c.indexable_html_urls,
  c.nonindexable_html_urls,
  c.status_4xx_urls,
  c.status_5xx_urls,
  c.missing_title_urls,
  c.duplicate_title_urls,
  c.missing_meta_description_urls,
  c.missing_h1_urls,
  c.canonical_issue_urls,
  c.low_content_urls,
  c.issue_counts_json,
  issue_examples.crawl_issue_examples_json,
  c.export_manifest_path,
  'agency_memory.seo_client_memory_summaries + agency_reporting.client_crawl_latest + agency_memory.client_crawl_issue_rows' AS source_table,
  COALESCE(c.source_ref_hash, s.source_ref_hash) AS source_ref_hash
FROM `{project}.{memory}.seo_client_memory_summaries` s
LEFT JOIN `{project}.{reporting}.client_crawl_latest` c
USING (client_slug)
LEFT JOIN (
  SELECT
    crawl_id,
    TO_JSON_STRING(ARRAY_AGG(STRUCT(
      issue_name,
      issue_type,
      issue_priority,
      issue_count,
      address,
      source_url,
      destination_url,
      status_code
    ) ORDER BY
      CASE LOWER(COALESCE(issue_priority, ''))
        WHEN 'high' THEN 1
        WHEN 'medium' THEN 2
        WHEN 'low' THEN 3
        ELSE 4
      END,
      COALESCE(issue_count, 0) DESC,
      row_number
      LIMIT 25
    )) AS crawl_issue_examples_json
  FROM `{project}.{memory}.client_crawl_issue_rows`
  GROUP BY crawl_id
) issue_examples
ON c.crawl_id = issue_examples.crawl_id
{filter_sql.replace("WHERE client_slug", "WHERE s.client_slug") if filter_sql else ""}
QUALIFY ROW_NUMBER() OVER (PARTITION BY s.client_slug ORDER BY s.synced_at DESC) = 1
ORDER BY client_slug
LIMIT {int(limit)}
"""
    elif agent_id == "content_research_agent":
        filter_sql = _client_filter(client_slug, field="s.client_slug")
        sql = f"""
SELECT
  s.client_slug,
  s.client_name,
  s.domain,
  s.site_type,
  s.market_scope,
  s.workflow_profile,
  s.sidecar_path,
  s.brief_path,
  s.timeline_path,
  s.sidecar_present,
  s.brief_present,
  s.timeline_present,
  s.has_search_console_route,
  s.has_se_ranking,
  s.has_monday_route,
  s.has_drive_root,
  s.collection_count,
  s.priority_pages_count,
  s.deliverables_json,
  'agency_memory.seo_client_memory_summaries' AS source_table,
  s.source_ref_hash
FROM `{project}.{memory}.seo_client_memory_summaries` s
{filter_sql}
QUALIFY ROW_NUMBER() OVER (PARTITION BY s.client_slug ORDER BY s.synced_at DESC) = 1
ORDER BY s.client_slug
LIMIT {int(limit)}
"""
    elif agent_id == "content_writer_agent":
        filter_sql = _client_filter(client_slug, field="s.client_slug")
        sql = f"""
SELECT
  s.client_slug,
  s.client_name,
  s.domain,
  s.site_type,
  s.market_scope,
  s.workflow_profile,
  s.sidecar_path,
  s.brief_path,
  s.timeline_path,
  s.sidecar_present,
  s.brief_present,
  s.timeline_present,
  s.has_search_console_route,
  s.has_se_ranking,
  s.has_monday_route,
  s.has_drive_root,
  s.collection_count,
  s.priority_pages_count,
  s.deliverables_json,
  'agency_memory.seo_client_memory_summaries' AS source_table,
  s.source_ref_hash
FROM `{project}.{memory}.seo_client_memory_summaries` s
{filter_sql}
QUALIFY ROW_NUMBER() OVER (PARTITION BY s.client_slug ORDER BY s.synced_at DESC) = 1
ORDER BY s.client_slug
LIMIT {int(limit)}
"""
    else:
        raise SystemExit(f"Unsupported agent: {agent_id}")
    _, rows = runner.run_query(sql, purpose=f"{agent_id}: read specialist context")
    return [dict(row) for row in rows]


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    should_write_bigquery = (args.write_bigquery or args.from_bigquery) and not args.dry_run
    if should_write_bigquery and not args.from_bigquery:
        raise SystemExit("--write-bigquery requires --from-bigquery for specialist agents")
    run_id = args.run_id or uuid4().hex
    started_at = utc_now_iso()
    agent_config = SPECIALIST_AGENT_CONFIGS[args.agent_id]
    mode = "bigquery" if args.from_bigquery else "local_context"
    default_dir = PROJECT_ROOT / "data" / "agent_runs" / args.agent_id
    output_path = Path(args.output_json) if args.output_json else default_dir / f"{run_id}.json"
    start_agent_run_lifecycle(
        index_path=DEFAULT_AGENT_RUN_INDEX,
        active_dir=DEFAULT_ACTIVE_RUN_DIR,
        run_id=run_id,
        automation_id=args.automation_id,
        agent_id=args.agent_id,
        agent_name=agent_config.agent_name,
        started_at=started_at,
        mode=mode,
        prompt_version=agent_config.prompt_version,
        input_sources=["pending_context_resolution"],
        output_path=str(output_path),
        run_json_path=str(output_path),
        dry_run=not should_write_bigquery,
    )
    config = BigQueryCostConfig.from_file(args.config)
    try:
        if args.load_env:
            load_env_file(Path(args.load_env))
        if args.agent_id == "system_admin_agent":
            from run_system_admin_agent import local_check_rows, read_bigquery_rows

            rows = local_check_rows(config, created_at=started_at)
            if args.from_bigquery:
                rows.extend(read_bigquery_rows(config, limit=args.limit))
        elif args.from_bigquery:
            rows = read_bigquery_rows(args.agent_id, config, limit=args.limit, client_slug=args.client_slug)
        else:
            rows = local_client_rows(
                run_id=run_id,
                seo_automation_root=args.seo_automation_root,
                client_slug=args.client_slug,
            )[: args.limit]
        output = output_for_agent(args.agent_id, rows, run_id=run_id, created_at=started_at)
        context_pack = context_pack_for_output(
            agent_id=args.agent_id,
            run_id=run_id,
            created_at=started_at,
            rows=rows,
            output=output,
            client_slug=args.client_slug,
        )
        run_row = build_agent_run_row(
            run_id=run_id,
            automation_id=args.automation_id,
            agent_id=args.agent_id,
            agent_name=agent_config.agent_name,
            started_at=started_at,
            completed_at=utc_now_iso(),
            status="succeeded",
            mode=mode,
            prompt_version=agent_config.prompt_version,
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
                purpose=f"{args.agent_id}: log validated output",
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
            purpose=f"{args.agent_id}: log langfuse trace link",
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
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "run_id": run_id,
                    "agent_id": args.agent_id,
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
    except Exception as exc:
        fail_agent_run_lifecycle(
            index_path=DEFAULT_AGENT_RUN_INDEX,
            active_dir=DEFAULT_ACTIVE_RUN_DIR,
            run_id=run_id,
            automation_id=args.automation_id,
            agent_id=args.agent_id,
            agent_name=agent_config.agent_name,
            started_at=started_at,
            mode=mode,
            prompt_version=agent_config.prompt_version,
            input_sources=["pending_context_resolution"],
            output_path=str(output_path),
            run_json_path=str(output_path),
            dry_run=not should_write_bigquery,
            exc=exc,
        )
        raise


if __name__ == "__main__":
    raise SystemExit(run())
