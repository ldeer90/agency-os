from __future__ import annotations

import calendar
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402

from .scoring import overall_health  # noqa: E402

SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_ENV_PATH = Path("/Users/laurencedeer/Projects/Codex/SEO Automation/.env")
REPORTING_PORTAL_ENV_PATH = Path("/Users/laurencedeer/Projects/Codex/seo-reporting-platform/.env.local")
DEFAULT_REPORTS_PUBLIC_BASE_URL = "https://reports.laurencedeer.com.au"
AGENT_INDEX_PATH = PROJECT_ROOT / "data" / "agent_runs" / "index.json"
AGENT_RUNS_ROOT = PROJECT_ROOT / "data" / "agent_runs"
DRIVE_VERIFICATIONS_PATH = PROJECT_ROOT / "data" / "client_health" / "drive_folder_verifications.json"
SEO_CLIENTS_PATH = Path("/Users/laurencedeer/Projects/Codex/SEO Automation/docs/agent/clients")
CACHE_TTL_SECONDS = 120
MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")
_CACHE_LOCK = Lock()
_DASHBOARD_CACHE: dict[str, Any] = {"created_at": 0.0, "payload": None}
EXCLUDED_CLIENT_SLUGS = {
    "acorn-car-rentals",
    "bestvpn",
    "heiych",
    "joe-rascal",
    "joe-rascal-ducati",
    "joe-rascal-global",
    "mr-gadget",
    "mrgadget",
    "salad-servers",
}
CLIENT_SLUG_ALIASES = {
    "acorn-car-rentals": "acorn-rentals",
    "joe-rascal-ducati": "ducati-melbourne",
    "salad-servers": "salad-servers-direct",
}
EXCLUDED_CLIENT_NAME_FRAGMENTS = {
    "bestvpn",
    "heiych",
    "joerascal.com",
    "mr gadget",
    "mrgadget",
}


def canonical_client_slug(value: Any) -> str:
    slug = str(value or "").strip().lower()
    return CLIENT_SLUG_ALIASES.get(slug, slug)


def canonical_client_slug_sql(expression: str) -> str:
    clauses = " ".join(f"WHEN '{alias}' THEN '{canonical}'" for alias, canonical in sorted(CLIENT_SLUG_ALIASES.items()))
    return f"CASE LOWER({expression}) {clauses} ELSE LOWER({expression}) END"


def utc_now() -> str:
    return datetime.now(MELBOURNE_TIMEZONE).replace(microsecond=0).isoformat()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
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


