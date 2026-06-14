from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .agency_ops_ingestion import slugify


MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")
ALLOWED_FINDING_SEVERITIES = {"critical", "high", "medium", "low", "info"}
ALLOWED_ACTION_PRIORITIES = {"high", "medium", "low"}
ALLOWED_ACTION_STATUSES = {"suggested", "needs_review", "approved", "rejected", "completed", "ignored"}
ALLOWED_QA_STATUSES = {"approved", "needs_review", "rejected"}
ALLOWED_APPROVAL_DECISIONS = {"approved", "rejected", "ignored", "completed"}
EXTERNAL_TARGET_SYSTEMS = {"monday", "gmail", "outlook", "drive", "docs", "google_drive", "google_docs"}
SAFE_TARGET_SYSTEMS = {"bigquery", "local_report", "codex", "none"}
ALLOWED_TARGET_SYSTEMS = EXTERNAL_TARGET_SYSTEMS | SAFE_TARGET_SYSTEMS
CLIENT_SLUG_ALIASES = {
    "acorn-car-rentals": "acorn-rentals",
    "joe-rascal-ducati": "ducati-melbourne",
    "salad-servers": "salad-servers-direct",
}
AGENT_RUN_INDEX_SCHEMA_VERSION = 1

PROMISE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(i|we)([' ]?ll| will)\b",
        r"\bwe will\b",
        r"\bi will\b",
        r"\b(send|update|include|ask|review|prepare|come back|follow up|share|provide)\b",
        r"\bby (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week|eod|\d{1,2}[/-]\d{1,2})\b",
    )
]

UNCERTAIN_PROMISE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bcheck whether\b",
        r"\bconfirm whether\b",
        r"\bneeds follow[- ]?up\b",
        r"\bwaiting on us\b",
        r"\bshould (review|check|confirm)\b",
    )
]


class AgentValidationError(ValueError):
    """Raised when an agent finding/action cannot be safely logged."""


@dataclass(frozen=True)
class AgentPermissions:
    dry_run_default: bool = True
    allow_email_send: bool = False
    allow_email_draft_create: bool = False
    allow_monday_write: bool = False
    allow_drive_write: bool = False
    allow_drive_share: bool = False
    allow_external_publish: bool = False
    allow_bigquery_logging: bool = True
    require_approval_for_external_actions: bool = True
    allowed_bigquery_write_purposes: tuple[str, ...] = (
        "agent_run_log",
        "agent_findings",
        "agent_actions",
        "agent_approvals",
        "context_packs",
        "llm_usage_log",
        "seo_workflow_catalog",
        "seo_client_memory_summaries",
        "seo_workflow_run_summaries",
        "seo_workflow_readiness",
        "seo_opportunity_queue",
    )


def utc_now_iso() -> str:
    return datetime.now(MELBOURNE_TIMEZONE).isoformat()


def iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MELBOURNE_TIMEZONE)
    return parsed.astimezone(MELBOURNE_TIMEZONE).date().isoformat()


def stable_hash(value: Any, *, length: int = 32) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_agent_run_index(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        return {"schema_version": AGENT_RUN_INDEX_SCHEMA_VERSION, "runs": []}
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"schema_version": AGENT_RUN_INDEX_SCHEMA_VERSION, "runs": raw}
    if not isinstance(raw, dict):
        return {"schema_version": AGENT_RUN_INDEX_SCHEMA_VERSION, "runs": []}
    runs = raw.get("runs")
    if not isinstance(runs, list):
        runs = []
    return {"schema_version": raw.get("schema_version") or AGENT_RUN_INDEX_SCHEMA_VERSION, "runs": runs}


def upsert_agent_run_index(index_path: Path, run_entry: dict[str, Any]) -> dict[str, Any]:
    index = load_agent_run_index(index_path)
    run_id = str(run_entry.get("run_id") or "")
    agent_id = str(run_entry.get("agent_id") or "")
    runs = [
        existing
        for existing in index["runs"]
        if not (str(existing.get("run_id") or "") == run_id and str(existing.get("agent_id") or "") == agent_id)
    ]
    runs.append(run_entry)
    runs.sort(key=lambda item: str(item.get("started_at") or item.get("created_at") or ""), reverse=True)
    index["runs"] = runs
    write_json_atomic(index_path, index)
    return index


