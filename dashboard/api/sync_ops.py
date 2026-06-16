from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Any, Callable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")
DEFAULT_ENV_PATH = Path("/Users/laurencedeer/Projects/Codex/SEO Automation/.env")
MONDAY_HUB_ROOT = Path("/Users/laurencedeer/Projects/Codex/monday-agency-hub")
SYNC_STATE_ROOT = PROJECT_ROOT / "data" / "sync_ops"
COMMANDS_PATH = SYNC_STATE_ROOT / "commands" / "index.jsonl"
RUNS_ROOT = SYNC_STATE_ROOT / "runs"
MELBOURNE_TZ_NAME = "Australia/Melbourne"
_STATE_LOCK = threading.Lock()

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|private[_-]?key|authorization)(\s*[=:]\s*)[^\s\"']+"),
    re.compile(r"(?i)(GOOGLE_APPLICATION_CREDENTIALS|GOOGLE_CLOUD_PROJECT)(\s*[=:]\s*)[^\s\"']+"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----", re.DOTALL),
]


class SyncValidationError(ValueError):
    """Raised when a sync request cannot be safely converted to a command."""


@dataclass(frozen=True)
class SyncDefinition:
    sync_id: str
    label: str
    category: str
    risk_level: str
    source_system: str
    destination_layer: str
    cadence: str
    supports_dry_run: bool
    supports_live_run: bool
    supports_client_scope: bool = False
    supports_table_scope: bool = False
    supports_ensure_tables: bool = False
    requires_input_path: bool = False
    confirmation_text: str = ""
    expected_logs: tuple[str, ...] = ()
    notes: str = ""
    plain_english: str = ""
    simple_group: str = ""
    master_step_ids: tuple[str, ...] = ()


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def registry() -> dict[str, SyncDefinition]:
    return {
        "master_sync": SyncDefinition(
            sync_id="master_sync",
            label="Master Sync",
            category="Master",
            risk_level="high",
            source_system="approved local source snapshots and AgencyOS scripts",
            destination_layer="local snapshots, agency memory, reporting marts, and agent logs",
            cadence="when you want the dashboard brought up to date end-to-end",
            supports_dry_run=True,
            supports_live_run=True,
            supports_ensure_tables=True,
            confirmation_text="RUN MASTER SYNC",
            expected_logs=("local sync_ops run file", "agency_control.ingestion_runs", "agency_control.cost_checks", "agency_control.agent_run_log"),
            notes="Runs the normal keep-the-system-current sequence. Heavy monthly API backfills and crawl imports stay manual.",
            plain_english="One button to refresh the operating picture: Monday snapshot, BigQuery agency memory, SEO workflow/client memory, finance, and the system-admin agent.",
            simple_group="Master",
            master_step_ids=("monday_state_refresh", "agency_ops_ingest", "seo_catalog_sync", "seo_client_memory_sync", "finance_sync", "agent_work_update"),
        ),
        "monday_state_refresh": SyncDefinition(
            sync_id="monday_state_refresh",
            label="Monday State Refresh",
            category="Monday",
            risk_level="medium",
            source_system="monday-agency-hub local snapshot",
            destination_layer="local snapshot",
            cadence="before agency ops ingestion",
            supports_dry_run=False,
            supports_live_run=True,
            confirmation_text="REFRESH MONDAY SNAPSHOT",
            expected_logs=("local sync_ops run file",),
            notes="Reads Monday metadata into the local monday-agency-hub snapshot only; no Monday writes.",
            plain_english="Refreshes the local Monday snapshot so tasks, statuses, owners, due dates, retainers, and expenses start from the latest Monday state.",
            simple_group="Monday",
        ),
        "agency_ops_ingest": SyncDefinition(
            sync_id="agency_ops_ingest",
            label="Agency Ops BigQuery Ingest",
            category="BigQuery",
            risk_level="high",
            source_system="local Monday, SEO Automation, reporting snapshots",
            destination_layer="agency_memory and agency_reporting",
            cadence="after source snapshots change",
            supports_dry_run=True,
            supports_live_run=True,
            supports_ensure_tables=True,
            confirmation_text="LOAD AGENCY OPS",
            expected_logs=("agency_control.ingestion_runs", "agency_control.cost_checks"),
            plain_english="Pushes sanitized local agency state into BigQuery and rebuilds the reporting tables the dashboard reads.",
            simple_group="BigQuery",
        ),
        "seo_catalog_sync": SyncDefinition(
            sync_id="seo_catalog_sync",
            label="SEO Workflow Catalog Sync",
            category="BigQuery",
            risk_level="medium",
            source_system="SEO Automation workflow docs",
            destination_layer="agency_memory.seo_workflow_catalog",
            cadence="when workflow docs change",
            supports_dry_run=True,
            supports_live_run=True,
            supports_ensure_tables=True,
            confirmation_text="SYNC SEO CATALOG",
            expected_logs=("agency_control.cost_checks",),
            plain_english="Updates BigQuery with the available SEO workflows, required inputs, scripts, validators, and safety gates.",
            simple_group="SEO Memory",
        ),
        "seo_client_memory_sync": SyncDefinition(
            sync_id="seo_client_memory_sync",
            label="SEO Client Memory Sync",
            category="BigQuery",
            risk_level="medium",
            source_system="SEO Automation client briefs and sidecars",
            destination_layer="agency_memory and agency_reporting workflow tables",
            cadence="when client routing changes",
            supports_dry_run=True,
            supports_live_run=True,
            supports_client_scope=True,
            supports_ensure_tables=True,
            confirmation_text="SYNC CLIENT MEMORY",
            expected_logs=("agency_control.cost_checks",),
            plain_english="Updates sanitized client routing and readiness memory from SEO Automation briefs and sidecars.",
            simple_group="SEO Memory",
        ),
        "finance_sync": SyncDefinition(
            sync_id="finance_sync",
            label="Finance Sync",
            category="Finance",
            risk_level="high",
            source_system="local finance JSON and Monday board snapshot",
            destination_layer="agency_memory finance tables",
            cadence="monthly or after retainer updates",
            supports_dry_run=True,
            supports_live_run=True,
            confirmation_text="LOAD FINANCE",
            expected_logs=("agency_control.ingestion_runs",),
            plain_english="Loads retainers and operating expenses from the approved local finance and Monday snapshot sources.",
            simple_group="Finance",
        ),
        "monthly_api_snapshots": SyncDefinition(
            sync_id="monthly_api_snapshots",
            label="Monthly API Snapshots",
            category="API Checks",
            risk_level="high",
            source_system="GA4, Search Console, SE Ranking",
            destination_layer="agency_memory monthly performance tables",
            cadence="monthly",
            supports_dry_run=True,
            supports_live_run=True,
            supports_client_scope=True,
            confirmation_text="LOAD MONTHLY API SNAPSHOTS",
            expected_logs=("agency_control.ingestion_runs", "agency_control.cost_checks"),
            notes="Read-only external APIs; writes sanitized monthly summaries to BigQuery.",
            plain_english="Pulls monthly GA4, Search Console, and SE Ranking summaries. Use when refreshing performance history, not for every quick dashboard refresh.",
            simple_group="Performance APIs",
        ),
        "api_smoke_checks": SyncDefinition(
            sync_id="api_smoke_checks",
            label="Reporting API Smoke Checks",
            category="API Checks",
            risk_level="medium",
            source_system="GA4, Search Console, SE Ranking",
            destination_layer="agency_control.api_smoke_checks",
            cadence="weekly or before reporting",
            supports_dry_run=True,
            supports_live_run=True,
            supports_client_scope=True,
            confirmation_text="LOG API SMOKE CHECKS",
            expected_logs=("agency_control.api_smoke_checks",),
            plain_english="Checks whether GA4, Search Console, and SE Ranking routes still respond for a client, then logs sanitized pass/fail evidence.",
            simple_group="Performance APIs",
        ),
        "crawl_memory_load": SyncDefinition(
            sync_id="crawl_memory_load",
            label="Crawl Memory Load",
            category="Crawls",
            risk_level="high",
            source_system="sanitized Screaming Frog export directory",
            destination_layer="agency_memory crawl tables",
            cadence="after approved crawl export",
            supports_dry_run=True,
            supports_live_run=True,
            supports_client_scope=True,
            supports_ensure_tables=True,
            requires_input_path=True,
            confirmation_text="LOAD CRAWL MEMORY",
            expected_logs=("agency_control.cost_checks",),
            plain_english="Imports an approved sanitized Screaming Frog export into crawl memory. Needs a crawl export path and crawl ID.",
            simple_group="Crawls",
        ),
        "agent_work_update": SyncDefinition(
            sync_id="agent_work_update",
            label="Agent Work Update",
            category="Agents",
            risk_level="medium",
            source_system="approved local AgencyOS agents",
            destination_layer="agent operating logs",
            cadence="daily or weekly",
            supports_dry_run=True,
            supports_live_run=True,
            supports_client_scope=True,
            supports_ensure_tables=True,
            confirmation_text="LOG AGENT WORK",
            expected_logs=("agency_control.agent_run_log", "agency_memory.agent_findings", "agency_memory.agent_actions"),
            plain_english="Runs an approved AgencyOS agent and logs its findings/actions so the dashboard reflects recent agent work.",
            simple_group="Agents",
        ),
    }