def load_safe_env_value(path: Path, key_name: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key == key_name:
            return value.strip().strip('"').strip("'").rstrip("/")
    return None


def reports_public_base_url() -> str | None:
    value = os.environ.get("REPORTS_PUBLIC_BASE_URL") or load_safe_env_value(REPORTING_PORTAL_ENV_PATH, "REPORTS_PUBLIC_BASE_URL") or DEFAULT_REPORTS_PUBLIC_BASE_URL
    if not value:
        return None
    value = value.strip().strip('"').strip("'").rstrip("/")
    if not value.startswith(("http://", "https://")):
        return None
    return value


def report_period_slug(period_id: Any, report_month: Any = None) -> str | None:
    source = str(period_id or "").strip()
    if not source and report_month:
        source = str(report_month).strip()[:7]
    try:
        year_text, month_text = source.split("-", 1)
        year = int(year_text)
        month = int(month_text[:2])
    except (TypeError, ValueError):
        return None
    if month < 1 or month > 12:
        return None
    return f"{calendar.month_name[month].lower()}-{year}"


def enrich_report_links(payload: dict[str, Any], public_base_url: str | None = None) -> None:
    base_url = (public_base_url or reports_public_base_url() or "").rstrip("/")
    for row in payload.get("report_links", []):
        slug = str(row.get("client_slug") or "").strip()
        share_id = str(row.get("share_id") or "").strip()
        period_slug = report_period_slug(row.get("period_id"), row.get("report_month"))
        row["month_tab"] = str(row.get("period_id") or str(row.get("report_month") or "")[:7] or "").strip()
        if not slug or not share_id or not period_slug:
            row["report_public_path"] = None
            row["compact_report_public_path"] = None
            row["report_url"] = None
            row["compact_report_url"] = None
            continue
        path = f"/{slug}/{period_slug}/{share_id}/"
        compact_path = f"{path}compact/"
        row["report_public_path"] = path
        row["compact_report_public_path"] = compact_path
        row["report_url"] = f"{base_url}{path}" if base_url else None
        row["compact_report_url"] = f"{base_url}{compact_path}" if base_url else None


def query_definitions(config: BigQueryCostConfig) -> dict[str, str]:
    project = config.project_id
    memory = config.memory_dataset
    reporting = config.reporting_dataset
    control = config.control_dataset
    excluded_slugs_sql = ", ".join(f"'{slug}'" for slug in sorted(EXCLUDED_CLIENT_SLUGS))
    task_client_slug_sql = canonical_client_slug_sql("t.client_slug")
    return {
        "clients": f"""
SELECT snapshot_date, client_slug, client_name, expected_assets, present_assets, health_status, health_score, critical_missing_assets,
  missing_required_assets, latest_report_month, has_drive_root_verified, has_roadmap_content_validated,
  has_ga4_access, has_search_console_access, has_se_ranking_access, missing_required_json, missing_optional_json,
  has_sidecar_json, has_client_brief, has_timeline, has_drive_root, has_roadmap_route, has_roadmap_files,
  has_content_route, has_reports_route, has_monday_board, has_reporting_config, has_monthly_report_snapshot, has_roadmap_items
FROM `{project}.{reporting}.client_health_check`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
ORDER BY CASE health_status WHEN 'critical_missing' THEN 1 WHEN 'needs_attention' THEN 2 WHEN 'partial' THEN 3 ELSE 4 END, client_slug
LIMIT 100
""",
        "client_profiles": f"""
SELECT client_slug, client_name, canonical_host, website_hosts_json, favicon_url, favicon_source,
  favicon_candidates_json, ga4_property, search_console_json, se_ranking_project_id, monday_board_id,
  reporting_template, source_paths_json, status
FROM `{project}.{memory}.client_registry`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY ingested_at DESC) = 1
ORDER BY client_slug
LIMIT 100
""",
        "client_context": f"""
SELECT client_slug, client_name, business_summary, primary_goals_json, seo_priorities_json, target_audience,
  key_products_or_services_json, important_pages_json, brand_tone, competitors_json, constraints_or_risks_json,
  approval_preferences, reporting_expectations, agent_context_summary, source_drive_file_id, source_drive_file_name,
  source_modified_at, review_status, confidence, source_ref_hash, validation_status
FROM `{project}.{memory}.client_onboarding_profiles`
WHERE client_slug NOT IN ({excluded_slugs_sql})
  AND review_status IN ('reviewed', 'approved')
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY source_modified_at DESC NULLS LAST, ingested_at DESC) = 1
ORDER BY client_slug
LIMIT 100
""",
        "health_assets": f"""
SELECT snapshot_date, client_slug, client_name, asset_type, asset_label, presence_status, expected, criticality,
  source_system, source_path, source_ref, freshness_date, verification_level, verified_at, verification_method, notes
FROM `{project}.{memory}.client_health_assets`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
ORDER BY client_slug, expected DESC, CASE criticality WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, asset_type
LIMIT 400
""",
        "delivery": f"""
WITH latest_clients AS (
  SELECT client_slug
  FROM `{project}.{reporting}.client_health_check`
  WHERE client_slug NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
),
latest_tasks AS (
  SELECT
    t.*,
    {task_client_slug_sql} AS canonical_client_slug
  FROM `{project}.{reporting}.client_task_status` t
  JOIN latest_clients c
    ON {task_client_slug_sql} = c.client_slug
  WHERE {task_client_slug_sql} NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY t.snapshot_date DESC) = 1
)
SELECT snapshot_date, canonical_client_slug AS client_slug, board_name, group_title, item_name, status, normalized_status, owner, due_date,
  due_date < CURRENT_DATE('Australia/Melbourne') AS is_overdue,
  owner IS NULL AS owner_missing,
  CASE WHEN due_date < CURRENT_DATE('Australia/Melbourne') THEN 'overdue' WHEN due_date IS NULL THEN 'missing_due_date' ELSE 'open' END AS due_state
FROM latest_tasks
WHERE COALESCE(normalized_status, 'Not Started') != 'Done'
ORDER BY is_overdue DESC, due_date IS NULL DESC, due_date, canonical_client_slug, item_name
LIMIT 150
""",
        "task_client_detail": f"""
WITH latest_clients AS (
  SELECT client_slug, client_name
  FROM `{project}.{reporting}.client_health_check`
  WHERE client_slug NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
),
latest_tasks AS (
  SELECT t.*
  FROM `{project}.{reporting}.client_task_status` t
  JOIN latest_clients c
    ON {task_client_slug_sql} = c.client_slug
  WHERE {task_client_slug_sql} NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY t.snapshot_date DESC) = 1
)
SELECT
  t.snapshot_date,
  {task_client_slug_sql} AS client_slug,
  c.client_name,
  t.board_name,
  t.group_title,
  t.item_id,
  t.item_name,
  t.status,
  t.normalized_status,
  COALESCE(t.normalized_status, t.status, 'Not Started') AS status_label,
  t.owner,
  t.due_date,
  t.updated_at,
  IFNULL(t.is_done, FALSE) AS is_done,
  IFNULL(t.is_overdue, FALSE) AS is_overdue,
  t.owner IS NULL AS owner_missing,
  t.due_date IS NULL AND NOT IFNULL(t.is_done, FALSE) AS due_date_missing,
  CASE
    WHEN IFNULL(t.is_overdue, FALSE) THEN 'overdue'
    WHEN t.due_date IS NULL AND NOT IFNULL(t.is_done, FALSE) THEN 'missing_due_date'
    WHEN IFNULL(t.is_done, FALSE) THEN 'done'
    ELSE 'open'
  END AS due_state
FROM latest_tasks t
JOIN latest_clients c
  ON {task_client_slug_sql} = c.client_slug
ORDER BY IFNULL(t.is_done, FALSE), IFNULL(t.is_overdue, FALSE) DESC, t.due_date IS NULL DESC, t.due_date, c.client_name, t.item_name
LIMIT 500
""",
        "task_status_by_client": f"""
WITH latest_clients AS (
  SELECT client_slug, client_name
  FROM `{project}.{reporting}.client_health_check`
  WHERE client_slug NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
),
latest_tasks AS (
  SELECT
    t.*,
    {task_client_slug_sql} AS canonical_client_slug,
    COALESCE(t.normalized_status, t.status, 'Not Started') AS status_label
  FROM `{project}.{reporting}.client_task_status` t
  JOIN latest_clients c
    ON {task_client_slug_sql} = c.client_slug
  WHERE {task_client_slug_sql} NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY t.snapshot_date DESC) = 1
)
SELECT
  c.client_slug,
  c.client_name,
  COUNT(t.item_id) AS total_tasks,
  COUNTIF(t.item_id IS NOT NULL AND IFNULL(t.is_done, FALSE)) AS done_tasks,
  COUNTIF(t.item_id IS NOT NULL AND NOT IFNULL(t.is_done, FALSE)) AS open_tasks,
  COUNTIF(t.item_id IS NOT NULL AND t.status_label = 'Not Started') AS not_started_tasks,
  COUNTIF(t.item_id IS NOT NULL AND t.status_label = 'In Progress') AS in_progress_tasks,
  COUNTIF(t.item_id IS NOT NULL AND LOWER(t.status_label) LIKE '%approval%') AS approval_tasks,
  COUNTIF(t.item_id IS NOT NULL AND LOWER(t.status_label) LIKE '%brief%') AS brief_tasks,
  COUNTIF(
    t.item_id IS NOT NULL
    AND
    NOT IFNULL(t.is_done, FALSE)
    AND t.status_label NOT IN ('Not Started', 'In Progress')
    AND LOWER(t.status_label) NOT LIKE '%approval%'
    AND LOWER(t.status_label) NOT LIKE '%brief%'
  ) AS other_open_tasks,
  COUNTIF(t.item_id IS NOT NULL AND IFNULL(t.is_overdue, FALSE)) AS overdue_tasks,
  COUNTIF(t.item_id IS NOT NULL AND t.owner IS NULL) AS missing_owner_tasks,
  COUNTIF(t.item_id IS NOT NULL AND t.due_date IS NULL AND NOT IFNULL(t.is_done, FALSE)) AS missing_due_date_tasks,
  MAX(t.snapshot_date) AS latest_snapshot_date,
  MAX(t.updated_at) AS latest_update_at
FROM latest_clients c
LEFT JOIN latest_tasks t
  ON c.client_slug = t.canonical_client_slug
GROUP BY c.client_slug, c.client_name
ORDER BY c.client_name
LIMIT 100
""",
        "task_status_distribution": f"""
WITH latest_clients AS (
  SELECT client_slug
  FROM `{project}.{reporting}.client_health_check`
  WHERE client_slug NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
),
latest_tasks AS (
  SELECT
    COALESCE(t.normalized_status, t.status, 'Not Started') AS status_label,
    IFNULL(t.is_overdue, FALSE) AS is_overdue
  FROM `{project}.{reporting}.client_task_status` t
  JOIN latest_clients c
    ON {task_client_slug_sql} = c.client_slug
  WHERE {task_client_slug_sql} NOT IN ({excluded_slugs_sql})
  QUALIFY RANK() OVER (ORDER BY t.snapshot_date DESC) = 1
)
SELECT
  status_label,
  COUNT(*) AS task_count,
  COUNTIF(is_overdue) AS overdue_tasks
FROM latest_tasks
GROUP BY status_label
ORDER BY task_count DESC, status_label
LIMIT 50
""",
        "ops_drift": f"""
SELECT
  snapshot_date,
  client AS client_name,
  alignment_rows,
  status_mismatches,
  owner_mismatches,
  due_date_mismatches,
  stale_client_updates,
  IFNULL(status_mismatches, 0) + IFNULL(owner_mismatches, 0) + IFNULL(due_date_mismatches, 0) + IFNULL(stale_client_updates, 0) AS drift_issues
FROM `{project}.{reporting}.ops_drift_summary`
QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1
ORDER BY drift_issues DESC, client_name
LIMIT 100
""",
        "performance": f"""
SELECT c.client_slug, c.client_name, c.period_id, c.organic_sessions, c.organic_sessions_mom_pct,
  c.organic_sessions_yoy_pct, c.gsc_clicks, c.gsc_clicks_mom_pct, c.organic_revenue,
  c.organic_revenue_mom_pct, c.se_visibility_end, c.source_health,
  b.performance_status
FROM `{project}.{reporting}.client_monthly_comparison` c
LEFT JOIN `{project}.{reporting}.client_benchmark_summary` b USING (client_slug)
WHERE c.client_slug NOT IN ({excluded_slugs_sql})
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.client_slug ORDER BY c.month_start DESC) = 1
ORDER BY c.client_slug
LIMIT 100
""",
        "performance_history": f"""
SELECT period_id, month_start, month_end, client_slug, client_name, ga4_status, gsc_status, se_ranking_status,
  organic_sessions, organic_users, organic_revenue, organic_conversion_rate, ai_sessions,
  gsc_clicks, gsc_impressions, gsc_ctr, gsc_avg_position, se_visibility_end, se_visibility_delta,
  se_top10_end, se_avg_position_end
FROM `{project}.{reporting}.client_monthly_performance_history`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY month_start DESC) <= 13
ORDER BY client_slug, month_start
LIMIT 200
""",
        "comms": f"""
SELECT week_start, week_end, client_slug, client_name, signal_type, severity, channel, category,
  summary, recommended_action, owner_hint, due_hint, latest_event_at
FROM `{project}.{reporting}.client_comms_attention`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY RANK() OVER (ORDER BY week_start DESC) = 1
ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, client_slug, signal_type
LIMIT 100
""",
        "roadmaps": f"""
SELECT planned_month, client_slug, client_name, planned_items, completed_items, missing_evidence_items,
  overdue_items, completion_rate, status_summary
FROM `{project}.{reporting}.client_roadmap_monthly_completion`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY RANK() OVER (ORDER BY planned_month DESC) = 1
ORDER BY status_summary, client_slug
LIMIT 100
""",
        "roadmap_items": f"""
SELECT planned_month, period_id, client_slug, client_name, roadmap_item_id, item_title, work_type, priority,
  planned_status, delivery_status, owner_hint, due_date, target_url, keyword_theme,
  completion_evidence_type, completion_summary, completion_confidence, matched_evidence_table, matched_evidence_date
FROM `{project}.{reporting}.client_roadmap_current`
WHERE client_slug NOT IN ({excluded_slugs_sql})
ORDER BY planned_month DESC, client_slug, CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, due_date, item_title
LIMIT 500
""",
        "reporting": f"""
SELECT rr.client_slug, rr.client_name, rr.monday_board_id, rr.ga4_property, rr.has_report_snapshot,
  rr.latest_report_month, rr.readiness_status, cov.coverage_status, cov.has_ga4, cov.has_search_console,
  cov.has_se_ranking, cov.has_ai_referrals
FROM `{project}.{reporting}.reporting_readiness` rr
LEFT JOIN `{project}.{reporting}.client_monthly_reporting_coverage` cov
  ON rr.client_slug = cov.client_slug
WHERE rr.client_slug NOT IN ({excluded_slugs_sql})
QUALIFY ROW_NUMBER() OVER (PARTITION BY rr.client_slug ORDER BY cov.period_id DESC NULLS LAST) = 1
ORDER BY rr.readiness_status, rr.client_slug
LIMIT 100
""",
        "report_links": f"""
SELECT period_id, report_month, client_slug, client_name, share_id, report_path, generated_at, schema_version,
  template, source_caveats_json
FROM `{project}.{memory}.monthly_report_snapshots`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug, period_id ORDER BY generated_at DESC NULLS LAST, ingested_at DESC) = 1
ORDER BY report_month DESC, client_slug
LIMIT 200
""",
        "agent_run_log": f"""
SELECT run_id, automation_id, agent_id, agent_name, started_at, completed_at, status, mode, prompt_version,
  output_path, findings_count, actions_count, error_message, dry_run, bigquery_write_status
FROM `{project}.{control}.agent_run_log`
ORDER BY started_at DESC
LIMIT 100
""",
        "workflow_runs": f"""
SELECT completed_at, run_id, client_slug, workflow_id, agent_id, status, summary, outputs_json, blockers_json, next_actions_json
FROM `{project}.{memory}.seo_workflow_run_summaries`
ORDER BY completed_at DESC
LIMIT 100
""",
        "client_timeline": f"""
SELECT client_slug, client_name, event_date, event_type, title, status, source_table, source_id
FROM `{project}.{reporting}.client_delivery_timeline`
WHERE client_slug NOT IN ({excluded_slugs_sql})
ORDER BY event_date DESC, client_slug, title
LIMIT 500
""",
        "report_narratives": f"""
SELECT period_id, report_month, client_slug, client_name, share_id, generated_at, summary, completed_work, next_focus, caveats
FROM `{project}.{reporting}.client_monthly_report_narrative`
WHERE client_slug NOT IN ({excluded_slugs_sql})
QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug, period_id ORDER BY generated_at DESC NULLS LAST) = 1
ORDER BY report_month DESC, client_slug
LIMIT 100
""",
        "comms_history": f"""
SELECT week_start, week_end, client_slug, client_name, thread_status, latest_event_at, resolved_at, channel, category,
  summary, recommended_action, owner_hint, due_hint, needs_reply, blocked, waiting_on_client, waiting_on_us,
  stale_followup, urgency, sentiment, resolution_summary, source_event_count, confidence
FROM `{project}.{reporting}.client_comms_history`
WHERE client_slug NOT IN ({excluded_slugs_sql})
ORDER BY latest_event_at DESC, client_slug
LIMIT 150
""",
        "seo_opportunities": f"""
SELECT generated_at, client_slug, client_name, opportunity_type, workflow_id, priority, summary, recommended_action, source_ref_hash
FROM `{project}.{reporting}.seo_opportunity_queue`
WHERE client_slug NOT IN ({excluded_slugs_sql})
ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, generated_at DESC, client_slug
LIMIT 150
""",
        "workflow_readiness": f"""
SELECT generated_at, client_slug, client_name, readiness_status, recommended_workflow_id, recommended_agent_id, missing_inputs_json, source_ref_hash
FROM `{project}.{reporting}.seo_workflow_readiness`
WHERE client_slug NOT IN ({excluded_slugs_sql})
ORDER BY CASE readiness_status WHEN 'blocked' THEN 1 WHEN 'needs_attention' THEN 2 WHEN 'partial' THEN 3 WHEN 'ready' THEN 4 ELSE 5 END, client_slug
LIMIT 150
""",
        "crawl_latest": f"""
SELECT crawl_date, crawl_id, crawl_id AS source_id, client_slug, client_name, crawl_trigger, crawler, crawl_status, pages_crawled, indexable_html_urls,
  status_4xx_urls, status_5xx_urls, missing_title_urls, missing_meta_description_urls, missing_h1_urls,
  canonical_issue_urls, low_content_urls
FROM `{project}.{reporting}.client_crawl_latest`
WHERE client_slug NOT IN ({excluded_slugs_sql})
ORDER BY crawl_date DESC, client_slug
LIMIT 100
""",
        "api_smoke_checks": f"""
SELECT client_slug, source, checked_at, status, date_start, date_end, rows_returned, error_class
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY client_slug, source ORDER BY checked_at DESC) AS rn
  FROM `{project}.{control}.api_smoke_checks`
  WHERE client_slug NOT IN ({excluded_slugs_sql})
)
WHERE rn = 1
ORDER BY client_slug, source
LIMIT 100
""",
        "data_health_ingestion": f"""
SELECT started_at, completed_at, source_id, status, destination_table, rows_loaded, error_message
FROM `{project}.{control}.ingestion_runs`
ORDER BY started_at DESC
LIMIT 30
""",
        "data_health_cost": f"""
SELECT logged_at, purpose, status, estimated_bytes, cap_bytes, job_id
FROM `{project}.{control}.cost_checks`
ORDER BY logged_at DESC
LIMIT 30
""",
    }


def read_agent_index() -> list[dict[str, Any]]:
    if not AGENT_INDEX_PATH.exists():
        return []
    try:
        payload = json.loads(AGENT_INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return payload[:100]
    if isinstance(payload, dict):
        entries = payload.get("runs") or payload.get("entries") or []
        return entries[:100] if isinstance(entries, list) else []
    return []


def coerce_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def safe_profile_text(value: Any, *, max_length: int = 120) -> str | None:
    if value in (None, "", []):
        return None
    text = str(value).strip()
    if not text or len(text) > max_length:
        return None
    if "@" in text or "://" in text:
        return None
    return text


def nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def read_client_sidecar_profiles(path: Path = SEO_CLIENTS_PATH) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return profiles
    for sidecar_path in sorted(path.glob("*.json")):
        if sidecar_path.name.startswith("CLIENT_TEMPLATE"):
            continue
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        slug = str(sidecar.get("client") or sidecar_path.stem).strip().lower().replace(" ", "-")
        if not slug:
            continue
        contact = sidecar.get("primary_contact") if isinstance(sidecar.get("primary_contact"), dict) else {}
        contact = contact or (sidecar.get("contact") if isinstance(sidecar.get("contact"), dict) else {})
        business = sidecar.get("business") if isinstance(sidecar.get("business"), dict) else {}
        profile = sidecar.get("profile") if isinstance(sidecar.get("profile"), dict) else {}
        account = sidecar.get("account") if isinstance(sidecar.get("account"), dict) else {}
        drive = sidecar.get("drive") if isinstance(sidecar.get("drive"), dict) else {}
        folders = drive.get("folders") if isinstance(drive.get("folders"), dict) else {}
        profiles[slug] = {
            "abn": safe_profile_text(sidecar.get("abn") or business.get("abn") or profile.get("abn") or account.get("abn"), max_length=40),
            "primary_contact_name": safe_profile_text(
                sidecar.get("primary_contact_name")
                or contact.get("name")
                or account.get("primary_contact_name")
                or profile.get("primary_contact_name")
            ),
            "primary_contact_role": safe_profile_text(
                sidecar.get("primary_contact_role")
                or contact.get("role")
                or contact.get("title")
                or account.get("primary_contact_role")
                or profile.get("primary_contact_role")
            ),
            "domain": sidecar.get("domain") or nested_get(sidecar, "website", "primary_url"),
            "drive_client_folder_id": drive.get("client_folder_id"),
            "drive_roadmap_folder_id": folders.get("02_roadmap"),
            "drive_reports_folder_id": folders.get("07_reports"),
            "monday_board_url": nested_get(sidecar, "monday", "board_url"),
            "source_path": str(sidecar_path),
        }
    return profiles


def read_drive_evidence(path: Path = DRIVE_VERIFICATIONS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    folders = payload.get("folders") if isinstance(payload, dict) else []
    if not isinstance(folders, list):
        return []
    rows: list[dict[str, Any]] = []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        rows.append(
            {
                "client_slug": folder.get("client_slug"),
                "client_name": folder.get("client_name"),
                "folder_role": folder.get("folder_role"),
                "folder_id": folder.get("folder_id"),
                "verified_at": folder.get("verified_at") or payload.get("verified_at"),
                "file_count": folder.get("file_count"),
                "populated_file_count": folder.get("populated_file_count"),
                "content_validated_file_count": folder.get("content_validated_file_count"),
                "content_failed_file_count": folder.get("content_failed_file_count"),
                "content_validation_status": folder.get("content_validation_status"),
                "latest_modified_date": folder.get("latest_modified_date"),
                "source": "data/client_health/drive_folder_verifications.json",
            }
        )
    return rows


def missing_asset_labels(row: dict[str, Any], key: str) -> list[str]:
    raw = coerce_json(row.get(key))
    if isinstance(raw, list):
        return [str(item) for item in raw if item not in (None, "")]
    if isinstance(raw, dict):
        return [str(value) for value in raw.values() if value not in (None, "")]
    return []


def group_by_client(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        slug = str(row.get("client_slug") or "")
        if slug:
            grouped.setdefault(slug, []).append(row)
    return grouped


def agent_completed_at(row: dict[str, Any]) -> str:
    return str(row.get("completed_at") or row.get("started_at") or "")


def title_from_identifier(value: Any) -> str | None:
    text = safe_profile_text(value, max_length=120)
    if not text:
        return None
    head = text.split("/", 1)[0]
    return head.replace("_", " ").replace("-", " ").title()


def safe_summary_text(value: Any, *, max_length: int = 260) -> str | None:
    text = safe_profile_text(value, max_length=max_length)
    if not text:
        return None
    return text


def safe_agent_run_path(row: dict[str, Any]) -> Path | None:
    candidates: list[Path] = []
    for key in ("run_json_path", "output_path"):
        value = row.get(key)
        if isinstance(value, str) and value.endswith(".json"):
            candidates.append(Path(value))
    agent_id = str(row.get("agent_id") or "")
    run_id = str(row.get("run_id") or "")
    if agent_id and run_id:
        candidates.append(AGENT_RUNS_ROOT / agent_id / f"{run_id}.json")
    root = AGENT_RUNS_ROOT.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if root == resolved or root in resolved.parents:
            return resolved
    return None


def read_agent_run_detail(row: dict[str, Any]) -> dict[str, Any]:
    path = safe_agent_run_path(row)
    if not path or not path.exists() or path.stat().st_size > 2_000_000:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    run_log = payload.get("run_log") if isinstance(payload.get("run_log"), dict) else {}
    detail: dict[str, Any] = {
        "task_summary": safe_summary_text(payload.get("summary") or run_log.get("summary")),
        "task_name": safe_summary_text(payload.get("task_name") or payload.get("title"), max_length=120),
        "detail_findings_count": len(findings),
        "detail_actions_count": len(actions),
        "metrics": {str(key): value for key, value in metrics.items() if isinstance(value, (str, int, float, bool))},
    }
    if not detail["task_name"]:
        action_types = sorted({str(action.get("action_type") or "").replace("_", " ") for action in actions[:8] if isinstance(action, dict) and action.get("action_type")})
        finding_types = sorted({str(finding.get("finding_type") or "").replace("_", " ") for finding in findings[:8] if isinstance(finding, dict) and finding.get("finding_type")})
        if action_types:
            detail["task_name"] = f"Review {', '.join(action_types[:2]).title()}"
        elif finding_types:
            detail["task_name"] = f"Check {', '.join(finding_types[:2]).title()}"
    return detail


def agent_task_name(row: dict[str, Any], detail: dict[str, Any]) -> str:
    summary_name = infer_agent_task_name_from_summary(row.get("task_summary") or row.get("summary") or detail.get("task_summary"))
    return (
        safe_summary_text(row.get("task_name"), max_length=120)
        or safe_summary_text(detail.get("task_name"), max_length=120)
        or summary_name
        or title_from_identifier(row.get("workflow_id"))
        or title_from_identifier(row.get("prompt_version"))
        or title_from_identifier(row.get("agent_name") or row.get("agent_id"))
        or "Agent task"
    )


def infer_agent_task_name_from_summary(value: Any) -> str | None:
    summary = str(value or "").lower()
    if "daily agency brief" in summary:
        return "Daily agency brief"
    if "summarized comms" in summary or "possible promise" in summary:
        return "Promise review"
    if "reporting readiness" in summary:
        return "Reporting readiness review"
    if "technical audit" in summary:
        return "Technical audit review"
    return None


def agent_task_summary(row: dict[str, Any], detail: dict[str, Any]) -> str:
    summary = safe_summary_text(row.get("task_summary") or row.get("summary") or detail.get("task_summary"))
    if summary:
        return summary
    findings_count = safe_int(row.get("findings_count") or detail.get("detail_findings_count"))
    actions_count = safe_int(row.get("actions_count") or detail.get("detail_actions_count"))
    mode = row.get("mode")
    if findings_count or actions_count:
        return f"Completed with {findings_count} finding(s) and {actions_count} suggested action(s)."
    if mode:
        return f"Completed a {mode} run with no findings or actions recorded."
    return "Completed run; no short summary was recorded."


def agent_task_row(row: dict[str, Any], source: str) -> dict[str, Any]:
    detail = read_agent_run_detail(row)
    return {
        "agent_id": row.get("agent_id"),
        "agent_name": row.get("agent_name") or row.get("agent_id"),
        "run_id": row.get("run_id"),
        "status": row.get("status"),
        "mode": row.get("mode"),
        "completed_at": row.get("completed_at"),
        "started_at": row.get("started_at"),
        "findings_count": row.get("findings_count") or detail.get("detail_findings_count"),
        "actions_count": row.get("actions_count") or detail.get("detail_actions_count"),
        "output_path": row.get("output_path"),
        "workflow_id": row.get("workflow_id"),
        "client_slug": row.get("client_slug"),
        "task_name": agent_task_name(row, detail),
        "task_summary": agent_task_summary(row, detail),
        "metrics": detail.get("metrics") or {},
        "source": source,
    }


def summarize_agent_activity(local_runs: list[dict[str, Any]], bq_runs: list[dict[str, Any]], workflow_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in [*bq_runs, *local_runs]:
        if str(row.get("status") or "").lower() == "running":
            continue
        rows.append(agent_task_row(row, "agency_control.agent_run_log" if row in bq_runs else "data/agent_runs/index.json"))
    for row in workflow_runs:
        rows.append(agent_task_row({**row, "agent_name": row.get("agent_id"), "mode": "seo_workflow"}, "agency_memory.seo_workflow_run_summaries"))
    grouped: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=agent_completed_at, reverse=True):
        agent_id = str(row.get("agent_id") or "unknown")
        entry = grouped.setdefault(
            agent_id,
            {
                "agent_id": agent_id,
                "agent_name": row.get("agent_name") or agent_id,
                "last_completed_at": row.get("completed_at") or row.get("started_at"),
                "recent_runs": [],
                "succeeded": 0,
                "failed": 0,
            },
        )
        if len(entry["recent_runs"]) < 5:
            entry["recent_runs"].append(row)
        status = str(row.get("status") or "").lower()
        if status in {"succeeded", "success", "ok"}:
            entry["succeeded"] += 1
        elif status in {"failed", "error"}:
            entry["failed"] += 1
    return list(grouped.values())


def completed_agent_work_rows(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agent in summaries:
        for run in agent.get("recent_runs", []):
            status = str(run.get("status") or "").lower()
            if status not in {"succeeded", "success", "ok", "completed", "done"}:
                continue
            rows.append(
                {
                    "agent_id": agent.get("agent_id"),
                    "agent_name": agent.get("agent_name"),
                    "task_name": run.get("task_name"),
                    "task_summary": run.get("task_summary"),
                    "client_slug": run.get("client_slug"),
                    "completed_at": run.get("completed_at") or run.get("started_at"),
                    "status": run.get("status"),
                    "findings_count": run.get("findings_count"),
                    "actions_count": run.get("actions_count"),
                    "workflow_id": run.get("workflow_id"),
                    "output_path": run.get("output_path"),
                    "source": run.get("source"),
                }
            )
    return sorted(rows, key=lambda row: str(row.get("completed_at") or ""), reverse=True)


def event_date_text(value: Any) -> str:
    return str(value or "")[:10]


def unified_timeline_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for row in payload.get("client_timeline", []):
        rows.append(
            {
                "event_date": row.get("event_date"),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": row.get("event_type") or "timeline",
                "title": row.get("title"),
                "status": row.get("status"),
                "summary": row.get("title"),
                "source_table": row.get("source_table") or "agency_reporting.client_delivery_timeline",
                "source_id": row.get("source_id"),
            }
        )

    for row in payload.get("crawl_latest", []):
        summary = (
            f"{row.get('crawler') or 'Crawl'} {row.get('crawl_status') or 'completed'}"
            f"; {row.get('pages_crawled') or 0} pages crawled"
        )
        rows.append(
            {
                "event_date": row.get("crawl_date"),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": "technical_crawl",
                "title": f"Technical crawl: {row.get('crawl_trigger') or 'crawl'}",
                "status": row.get("crawl_status"),
                "summary": summary,
                "source_table": "agency_reporting.client_crawl_latest",
                "source_id": row.get("source_id") or row.get("crawl_id"),
                "pages_crawled": row.get("pages_crawled"),
            }
        )

    for row in payload.get("report_narratives", []):
        rows.append(
            {
                "event_date": row.get("report_month") or event_date_text(row.get("generated_at")),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": "report_narrative",
                "title": f"Report narrative: {row.get('period_id') or row.get('report_month')}",
                "status": "ready",
                "summary": row.get("next_focus") or row.get("summary"),
                "source_table": "agency_reporting.client_monthly_report_narrative",
                "source_id": row.get("share_id"),
            }
        )

    for row in payload.get("agent_work_completed", []):
        rows.append(
            {
                "event_date": event_date_text(row.get("completed_at")),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": "agent_work_completed",
                "title": row.get("task_name"),
                "status": row.get("status"),
                "summary": row.get("task_summary"),
                "source_table": row.get("source"),
                "source_id": row.get("workflow_id") or row.get("output_path"),
                "agent_name": row.get("agent_name"),
            }
        )

    for row in payload.get("drive_evidence", []):
        if row.get("folder_role") not in {"drive_roadmap_folder", "drive_reports_folder", "drive_content_folder"}:
            continue
        rows.append(
            {
                "event_date": event_date_text(row.get("verified_at")),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": "drive_evidence",
                "title": f"Drive evidence verified: {row.get('folder_role')}",
                "status": row.get("content_validation_status") or "verified",
                "summary": f"{row.get('populated_file_count') or row.get('file_count') or 0} file(s), latest modified {row.get('latest_modified_date') or 'unknown'}",
                "source_table": "data/client_health/drive_folder_verifications.json",
                "source_id": row.get("folder_id"),
            }
        )

    for row in payload.get("seo_opportunities", []):
        rows.append(
            {
                "event_date": event_date_text(row.get("generated_at")),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": "seo_opportunity",
                "title": row.get("workflow_id") or row.get("opportunity_type"),
                "status": row.get("priority"),
                "summary": row.get("summary"),
                "source_table": "agency_reporting.seo_opportunity_queue",
                "source_id": row.get("source_ref_hash"),
            }
        )

    for row in payload.get("workflow_readiness", []):
        rows.append(
            {
                "event_date": event_date_text(row.get("generated_at")),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": "workflow_readiness",
                "title": row.get("recommended_workflow_id"),
                "status": row.get("readiness_status"),
                "summary": f"Recommended agent: {row.get('recommended_agent_id') or 'unknown'}",
                "source_table": "agency_reporting.seo_workflow_readiness",
                "source_id": row.get("source_ref_hash"),
            }
        )

    for row in payload.get("api_smoke_checks", []):
        rows.append(
            {
                "event_date": event_date_text(row.get("checked_at")),
                "client_slug": row.get("client_slug"),
                "client_name": row.get("client_name"),
                "event_type": "api_smoke_check",
                "title": f"{row.get('source')} API smoke check",
                "status": row.get("status"),
                "summary": f"{row.get('rows_returned') or 0} row(s) returned",
                "source_table": "agency_control.api_smoke_checks",
                "source_id": row.get("source"),
            }
        )

    filtered = [row for row in rows if row.get("client_slug") and row.get("event_date")]
    return sorted(filtered, key=lambda row: (str(row.get("event_date") or ""), str(row.get("event_type") or "")), reverse=True)[:800]


def overview_details(payload: dict[str, Any]) -> dict[str, Any]:
    health_assets = payload.get("health_assets", [])
    missing_assets = [row for row in health_assets if str(row.get("presence_status") or "").lower() != "present" and row.get("expected")]
    clients = payload.get("clients", [])
    roadmap_items = payload.get("roadmap_items", [])
    roadmaps = payload.get("roadmaps", [])
    roadmap_missing = [
        row
        for row in clients
        if not row.get("has_roadmap_items") or not row.get("has_roadmap_content_validated")
    ]
    report_missing = [row for row in clients if not row.get("has_monthly_report_snapshot")]
    performance_history = payload.get("performance_history", [])
    latest_months = sorted({str(row.get("period_id")) for row in performance_history if row.get("period_id")})
    clients_with_roadmap_items = sum(1 for row in clients if row.get("has_roadmap_items"))
    clients_with_validated_roadmaps = sum(1 for row in clients if row.get("has_roadmap_content_validated"))
    missing_evidence_items = sum(int(row.get("missing_evidence_items") or 0) for row in roadmaps)
    overdue_roadmap_items = sum(int(row.get("overdue_items") or 0) for row in roadmaps)
    return {
        "missing_assets_by_type": count_rows(missing_assets, "asset_type"),
        "roadmap_gap_clients": [row.get("client_slug") for row in roadmap_missing],
        "roadmap_coverage": {
            "clients_total": len(clients),
            "clients_with_items": clients_with_roadmap_items,
            "clients_with_validated_content": clients_with_validated_roadmaps,
            "current_items": len(roadmap_items),
            "monthly_rollups": len(roadmaps),
            "missing_evidence_items": missing_evidence_items,
            "overdue_items": overdue_roadmap_items,
        },
        "report_gap_clients": [row.get("client_slug") for row in report_missing],
        "performance_months": latest_months[-13:],
        "recent_agent_runs": sum(len(row.get("recent_runs", [])) for row in payload.get("agent_activity_summary", [])),
        "source_tables": payload.get("meta", {}).get("source_tables", []),
    }


def count_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return [{"name": name, "value": value} for name, value in sorted(counts.items())]


def normalize_client_key(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def active_client_maps(payload: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    active_slugs = {str(row.get("client_slug") or "") for row in payload.get("clients", []) if row.get("client_slug")}
    name_to_slug: dict[str, str] = {}
    for row in payload.get("clients", []):
        slug = str(row.get("client_slug") or "")
        if not slug:
            continue
        name_to_slug[normalize_client_key(slug)] = slug
        name_to_slug[normalize_client_key(row.get("client_name"))] = slug
    return active_slugs, name_to_slug


def active_task_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    active_slugs, _ = active_client_maps(payload)
    rows: list[dict[str, Any]] = []
    for row in payload.get(key, []):
        slug = canonical_client_slug(row.get("client_slug"))
        if slug not in active_slugs:
            continue
        next_row = dict(row)
        next_row["client_slug"] = slug
        rows.append(next_row)
    return rows


def active_client_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    active_slugs, _ = active_client_maps(payload)
    return [row for row in payload.get(key, []) if str(row.get("client_slug") or "") in active_slugs]


def active_ops_drift_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    _, name_to_slug = active_client_maps(payload)
    rows: list[dict[str, Any]] = []
    for row in payload.get("ops_drift", []):
        slug = str(row.get("client_slug") or "")
        if not slug:
            slug = name_to_slug.get(normalize_client_key(row.get("client_name") or row.get("client")))
        if not slug:
            continue
        next_row = dict(row)
        next_row["client_slug"] = slug
        rows.append(next_row)
    return rows


def build_task_ops(payload: dict[str, Any]) -> None:
    payload["task_client_detail"] = active_task_rows(payload, "task_client_detail")
    payload["task_status_by_client"] = active_task_rows(payload, "task_status_by_client")
    payload["ops_drift"] = active_ops_drift_rows(payload)
    for key in (
        "client_timeline",
        "report_narratives",
        "comms_history",
        "seo_opportunities",
        "workflow_readiness",
        "crawl_latest",
        "api_smoke_checks",
        "drive_evidence",
    ):
        payload[key] = active_client_rows(payload, key)
    payload["unified_timeline"] = active_client_rows(payload, "unified_timeline")

    distribution: dict[str, dict[str, Any]] = {}
    for row in payload.get("task_client_detail", []):
        status_label = str(row.get("status_label") or row.get("normalized_status") or row.get("status") or "Not Started")
        entry = distribution.setdefault(status_label, {"status_label": status_label, "task_count": 0, "overdue_tasks": 0})
        entry["task_count"] += 1
        if row.get("is_overdue"):
            entry["overdue_tasks"] += 1
    if distribution:
        payload["task_status_distribution"] = sorted(distribution.values(), key=lambda row: (-safe_int(row.get("task_count")), str(row.get("status_label"))))
    else:
        payload["task_status_distribution"] = payload.get("task_status_distribution", [])

    drift_totals = {
        "drift_issues": 0,
        "status_mismatches": 0,
        "owner_mismatches": 0,
        "due_date_mismatches": 0,
        "stale_client_updates": 0,
    }
    for row in payload.get("ops_drift", []):
        for key in drift_totals:
            drift_totals[key] += safe_int(row.get(key))

    summary = {
        "total_tasks": sum(safe_int(row.get("total_tasks")) for row in payload.get("task_status_by_client", [])),
        "open_tasks": sum(safe_int(row.get("open_tasks")) for row in payload.get("task_status_by_client", [])),
        "done_tasks": sum(safe_int(row.get("done_tasks")) for row in payload.get("task_status_by_client", [])),
        "overdue_tasks": sum(safe_int(row.get("overdue_tasks")) for row in payload.get("task_status_by_client", [])),
        "missing_owner_tasks": sum(safe_int(row.get("missing_owner_tasks")) for row in payload.get("task_status_by_client", [])),
        "missing_due_date_tasks": sum(safe_int(row.get("missing_due_date_tasks")) for row in payload.get("task_status_by_client", [])),
        **drift_totals,
    }
    payload["task_summary"] = summary


def build_client_details(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = {str(row.get("client_slug")): row for row in payload.get("client_profiles", [])}
    context_by_client = {str(row.get("client_slug")): row for row in payload.get("client_context", [])}
    sidecar_profiles = read_client_sidecar_profiles()
    assets_by_client = group_by_client(payload.get("health_assets", []))
    delivery_by_client = group_by_client(payload.get("delivery", []))
    performance_by_client = group_by_client(payload.get("performance_history", []))
    roadmap_by_client = group_by_client(payload.get("roadmap_items", []))
    reports_by_client = group_by_client(payload.get("report_links", []))
    narratives_by_client = group_by_client(payload.get("report_narratives", []))
    timeline_by_client = group_by_client(payload.get("unified_timeline", []))
    comms_by_client = group_by_client(payload.get("comms", []))
    comms_history_by_client = group_by_client(payload.get("comms_history", []))
    agents_by_client = group_by_client(payload.get("agent_work_completed", []))
    drive_by_client = group_by_client(payload.get("drive_evidence", []))
    opportunities_by_client = group_by_client(payload.get("seo_opportunities", []))
    readiness_by_client = group_by_client(payload.get("workflow_readiness", []))
    crawls_by_client = group_by_client(payload.get("crawl_latest", []))
    api_smoke_by_client = group_by_client(payload.get("api_smoke_checks", []))
    reporting_by_client = {str(row.get("client_slug")): row for row in payload.get("reporting", [])}
    details: dict[str, dict[str, Any]] = {}
    for client in payload.get("clients", []):
        slug = str(client.get("client_slug") or "")
        if not slug:
            continue
        registry = profiles.get(slug, {})
        sidecar = sidecar_profiles.get(slug, {})
        health_assets = assets_by_client.get(slug, [])
        missing_assets = [
            row for row in health_assets if row.get("expected") and str(row.get("presence_status") or "").lower() != "present"
        ]
        details[slug] = {
            "profile": {
                "client_slug": slug,
                "client_name": client.get("client_name") or registry.get("client_name"),
                "favicon_url": registry.get("favicon_url") or client.get("favicon_url"),
                "favicon_source": registry.get("favicon_source") or client.get("favicon_source"),
                "favicon_candidates_json": registry.get("favicon_candidates_json") or client.get("favicon_candidates_json"),
                "abn": sidecar.get("abn") or registry.get("abn"),
                "primary_contact_name": sidecar.get("primary_contact_name") or registry.get("primary_contact_name"),
                "primary_contact_role": sidecar.get("primary_contact_role") or registry.get("primary_contact_role"),
                "canonical_host": registry.get("canonical_host") or sidecar.get("domain"),
                "monday_board_id": registry.get("monday_board_id"),
                "monday_board_url": sidecar.get("monday_board_url"),
                "ga4_property": registry.get("ga4_property"),
                "se_ranking_project_id": registry.get("se_ranking_project_id"),
                "drive_client_folder_id": sidecar.get("drive_client_folder_id"),
                "drive_roadmap_folder_id": sidecar.get("drive_roadmap_folder_id"),
                "drive_reports_folder_id": sidecar.get("drive_reports_folder_id"),
                "source": "agency_memory.client_registry + approved SEO Automation sidecar metadata",
            },
            "context": context_by_client.get(slug),
            "health": client,
            "missing_required": missing_asset_labels(client, "missing_required_json"),
            "missing_optional": missing_asset_labels(client, "missing_optional_json"),
            "missing_assets": missing_assets,
            "health_assets": health_assets,
            "reporting": reporting_by_client.get(slug),
            "reports": reports_by_client.get(slug, []),
            "report_narratives": narratives_by_client.get(slug, []),
            "roadmaps": roadmap_by_client.get(slug, []),
            "roadmap_missing": not client.get("has_roadmap_items"),
            "roadmap_evidence_missing": not client.get("has_roadmap_content_validated"),
            "performance_history": performance_by_client.get(slug, []),
            "delivery": delivery_by_client.get(slug, []),
            "comms": comms_by_client.get(slug, []),
            "comms_history": comms_history_by_client.get(slug, []),
            "timeline": timeline_by_client.get(slug, []),
            "agent_work": agents_by_client.get(slug, []),
            "drive_evidence": drive_by_client.get(slug, []),
            "seo_opportunities": opportunities_by_client.get(slug, []),
            "workflow_readiness": readiness_by_client.get(slug, []),
            "crawl_latest": crawls_by_client.get(slug, []),
            "api_smoke_checks": api_smoke_by_client.get(slug, []),
        }
    return details


def enrich_clients_with_registry(payload: dict[str, Any]) -> None:
    profiles = {str(row.get("client_slug")): row for row in payload.get("client_profiles", [])}
    for key in (
        "clients",
        "needs_attention",
        "delivery",
        "task_status_by_client",
        "task_client_detail",
        "ops_drift",
        "performance",
        "performance_history",
        "comms",
        "roadmaps",
        "roadmap_items",
        "reporting",
        "report_links",
        "client_timeline",
        "report_narratives",
        "comms_history",
        "seo_opportunities",
        "workflow_readiness",
        "crawl_latest",
        "api_smoke_checks",
        "agent_work_completed",
        "unified_timeline",
    ):
        for client in payload.get(key, []):
            profile = profiles.get(str(client.get("client_slug") or ""))
            if not profile:
                continue
            if profile.get("client_name") and not client.get("client_name"):
                client["client_name"] = profile["client_name"]
            for field in ("favicon_url", "favicon_source", "favicon_candidates_json", "canonical_host"):
                if profile.get(field) and not client.get(field):
                    client[field] = profile[field]

    for client in payload.get("clients", []):
        profile = profiles.get(str(client.get("client_slug") or ""))
        if not profile:
            continue
        for key in ("favicon_url", "favicon_source", "favicon_candidates_json", "canonical_host"):
            if profile.get(key) and not client.get(key):
                client[key] = profile[key]


def is_excluded_client_row(row: dict[str, Any]) -> bool:
    slug = canonical_client_slug(row.get("client_slug"))
    if slug in EXCLUDED_CLIENT_SLUGS:
        return True
    haystack = " ".join(
        str(row.get(key) or "").lower()
        for key in ("client", "client_name", "item_name", "summary", "recommended_action")
    )
    return any(fragment in haystack for fragment in EXCLUDED_CLIENT_NAME_FRAGMENTS)


def filter_excluded_clients(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not is_excluded_client_row(row)]


def live_payload(load_env: bool = True) -> dict[str, Any]:
    if load_env:
        load_env_file(DEFAULT_ENV_PATH)
    from google.cloud import bigquery

    config = BigQueryCostConfig.from_file(DEFAULT_CONFIG_PATH)
    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    definitions = query_definitions(config)
    payload: dict[str, Any] = {
        "meta": {
            "generated_at": utc_now(),
            "environment": config.project_id,
            "data_source_status": "live",
            "source_tables": [
                "agency_reporting.client_health_check",
                "agency_memory.client_registry",
                "agency_memory.client_onboarding_profiles",
                "agency_memory.client_health_assets",
                "agency_reporting.reporting_readiness",
                "agency_reporting.client_task_status",
                "agency_reporting.ops_drift_summary",
                "agency_reporting.client_monthly_comparison",
                "agency_reporting.client_monthly_performance_history",
                "agency_reporting.client_benchmark_summary",
                "agency_reporting.client_comms_attention",
                "agency_reporting.client_roadmap_current",
                "agency_reporting.client_roadmap_monthly_completion",
                "agency_reporting.client_monthly_reporting_coverage",
                "agency_memory.monthly_report_snapshots",
                "agency_control.agent_run_log",
                "agency_memory.seo_workflow_run_summaries",
                "agency_reporting.client_delivery_timeline",
                "agency_reporting.client_monthly_report_narrative",
                "agency_reporting.client_comms_history",
                "agency_reporting.seo_opportunity_queue",
                "agency_reporting.seo_workflow_readiness",
                "agency_reporting.client_crawl_latest",
                "agency_control.api_smoke_checks",
                "data/client_health/drive_folder_verifications.json",
                "agency_control.ingestion_runs",
                "agency_control.cost_checks",
                "data/agent_runs/index.json",
            ],
        },
        "agents": read_agent_index(),
    }
    optional_keys = {"agent_run_log", "workflow_runs", "client_context"}
    for key, sql in definitions.items():
        try:
            _, rows = runner.run_query(sql, purpose=f"agency-health-dashboard: read {key}")
        except Exception as exc:
            if key not in optional_keys:
                raise
            payload[key] = []
            payload.setdefault("meta", {}).setdefault("optional_query_errors", {})[key] = type(exc).__name__
            continue
        data = [dict(row) for row in rows]
        if key == "data_health_ingestion":
            payload.setdefault("data_health", {})["ingestion_runs"] = data
        elif key == "data_health_cost":
            payload.setdefault("data_health", {})["cost_checks"] = data
        else:
            payload[key] = filter_excluded_clients(data)
    data_health = payload.setdefault("data_health", {})
    data_health["cost_failures"] = sum(1 for row in data_health.get("cost_checks", []) if str(row.get("status")).lower() not in {"succeeded", "success", "ok"})
    data_health["ingestion_failures"] = sum(1 for row in data_health.get("ingestion_runs", []) if str(row.get("status")).lower() not in {"succeeded", "success", "ok"})
    data_health["stale_tables"] = sum(1 for row in payload.get("clients", []) if not row.get("snapshot_date"))
    data_health["agent_failures"] = sum(1 for row in payload.get("agents", []) if str(row.get("status")).lower() in {"failed", "error"})
    payload["agent_activity_summary"] = summarize_agent_activity(
        payload.get("agents", []),
        payload.get("agent_run_log", []),
        payload.get("workflow_runs", []),
    )
    payload["agent_work_completed"] = completed_agent_work_rows(payload["agent_activity_summary"])
    payload["drive_evidence"] = filter_excluded_clients(read_drive_evidence())
    enrich_report_links(payload)
    enrich_clients_with_registry(payload)
    payload["unified_timeline"] = filter_excluded_clients(unified_timeline_rows(payload))
    build_task_ops(payload)
    payload["client_details"] = build_client_details(payload)
    payload["overview_details"] = overview_details(payload)
    return payload


def dashboard_payload(*, force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    cached = _DASHBOARD_CACHE.get("payload")
    if not force_refresh and cached and now - float(_DASHBOARD_CACHE.get("created_at") or 0) < CACHE_TTL_SECONDS:
        return cached
    with _CACHE_LOCK:
        now = time.time()
        cached = _DASHBOARD_CACHE.get("payload")
        if not force_refresh and cached and now - float(_DASHBOARD_CACHE.get("created_at") or 0) < CACHE_TTL_SECONDS:
            return cached
        payload = live_payload()
        payload["overview"] = overall_health(payload)
        payload["needs_attention"] = needs_attention(payload)
        payload["meta"]["cache_ttl_seconds"] = CACHE_TTL_SECONDS
        payload["meta"]["cached_at"] = utc_now()
        _DASHBOARD_CACHE["payload"] = payload
        _DASHBOARD_CACHE["created_at"] = time.time()
        return payload


def needs_attention(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    active_slugs = {str(row.get("client_slug") or "") for row in payload.get("clients", []) if row.get("client_slug")}
    for row in payload.get("clients", []):
        if str(row.get("health_status") or "").lower() in {"critical_missing", "needs_attention", "partial", "red", "amber"}:
            items.append({"area": "Client health", "client_slug": row.get("client_slug"), "severity": "high" if row.get("health_status") == "critical_missing" else "medium", "summary": f"{row.get('client_name') or row.get('client_slug')} health is {row.get('health_status')}", "source": "agency_reporting.client_health_check"})
    for row in payload.get("delivery", [])[:30]:
        if row.get("is_overdue") or row.get("owner_missing"):
            items.append({"area": "Delivery", "client_slug": row.get("client_slug"), "severity": "high" if row.get("is_overdue") else "medium", "summary": row.get("item_name") or "Delivery item needs attention", "source": "agency_reporting.client_task_status"})
    for row in payload.get("comms", []):
        if str(row.get("severity") or "").lower() in {"high", "medium"}:
            items.append({"area": "Comms", "client_slug": row.get("client_slug"), "severity": row.get("severity"), "summary": row.get("summary"), "source": "agency_reporting.client_comms_attention"})
    for row in payload.get("drive_evidence", []):
        if row.get("folder_role") == "drive_roadmap_folder" and str(row.get("content_validation_status") or "").lower() not in {"present", "valid"}:
            items.append({"area": "Drive evidence", "client_slug": row.get("client_slug"), "severity": "high", "summary": "Roadmap folder lacks populated validated roadmap metadata", "source": "data/client_health/drive_folder_verifications.json"})
    for row in payload.get("seo_opportunities", []):
        items.append({"area": "SEO opportunity", "client_slug": row.get("client_slug"), "severity": row.get("priority") or "medium", "summary": row.get("summary"), "source": "agency_reporting.seo_opportunity_queue"})
    for row in payload.get("workflow_readiness", []):
        status = str(row.get("readiness_status") or "").lower()
        if status in {"blocked", "needs_attention", "partial"}:
            items.append({"area": "Workflow readiness", "client_slug": row.get("client_slug"), "severity": "high" if status == "blocked" else "medium", "summary": f"{row.get('recommended_workflow_id') or 'Workflow'} is {row.get('readiness_status')}", "source": "agency_reporting.seo_workflow_readiness"})
    crawled_slugs = {str(row.get("client_slug") or "") for row in payload.get("crawl_latest", []) if row.get("client_slug")}
    for slug in sorted(active_slugs - crawled_slugs):
        items.append({"area": "Technical crawl", "client_slug": slug, "severity": "low", "summary": "No latest crawl summary row is available yet", "source": "agency_reporting.client_crawl_latest"})
    for row in payload.get("api_smoke_checks", []):
        if str(row.get("status") or "").lower() not in {"succeeded", "success", "ok"}:
            items.append({"area": "API smoke", "client_slug": row.get("client_slug"), "severity": "high", "summary": f"{row.get('source')} smoke check is {row.get('status')}", "source": "agency_control.api_smoke_checks"})
    severity_rank = {"high": 0, "critical": 0, "medium": 1, "warning": 1, "low": 2}
    return sorted(items, key=lambda item: (severity_rank.get(str(item.get("severity") or "").lower(), 3), str(item.get("area") or ""), str(item.get("client_slug") or "")))[:40]