def agent_run_activity_entry(
    *,
    run_id: str,
    agent_id: str,
    agent_name: str,
    started_at: str,
    status: str,
    mode: str,
    dry_run: bool,
    automation_id: str | None = None,
    completed_at: str | None = None,
    prompt_version: str | None = None,
    context_id: str | None = None,
    input_sources: list[str] | None = None,
    output_path: str | None = None,
    run_json_path: str | None = None,
    brief_path: str | None = None,
    findings_count: int = 0,
    actions_count: int = 0,
    bigquery_logged: bool = False,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": AGENT_RUN_INDEX_SCHEMA_VERSION,
        "run_id": run_id,
        "automation_id": automation_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "started_at": started_at,
        "completed_at": completed_at,
        "run_date": iso_date(started_at),
        "status": status,
        "mode": mode,
        "prompt_version": prompt_version,
        "context_id": context_id,
        "input_sources_json": input_sources or [],
        "output_path": output_path,
        "run_json_path": run_json_path,
        "brief_path": brief_path,
        "findings_count": findings_count,
        "actions_count": actions_count,
        "dry_run": dry_run,
        "bigquery_logged": bigquery_logged,
        "error_message": error_message,
    }


def active_marker_path(active_dir: Path, agent_id: str) -> Path:
    return active_dir / f"{slugify(agent_id)}.json"


def mark_agent_run_started(index_path: Path, active_dir: Path, run_entry: dict[str, Any]) -> dict[str, Any]:
    marker = {**run_entry, "marker_path": str(active_marker_path(active_dir, str(run_entry.get("agent_id") or "agent")).resolve())}
    write_json_atomic(Path(marker["marker_path"]), marker)
    return upsert_agent_run_index(index_path, marker)


def mark_agent_run_completed(index_path: Path, active_dir: Path, run_entry: dict[str, Any]) -> dict[str, Any]:
    index = upsert_agent_run_index(index_path, run_entry)
    marker = active_marker_path(active_dir, str(run_entry.get("agent_id") or "agent"))
    if marker.exists():
        marker.unlink()
    return index


def load_active_agent_markers(active_dir: Path) -> list[dict[str, Any]]:
    if not active_dir.exists():
        return []
    markers: list[dict[str, Any]] = []
    for path in sorted(active_dir.glob("*.json")):
        try:
            marker = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            marker = {"agent_id": path.stem, "status": "unreadable_marker", "marker_path": str(path)}
        marker.setdefault("marker_path", str(path))
        markers.append(marker)
    return markers


def agent_activity_for_date(index_path: Path, active_dir: Path, activity_date: date) -> dict[str, Any]:
    index = load_agent_run_index(index_path)
    day = activity_date.isoformat()
    runs = [
        run for run in index.get("runs", [])
        if str(run.get("run_date") or iso_date(run.get("started_at"))) == day
    ]
    runs.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    active = load_active_agent_markers(active_dir)
    return {
        "date": day,
        "active_runs": active,
        "runs": runs,
        "metrics": {
            "active_runs": len(active),
            "runs_today": len(runs),
            "succeeded": sum(1 for run in runs if run.get("status") == "succeeded"),
            "failed": sum(1 for run in runs if run.get("status") == "failed"),
            "dry_runs": sum(1 for run in runs if run.get("dry_run")),
            "bigquery_logged": sum(1 for run in runs if run.get("bigquery_logged")),
        },
    }


def agent_activity_markdown(activity: dict[str, Any]) -> str:
    metrics = activity.get("metrics") or {}
    lines = [
        f"# Agent Activity - {activity.get('date')}",
        "",
        f"- Active runs: {metrics.get('active_runs', 0)}",
        f"- Runs today: {metrics.get('runs_today', 0)}",
        f"- Succeeded: {metrics.get('succeeded', 0)}",
        f"- Failed: {metrics.get('failed', 0)}",
        f"- Dry runs: {metrics.get('dry_runs', 0)}",
        f"- BigQuery logged: {metrics.get('bigquery_logged', 0)}",
        "",
        "## Active Runs",
    ]
    active = activity.get("active_runs") or []
    if active:
        for run in active:
            lines.append(f"- {run.get('agent_id')}: {run.get('run_id')} started {run.get('started_at')} ({run.get('mode')})")
    else:
        lines.append("- No active local run markers.")
    lines.extend(["", "## Runs"])
    runs = activity.get("runs") or []
    if runs:
        for run in runs:
            detail = run.get("output_path") or run.get("run_json_path") or "no output path"
            lines.append(f"- {run.get('agent_id')}: {run.get('status')} run {run.get('run_id')} ({run.get('findings_count', 0)} findings, {run.get('actions_count', 0)} actions) - {detail}")
    else:
        lines.append("- No indexed runs for this date.")
    return "\n".join(lines) + "\n"


