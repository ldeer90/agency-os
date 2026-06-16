from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LANGFUSE_PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
LANGFUSE_SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"
LANGFUSE_HOST_ENV = "LANGFUSE_HOST"
LANGFUSE_BASE_URL_ENV = "LANGFUSE_BASE_URL"
LANGFUSE_ENABLED_ENV = "LANGFUSE_ENABLED"
LANGFUSE_CAPTURE_PAYLOADS_ENV = "LANGFUSE_CAPTURE_PAYLOADS"
PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"


@dataclass(frozen=True)
class LangfuseTraceResult:
    status: str
    enabled: bool
    trace_id: str | None = None
    trace_url: str | None = None
    metadata_sha256: str | None = None
    session_id: str | None = None
    message: str | None = None


def langfuse_env_enabled(env: dict[str, str] | None = None) -> bool:
    values = env or os.environ
    explicit = str(values.get(LANGFUSE_ENABLED_ENV, "")).strip().lower()
    if explicit in {"0", "false", "no", "off"}:
        return False
    return bool(values.get(LANGFUSE_PUBLIC_KEY_ENV) and values.get(LANGFUSE_SECRET_KEY_ENV))


def _payload_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prompt_metadata_for_agent(
    agent_id: str | None,
    prompt_version: str | None = None,
    *,
    prompts_root: Path = PROMPTS_ROOT,
) -> dict[str, Any]:
    if not agent_id:
        return {}

    prompt_dir = prompts_root / str(agent_id)
    candidates: list[Path] = []
    if prompt_version and "/" in prompt_version:
        version_name = prompt_version.split("/", 1)[1]
        candidates.append(prompt_dir / f"{version_name}.md")
    candidates.append(prompt_dir / "current.md")

    prompts: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists() or not path.is_file():
            continue
        seen.add(path)
        content = path.read_bytes()
        prompts.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(prompts_root.parents[0])),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )

    return {
        "agent_id": agent_id,
        "prompt_version": prompt_version,
        "prompts": prompts,
    }


def _safe_trace_payload(
    *,
    run_row: dict[str, Any],
    findings: list[dict[str, Any]] | None,
    actions: list[dict[str, Any]] | None,
    context_pack: dict[str, Any] | None,
    llm_usage: list[dict[str, Any]] | None,
    prompt_metadata: dict[str, Any] | None,
    bigquery_project: str | None,
    bigquery_dataset: str | None,
    capture_payloads: bool,
) -> dict[str, Any]:
    findings = findings or []
    actions = actions or []
    llm_usage = llm_usage or []
    prompt_info = prompt_metadata or prompt_metadata_for_agent(
        str(run_row.get("agent_id") or ""),
        str(run_row.get("prompt_version") or ""),
    )
    payload: dict[str, Any] = {
        "run_id": run_row.get("run_id"),
        "automation_id": run_row.get("automation_id"),
        "agent_id": run_row.get("agent_id"),
        "agent_name": run_row.get("agent_name"),
        "context_id": run_row.get("context_id"),
        "prompt_version": run_row.get("prompt_version"),
        "mode": run_row.get("mode"),
        "dry_run": run_row.get("dry_run"),
        "status": run_row.get("status"),
        "started_at": run_row.get("started_at"),
        "completed_at": run_row.get("completed_at"),
        "findings_count": len(findings),
        "actions_count": len(actions),
        "llm_usage_count": len(llm_usage),
        "bigquery_project": bigquery_project,
        "bigquery_dataset": bigquery_dataset,
        "output_path": run_row.get("output_path"),
        "run": {
            "run_id": run_row.get("run_id"),
            "automation_id": run_row.get("automation_id"),
            "agent_id": run_row.get("agent_id"),
            "agent_name": run_row.get("agent_name"),
            "status": run_row.get("status"),
            "mode": run_row.get("mode"),
            "prompt_version": run_row.get("prompt_version"),
            "context_id": run_row.get("context_id"),
            "started_at": run_row.get("started_at"),
            "completed_at": run_row.get("completed_at"),
            "dry_run": run_row.get("dry_run"),
        },
        "counts": {
            "findings": len(findings),
            "actions": len(actions),
            "llm_usage": len(llm_usage),
        },
        "hashes": {
            "findings_sha256": _payload_hash(findings),
            "actions_sha256": _payload_hash(actions),
            "context_pack_sha256": _payload_hash(context_pack or {}),
            "llm_usage_sha256": _payload_hash(llm_usage),
            "prompt_sha256": _payload_hash(prompt_info),
        },
        "prompt": prompt_info,
    }
    if capture_payloads:
        payload["payloads"] = {
            "findings": findings,
            "actions": actions,
            "context_pack": context_pack,
            "llm_usage": llm_usage,
        }
    return payload


def _normalize_langfuse_host_env() -> None:
    if not os.environ.get(LANGFUSE_HOST_ENV) and os.environ.get(LANGFUSE_BASE_URL_ENV):
        os.environ[LANGFUSE_HOST_ENV] = str(os.environ[LANGFUSE_BASE_URL_ENV])


def _get_langfuse_client() -> Any:
    _normalize_langfuse_host_env()
    from langfuse import Langfuse

    return Langfuse()


