#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.schema import ensure_agent_operating_tables, plan_agent_operating_tables  # noqa: E402


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
    parser = argparse.ArgumentParser(description="Plan or ensure SEO Agency OS agent operating tables.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Inspect table status without creating/updating anything.")
    mode.add_argument("--ensure", action="store_true", help="Create/update the approved agent operating tables.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.load_env:
        load_env_file(Path(args.load_env))
    config = BigQueryCostConfig.from_file(args.config)
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    if args.ensure:
        ensure_agent_operating_tables(client, config)
    plan = plan_agent_operating_tables(client, config)
    print(json.dumps({"status": "succeeded", "mode": "ensure" if args.ensure else "plan", "tables": plan}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