def parse_bool_text(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on", "1"}:
        return True
    if lowered in {"false", "no", "off", "0"}:
        return False
    return None


def load_agent_permissions(path: Path) -> AgentPermissions:
    if not path.exists():
        return AgentPermissions()
    values: dict[str, bool] = {}
    lists: dict[str, list[str]] = {}
    current_list_key: str | None = None
    known_bool_keys = {
        "dry_run_default",
        "allow_email_send",
        "allow_email_draft_create",
        "allow_monday_write",
        "allow_drive_write",
        "allow_drive_share",
        "allow_external_publish",
        "allow_bigquery_logging",
        "require_approval_for_external_actions",
    }
    known_list_keys = {"allowed_bigquery_write_purposes"}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("- ") and current_list_key:
            lists.setdefault(current_list_key, []).append(line[2:].strip())
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if key in known_list_keys and not raw_value.strip():
            current_list_key = key
            lists.setdefault(key, [])
            continue
        if key not in known_bool_keys:
            parsed_unknown = parse_bool_text(raw_value)
            if key.startswith("allow_") and parsed_unknown:
                raise AgentValidationError(f"unknown enabled permission key is not allowed: {key}")
            continue
        parsed = parse_bool_text(raw_value)
        if parsed is not None:
            values[key] = parsed
    return AgentPermissions(
        dry_run_default=values.get("dry_run_default", True),
        allow_email_send=values.get("allow_email_send", False),
        allow_email_draft_create=values.get("allow_email_draft_create", False),
        allow_monday_write=values.get("allow_monday_write", False),
        allow_drive_write=values.get("allow_drive_write", False),
        allow_drive_share=values.get("allow_drive_share", False),
        allow_external_publish=values.get("allow_external_publish", False),
        allow_bigquery_logging=values.get("allow_bigquery_logging", True),
        require_approval_for_external_actions=values.get("require_approval_for_external_actions", True),
        allowed_bigquery_write_purposes=tuple(lists.get("allowed_bigquery_write_purposes") or AgentPermissions().allowed_bigquery_write_purposes),
    )


def validate_permissions_safe_default(permissions: AgentPermissions) -> None:
    unsafe = []
    if not permissions.dry_run_default:
        unsafe.append("dry_run_default must stay true for this MVP")
    if permissions.allow_email_send:
        unsafe.append("allow_email_send must stay false")
    if permissions.allow_email_draft_create:
        unsafe.append("allow_email_draft_create must stay false until draft approval workflows exist")
    if permissions.allow_monday_write:
        unsafe.append("allow_monday_write must stay false")
    if permissions.allow_drive_write:
        unsafe.append("allow_drive_write must stay false")
    if permissions.allow_drive_share:
        unsafe.append("allow_drive_share must stay false")
    if permissions.allow_external_publish:
        unsafe.append("allow_external_publish must stay false")
    if not permissions.require_approval_for_external_actions:
        unsafe.append("require_approval_for_external_actions must stay true")
    if unsafe:
        raise AgentValidationError("; ".join(unsafe))


FORBIDDEN_CONTEXT_KEY_PATTERNS = (
    "raw",
    "body",
    "message",
    "comment",
    "description",
    "private",
    "note",
    "notes",
    "email",
    "token",
    "secret",
    "password",
    "credential",
    "cookie",
    "authorization",
)


def sanitize_context_value(value: Any, *, depth: int = 0, max_list_items: int = 50, max_string_length: int = 500) -> Any:
    if depth > 6:
        return "[truncated_depth]"
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(pattern in lowered for pattern in FORBIDDEN_CONTEXT_KEY_PATTERNS):
                continue
            cleaned[key_text] = sanitize_context_value(
                child,
                depth=depth + 1,
                max_list_items=max_list_items,
                max_string_length=max_string_length,
            )
        return cleaned
    if isinstance(value, list):
        return [
            sanitize_context_value(
                item,
                depth=depth + 1,
                max_list_items=max_list_items,
                max_string_length=max_string_length,
            )
            for item in value[:max_list_items]
        ]
    if isinstance(value, str):
        return value[:max_string_length]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_string_length]


