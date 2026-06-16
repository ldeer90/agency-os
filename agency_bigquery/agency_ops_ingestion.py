from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
from uuid import uuid4
from zoneinfo import ZoneInfo

from .capped_query_runner import CappedBigQueryRunner
from .cost_config import BigQueryCostConfig
from .schema import ensure_agency_ops_tables, ensure_comms_memory_tables, ensure_roadmap_memory_tables


PROJECTS_ROOT = Path("/Users/laurencedeer/Projects/Codex")
DEFAULT_MONDAY_HUB_ROOT = PROJECTS_ROOT / "monday-agency-hub"
DEFAULT_SEO_AUTOMATION_ROOT = PROJECTS_ROOT / "SEO Automation"
DEFAULT_SEO_REPORTING_ROOT = PROJECTS_ROOT / "seo-reporting-platform"
MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")

V1_BOARD_ROLES = {
    "client_facing",
    "internal_seo_execution",
    "client_registry",
    "content_production",
    "monthly_planning",
    "agency_ops",
}
SAFE_COLUMN_TYPES = {"status", "people", "date", "time_tracking", "numbers"}
SAFE_TEXT_COLUMN_TITLES = {"client url"}
TEXT_TITLES_TO_REDACT = {"notes", "invoice agreement", "email", "phone", "location"}
SECRET_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"private_key",
        r"client_secret",
        r"refresh_token",
        r"access_token",
        r"api[_-]?key\s*[=:]",
        r"password\s*[=:]",
        r"-----BEGIN",
    )
]
COMMS_ALLOWED_CHANNELS = {"gmail", "outlook", "monday", "mixed"}
COMMS_ALLOWED_CATEGORIES = {
    "client_conversation",
    "internal_ops",
    "reporting",
    "access_blocker",
    "approval",
    "billing",
    "platform_alert",
    "other",
}
COMMS_ALLOWED_URGENCIES = {"high", "medium", "low", "none"}
COMMS_ALLOWED_SENTIMENTS = {"positive", "neutral", "negative", "mixed", "unknown"}
COMMS_ALLOWED_THREAD_STATUSES = {"open", "waiting_on_us", "waiting_on_client", "resolved", "fyi"}
COMMS_MAX_SUMMARY_CHARS = 420
COMMS_MAX_ACTION_CHARS = 260
ROADMAP_ALLOWED_SOURCE_TYPES = {"drive_sheet", "drive_doc", "monday", "seo_timeline", "manual", "mixed"}
ROADMAP_ALLOWED_WORK_TYPES = {
    "technical",
    "content",
    "collection",
    "blog",
    "link_building",
    "reporting",
    "local_seo",
    "schema",
    "analytics",
    "other",
}
ROADMAP_ALLOWED_PRIORITIES = {"high", "medium", "low", "none"}
ROADMAP_ALLOWED_STATUSES = {"planned", "in_progress", "completed", "deferred", "cancelled", "blocked"}
ROADMAP_ALLOWED_EVIDENCE_TYPES = {"monday", "timeline", "report", "manual", "none"}
ROADMAP_MAX_TITLE_CHARS = 180
ROADMAP_MAX_SUMMARY_CHARS = 360
CLIENT_CONTEXT_ALLOWED_REVIEW_STATUSES = {"draft", "reviewed", "approved"}
CLIENT_CONTEXT_MAX_TEXT_CHARS = 520
CLIENT_CONTEXT_MAX_LIST_ITEM_CHARS = 180
CLIENT_CONTEXT_MAX_LIST_ITEMS = 8
ROADMAP_URL_RE = re.compile(r"^https?://[^\s<>\"]+$|^/[A-Za-z0-9][^\s<>\"]*$")
CLIENT_SLUG_ALIASES = {
    "acorn-car-rentals": "acorn-rentals",
    "joe-rascal-ducati": "ducati-melbourne",
    "salad-servers": "salad-servers-direct",
}
HEALTH_VERIFICATION_LEVELS = {
    "route_config",
    "local_content",
    "metadata_verified",
    "bounded_content_validated",
    "api_smoke",
    "warehouse_derived",
}
COMMS_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
COMMS_RAW_HEADER_RE = re.compile(
    r"(?mi)(^|\n)\s*(from|to|cc|bcc|sent|subject|date):\s|-----original message-----|begin forwarded message|wrote:\s*$"
)
COMMS_LONG_QUOTE_RE = re.compile(r'"(?:[^"\s]+\s+){17,}[^"]+"')
COMMS_PHONEISH_RE = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")


@dataclass(frozen=True)
class SourcePaths:
    monday_hub: Path = DEFAULT_MONDAY_HUB_ROOT
    seo_automation: Path = DEFAULT_SEO_AUTOMATION_ROOT
    seo_reporting: Path = DEFAULT_SEO_REPORTING_ROOT
    big_query: Path = PROJECTS_ROOT / "Big Query"

    @property
    def monday_derived(self) -> Path:
        return self.monday_hub / "data" / "derived"

    @property
    def monday_snapshots(self) -> Path:
        return self.monday_hub / "data" / "snapshots"

    @property
    def seo_clients(self) -> Path:
        return self.seo_automation / "docs" / "agent" / "clients"

    @property
    def reporting_config(self) -> Path:
        return self.seo_reporting / "config"

    @property
    def reporting_content(self) -> Path:
        return self.seo_reporting / "content"

    @property
    def drive_folder_verifications(self) -> Path:
        return self.big_query / "data" / "client_health" / "drive_folder_verifications.json"

    @property
    def api_smoke_verifications(self) -> Path:
        return self.big_query / "data" / "client_health" / "api_smoke_verifications.json"

    @property
    def client_context_staging(self) -> Path:
        return self.big_query / "data" / "client_context" / "staging"


@dataclass(frozen=True)
class IngestionSummary:
    run_id: str
    status: str
    table_counts: dict[str, int]
    mart_statuses: dict[str, str]


def utc_now_iso() -> str:
    return datetime.now(MELBOURNE_TIMEZONE).isoformat()


def today_iso() -> str:
    return datetime.now(MELBOURNE_TIMEZONE).date().isoformat()


def slugify(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return cleaned.strip("-")


def canonical_client_slug(value: Any) -> str:
    slug = slugify(str(value or ""))
    return CLIENT_SLUG_ALIASES.get(slug, slug)


def canonical_client_slug_sql(expression: str) -> str:
    clauses = " ".join(f"WHEN '{alias}' THEN '{canonical}'" for alias, canonical in sorted(CLIENT_SLUG_ALIASES.items()))
    return f"CASE LOWER({expression}) {clauses} ELSE LOWER({expression}) END"


def parse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    match = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-01"
    return None


def parse_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"true", "yes", "1", "y"}:
        return True
    if text in {"false", "no", "0", "n"}:
        return False
    return None


def normalize_status(value: str | None) -> str:
    text = (value or "").strip()
    lowered = text.lower()
    if not lowered:
        return "Not Started"
    if lowered in {"done", "published / live", "published", "complete", "completed"}:
        return "Done"
    if lowered in {"stuck", "blocked", "needs edits", "high"}:
        return "Blocked"
    if lowered in {"working on it", "with client", "with writer", "pending", "medium"}:
        return "In Progress"
    if lowered in {"not started", "low"}:
        return "Not Started"
    return text


def has_secret_like_text(value: Any) -> bool:
    if value is None:
        return False
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def has_email_address(value: Any) -> bool:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return bool(COMMS_EMAIL_RE.search(text))


def has_raw_comms_shape(value: Any) -> bool:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    if COMMS_RAW_HEADER_RE.search(text) or COMMS_LONG_QUOTE_RE.search(text):
        return True
    quoted_lines = [line for line in text.splitlines() if line.strip().startswith(">")]
    if len(quoted_lines) >= 2:
        return True
    return False


def has_phone_heavy_text(value: Any) -> bool:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    for match in COMMS_PHONEISH_RE.findall(text):
        digits = re.sub(r"\D", "", match)
        if len(digits) >= 10:
            return True
    return False


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def json_dump(value: Any) -> Any:
    return sanitize_json_value(value)


def sanitize_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        if not value:
            return None
        return {str(key): sanitize_json_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_json_value(child) for child in value]
    return value