def public_registry() -> list[dict[str, Any]]:
    return [asdict(definition) for definition in registry().values()]


def redact_text(value: str, max_chars: int = 12000) -> str:
    text = value[-max_chars:]
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    return text


def _clean_slug(value: Any) -> str:
    slug = str(value or "").strip().lower()
    if not slug:
        return ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,80}", slug):
        raise SyncValidationError("client_slug contains unsupported characters")
    return slug


def _safe_path(value: Any) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    allowed_roots = (
        PROJECT_ROOT,
        Path("/Users/laurencedeer/Projects/Codex/SEO Automation").resolve(),
        Path("/Users/laurencedeer/Projects/Codex/seo-reporting-platform").resolve(),
    )
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise SyncValidationError("input_path must stay inside an approved project folder")
    return resolved


def build_command(sync_id: str, mode: str, options: dict[str, Any] | None = None) -> tuple[list[str], Path]:
    options = options or {}
    definitions = registry()
    if sync_id not in definitions:
        raise SyncValidationError("Unknown sync_id")
    definition = definitions[sync_id]
    if mode not in {"dry_run", "live"}:
        raise SyncValidationError("mode must be dry_run or live")
    if mode == "dry_run" and not definition.supports_dry_run:
        raise SyncValidationError(f"{sync_id} does not support dry run")
    if mode == "live" and not definition.supports_live_run:
        raise SyncValidationError(f"{sync_id} does not support live run")

    client_slug = _clean_slug(options.get("client_slug"))
    ensure_tables = bool(options.get("ensure_tables"))
    if client_slug and not definition.supports_client_scope:
        raise SyncValidationError(f"{sync_id} does not support client scope")
    if ensure_tables and not definition.supports_ensure_tables:
        raise SyncValidationError(f"{sync_id} does not support ensure_tables")

    if sync_id == "master_sync":
        return ([PYTHON, "-c", "print('Master Sync runs allowlisted child steps; see step_results in the run file.')"], PROJECT_ROOT)
    if sync_id == "monday_state_refresh":
        return (["./scripts/map_workspace.sh"], MONDAY_HUB_ROOT)

    command: list[str]
    cwd = PROJECT_ROOT
    if sync_id == "agency_ops_ingest":
        command = [PYTHON, "scripts/ingest_agency_ops.py"]
        command.append("--local-dry-run" if mode == "dry_run" else "--load-env")
        if mode == "live":
            command.append(str(DEFAULT_ENV_PATH))
        if ensure_tables and mode == "live":
            command.append("--ensure-only")
    elif sync_id == "seo_catalog_sync":
        command = [PYTHON, "scripts/sync_seo_automation_catalog.py"]
        if mode == "dry_run":
            command.append("--dry-run")
        else:
            command.extend(["--write-bigquery", "--load-env", str(DEFAULT_ENV_PATH)])
            if ensure_tables:
                command.append("--ensure-tables")
    elif sync_id == "seo_client_memory_sync":
        command = [PYTHON, "scripts/sync_seo_client_memory.py"]
        if mode == "dry_run":
            command.append("--dry-run")
        else:
            command.extend(["--write-bigquery", "--load-env", str(DEFAULT_ENV_PATH)])
            if ensure_tables:
                command.append("--ensure-tables")
        if client_slug:
            command.extend(["--client-slug", client_slug])
    elif sync_id == "finance_sync":
        command = [PYTHON, "scripts/load_client_finance.py"]
        if mode == "dry_run":
            command.append("--dry-run")
        else:
            command.extend(["--load-env", str(DEFAULT_ENV_PATH)])
    elif sync_id == "monthly_api_snapshots":
        command = [PYTHON, "scripts/load_monthly_api_snapshots.py"]
        if mode == "dry_run":
            command.append("--dry-run")
        if client_slug:
            command.extend(["--client", client_slug])
    elif sync_id == "api_smoke_checks":
        command = [PYTHON, "scripts/smoke_reporting_apis.py"]
        command.extend(["--client", client_slug or "shop-rongrong"])
        if mode == "live":
            command.append("--log-bigquery")
    elif sync_id == "crawl_memory_load":
        input_path = _safe_path(options.get("input_path"))
        crawl_id = str(options.get("crawl_id") or "").strip()
        crawl_trigger = str(options.get("crawl_trigger") or "monthly_baseline").strip()
        crawl_scope = str(options.get("crawl_scope") or "full_site").strip()
        if not client_slug or not crawl_id:
            raise SyncValidationError("crawl_memory_load requires client_slug and crawl_id")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", crawl_id):
            raise SyncValidationError("crawl_id contains unsupported characters")
        if crawl_trigger not in {"monthly_baseline", "post_task"} or crawl_scope not in {"full_site", "partial_scope"}:
            raise SyncValidationError("crawl trigger or scope is not allowlisted")
        command = [
            PYTHON,
            "scripts/load_screaming_frog_export.py",
            "--export-dir",
            str(input_path),
            "--client-slug",
            client_slug,
            "--crawl-id",
            crawl_id,
            "--crawl-trigger",
            crawl_trigger,
            "--crawl-scope",
            crawl_scope,
        ]
        command.append("--dry-run" if mode == "dry_run" else "--write-bigquery")
        if ensure_tables and mode == "live":
            command.append("--ensure-tables")
    elif sync_id == "agent_work_update":
        agent_script = str(options.get("agent_script") or "run_system_admin_agent.py")
        allowed_agents = {
            "run_system_admin_agent.py",
            "run_daily_agency_brief.py",
            "run_promise_tracker.py",
            "run_reporting_prep_agent.py",
            "run_seo_opportunity_agent.py",
            "run_seo_workflow_router.py",
            "run_specialist_agent.py",
        }
        if agent_script not in allowed_agents:
            raise SyncValidationError("agent_script is not allowlisted")
        command = [PYTHON, f"scripts/{agent_script}", "--from-bigquery", "--load-env", str(DEFAULT_ENV_PATH)]
        if mode == "dry_run":
            command.append("--dry-run")
        else:
            command.append("--write-bigquery")
            if ensure_tables:
                command.append("--ensure-tables")
        if client_slug and agent_script in {"run_reporting_prep_agent.py", "run_seo_opportunity_agent.py", "run_specialist_agent.py"}:
            command.extend(["--client-slug", client_slug])
    else:
        raise SyncValidationError("Unhandled sync_id")
    return command, cwd


