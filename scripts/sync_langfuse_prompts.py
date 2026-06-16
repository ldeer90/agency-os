#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.langfuse_tracing import (  # noqa: E402
    LANGFUSE_BASE_URL_ENV,
    LANGFUSE_CAPTURE_PAYLOADS_ENV,
    LANGFUSE_ENABLED_ENV,
    LANGFUSE_HOST_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
    _get_langfuse_client,
    langfuse_env_enabled,
    prompt_metadata_for_agent,
)


SAFE_ENV_KEYS = {
    LANGFUSE_BASE_URL_ENV,
    LANGFUSE_CAPTURE_PAYLOADS_ENV,
    LANGFUSE_ENABLED_ENV,
    LANGFUSE_HOST_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
}
DEFAULT_PROMPTS_ROOT = PROJECT_ROOT / "prompts"


@dataclass(frozen=True)
class PromptSyncPlan:
    agent_id: str
    name: str
    version_label: str
    labels: tuple[str, ...]
    path: Path
    sha256: str
    prompt: str


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
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def prompt_sync_plans(prompts_root: Path = DEFAULT_PROMPTS_ROOT) -> list[PromptSyncPlan]:
    plans: list[PromptSyncPlan] = []
    for prompt_dir in sorted(path for path in prompts_root.iterdir() if path.is_dir()):
        agent_id = prompt_dir.name
        current_path = prompt_dir / "current.md"
        current_text = current_path.read_text(encoding="utf-8") if current_path.exists() else None
        version_paths = sorted(path for path in prompt_dir.glob("*.md") if path.name != "current.md")
        if not version_paths and current_path.exists():
            version_paths = [current_path]

        for path in version_paths:
            prompt = path.read_text(encoding="utf-8")
            version_label = "current" if path.name == "current.md" else path.stem
            labels = [version_label]
            if current_text is not None and prompt == current_text and "current" not in labels:
                labels.append("current")
            metadata = prompt_metadata_for_agent(agent_id, f"{agent_id}/{version_label}", prompts_root=prompts_root)
            prompt_hash = ""
            for item in metadata.get("prompts", []):
                if item.get("path") == str(path):
                    prompt_hash = str(item.get("sha256") or "")
                    break
            plans.append(
                PromptSyncPlan(
                    agent_id=agent_id,
                    name=f"agency-os/{agent_id}",
                    version_label=version_label,
                    labels=tuple(labels),
                    path=path,
                    sha256=prompt_hash,
                    prompt=prompt,
                )
            )
    return plans


def sync_prompt_plan(client: Any, plan: PromptSyncPlan, *, dry_run: bool) -> dict[str, Any]:
    status = "create"
    existing_version = None
    try:
        existing = client.get_prompt(plan.name, label=plan.version_label, type="text")
        existing_version = getattr(existing, "version", None)
        if getattr(existing, "prompt", None) == plan.prompt:
            status = "unchanged"
    except Exception:
        existing = None

    if dry_run or status == "unchanged":
        return {
            "name": plan.name,
            "agent_id": plan.agent_id,
            "version_label": plan.version_label,
            "labels": list(plan.labels),
            "path": str(plan.path),
            "sha256": plan.sha256,
            "status": "would_" + status if dry_run and status != "unchanged" else status,
            "existing_version": existing_version,
        }

    created = client.create_prompt(
        name=plan.name,
        prompt=plan.prompt,
        labels=list(plan.labels),
        tags=["agency-os", "bigquery"],
        type="text",
        config={"agent_id": plan.agent_id, "source_path": str(plan.path), "sha256": plan.sha256},
        commit_message=f"Sync {plan.agent_id} {plan.version_label} from Agency OS Big Query prompts",
    )
    return {
        "name": plan.name,
        "agent_id": plan.agent_id,
        "version_label": plan.version_label,
        "labels": list(plan.labels),
        "path": str(plan.path),
        "sha256": plan.sha256,
        "status": "created",
        "version": getattr(created, "version", None),
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        status = str(result.get("status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Agency OS prompt files into Langfuse prompt management.")
    parser.add_argument("--load-env", help="Optional .env path. Only Langfuse keys are loaded.")
    parser.add_argument("--prompts-root", default=str(DEFAULT_PROMPTS_ROOT), help="Prompt root directory.")
    parser.add_argument("--agent-id", help="Limit sync to one agent id.")
    parser.add_argument(
        "--extra-label",
        action="append",
        choices=("staging", "production"),
        default=[],
        help="Additional Langfuse prompt label to assign when creating new prompt versions.",
    )
    parser.add_argument("--write", action="store_true", help="Create Langfuse prompt versions when needed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.load_env:
        load_env_file(Path(args.load_env))

    plans = prompt_sync_plans(Path(args.prompts_root))
    if args.agent_id:
        plans = [plan for plan in plans if plan.agent_id == args.agent_id]
    if args.extra_label:
        plans = [
            replace(plan, labels=tuple(dict.fromkeys([*plan.labels, *args.extra_label])))
            for plan in plans
        ]

    if not args.write:
        results = [
            {
                "name": plan.name,
                "agent_id": plan.agent_id,
                "version_label": plan.version_label,
                "labels": list(plan.labels),
                "path": str(plan.path),
                "sha256": plan.sha256,
                "status": "would_check",
            }
            for plan in plans
        ]
    else:
        if not langfuse_env_enabled():
            raise SystemExit("Langfuse credentials not configured; pass --load-env or set env vars before --write.")
        client = _get_langfuse_client()
        results = [sync_prompt_plan(client, plan, dry_run=False) for plan in plans]
        if hasattr(client, "flush"):
            client.flush()
    summary = summarize_results(results)

    print(
        json.dumps(
            {
                "status": "succeeded",
                "dry_run": not args.write,
                "prompt_count": len(results),
                "summary": summary,
                "results": results,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