def require_comms_safe_text(value: Any, *, field_name: str, max_chars: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_chars is not None and len(text) > max_chars:
        raise ValueError(f"{field_name} is too long for summarized comms memory")
    if has_secret_like_text(text):
        raise ValueError(f"{field_name} contains credential-like text")
    if has_email_address(text):
        raise ValueError(f"{field_name} contains a raw email address")
    if has_raw_comms_shape(text):
        raise ValueError(f"{field_name} looks like raw email/Monday content")
    if has_phone_heavy_text(text):
        raise ValueError(f"{field_name} contains phone-heavy text")
    return text


def normalize_comms_choice(value: Any, *, field_name: str, allowed: set[str], default: str | None = None) -> str:
    text = str(value or default or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return text


def coerce_required_bool(value: Any, *, field_name: str) -> bool:
    parsed = parse_bool(value)
    if parsed is None:
        if value in (None, ""):
            return False
        raise ValueError(f"{field_name} must be a boolean")
    return parsed


def coerce_non_negative_int(value: Any, *, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number < 0:
        raise ValueError(f"{field_name} must not be negative")
    return number


def coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number between 0 and 1") from exc
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be a number between 0 and 1")
    return confidence


def normalize_choice(value: Any, *, field_name: str, allowed: set[str], default: str | None = None) -> str:
    text = str(value or default or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return text


def hash_source_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("source references must not be blank")
    if has_secret_like_text(text) or has_email_address(text):
        raise ValueError("source references must not contain secrets or email addresses")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def require_summary_safe_text(value: Any, *, field_name: str, max_chars: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_chars is not None and len(text) > max_chars:
        raise ValueError(f"{field_name} is too long")
    if has_secret_like_text(text):
        raise ValueError(f"{field_name} contains credential-like text")
    if has_email_address(text):
        raise ValueError(f"{field_name} contains a raw email address")
    if has_raw_comms_shape(text):
        raise ValueError(f"{field_name} looks like raw private content")
    if has_phone_heavy_text(text):
        raise ValueError(f"{field_name} contains phone-heavy text")
    return text


def normalize_drive_id(value: Any, *, field_name: str) -> str | None:
    text = require_summary_safe_text(value, field_name=field_name, max_chars=160)
    if not text:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,160}", text):
        raise ValueError(f"{field_name} must be a Drive-style opaque ID")
    return text


def normalize_opaque_drive_id(value: Any, *, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if has_secret_like_text(text) or has_email_address(text) or has_raw_comms_shape(text):
        raise ValueError(f"{field_name} contains unsafe text")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,160}", text):
        raise ValueError(f"{field_name} must be a Drive-style opaque ID")
    return text


def normalize_target_url(value: Any) -> str | None:
    text = require_summary_safe_text(value, field_name="target_url", max_chars=300)
    if not text:
        return None
    if not ROADMAP_URL_RE.fullmatch(text):
        raise ValueError("target_url must be an http(s) URL or site-relative path")
    return text


def require_client_context_text(value: Any, *, field_name: str, max_chars: int = CLIENT_CONTEXT_MAX_TEXT_CHARS) -> str | None:
    return require_summary_safe_text(value, field_name=field_name, max_chars=max_chars)


def require_client_context_list(value: Any, *, field_name: str) -> list[str] | None:
    if value in (None, ""):
        return None
    values = value if isinstance(value, list) else [value]
    if len(values) > CLIENT_CONTEXT_MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} has too many items")
    output: list[str] = []
    for index, item in enumerate(values, start=1):
        text = require_client_context_text(item, field_name=f"{field_name}[{index}]", max_chars=CLIENT_CONTEXT_MAX_LIST_ITEM_CHARS)
        if text:
            output.append(text)
    return output or None


def normalize_client_onboarding_profile_row(row: dict[str, Any], *, run_id: str, ingested_at: str) -> dict[str, Any]:
    client_slug = slugify(require_client_context_text(row.get("client_slug"), field_name="client_slug", max_chars=120))
    if not client_slug:
        raise ValueError("client_slug is required")
    client_name = require_client_context_text(row.get("client_name"), field_name="client_name", max_chars=160)
    if not client_name:
        raise ValueError("client_name is required")
    review_status = normalize_choice(
        row.get("review_status"),
        field_name="review_status",
        allowed=CLIENT_CONTEXT_ALLOWED_REVIEW_STATUSES,
        default="draft",
    )
    source_drive_file_id = normalize_opaque_drive_id(row.get("source_drive_file_id"), field_name="source_drive_file_id")
    source_drive_file_name = require_client_context_text(row.get("source_drive_file_name"), field_name="source_drive_file_name", max_chars=220)
    source_ref = row.get("source_ref") or "|".join(
        part for part in (client_slug, source_drive_file_id or "", source_drive_file_name or "") if part
    )
    source_ref_hash = str(row.get("source_ref_hash") or hash_source_ref(source_ref)).strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", source_ref_hash):
        raise ValueError("source_ref_hash must be hash-like")
    return {
        "ingested_at": ingested_at,
        "run_id": run_id,
        "client_slug": client_slug,
        "client_name": client_name,
        "business_summary": require_client_context_text(row.get("business_summary"), field_name="business_summary"),
        "primary_goals_json": json_dump(require_client_context_list(row.get("primary_goals"), field_name="primary_goals")),
        "seo_priorities_json": json_dump(require_client_context_list(row.get("seo_priorities"), field_name="seo_priorities")),
        "target_audience": require_client_context_text(row.get("target_audience"), field_name="target_audience"),
        "key_products_or_services_json": json_dump(require_client_context_list(row.get("key_products_or_services"), field_name="key_products_or_services")),
        "important_pages_json": json_dump(require_client_context_list(row.get("important_pages"), field_name="important_pages")),
        "brand_tone": require_client_context_text(row.get("brand_tone"), field_name="brand_tone", max_chars=260),
        "competitors_json": json_dump(require_client_context_list(row.get("competitors"), field_name="competitors")),
        "constraints_or_risks_json": json_dump(require_client_context_list(row.get("constraints_or_risks"), field_name="constraints_or_risks")),
        "approval_preferences": require_client_context_text(row.get("approval_preferences"), field_name="approval_preferences", max_chars=360),
        "reporting_expectations": require_client_context_text(row.get("reporting_expectations"), field_name="reporting_expectations", max_chars=360),
        "agent_context_summary": require_client_context_text(row.get("agent_context_summary"), field_name="agent_context_summary"),
        "source_drive_file_id": source_drive_file_id,
        "source_drive_file_name": source_drive_file_name,
        "source_modified_at": parse_timestamp(row.get("source_modified_at")),
        "review_status": review_status,
        "confidence": coerce_confidence(row.get("confidence", 0)),
        "source_ref_hash": source_ref_hash,
        "validation_status": "validated",
    }


def parse_client_onboarding_profile_jsonl(path: Path, *, run_id: str, ingested_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: expected JSON object")
        try:
            rows.append(normalize_client_onboarding_profile_row(payload, run_id=run_id, ingested_at=ingested_at))
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
    return rows


def parse_client_onboarding_profiles(paths: SourcePaths, *, run_id: str, ingested_at: str) -> list[dict[str, Any]]:
    if not paths.client_context_staging.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(paths.client_context_staging.glob("*.jsonl")):
        rows.extend(parse_client_onboarding_profile_jsonl(path, run_id=run_id, ingested_at=ingested_at))
    return rows


def normalize_source_ref_hashes(row: dict[str, Any]) -> list[str] | None:
    if row.get("source_ref_hashes_json") is not None:
        value = row["source_ref_hashes_json"]
        refs = value if isinstance(value, list) else json.loads(value)
        hashes = [str(ref).strip() for ref in refs if str(ref).strip()]
        if any(not re.fullmatch(r"[a-fA-F0-9]{16,64}", ref) for ref in hashes):
            raise ValueError("source_ref_hashes_json must contain hash-like values")
        return hashes or None
    if row.get("source_ref_hashes") is not None:
        refs = row["source_ref_hashes"]
        hashes = [str(ref).strip() for ref in refs if str(ref).strip()]
        if any(not re.fullmatch(r"[a-fA-F0-9]{16,64}", ref) for ref in hashes):
            raise ValueError("source_ref_hashes must contain hash-like values")
        return hashes or None
    if row.get("source_refs") is not None:
        refs = row["source_refs"]
        if not isinstance(refs, list):
            raise ValueError("source_refs must be a list")
        return [hash_source_ref(ref) for ref in refs if str(ref or "").strip()] or None
    return None


def normalize_thread_ref_hash(row: dict[str, Any], source_ref_hashes: list[str] | None) -> str | None:
    if row.get("thread_ref_hash"):
        value = str(row["thread_ref_hash"]).strip()
        if not re.fullmatch(r"[a-fA-F0-9]{16,64}", value):
            raise ValueError("thread_ref_hash must be hash-like")
        return value.lower()
    if row.get("thread_ref"):
        return hash_source_ref(row["thread_ref"])
    if row.get("thread_ref_key"):
        return hash_source_ref(row["thread_ref_key"])
    if source_ref_hashes:
        return source_ref_hashes[0].lower()
    return None


def infer_thread_status(row: dict[str, Any]) -> str:
    if row.get("thread_status"):
        return normalize_comms_choice(
            row.get("thread_status"),
            field_name="thread_status",
            allowed=COMMS_ALLOWED_THREAD_STATUSES,
        )
    if coerce_required_bool(row.get("waiting_on_us"), field_name="waiting_on_us") or coerce_required_bool(
        row.get("needs_reply"),
        field_name="needs_reply",
    ):
        return "waiting_on_us"
    if coerce_required_bool(row.get("waiting_on_client"), field_name="waiting_on_client"):
        return "waiting_on_client"
    if coerce_required_bool(row.get("blocked"), field_name="blocked") or str(row.get("category", "")).strip().lower() == "access_blocker":
        return "open"
    return "fyi"


def normalize_comms_timestamp(value: Any, *, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    parsed = parse_timestamp(value)
    if parsed:
        return parsed
    parsed_date = parse_date(value)
    if parsed_date:
        return f"{parsed_date}T00:00:00+00:00"
    raise ValueError(f"{field_name} must be an ISO timestamp or date")


def normalize_comms_summary_row(
    row: dict[str, Any],
    *,
    run_id: str,
    created_at: str,
    default_week_start: str | None = None,
    default_week_end: str | None = None,
    default_summarizer_model: str | None = None,
) -> dict[str, Any]:
    week_start = parse_date(row.get("week_start") or default_week_start)
    week_end = parse_date(row.get("week_end") or default_week_end)
    if not week_start or not week_end:
        raise ValueError("week_start and week_end are required dates")
    if week_end < week_start:
        raise ValueError("week_end must be on or after week_start")
    client_slug = slugify(require_comms_safe_text(row.get("client_slug"), field_name="client_slug", max_chars=120))
    if not client_slug:
        raise ValueError("client_slug is required")
    client_name = require_comms_safe_text(row.get("client_name"), field_name="client_name", max_chars=160)
    if not client_name:
        raise ValueError("client_name is required")
    summary = require_comms_safe_text(row.get("summary"), field_name="summary", max_chars=COMMS_MAX_SUMMARY_CHARS)
    if not summary:
        raise ValueError("summary is required")
    recommended_action = require_comms_safe_text(
        row.get("recommended_action"),
        field_name="recommended_action",
        max_chars=COMMS_MAX_ACTION_CHARS,
    )
    owner_hint = require_comms_safe_text(row.get("owner_hint"), field_name="owner_hint", max_chars=120)
    due_hint = require_comms_safe_text(row.get("due_hint"), field_name="due_hint", max_chars=120)
    summarizer_model = require_comms_safe_text(
        row.get("summarizer_model") or default_summarizer_model,
        field_name="summarizer_model",
        max_chars=120,
    )
    source_ref_hashes = normalize_source_ref_hashes(row)
    thread_ref_hash = normalize_thread_ref_hash(row, source_ref_hashes)
    thread_status = infer_thread_status(row)
    latest_event_at = normalize_comms_timestamp(row.get("latest_event_at"), field_name="latest_event_at") or created_at
    resolved_at = normalize_comms_timestamp(row.get("resolved_at"), field_name="resolved_at")
    if thread_status == "resolved" and not resolved_at:
        resolved_at = latest_event_at
    resolution_summary = require_comms_safe_text(
        row.get("resolution_summary"),
        field_name="resolution_summary",
        max_chars=COMMS_MAX_ACTION_CHARS,
    )
    return {
        "run_id": run_id,
        "created_at": created_at,
        "week_start": week_start,
        "week_end": week_end,
        "client_slug": client_slug,
        "client_name": client_name,
        "channel": normalize_comms_choice(
            row.get("channel"),
            field_name="channel",
            allowed=COMMS_ALLOWED_CHANNELS,
            default="mixed",
        ),
        "category": normalize_comms_choice(
            row.get("category"),
            field_name="category",
            allowed=COMMS_ALLOWED_CATEGORIES,
            default="other",
        ),
        "summary": summary,
        "recommended_action": recommended_action,
        "owner_hint": owner_hint,
        "due_hint": due_hint,
        "needs_reply": coerce_required_bool(row.get("needs_reply"), field_name="needs_reply"),
        "blocked": coerce_required_bool(row.get("blocked"), field_name="blocked"),
        "waiting_on_client": coerce_required_bool(row.get("waiting_on_client"), field_name="waiting_on_client"),
        "waiting_on_us": coerce_required_bool(row.get("waiting_on_us"), field_name="waiting_on_us"),
        "stale_followup": coerce_required_bool(row.get("stale_followup"), field_name="stale_followup"),
        "urgency": normalize_comms_choice(
            row.get("urgency"),
            field_name="urgency",
            allowed=COMMS_ALLOWED_URGENCIES,
            default="none",
        ),
        "sentiment": normalize_comms_choice(
            row.get("sentiment"),
            field_name="sentiment",
            allowed=COMMS_ALLOWED_SENTIMENTS,
            default="unknown",
        ),
        "source_event_count": coerce_non_negative_int(
            row.get("source_event_count", 0),
            field_name="source_event_count",
        ),
        "source_ref_hashes_json": source_ref_hashes,
        "thread_ref_hash": thread_ref_hash,
        "thread_status": thread_status,
        "latest_event_at": latest_event_at,
        "resolved_at": resolved_at,
        "resolution_summary": resolution_summary,
        "summarizer_model": summarizer_model,
        "confidence": coerce_confidence(row.get("confidence", 0)),
        "validation_status": "validated",
    }


def parse_comms_summary_jsonl(
    path: Path,
    *,
    run_id: str,
    created_at: str,
    default_week_start: str | None = None,
    default_week_end: str | None = None,
    default_summarizer_model: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: expected JSON object")
        try:
            rows.append(
                normalize_comms_summary_row(
                    payload,
                    run_id=run_id,
                    created_at=created_at,
                    default_week_start=default_week_start,
                    default_week_end=default_week_end,
                    default_summarizer_model=default_summarizer_model,
                )
            )
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
    return rows


def normalize_roadmap_item_row(
    row: dict[str, Any],
    *,
    run_id: str,
    ingested_at: str,
    default_planned_month: str | None = None,
    default_source_type: str | None = None,
) -> dict[str, Any]:
    planned_month = parse_date(row.get("planned_month") or row.get("month") or default_planned_month)
    if not planned_month:
        raise ValueError("planned_month is required")
    planned_month = planned_month[:8] + "01"
    period_id = require_summary_safe_text(row.get("period_id") or planned_month[:7], field_name="period_id", max_chars=20)
    client_slug = slugify(require_summary_safe_text(row.get("client_slug"), field_name="client_slug", max_chars=120))
    if not client_slug:
        raise ValueError("client_slug is required")
    client_name = require_summary_safe_text(row.get("client_name"), field_name="client_name", max_chars=160)
    if not client_name:
        raise ValueError("client_name is required")
    item_title = require_summary_safe_text(row.get("item_title") or row.get("title"), field_name="item_title", max_chars=ROADMAP_MAX_TITLE_CHARS)
    if not item_title:
        raise ValueError("item_title is required")
    source_type = normalize_choice(
        row.get("source_type"),
        field_name="source_type",
        allowed=ROADMAP_ALLOWED_SOURCE_TYPES,
        default=default_source_type or "manual",
    )
    source_title = require_summary_safe_text(row.get("source_title"), field_name="source_title", max_chars=180)
    source_path = require_summary_safe_text(row.get("source_path"), field_name="source_path", max_chars=500)
    drive_file_id = normalize_drive_id(row.get("drive_file_id"), field_name="drive_file_id")
    drive_folder_id = normalize_drive_id(row.get("drive_folder_id"), field_name="drive_folder_id")
    source_ref = row.get("source_ref") or row.get("source_ref_key") or "|".join(
        part
        for part in (
            client_slug,
            period_id,
            source_type,
            source_title or "",
            source_path or "",
            drive_file_id or "",
            drive_folder_id or "",
        )
        if part
    )
    source_ref_hash = row.get("source_ref_hash") or hash_source_ref(source_ref)
    source_ref_hash = str(source_ref_hash).strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", source_ref_hash):
        raise ValueError("source_ref_hash must be hash-like")
    explicit_item_id = row.get("roadmap_item_id")
    if explicit_item_id:
        roadmap_item_id = str(explicit_item_id).strip().lower()
        if not re.fullmatch(r"[a-f0-9]{16,64}", roadmap_item_id):
            raise ValueError("roadmap_item_id must be hash-like")
    else:
        roadmap_item_id = hashlib.sha256(
            f"{client_slug}|{period_id}|{item_title}|{source_ref_hash}".encode("utf-8")
        ).hexdigest()[:32]
    source_row_index = row.get("source_row_index")
    if source_row_index in (None, ""):
        normalized_source_row_index = None
    else:
        normalized_source_row_index = coerce_non_negative_int(source_row_index, field_name="source_row_index")
    evidence_type = normalize_choice(
        row.get("completion_evidence_type"),
        field_name="completion_evidence_type",
        allowed=ROADMAP_ALLOWED_EVIDENCE_TYPES,
        default="none",
    )
    evidence_ref = require_summary_safe_text(
        row.get("completion_evidence_ref"),
        field_name="completion_evidence_ref",
        max_chars=220,
    )
    if evidence_ref and (has_email_address(evidence_ref) or has_secret_like_text(evidence_ref)):
        raise ValueError("completion_evidence_ref must not contain secrets or email addresses")
    return {
        "run_id": run_id,
        "ingested_at": ingested_at,
        "client_slug": client_slug,
        "client_name": client_name,
        "period_id": period_id,
        "planned_month": planned_month,
        "roadmap_item_id": roadmap_item_id,
        "item_title": item_title,
        "work_type": normalize_choice(
            row.get("work_type"),
            field_name="work_type",
            allowed=ROADMAP_ALLOWED_WORK_TYPES,
            default="other",
        ),
        "priority": normalize_choice(
            row.get("priority"),
            field_name="priority",
            allowed=ROADMAP_ALLOWED_PRIORITIES,
            default="none",
        ),
        "planned_status": normalize_choice(
            row.get("planned_status") or row.get("status"),
            field_name="planned_status",
            allowed=ROADMAP_ALLOWED_STATUSES,
            default="planned",
        ),
        "owner_hint": require_summary_safe_text(row.get("owner_hint"), field_name="owner_hint", max_chars=120),
        "due_date": parse_date(row.get("due_date")),
        "target_url": normalize_target_url(row.get("target_url")),
        "keyword_theme": require_summary_safe_text(row.get("keyword_theme"), field_name="keyword_theme", max_chars=180),
        "notes_summary": require_summary_safe_text(row.get("notes_summary"), field_name="notes_summary", max_chars=ROADMAP_MAX_SUMMARY_CHARS),
        "source_type": source_type,
        "source_title": source_title,
        "source_path": source_path,
        "drive_file_id": drive_file_id,
        "drive_folder_id": drive_folder_id,
        "source_ref_hash": source_ref_hash,
        "source_row_index": normalized_source_row_index,
        "completion_evidence_type": evidence_type,
        "completion_evidence_ref": evidence_ref,
        "completion_summary": require_summary_safe_text(row.get("completion_summary"), field_name="completion_summary", max_chars=ROADMAP_MAX_SUMMARY_CHARS),
        "completion_confidence": coerce_confidence(row.get("completion_confidence", 0)),
        "validation_status": "validated",
    }


def parse_roadmap_item_jsonl(
    path: Path,
    *,
    run_id: str,
    ingested_at: str,
    default_planned_month: str | None = None,
    default_source_type: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: expected JSON object")
        try:
            rows.append(
                normalize_roadmap_item_row(
                    payload,
                    run_id=run_id,
                    ingested_at=ingested_at,
                    default_planned_month=default_planned_month,
                    default_source_type=default_source_type,
                )
            )
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
    return rows


def roadmap_source_rows_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (item["client_slug"], item["period_id"], item["source_ref_hash"])
        output.setdefault(
            key,
            {
                "run_id": item["run_id"],
                "ingested_at": item["ingested_at"],
                "client_slug": item["client_slug"],
                "client_name": item["client_name"],
                "source_type": item["source_type"],
                "source_title": item["source_title"],
                "source_path": item["source_path"],
                "drive_file_id": item["drive_file_id"],
                "drive_folder_id": item["drive_folder_id"],
                "source_ref_hash": item["source_ref_hash"],
                "period_id": item["period_id"],
                "source_status": "active",
                "notes_summary": item["notes_summary"],
            },
        )
    return sorted(output.values(), key=lambda item: (item["client_slug"], item["period_id"], item["source_ref_hash"]))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_registry_rows(paths: SourcePaths, ingested_at: str) -> list[dict[str, Any]]:
    sources = [
        ("monday_board_index", "Monday board index", "csv", paths.monday_derived / "board_index.csv", "daily", "low"),
        ("monday_client_board_matrix", "Monday client board matrix", "csv", paths.monday_derived / "client_board_matrix.csv", "daily", "low"),
        ("monday_task_alignment", "Monday task alignment report", "csv", paths.monday_derived / "task_alignment_report.csv", "daily", "medium"),
        ("monday_status_labels", "Monday status label metadata", "csv", paths.monday_derived / "status_labels.csv", "daily", "low"),
        ("monday_board_snapshots", "Monday board JSON snapshots", "json", paths.monday_snapshots, "daily", "medium"),
        ("seo_client_sidecars", "SEO Automation client sidecars", "json", paths.seo_clients, "weekly", "medium"),
        ("seo_client_health_assets", "SEO Automation client health asset inventory", "metadata", paths.seo_clients, "weekly", "low"),
        ("drive_folder_verifications", "Google Drive MCP folder verification metadata", "json", paths.drive_folder_verifications, "weekly", "medium"),
        ("api_smoke_verifications", "GA4, Search Console, and SE Ranking smoke verification metadata", "json", paths.api_smoke_verifications, "weekly", "medium"),
        ("seo_client_timelines", "SEO Automation client timelines", "markdown", paths.seo_clients, "weekly", "medium"),
        ("reporting_client_config", "SEO Reporting client config", "json", paths.reporting_config / "clients.json", "weekly", "medium"),
        ("reporting_report_index", "SEO Reporting report index", "json", paths.reporting_content / "report-index.json", "monthly", "medium"),
        ("reporting_report_snapshots", "SEO Reporting report snapshots", "json", paths.reporting_content / "reports", "monthly", "medium"),
        ("client_roadmap_items", "Sanitized client roadmap item staging JSONL", "jsonl", PROJECTS_ROOT / "Big Query" / "data" / "roadmap_memory" / "staging", "weekly", "medium"),
        ("client_onboarding_profiles", "Sanitized client onboarding goals and priorities staging JSONL", "jsonl", paths.client_context_staging, "weekly", "medium"),
    ]
    return [
        {
            "source_id": source_id,
            "source_name": name,
            "source_type": source_type,
            "source_path": str(path),
            "refresh_cadence": cadence,
            "risk_level": risk,
            "owner": "codex",
            "notes": "Agency Ops Memory V1 source. One-way mirror into BigQuery.",
            "registered_at": ingested_at,
        }
        for source_id, name, source_type, path, cadence, risk in sources
    ]


def file_freshness_date(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()


def safe_asset_source_hash(value: str | None) -> str | None:
    if not value:
        return None
    if has_secret_like_text(value) or has_email_address(value):
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def local_markdown_status(path: Path, *, require_heading: bool = False, require_table_row: bool = False) -> tuple[str, str | None]:
    if not path.exists():
        return "missing", None
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        return "missing", "File exists but is empty."
    if require_heading and not re.search(r"(?m)^#\s+\S+", text):
        return "missing", "File exists but no top-level heading was found."
    if require_table_row:
        has_row = False
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|") or stripped.startswith("|---") or " Date " in stripped:
                continue
            cells = split_markdown_table_row(stripped, expected_cells=9)
            if cells and parse_date(cells[0]):
                has_row = True
                break
        if not has_row:
            return "missing", "File exists but no dated timeline rows were found."
    return "present", None


def sidecar_status(sidecar: dict[str, Any], sidecar_path: Path) -> tuple[str, str | None]:
    if not sidecar_path.exists():
        return "missing", None
    if not sidecar:
        return "missing", "Sidecar exists but did not parse as a JSON object."
    missing = []
    if not (sidecar.get("client") or sidecar.get("brand_display_name")):
        missing.append("client/brand_display_name")
    if not (sidecar.get("domain") or nested_get(sidecar, ("website", "canonical_host"))):
        missing.append("domain")
    if missing:
        return "missing", f"Sidecar exists but required field(s) are missing: {', '.join(missing)}."
    return "present", None


def add_health_asset(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
    client_slug: str,
    client_name: str,
    asset_type: str,
    asset_label: str,
    present: bool,
    expected: bool,
    criticality: str,
    source_system: str,
    source_path: str | None = None,
    source_ref: str | None = None,
    freshness_date: str | None = None,
    notes: str | None = None,
    presence_status: str | None = None,
    verification_level: str | None = None,
    verified_at: str | None = None,
    verification_method: str | None = None,
) -> None:
    status = presence_status or ("present" if present else "missing")
    if status not in {"present", "missing", "unknown"}:
        raise ValueError(f"Unsupported health asset presence_status: {status}")
    if verification_level and verification_level not in HEALTH_VERIFICATION_LEVELS:
        raise ValueError(f"Unsupported health asset verification_level: {verification_level}")
    clean_source_ref = str(source_ref).strip() if source_ref not in (None, "") else None
    if clean_source_ref and (has_secret_like_text(clean_source_ref) or has_email_address(clean_source_ref)):
        clean_source_ref = None
    rows.append(
        {
            "snapshot_date": snapshot_date,
            "ingested_at": ingested_at,
            "run_id": run_id,
            "client_slug": client_slug,
            "client_name": client_name,
            "asset_type": asset_type,
            "asset_label": asset_label,
            "presence_status": status,
            "expected": expected,
            "criticality": criticality,
            "source_system": source_system,
            "source_path": source_path,
            "source_ref": clean_source_ref,
            "source_ref_hash": safe_asset_source_hash(clean_source_ref),
            "freshness_date": freshness_date,
            "verification_level": verification_level,
            "verified_at": verified_at,
            "verification_method": verification_method,
            "notes": notes,
        }
    )


def load_drive_folder_verifications(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = load_json(path)
    if isinstance(payload, dict):
        entries = payload.get("folders", payload)
    else:
        entries = payload
    output: dict[str, dict[str, Any]] = {}
    if isinstance(entries, dict):
        iterator = entries.items()
    elif isinstance(entries, list):
        iterator = ((entry.get("folder_id") or entry.get("client_slug"), entry) for entry in entries if isinstance(entry, dict))
    else:
        return {}
    for key, entry in iterator:
        if not key or not isinstance(entry, dict):
            continue
        folder_id = str(entry.get("folder_id") or key).strip()
        client_slug = slugify(entry.get("client_slug")) if entry.get("client_slug") else ""
        if folder_id:
            output[folder_id] = entry
        if client_slug:
            output[client_slug] = entry
    return output


def load_api_smoke_verifications(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    payload = load_json(path)
    entries = payload.get("checks", payload.get("results", payload)) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return {}
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = slugify(entry.get("client_slug"))
        source = str(entry.get("source") or "").strip()
        if slug and source:
            output[(slug, source)] = entry
    return output


def drive_folder_status(
    verification: dict[str, Any] | None,
) -> tuple[str, str | None, str | None, str | None]:
    if not verification:
        return "unknown", None, None, "Folder route exists but Drive MCP metadata verification has not been run."
    verified_at = verification.get("verified_at")
    latest_modified = verification.get("latest_modified_date") or verification.get("latest_modified")
    if latest_modified:
        latest_modified = str(latest_modified)[:10]
    return "present", str(verified_at) if verified_at else None, latest_modified, "Drive MCP metadata verified folder access."


def roadmap_folder_verification_status(
    verification: dict[str, Any] | None,
) -> tuple[str, str | None, str | None]:
    if not verification:
        return "unknown", None, "Folder route exists but contents have not been verified through Drive MCP."

    populated_count = int(verification.get("populated_file_count") or verification.get("roadmap_file_count") or 0)
    file_count = int(verification.get("file_count") or populated_count or 0)
    latest_modified = verification.get("latest_modified_date") or verification.get("latest_modified")
    verified_at = verification.get("verified_at")
    if latest_modified:
        latest_modified = str(latest_modified)[:10]
    status = "present" if populated_count > 0 else "missing"
    notes = (
        f"Drive MCP verification found {populated_count} populated roadmap file(s) "
        f"from {file_count} folder item(s)."
    )
    if verified_at:
        notes = f"{notes} Verified at {str(verified_at)[:19]}."
    return status, latest_modified, notes


def roadmap_content_validation_status(
    verification: dict[str, Any] | None,
) -> tuple[str, str | None, str | None, str | None]:
    if not verification:
        return "unknown", None, None, "Roadmap content has not been checked with bounded Drive validation."
    verified_at = verification.get("content_verified_at") or verification.get("verified_at")
    latest_modified = verification.get("latest_modified_date") or verification.get("latest_modified")
    if latest_modified:
        latest_modified = str(latest_modified)[:10]
    validated_count = int(verification.get("content_validated_file_count") or 0)
    failed_count = int(verification.get("content_failed_file_count") or 0)
    if validated_count > 0:
        return (
            "present",
            str(verified_at) if verified_at else None,
            latest_modified,
            f"Bounded Drive validation found {validated_count} roadmap-shaped file(s).",
        )
    if failed_count > 0:
        return (
            "missing",
            str(verified_at) if verified_at else None,
            latest_modified,
            f"Bounded Drive validation ran but {failed_count} file(s) failed roadmap-shape checks.",
        )
    if int(verification.get("populated_file_count") or verification.get("roadmap_file_count") or 0) > 0:
        return "unknown", str(verified_at) if verified_at else None, latest_modified, "Files exist, but bounded content validation has not been run."
    return "missing", str(verified_at) if verified_at else None, latest_modified, "Drive MCP verification found no populated roadmap files to validate."


def api_smoke_status(
    checks: dict[tuple[str, str], dict[str, Any]],
    client_slug: str,
    source: str,
) -> tuple[str, str | None, str | None, str | None]:
    check = checks.get((client_slug, source))
    if not check:
        return "unknown", None, None, f"{source} smoke verification has not been run."
    checked_at = str(check.get("checked_at") or check.get("verified_at") or "") or None
    status = "present" if check.get("status") == "succeeded" else "missing"
    rows_returned = check.get("rows_returned")
    date_end = check.get("date_end")
    note = f"{source} smoke check {check.get('status')}."
    if rows_returned is not None:
        note = f"{note} rows_returned={rows_returned}."
    if check.get("error_class"):
        note = f"{note} error_class={check.get('error_class')}."
    return status, checked_at, str(date_end)[:10] if date_end else None, note


def maybe_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    return {}


def monthly_report_snapshot_status(report: dict[str, Any] | None) -> tuple[str, str | None, str | None]:
    if not report:
        return "missing", None, None
    headline = maybe_json_object(report.get("headline_metrics_json"))
    commentary = maybe_json_object(report.get("commentary_json"))
    missing = []
    if not (headline.get("ga4_current") or headline.get("ga4_overview")):
        missing.append("ga4")
    if not (headline.get("search_console_summary") or headline.get("search_console_current")):
        missing.append("searchConsole")
    if not commentary.get("summary"):
        missing.append("commentary.summary")
    if missing:
        return "missing", report.get("report_month"), f"Latest report snapshot exists but missing section(s): {', '.join(missing)}."
    return "present", report.get("report_month"), "Latest report snapshot has core metric and commentary sections."


def reporting_config_status(reporting_client: dict[str, Any]) -> tuple[str, str | None]:
    if not reporting_client:
        return "missing", None
    missing = []
    for key in ("slug", "name", "template", "websiteHosts"):
        if not reporting_client.get(key):
            missing.append(key)
    if missing:
        return "missing", f"Reporting config exists but missing field(s): {', '.join(missing)}."
    return "present", None



def parse_client_health_assets(
    paths: SourcePaths,
    client_board_rows: list[dict[str, str]],
    *,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
) -> list[dict[str, Any]]:
    sidecars: dict[str, dict[str, Any]] = {}
    drive_folder_verifications = load_drive_folder_verifications(paths.drive_folder_verifications)
    api_smoke_verifications = load_api_smoke_verifications(paths.api_smoke_verifications)
    reporting_clients = load_reporting_clients(paths.reporting_config / "clients.json")
    reporting_by_slug = {
        canonical_client_slug(client.get("slug") or client.get("name")): client
        for client in reporting_clients
        if canonical_client_slug(client.get("slug") or client.get("name"))
    }
    known_slug_by_board_id: dict[str, str] = {}
    clients: dict[str, dict[str, Any]] = {
        slug: {"client_name": client.get("name") or slug}
        for slug, client in reporting_by_slug.items()
    }

    for path in sorted(paths.seo_clients.glob("*.json")):
        if path.name.startswith("CLIENT_TEMPLATE"):
            continue
        try:
            payload = load_json(path)
        except json.JSONDecodeError:
            continue
        slug = canonical_client_slug(path.stem)
        if not slug:
            continue
        sidecars[slug] = {"path": path, "payload": payload}
        board_id = nested_get(payload, ("monday", "board_id"))
        if board_id:
            known_slug_by_board_id[str(board_id)] = slug

    for slug, client in reporting_by_slug.items():
        board_id = nested_get(client, ("monday", "boardId"))
        if board_id:
            known_slug_by_board_id[str(board_id)] = slug

    board_by_slug: dict[str, dict[str, str]] = {}
    for row in client_board_rows:
        raw_slug = canonical_client_slug(row.get("client_slug") or row.get("client_name"))
        board_id = str(row.get("client_board_id") or "")
        slug = known_slug_by_board_id.get(board_id, raw_slug)
        if not slug or slug not in reporting_by_slug:
            continue
        board_by_slug[slug] = row

    latest_reports: dict[str, dict[str, Any]] = {}
    for report in parse_monthly_report_snapshots(paths, run_id, ingested_at):
        report_month = report.get("report_month")
        latest = latest_reports.get(report["client_slug"])
        if report_month and (not latest or report_month > str(latest.get("report_month") or "")):
            latest_reports[report["client_slug"]] = report

    rows: list[dict[str, Any]] = []
    for slug in sorted(clients):
        sidecar_entry = sidecars.get(slug)
        sidecar = sidecar_entry["payload"] if sidecar_entry else {}
        sidecar_path = sidecar_entry["path"] if sidecar_entry else paths.seo_clients / f"{slug}.json"
        brief_path = paths.seo_clients / f"{slug}.md"
        timeline_path = paths.seo_clients / f"{slug}-timeline.md"
        writing_style_path = paths.seo_clients / f"{slug}-writing-style.md"
        reporting_client = reporting_by_slug.get(slug) or {}
        board_row = board_by_slug.get(slug) or {}
        client_name = (
            clients[slug].get("client_name")
            or sidecar.get("brand_display_name")
            or reporting_client.get("name")
            or board_row.get("client_name")
            or slug
        )
        drive = sidecar.get("drive") or {}
        drive_folders = drive.get("folders") or {}
        root_folder_id = str(drive.get("client_folder_id") or "").strip()
        roadmap_folder_id = str(drive_folders.get("02_roadmap") or "").strip()
        content_folder_id = str(drive_folders.get("05_content") or drive_folders.get("05_content_blogs") or "").strip()
        reports_folder_id = str(drive_folders.get("07_reports") or "").strip()
        root_verification = drive_folder_verifications.get(root_folder_id) or drive_folder_verifications.get(f"{slug}:drive_root")
        roadmap_verification = drive_folder_verifications.get(roadmap_folder_id) or drive_folder_verifications.get(slug)
        content_verification = drive_folder_verifications.get(content_folder_id) or drive_folder_verifications.get(f"{slug}:drive_content_folder")
        reports_verification = drive_folder_verifications.get(reports_folder_id) or drive_folder_verifications.get(f"{slug}:drive_reports_folder")
        root_folder_status, root_verified_at, root_freshness, root_notes = drive_folder_status(root_verification)
        roadmap_folder_status, roadmap_folder_verified_at, roadmap_folder_freshness, roadmap_folder_notes = drive_folder_status(roadmap_verification)
        roadmap_file_status, roadmap_file_freshness, roadmap_file_notes = roadmap_folder_verification_status(
            roadmap_verification
        )
        roadmap_content_status, roadmap_content_verified_at, roadmap_content_freshness, roadmap_content_notes = roadmap_content_validation_status(roadmap_verification)
        content_folder_status, content_verified_at, content_freshness, content_notes = drive_folder_status(content_verification)
        reports_folder_status, reports_verified_at, reports_freshness, reports_notes = drive_folder_status(reports_verification)
        monday_board_id = nested_get(sidecar, ("monday", "board_id")) or nested_get(reporting_client, ("monday", "boardId")) or board_row.get("client_board_id")
        ga4_property = sidecar.get("ga4_property") or nested_get(reporting_client, ("ga4", "property"))
        search_console = nested_get(reporting_client, ("searchConsole", "properties"))
        se_ranking_project = nested_get(sidecar, ("se_ranking", "project_id")) or nested_get(reporting_client, ("seRanking", "projectId"))
        sidecar_presence, sidecar_notes = sidecar_status(sidecar, sidecar_path)
        brief_presence, brief_notes = local_markdown_status(brief_path, require_heading=True)
        timeline_presence, timeline_notes = local_markdown_status(timeline_path, require_table_row=True)
        writing_style_presence, writing_style_notes = local_markdown_status(writing_style_path)
        brand_writing_guide = sidecar.get("brand_writing_guide") if isinstance(sidecar.get("brand_writing_guide"), dict) else {}
        brand_guide_doc_id = str(brand_writing_guide.get("google_doc_id") or "").strip()
        brand_guide_doc_url = str(brand_writing_guide.get("google_doc_url") or "").strip()
        brand_guide_folder_id = str(brand_writing_guide.get("drive_folder_id") or "").strip()
        brand_guide_status = str(brand_writing_guide.get("status") or "").strip()
        brand_guide_presence = "present" if brand_guide_doc_id and brand_guide_doc_url and brand_guide_folder_id else "missing"
        brand_guide_notes = (
            f"Client-editable brand writing guide Doc recorded with status `{brand_guide_status}`."
            if brand_guide_presence == "present"
            else "No client-editable brand writing guide Google Doc is recorded in the sidecar."
        )
        reporting_presence, reporting_notes = reporting_config_status(reporting_client)
        report_presence, report_freshness, report_notes = monthly_report_snapshot_status(latest_reports.get(slug))
        ga4_smoke_presence, ga4_smoke_at, ga4_smoke_freshness, ga4_smoke_notes = api_smoke_status(api_smoke_verifications, slug, "ga4")
        gsc_smoke_presence, gsc_smoke_at, gsc_smoke_freshness, gsc_smoke_notes = api_smoke_status(api_smoke_verifications, slug, "gsc")
        se_smoke_presence, se_smoke_at, se_smoke_freshness, se_smoke_notes = api_smoke_status(api_smoke_verifications, slug, "se_ranking")
        monday_snapshot_present = bool(board_row and str(board_row.get("client_board_id") or "") == str(monday_board_id or ""))

        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="sidecar_json", asset_label="SEO Automation sidecar JSON", present=sidecar_presence == "present", expected=True, criticality="high", source_system="seo_automation", source_path=str(sidecar_path), freshness_date=file_freshness_date(sidecar_path), notes=sidecar_notes, presence_status=sidecar_presence, verification_level="local_content", verification_method="json_parse_required_fields")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="client_brief", asset_label="SEO Automation client brief", present=brief_presence == "present", expected=True, criticality="high", source_system="seo_automation", source_path=str(brief_path), freshness_date=file_freshness_date(brief_path), notes=brief_notes, presence_status=brief_presence, verification_level="local_content", verification_method="markdown_nonempty_heading")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="timeline", asset_label="Client timeline", present=timeline_presence == "present", expected=True, criticality="medium", source_system="seo_automation", source_path=str(timeline_path), freshness_date=file_freshness_date(timeline_path), notes=timeline_notes, presence_status=timeline_presence, verification_level="local_content", verification_method="markdown_dated_table_rows")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="writing_style", asset_label="Client writing-style guide", present=writing_style_presence == "present", expected=False, criticality="low", source_system="seo_automation", source_path=str(writing_style_path), freshness_date=file_freshness_date(writing_style_path), notes=writing_style_notes, presence_status=writing_style_presence, verification_level="local_content", verification_method="markdown_nonempty")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="brand_writing_guide_doc", asset_label="Client-editable brand writing guide Google Doc", present=brand_guide_presence == "present", expected=False, criticality="low", source_system="seo_automation_sidecar", source_path=str(sidecar_path) if sidecar_path.exists() else None, source_ref=brand_guide_doc_id or None, freshness_date=brand_writing_guide.get("created_at") if brand_writing_guide else None, notes=brand_guide_notes, presence_status=brand_guide_presence, verification_level="route_config", verification_method="sidecar_brand_writing_guide_google_doc")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_root", asset_label="Google Drive client folder route", present=bool(root_folder_id), expected=True, criticality="high", source_system="seo_automation_sidecar", source_path=str(sidecar_path) if sidecar_path.exists() else None, source_ref=root_folder_id or None, verification_level="route_config", verification_method="sidecar_folder_id")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_root_verified", asset_label="Verified Google Drive client folder", present=root_folder_status == "present", expected=True, criticality="high", source_system="google_drive_mcp", source_path=str(paths.drive_folder_verifications), source_ref=root_folder_id or None, freshness_date=root_freshness, notes=root_notes if root_folder_id else "No Drive root folder route is configured.", presence_status=root_folder_status if root_folder_id else "missing", verification_level="metadata_verified", verified_at=root_verified_at, verification_method="drive_mcp_folder_metadata")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_roadmap_folder", asset_label="Google Drive roadmap folder route configured", present=bool(roadmap_folder_id), expected=True, criticality="medium", source_system="seo_automation_sidecar", source_path=str(sidecar_path) if sidecar_path.exists() else None, source_ref=roadmap_folder_id or None, verification_level="route_config", verification_method="sidecar_folder_id")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_roadmap_folder_verified", asset_label="Verified Google Drive roadmap folder", present=roadmap_folder_status == "present", expected=True, criticality="medium", source_system="google_drive_mcp", source_path=str(paths.drive_folder_verifications), source_ref=roadmap_folder_id or None, freshness_date=roadmap_folder_freshness, notes=roadmap_folder_notes if roadmap_folder_id else "No roadmap folder route is configured.", presence_status=roadmap_folder_status if roadmap_folder_id else "missing", verification_level="metadata_verified", verified_at=roadmap_folder_verified_at, verification_method="drive_mcp_folder_metadata")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_roadmap_files", asset_label="Verified populated roadmap files", present=roadmap_file_status == "present", expected=True, criticality="high", source_system="google_drive_mcp", source_path=str(paths.drive_folder_verifications), source_ref=roadmap_folder_id or None, freshness_date=roadmap_file_freshness, notes=roadmap_file_notes if roadmap_folder_id else "No roadmap folder route is configured.", presence_status=roadmap_file_status if roadmap_folder_id else "missing", verification_level="metadata_verified", verified_at=roadmap_folder_verified_at, verification_method="drive_mcp_file_metadata")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_roadmap_content", asset_label="Bounded validated roadmap content", present=roadmap_content_status == "present", expected=True, criticality="high", source_system="google_drive_mcp", source_path=str(paths.drive_folder_verifications), source_ref=roadmap_folder_id or None, freshness_date=roadmap_content_freshness, notes=roadmap_content_notes if roadmap_folder_id else "No roadmap folder route is configured.", presence_status=roadmap_content_status if roadmap_folder_id else "missing", verification_level="bounded_content_validated", verified_at=roadmap_content_verified_at, verification_method="drive_mcp_bounded_sheet_validation")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_content_folder", asset_label="Google Drive content folder route", present=bool(content_folder_id), expected=True, criticality="medium", source_system="seo_automation_sidecar", source_path=str(sidecar_path) if sidecar_path.exists() else None, source_ref=content_folder_id or None, verification_level="route_config", verification_method="sidecar_folder_id")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_content_folder_verified", asset_label="Verified Google Drive content folder", present=content_folder_status == "present", expected=True, criticality="medium", source_system="google_drive_mcp", source_path=str(paths.drive_folder_verifications), source_ref=content_folder_id or None, freshness_date=content_freshness, notes=content_notes if content_folder_id else "No content folder route is configured.", presence_status=content_folder_status if content_folder_id else "missing", verification_level="metadata_verified", verified_at=content_verified_at, verification_method="drive_mcp_folder_metadata")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_reports_folder", asset_label="Google Drive reports folder route", present=bool(reports_folder_id), expected=True, criticality="medium", source_system="seo_automation_sidecar", source_path=str(sidecar_path) if sidecar_path.exists() else None, source_ref=reports_folder_id or None, verification_level="route_config", verification_method="sidecar_folder_id")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="drive_reports_folder_verified", asset_label="Verified Google Drive reports folder", present=reports_folder_status == "present", expected=True, criticality="medium", source_system="google_drive_mcp", source_path=str(paths.drive_folder_verifications), source_ref=reports_folder_id or None, freshness_date=reports_freshness, notes=reports_notes if reports_folder_id else "No reports folder route is configured.", presence_status=reports_folder_status if reports_folder_id else "missing", verification_level="metadata_verified", verified_at=reports_verified_at, verification_method="drive_mcp_folder_metadata")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="monday_board", asset_label="Monday client board route", present=bool(monday_board_id), expected=True, criticality="high", source_system="seo_automation_or_reporting", source_path=str(sidecar_path) if sidecar_path.exists() else str(paths.reporting_config / "clients.json"), source_ref=str(monday_board_id) if monday_board_id else None, verification_level="route_config", verification_method="sidecar_or_reporting_board_id")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="monday_board_snapshot", asset_label="Verified Monday board snapshot", present=monday_snapshot_present, expected=True, criticality="high", source_system="monday_agency_hub", source_path=str(paths.monday_derived / "client_board_matrix.csv"), source_ref=str(monday_board_id) if monday_board_id else None, notes=None if monday_snapshot_present else "Configured Monday board was not confirmed in the local client board matrix.", presence_status="present" if monday_snapshot_present else "missing", verification_level="metadata_verified", verification_method="local_monday_board_matrix")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="reporting_config", asset_label="SEO Reporting client config", present=reporting_presence == "present", expected=True, criticality="medium", source_system="seo_reporting_platform", source_path=str(paths.reporting_config / "clients.json"), source_ref=slug if reporting_client else None, notes=reporting_notes, presence_status=reporting_presence, verification_level="local_content", verification_method="reporting_config_required_fields")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="ga4_property", asset_label="GA4 property route", present=bool(ga4_property), expected=True, criticality="high", source_system="seo_automation_or_reporting", source_path=str(sidecar_path) if sidecar_path.exists() else str(paths.reporting_config / "clients.json"), source_ref=str(ga4_property) if ga4_property else None, verification_level="route_config", verification_method="sidecar_or_reporting_property")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="ga4_access", asset_label="Verified GA4 access smoke check", present=ga4_smoke_presence == "present", expected=True, criticality="high", source_system="google_analytics_data_api", source_path=str(paths.api_smoke_verifications), source_ref=slug, freshness_date=ga4_smoke_freshness, notes=ga4_smoke_notes, presence_status=ga4_smoke_presence, verification_level="api_smoke", verified_at=ga4_smoke_at, verification_method="smoke_reporting_apis")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="search_console", asset_label="Search Console route", present=bool(search_console), expected=True, criticality="high", source_system="seo_reporting_platform", source_path=str(paths.reporting_config / "clients.json"), source_ref=slug if search_console else None, verification_level="route_config", verification_method="reporting_config_search_console_properties")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="search_console_access", asset_label="Verified Search Console access smoke check", present=gsc_smoke_presence == "present", expected=True, criticality="high", source_system="google_search_console_api", source_path=str(paths.api_smoke_verifications), source_ref=slug, freshness_date=gsc_smoke_freshness, notes=gsc_smoke_notes, presence_status=gsc_smoke_presence, verification_level="api_smoke", verified_at=gsc_smoke_at, verification_method="smoke_reporting_apis")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="se_ranking", asset_label="SE Ranking project route", present=bool(se_ranking_project), expected=True, criticality="medium", source_system="seo_automation_or_reporting", source_path=str(sidecar_path) if sidecar_path.exists() else str(paths.reporting_config / "clients.json"), source_ref=str(se_ranking_project) if se_ranking_project else None, verification_level="route_config", verification_method="sidecar_or_reporting_se_ranking_project")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="se_ranking_access", asset_label="Verified SE Ranking access smoke check", present=se_smoke_presence == "present", expected=True, criticality="medium", source_system="se_ranking_api", source_path=str(paths.api_smoke_verifications), source_ref=slug, freshness_date=se_smoke_freshness, notes=se_smoke_notes, presence_status=se_smoke_presence, verification_level="api_smoke", verified_at=se_smoke_at, verification_method="smoke_reporting_apis")
        add_health_asset(rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date, client_slug=slug, client_name=client_name, asset_type="monthly_report_snapshot", asset_label="Latest monthly report snapshot", present=report_presence == "present", expected=True, criticality="medium", source_system="seo_reporting_platform", source_path=str(paths.reporting_content / "reports"), source_ref=report_freshness, freshness_date=report_freshness, notes=report_notes, presence_status=report_presence, verification_level="local_content", verification_method="report_json_required_sections")
    return rows


def collect_agency_ops_rows(
    paths: SourcePaths,
    *,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
) -> dict[str, list[dict[str, Any]]]:
    board_index = read_csv_rows(paths.monday_derived / "board_index.csv")
    client_board_rows = read_csv_rows(paths.monday_derived / "client_board_matrix.csv")
    task_alignment_rows = read_csv_rows(paths.monday_derived / "task_alignment_report.csv")
    status_label_csv_rows = read_csv_rows(paths.monday_derived / "status_labels.csv")
    board_roles = {str(row.get("board_id", "")): row for row in board_index}
    client_by_board = {
        str(row.get("client_board_id", "")): row
        for row in client_board_rows
        if row.get("client_board_id")
    }

    collected = {
        "agency_staging.agency_ops_records": [],
        "agency_memory.monday_boards": parse_board_index_rows(board_index, run_id, ingested_at, snapshot_date),
        "agency_memory.monday_board_columns": [],
        "agency_memory.monday_status_labels": parse_status_label_csv_rows(
            status_label_csv_rows,
            run_id=run_id,
            ingested_at=ingested_at,
            snapshot_date=snapshot_date,
        ),
        "agency_memory.monday_items": [],
        "agency_memory.monday_item_column_values": [],
        "agency_memory.client_registry": parse_client_registry(paths, client_board_rows, run_id, ingested_at),
        "agency_memory.client_onboarding_profiles": parse_client_onboarding_profiles(paths, run_id=run_id, ingested_at=ingested_at),
        "agency_memory.client_board_map": parse_client_board_map_rows(client_board_rows, run_id, ingested_at),
        "agency_memory.task_alignment": parse_task_alignment_rows(task_alignment_rows, run_id, ingested_at, snapshot_date),
        "agency_memory.client_timeline_events": parse_timeline_events(paths.seo_clients, run_id, ingested_at),
        "agency_memory.monthly_report_snapshots": parse_monthly_report_snapshots(paths, run_id, ingested_at),
        "agency_memory.client_health_assets": parse_client_health_assets(
            paths,
            client_board_rows,
            run_id=run_id,
            ingested_at=ingested_at,
            snapshot_date=snapshot_date,
        ),
    }

    board_snapshot_rows = parse_monday_board_snapshots(
        paths.monday_snapshots,
        board_roles=board_roles,
        client_by_board=client_by_board,
        run_id=run_id,
        ingested_at=ingested_at,
        snapshot_date=snapshot_date,
    )
    for table_name, rows in board_snapshot_rows.items():
        if table_name == "monday_status_labels":
            collected[f"agency_memory.{table_name}"].extend(rows)
        else:
            collected[f"agency_memory.{table_name}"] = rows
    collected["agency_memory.monday_status_labels"] = dedupe_rows(
        collected["agency_memory.monday_status_labels"],
        ("board_id", "column_id", "label_id", "is_subitem"),
    )

    for table_name, rows in list(collected.items()):
        if table_name == "agency_staging.agency_ops_records":
            continue
        collected["agency_staging.agency_ops_records"].extend(
            make_staging_rows(table_name, rows, run_id=run_id, ingested_at=ingested_at, snapshot_date=snapshot_date)
        )
    return collected


def parse_board_index_rows(
    rows: list[dict[str, str]],
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        role = (row.get("role") or "").strip()
        if role and role not in V1_BOARD_ROLES:
            continue
        output.append(
            {
                "snapshot_date": snapshot_date,
                "ingested_at": ingested_at,
                "run_id": run_id,
                "board_id": str(row.get("board_id") or ""),
                "board_name": row.get("board_name") or "",
                "role": role or None,
                "role_label": row.get("role_label") or None,
                "board_kind": row.get("board_kind") or None,
                "permissions": row.get("permissions") or None,
                "state": row.get("state") or None,
                "items_count": int(row["items_count"]) if row.get("items_count") else None,
                "group_count": int(row["group_count"]) if row.get("group_count") else None,
                "column_count": int(row["column_count"]) if row.get("column_count") else None,
                "group_titles": row.get("group_titles") or None,
                "column_titles": row.get("column_titles") or None,
                "board_family": row.get("board_family") or None,
                "alias_risk": row.get("alias_risk") or None,
            }
        )
    return output


def parse_client_board_map_rows(rows: list[dict[str, str]], run_id: str, ingested_at: str) -> list[dict[str, Any]]:
    return [
        {
            "ingested_at": ingested_at,
            "run_id": run_id,
            "client_slug": canonical_client_slug(row.get("client_slug") or row.get("client_name")),
            "client_name": row.get("client_name") or "",
            "client_board_id": row.get("client_board_id") or None,
            "client_board_name": row.get("client_board_name") or None,
            "board_kind": row.get("board_kind") or None,
            "permissions": row.get("permissions") or None,
            "seo_execution_board_id": row.get("seo_execution_board_id") or None,
            "seo_execution_board_name": row.get("seo_execution_board_name") or None,
            "notes": row.get("notes") or None,
        }
        for row in rows
    ]


def parse_task_alignment_rows(
    rows: list[dict[str, str]],
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        output.append(
            {
                "snapshot_date": snapshot_date,
                "ingested_at": ingested_at,
                "run_id": run_id,
                "client": row.get("client") or None,
                "seo_task_item_id": row.get("seo_task_item_id") or None,
                "seo_task_name": row.get("seo_task_name") or None,
                "seo_status": row.get("seo_status") or None,
                "seo_owner": row.get("seo_owner") or None,
                "seo_due_date": parse_date(row.get("seo_due_date")),
                "client_board_id": row.get("client_board_id") or None,
                "client_board_name": row.get("client_board_name") or None,
                "client_task_item_id": row.get("client_task_item_id") or None,
                "client_task_name": row.get("client_task_name") or None,
                "client_status": row.get("client_status") or None,
                "client_owner": row.get("client_owner") or None,
                "client_due_date": parse_date(row.get("client_due_date")),
                "status_match": parse_bool(row.get("status_match")),
                "owner_match": parse_bool(row.get("owner_match")),
                "due_date_match": parse_bool(row.get("due_date_match")),
                "stale_client_update": parse_bool(row.get("stale_client_update")),
                "mismatch_reason": row.get("mismatch_reason") or None,
            }
        )
    return output


def parse_status_label_csv_rows(
    rows: list[dict[str, str]],
    *,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
) -> list[dict[str, Any]]:
    output = []
    seen: set[tuple[str, str, str, bool]] = set()
    for row in rows:
        role = row.get("role") or ""
        if role and role not in V1_BOARD_ROLES:
            continue
        key = (str(row.get("board_id") or ""), str(row.get("column_id") or ""), str(row.get("label_id") or ""), parse_bool(row.get("is_subitem")) or False)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "snapshot_date": snapshot_date,
                "ingested_at": ingested_at,
                "run_id": run_id,
                "board_id": key[0],
                "board_name": row.get("board_name") or "",
                "column_id": key[1],
                "column_title": row.get("column_title") or "",
                "label_id": key[2],
                "label_index": int(row["label_index"]) if str(row.get("label_index") or "").isdigit() else None,
                "label": row.get("label") or "",
                "color": str(row.get("color") or "") or None,
                "hex": row.get("hex") or None,
                "is_done": parse_bool(row.get("is_done")),
                "is_deactivated": parse_bool(row.get("is_deactivated")),
                "is_subitem": key[3],
            }
        )
    return output


def dedupe_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen = set()
    output = []
    for row in rows:
        key = tuple(row.get(item) for item in keys)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def parse_monday_board_snapshots(
    snapshot_dir: Path,
    *,
    board_roles: dict[str, dict[str, str]],
    client_by_board: dict[str, dict[str, str]],
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
) -> dict[str, list[dict[str, Any]]]:
    output = {
        "monday_board_columns": [],
        "monday_status_labels": [],
        "monday_items": [],
        "monday_item_column_values": [],
    }
    if not snapshot_dir.exists():
        return output

    allowed_board_ids = {
        board_id
        for board_id, row in board_roles.items()
        if (row.get("role") or "") in V1_BOARD_ROLES
    }
    for path in sorted(snapshot_dir.glob("board_*.json")):
        payload = load_json(path)
        board_id = str(payload.get("id") or path.stem.removeprefix("board_"))
        if allowed_board_ids and board_id not in allowed_board_ids:
            continue
        board_name = payload.get("name") or ""
        columns = list(payload.get("columns") or [])
        subitem_columns = list(payload.get("subItemColumns") or [])
        column_lookup = {column.get("id"): column for column in columns if column.get("id")}

        output["monday_board_columns"].extend(
            parse_board_columns(columns, board_id, board_name, run_id, ingested_at, snapshot_date, is_subitem=False)
        )
        output["monday_board_columns"].extend(
            parse_board_columns(subitem_columns, board_id, board_name, run_id, ingested_at, snapshot_date, is_subitem=True)
        )
        output["monday_status_labels"].extend(
            parse_status_labels(columns, board_id, board_name, run_id, ingested_at, snapshot_date, is_subitem=False)
        )
        output["monday_status_labels"].extend(
            parse_status_labels(subitem_columns, board_id, board_name, run_id, ingested_at, snapshot_date, is_subitem=True)
        )

        client_row = client_by_board.get(board_id)
        client_slug = client_row.get("client_slug") if client_row else infer_client_slug(board_name, None)
        items = payload.get("items_page", {}).get("items") or []
        for item in items:
            item_rows = parse_item(
                item,
                board_id=board_id,
                board_name=board_name,
                column_lookup=column_lookup,
                client_slug=client_slug,
                run_id=run_id,
                ingested_at=ingested_at,
                snapshot_date=snapshot_date,
                is_subitem=False,
                parent_item_id=None,
            )
            output["monday_items"].append(item_rows[0])
            output["monday_item_column_values"].extend(item_rows[1])
    return output


def parse_board_columns(
    columns: list[dict[str, Any]],
    board_id: str,
    board_name: str,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
    *,
    is_subitem: bool,
) -> list[dict[str, Any]]:
    rows = []
    for column in columns:
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "ingested_at": ingested_at,
                "run_id": run_id,
                "board_id": board_id,
                "board_name": board_name,
                "column_id": str(column.get("id") or ""),
                "column_title": column.get("title") or "",
                "column_type": column.get("type") or "",
                "settings_json": json_dump(column.get("settings") or {}),
                "revision": column.get("revision") or None,
                "is_subitem": is_subitem,
            }
        )
    return rows