def build_master_steps(mode: str, options: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    options = options or {}
    step_ids = registry()["master_sync"].master_step_ids
    steps: list[dict[str, Any]] = []
    for step_id in step_ids:
        step_mode = mode
        step_options: dict[str, Any] = {}
        if step_id == "monday_state_refresh":
            if mode == "dry_run":
                continue
            step_mode = "live"
        if step_id in {"agency_ops_ingest", "seo_catalog_sync", "seo_client_memory_sync", "agent_work_update"} and mode == "live":
            step_options["ensure_tables"] = bool(options.get("ensure_tables", True))
        if step_id == "agent_work_update":
            step_options["agent_script"] = "run_system_admin_agent.py"
        command, cwd = build_command(step_id, step_mode, step_options)
        steps.append(
            {
                "sync_id": step_id,
                "label": registry()[step_id].label,
                "mode": step_mode,
                "cwd": str(cwd),
                "command": command,
                "command_display": _safe_command_display(command),
            }
        )
    return steps


def _safe_command_display(command: list[str]) -> list[str]:
    output: list[str] = []
    skip_next = False
    secret_flags = {"--load-env", "--google-env", "--reporting-env", "--se-ranking-env"}
    for part in command:
        if skip_next:
            output.append("[approved local env path]")
            skip_next = False
            continue
        output.append(part)
        if part in secret_flags:
            skip_next = True
    return output


def _read_commands() -> list[dict[str, Any]]:
    if not COMMANDS_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in COMMANDS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _write_commands(rows: list[dict[str, Any]]) -> None:
    COMMANDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows)
    COMMANDS_PATH.write_text(body, encoding="utf-8")