def sanitize_context_pack_sections(sections: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_context_value(sections)
    if not isinstance(sanitized, dict):
        raise AgentValidationError("context pack sections must sanitize to a dict")
    return sanitized


def clean_client_slug(value: Any) -> str:
    slug = slugify(str(value or ""))
    return CLIENT_SLUG_ALIASES.get(slug, slug)


def task_hygiene_issues(row: dict[str, Any], *, today: date | None = None) -> list[str]:
    issues: list[str] = []
    raw_slug = slugify(str(row.get("client_slug") or ""))
    if not raw_slug:
        issues.append("missing_client_mapping")
    elif raw_slug in CLIENT_SLUG_ALIASES:
        issues.append("client_alias_needs_normalisation")
    elif raw_slug in {"content-board", "seo-tasks", "uncategorised", "uncategorized"}:
        issues.append("non_client_board_mapping")
    item_name = str(row.get("item_name") or row.get("item_title") or "").strip()
    if not item_name:
        issues.append("empty_task_name")
    if not str(row.get("owner") or "").strip():
        issues.append("missing_owner")
    if not row.get("due_date"):
        issues.append("missing_due_date")
    if row.get("due_date") and today:
        try:
            due = date.fromisoformat(str(row.get("due_date"))[:10])
        except ValueError:
            due = None
        if due and due < today:
            issues.append("stale_or_overdue_due_date")
    status = str(row.get("normalized_status") or row.get("delivery_status") or row.get("status") or "").strip().lower()
    if not status:
        issues.append("missing_status")
    return issues


def evidence_hashes(evidence: list[dict[str, Any]]) -> list[str]:
    return [stable_hash(item) for item in evidence]


def normalize_finding(payload: dict[str, Any], *, run_id: str, agent_id: str, created_at: str | None = None) -> dict[str, Any]:
    client_slug = clean_client_slug(payload.get("client_slug") or payload.get("client_id"))
    summary = str(payload.get("summary") or "").strip()
    evidence = payload.get("evidence") or payload.get("evidence_json") or []
    if not isinstance(evidence, list):
        raise AgentValidationError("finding evidence must be a list")
    severity = str(payload.get("severity") or "medium").strip().lower()
    qa_status = str(payload.get("qa_status") or "needs_review").strip().lower()
    confidence = float(payload.get("confidence_score") if payload.get("confidence_score") is not None else 0.5)

    errors = []
    if not client_slug:
        errors.append("finding requires client_slug")
    if not summary:
        errors.append("finding requires summary")
    if not evidence:
        errors.append("finding requires evidence")
    if severity not in ALLOWED_FINDING_SEVERITIES:
        errors.append(f"invalid finding severity: {severity}")
    if qa_status not in ALLOWED_QA_STATUSES:
        errors.append(f"invalid qa_status: {qa_status}")
    if confidence < 0 or confidence > 1:
        errors.append("confidence_score must be between 0 and 1")
    if errors:
        raise AgentValidationError("; ".join(errors))

    source_tables = payload.get("source_tables") or payload.get("source_tables_json") or []
    if not isinstance(source_tables, list):
        source_tables = [str(source_tables)]
    finding_id = payload.get("finding_id") or stable_hash(
        {
            "run_id": run_id,
            "agent_id": agent_id,
            "client_slug": client_slug,
            "summary": summary,
            "evidence": evidence_hashes(evidence),
        }
    )
    return {
        "created_at": created_at or utc_now_iso(),
        "run_id": run_id,
        "agent_id": agent_id,
        "finding_id": finding_id,
        "client_slug": client_slug,
        "finding_type": str(payload.get("finding_type") or "general").strip().lower(),
        "severity": severity,
        "summary": summary,
        "evidence_json": evidence,
        "source_tables_json": source_tables,
        "recommended_action": str(payload.get("recommended_action") or "").strip() or None,
        "confidence_score": confidence,
        "requires_human_review": bool(payload.get("requires_human_review", True)),
        "qa_status": qa_status,
        "status": str(payload.get("status") or "open").strip().lower(),
        "source_ref_hash": stable_hash(evidence_hashes(evidence)),
    }


def normalize_action(payload: dict[str, Any], *, run_id: str, agent_id: str, created_at: str | None = None) -> dict[str, Any]:
    client_slug = clean_client_slug(payload.get("client_slug") or payload.get("client_id"))
    recommended_action = str(payload.get("recommended_action") or "").strip()
    target_system = str(payload.get("target_system") or "none").strip().lower()
    status = str(payload.get("status") or "suggested").strip().lower()
    priority = str(payload.get("priority") or "medium").strip().lower()
    evidence = payload.get("evidence") or payload.get("evidence_json") or []
    if not isinstance(evidence, list):
        raise AgentValidationError("action evidence must be a list")
    requires_approval = bool(payload.get("requires_approval", target_system in EXTERNAL_TARGET_SYSTEMS))

    errors = []
    if not client_slug:
        errors.append("action requires client_slug")
    if not recommended_action:
        errors.append("action requires recommended_action")
    if not evidence:
        errors.append("action requires evidence")
    if target_system not in ALLOWED_TARGET_SYSTEMS:
        errors.append(f"invalid target_system: {target_system}")
    if status not in ALLOWED_ACTION_STATUSES:
        errors.append(f"invalid action status: {status}")
    if priority not in ALLOWED_ACTION_PRIORITIES:
        errors.append(f"invalid priority: {priority}")
    if target_system in EXTERNAL_TARGET_SYSTEMS and not requires_approval:
        errors.append(f"{target_system} actions require approval")
    if errors:
        raise AgentValidationError("; ".join(errors))

    action_id = payload.get("action_id") or stable_hash(
        {
            "run_id": run_id,
            "agent_id": agent_id,
            "client_slug": client_slug,
            "target_system": target_system,
            "recommended_action": recommended_action,
        }
    )
    return {
        "created_at": created_at or utc_now_iso(),
        "run_id": run_id,
        "agent_id": agent_id,
        "action_id": action_id,
        "finding_id": payload.get("finding_id"),
        "client_slug": client_slug,
        "action_type": str(payload.get("action_type") or "review").strip().lower(),
        "target_system": target_system,
        "recommended_action": recommended_action,
        "priority": priority,
        "status": status,
        "requires_approval": requires_approval,
        "evidence_json": evidence,
        "due_hint": str(payload.get("due_hint") or "").strip() or None,
        "owner_hint": str(payload.get("owner_hint") or "").strip() or None,
        "approval_id": payload.get("approval_id"),
    }


def approval_decision_to_action_status(decision: str) -> str:
    cleaned = decision.strip().lower()
    if cleaned not in ALLOWED_APPROVAL_DECISIONS:
        raise AgentValidationError(f"invalid approval decision: {cleaned}")
    return cleaned


def build_agent_approval_row(
    *,
    approval_id: str | None = None,
    action_id: str,
    run_id: str,
    client_slug: str,
    decision: str,
    decided_by: str,
    reason: str | None = None,
    notes: str | None = None,
    source_system: str = "codex",
    decided_at: str | None = None,
) -> dict[str, Any]:
    clean_decision = approval_decision_to_action_status(decision)
    normalized_client_slug = clean_client_slug(client_slug)
    errors = []
    if not action_id:
        errors.append("approval requires action_id")
    if not run_id:
        errors.append("approval requires run_id")
    if not normalized_client_slug:
        errors.append("approval requires client_slug")
    if not decided_by.strip():
        errors.append("approval requires decided_by")
    if errors:
        raise AgentValidationError("; ".join(errors))
    effective_approval_id = approval_id or stable_hash(
        {
            "action_id": action_id,
            "run_id": run_id,
            "client_slug": normalized_client_slug,
            "decision": clean_decision,
            "decided_by": decided_by,
        }
    )
    return {
        "decided_at": decided_at or utc_now_iso(),
        "approval_id": effective_approval_id,
        "action_id": action_id,
        "run_id": run_id,
        "client_slug": normalized_client_slug,
        "decision": clean_decision,
        "decided_by": decided_by.strip(),
        "reason": (reason or "").strip() or None,
        "notes": (notes or "").strip() or None,
        "source_system": source_system,
    }


def validate_agent_output(output: dict[str, Any]) -> dict[str, Any]:
    run_id = str(output.get("run_id") or "").strip()
    agent_id = str(output.get("agent_id") or "").strip()
    if not run_id:
        raise AgentValidationError("output requires run_id")
    if not agent_id:
        raise AgentValidationError("output requires agent_id")
    created_at = str(output.get("created_at") or utc_now_iso())
    findings = [
        normalize_finding(finding, run_id=run_id, agent_id=agent_id, created_at=created_at)
        for finding in output.get("findings", [])
    ]
    actions = [
        normalize_action(action, run_id=run_id, agent_id=agent_id, created_at=created_at)
        for action in output.get("actions", [])
    ]
    return {
        **output,
        "run_id": run_id,
        "agent_id": agent_id,
        "created_at": created_at,
        "findings": findings,
        "actions": actions,
    }


def looks_like_promise(row: dict[str, Any]) -> tuple[bool, str, float]:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("summary", "recommended_action", "due_hint", "category", "signal_type")
    )
    strong_matches = sum(1 for pattern in PROMISE_PATTERNS if pattern.search(text))
    uncertain_matches = sum(1 for pattern in UNCERTAIN_PROMISE_PATTERNS if pattern.search(text))
    waiting_on_us = bool(row.get("waiting_on_us")) or str(row.get("thread_status") or "").lower() == "waiting_on_us"
    if uncertain_matches and strong_matches < 2:
        return True, "needs_review", 0.58 if waiting_on_us else 0.52
    if strong_matches >= 2 or (strong_matches >= 1 and waiting_on_us):
        return True, "high_confidence", min(0.95, 0.72 + (0.06 * strong_matches))
    if strong_matches or uncertain_matches or waiting_on_us:
        return True, "needs_review", 0.58 if uncertain_matches or waiting_on_us else 0.52
    return False, "ignored", 0.0