def parse_status_labels(
    columns: list[dict[str, Any]],
    board_id: str,
    board_name: str,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
    *,
    is_subitem: bool,
) -> list[dict[str, Any]]:
    rows = []
    for column in columns:
        if column.get("type") != "status":
            continue
        labels = normalize_status_label_settings((column.get("settings") or {}).get("labels"))
        for label in labels:
            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "ingested_at": ingested_at,
                    "run_id": run_id,
                    "board_id": board_id,
                    "board_name": board_name,
                    "column_id": str(column.get("id") or ""),
                    "column_title": column.get("title") or "",
                    "label_id": str(label.get("id") or label.get("index") or label.get("label") or ""),
                    "label_index": int(label["index"]) if label.get("index") is not None else None,
                    "label": label.get("label") or "",
                    "color": str(label.get("color")) if label.get("color") is not None else None,
                    "hex": label.get("hex") or None,
                    "is_done": label.get("is_done"),
                    "is_deactivated": label.get("is_deactivated"),
                    "is_subitem": is_subitem,
                }
            )
    return rows


def normalize_status_label_settings(labels: Any) -> list[dict[str, Any]]:
    if isinstance(labels, list):
        return [label for label in labels if isinstance(label, dict)]
    if isinstance(labels, dict):
        output = []
        for label_id, value in labels.items():
            if isinstance(value, dict):
                label = dict(value)
                label.setdefault("id", label_id)
                output.append(label)
            elif isinstance(value, str):
                output.append({"id": label_id, "label": value})
        return output
    return []


