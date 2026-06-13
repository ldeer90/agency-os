#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agent_logging import log_rows_with_staging_merge  # noqa: E402
from agency_bigquery.agent_ops import (  # noqa: E402
    approval_decision_to_action_status,
    build_agent_approval_row,
    load_agent_permissions,
    validate_permissions_safe_default,
)
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a human approval decision for a suggested agent action.")
    parser.add_argument("--action-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--client-slug", required=True)
    parser.add_argument("--decision", required=True, choices=("approved", "rejected", "ignored", "completed"))
    parser.add_argument("--decided-by", default="laurence")
    parser.add_argument("--reason")
    parser.add_argument("--notes")
    parser.add_argument("--action-json", help="Optional existing action row JSON to update and log with the approval.")
    parser.add_argument("--output-json", help="Optional local output path for the approval record.")
    parser.add_argument("--write-bigquery", action="store_true", help="Explicitly log the approval row to BigQuery.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/verify agent operating tables before BigQuery logging.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--permissions", default=str(PROJECT_ROOT / "config" / "permissions.yaml"), help="Path to permissions YAML.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    permissions = load_agent_permissions(Path(args.permissions))
    validate_permissions_safe_default(permissions)
    config = BigQueryCostConfig.from_file(args.config)
    if args.load_env:
        load_env_file(Path(args.load_env))

    approval = build_agent_approval_row(
        action_id=args.action_id,
        run_id=args.run_id,
        client_slug=args.client_slug,
        decision=args.decision,
        decided_by=args.decided_by,
        reason=args.reason,
        notes=args.notes,
    )
    action_rows: list[dict] = []
    if args.action_json:
        action = json.loads(Path(args.action_json).read_text(encoding="utf-8"))
        action["status"] = approval_decision_to_action_status(args.decision)
        action["approval_id"] = approval["approval_id"]
        action_rows.append(action)

    output = {"approval": approval, "updated_actions": action_rows, "dry_run": not args.write_bigquery}
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2, sort_keys=True, default=str), encoding="utf-8")

    loaded = None
    if args.write_bigquery:
        if not permissions.allow_bigquery_logging:
            raise SystemExit("BigQuery logging is disabled in permissions.yaml")
        from google.cloud import bigquery

        client = bigquery.Client(project=config.project_id)
        if args.ensure_tables:
            from agency_bigquery.agent_logging import ensure_agent_logging_tables

            ensure_agent_logging_tables(client, config)
        approval_result = log_rows_with_staging_merge(
            client,
            config,
            "agent_approvals",
            [approval],
            dry_run=False,
            batch_id=approval["approval_id"],
            purpose="agent-approval: log human decision",
        )
        loaded = {"agent_approvals": approval_result.rows}
        if action_rows:
            action_result = log_rows_with_staging_merge(
                client,
                config,
                "agent_actions",
                action_rows,
                dry_run=False,
                batch_id=approval["approval_id"],
                purpose="agent-approval: update suggested action status",
            )
            loaded["agent_actions"] = action_result.rows

    print(json.dumps({**output, "bigquery_loaded": loaded}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
