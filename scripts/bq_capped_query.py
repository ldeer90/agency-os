#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.cost_config import BigQueryCostConfig, DEFAULT_CONFIG_PATH
from agency_bigquery.capped_query_runner import CappedBigQueryRunner, QueryCostExceeded
from agency_bigquery.schema import ensure_cost_checks_table


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}


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


def read_sql(args: argparse.Namespace) -> str:
    if args.sql:
        return args.sql
    if args.sql_file:
        return Path(args.sql_file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("Provide --sql, --sql-file, or pipe SQL on stdin.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BigQuery SQL with dry-run and maximum-bytes guardrails.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--sql", help="SQL text to run.")
    parser.add_argument("--sql-file", help="Path to SQL file to run.")
    parser.add_argument("--purpose", required=True, help="Short audit purpose, e.g. 'qa: smoke test cost checks'.")
    parser.add_argument("--admin-cap-10gb", action="store_true", help="Use the explicit 10 GB manual override cap.")
    parser.add_argument("--estimate-only", action="store_true", help="Dry-run estimate only; do not execute.")
    parser.add_argument("--ensure-log-table", action="store_true", help="Create agency_control.cost_checks if missing.")
    parser.add_argument("--location", help="Override BigQuery job location.")
    parser.add_argument("--limit-preview", type=int, default=0, help="Rows to print from query results. Defaults to 0 for safety.")
    args = parser.parse_args()

    if args.load_env:
        load_env_file(Path(args.load_env))

    config = BigQueryCostConfig.from_file(args.config)
    try:
        from google.cloud import bigquery
    except ModuleNotFoundError:
        print("google-cloud-bigquery is not installed. Run: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    client = bigquery.Client(project=config.project_id)
    if args.ensure_log_table:
        try:
            ensure_cost_checks_table(client, config)
        except Exception as exc:
            print(
                f"Could not create or verify {config.cost_checks_table_id}: "
                f"{type(exc).__name__}: {str(exc).splitlines()[0]}",
                file=sys.stderr,
            )
            return 4

    runner = CappedBigQueryRunner(client, config)
    sql = read_sql(args)

    if args.estimate_only:
        result = runner.estimate_query(sql, purpose=args.purpose, location=args.location)
        print(
            json.dumps(
                {
                    "status": result.status,
                    "purpose": result.purpose,
                    "estimated_bytes": result.estimated_bytes,
                    "estimated_human": result.estimated_human,
                    "normal_cap_bytes": config.normal_query_cap_bytes,
                    "cost_check_log_errors": list(result.log_errors),
                },
                indent=2,
            )
        )
        return 0

    try:
        result, rows = runner.run_query(
            sql,
            purpose=args.purpose,
            admin_cap_10gb=args.admin_cap_10gb,
            location=args.location,
        )
    except QueryCostExceeded as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(
            f"BigQuery query failed before completion: {type(exc).__name__}: {str(exc).splitlines()[0]}",
            file=sys.stderr,
        )
        return 4

    print(
        json.dumps(
            {
                "status": result.status,
                "purpose": result.purpose,
                "estimated_bytes": result.estimated_bytes,
                "estimated_human": result.estimated_human,
                "cap_bytes": result.cap_bytes,
                "cap_human": result.cap_human,
                "job_id": result.job_id,
                "cost_check_log_errors": list(result.log_errors),
            },
            indent=2,
        )
    )
    if args.limit_preview > 0 and rows is not None:
        for index, row in enumerate(rows):
            if index >= args.limit_preview:
                break
            print(dict(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