def _usage_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usage_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _usage_details(row: dict[str, Any]) -> dict[str, int]:
    details: dict[str, int] = {}
    input_tokens = _usage_int(row.get("input_tokens") or row.get("prompt_tokens"))
    output_tokens = _usage_int(row.get("output_tokens") or row.get("completion_tokens"))
    total_tokens = _usage_int(row.get("total_tokens"))
    if input_tokens is not None:
        details["input"] = input_tokens
    if output_tokens is not None:
        details["output"] = output_tokens
    if total_tokens is not None:
        details["total"] = total_tokens
    elif input_tokens is not None or output_tokens is not None:
        details["total"] = (input_tokens or 0) + (output_tokens or 0)
    return details


def _cost_details(row: dict[str, Any]) -> dict[str, float] | None:
    cost = _usage_float(row.get("cost_estimate_aud"))
    if cost is None:
        return None
    return {"total": cost}


def _emit_llm_usage_generations(
    client: Any,
    *,
    trace_id: str,
    run_row: dict[str, Any],
    llm_usage: list[dict[str, Any]],
    prompt_metadata: dict[str, Any],
) -> None:
    for index, row in enumerate(llm_usage, start=1):
        if not isinstance(row, dict):
            continue
        usage_details = _usage_details(row)
        generation = client.start_observation(
            trace_context={"trace_id": trace_id},
            name=str(row.get("name") or run_row.get("prompt_version") or run_row.get("agent_id") or f"llm_usage_{index}"),
            as_type="generation",
            input={
                "prompt_version": run_row.get("prompt_version"),
                "prompt": prompt_metadata,
            },
            output={"notes": row.get("notes")},
            metadata={
                "run_id": run_row.get("run_id"),
                "agent_id": run_row.get("agent_id"),
                "prompt_version": run_row.get("prompt_version"),
                "logged_at": row.get("logged_at"),
            },
            version=str(run_row.get("prompt_version") or ""),
            model=row.get("model"),
            usage_details=usage_details or None,
            cost_details=_cost_details(row),
        )
        if hasattr(generation, "end"):
            generation.end()


def emit_agent_trace(
    *,
    run_row: dict[str, Any],
    findings: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    context_pack: dict[str, Any] | None = None,
    llm_usage: list[dict[str, Any]] | None = None,
    prompt_metadata: dict[str, Any] | None = None,
    bigquery_project: str | None = None,
    bigquery_dataset: str | None = None,
    error_message: str | None = None,
    flush: bool = True,
) -> LangfuseTraceResult:
    if not langfuse_env_enabled():
        return LangfuseTraceResult(status="skipped", enabled=False, message="Langfuse credentials not configured")

    capture_payloads = str(os.environ.get(LANGFUSE_CAPTURE_PAYLOADS_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    trace_id = str(run_row.get("run_id") or "")
    metadata = _safe_trace_payload(
        run_row=run_row,
        findings=findings,
        actions=actions,
        context_pack=context_pack,
        llm_usage=llm_usage,
        prompt_metadata=prompt_metadata,
        bigquery_project=bigquery_project,
        bigquery_dataset=bigquery_dataset,
        capture_payloads=capture_payloads,
    )
    metadata_sha256 = _payload_hash(metadata)
    session_id = str(run_row.get("automation_id") or f"manual:{str(run_row.get('started_at') or '')[:10]}")
    if error_message:
        metadata["error"] = {"message": error_message[:500]}

    try:
        client = _get_langfuse_client()
        langfuse_trace_id = client.create_trace_id(seed=trace_id or None)
        trace_url = client.get_trace_url(trace_id=langfuse_trace_id) if hasattr(client, "get_trace_url") else None
        observation = client.start_observation(
            trace_context={"trace_id": langfuse_trace_id},
            name=str(run_row.get("agent_id") or "agency_bigquery_agent"),
            as_type="agent",
            input={
                "mode": run_row.get("mode"),
                "prompt_version": run_row.get("prompt_version"),
                "dry_run": run_row.get("dry_run"),
                "session_id": session_id,
            },
            output={
                "status": run_row.get("status"),
                "findings_count": len(findings or []),
                "actions_count": len(actions or []),
            },
            metadata=metadata,
            version=str(run_row.get("prompt_version") or ""),
            level="ERROR" if error_message else "DEFAULT",
            status_message=error_message,
        )
        if hasattr(observation, "end"):
            observation.end()
        _emit_llm_usage_generations(
            client,
            trace_id=langfuse_trace_id,
            run_row=run_row,
            llm_usage=llm_usage or [],
            prompt_metadata=metadata.get("prompt") or {},
        )
        if flush and hasattr(client, "flush"):
            client.flush()
    except ImportError:
        return LangfuseTraceResult(
            status="skipped",
            enabled=True,
            trace_id=trace_id,
            metadata_sha256=metadata_sha256,
            session_id=session_id,
            message="langfuse package not installed",
        )
    except Exception as exc:  # pragma: no cover - defensive: tracing must never break agent runs.
        return LangfuseTraceResult(
            status="failed",
            enabled=True,
            trace_id=trace_id,
            metadata_sha256=metadata_sha256,
            session_id=session_id,
            message=f"{exc.__class__.__name__}: {exc}",
        )

    return LangfuseTraceResult(
        status="emitted",
        enabled=True,
        trace_id=langfuse_trace_id,
        trace_url=trace_url,
        metadata_sha256=metadata_sha256,
        session_id=session_id,
    )