def promise_tracker_output(
    comms_rows: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    created_at: str | None = None,
    agent_id: str = "promise_tracker",
    limit: int | None = None,
) -> dict[str, Any]:
    effective_run_id = run_id or uuid4().hex
    effective_created_at = created_at or utc_now_iso()
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    considered = comms_rows[:limit] if limit else comms_rows

    for row in considered:
        is_promise, review_status, confidence = looks_like_promise(row)
        if not is_promise:
            continue
        client_slug = clean_client_slug(row.get("client_slug") or row.get("client_id"))
        if not client_slug:
            continue
        summary = str(row.get("summary") or row.get("recommended_action") or "").strip()
        recommended = str(row.get("recommended_action") or "Review this commitment and confirm the next action.").strip()
        evidence = [
            {
                "source": row.get("source_table") or row.get("source") or "summarized_comms",
                "client_slug": client_slug,
                "week_start": row.get("week_start"),
                "week_end": row.get("week_end"),
                "thread_ref_hash": row.get("thread_ref_hash") or row.get("effective_thread_ref_hash"),
                "summary": summary[:360],
            }
        ]
        severity = "medium" if review_status == "high_confidence" else "low"
        finding_payload = {
            "client_slug": client_slug,
            "finding_type": "promise",
            "severity": severity,
            "summary": f"Potential client commitment: {summary}",
            "evidence": evidence,
            "source_tables": [str(row.get("source_table") or "agency_reporting.client_comms_attention")],
            "recommended_action": recommended,
            "confidence_score": confidence,
            "requires_human_review": review_status != "high_confidence",
            "qa_status": "needs_review",
        }
        finding = normalize_finding(finding_payload, run_id=effective_run_id, agent_id=agent_id, created_at=effective_created_at)
        action_payload = {
            "client_slug": client_slug,
            "finding_id": finding["finding_id"],
            "action_type": "promise_follow_up",
            "target_system": "monday",
            "recommended_action": recommended,
            "priority": "high" if row.get("urgency") == "high" else "medium",
            "status": "suggested" if review_status == "high_confidence" else "needs_review",
            "requires_approval": True,
            "evidence": evidence,
            "due_hint": row.get("due_hint"),
            "owner_hint": row.get("owner_hint"),
        }
        findings.append(finding)
        actions.append(normalize_action(action_payload, run_id=effective_run_id, agent_id=agent_id, created_at=effective_created_at))

    output = {
        "run_id": effective_run_id,
        "agent_id": agent_id,
        "created_at": effective_created_at,
        "summary": f"Reviewed {len(considered)} summarized comms row(s) and found {len(findings)} possible promise(s).",
        "findings": findings,
        "actions": actions,
        "metrics": {
            "rows_reviewed": len(considered),
            "promises_found": len(findings),
            "actions_suggested": len(actions),
        },
    }
    return validate_agent_output(output)


