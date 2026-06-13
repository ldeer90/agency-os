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

from agency_bigquery.agent_logging import log_rows_with_staging_merge  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.seo_automation_catalog import DEFAULT_SEO_AUTOMATION_ROOT, build_workflow_catalog_rows  # noqa: E402


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "agent_runs" / "seo_automation_catalog"


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
    parser = argparse.ArgumentParser(description="Sync SEO Automation workflow catalog metadata into AgencyOS-safe rows.")
    parser.add_argument("--seo-automation-root", default=str(DEFAULT_SEO_AUTOMATION_ROOT), help="SEO Automation repo root.")
    parser.add_argument("--from-bigquery", action="store_true", help="Accepted for runner compatibility; this sync reads SEO Automation metadata directly.")
    parser.add_argument("--write-bigquery", action="store_true", help="Write sanitized catalog rows through the allowlisted staging/MERGE helper.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and write local output only. This is the default unless --write-bigquery is passed.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify operating tables before BigQuery logging.")
    parser.add_argument("--automation-id", default=os.environ.get("SEO_AGENCY_OS_AUTOMATION_ID"), help="Optional automation ID.")
    parser.add_argument("--client-slug", help="Accepted for runner compatibility; catalog sync is not client-scoped.")
    parser.add_argument("--run-id", default=None, help="Optional run ID. Defaults to a UUID hex.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--output-json", help="Output path for sanitized rows and run metadata.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or uuid4().hex
    rows = build_workflow_catalog_rows(root=Path(args.seo_automation_root), run_id=run_id)
    output_path = Path(args.output_json) if args.output_json else DEFAULT_OUTPUT_DIR / f"{run_id}.json"
    payload = {
        "status": "succeeded",
        "run_id": run_id,
        "automation_id": args.automation_id,
        "dry_run": not args.write_bigquery,
        "rows": rows,
        "row_count": len(rows),
        "bigquery_loaded": None,
    }
    if args.write_bigquery:
        if args.load_env:
            load_env_file(Path(args.load_env))
        from google.cloud import bigquery

        config = BigQueryCostConfig.from_file(args.config)
        client = bigquery.Client(project=config.project_id)
        result = log_rows_with_staging_merge(
            client,
            config,
            "seo_workflow_catalog",
            rows,
            dry_run=False,
            ensure_tables_first=args.ensure_tables,
            batch_id=run_id,
            purpose="seo-automation-catalog: sync workflow catalog",
        )
        payload["bigquery_loaded"] = {"table": result.table, "rows": result.rows, "destination_table_id": result.destination_table_id}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("status", "run_id", "dry_run", "row_count", "bigquery_loaded")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

