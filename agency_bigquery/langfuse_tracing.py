from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any


LANGFUSE_PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
LANGFUSE_SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"
LANGFUSE_HOST_ENV = "LANGFUSE_HOST"
LANGFUSE_ENABLED_ENV = "LANGFUSE_ENABLED"
LANGFUSE_CAPTURE_PAYLOADS_ENV = "LANGFUSE_CAPTURE_PAYLOADS"


@dataclass(frozen=True)
class LangfuseTraceResult:
    status: str
    enabled: bool
    trace_id: str | None = None
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


def _safe_trace_payload(
    *,
    run_row: dict[str, Any],
    findings: list[dict[str, Any]] | None,
    actions: list[dict[str, Any]] | None,
    context_pack: dict[str, Any] | None,
    llm_usage: list[dict[str, Any]] | None,
    capture_payloads: bool,
) -> dict[str, Any]:
    findings = findings or []
    actions = actions or []
    llm_usage = llm_usage or []
    payload: dict[str, Any] = {
        "run": {
            "run_id": run_row.get("run_id"),
            "automation_id": run_row.get("automation_id"),
            "agent_id": run_row.get("agent_id"),
            "agent_name": run_row.get("agent_name"),
            "status": run_row.get("status"),
            "mode": run_row.get("mode"),
            "prompt_version": run_row.get("prompt_version"),
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
        },
    }
    if capture_payloads:
        payload["payloads"] = {
            "findings": findings,
            "actions": actions,
            "context_pack": context_pack,
            "llm_usage": llm_usage,
        }
    return payload


def _get_langfuse_client() -> Any:
    from langfuse import Langfuse

    return Langfuse()


def emit_agent_trace(
    *,
    run_row: dict[str, Any],
    findings: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    context_pack: dict[str, Any] | None = None,
    llm_usage: list[dict[str, Any]] | None = None,
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
        capture_payloads=capture_payloads,
    )
    if error_message:
        metadata["error"] = {"message": error_message[:500]}

    try:
        client = _get_langfuse_client()
        trace = client.trace(
            id=trace_id or None,
            name=str(run_row.get("agent_id") or "agency_bigquery_agent"),
            user_id="codex-local",
            session_id=str(run_row.get("automation_id") or "manual"),
            metadata=metadata,
            tags=["bigquery-agency-memory", str(run_row.get("mode") or "unknown")],
        )
        if hasattr(trace, "update"):
            trace.update(
                output={
                    "status": run_row.get("status"),
                    "findings_count": len(findings or []),
                    "actions_count": len(actions or []),
                },
                level="ERROR" if error_message else "DEFAULT",
                status_message=error_message,
            )
        if flush and hasattr(client, "flush"):
            client.flush()
    except ImportError:
        return LangfuseTraceResult(status="skipped", enabled=True, trace_id=trace_id, message="langfuse package not installed")
    except Exception as exc:  # pragma: no cover - defensive: tracing must never break agent runs.
        return LangfuseTraceResult(status="failed", enabled=True, trace_id=trace_id, message=f"{exc.__class__.__name__}: {exc}")

    return LangfuseTraceResult(status="emitted", enabled=True, trace_id=trace_id)