def qa_guardrail_output(output: dict[str, Any]) -> dict[str, Any]:
    validated = validate_agent_output(output)
    seen_actions: set[tuple[str, str, str]] = set()
    checked_actions = []
    for action in validated["actions"]:
        key = (action["client_slug"], action["target_system"], action["recommended_action"].lower())
        if key in seen_actions:
            action = {**action, "status": "needs_review"}
        seen_actions.add(key)
        checked_actions.append(action)
    validated["actions"] = checked_actions
    return validated


def build_agent_run_row(
    *,
    run_id: str,
    agent_id: str,
    agent_name: str,
    started_at: str,
    completed_at: str,
    status: str,
    mode: str,
    prompt_version: str | None,
    context_id: str | None,
    input_sources: list[str],
    output_path: str | None,
    findings_count: int,
    actions_count: int,
    dry_run: bool,
    automation_id: str | None = None,
    bigquery_write_status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "automation_id": automation_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "mode": mode,
        "prompt_version": prompt_version,
        "context_id": context_id,
        "input_sources_json": input_sources,
        "output_path": output_path,
        "findings_count": findings_count,
        "actions_count": actions_count,
        "error_message": error_message,
        "dry_run": dry_run,
        "bigquery_write_status": bigquery_write_status,
    }


def build_context_pack(
    *,
    agent_id: str,
    sections: dict[str, Any],
    source_tables: list[str],
    client_slug: str | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
    task_type: str | None = None,
) -> dict[str, Any]:
    effective_run_id = run_id or uuid4().hex
    effective_created_at = created_at or utc_now_iso()
    safe_client = clean_client_slug(client_slug) if client_slug else None
    context_id = stable_hash(
        {
            "agent_id": agent_id,
            "client_slug": safe_client,
            "run_id": effective_run_id,
            "source_tables": source_tables,
        }
    )
    return {
        "created_at": effective_created_at,
        "context_id": context_id,
        "run_id": effective_run_id,
        "agent_id": agent_id,
        "client_slug": safe_client,
        "task_type": task_type or agent_id,
        "sections_json": sanitize_context_pack_sections(sections),
        "source_tables_json": source_tables,
        "source_ref_hash": stable_hash(source_tables),
        "retention_hint": "operational_summary",
    }