def parse_item(
    item: dict[str, Any],
    *,
    board_id: str,
    board_name: str,
    column_lookup: dict[str, dict[str, Any]],
    client_slug: str | None,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
    is_subitem: bool,
    parent_item_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values = item.get("column_values") or []
    safe_column_rows = []
    status = None
    owner = None
    due_date = None
    date_value = None
    files_present = False
    notes_present = False

    for value in values:
        column_id = value.get("id")
        column = column_lookup.get(column_id, {})
        column_type = column.get("type") or ""
        column_title = column.get("title") or ""
        text_value = value.get("text")
        title_key = column_title.strip().lower()

        if title_key in TEXT_TITLES_TO_REDACT:
            if text_value:
                notes_present = True
            continue
        if column_type == "file" and text_value:
            files_present = True
            continue
        if column_type == "status" and status is None:
            status = text_value or None
        if column_type == "people" and owner is None:
            owner = text_value or None
        if column_type == "date":
            parsed = parse_date(text_value)
            if "due" in title_key and due_date is None:
                due_date = parsed
            elif date_value is None:
                date_value = parsed

        if not is_safe_column_value(column_type, column_title, text_value):
            continue
        safe_column_rows.append(
            {
                "snapshot_date": snapshot_date,
                "ingested_at": ingested_at,
                "run_id": run_id,
                "board_id": board_id,
                "item_id": str(item.get("id") or ""),
                "column_id": str(column_id or ""),
                "column_title": column_title or None,
                "column_type": column_type or None,
                "text_value": text_value or None,
                "is_subitem": is_subitem,
            }
        )

    item_name = item.get("name") or ""
    effective_client_slug = client_slug or infer_client_slug(board_name, item_name)
    row = {
        "snapshot_date": snapshot_date,
        "ingested_at": ingested_at,
        "run_id": run_id,
        "board_id": board_id,
        "board_name": board_name,
        "item_id": str(item.get("id") or ""),
        "item_name": item_name,
        "group_id": (item.get("group") or {}).get("id"),
        "group_title": (item.get("group") or {}).get("title"),
        "updated_at": parse_timestamp(item.get("updated_at")),
        "parent_item_id": parent_item_id,
        "is_subitem": is_subitem,
        "client_slug": effective_client_slug,
        "status": status,
        "normalized_status": normalize_status(status),
        "owner": owner,
        "due_date": due_date,
        "date_value": date_value,
        "files_present": files_present,
        "notes_present": notes_present,
    }
    return row, safe_column_rows


def is_safe_column_value(column_type: str, column_title: str, text_value: Any) -> bool:
    if text_value in (None, ""):
        return False
    if has_secret_like_text(text_value):
        return False
    title_key = column_title.strip().lower()
    if title_key in TEXT_TITLES_TO_REDACT:
        return False
    return column_type in SAFE_COLUMN_TYPES or (column_type == "text" and title_key in SAFE_TEXT_COLUMN_TITLES)


def infer_client_slug(board_name: str | None, item_name: str | None) -> str | None:
    if board_name and board_name not in {"SEO Tasks", "Client Board"}:
        return canonical_client_slug(board_name)
    if item_name and "::" in item_name:
        return canonical_client_slug(item_name.split("::", 1)[0])
    return None


def parse_client_registry(
    paths: SourcePaths,
    client_board_rows: list[dict[str, str]],
    run_id: str,
    ingested_at: str,
) -> list[dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    favicon_overrides = load_client_favicon_overrides(paths.big_query / "config" / "client_favicons.json")
    for row in client_board_rows:
        slug = canonical_client_slug(row.get("client_slug") or row.get("client_name"))
        registry[slug] = {
            "ingested_at": ingested_at,
            "run_id": run_id,
            "client_slug": slug,
            "client_name": row.get("client_name") or slug,
            "abn": None,
            "primary_contact_name": None,
            "primary_contact_role": None,
            "canonical_host": None,
            "website_hosts_json": None,
            "favicon_url": None,
            "favicon_source": None,
            "favicon_candidates_json": None,
            "ga4_property": None,
            "search_console_json": None,
            "se_ranking_project_id": None,
            "monday_board_id": row.get("client_board_id") or None,
            "reporting_template": None,
            "source_paths_json": {"monday_client_board_matrix": str(paths.monday_derived / "client_board_matrix.csv")},
            "status": "active",
        }

    reporting_clients = load_reporting_clients(paths.reporting_config / "clients.json")
    for client in reporting_clients:
        slug = canonical_client_slug(client.get("slug") or client.get("name"))
        entry = registry.setdefault(
            slug,
            {
                "ingested_at": ingested_at,
                "run_id": run_id,
                "client_slug": slug,
                "client_name": client.get("name") or slug,
                "abn": None,
                "primary_contact_name": None,
                "primary_contact_role": None,
                "canonical_host": None,
                "website_hosts_json": None,
                "favicon_url": None,
                "favicon_source": None,
                "favicon_candidates_json": None,
                "ga4_property": None,
                "search_console_json": None,
                "se_ranking_project_id": None,
                "monday_board_id": None,
                "reporting_template": None,
                "source_paths_json": {},
                "status": "active",
            },
        )
        entry["client_name"] = entry.get("client_name") or client.get("name") or slug
        entry["canonical_host"] = client.get("canonicalHost") or entry.get("canonical_host")
        entry["website_hosts_json"] = json_dump(client.get("websiteHosts")) or entry.get("website_hosts_json")
        entry["ga4_property"] = nested_get(client, ("ga4", "property")) or entry.get("ga4_property")
        entry["search_console_json"] = json_dump(client.get("searchConsole")) or entry.get("search_console_json")
        entry["se_ranking_project_id"] = str(nested_get(client, ("seRanking", "projectId")) or entry.get("se_ranking_project_id") or "") or None
        entry["monday_board_id"] = str(nested_get(client, ("monday", "boardId")) or entry.get("monday_board_id") or "") or None
        entry["reporting_template"] = client.get("template") or entry.get("reporting_template")
        entry.setdefault("source_paths_json", {})["reporting_clients"] = str(paths.reporting_config / "clients.json")

    for sidecar_path in sorted(paths.seo_clients.glob("*.json")):
        if sidecar_path.name.startswith("CLIENT_TEMPLATE"):
            continue
        try:
            sidecar = load_json(sidecar_path)
        except json.JSONDecodeError:
            continue
        slug = sidecar.get("client") or sidecar_path.stem
        slug = slugify(slug)
        entry = registry.setdefault(
            slug,
            {
                "ingested_at": ingested_at,
                "run_id": run_id,
                "client_slug": slug,
                "client_name": sidecar.get("brand_display_name") or slug,
                "abn": None,
                "primary_contact_name": None,
                "primary_contact_role": None,
                "canonical_host": None,
                "website_hosts_json": None,
                "favicon_url": None,
                "favicon_source": None,
                "favicon_candidates_json": None,
                "ga4_property": None,
                "search_console_json": None,
                "se_ranking_project_id": None,
                "monday_board_id": None,
                "reporting_template": None,
                    "source_paths_json": None,
                "status": "active",
            },
        )
        profile = client_profile_fields(sidecar)
        entry["client_name"] = sidecar.get("brand_display_name") or entry.get("client_name") or slug
        entry["abn"] = profile["abn"] or entry.get("abn")
        entry["primary_contact_name"] = profile["primary_contact_name"] or entry.get("primary_contact_name")
        entry["primary_contact_role"] = profile["primary_contact_role"] or entry.get("primary_contact_role")
        entry["canonical_host"] = sidecar.get("domain") or nested_get(sidecar, ("website", "canonical_host")) or entry.get("canonical_host")
        entry["ga4_property"] = str(sidecar.get("ga4_property") or entry.get("ga4_property") or "") or None
        entry["se_ranking_project_id"] = str(nested_get(sidecar, ("se_ranking", "project_id")) or entry.get("se_ranking_project_id") or "") or None
        entry["monday_board_id"] = str(nested_get(sidecar, ("monday", "board_id")) or entry.get("monday_board_id") or "") or None
        if not entry.get("source_paths_json"):
            entry["source_paths_json"] = {}
        entry["source_paths_json"]["seo_sidecar"] = str(sidecar_path)

    for entry in registry.values():
        configured_candidates = favicon_overrides.get(str(entry.get("client_slug") or ""))
        favicon_candidates = [*configured_candidates, *favicon_candidates_for_host(entry.get("canonical_host"))] if configured_candidates else favicon_candidates_for_host(entry.get("canonical_host"))
        favicon_candidates = list(dict.fromkeys(favicon_candidates))
        if favicon_candidates:
            entry["favicon_url"] = favicon_candidates[0]
            entry["favicon_source"] = "client_favicons_config" if configured_candidates else "canonical_host_candidates"
            entry["favicon_candidates_json"] = json_dump(favicon_candidates)
        entry["source_paths_json"] = json_dump(entry.get("source_paths_json"))
    return sorted(registry.values(), key=lambda item: item["client_slug"])


def load_client_favicon_overrides(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        payload = load_json(path)
    except json.JSONDecodeError:
        return {}
    clients = payload.get("clients") if isinstance(payload, dict) else {}
    if not isinstance(clients, dict):
        return {}
    output: dict[str, list[str]] = {}
    for slug, candidates in clients.items():
        if not isinstance(candidates, list):
            continue
        safe_candidates = [
            candidate.strip()
            for candidate in candidates
            if isinstance(candidate, str) and candidate.strip().startswith("https://")
        ]
        if safe_candidates:
            output[slugify(slug)] = list(dict.fromkeys(safe_candidates))
    return output


def favicon_url_for_host(value: Any) -> str | None:
    candidates = favicon_candidates_for_host(value)
    return candidates[0] if candidates else None


def favicon_candidates_for_host(value: Any) -> list[str]:
    host = str(value or "").strip().lower()
    if not host:
        return []
    host = host.removeprefix("https://").removeprefix("http://").split("/", 1)[0]
    host = host.split("?", 1)[0].strip()
    if not host or "." not in host or any(character.isspace() for character in host):
        return []
    apex_host = host.removeprefix("www.")
    candidates = [
        f"https://{host}/favicon.ico",
        f"https://{host}/apple-touch-icon.png",
        f"https://{host}/apple-touch-icon-precomposed.png",
        f"https://icons.duckduckgo.com/ip3/{host}.ico",
        f"https://www.google.com/s2/favicons?domain={host}&sz=128",
    ]
    if apex_host != host:
        candidates.extend(
            [
                f"https://{apex_host}/favicon.ico",
                f"https://icons.duckduckgo.com/ip3/{apex_host}.ico",
                f"https://www.google.com/s2/favicons?domain={apex_host}&sz=128",
            ]
        )
    return list(dict.fromkeys(candidates))


def safe_profile_string(value: Any, *, max_length: int = 120) -> str | None:
    if value in (None, "", []):
        return None
    text = str(value).strip()
    if not text or len(text) > max_length:
        return None
    if "@" in text or "://" in text:
        return None
    return text


def client_profile_fields(sidecar: dict[str, Any]) -> dict[str, str | None]:
    contact = sidecar.get("primary_contact") if isinstance(sidecar.get("primary_contact"), dict) else {}
    contact = contact or (sidecar.get("contact") if isinstance(sidecar.get("contact"), dict) else {})
    business = sidecar.get("business") if isinstance(sidecar.get("business"), dict) else {}
    profile = sidecar.get("profile") if isinstance(sidecar.get("profile"), dict) else {}
    account = sidecar.get("account") if isinstance(sidecar.get("account"), dict) else {}
    return {
        "abn": safe_profile_string(
            sidecar.get("abn")
            or business.get("abn")
            or profile.get("abn")
            or account.get("abn"),
            max_length=40,
        ),
        "primary_contact_name": safe_profile_string(
            sidecar.get("primary_contact_name")
            or contact.get("name")
            or account.get("primary_contact_name")
            or profile.get("primary_contact_name")
        ),
        "primary_contact_role": safe_profile_string(
            sidecar.get("primary_contact_role")
            or contact.get("role")
            or contact.get("title")
            or account.get("primary_contact_role")
            or profile.get("primary_contact_role")
        ),
    }


def load_reporting_clients(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = load_json(path)
    clients = payload.get("clients") if isinstance(payload, dict) else payload
    if isinstance(clients, dict):
        return list(clients.values())
    if isinstance(clients, list):
        return [client for client in clients if isinstance(client, dict)]
    return []


def nested_get(payload: dict[str, Any], keys: Iterable[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_timeline_events(clients_dir: Path, run_id: str, ingested_at: str) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(clients_dir.glob("*-timeline.md")):
        client_slug = path.name.removesuffix("-timeline.md")
        for index, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            line = raw_line.strip()
            if not line.startswith("|") or line.startswith("|---") or " Date " in line:
                continue
            cells = split_markdown_table_row(line, expected_cells=9)
            if len(cells) < 2:
                continue
            event_date = parse_date(cells[0])
            if not event_date:
                continue
            rows.append(
                {
                    "ingested_at": ingested_at,
                    "run_id": run_id,
                    "client_slug": client_slug,
                    "event_date": event_date,
                    "task": cells[1] if len(cells) > 1 else None,
                    "request_source": cells[2] if len(cells) > 2 else None,
                    "evidence_checked": cells[3] if len(cells) > 3 else None,
                    "outputs": cells[4] if len(cells) > 4 else None,
                    "decisions": cells[5] if len(cells) > 5 else None,
                    "caveats": cells[6] if len(cells) > 6 else None,
                    "next_action": cells[7] if len(cells) > 7 else None,
                    "proof_summary": cells[8] if len(cells) > 8 else None,
                    "source_path": str(path),
                    "row_index": index,
                }
            )
    return rows


def split_markdown_table_row(line: str, *, expected_cells: int) -> list[str]:
    stripped = line.strip().strip("|")
    parts = [part.strip() for part in stripped.split("|")]
    if len(parts) <= expected_cells:
        return parts
    head = parts[: expected_cells - 1]
    tail = " | ".join(parts[expected_cells - 1 :]).strip()
    return [*head, tail]


def parse_monthly_report_snapshots(paths: SourcePaths, run_id: str, ingested_at: str) -> list[dict[str, Any]]:
    rows = []
    report_root = paths.reporting_content / "reports"
    for path in sorted(report_root.glob("*/*.json")):
        try:
            payload = load_json(path)
        except json.JSONDecodeError:
            continue
        client = payload.get("client") or {}
        period = client.get("period") or path.parent.name
        if isinstance(period, dict):
            period_id = period.get("id") or path.parent.name
            report_month = parse_date(period.get("start") or period_id)
        else:
            period_id = period
            report_month = parse_date(period_id)
        client_slug = client.get("slug") or slugify(client.get("name") or path.stem)
        caveats = {
            "ga4": nested_get(payload, ("ga4", "caveats")),
            "searchConsole": nested_get(payload, ("searchConsole", "caveats")),
            "seRanking": nested_get(payload, ("seRanking", "caveats")),
            "aiReferrals": nested_get(payload, ("aiReferrals", "caveats")),
        }
        rows.append(
            {
                "ingested_at": ingested_at,
                "run_id": run_id,
                "period_id": str(period_id),
                "report_month": report_month,
                "client_slug": client_slug,
                "client_name": client.get("name") or client_slug,
                "share_id": client.get("shareId") or None,
                "report_path": str(path),
                "generated_at": parse_timestamp(client.get("generatedAt")),
                "schema_version": int(payload["schemaVersion"]) if payload.get("schemaVersion") is not None else None,
                "template": client.get("template") or None,
                "headline_metrics_json": json_dump(extract_headline_metrics(payload)),
                "commentary_json": json_dump(payload.get("commentary")),
                "source_caveats_json": json_dump(caveats),
                "raw_report_json": json_dump(payload),
            }
        )
    return rows


def extract_headline_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ga4_overview": nested_get(payload, ("ga4", "overview")),
        "ga4_current": nested_get(payload, ("ga4", "current")),
        "search_console_summary": nested_get(payload, ("searchConsole", "summary")),
        "search_console_current": nested_get(payload, ("searchConsole", "current")),
        "se_ranking_visibility": nested_get(payload, ("seRanking", "visibility")),
        "se_ranking_average_position": nested_get(payload, ("seRanking", "averagePosition")),
        "ai_referral_scorecards": nested_get(payload, ("aiReferrals", "scorecards")),
    }


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def join_values(value: Any) -> str | None:
    if value in (None, "", []):
        return None
    if isinstance(value, list):
        return " | ".join(str(item) for item in value if item not in (None, ""))
    return str(value)


def extract_monthly_performance_summary(payload: dict[str, Any]) -> dict[str, float | None]:
    ga4_totals = nested_get(payload, ("ga4", "current", "totals")) or nested_get(payload, ("ga4", "overview", "scorecards")) or {}
    gsc_totals = nested_get(payload, ("searchConsole", "current", "totals")) or nested_get(payload, ("searchConsole", "totals")) or {}
    se_visibility = nested_get(payload, ("seRanking", "visibility")) or {}
    se_top10 = nested_get(payload, ("seRanking", "top10Share")) or {}
    se_average = nested_get(payload, ("seRanking", "averagePosition")) or {}
    ai_scorecards = nested_get(payload, ("aiReferrals", "scorecards")) or {}
    return {
        "organic_sessions": as_float(ga4_totals.get("sessions") or ga4_totals.get("organicSessions")),
        "organic_users": as_float(ga4_totals.get("users")),
        "engaged_sessions": as_float(ga4_totals.get("engagedSessions") or ga4_totals.get("engaged_sessions")),
        "organic_purchases": as_float(ga4_totals.get("purchases") or ga4_totals.get("organicTransactions")),
        "organic_revenue": as_float(ga4_totals.get("revenue") or ga4_totals.get("organicRevenue")),
        "organic_conversion_rate": as_float(
            ga4_totals.get("conversion_rate") or ga4_totals.get("purchaseRate") or ga4_totals.get("purchase_rate")
        ),
        "organic_aov": as_float(ga4_totals.get("aov") or ga4_totals.get("averageOrderValue")),
        "gsc_clicks": as_float(gsc_totals.get("clicks")),
        "gsc_impressions": as_float(gsc_totals.get("impressions")),
        "gsc_ctr": as_float(gsc_totals.get("ctr")),
        "gsc_avg_position": as_float(gsc_totals.get("position")),
        "se_visibility_start": as_float(se_visibility.get("start")),
        "se_visibility_end": as_float(se_visibility.get("end")),
        "se_visibility_delta": as_float(se_visibility.get("delta")),
        "se_top10_start": as_float(se_top10.get("start")),
        "se_top10_end": as_float(se_top10.get("end")),
        "se_top10_delta": as_float(se_top10.get("delta")),
        "se_avg_position_start": as_float(se_average.get("start")),
        "se_avg_position_end": as_float(se_average.get("end")),
        "se_avg_position_delta": as_float(se_average.get("delta")),
        "ai_sessions": as_float(ai_scorecards.get("sessions")),
        "ai_users": as_float(ai_scorecards.get("users")),
        "ai_revenue": as_float(ai_scorecards.get("revenue")),
        "ai_blog_sessions": as_float(ai_scorecards.get("blogSessions")),
    }


def extract_monthly_report_narrative(payload: dict[str, Any]) -> dict[str, str | None]:
    commentary = payload.get("commentary") or {}
    return {
        "summary": commentary.get("summary"),
        "completed_work": join_values(commentary.get("completedWork")),
        "next_focus": join_values(commentary.get("nextFocus")),
        "caveats": join_values(commentary.get("caveats")),
    }


def extract_monthly_reporting_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    has_ga4 = bool(nested_get(payload, ("ga4", "current", "totals")) or nested_get(payload, ("ga4", "overview", "scorecards")))
    has_search_console = bool(nested_get(payload, ("searchConsole", "current", "totals")) or nested_get(payload, ("searchConsole", "totals")))
    has_se_ranking = bool(nested_get(payload, ("seRanking", "visibility")) or nested_get(payload, ("seRanking", "averagePosition")))
    has_ai_referrals = bool(nested_get(payload, ("aiReferrals", "scorecards")))
    if not has_ga4 or not has_search_console:
        coverage_status = "missing_core_metrics"
    elif has_ga4 and has_search_console and has_se_ranking and has_ai_referrals:
        coverage_status = "ready"
    else:
        coverage_status = "partial"
    return {
        "has_ga4": has_ga4,
        "has_search_console": has_search_console,
        "has_se_ranking": has_se_ranking,
        "has_ai_referrals": has_ai_referrals,
        "ga4_caveats": join_values(nested_get(payload, ("ga4", "caveats"))),
        "search_console_caveats": join_values(nested_get(payload, ("searchConsole", "caveats"))),
        "se_ranking_caveats": join_values(nested_get(payload, ("seRanking", "caveats"))),
        "ai_referrals_caveats": join_values(nested_get(payload, ("aiReferrals", "caveats"))),
        "coverage_status": coverage_status,
    }


def make_staging_rows(
    table_name: str,
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    ingested_at: str,
    snapshot_date: str,
) -> list[dict[str, Any]]:
    staging_rows = []
    source_id = table_name.replace(".", "_")
    for row in rows:
        record_id = stable_record_id(table_name, row)
        if has_secret_like_text(row):
            continue
        staging_rows.append(
            {
                "run_id": run_id,
                "source_id": source_id,
                "source_path": str(row.get("source_path") or row.get("report_path") or table_name),
                "record_type": table_name,
                "record_id": record_id,
                "snapshot_date": row.get("snapshot_date") or snapshot_date,
                "ingested_at": ingested_at,
                "payload_json": json_dump(row),
            }
        )
    return staging_rows


def stable_record_id(table_name: str, row: dict[str, Any]) -> str:
    candidates = [
        row.get("item_id"),
        row.get("board_id"),
        row.get("client_slug"),
        row.get("share_id"),
        row.get("source_path"),
    ]
    basis = "|".join(str(item) for item in candidates if item)
    if not basis:
        basis = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(f"{table_name}|{basis}".encode("utf-8")).hexdigest()[:32]


def client_comms_attention_sql(project: str, memory: str, reporting: str) -> str:
    return f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_comms_attention`
PARTITION BY week_start
CLUSTER BY client_slug, signal_type AS
WITH recent AS (
  SELECT
    *,
    COALESCE(
      thread_ref_hash,
      JSON_VALUE(source_ref_hashes_json, '$[0]'),
      TO_HEX(SHA256(CONCAT(client_slug, '|', summary)))
    ) AS effective_thread_ref_hash,
    COALESCE(
      thread_status,
      CASE
        WHEN waiting_on_us OR needs_reply THEN 'waiting_on_us'
        WHEN waiting_on_client THEN 'waiting_on_client'
        WHEN stale_followup OR blocked OR category = 'access_blocker' THEN 'open'
        ELSE 'fyi'
      END
    ) AS effective_thread_status,
    COALESCE(latest_event_at, TIMESTAMP(week_end), created_at) AS effective_latest_event_at
  FROM `{project}.{memory}.client_comms_weekly_summaries`
  WHERE week_start >= DATE_SUB(CURRENT_DATE('Australia/Melbourne'), INTERVAL 13 MONTH)
),
latest_thread_state AS (
  SELECT *
  FROM recent
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY client_slug, effective_thread_ref_hash
    ORDER BY effective_latest_event_at DESC, created_at DESC, week_end DESC
  ) = 1
),
active AS (
  SELECT *
  FROM latest_thread_state
  WHERE effective_thread_status NOT IN ('resolved', 'fyi')
),
signals AS (
  SELECT
    week_start,
    week_end,
    client_slug,
    client_name,
    effective_thread_ref_hash AS thread_ref_hash,
    effective_thread_status AS thread_status,
    'waiting_on_us' AS signal_type,
    CASE WHEN urgency = 'high' THEN 'high' WHEN urgency = 'medium' THEN 'medium' ELSE 'low' END AS severity,
    channel,
    category,
    summary,
    recommended_action,
    owner_hint,
    due_hint,
    source_event_count,
    confidence,
    'agency_memory.client_comms_weekly_summaries' AS evidence_table,
    run_id,
    created_at,
    effective_latest_event_at AS latest_event_at
  FROM active
  WHERE effective_thread_status = 'waiting_on_us' OR waiting_on_us OR needs_reply
  UNION ALL
  SELECT
    week_start,
    week_end,
    client_slug,
    client_name,
    effective_thread_ref_hash AS thread_ref_hash,
    effective_thread_status AS thread_status,
    'waiting_on_client' AS signal_type,
    CASE WHEN urgency = 'high' THEN 'high' WHEN urgency = 'medium' THEN 'medium' ELSE 'low' END AS severity,
    channel,
    category,
    summary,
    recommended_action,
    owner_hint,
    due_hint,
    source_event_count,
    confidence,
    'agency_memory.client_comms_weekly_summaries' AS evidence_table,
    run_id,
    created_at,
    effective_latest_event_at AS latest_event_at
  FROM active
  WHERE effective_thread_status = 'waiting_on_client' OR waiting_on_client
  UNION ALL
  SELECT
    week_start,
    week_end,
    client_slug,
    client_name,
    effective_thread_ref_hash AS thread_ref_hash,
    effective_thread_status AS thread_status,
    'stale_followup' AS signal_type,
    CASE WHEN urgency IN ('high', 'medium') THEN urgency ELSE 'medium' END AS severity,
    channel,
    category,
    summary,
    recommended_action,
    owner_hint,
    due_hint,
    source_event_count,
    confidence,
    'agency_memory.client_comms_weekly_summaries' AS evidence_table,
    run_id,
    created_at,
    effective_latest_event_at AS latest_event_at
  FROM active
  WHERE stale_followup
  UNION ALL
  SELECT
    week_start,
    week_end,
    client_slug,
    client_name,
    effective_thread_ref_hash AS thread_ref_hash,
    effective_thread_status AS thread_status,
    'client_blocker' AS signal_type,
    CASE WHEN urgency = 'low' OR urgency = 'none' THEN 'medium' ELSE urgency END AS severity,
    channel,
    category,
    summary,
    recommended_action,
    owner_hint,
    due_hint,
    source_event_count,
    confidence,
    'agency_memory.client_comms_weekly_summaries' AS evidence_table,
    run_id,
    created_at,
    effective_latest_event_at AS latest_event_at
  FROM active
  WHERE blocked OR category = 'access_blocker'
)
SELECT *
FROM signals
"""


def client_comms_history_sql(project: str, memory: str, reporting: str) -> str:
    return f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_comms_history`
PARTITION BY week_start
CLUSTER BY client_slug, thread_status AS
SELECT
  week_start,
  week_end,
  client_slug,
  client_name,
  COALESCE(
    thread_ref_hash,
    JSON_VALUE(source_ref_hashes_json, '$[0]'),
    TO_HEX(SHA256(CONCAT(client_slug, '|', summary)))
  ) AS thread_ref_hash,
  COALESCE(
    thread_status,
    CASE
      WHEN waiting_on_us OR needs_reply THEN 'waiting_on_us'
      WHEN waiting_on_client THEN 'waiting_on_client'
      WHEN stale_followup OR blocked OR category = 'access_blocker' THEN 'open'
      ELSE 'fyi'
    END
  ) AS thread_status,
  COALESCE(latest_event_at, TIMESTAMP(week_end), created_at) AS latest_event_at,
  resolved_at,
  channel,
  category,
  summary,
  recommended_action,
  owner_hint,
  due_hint,
  needs_reply,
  blocked,
  waiting_on_client,
  waiting_on_us,
  stale_followup,
  urgency,
  sentiment,
  resolution_summary,
  source_event_count,
  confidence,
  run_id,
  created_at
FROM `{project}.{memory}.client_comms_weekly_summaries`
WHERE week_start >= DATE_SUB(CURRENT_DATE('Australia/Melbourne'), INTERVAL 13 MONTH)
"""


def build_comms_reporting_marts(runner: CappedBigQueryRunner, config: BigQueryCostConfig) -> dict[str, str]:
    queries = {
        "client_comms_attention": client_comms_attention_sql(config.project_id, config.memory_dataset, config.reporting_dataset),
        "client_comms_history": client_comms_history_sql(config.project_id, config.memory_dataset, config.reporting_dataset),
    }
    statuses = {}
    for mart_name, sql in queries.items():
        result, _ = runner.run_query(sql, purpose=f"comms-memory: build {mart_name}")
        statuses[mart_name] = result.status
    return statuses


def client_roadmap_current_sql(project: str, memory: str, reporting: str) -> str:
    return f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_roadmap_current`
PARTITION BY planned_month
CLUSTER BY client_slug, delivery_status AS
WITH latest_items AS (
  SELECT *
  FROM `{project}.{memory}.client_roadmap_items`
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY roadmap_item_id
    ORDER BY ingested_at DESC, run_id DESC
  ) = 1
),
delivery_evidence AS (
  SELECT
    client_slug,
    event_date,
    title,
    source_table,
    source_id,
    REGEXP_REPLACE(LOWER(IFNULL(title, '')), r'[^a-z0-9]+', ' ') AS normalized_title
  FROM `{project}.{reporting}.client_delivery_timeline`
  WHERE event_type IN ('task_done', 'timeline')
),
matched AS (
  SELECT
    r.roadmap_item_id,
    d.source_table,
    d.source_id,
    d.title,
    d.event_date
  FROM latest_items AS r
  JOIN delivery_evidence AS d
    ON r.client_slug = d.client_slug
   AND d.event_date >= r.planned_month
   AND d.event_date < DATE_ADD(DATE_ADD(r.planned_month, INTERVAL 1 MONTH), INTERVAL 14 DAY)
   AND LENGTH(d.normalized_title) >= 6
   AND (
     STRPOS(d.normalized_title, REGEXP_REPLACE(LOWER(r.item_title), r'[^a-z0-9]+', ' ')) > 0
     OR STRPOS(REGEXP_REPLACE(LOWER(r.item_title), r'[^a-z0-9]+', ' '), d.normalized_title) > 0
   )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY r.roadmap_item_id
    ORDER BY d.event_date DESC, d.source_id DESC
  ) = 1
)
SELECT
  r.planned_month,
  r.period_id,
  r.client_slug,
  r.client_name,
  r.roadmap_item_id,
  r.item_title,
  r.work_type,
  r.priority,
  r.planned_status,
  CASE
    WHEN r.planned_status = 'completed'
      OR (r.completion_evidence_type IS NOT NULL AND r.completion_evidence_type != 'none' AND r.completion_confidence >= 0.4)
      OR m.source_id IS NOT NULL THEN 'completed'
    WHEN r.planned_status IN ('deferred', 'cancelled', 'blocked') THEN r.planned_status
    WHEN r.due_date IS NOT NULL AND r.due_date < CURRENT_DATE('Australia/Melbourne') THEN 'overdue'
    WHEN r.planned_status = 'in_progress' THEN 'in_progress'
    ELSE 'planned'
  END AS delivery_status,
  r.owner_hint,
  r.due_date,
  r.target_url,
  r.keyword_theme,
  NULLIF(r.completion_evidence_type, 'none') AS completion_evidence_type,
  r.completion_evidence_ref,
  r.completion_summary,
  r.completion_confidence,
  m.source_table AS matched_evidence_table,
  m.source_id AS matched_evidence_id,
  m.title AS matched_evidence_title,
  m.event_date AS matched_evidence_date,
  r.source_ref_hash,
  r.run_id,
  r.ingested_at
FROM latest_items AS r
LEFT JOIN matched AS m
  ON r.roadmap_item_id = m.roadmap_item_id
"""


def client_roadmap_monthly_completion_sql(project: str, reporting: str) -> str:
    return f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_roadmap_monthly_completion`
PARTITION BY planned_month
CLUSTER BY client_slug, status_summary AS
SELECT
  planned_month,
  period_id,
  client_slug,
  client_name,
  COUNT(*) AS planned_items,
  COUNTIF(delivery_status = 'completed') AS completed_items,
  COUNTIF(delivery_status = 'in_progress') AS in_progress_items,
  COUNTIF(delivery_status = 'blocked') AS blocked_items,
  COUNTIF(delivery_status IN ('deferred', 'cancelled')) AS deferred_items,
  COUNTIF(delivery_status NOT IN ('completed', 'deferred', 'cancelled')) AS missing_evidence_items,
  COUNTIF(delivery_status = 'overdue') AS overdue_items,
  SAFE_DIVIDE(COUNTIF(delivery_status = 'completed'), COUNT(*)) AS completion_rate,
  COUNTIF(priority = 'high' AND delivery_status NOT IN ('completed', 'deferred', 'cancelled')) AS high_priority_open_items,
  CASE
    WHEN COUNT(*) = 0 THEN 'no_roadmap'
    WHEN COUNTIF(delivery_status NOT IN ('completed', 'deferred', 'cancelled')) = 0 THEN 'complete'
    WHEN COUNTIF(delivery_status = 'overdue') > 0 OR COUNTIF(delivery_status = 'blocked') > 0 THEN 'needs_attention'
    WHEN COUNTIF(priority = 'high' AND delivery_status NOT IN ('completed', 'deferred', 'cancelled')) > 0 THEN 'high_priority_open'
    ELSE 'in_progress'
  END AS status_summary
FROM `{project}.{reporting}.client_roadmap_current`
GROUP BY planned_month, period_id, client_slug, client_name
"""


def build_roadmap_reporting_marts(runner: CappedBigQueryRunner, config: BigQueryCostConfig) -> dict[str, str]:
    queries = {
        "client_roadmap_current": client_roadmap_current_sql(config.project_id, config.memory_dataset, config.reporting_dataset),
        "client_roadmap_monthly_completion": client_roadmap_monthly_completion_sql(config.project_id, config.reporting_dataset),
    }
    statuses = {}
    for mart_name, sql in queries.items():
        result, _ = runner.run_query(sql, purpose=f"roadmap-memory: build {mart_name}")
        statuses[mart_name] = result.status
    return statuses


def client_health_check_sql(project: str, memory: str, reporting: str) -> str:
    return f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_health_check`
PARTITION BY snapshot_date
CLUSTER BY client_slug, health_status AS
WITH latest_snapshot AS (
  SELECT MAX(snapshot_date) AS snapshot_date
  FROM `{project}.{memory}.client_health_assets`
),
latest_assets AS (
  SELECT a.*
  FROM `{project}.{memory}.client_health_assets` AS a
  JOIN latest_snapshot
    ON a.snapshot_date = latest_snapshot.snapshot_date
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY a.client_slug, a.asset_type, a.asset_label
    ORDER BY a.ingested_at DESC, a.run_id DESC
  ) = 1
),
clients AS (
  SELECT DISTINCT snapshot_date, client_slug, client_name
  FROM latest_assets
),
roadmap_clients AS (
  SELECT client_slug, COUNT(*) AS roadmap_item_count
  FROM `{project}.{memory}.client_roadmap_items`
  WHERE planned_month >= DATE_TRUNC(DATE_SUB(CURRENT_DATE('Australia/Melbourne'), INTERVAL 2 MONTH), MONTH)
  GROUP BY client_slug
),
latest_reports AS (
  SELECT client_slug, MAX(report_month) AS latest_report_month
  FROM `{project}.{memory}.monthly_report_snapshots`
  GROUP BY client_slug
),
assets_plus AS (
  SELECT
    snapshot_date,
    ingested_at,
    run_id,
    client_slug,
    client_name,
    asset_type,
    asset_label,
    presence_status,
    expected,
    criticality,
    source_system,
    source_path,
    source_ref,
    source_ref_hash,
    freshness_date,
    verification_level,
    verified_at,
    verification_method,
    notes
  FROM latest_assets
  UNION ALL
  SELECT
    c.snapshot_date,
    CURRENT_TIMESTAMP() AS ingested_at,
    'derived-roadmap-items' AS run_id,
    c.client_slug,
    c.client_name,
    'roadmap_items' AS asset_type,
    'Loaded roadmap items' AS asset_label,
    IF(IFNULL(r.roadmap_item_count, 0) > 0, 'present', 'missing') AS presence_status,
    TRUE AS expected,
    'medium' AS criticality,
    'bigquery' AS source_system,
    'agency_memory.client_roadmap_items' AS source_path,
    CAST(r.roadmap_item_count AS STRING) AS source_ref,
    TO_HEX(SHA256(CONCAT(c.client_slug, '|roadmap_items'))) AS source_ref_hash,
    CAST(NULL AS DATE) AS freshness_date,
    'warehouse_derived' AS verification_level,
    CURRENT_TIMESTAMP() AS verified_at,
    'client_roadmap_items_recent_row_count' AS verification_method,
    'Derived from loaded roadmap item rows.' AS notes
  FROM clients AS c
  LEFT JOIN roadmap_clients AS r
    ON c.client_slug = r.client_slug
),
asset_rollup AS (
  SELECT
    snapshot_date,
    client_slug,
    ANY_VALUE(client_name) AS client_name,
    COUNTIF(expected) AS expected_assets,
    COUNTIF(expected AND presence_status = 'present') AS present_assets,
    COUNTIF(expected AND presence_status != 'present') AS missing_required_assets,
    COUNTIF(NOT expected AND presence_status != 'present') AS missing_optional_assets,
    COUNTIF(presence_status = 'unknown') AS unknown_assets,
    COUNTIF(expected AND criticality = 'high' AND presence_status != 'present') AS critical_missing_assets,
    TO_JSON(ARRAY_AGG(IF(expected AND presence_status != 'present', asset_label, NULL) IGNORE NULLS ORDER BY asset_label)) AS missing_required_json,
    TO_JSON(ARRAY_AGG(IF(NOT expected AND presence_status != 'present', asset_label, NULL) IGNORE NULLS ORDER BY asset_label)) AS missing_optional_json,
    COUNTIF(asset_type = 'sidecar_json' AND presence_status = 'present') > 0 AS has_sidecar_json,
    COUNTIF(asset_type = 'client_brief' AND presence_status = 'present') > 0 AS has_client_brief,
    COUNTIF(asset_type = 'timeline' AND presence_status = 'present') > 0 AS has_timeline,
    COUNTIF(asset_type = 'writing_style' AND presence_status = 'present') > 0 AS has_writing_style,
    COUNTIF(asset_type = 'brand_writing_guide_doc' AND presence_status = 'present') > 0 AS has_brand_writing_guide_doc,
    COUNTIF(asset_type = 'drive_root' AND presence_status = 'present') > 0 AS has_drive_root,
    COUNTIF(asset_type = 'drive_root_verified' AND presence_status = 'present') > 0 AS has_drive_root_verified,
    COUNTIF(asset_type = 'drive_roadmap_folder' AND presence_status = 'present') > 0 AS has_roadmap_route,
    COUNTIF(asset_type = 'drive_roadmap_folder_verified' AND presence_status = 'present') > 0 AS has_roadmap_folder_verified,
    COUNTIF(asset_type = 'drive_roadmap_files' AND presence_status = 'present') > 0 AS has_roadmap_files,
    COUNTIF(asset_type = 'drive_roadmap_content' AND presence_status = 'present') > 0 AS has_roadmap_content_validated,
    COUNTIF(asset_type = 'drive_content_folder' AND presence_status = 'present') > 0 AS has_content_route,
    COUNTIF(asset_type = 'drive_content_folder_verified' AND presence_status = 'present') > 0 AS has_content_folder_verified,
    COUNTIF(asset_type = 'drive_reports_folder' AND presence_status = 'present') > 0 AS has_reports_route,
    COUNTIF(asset_type = 'drive_reports_folder_verified' AND presence_status = 'present') > 0 AS has_reports_folder_verified,
    COUNTIF(asset_type = 'monday_board' AND presence_status = 'present') > 0 AS has_monday_board,
    COUNTIF(asset_type = 'monday_board_snapshot' AND presence_status = 'present') > 0 AS has_monday_board_snapshot,
    COUNTIF(asset_type = 'reporting_config' AND presence_status = 'present') > 0 AS has_reporting_config,
    COUNTIF(asset_type = 'ga4_property' AND presence_status = 'present') > 0 AS has_ga4_property,
    COUNTIF(asset_type = 'ga4_access' AND presence_status = 'present') > 0 AS has_ga4_access,
    COUNTIF(asset_type = 'search_console' AND presence_status = 'present') > 0 AS has_search_console,
    COUNTIF(asset_type = 'search_console_access' AND presence_status = 'present') > 0 AS has_search_console_access,
    COUNTIF(asset_type = 'se_ranking' AND presence_status = 'present') > 0 AS has_se_ranking,
    COUNTIF(asset_type = 'se_ranking_access' AND presence_status = 'present') > 0 AS has_se_ranking_access,
    COUNTIF(asset_type = 'monthly_report_snapshot' AND presence_status = 'present') > 0 AS has_monthly_report_snapshot,
    COUNTIF(asset_type = 'roadmap_items' AND presence_status = 'present') > 0 AS has_roadmap_items
FROM assets_plus
GROUP BY snapshot_date, client_slug
)
SELECT
  r.snapshot_date,
  r.client_slug,
  r.client_name,
  r.expected_assets,
  r.present_assets,
  r.missing_required_assets,
  r.missing_optional_assets,
  r.unknown_assets,
  r.critical_missing_assets,
  SAFE_DIVIDE(r.present_assets, r.expected_assets) AS health_score,
  CASE
    WHEN r.critical_missing_assets > 0 THEN 'critical_missing'
    WHEN r.missing_required_assets > 0 THEN 'needs_attention'
    WHEN SAFE_DIVIDE(r.present_assets, r.expected_assets) = 1 THEN 'healthy'
    ELSE 'partial'
  END AS health_status,
  r.missing_required_json,
  r.missing_optional_json,
  r.has_sidecar_json,
  r.has_client_brief,
  r.has_timeline,
  r.has_writing_style,
  r.has_brand_writing_guide_doc,
  r.has_drive_root,
  r.has_drive_root_verified,
  r.has_roadmap_route,
  r.has_roadmap_folder_verified,
  r.has_roadmap_files,
  r.has_roadmap_content_validated,
  r.has_content_route,
  r.has_content_folder_verified,
  r.has_reports_route,
  r.has_reports_folder_verified,
  r.has_monday_board,
  r.has_monday_board_snapshot,
  r.has_reporting_config,
  r.has_ga4_property,
  r.has_ga4_access,
  r.has_search_console,
  r.has_search_console_access,
  r.has_se_ranking,
  r.has_se_ranking_access,
  r.has_monthly_report_snapshot,
  r.has_roadmap_items,
  latest_reports.latest_report_month
FROM asset_rollup AS r
LEFT JOIN latest_reports
  ON r.client_slug = latest_reports.client_slug
"""


def client_finance_health_sql(project: str, memory: str, reporting: str) -> str:
    return f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_finance_health`
PARTITION BY month_start
CLUSTER BY client_slug, finance_status AS
WITH base AS (
  SELECT
    f.period_id,
    f.month_start,
    f.client_slug,
    COALESCE(c.client_name, f.client_label, f.client_slug) AS client_name,
    f.client_label,
    f.billing_status,
    f.retainer_amount_aud,
    f.expense_amount_aud,
    f.net_amount_aud,
    f.is_billable,
    f.month_start <= DATE_TRUNC(CURRENT_DATE('Australia/Melbourne'), MONTH) AND f.is_billable AS is_due,
    f.billing_status = 'paid' AS is_paid,
    f.billing_status IN ('paid', 'issued') AS is_issued
  FROM `{project}.{memory}.client_finance_monthly` AS f
  LEFT JOIN `{project}.{memory}.client_registry` AS c
    ON f.client_slug = c.client_slug
),
client_rollup AS (
  SELECT
    client_slug,
    SUM(IF(is_due, retainer_amount_aud, 0)) AS due_amount_aud,
    SUM(IF(is_due AND is_paid, retainer_amount_aud, 0)) AS paid_due_amount_aud,
    SUM(IF(is_due AND is_issued, retainer_amount_aud, 0)) AS issued_due_amount_aud,
    SUM(IF(is_due AND billing_status = 'not_issued', retainer_amount_aud, 0)) AS not_issued_due_amount_aud,
    SUM(IF(is_billable, retainer_amount_aud, 0)) AS retainer_total_aud,
    SUM(IF(is_billable, expense_amount_aud, 0)) AS expense_total_aud,
    SUM(IF(is_billable, net_amount_aud, 0)) AS net_total_aud,
    COUNTIF(is_billable) AS billable_months,
    COUNTIF(is_due) AS due_months,
    COUNTIF(is_due AND billing_status = 'not_issued') AS not_issued_due_months
  FROM base
  GROUP BY client_slug
),
scored AS (
  SELECT
    b.*,
    r.due_amount_aud,
    r.paid_due_amount_aud,
    r.issued_due_amount_aud,
    r.not_issued_due_amount_aud,
    r.retainer_total_aud,
    r.expense_total_aud,
    r.net_total_aud,
    r.net_total_aud AS gross_margin_amount_aud,
    r.billable_months,
    r.due_months,
    r.not_issued_due_months,
    SAFE_DIVIDE(r.paid_due_amount_aud, NULLIF(r.due_amount_aud, 0)) AS collection_rate,
    SAFE_DIVIDE(r.issued_due_amount_aud, NULLIF(r.due_amount_aud, 0)) AS invoice_coverage_rate,
    SAFE_DIVIDE(r.expense_total_aud, NULLIF(r.retainer_total_aud, 0)) AS expense_ratio,
    SAFE_DIVIDE(r.net_total_aud, NULLIF(r.retainer_total_aud, 0)) AS gross_margin_rate
  FROM base AS b
  JOIN client_rollup AS r
    USING (client_slug)
),
with_score AS (
  SELECT
    *,
    CAST(ROUND(
      (IFNULL(collection_rate, 1) * 55)
      + (IFNULL(invoice_coverage_rate, 1) * 30)
      + ((1 - LEAST(IFNULL(expense_ratio, 0), 1)) * 15)
    ) AS INT64) AS finance_score
  FROM scored
)
SELECT
  *,
  CASE
    WHEN finance_score < 45 THEN 'critical'
    WHEN finance_score < 70 THEN 'needs_attention'
    WHEN finance_score < 85 THEN 'watch'
    ELSE 'healthy'
  END AS finance_status,
  'agency_memory.client_finance_monthly' AS source_table
FROM with_score
"""


def build_finance_reporting_mart(runner: CappedBigQueryRunner, config: BigQueryCostConfig) -> dict[str, str]:
    result, _ = runner.run_query(
        client_finance_health_sql(config.project_id, config.memory_dataset, config.reporting_dataset),
        purpose="agency-ops-mart: build client_finance_health",
    )
    return {"client_finance_health": result.status}


def build_reporting_marts(runner: CappedBigQueryRunner, config: BigQueryCostConfig) -> dict[str, str]:
    project = config.project_id
    memory = config.memory_dataset
    reporting = config.reporting_dataset
    monday_item_client_slug_sql = canonical_client_slug_sql("i.client_slug")
    queries = {
        "client_task_status": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_task_status`
PARTITION BY snapshot_date AS
WITH normalized_items AS (
  SELECT
    i.*,
    {monday_item_client_slug_sql} AS canonical_client_slug
  FROM `{project}.{memory}.monday_items` AS i
)
SELECT
  i.snapshot_date,
  i.canonical_client_slug AS client_slug,
  COALESCE(c.client_name, m.client_name, i.canonical_client_slug) AS client_name,
  CAST(i.board_id AS STRING) AS board_id,
  i.board_name,
  CAST(i.item_id AS STRING) AS item_id,
  i.item_name,
  i.status,
  i.normalized_status,
  i.owner,
  i.due_date,
  i.group_title,
  i.updated_at,
  i.normalized_status = 'Done' AS is_done,
  IFNULL(i.due_date < CURRENT_DATE('Australia/Melbourne') AND i.normalized_status != 'Done', FALSE) AS is_overdue
FROM normalized_items AS i
LEFT JOIN `{project}.{memory}.client_registry` AS c
  ON i.canonical_client_slug = c.client_slug
LEFT JOIN `{project}.{memory}.client_board_map` AS m
  ON i.board_id = m.client_board_id
WHERE i.is_subitem = FALSE
""",
        "client_delivery_timeline": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_delivery_timeline`
CLUSTER BY client_slug AS
SELECT
  t.client_slug,
  c.client_name,
  t.event_date,
  'timeline' AS event_type,
  t.task AS title,
  CAST(NULL AS STRING) AS status,
  'agency_memory.client_timeline_events' AS source_table,
  CONCAT(t.client_slug, ':', CAST(t.row_index AS STRING)) AS source_id
FROM `{project}.{memory}.client_timeline_events` AS t
LEFT JOIN `{project}.{memory}.client_registry` AS c
  ON t.client_slug = c.client_slug
UNION ALL
SELECT
  i.client_slug,
  COALESCE(c.client_name, i.client_slug) AS client_name,
  COALESCE(i.due_date, i.date_value, DATE(i.updated_at)) AS event_date,
  'task_done' AS event_type,
  i.item_name AS title,
  i.normalized_status AS status,
  'agency_memory.monday_items' AS source_table,
  CAST(i.item_id AS STRING) AS source_id
FROM `{project}.{memory}.monday_items` AS i
LEFT JOIN `{project}.{memory}.client_registry` AS c
  ON i.client_slug = c.client_slug
WHERE i.normalized_status = 'Done'
  AND COALESCE(i.due_date, i.date_value, DATE(i.updated_at)) IS NOT NULL
""",
        "client_month_performance": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_month_performance`
CLUSTER BY client_slug AS
SELECT
  period_id,
  report_month,
  client_slug,
  client_name,
  share_id,
  generated_at,
  headline_metrics_json,
  commentary_json,
  source_caveats_json
FROM `{project}.{memory}.monthly_report_snapshots`
""",
        "client_monthly_performance_summary": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_monthly_performance_summary`
CLUSTER BY client_slug AS
SELECT
  period_id,
  report_month,
  client_slug,
  client_name,
  share_id,
  generated_at,
  SAFE_CAST(headline_metrics_json.ga4_current.totals.sessions AS FLOAT64) AS organic_sessions,
  SAFE_CAST(headline_metrics_json.ga4_current.totals.users AS FLOAT64) AS organic_users,
  SAFE_CAST(headline_metrics_json.ga4_current.totals.engagedSessions AS FLOAT64) AS engaged_sessions,
  SAFE_CAST(headline_metrics_json.ga4_current.totals.purchases AS FLOAT64) AS organic_purchases,
  SAFE_CAST(headline_metrics_json.ga4_current.totals.revenue AS FLOAT64) AS organic_revenue,
  SAFE_CAST(
    COALESCE(
      headline_metrics_json.ga4_current.totals.conversion_rate,
      headline_metrics_json.ga4_current.totals.purchaseRate,
      headline_metrics_json.ga4_current.totals.purchase_rate
    ) AS FLOAT64
  ) AS organic_conversion_rate,
  SAFE_CAST(
    COALESCE(
      headline_metrics_json.ga4_current.totals.aov,
      headline_metrics_json.ga4_current.totals.averageOrderValue
    ) AS FLOAT64
  ) AS organic_aov,
  SAFE_CAST(raw_report_json.searchConsole.current.totals.clicks AS FLOAT64) AS gsc_clicks,
  SAFE_CAST(raw_report_json.searchConsole.current.totals.impressions AS FLOAT64) AS gsc_impressions,
  SAFE_CAST(raw_report_json.searchConsole.current.totals.ctr AS FLOAT64) AS gsc_ctr,
  SAFE_CAST(raw_report_json.searchConsole.current.totals.position AS FLOAT64) AS gsc_avg_position,
  SAFE_CAST(headline_metrics_json.se_ranking_visibility.start AS FLOAT64) AS se_visibility_start,
  SAFE_CAST(headline_metrics_json.se_ranking_visibility.`end` AS FLOAT64) AS se_visibility_end,
  SAFE_CAST(headline_metrics_json.se_ranking_visibility.delta AS FLOAT64) AS se_visibility_delta,
  SAFE_CAST(raw_report_json.seRanking.top10Share.start AS FLOAT64) AS se_top10_start,
  SAFE_CAST(raw_report_json.seRanking.top10Share.`end` AS FLOAT64) AS se_top10_end,
  SAFE_CAST(raw_report_json.seRanking.top10Share.delta AS FLOAT64) AS se_top10_delta,
  SAFE_CAST(headline_metrics_json.se_ranking_average_position.start AS FLOAT64) AS se_avg_position_start,
  SAFE_CAST(headline_metrics_json.se_ranking_average_position.`end` AS FLOAT64) AS se_avg_position_end,
  SAFE_CAST(headline_metrics_json.se_ranking_average_position.delta AS FLOAT64) AS se_avg_position_delta,
  SAFE_CAST(headline_metrics_json.ai_referral_scorecards.sessions AS FLOAT64) AS ai_sessions,
  SAFE_CAST(headline_metrics_json.ai_referral_scorecards.users AS FLOAT64) AS ai_users,
  SAFE_CAST(headline_metrics_json.ai_referral_scorecards.revenue AS FLOAT64) AS ai_revenue,
  SAFE_CAST(headline_metrics_json.ai_referral_scorecards.blogSessions AS FLOAT64) AS ai_blog_sessions
FROM `{project}.{memory}.monthly_report_snapshots`
""",
        "client_monthly_report_narrative": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_monthly_report_narrative`
CLUSTER BY client_slug AS
SELECT
  period_id,
  report_month,
  client_slug,
  client_name,
  share_id,
  generated_at,
  commentary_json.summary AS summary,
  ARRAY_TO_STRING(commentary_json.completedWork, ' | ') AS completed_work,
  ARRAY_TO_STRING(commentary_json.nextFocus, ' | ') AS next_focus,
  ARRAY_TO_STRING(commentary_json.caveats, ' | ') AS caveats
FROM `{project}.{memory}.monthly_report_snapshots`
""",
        "client_monthly_reporting_coverage": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_monthly_reporting_coverage`
CLUSTER BY client_slug AS
WITH coverage AS (
  SELECT
    period_id,
    report_month,
    client_slug,
    client_name,
    share_id,
    generated_at,
    headline_metrics_json.ga4_current.totals.sessions IS NOT NULL
      OR headline_metrics_json.ga4_overview.scorecards.organicSessions IS NOT NULL AS has_ga4,
    raw_report_json.searchConsole.current.totals.clicks IS NOT NULL
      OR raw_report_json.searchConsole.totals.clicks IS NOT NULL AS has_search_console,
    headline_metrics_json.se_ranking_visibility.start IS NOT NULL
      OR headline_metrics_json.se_ranking_average_position.start IS NOT NULL AS has_se_ranking,
    headline_metrics_json.ai_referral_scorecards.sessions IS NOT NULL
      OR headline_metrics_json.ai_referral_scorecards.revenue IS NOT NULL AS has_ai_referrals,
    ARRAY_TO_STRING(source_caveats_json.ga4, ' | ') AS ga4_caveats,
    ARRAY_TO_STRING(source_caveats_json.searchConsole, ' | ') AS search_console_caveats,
    ARRAY_TO_STRING(source_caveats_json.seRanking, ' | ') AS se_ranking_caveats,
    ARRAY_TO_STRING(source_caveats_json.aiReferrals, ' | ') AS ai_referrals_caveats
  FROM `{project}.{memory}.monthly_report_snapshots`
)
SELECT
  *,
  CASE
    WHEN NOT has_ga4 OR NOT has_search_console THEN 'missing_core_metrics'
    WHEN has_ga4 AND has_search_console AND has_se_ranking AND has_ai_referrals THEN 'ready'
    ELSE 'partial'
  END AS coverage_status
FROM coverage
""",
        "client_monthly_performance_history": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_monthly_performance_history`
PARTITION BY month_start
CLUSTER BY client_slug AS
SELECT
  period_id,
  month_start,
  month_end,
  client_slug,
  client_name,
  ga4_status,
  gsc_status,
  se_ranking_status,
  organic_sessions,
  organic_users,
  engaged_sessions,
  organic_purchases,
  organic_revenue,
  organic_conversion_rate,
  organic_aov,
  ai_sessions,
  ai_users,
  ai_revenue,
  ai_blog_sessions,
  gsc_clicks,
  gsc_impressions,
  gsc_ctr,
  gsc_avg_position,
  se_visibility_start,
  se_visibility_end,
  se_visibility_delta,
  se_top10_start,
  se_top10_end,
  se_top10_delta,
  se_avg_position_start,
  se_avg_position_end,
  se_avg_position_delta
FROM `{project}.{memory}.client_monthly_api_snapshots`
""",
        "client_monthly_comparison": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_monthly_comparison`
PARTITION BY month_start
CLUSTER BY client_slug AS
WITH base AS (
  SELECT
    *,
    LAG(organic_revenue) OVER client_month AS prev_organic_revenue,
    LAG(organic_revenue, 12) OVER client_month AS yoy_organic_revenue,
    LAG(organic_sessions) OVER client_month AS prev_organic_sessions,
    LAG(organic_sessions, 12) OVER client_month AS yoy_organic_sessions,
    LAG(gsc_clicks) OVER client_month AS prev_gsc_clicks,
    LAG(gsc_clicks, 12) OVER client_month AS yoy_gsc_clicks,
    LAG(se_visibility_end) OVER client_month AS prev_se_visibility_end,
    LAG(se_visibility_end, 12) OVER client_month AS yoy_se_visibility_end,
    LAG(ai_sessions) OVER client_month AS prev_ai_sessions,
    LAG(ai_sessions, 12) OVER client_month AS yoy_ai_sessions
  FROM `{project}.{reporting}.client_monthly_performance_history`
  WINDOW client_month AS (PARTITION BY client_slug ORDER BY month_start)
)
SELECT
  period_id,
  month_start,
  client_slug,
  client_name,
  organic_revenue,
  organic_revenue - prev_organic_revenue AS organic_revenue_mom_delta,
  SAFE_DIVIDE(organic_revenue - prev_organic_revenue, NULLIF(prev_organic_revenue, 0)) AS organic_revenue_mom_pct,
  organic_revenue - yoy_organic_revenue AS organic_revenue_yoy_delta,
  SAFE_DIVIDE(organic_revenue - yoy_organic_revenue, NULLIF(yoy_organic_revenue, 0)) AS organic_revenue_yoy_pct,
  organic_sessions,
  organic_sessions - prev_organic_sessions AS organic_sessions_mom_delta,
  SAFE_DIVIDE(organic_sessions - prev_organic_sessions, NULLIF(prev_organic_sessions, 0)) AS organic_sessions_mom_pct,
  organic_sessions - yoy_organic_sessions AS organic_sessions_yoy_delta,
  SAFE_DIVIDE(organic_sessions - yoy_organic_sessions, NULLIF(yoy_organic_sessions, 0)) AS organic_sessions_yoy_pct,
  gsc_clicks,
  gsc_clicks - prev_gsc_clicks AS gsc_clicks_mom_delta,
  SAFE_DIVIDE(gsc_clicks - prev_gsc_clicks, NULLIF(prev_gsc_clicks, 0)) AS gsc_clicks_mom_pct,
  gsc_clicks - yoy_gsc_clicks AS gsc_clicks_yoy_delta,
  SAFE_DIVIDE(gsc_clicks - yoy_gsc_clicks, NULLIF(yoy_gsc_clicks, 0)) AS gsc_clicks_yoy_pct,
  se_visibility_end,
  se_visibility_end - prev_se_visibility_end AS se_visibility_mom_delta,
  se_visibility_end - yoy_se_visibility_end AS se_visibility_yoy_delta,
  ai_sessions,
  ai_sessions - prev_ai_sessions AS ai_sessions_mom_delta,
  ai_sessions - yoy_ai_sessions AS ai_sessions_yoy_delta,
  CASE
    WHEN ga4_status = 'succeeded' AND gsc_status = 'succeeded' AND se_ranking_status = 'succeeded' THEN 'complete'
    WHEN ga4_status = 'succeeded' OR gsc_status = 'succeeded' OR se_ranking_status = 'succeeded' THEN 'partial'
    ELSE 'missing'
  END AS source_health
FROM base
""",
        "client_trailing_performance": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_trailing_performance`
PARTITION BY month_start
CLUSTER BY client_slug AS
SELECT
  period_id,
  month_start,
  client_slug,
  client_name,
  SUM(organic_revenue) OVER t3 AS organic_revenue_t3,
  SUM(organic_revenue) OVER t6 AS organic_revenue_t6,
  SUM(organic_revenue) OVER t12 AS organic_revenue_t12,
  SUM(organic_sessions) OVER t3 AS organic_sessions_t3,
  SUM(organic_sessions) OVER t6 AS organic_sessions_t6,
  SUM(organic_sessions) OVER t12 AS organic_sessions_t12,
  SUM(gsc_clicks) OVER t3 AS gsc_clicks_t3,
  SUM(gsc_clicks) OVER t6 AS gsc_clicks_t6,
  SUM(gsc_clicks) OVER t12 AS gsc_clicks_t12,
  SUM(ai_sessions) OVER t3 AS ai_sessions_t3,
  SUM(ai_sessions) OVER t6 AS ai_sessions_t6,
  SUM(ai_sessions) OVER t12 AS ai_sessions_t12,
  se_visibility_end AS latest_se_visibility,
  COUNT(*) OVER t12 AS months_available
FROM `{project}.{reporting}.client_monthly_performance_history`
WINDOW
  t3 AS (PARTITION BY client_slug ORDER BY month_start ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
  t6 AS (PARTITION BY client_slug ORDER BY month_start ROWS BETWEEN 5 PRECEDING AND CURRENT ROW),
  t12 AS (PARTITION BY client_slug ORDER BY month_start ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
""",
        "client_benchmark_summary": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_benchmark_summary`
PARTITION BY month_start
CLUSTER BY client_slug AS
WITH latest AS (
  SELECT MAX(month_start) AS month_start
  FROM `{project}.{reporting}.client_monthly_comparison`
),
base AS (
  SELECT c.*
  FROM `{project}.{reporting}.client_monthly_comparison` AS c
  JOIN latest
    ON c.month_start = latest.month_start
)
SELECT
  period_id,
  month_start,
  client_slug,
  client_name,
  organic_revenue,
  organic_revenue_yoy_pct,
  organic_sessions,
  gsc_clicks,
  se_visibility_end,
  ai_sessions,
  RANK() OVER (ORDER BY organic_revenue DESC NULLS LAST) AS organic_revenue_rank,
  RANK() OVER (ORDER BY organic_revenue_yoy_pct DESC NULLS LAST) AS organic_revenue_yoy_rank,
  RANK() OVER (ORDER BY organic_sessions DESC NULLS LAST) AS organic_sessions_rank,
  RANK() OVER (ORDER BY gsc_clicks DESC NULLS LAST) AS gsc_clicks_rank,
  RANK() OVER (ORDER BY se_visibility_end DESC NULLS LAST) AS se_visibility_rank,
  CASE
    WHEN source_health != 'complete' THEN 'needs_review'
    WHEN organic_revenue_yoy_pct IS NULL THEN 'needs_history'
    WHEN organic_revenue_yoy_pct >= 0.10 AND IFNULL(organic_sessions_yoy_pct, 0) >= 0 THEN 'growing'
    WHEN organic_revenue_yoy_pct <= -0.10 OR organic_sessions_yoy_pct <= -0.10 THEN 'declining'
    ELSE 'stable'
  END AS performance_status,
  source_health
FROM base
""",
        "reporting_readiness": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.reporting_readiness`
CLUSTER BY client_slug AS
WITH latest_reports AS (
  SELECT client_slug, MAX(report_month) AS latest_report_month
  FROM `{project}.{memory}.monthly_report_snapshots`
  GROUP BY client_slug
)
SELECT
  c.client_slug,
  c.client_name,
  c.monday_board_id,
  c.ga4_property,
  latest_reports.latest_report_month IS NOT NULL AS has_report_snapshot,
  latest_reports.latest_report_month,
  CASE
    WHEN c.monday_board_id IS NULL THEN 'missing_monday_board'
    WHEN c.ga4_property IS NULL THEN 'missing_ga4_property'
    WHEN latest_reports.latest_report_month IS NULL THEN 'missing_report_snapshot'
    ELSE 'ready'
  END AS readiness_status
FROM `{project}.{memory}.client_registry` AS c
LEFT JOIN latest_reports
  ON c.client_slug = latest_reports.client_slug
""",
        "ops_drift_summary": f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.ops_drift_summary`
PARTITION BY snapshot_date AS
SELECT
  snapshot_date,
  client,
  COUNT(*) AS alignment_rows,
  COUNTIF(status_match = FALSE) AS status_mismatches,
  COUNTIF(owner_match = FALSE) AS owner_mismatches,
  COUNTIF(due_date_match = FALSE) AS due_date_mismatches,
  COUNTIF(stale_client_update = TRUE) AS stale_client_updates
FROM `{project}.{memory}.task_alignment`
GROUP BY snapshot_date, client
""",
        "client_comms_attention": client_comms_attention_sql(project, memory, reporting),
        "client_comms_history": client_comms_history_sql(project, memory, reporting),
        "client_roadmap_current": client_roadmap_current_sql(project, memory, reporting),
        "client_roadmap_monthly_completion": client_roadmap_monthly_completion_sql(project, reporting),
        "client_health_check": client_health_check_sql(project, memory, reporting),
        "client_finance_health": client_finance_health_sql(project, memory, reporting),
    }
    statuses = {}
    for mart_name, sql in queries.items():
        result, _ = runner.run_query(sql, purpose=f"agency-ops-mart: build {mart_name}")
        statuses[mart_name] = result.status
    return statuses


class AgencyOpsBigQueryIngestor:
    def __init__(self, client: Any, config: BigQueryCostConfig, paths: SourcePaths | None = None) -> None:
        self.client = client
        self.config = config
        self.paths = paths or SourcePaths()

    def ensure_tables(self) -> None:
        ensure_agency_ops_tables(self.client, self.config)

    def run(
        self,
        *,
        run_id: str | None = None,
        write_disposition: str = "WRITE_TRUNCATE",
        build_marts: bool = True,
    ) -> IngestionSummary:
        run_id = run_id or uuid4().hex
        ingested_at = utc_now_iso()
        snapshot_date = today_iso()
        self.ensure_tables()
        self.load_rows(
            self.config.table_id(self.config.control_dataset, "data_sources"),
            source_registry_rows(self.paths, ingested_at),
            write_disposition="WRITE_TRUNCATE",
        )
        rows_by_table = collect_agency_ops_rows(
            self.paths,
            run_id=run_id,
            ingested_at=ingested_at,
            snapshot_date=snapshot_date,
        )
        counts: dict[str, int] = {}
        for short_table, rows in rows_by_table.items():
            dataset, table = short_table.split(".", 1)
            table_id = self.config.table_id(dataset, table)
            try:
                loaded = self.load_rows(table_id, rows, write_disposition=write_disposition)
                self.log_ingestion_run(
                    run_id=run_id,
                    source_id=short_table.replace(".", "_"),
                    started_at=ingested_at,
                    status="succeeded",
                    source_path=short_table,
                    destination_table=table_id,
                    rows_loaded=loaded,
                )
                counts[short_table] = loaded
            except Exception as exc:
                self.log_ingestion_run(
                    run_id=run_id,
                    source_id=short_table.replace(".", "_"),
                    started_at=ingested_at,
                    status="failed",
                    source_path=short_table,
                    destination_table=table_id,
                    rows_loaded=0,
                    error_message=f"{type(exc).__name__}: {str(exc)[:400]}",
                )
                raise

        mart_statuses: dict[str, str] = {}
        if build_marts:
            runner = CappedBigQueryRunner(self.client, self.config)
            mart_statuses = build_reporting_marts(runner, self.config)
        return IngestionSummary(run_id=run_id, status="succeeded", table_counts=counts, mart_statuses=mart_statuses)

    def load_rows(self, table_id: str, rows: list[dict[str, Any]], *, write_disposition: str) -> int:
        if not rows:
            return 0
        try:
            from google.cloud import bigquery
        except ModuleNotFoundError as exc:
            raise RuntimeError("google-cloud-bigquery is required for live ingestion.") from exc
        job_config = bigquery.LoadJobConfig(write_disposition=write_disposition)
        job = self.client.load_table_from_json(rows, table_id, job_config=job_config, location=self.config.default_location)
        job.result()
        return len(rows)

    def log_ingestion_run(
        self,
        *,
        run_id: str,
        source_id: str,
        started_at: str,
        status: str,
        source_path: str,
        destination_table: str,
        rows_loaded: int,
        error_message: str | None = None,
    ) -> None:
        completed_at = utc_now_iso() if status != "started" else None
        row = {
            "run_id": run_id,
            "source_id": source_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "status": status,
            "source_path": source_path,
            "destination_table": destination_table,
            "rows_loaded": rows_loaded,
            "error_message": error_message,
        }
        errors = self.client.insert_rows_json(self.config.table_id(self.config.control_dataset, "ingestion_runs"), [row])
        if errors:
            raise RuntimeError(f"Could not log ingestion run: {errors}")
