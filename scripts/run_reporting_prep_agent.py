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

from agency_bigquery.agent_logging import log_agent_output  # noqa: E402
from agency_bigquery.agent_ops import build_agent_run_row, build_context_pack, utc_now_iso  # noqa: E402
from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.seo_automation_catalog import (  # noqa: E402
    DEFAULT_SEO_AUTOMATION_ROOT,
    agent_output_from_opportunities,
    build_client_memory_summary_rows,
    opportunity_rows_from_context,
)


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "agent_runs" / "reporting_prep_agent"


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
    parser = argparse.ArgumentParser(description="Review monthly reporting prep gaps and suggest draft-only next actions.")
    parser.add_argument("--seo-automation-root", default=str(DEFAULT_SEO_AUTOMATION_ROOT), help="SEO Automation repo root for local dry-runs.")
    parser.add_argument("--from-bigquery", action="store_true", help="Read reporting coverage and client memory from BigQuery through the capped runner.")
    parser.add_argument("--write-bigquery", action="store_true", help="Log validated findings/actions/run/context to BigQuery.")
    parser.add_argument("--dry-run", action="store_true", help="Local/report-only mode. This is the default unless --write-bigquery is passed.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify operating tables before BigQuery logging.")
    parser.add_argument("--automation-id", default=os.environ.get("SEO_AGENCY_OS_AUTOMATION_ID"), help="Optional automation ID.")
    parser.add_argument("--client-slug", help="Limit review to one client slug.")
    parser.add_argument("--run-id", default=None, help="Optional run ID. Defaults to a UUID hex.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows.")
    parser.add_argument("--output-json", help="Output path for validated run JSON.")
    return parser.parse_args()


def read_bigquery_context(config: BigQueryCostConfig, *, limit: int, client_slug: str | None) -> tuple[list[dict], list[dict]]:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    client_filter = f"WHERE client_slug = '{client_slug.replace(chr(39), '')}'" if client_slug else ""
    memory_sql = f"""
SELECT *
FROM `{config.project_id}.{config.memory_dataset}.seo_client_memory_summaries`
{client_filter}
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY synced_at DESC) = 1
ORDER BY client_slug
LIMIT {int(limit)}
"""
    coverage_filter = f"WHERE client_slug = '{client_slug.replace(chr(39), '')}'" if client_slug else ""
    coverage_sql = f"""
SELECT client_slug, period_id, coverage_status, has_ga4, has_search_console, has_se_ranking, has_ai_referrals
FROM `{config.project_id}.{config.reporting_dataset}.client_monthly_reporting_coverage`
{coverage_filter}
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY period_id DESC) = 1
ORDER BY client_slug
LIMIT {int(limit)}
"""
    _, memory_rows = runner.run_query(memory_sql, purpose="reporting-prep-agent: read SEO client memory summaries")
    _, coverage_rows = runner.run_query(coverage_sql, purpose="reporting-prep-agent: read monthly reporting coverage")
    return [dict(row) for row in memory_rows], [dict(row) for row in coverage_rows]


def main() -> int:
    args = parse_args()
    if args.write_bigquery and not args.from_bigquery:
        raise SystemExit("--write-bigquery requires --from-bigquery for Reporting Prep Agent")
    run_id = args.run_id or uuid4().hex
    started_at = utc_now_iso()
    config = BigQueryCostConfig.from_file(args.config)
    if args.load_env:
        load_env_file(Path(args.load_env))
    if args.from_bigquery:
        client_rows, coverage_rows = read_bigquery_context(config, limit=args.limit, client_slug=args.client_slug)
    else:
        client_rows = build_client_memory_summary_rows(root=Path(args.seo_automation_root), run_id=run_id, only_client_slug=args.client_slug)
        coverage_rows = []
    opportunities = opportunity_rows_from_context(client_rows=client_rows, reporting_rows=coverage_rows)
    for opportunity in opportunities:
        opportunity["opportunity_type"] = "reporting_prep" if opportunity["opportunity_type"] == "seo_opportunity" else opportunity["opportunity_type"]
        if opportunity["workflow_id"] == "gsc-opportunity-mining":
            opportunity["workflow_id"] = "monthly-performance-comment"
            opportunity["summary"] = f"Prepare draft-only monthly reporting workflow for {opportunity['client_name']}."
            opportunity["recommended_action"] = "Review monthly reporting coverage, draft report commentary, and flag missing sources before any Monday or client-facing post."
    output = agent_output_from_opportunities(
        opportunities=opportunities,
        run_id=run_id,
        agent_id="reporting_prep_agent",
        created_at=started_at,
        limit=args.limit,
    )
    context_pack = build_context_pack(
        agent_id="reporting_prep_agent",
        run_id=run_id,
        created_at=started_at,
        task_type="reporting_prep_review",
        source_tables=["agency_memory.seo_client_memory_summaries", "agency_reporting.client_monthly_reporting_coverage"],
        client_slug=args.client_slug,
        sections={"metrics": output.get("metrics", {}), "coverage_rows": coverage_rows[:20]},
    )
    run_row = build_agent_run_row(
        run_id=run_id,
        automation_id=args.automation_id,
        agent_id="reporting_prep_agent",
        agent_name="Reporting Prep Agent",
        started_at=started_at,
        completed_at=utc_now_iso(),
        status="succeeded",
        mode="bigquery" if args.from_bigquery else "local_context",
        prompt_version="reporting_prep_agent/v001",
        context_id=context_pack["context_id"],
        input_sources=context_pack["source_tables_json"],
        output_path=None,
        findings_count=len(output["findings"]),
        actions_count=len(output["actions"]),
        dry_run=not args.write_bigquery,
        bigquery_write_status="succeeded" if args.write_bigquery else "dry_run",
    )
    loaded = None
    if args.write_bigquery:
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
            purpose="reporting-prep-agent: log validated output",
        )
    payload = {**output, "run_log": run_row, "context_pack": context_pack, "bigquery_loaded": loaded}
    output_path = Path(args.output_json) if args.output_json else DEFAULT_OUTPUT_DIR / f"{run_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({"status": "succeeded", "run_id": run_id, "dry_run": not args.write_bigquery, "findings": len(output["findings"]), "actions": len(output["actions"]), "output_json": str(output_path), "bigquery_loaded": loaded}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