def daily_brief_markdown(
    *,
    brief_date: date,
    client_health: list[dict[str, Any]],
    delivery_items: list[dict[str, Any]],
    promise_output: dict[str, Any],
    recent_findings: list[dict[str, Any]] | None = None,
    recent_actions: list[dict[str, Any]] | None = None,
    seo_readiness: list[dict[str, Any]] | None = None,
    seo_opportunities: list[dict[str, Any]] | None = None,
    seo_workflow_summaries: list[dict[str, Any]] | None = None,
    activity: dict[str, Any] | None = None,
) -> str:
    recent_findings = recent_findings or []
    recent_actions = recent_actions or []
    seo_readiness = seo_readiness or []
    seo_opportunities = seo_opportunities or []
    seo_workflow_summaries = seo_workflow_summaries or []
    promise_findings = promise_output.get("findings", [])
    promise_actions = promise_output.get("actions", [])
    hygiene_findings = [finding for finding in recent_findings if finding.get("finding_type") == "monday_hygiene"]
    red_or_amber = [
        row for row in client_health
        if str(row.get("health_status") or row.get("status") or "").lower() in {"critical_missing", "needs_attention", "red", "amber", "partial"}
    ]
    monday_hygiene = [
        row for row in delivery_items
        if task_hygiene_issues(row, today=brief_date)
    ]
    approval_actions = [
        action for action in [*promise_actions, *recent_actions]
        if action.get("requires_approval")
    ]

    lines = [
        f"# Daily Agency Brief - {brief_date.isoformat()}",
        "",
        "## Focus Today",
    ]
    if red_or_amber or promise_findings or monday_hygiene:
        hygiene_text = f"{len(monday_hygiene)} Monday hygiene row(s)"
        if hygiene_findings:
            hygiene_text = f"{len(monday_hygiene)} Monday hygiene row(s), grouped into {len(hygiene_findings)} review finding(s)"
        lines.append(f"- Review {len(red_or_amber)} client health item(s), {len(promise_findings)} promise item(s), and {hygiene_text}.")
    else:
        lines.append("- No urgent client health, promise, or Monday hygiene items were found in the available dry-run context.")

    lines.extend(["", "## Client Health"])
    if red_or_amber:
        for row in red_or_amber[:15]:
            lines.append(f"- {row.get('client_slug')}: {row.get('health_status') or row.get('status')} - {row.get('critical_missing_assets') or row.get('missing_required_assets') or 'review setup health'}")
    else:
        lines.append("- No red/amber client health rows in the available context.")

    lines.extend(["", "## Promises And Follow-Ups"])
    if promise_findings:
        for finding in promise_findings[:15]:
            lines.append(f"- {finding['client_slug']}: {finding['summary']} ({finding['qa_status']}, confidence {finding['confidence_score']:.2f})")
    else:
        lines.append("- No likely promises found in the available summarized comms.")

    lines.extend(["", "## Monday Hygiene"])
    if hygiene_findings:
        for finding in hygiene_findings[:15]:
            lines.append(f"- {finding['client_slug']}: {finding['summary']} ({finding['severity']})")
    elif monday_hygiene:
        for row in monday_hygiene[:20]:
            label = row.get("item_name") or row.get("item_title") or row.get("task") or "Delivery item"
            client_slug = clean_client_slug(row.get("client_slug"))
            issues = ", ".join(task_hygiene_issues(row, today=brief_date))
            lines.append(f"- {client_slug or 'unmapped'}: {label} due {row.get('due_date') or 'no due date'} ({row.get('normalized_status') or row.get('delivery_status') or row.get('status') or 'unknown'}; {issues})")
    else:
        lines.append("- No Monday hygiene issues in the available context.")

    lines.extend(["", "## SEO Automation Workflows"])
    readiness_warnings = [
        row for row in seo_readiness
        if str(row.get("readiness_status") or "").lower() in {"blocked", "needs_attention", "missing", "partial"}
    ]
    if readiness_warnings:
        for row in readiness_warnings[:12]:
            missing = row.get("missing_inputs_json") or []
            if isinstance(missing, str):
                missing_text = missing
            else:
                missing_text = ", ".join(str(item) for item in missing[:8])
            lines.append(
                f"- {row.get('client_slug')}: {row.get('readiness_status')} for SEO Automation workflows"
                f" ({missing_text or 'review required'})."
            )
    else:
        lines.append("- No SEO Automation readiness blockers were included in this run.")
    if seo_opportunities:
        lines.append("- Recommended SEO workflow focus:")
        for row in seo_opportunities[:10]:
            lines.append(
                f"  - {row.get('client_slug')}: {row.get('workflow_id')} - {row.get('summary') or row.get('recommended_action')}"
            )
    if seo_workflow_summaries:
        lines.append("- Recent SEO Automation workflow summaries:")
        for row in seo_workflow_summaries[:8]:
            lines.append(f"  - {row.get('client_slug')}: {row.get('workflow_id')} {row.get('status')} - {row.get('summary')}")

    lines.extend(["", "## Suggested Actions"])
    suggested = [*promise_actions, *recent_actions]
    if suggested:
        for action in suggested[:20]:
            approval = "approval required" if action.get("requires_approval") else "no external approval needed"
            lines.append(f"- {action['client_slug']}: {action['recommended_action']} [{action['target_system']}, {action['status']}, {approval}]")
    else:
        lines.append("- No suggested actions were generated.")

    lines.extend(["", "## Actions Needing Approval"])
    if approval_actions:
        for action in approval_actions[:20]:
            lines.append(f"- {action['client_slug']}: {action['recommended_action']} -> {action['target_system']}")
    else:
        lines.append("- No approval-gated actions in the available context.")

    lines.extend(["", "## Recent Findings"])
    if recent_findings:
        for finding in recent_findings[:15]:
            lines.append(f"- {finding.get('client_slug')}: {finding.get('summary')} ({finding.get('severity')})")
    else:
        lines.append("- No previous findings were included in this run.")

    lines.extend(["", "## Agent Activity Visibility"])
    if activity:
        metrics = activity.get("metrics") or {}
        lines.append(
            f"- Local runs today: {metrics.get('runs_today', 0)} indexed, {metrics.get('active_runs', 0)} active marker(s), {metrics.get('failed', 0)} failed."
        )
        for run in (activity.get("runs") or [])[:8]:
            output_path = run.get("output_path") or run.get("run_json_path") or "no output path"
            automation = f", automation {run.get('automation_id')}" if run.get("automation_id") else ""
            lines.append(f"- {run.get('agent_id')}: {run.get('status')} run {run.get('run_id')}{automation} - {output_path}")
    else:
        lines.append("- Local activity index was not available for this brief run.")

    lines.extend(
        [
            "",
            "## Safety Notes",
            "- This brief is generated from approved summaries and existing reporting data.",
            "- It does not send emails, create Monday tasks, share Drive files, or publish client-facing output.",
        ]
    )
    return "\n".join(lines) + "\n"