def _update_command(command_id: str, **updates: Any) -> dict[str, Any]:
    with _STATE_LOCK:
        rows = _read_commands()
        for row in rows:
            if row.get("command_id") == command_id:
                row.update(updates)
                row.setdefault("history", []).append({"at": utc_now(), "status": updates.get("status", row.get("status"))})
                _write_commands(rows)
                return row
    raise SyncValidationError("Command not found")


def _write_run(run_id: str, payload: dict[str, Any]) -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / f"{run_id}.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_run(run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    path = RUNS_ROOT / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def execute_command(command_id: str, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> dict[str, Any]:
    command = get_command(command_id)
    run_id = str(command["run_id"])
    started_at = utc_now()
    _update_command(command_id, status="running", started_at=started_at)
    run_payload = {
        "run_id": run_id,
        "command_id": command_id,
        "sync_id": command["sync_id"],
        "mode": command["mode"],
        "status": "running",
        "started_at": started_at,
        "command_display": command["command_display"],
    }
    _write_run(run_id, run_payload)
    runner = runner or subprocess.run
    try:
        if command.get("steps"):
            step_results = []
            status = "succeeded"
            for step in command["steps"]:
                result = runner(
                    step["command"],
                    cwd=step["cwd"],
                    text=True,
                    capture_output=True,
                    timeout=60 * 60,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                step_result = {
                    "sync_id": step["sync_id"],
                    "label": step["label"],
                    "mode": step["mode"],
                    "status": "succeeded" if result.returncode == 0 else "failed",
                    "exit_code": result.returncode,
                    "stdout": redact_text(result.stdout or "", max_chars=4000),
                    "stderr": redact_text(result.stderr or "", max_chars=4000),
                    "command_display": step["command_display"],
                }
                step_results.append(step_result)
                run_payload["step_results"] = step_results
                _write_run(run_id, run_payload)
                if result.returncode != 0:
                    status = "failed"
                    break
            result_returncode = 0 if status == "succeeded" else 1
            stdout = "\n".join(f"{step['label']}: {step['status']}" for step in step_results)
            stderr = "\n".join(step["stderr"] for step in step_results if step.get("stderr"))
        else:
            result = runner(
                command["command"],
                cwd=command["cwd"],
                text=True,
                capture_output=True,
                timeout=60 * 60,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            status = "succeeded" if result.returncode == 0 else "failed"
            result_returncode = result.returncode
            stdout = result.stdout or ""
            stderr = result.stderr or ""
        completed_at = utc_now()
        run_payload.update(
            {
                "status": status,
                "completed_at": completed_at,
                "exit_code": result_returncode,
                "stdout": redact_text(stdout),
                "stderr": redact_text(stderr),
            }
        )
        _write_run(run_id, run_payload)
        return _update_command(command_id, status=status, completed_at=completed_at, exit_code=result_returncode)
    except Exception as exc:
        completed_at = utc_now()
        run_payload.update({"status": "failed", "completed_at": completed_at, "exit_code": None, "stderr": redact_text(f"{type(exc).__name__}: {exc}")})
        _write_run(run_id, run_payload)
        return _update_command(command_id, status="failed", completed_at=completed_at, exit_code=None, error_message=type(exc).__name__)


def _execute_in_thread(command_id: str) -> None:
    thread = threading.Thread(target=execute_command, args=(command_id,), daemon=True)
    thread.start()


def queue_command(sync_id: str, mode: str, options: dict[str, Any] | None = None, *, confirmation: str | None = None, auto_start: bool = True) -> dict[str, Any]:
    options = options or {}
    definition = registry().get(sync_id)
    if not definition:
        raise SyncValidationError("Unknown sync_id")
    if mode == "live" and definition.confirmation_text and confirmation != definition.confirmation_text:
        raise SyncValidationError("Live run confirmation text does not match")
    command, cwd = build_command(sync_id, mode, options)
    steps = build_master_steps(mode, options) if sync_id == "master_sync" else None
    now = utc_now()
    command_id = f"cmd_{uuid4().hex[:16]}"
    run_id = f"sync_{uuid4().hex[:16]}"
    row = {
        "command_id": command_id,
        "run_id": run_id,
        "sync_id": sync_id,
        "label": definition.label,
        "category": definition.category,
        "mode": mode,
        "status": "queued",
        "queued_at": now,
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "cwd": str(cwd),
        "command": command,
        "command_display": _safe_command_display(command),
        "steps": steps,
        "options": {key: value for key, value in options.items() if key not in {"confirmation"}},
        "expected_logs": list(definition.expected_logs),
        "history": [{"at": now, "status": "queued"}],
    }
    with _STATE_LOCK:
        rows = _read_commands()
        rows.append(row)
        _write_commands(rows[-500:])
    if auto_start:
        _execute_in_thread(command_id)
    return sanitize_command(row)


def get_command(command_id: str) -> dict[str, Any]:
    with _STATE_LOCK:
        for row in _read_commands():
            if row.get("command_id") == command_id:
                return row
    raise SyncValidationError("Command not found")


def sanitize_command(row: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(row)
    sanitized.pop("command", None)
    sanitized["run"] = _read_run(str(row.get("run_id") or "")) or None
    return sanitized


def command_state(command_id: str) -> dict[str, Any]:
    return sanitize_command(get_command(command_id))


def _latest_for_sync(rows: list[dict[str, Any]], sync_id: str, statuses: set[str] | None = None) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("sync_id") == sync_id and (statuses is None or row.get("status") in statuses)]
    return matches[-1] if matches else None


def sync_payload(dashboard_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = _read_commands()
    definitions = public_registry()
    by_sync: list[dict[str, Any]] = []
    now = utc_now()
    for definition in definitions:
        latest = _latest_for_sync(rows, definition["sync_id"])
        latest_success = _latest_for_sync(rows, definition["sync_id"], {"succeeded"})
        latest_failure = _latest_for_sync(rows, definition["sync_id"], {"failed"})
        stale = latest_success is None
        by_sync.append(
            {
                **definition,
                "last_run": sanitize_command(latest) if latest else None,
                "last_success_at": latest_success.get("completed_at") if latest_success else None,
                "last_failure_at": latest_failure.get("completed_at") if latest_failure else None,
                "freshness_status": "unknown" if stale else "recent",
            }
        )
    visible_rows = [sanitize_command(row) for row in rows[-100:]][::-1]
    running = [row for row in visible_rows if row.get("status") in {"queued", "running"}]
    failed = [row for row in visible_rows if row.get("status") == "failed"]
    monday_success = next((row for row in visible_rows if row.get("sync_id") == "monday_state_refresh" and row.get("status") == "succeeded"), None)
    bq_success = next((row for row in visible_rows if row.get("category") in {"BigQuery", "Finance", "API Checks", "Crawls"} and row.get("status") == "succeeded"), None)
    cost_failures = 0
    if dashboard_payload:
        cost_failures = int(dashboard_payload.get("data_health", {}).get("cost_failures") or 0)
    return {
        "meta": {"generated_at": now, "state_root": str(SYNC_STATE_ROOT), "poll_seconds": 5},
        "summary": {
            "running_syncs": len(running),
            "failed_syncs": len(failed),
            "last_successful_monday_state_update": monday_success.get("completed_at") if monday_success else None,
            "last_successful_bigquery_push": bq_success.get("completed_at") if bq_success else None,
            "oldest_stale_sync": next((row["sync_id"] for row in by_sync if row["freshness_status"] == "unknown"), None),
            "recent_cost_guardrail_failures": cost_failures,
        },
        "syncs": by_sync,
        "commands": visible_rows,
        "timeline": visible_rows,
    }


def handle_post_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sync_id = str(payload.get("sync_id") or "")
    mode = str(payload.get("mode") or "dry_run")
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    confirmation = str(payload.get("confirmation") or "")
    return queue_command(sync_id, mode, options, confirmation=confirmation or None)


if not Path(PYTHON).exists():
    PYTHON = sys.executable
