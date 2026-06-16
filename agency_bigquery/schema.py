from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .cost_config import BigQueryCostConfig


SchemaTuple = tuple[str, str, str]


@dataclass(frozen=True)
class TableSpec:
    dataset: str
    table: str
    schema: list[SchemaTuple]
    partition_field: str | None = None
    cluster_fields: tuple[str, ...] = ()
    expires_in_hours: int | None = None

    @property
    def schema_by_name(self) -> dict[str, tuple[str, str]]:
        return {name: (field_type, mode) for name, field_type, mode in self.schema}


COST_CHECKS_SCHEMA = [
    ("logged_at", "TIMESTAMP", "REQUIRED"),
    ("query_id", "STRING", "REQUIRED"),
    ("purpose", "STRING", "REQUIRED"),
    ("status", "STRING", "REQUIRED"),
    ("estimated_bytes", "INT64", "REQUIRED"),
    ("cap_bytes", "INT64", "REQUIRED"),
    ("estimated_human", "STRING", "REQUIRED"),
    ("cap_human", "STRING", "REQUIRED"),
    ("job_id", "STRING", "NULLABLE"),
    ("admin_cap_10gb", "BOOL", "REQUIRED"),
    ("location", "STRING", "REQUIRED"),
    ("error_class", "STRING", "NULLABLE"),
    ("error_message", "STRING", "NULLABLE"),
]


DATA_SOURCES_SCHEMA: list[SchemaTuple] = [
    ("source_id", "STRING", "REQUIRED"),
    ("source_name", "STRING", "REQUIRED"),
    ("source_type", "STRING", "REQUIRED"),
    ("source_path", "STRING", "REQUIRED"),
    ("refresh_cadence", "STRING", "REQUIRED"),
    ("risk_level", "STRING", "REQUIRED"),
    ("owner", "STRING", "REQUIRED"),
    ("notes", "STRING", "NULLABLE"),
    ("registered_at", "TIMESTAMP", "REQUIRED"),
]


INGESTION_RUNS_SCHEMA: list[SchemaTuple] = [
    ("run_id", "STRING", "REQUIRED"),
    ("source_id", "STRING", "REQUIRED"),
    ("started_at", "TIMESTAMP", "REQUIRED"),
    ("completed_at", "TIMESTAMP", "NULLABLE"),
    ("status", "STRING", "REQUIRED"),
    ("source_path", "STRING", "REQUIRED"),
    ("destination_table", "STRING", "REQUIRED"),
    ("rows_loaded", "INT64", "REQUIRED"),
    ("error_message", "STRING", "NULLABLE"),
]


API_SMOKE_CHECKS_SCHEMA: list[SchemaTuple] = [
    ("checked_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("source", "STRING", "REQUIRED"),
    ("status", "STRING", "REQUIRED"),
    ("date_start", "DATE", "NULLABLE"),
    ("date_end", "DATE", "NULLABLE"),
    ("rows_returned", "INT64", "NULLABLE"),
    ("error_class", "STRING", "NULLABLE"),
    ("error_message", "STRING", "NULLABLE"),
]


STAGING_RECORDS_SCHEMA: list[SchemaTuple] = [
    ("run_id", "STRING", "REQUIRED"),
    ("source_id", "STRING", "REQUIRED"),
    ("source_path", "STRING", "REQUIRED"),
    ("record_type", "STRING", "REQUIRED"),
    ("record_id", "STRING", "REQUIRED"),
    ("snapshot_date", "DATE", "NULLABLE"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("payload_json", "JSON", "REQUIRED"),
]


MONDAY_BOARDS_SCHEMA: list[SchemaTuple] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("board_id", "STRING", "REQUIRED"),
    ("board_name", "STRING", "REQUIRED"),
    ("role", "STRING", "NULLABLE"),
    ("role_label", "STRING", "NULLABLE"),
    ("board_kind", "STRING", "NULLABLE"),
    ("permissions", "STRING", "NULLABLE"),
    ("state", "STRING", "NULLABLE"),
    ("items_count", "INT64", "NULLABLE"),
    ("group_count", "INT64", "NULLABLE"),
    ("column_count", "INT64", "NULLABLE"),
    ("group_titles", "STRING", "NULLABLE"),
    ("column_titles", "STRING", "NULLABLE"),
    ("board_family", "STRING", "NULLABLE"),
    ("alias_risk", "STRING", "NULLABLE"),
]


MONDAY_BOARD_COLUMNS_SCHEMA: list[SchemaTuple] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("board_id", "STRING", "REQUIRED"),
    ("board_name", "STRING", "REQUIRED"),
    ("column_id", "STRING", "REQUIRED"),
    ("column_title", "STRING", "REQUIRED"),
    ("column_type", "STRING", "REQUIRED"),
    ("settings_json", "JSON", "NULLABLE"),
    ("revision", "STRING", "NULLABLE"),
    ("is_subitem", "BOOL", "REQUIRED"),
]


MONDAY_STATUS_LABELS_SCHEMA: list[SchemaTuple] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("board_id", "STRING", "REQUIRED"),
    ("board_name", "STRING", "REQUIRED"),
    ("column_id", "STRING", "REQUIRED"),
    ("column_title", "STRING", "REQUIRED"),
    ("label_id", "STRING", "REQUIRED"),
    ("label_index", "INT64", "NULLABLE"),
    ("label", "STRING", "REQUIRED"),
    ("color", "STRING", "NULLABLE"),
    ("hex", "STRING", "NULLABLE"),
    ("is_done", "BOOL", "NULLABLE"),
    ("is_deactivated", "BOOL", "NULLABLE"),
    ("is_subitem", "BOOL", "REQUIRED"),
]


MONDAY_ITEMS_SCHEMA: list[SchemaTuple] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("board_id", "STRING", "REQUIRED"),
    ("board_name", "STRING", "REQUIRED"),
    ("item_id", "STRING", "REQUIRED"),
    ("item_name", "STRING", "REQUIRED"),
    ("group_id", "STRING", "NULLABLE"),
    ("group_title", "STRING", "NULLABLE"),
    ("updated_at", "TIMESTAMP", "NULLABLE"),
    ("parent_item_id", "STRING", "NULLABLE"),
    ("is_subitem", "BOOL", "REQUIRED"),
    ("client_slug", "STRING", "NULLABLE"),
    ("status", "STRING", "NULLABLE"),
    ("normalized_status", "STRING", "REQUIRED"),
    ("owner", "STRING", "NULLABLE"),
    ("due_date", "DATE", "NULLABLE"),
    ("date_value", "DATE", "NULLABLE"),
    ("files_present", "BOOL", "REQUIRED"),
    ("notes_present", "BOOL", "REQUIRED"),
]


MONDAY_ITEM_COLUMN_VALUES_SCHEMA: list[SchemaTuple] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("board_id", "STRING", "REQUIRED"),
    ("item_id", "STRING", "REQUIRED"),
    ("column_id", "STRING", "REQUIRED"),
    ("column_title", "STRING", "NULLABLE"),
    ("column_type", "STRING", "NULLABLE"),
    ("text_value", "STRING", "NULLABLE"),
    ("is_subitem", "BOOL", "REQUIRED"),
]


CLIENT_REGISTRY_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("abn", "STRING", "NULLABLE"),
    ("primary_contact_name", "STRING", "NULLABLE"),
    ("primary_contact_role", "STRING", "NULLABLE"),
    ("canonical_host", "STRING", "NULLABLE"),
    ("website_hosts_json", "JSON", "NULLABLE"),
    ("favicon_url", "STRING", "NULLABLE"),
    ("favicon_source", "STRING", "NULLABLE"),
    ("favicon_candidates_json", "JSON", "NULLABLE"),
    ("ga4_property", "STRING", "NULLABLE"),
    ("search_console_json", "JSON", "NULLABLE"),
    ("se_ranking_project_id", "STRING", "NULLABLE"),
    ("monday_board_id", "STRING", "NULLABLE"),
    ("reporting_template", "STRING", "NULLABLE"),
    ("source_paths_json", "JSON", "NULLABLE"),
    ("status", "STRING", "NULLABLE"),
]


CLIENT_ONBOARDING_PROFILES_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("business_summary", "STRING", "NULLABLE"),
    ("primary_goals_json", "JSON", "NULLABLE"),
    ("seo_priorities_json", "JSON", "NULLABLE"),
    ("target_audience", "STRING", "NULLABLE"),
    ("key_products_or_services_json", "JSON", "NULLABLE"),
    ("important_pages_json", "JSON", "NULLABLE"),
    ("brand_tone", "STRING", "NULLABLE"),
    ("competitors_json", "JSON", "NULLABLE"),
    ("constraints_or_risks_json", "JSON", "NULLABLE"),
    ("approval_preferences", "STRING", "NULLABLE"),
    ("reporting_expectations", "STRING", "NULLABLE"),
    ("agent_context_summary", "STRING", "NULLABLE"),
    ("source_drive_file_id", "STRING", "NULLABLE"),
    ("source_drive_file_name", "STRING", "NULLABLE"),
    ("source_modified_at", "TIMESTAMP", "NULLABLE"),
    ("review_status", "STRING", "REQUIRED"),
    ("confidence", "FLOAT", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("validation_status", "STRING", "REQUIRED"),
]


CLIENT_BOARD_MAP_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("client_board_id", "STRING", "NULLABLE"),
    ("client_board_name", "STRING", "NULLABLE"),
    ("board_kind", "STRING", "NULLABLE"),
    ("permissions", "STRING", "NULLABLE"),
    ("seo_execution_board_id", "STRING", "NULLABLE"),
    ("seo_execution_board_name", "STRING", "NULLABLE"),
    ("notes", "STRING", "NULLABLE"),
]


TASK_ALIGNMENT_SCHEMA: list[SchemaTuple] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client", "STRING", "NULLABLE"),
    ("seo_task_item_id", "STRING", "NULLABLE"),
    ("seo_task_name", "STRING", "NULLABLE"),
    ("seo_status", "STRING", "NULLABLE"),
    ("seo_owner", "STRING", "NULLABLE"),
    ("seo_due_date", "DATE", "NULLABLE"),
    ("client_board_id", "STRING", "NULLABLE"),
    ("client_board_name", "STRING", "NULLABLE"),
    ("client_task_item_id", "STRING", "NULLABLE"),
    ("client_task_name", "STRING", "NULLABLE"),
    ("client_status", "STRING", "NULLABLE"),
    ("client_owner", "STRING", "NULLABLE"),
    ("client_due_date", "DATE", "NULLABLE"),
    ("status_match", "BOOL", "NULLABLE"),
    ("owner_match", "BOOL", "NULLABLE"),
    ("due_date_match", "BOOL", "NULLABLE"),
    ("stale_client_update", "BOOL", "NULLABLE"),
    ("mismatch_reason", "STRING", "NULLABLE"),
]


CLIENT_TIMELINE_EVENTS_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("event_date", "DATE", "REQUIRED"),
    ("task", "STRING", "NULLABLE"),
    ("request_source", "STRING", "NULLABLE"),
    ("evidence_checked", "STRING", "NULLABLE"),
    ("outputs", "STRING", "NULLABLE"),
    ("decisions", "STRING", "NULLABLE"),
    ("caveats", "STRING", "NULLABLE"),
    ("next_action", "STRING", "NULLABLE"),
    ("proof_summary", "STRING", "NULLABLE"),
    ("source_path", "STRING", "REQUIRED"),
    ("row_index", "INT64", "REQUIRED"),
]


MONTHLY_REPORT_SNAPSHOTS_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("period_id", "STRING", "REQUIRED"),
    ("report_month", "DATE", "NULLABLE"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("share_id", "STRING", "NULLABLE"),
    ("report_path", "STRING", "REQUIRED"),
    ("generated_at", "TIMESTAMP", "NULLABLE"),
    ("schema_version", "INT64", "NULLABLE"),
    ("template", "STRING", "NULLABLE"),
    ("headline_metrics_json", "JSON", "NULLABLE"),
    ("commentary_json", "JSON", "NULLABLE"),
    ("source_caveats_json", "JSON", "NULLABLE"),
    ("raw_report_json", "JSON", "REQUIRED"),
]


CLIENT_MONTHLY_API_SNAPSHOTS_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("month_end", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("ga4_property", "STRING", "NULLABLE"),
    ("gsc_site_url", "STRING", "NULLABLE"),
    ("se_ranking_project_id", "STRING", "NULLABLE"),
    ("se_ranking_engine_id", "STRING", "NULLABLE"),
    ("ga4_status", "STRING", "REQUIRED"),
    ("gsc_status", "STRING", "REQUIRED"),
    ("se_ranking_status", "STRING", "REQUIRED"),
    ("organic_sessions", "FLOAT64", "NULLABLE"),
    ("organic_users", "FLOAT64", "NULLABLE"),
    ("engaged_sessions", "FLOAT64", "NULLABLE"),
    ("organic_purchases", "FLOAT64", "NULLABLE"),
    ("organic_revenue", "FLOAT64", "NULLABLE"),
    ("organic_conversion_rate", "FLOAT64", "NULLABLE"),
    ("organic_aov", "FLOAT64", "NULLABLE"),
    ("ai_sessions", "FLOAT64", "NULLABLE"),
    ("ai_users", "FLOAT64", "NULLABLE"),
    ("ai_revenue", "FLOAT64", "NULLABLE"),
    ("ai_blog_sessions", "FLOAT64", "NULLABLE"),
    ("gsc_clicks", "FLOAT64", "NULLABLE"),
    ("gsc_impressions", "FLOAT64", "NULLABLE"),
    ("gsc_ctr", "FLOAT64", "NULLABLE"),
    ("gsc_avg_position", "FLOAT64", "NULLABLE"),
    ("se_visibility_start", "FLOAT64", "NULLABLE"),
    ("se_visibility_end", "FLOAT64", "NULLABLE"),
    ("se_visibility_delta", "FLOAT64", "NULLABLE"),
    ("se_top10_start", "FLOAT64", "NULLABLE"),
    ("se_top10_end", "FLOAT64", "NULLABLE"),
    ("se_top10_delta", "FLOAT64", "NULLABLE"),
    ("se_avg_position_start", "FLOAT64", "NULLABLE"),
    ("se_avg_position_end", "FLOAT64", "NULLABLE"),
    ("se_avg_position_delta", "FLOAT64", "NULLABLE"),
    ("ga4_rows_returned", "INT64", "NULLABLE"),
    ("gsc_rows_returned", "INT64", "NULLABLE"),
    ("se_ranking_rows_returned", "INT64", "NULLABLE"),
    ("ga4_error", "STRING", "NULLABLE"),
    ("gsc_error", "STRING", "NULLABLE"),
    ("se_ranking_error", "STRING", "NULLABLE"),
]


CLIENT_FINANCE_MONTHLY_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("source_id", "STRING", "REQUIRED"),
    ("source_path", "STRING", "REQUIRED"),
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_label", "STRING", "REQUIRED"),
    ("billing_status", "STRING", "REQUIRED"),
    ("retainer_amount_aud", "FLOAT64", "REQUIRED"),
    ("expense_amount_aud", "FLOAT64", "REQUIRED"),
    ("net_amount_aud", "FLOAT64", "REQUIRED"),
    ("is_billable", "BOOL", "REQUIRED"),
    ("is_due", "BOOL", "REQUIRED"),
    ("is_paid", "BOOL", "REQUIRED"),
    ("is_issued", "BOOL", "REQUIRED"),
    ("notes", "STRING", "NULLABLE"),
]


AGENCY_EXPENSES_MONTHLY_SCHEMA: list[SchemaTuple] = [
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("source_id", "STRING", "REQUIRED"),
    ("source_path", "STRING", "REQUIRED"),
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("expense_item_id", "STRING", "REQUIRED"),
    ("expense_name", "STRING", "REQUIRED"),
    ("cost_per_month_aud", "FLOAT64", "REQUIRED"),
    ("start_date", "DATE", "NULLABLE"),
    ("renewal_date", "DATE", "NULLABLE"),
    ("invoicing_schedule_date", "DATE", "NULLABLE"),
    ("invoice_agreement", "STRING", "NULLABLE"),
    ("is_active", "BOOL", "REQUIRED"),
]


CLIENT_COMMS_DIGEST_RUNS_SCHEMA: list[SchemaTuple] = [
    ("run_id", "STRING", "REQUIRED"),
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("loaded_at", "TIMESTAMP", "NULLABLE"),
    ("week_start", "DATE", "REQUIRED"),
    ("week_end", "DATE", "REQUIRED"),
    ("channels_json", "JSON", "REQUIRED"),
    ("summarizer_agent", "STRING", "NULLABLE"),
    ("summarizer_model", "STRING", "NULLABLE"),
    ("status", "STRING", "REQUIRED"),
    ("source_event_count", "INT64", "REQUIRED"),
    ("summary_rows", "INT64", "REQUIRED"),
    ("rejected_rows", "INT64", "REQUIRED"),
    ("validation_errors_json", "JSON", "NULLABLE"),
    ("staging_path", "STRING", "NULLABLE"),
    ("retention_months", "INT64", "REQUIRED"),
]


CLIENT_COMMS_WEEKLY_SUMMARIES_SCHEMA: list[SchemaTuple] = [
    ("run_id", "STRING", "REQUIRED"),
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("week_start", "DATE", "REQUIRED"),
    ("week_end", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("channel", "STRING", "REQUIRED"),
    ("category", "STRING", "REQUIRED"),
    ("summary", "STRING", "REQUIRED"),
    ("recommended_action", "STRING", "NULLABLE"),
    ("owner_hint", "STRING", "NULLABLE"),
    ("due_hint", "STRING", "NULLABLE"),
    ("needs_reply", "BOOL", "REQUIRED"),
    ("blocked", "BOOL", "REQUIRED"),
    ("waiting_on_client", "BOOL", "REQUIRED"),
    ("waiting_on_us", "BOOL", "REQUIRED"),
    ("stale_followup", "BOOL", "REQUIRED"),
    ("urgency", "STRING", "REQUIRED"),
    ("sentiment", "STRING", "NULLABLE"),
    ("source_event_count", "INT64", "REQUIRED"),
    ("source_ref_hashes_json", "JSON", "NULLABLE"),
    ("thread_ref_hash", "STRING", "NULLABLE"),
    ("thread_status", "STRING", "NULLABLE"),
    ("latest_event_at", "TIMESTAMP", "NULLABLE"),
    ("resolved_at", "TIMESTAMP", "NULLABLE"),
    ("resolution_summary", "STRING", "NULLABLE"),
    ("summarizer_model", "STRING", "NULLABLE"),
    ("confidence", "FLOAT64", "REQUIRED"),
    ("validation_status", "STRING", "REQUIRED"),
]


CLIENT_ROADMAP_SOURCES_SCHEMA: list[SchemaTuple] = [
    ("run_id", "STRING", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("source_type", "STRING", "REQUIRED"),
    ("source_title", "STRING", "NULLABLE"),
    ("source_path", "STRING", "NULLABLE"),
    ("drive_file_id", "STRING", "NULLABLE"),
    ("drive_folder_id", "STRING", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("period_id", "STRING", "NULLABLE"),
    ("source_status", "STRING", "REQUIRED"),
    ("notes_summary", "STRING", "NULLABLE"),
]


CLIENT_ROADMAP_ITEMS_SCHEMA: list[SchemaTuple] = [
    ("run_id", "STRING", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("period_id", "STRING", "REQUIRED"),
    ("planned_month", "DATE", "REQUIRED"),
    ("roadmap_item_id", "STRING", "REQUIRED"),
    ("item_title", "STRING", "REQUIRED"),
    ("work_type", "STRING", "REQUIRED"),
    ("priority", "STRING", "REQUIRED"),
    ("planned_status", "STRING", "REQUIRED"),
    ("owner_hint", "STRING", "NULLABLE"),
    ("due_date", "DATE", "NULLABLE"),
    ("target_url", "STRING", "NULLABLE"),
    ("keyword_theme", "STRING", "NULLABLE"),
    ("notes_summary", "STRING", "NULLABLE"),
    ("source_type", "STRING", "REQUIRED"),
    ("source_title", "STRING", "NULLABLE"),
    ("source_path", "STRING", "NULLABLE"),
    ("drive_file_id", "STRING", "NULLABLE"),
    ("drive_folder_id", "STRING", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("source_row_index", "INT64", "NULLABLE"),
    ("completion_evidence_type", "STRING", "NULLABLE"),
    ("completion_evidence_ref", "STRING", "NULLABLE"),
    ("completion_summary", "STRING", "NULLABLE"),
    ("completion_confidence", "FLOAT64", "REQUIRED"),
    ("validation_status", "STRING", "REQUIRED"),
]


CLIENT_HEALTH_ASSETS_SCHEMA: list[SchemaTuple] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("asset_type", "STRING", "REQUIRED"),
    ("asset_label", "STRING", "REQUIRED"),
    ("presence_status", "STRING", "REQUIRED"),
    ("expected", "BOOL", "REQUIRED"),
    ("criticality", "STRING", "REQUIRED"),
    ("source_system", "STRING", "REQUIRED"),
    ("source_path", "STRING", "NULLABLE"),
    ("source_ref", "STRING", "NULLABLE"),
    ("source_ref_hash", "STRING", "NULLABLE"),
    ("freshness_date", "DATE", "NULLABLE"),
    ("verification_level", "STRING", "NULLABLE"),
    ("verified_at", "TIMESTAMP", "NULLABLE"),
    ("verification_method", "STRING", "NULLABLE"),
    ("notes", "STRING", "NULLABLE"),
]


CLIENT_CRAWL_RUNS_SCHEMA: list[SchemaTuple] = [
    ("crawl_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("crawl_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("crawl_trigger", "STRING", "REQUIRED"),
    ("trigger_ref", "STRING", "NULLABLE"),
    ("crawler", "STRING", "REQUIRED"),
    ("crawl_scope", "STRING", "REQUIRED"),
    ("start_url", "STRING", "REQUIRED"),
    ("config_ref", "STRING", "NULLABLE"),
    ("robots_respected", "BOOL", "REQUIRED"),
    ("crawl_status", "STRING", "REQUIRED"),
    ("pages_crawled", "INT64", "NULLABLE"),
    ("internal_html_urls", "INT64", "NULLABLE"),
    ("indexable_html_urls", "INT64", "NULLABLE"),
    ("nonindexable_html_urls", "INT64", "NULLABLE"),
    ("status_2xx_urls", "INT64", "NULLABLE"),
    ("status_3xx_urls", "INT64", "NULLABLE"),
    ("status_4xx_urls", "INT64", "NULLABLE"),
    ("status_5xx_urls", "INT64", "NULLABLE"),
    ("missing_title_urls", "INT64", "NULLABLE"),
    ("duplicate_title_urls", "INT64", "NULLABLE"),
    ("missing_meta_description_urls", "INT64", "NULLABLE"),
    ("duplicate_meta_description_urls", "INT64", "NULLABLE"),
    ("missing_h1_urls", "INT64", "NULLABLE"),
    ("duplicate_h1_urls", "INT64", "NULLABLE"),
    ("canonical_issue_urls", "INT64", "NULLABLE"),
    ("low_content_urls", "INT64", "NULLABLE"),
    ("issue_counts_json", "JSON", "NULLABLE"),
    ("export_manifest_path", "STRING", "NULLABLE"),
    ("export_drive_file_id", "STRING", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("retention_expires_on", "DATE", "REQUIRED"),
]


CLIENT_CRAWL_URL_SNAPSHOTS_SCHEMA: list[SchemaTuple] = [
    ("crawl_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("crawl_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("url", "STRING", "REQUIRED"),
    ("url_hash", "STRING", "REQUIRED"),
    ("normalized_url", "STRING", "NULLABLE"),
    ("status_code", "INT64", "NULLABLE"),
    ("content_type", "STRING", "NULLABLE"),
    ("indexability", "STRING", "NULLABLE"),
    ("indexability_status", "STRING", "NULLABLE"),
    ("title", "STRING", "NULLABLE"),
    ("title_length", "INT64", "NULLABLE"),
    ("meta_description_length", "INT64", "NULLABLE"),
    ("h1_count", "INT64", "NULLABLE"),
    ("word_count", "INT64", "NULLABLE"),
    ("canonical_url", "STRING", "NULLABLE"),
    ("is_noindex", "BOOL", "NULLABLE"),
    ("crawl_depth", "INT64", "NULLABLE"),
    ("inlinks", "INT64", "NULLABLE"),
    ("outlinks", "INT64", "NULLABLE"),
    ("issue_flags_json", "JSON", "NULLABLE"),
    ("export_name", "STRING", "NULLABLE"),
    ("source_file", "STRING", "NULLABLE"),
    ("row_number", "INT64", "NULLABLE"),
    ("raw_row_json", "JSON", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("retention_expires_on", "DATE", "REQUIRED"),
]


CLIENT_CRAWL_ISSUE_ROWS_SCHEMA: list[SchemaTuple] = [
    ("crawl_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("crawl_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("export_name", "STRING", "REQUIRED"),
    ("source_file", "STRING", "REQUIRED"),
    ("row_number", "INT64", "REQUIRED"),
    ("issue_name", "STRING", "NULLABLE"),
    ("issue_type", "STRING", "NULLABLE"),
    ("issue_priority", "STRING", "NULLABLE"),
    ("issue_count", "INT64", "NULLABLE"),
    ("address", "STRING", "NULLABLE"),
    ("source_url", "STRING", "NULLABLE"),
    ("destination_url", "STRING", "NULLABLE"),
    ("status_code", "INT64", "NULLABLE"),
    ("indexability", "STRING", "NULLABLE"),
    ("indexability_status", "STRING", "NULLABLE"),
    ("raw_row_json", "JSON", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("retention_expires_on", "DATE", "REQUIRED"),
]


CLIENT_CRAWL_LINK_ROWS_SCHEMA: list[SchemaTuple] = [
    ("crawl_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("crawl_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("export_name", "STRING", "REQUIRED"),
    ("source_file", "STRING", "REQUIRED"),
    ("row_number", "INT64", "REQUIRED"),
    ("link_type", "STRING", "NULLABLE"),
    ("source_url", "STRING", "NULLABLE"),
    ("destination_url", "STRING", "NULLABLE"),
    ("anchor", "STRING", "NULLABLE"),
    ("alt_text", "STRING", "NULLABLE"),
    ("status_code", "INT64", "NULLABLE"),
    ("status", "STRING", "NULLABLE"),
    ("crawlability", "STRING", "NULLABLE"),
    ("follow", "STRING", "NULLABLE"),
    ("path_type", "STRING", "NULLABLE"),
    ("link_position", "STRING", "NULLABLE"),
    ("raw_row_json", "JSON", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("retention_expires_on", "DATE", "REQUIRED"),
]


CLIENT_CRAWL_EXPORT_ROWS_SCHEMA: list[SchemaTuple] = [
    ("crawl_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("crawl_date", "DATE", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("export_name", "STRING", "REQUIRED"),
    ("source_file", "STRING", "REQUIRED"),
    ("row_number", "INT64", "REQUIRED"),
    ("primary_url", "STRING", "NULLABLE"),
    ("row_type", "STRING", "NULLABLE"),
    ("raw_row_json", "JSON", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("retention_expires_on", "DATE", "REQUIRED"),
]


REPORTING_CLIENT_TASK_STATUS_SCHEMA = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "NULLABLE"),
    ("client_name", "STRING", "NULLABLE"),
    ("board_id", "STRING", "REQUIRED"),
    ("board_name", "STRING", "REQUIRED"),
    ("item_id", "STRING", "REQUIRED"),
    ("item_name", "STRING", "REQUIRED"),
    ("status", "STRING", "NULLABLE"),
    ("normalized_status", "STRING", "REQUIRED"),
    ("owner", "STRING", "NULLABLE"),
    ("due_date", "DATE", "NULLABLE"),
    ("group_title", "STRING", "NULLABLE"),
    ("updated_at", "TIMESTAMP", "NULLABLE"),
    ("is_done", "BOOL", "REQUIRED"),
    ("is_overdue", "BOOL", "REQUIRED"),
]


REPORTING_CLIENT_DELIVERY_TIMELINE_SCHEMA = [
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "NULLABLE"),
    ("event_date", "DATE", "REQUIRED"),
    ("event_type", "STRING", "REQUIRED"),
    ("title", "STRING", "NULLABLE"),
    ("status", "STRING", "NULLABLE"),
    ("source_table", "STRING", "REQUIRED"),
    ("source_id", "STRING", "NULLABLE"),
]


REPORTING_CLIENT_MONTH_PERFORMANCE_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("report_month", "DATE", "NULLABLE"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("share_id", "STRING", "NULLABLE"),
    ("generated_at", "TIMESTAMP", "NULLABLE"),
    ("headline_metrics_json", "JSON", "NULLABLE"),
    ("commentary_json", "JSON", "NULLABLE"),
    ("source_caveats_json", "JSON", "NULLABLE"),
]


REPORTING_CLIENT_MONTHLY_PERFORMANCE_SUMMARY_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("report_month", "DATE", "NULLABLE"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("share_id", "STRING", "NULLABLE"),
    ("generated_at", "TIMESTAMP", "NULLABLE"),
    ("organic_sessions", "FLOAT64", "NULLABLE"),
    ("organic_users", "FLOAT64", "NULLABLE"),
    ("engaged_sessions", "FLOAT64", "NULLABLE"),
    ("organic_purchases", "FLOAT64", "NULLABLE"),
    ("organic_revenue", "FLOAT64", "NULLABLE"),
    ("organic_conversion_rate", "FLOAT64", "NULLABLE"),
    ("organic_aov", "FLOAT64", "NULLABLE"),
    ("gsc_clicks", "FLOAT64", "NULLABLE"),
    ("gsc_impressions", "FLOAT64", "NULLABLE"),
    ("gsc_ctr", "FLOAT64", "NULLABLE"),
    ("gsc_avg_position", "FLOAT64", "NULLABLE"),
    ("se_visibility_start", "FLOAT64", "NULLABLE"),
    ("se_visibility_end", "FLOAT64", "NULLABLE"),
    ("se_visibility_delta", "FLOAT64", "NULLABLE"),
    ("se_top10_start", "FLOAT64", "NULLABLE"),
    ("se_top10_end", "FLOAT64", "NULLABLE"),
    ("se_top10_delta", "FLOAT64", "NULLABLE"),
    ("se_avg_position_start", "FLOAT64", "NULLABLE"),
    ("se_avg_position_end", "FLOAT64", "NULLABLE"),
    ("se_avg_position_delta", "FLOAT64", "NULLABLE"),
    ("ai_sessions", "FLOAT64", "NULLABLE"),
    ("ai_users", "FLOAT64", "NULLABLE"),
    ("ai_revenue", "FLOAT64", "NULLABLE"),
    ("ai_blog_sessions", "FLOAT64", "NULLABLE"),
]


REPORTING_CLIENT_MONTHLY_REPORT_NARRATIVE_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("report_month", "DATE", "NULLABLE"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("share_id", "STRING", "NULLABLE"),
    ("generated_at", "TIMESTAMP", "NULLABLE"),
    ("summary", "STRING", "NULLABLE"),
    ("completed_work", "STRING", "NULLABLE"),
    ("next_focus", "STRING", "NULLABLE"),
    ("caveats", "STRING", "NULLABLE"),
]


REPORTING_CLIENT_MONTHLY_REPORTING_COVERAGE_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("report_month", "DATE", "NULLABLE"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("share_id", "STRING", "NULLABLE"),
    ("generated_at", "TIMESTAMP", "NULLABLE"),
    ("has_ga4", "BOOL", "REQUIRED"),
    ("has_search_console", "BOOL", "REQUIRED"),
    ("has_se_ranking", "BOOL", "REQUIRED"),
    ("has_ai_referrals", "BOOL", "REQUIRED"),
    ("ga4_caveats", "STRING", "NULLABLE"),
    ("search_console_caveats", "STRING", "NULLABLE"),
    ("se_ranking_caveats", "STRING", "NULLABLE"),
    ("ai_referrals_caveats", "STRING", "NULLABLE"),
    ("coverage_status", "STRING", "REQUIRED"),
]


REPORTING_CLIENT_MONTHLY_PERFORMANCE_HISTORY_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("month_end", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("ga4_status", "STRING", "REQUIRED"),
    ("gsc_status", "STRING", "REQUIRED"),
    ("se_ranking_status", "STRING", "REQUIRED"),
    ("organic_sessions", "FLOAT64", "NULLABLE"),
    ("organic_users", "FLOAT64", "NULLABLE"),
    ("engaged_sessions", "FLOAT64", "NULLABLE"),
    ("organic_purchases", "FLOAT64", "NULLABLE"),
    ("organic_revenue", "FLOAT64", "NULLABLE"),
    ("organic_conversion_rate", "FLOAT64", "NULLABLE"),
    ("organic_aov", "FLOAT64", "NULLABLE"),
    ("ai_sessions", "FLOAT64", "NULLABLE"),
    ("ai_users", "FLOAT64", "NULLABLE"),
    ("ai_revenue", "FLOAT64", "NULLABLE"),
    ("ai_blog_sessions", "FLOAT64", "NULLABLE"),
    ("gsc_clicks", "FLOAT64", "NULLABLE"),
    ("gsc_impressions", "FLOAT64", "NULLABLE"),
    ("gsc_ctr", "FLOAT64", "NULLABLE"),
    ("gsc_avg_position", "FLOAT64", "NULLABLE"),
    ("se_visibility_start", "FLOAT64", "NULLABLE"),
    ("se_visibility_end", "FLOAT64", "NULLABLE"),
    ("se_visibility_delta", "FLOAT64", "NULLABLE"),
    ("se_top10_start", "FLOAT64", "NULLABLE"),
    ("se_top10_end", "FLOAT64", "NULLABLE"),
    ("se_top10_delta", "FLOAT64", "NULLABLE"),
    ("se_avg_position_start", "FLOAT64", "NULLABLE"),
    ("se_avg_position_end", "FLOAT64", "NULLABLE"),
    ("se_avg_position_delta", "FLOAT64", "NULLABLE"),
]


REPORTING_CLIENT_MONTHLY_COMPARISON_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("organic_revenue", "FLOAT64", "NULLABLE"),
    ("organic_revenue_mom_delta", "FLOAT64", "NULLABLE"),
    ("organic_revenue_mom_pct", "FLOAT64", "NULLABLE"),
    ("organic_revenue_yoy_delta", "FLOAT64", "NULLABLE"),
    ("organic_revenue_yoy_pct", "FLOAT64", "NULLABLE"),
    ("organic_sessions", "FLOAT64", "NULLABLE"),
    ("organic_sessions_mom_delta", "FLOAT64", "NULLABLE"),
    ("organic_sessions_mom_pct", "FLOAT64", "NULLABLE"),
    ("organic_sessions_yoy_delta", "FLOAT64", "NULLABLE"),
    ("organic_sessions_yoy_pct", "FLOAT64", "NULLABLE"),
    ("gsc_clicks", "FLOAT64", "NULLABLE"),
    ("gsc_clicks_mom_delta", "FLOAT64", "NULLABLE"),
    ("gsc_clicks_mom_pct", "FLOAT64", "NULLABLE"),
    ("gsc_clicks_yoy_delta", "FLOAT64", "NULLABLE"),
    ("gsc_clicks_yoy_pct", "FLOAT64", "NULLABLE"),
    ("se_visibility_end", "FLOAT64", "NULLABLE"),
    ("se_visibility_mom_delta", "FLOAT64", "NULLABLE"),
    ("se_visibility_yoy_delta", "FLOAT64", "NULLABLE"),
    ("ai_sessions", "FLOAT64", "NULLABLE"),
    ("ai_sessions_mom_delta", "FLOAT64", "NULLABLE"),
    ("ai_sessions_yoy_delta", "FLOAT64", "NULLABLE"),
    ("source_health", "STRING", "REQUIRED"),
]


REPORTING_CLIENT_TRAILING_PERFORMANCE_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("organic_revenue_t3", "FLOAT64", "NULLABLE"),
    ("organic_revenue_t6", "FLOAT64", "NULLABLE"),
    ("organic_revenue_t12", "FLOAT64", "NULLABLE"),
    ("organic_sessions_t3", "FLOAT64", "NULLABLE"),
    ("organic_sessions_t6", "FLOAT64", "NULLABLE"),
    ("organic_sessions_t12", "FLOAT64", "NULLABLE"),
    ("gsc_clicks_t3", "FLOAT64", "NULLABLE"),
    ("gsc_clicks_t6", "FLOAT64", "NULLABLE"),
    ("gsc_clicks_t12", "FLOAT64", "NULLABLE"),
    ("ai_sessions_t3", "FLOAT64", "NULLABLE"),
    ("ai_sessions_t6", "FLOAT64", "NULLABLE"),
    ("ai_sessions_t12", "FLOAT64", "NULLABLE"),
    ("latest_se_visibility", "FLOAT64", "NULLABLE"),
    ("months_available", "INT64", "REQUIRED"),
]


REPORTING_CLIENT_BENCHMARK_SUMMARY_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("organic_revenue", "FLOAT64", "NULLABLE"),
    ("organic_revenue_yoy_pct", "FLOAT64", "NULLABLE"),
    ("organic_sessions", "FLOAT64", "NULLABLE"),
    ("gsc_clicks", "FLOAT64", "NULLABLE"),
    ("se_visibility_end", "FLOAT64", "NULLABLE"),
    ("ai_sessions", "FLOAT64", "NULLABLE"),
    ("organic_revenue_rank", "INT64", "NULLABLE"),
    ("organic_revenue_yoy_rank", "INT64", "NULLABLE"),
    ("organic_sessions_rank", "INT64", "NULLABLE"),
    ("gsc_clicks_rank", "INT64", "NULLABLE"),
    ("se_visibility_rank", "INT64", "NULLABLE"),
    ("performance_status", "STRING", "REQUIRED"),
    ("source_health", "STRING", "REQUIRED"),
]


REPORTING_READINESS_SCHEMA = [
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("monday_board_id", "STRING", "NULLABLE"),
    ("ga4_property", "STRING", "NULLABLE"),
    ("has_report_snapshot", "BOOL", "REQUIRED"),
    ("latest_report_month", "DATE", "NULLABLE"),
    ("readiness_status", "STRING", "REQUIRED"),
]


REPORTING_OPS_DRIFT_SUMMARY_SCHEMA = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("client", "STRING", "NULLABLE"),
    ("alignment_rows", "INT64", "REQUIRED"),
    ("status_mismatches", "INT64", "REQUIRED"),
    ("owner_mismatches", "INT64", "REQUIRED"),
    ("due_date_mismatches", "INT64", "REQUIRED"),
    ("stale_client_updates", "INT64", "REQUIRED"),
]


REPORTING_CLIENT_COMMS_ATTENTION_SCHEMA = [
    ("week_start", "DATE", "REQUIRED"),
    ("week_end", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("thread_ref_hash", "STRING", "NULLABLE"),
    ("thread_status", "STRING", "NULLABLE"),
    ("signal_type", "STRING", "REQUIRED"),
    ("severity", "STRING", "REQUIRED"),
    ("channel", "STRING", "REQUIRED"),
    ("category", "STRING", "REQUIRED"),
    ("summary", "STRING", "REQUIRED"),
    ("recommended_action", "STRING", "NULLABLE"),
    ("owner_hint", "STRING", "NULLABLE"),
    ("due_hint", "STRING", "NULLABLE"),
    ("source_event_count", "INT64", "REQUIRED"),
    ("confidence", "FLOAT64", "REQUIRED"),
    ("evidence_table", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("latest_event_at", "TIMESTAMP", "NULLABLE"),
]


REPORTING_CLIENT_COMMS_HISTORY_SCHEMA = [
    ("week_start", "DATE", "REQUIRED"),
    ("week_end", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("thread_ref_hash", "STRING", "NULLABLE"),
    ("thread_status", "STRING", "NULLABLE"),
    ("latest_event_at", "TIMESTAMP", "NULLABLE"),
    ("resolved_at", "TIMESTAMP", "NULLABLE"),
    ("channel", "STRING", "REQUIRED"),
    ("category", "STRING", "REQUIRED"),
    ("summary", "STRING", "REQUIRED"),
    ("recommended_action", "STRING", "NULLABLE"),
    ("owner_hint", "STRING", "NULLABLE"),
    ("due_hint", "STRING", "NULLABLE"),
    ("needs_reply", "BOOL", "REQUIRED"),
    ("blocked", "BOOL", "REQUIRED"),
    ("waiting_on_client", "BOOL", "REQUIRED"),
    ("waiting_on_us", "BOOL", "REQUIRED"),
    ("stale_followup", "BOOL", "REQUIRED"),
    ("urgency", "STRING", "REQUIRED"),
    ("sentiment", "STRING", "NULLABLE"),
    ("resolution_summary", "STRING", "NULLABLE"),
    ("source_event_count", "INT64", "REQUIRED"),
    ("confidence", "FLOAT64", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("created_at", "TIMESTAMP", "REQUIRED"),
]


REPORTING_CLIENT_ROADMAP_CURRENT_SCHEMA = [
    ("planned_month", "DATE", "REQUIRED"),
    ("period_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("roadmap_item_id", "STRING", "REQUIRED"),
    ("item_title", "STRING", "REQUIRED"),
    ("work_type", "STRING", "REQUIRED"),
    ("priority", "STRING", "REQUIRED"),
    ("planned_status", "STRING", "REQUIRED"),
    ("delivery_status", "STRING", "REQUIRED"),
    ("owner_hint", "STRING", "NULLABLE"),
    ("due_date", "DATE", "NULLABLE"),
    ("target_url", "STRING", "NULLABLE"),
    ("keyword_theme", "STRING", "NULLABLE"),
    ("completion_evidence_type", "STRING", "NULLABLE"),
    ("completion_evidence_ref", "STRING", "NULLABLE"),
    ("completion_summary", "STRING", "NULLABLE"),
    ("completion_confidence", "FLOAT64", "REQUIRED"),
    ("matched_evidence_table", "STRING", "NULLABLE"),
    ("matched_evidence_id", "STRING", "NULLABLE"),
    ("matched_evidence_title", "STRING", "NULLABLE"),
    ("matched_evidence_date", "DATE", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
]


REPORTING_CLIENT_ROADMAP_MONTHLY_COMPLETION_SCHEMA = [
    ("planned_month", "DATE", "REQUIRED"),
    ("period_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("planned_items", "INT64", "REQUIRED"),
    ("completed_items", "INT64", "REQUIRED"),
    ("in_progress_items", "INT64", "REQUIRED"),
    ("blocked_items", "INT64", "REQUIRED"),
    ("deferred_items", "INT64", "REQUIRED"),
    ("missing_evidence_items", "INT64", "REQUIRED"),
    ("overdue_items", "INT64", "REQUIRED"),
    ("completion_rate", "FLOAT64", "NULLABLE"),
    ("high_priority_open_items", "INT64", "REQUIRED"),
    ("status_summary", "STRING", "REQUIRED"),
]


REPORTING_CLIENT_HEALTH_CHECK_SCHEMA = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("expected_assets", "INT64", "REQUIRED"),
    ("present_assets", "INT64", "REQUIRED"),
    ("missing_required_assets", "INT64", "REQUIRED"),
    ("missing_optional_assets", "INT64", "REQUIRED"),
    ("unknown_assets", "INT64", "REQUIRED"),
    ("critical_missing_assets", "INT64", "REQUIRED"),
    ("health_score", "FLOAT64", "NULLABLE"),
    ("health_status", "STRING", "REQUIRED"),
    ("missing_required_json", "JSON", "NULLABLE"),
    ("missing_optional_json", "JSON", "NULLABLE"),
    ("has_sidecar_json", "BOOL", "REQUIRED"),
    ("has_client_brief", "BOOL", "REQUIRED"),
    ("has_timeline", "BOOL", "REQUIRED"),
    ("has_writing_style", "BOOL", "REQUIRED"),
    ("has_brand_writing_guide_doc", "BOOL", "REQUIRED"),
    ("has_drive_root", "BOOL", "REQUIRED"),
    ("has_drive_root_verified", "BOOL", "REQUIRED"),
    ("has_roadmap_route", "BOOL", "REQUIRED"),
    ("has_roadmap_folder_verified", "BOOL", "REQUIRED"),
    ("has_roadmap_files", "BOOL", "REQUIRED"),
    ("has_roadmap_content_validated", "BOOL", "REQUIRED"),
    ("has_content_route", "BOOL", "REQUIRED"),
    ("has_content_folder_verified", "BOOL", "REQUIRED"),
    ("has_reports_route", "BOOL", "REQUIRED"),
    ("has_reports_folder_verified", "BOOL", "REQUIRED"),
    ("has_monday_board", "BOOL", "REQUIRED"),
    ("has_monday_board_snapshot", "BOOL", "REQUIRED"),
    ("has_reporting_config", "BOOL", "REQUIRED"),
    ("has_ga4_property", "BOOL", "REQUIRED"),
    ("has_ga4_access", "BOOL", "REQUIRED"),
    ("has_search_console", "BOOL", "REQUIRED"),
    ("has_search_console_access", "BOOL", "REQUIRED"),
    ("has_se_ranking", "BOOL", "REQUIRED"),
    ("has_se_ranking_access", "BOOL", "REQUIRED"),
    ("has_monthly_report_snapshot", "BOOL", "REQUIRED"),
    ("has_roadmap_items", "BOOL", "REQUIRED"),
    ("latest_report_month", "DATE", "NULLABLE"),
]


REPORTING_CLIENT_FINANCE_HEALTH_SCHEMA = [
    ("period_id", "STRING", "REQUIRED"),
    ("month_start", "DATE", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("client_label", "STRING", "REQUIRED"),
    ("billing_status", "STRING", "REQUIRED"),
    ("retainer_amount_aud", "FLOAT64", "REQUIRED"),
    ("expense_amount_aud", "FLOAT64", "REQUIRED"),
    ("net_amount_aud", "FLOAT64", "REQUIRED"),
    ("is_billable", "BOOL", "REQUIRED"),
    ("is_due", "BOOL", "REQUIRED"),
    ("is_paid", "BOOL", "REQUIRED"),
    ("is_issued", "BOOL", "REQUIRED"),
    ("due_amount_aud", "FLOAT64", "REQUIRED"),
    ("paid_due_amount_aud", "FLOAT64", "REQUIRED"),
    ("issued_due_amount_aud", "FLOAT64", "REQUIRED"),
    ("not_issued_due_amount_aud", "FLOAT64", "REQUIRED"),
    ("retainer_total_aud", "FLOAT64", "REQUIRED"),
    ("expense_total_aud", "FLOAT64", "REQUIRED"),
    ("net_total_aud", "FLOAT64", "REQUIRED"),
    ("gross_margin_amount_aud", "FLOAT64", "REQUIRED"),
    ("billable_months", "INT64", "REQUIRED"),
    ("due_months", "INT64", "REQUIRED"),
    ("not_issued_due_months", "INT64", "REQUIRED"),
    ("collection_rate", "FLOAT64", "NULLABLE"),
    ("invoice_coverage_rate", "FLOAT64", "NULLABLE"),
    ("expense_ratio", "FLOAT64", "NULLABLE"),
    ("gross_margin_rate", "FLOAT64", "NULLABLE"),
    ("finance_score", "INT64", "REQUIRED"),
    ("finance_status", "STRING", "REQUIRED"),
    ("source_table", "STRING", "REQUIRED"),
]


REPORTING_CLIENT_CRAWL_LATEST_SCHEMA = [
    ("crawl_date", "DATE", "REQUIRED"),
    ("crawl_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("crawl_trigger", "STRING", "REQUIRED"),
    ("crawler", "STRING", "REQUIRED"),
    ("start_url", "STRING", "REQUIRED"),
    ("crawl_status", "STRING", "REQUIRED"),
    ("pages_crawled", "INT64", "NULLABLE"),
    ("indexable_html_urls", "INT64", "NULLABLE"),
    ("nonindexable_html_urls", "INT64", "NULLABLE"),
    ("status_4xx_urls", "INT64", "NULLABLE"),
    ("status_5xx_urls", "INT64", "NULLABLE"),
    ("missing_title_urls", "INT64", "NULLABLE"),
    ("duplicate_title_urls", "INT64", "NULLABLE"),
    ("missing_meta_description_urls", "INT64", "NULLABLE"),
    ("missing_h1_urls", "INT64", "NULLABLE"),
    ("canonical_issue_urls", "INT64", "NULLABLE"),
    ("low_content_urls", "INT64", "NULLABLE"),
    ("issue_counts_json", "JSON", "NULLABLE"),
    ("export_manifest_path", "STRING", "NULLABLE"),
    ("export_drive_file_id", "STRING", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


REPORTING_CLIENT_CRAWL_COMPARISON_SCHEMA = [
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("current_crawl_id", "STRING", "REQUIRED"),
    ("current_crawl_date", "DATE", "REQUIRED"),
    ("previous_crawl_id", "STRING", "NULLABLE"),
    ("previous_crawl_date", "DATE", "NULLABLE"),
    ("crawl_trigger", "STRING", "REQUIRED"),
    ("pages_crawled_delta", "INT64", "NULLABLE"),
    ("indexable_html_urls_delta", "INT64", "NULLABLE"),
    ("status_4xx_urls_delta", "INT64", "NULLABLE"),
    ("status_5xx_urls_delta", "INT64", "NULLABLE"),
    ("missing_title_urls_delta", "INT64", "NULLABLE"),
    ("missing_meta_description_urls_delta", "INT64", "NULLABLE"),
    ("missing_h1_urls_delta", "INT64", "NULLABLE"),
    ("canonical_issue_urls_delta", "INT64", "NULLABLE"),
    ("low_content_urls_delta", "INT64", "NULLABLE"),
    ("comparison_status", "STRING", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


AGENT_RUN_LOG_SCHEMA: list[SchemaTuple] = [
    ("run_id", "STRING", "REQUIRED"),
    ("automation_id", "STRING", "NULLABLE"),
    ("agent_id", "STRING", "REQUIRED"),
    ("agent_name", "STRING", "REQUIRED"),
    ("started_at", "TIMESTAMP", "REQUIRED"),
    ("completed_at", "TIMESTAMP", "NULLABLE"),
    ("status", "STRING", "REQUIRED"),
    ("mode", "STRING", "REQUIRED"),
    ("prompt_version", "STRING", "NULLABLE"),
    ("context_id", "STRING", "NULLABLE"),
    ("input_sources_json", "JSON", "NULLABLE"),
    ("output_path", "STRING", "NULLABLE"),
    ("findings_count", "INT64", "REQUIRED"),
    ("actions_count", "INT64", "REQUIRED"),
    ("error_message", "STRING", "NULLABLE"),
    ("dry_run", "BOOL", "REQUIRED"),
    ("bigquery_write_status", "STRING", "NULLABLE"),
]


AGENT_FINDINGS_SCHEMA: list[SchemaTuple] = [
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("agent_id", "STRING", "REQUIRED"),
    ("finding_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("finding_type", "STRING", "REQUIRED"),
    ("severity", "STRING", "REQUIRED"),
    ("summary", "STRING", "REQUIRED"),
    ("evidence_json", "JSON", "REQUIRED"),
    ("source_tables_json", "JSON", "NULLABLE"),
    ("recommended_action", "STRING", "NULLABLE"),
    ("confidence_score", "FLOAT64", "REQUIRED"),
    ("requires_human_review", "BOOL", "REQUIRED"),
    ("qa_status", "STRING", "REQUIRED"),
    ("status", "STRING", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


AGENT_ACTIONS_SCHEMA: list[SchemaTuple] = [
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("agent_id", "STRING", "REQUIRED"),
    ("action_id", "STRING", "REQUIRED"),
    ("finding_id", "STRING", "NULLABLE"),
    ("client_slug", "STRING", "REQUIRED"),
    ("action_type", "STRING", "REQUIRED"),
    ("target_system", "STRING", "REQUIRED"),
    ("recommended_action", "STRING", "REQUIRED"),
    ("priority", "STRING", "REQUIRED"),
    ("status", "STRING", "REQUIRED"),
    ("requires_approval", "BOOL", "REQUIRED"),
    ("evidence_json", "JSON", "REQUIRED"),
    ("due_hint", "STRING", "NULLABLE"),
    ("owner_hint", "STRING", "NULLABLE"),
    ("approval_id", "STRING", "NULLABLE"),
]


AGENT_APPROVALS_SCHEMA: list[SchemaTuple] = [
    ("decided_at", "TIMESTAMP", "REQUIRED"),
    ("approval_id", "STRING", "REQUIRED"),
    ("action_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("decision", "STRING", "REQUIRED"),
    ("decided_by", "STRING", "REQUIRED"),
    ("reason", "STRING", "NULLABLE"),
    ("notes", "STRING", "NULLABLE"),
    ("source_system", "STRING", "REQUIRED"),
]


CONTEXT_PACKS_SCHEMA: list[SchemaTuple] = [
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("context_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("agent_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "NULLABLE"),
    ("task_type", "STRING", "REQUIRED"),
    ("sections_json", "JSON", "REQUIRED"),
    ("source_tables_json", "JSON", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
    ("retention_hint", "STRING", "NULLABLE"),
]


LLM_USAGE_LOG_SCHEMA: list[SchemaTuple] = [
    ("logged_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("agent_id", "STRING", "REQUIRED"),
    ("model", "STRING", "NULLABLE"),
    ("prompt_version", "STRING", "NULLABLE"),
    ("input_tokens", "INT64", "NULLABLE"),
    ("output_tokens", "INT64", "NULLABLE"),
    ("cost_estimate_aud", "FLOAT64", "NULLABLE"),
    ("notes", "STRING", "NULLABLE"),
]


SEO_WORKFLOW_CATALOG_SCHEMA: list[SchemaTuple] = [
    ("synced_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("workflow_id", "STRING", "REQUIRED"),
    ("family", "STRING", "REQUIRED"),
    ("skill_id", "STRING", "REQUIRED"),
    ("workflow_doc_path", "STRING", "NULLABLE"),
    ("title", "STRING", "REQUIRED"),
    ("commands_json", "JSON", "NULLABLE"),
    ("required_inputs_json", "JSON", "NULLABLE"),
    ("scripts_json", "JSON", "NULLABLE"),
    ("validators_json", "JSON", "NULLABLE"),
    ("api_dependencies_json", "JSON", "NULLABLE"),
    ("mcp_dependencies_json", "JSON", "NULLABLE"),
    ("write_gates_json", "JSON", "NULLABLE"),
    ("proof_fields_json", "JSON", "NULLABLE"),
    ("active", "BOOL", "REQUIRED"),
    ("notes", "STRING", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


SEO_CLIENT_MEMORY_SUMMARIES_SCHEMA: list[SchemaTuple] = [
    ("synced_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("domain", "STRING", "NULLABLE"),
    ("site_type", "STRING", "NULLABLE"),
    ("market_scope", "STRING", "NULLABLE"),
    ("workflow_profile", "STRING", "NULLABLE"),
    ("sidecar_path", "STRING", "NULLABLE"),
    ("brief_path", "STRING", "NULLABLE"),
    ("timeline_path", "STRING", "NULLABLE"),
    ("sidecar_present", "BOOL", "REQUIRED"),
    ("brief_present", "BOOL", "REQUIRED"),
    ("timeline_present", "BOOL", "REQUIRED"),
    ("ga4_property", "STRING", "NULLABLE"),
    ("has_search_console_route", "BOOL", "REQUIRED"),
    ("has_se_ranking", "BOOL", "REQUIRED"),
    ("has_monday_route", "BOOL", "REQUIRED"),
    ("has_drive_root", "BOOL", "REQUIRED"),
    ("drive_routes_json", "JSON", "NULLABLE"),
    ("monday_routes_json", "JSON", "NULLABLE"),
    ("se_ranking_routes_json", "JSON", "NULLABLE"),
    ("collection_count", "INT64", "REQUIRED"),
    ("priority_pages_count", "INT64", "REQUIRED"),
    ("deliverables_json", "JSON", "NULLABLE"),
    ("reports_json", "JSON", "NULLABLE"),
    ("recent_timeline_summary_json", "JSON", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


SEO_WORKFLOW_RUN_SUMMARIES_SCHEMA: list[SchemaTuple] = [
    ("completed_at", "TIMESTAMP", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("workflow_id", "STRING", "REQUIRED"),
    ("agent_id", "STRING", "REQUIRED"),
    ("status", "STRING", "REQUIRED"),
    ("summary", "STRING", "REQUIRED"),
    ("outputs_json", "JSON", "NULLABLE"),
    ("blockers_json", "JSON", "NULLABLE"),
    ("next_actions_json", "JSON", "NULLABLE"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


REPORTING_SEO_WORKFLOW_READINESS_SCHEMA: list[SchemaTuple] = [
    ("generated_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("readiness_status", "STRING", "REQUIRED"),
    ("missing_inputs_json", "JSON", "NULLABLE"),
    ("recommended_workflow_id", "STRING", "NULLABLE"),
    ("recommended_agent_id", "STRING", "NULLABLE"),
    ("evidence_json", "JSON", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


REPORTING_SEO_OPPORTUNITY_QUEUE_SCHEMA: list[SchemaTuple] = [
    ("generated_at", "TIMESTAMP", "REQUIRED"),
    ("client_slug", "STRING", "REQUIRED"),
    ("client_name", "STRING", "REQUIRED"),
    ("opportunity_type", "STRING", "REQUIRED"),
    ("workflow_id", "STRING", "REQUIRED"),
    ("priority", "STRING", "REQUIRED"),
    ("summary", "STRING", "REQUIRED"),
    ("recommended_action", "STRING", "REQUIRED"),
    ("evidence_json", "JSON", "REQUIRED"),
    ("source_ref_hash", "STRING", "REQUIRED"),
]


def control_table_specs(config: BigQueryCostConfig) -> list[TableSpec]:
    return [
        TableSpec(config.control_dataset, config.cost_checks_table, COST_CHECKS_SCHEMA),
        TableSpec(config.control_dataset, "data_sources", DATA_SOURCES_SCHEMA),
        TableSpec(config.control_dataset, "ingestion_runs", INGESTION_RUNS_SCHEMA),
        TableSpec(config.control_dataset, "api_smoke_checks", API_SMOKE_CHECKS_SCHEMA),
        TableSpec(config.control_dataset, "agent_run_log", AGENT_RUN_LOG_SCHEMA, partition_field="started_at", cluster_fields=("agent_id", "status")),
        TableSpec(config.control_dataset, "llm_usage_log", LLM_USAGE_LOG_SCHEMA, partition_field="logged_at", cluster_fields=("agent_id", "model")),
    ]


def agent_operating_table_specs(config: BigQueryCostConfig) -> list[TableSpec]:
    return [
        TableSpec(config.control_dataset, "agent_run_log", AGENT_RUN_LOG_SCHEMA, partition_field="started_at", cluster_fields=("agent_id", "status")),
        TableSpec(config.control_dataset, "llm_usage_log", LLM_USAGE_LOG_SCHEMA, partition_field="logged_at", cluster_fields=("agent_id", "model")),
        TableSpec(config.memory_dataset, "agent_findings", AGENT_FINDINGS_SCHEMA, partition_field="created_at", cluster_fields=("client_slug", "agent_id", "qa_status")),
        TableSpec(config.memory_dataset, "agent_actions", AGENT_ACTIONS_SCHEMA, partition_field="created_at", cluster_fields=("client_slug", "target_system", "status")),
        TableSpec(config.memory_dataset, "agent_approvals", AGENT_APPROVALS_SCHEMA, partition_field="decided_at", cluster_fields=("client_slug", "decision")),
        TableSpec(config.memory_dataset, "context_packs", CONTEXT_PACKS_SCHEMA, partition_field="created_at", cluster_fields=("agent_id", "client_slug")),
        TableSpec(config.memory_dataset, "seo_workflow_catalog", SEO_WORKFLOW_CATALOG_SCHEMA, partition_field="synced_at", cluster_fields=("family", "workflow_id")),
        TableSpec(config.memory_dataset, "seo_client_memory_summaries", SEO_CLIENT_MEMORY_SUMMARIES_SCHEMA, partition_field="synced_at", cluster_fields=("client_slug", "site_type")),
        TableSpec(config.memory_dataset, "seo_workflow_run_summaries", SEO_WORKFLOW_RUN_SUMMARIES_SCHEMA, partition_field="completed_at", cluster_fields=("client_slug", "workflow_id", "status")),
        TableSpec(config.reporting_dataset, "seo_workflow_readiness", REPORTING_SEO_WORKFLOW_READINESS_SCHEMA, partition_field="generated_at", cluster_fields=("client_slug", "readiness_status")),
        TableSpec(config.reporting_dataset, "seo_opportunity_queue", REPORTING_SEO_OPPORTUNITY_QUEUE_SCHEMA, partition_field="generated_at", cluster_fields=("client_slug", "priority", "workflow_id")),
    ]


def crawl_memory_table_specs(config: BigQueryCostConfig) -> list[TableSpec]:
    return [
        TableSpec(
            config.memory_dataset,
            "client_crawl_runs",
            CLIENT_CRAWL_RUNS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "crawl_trigger", "crawler"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_url_snapshots",
            CLIENT_CRAWL_URL_SNAPSHOTS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "url_hash"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_issue_rows",
            CLIENT_CRAWL_ISSUE_ROWS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "issue_priority", "issue_type"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_link_rows",
            CLIENT_CRAWL_LINK_ROWS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "source_url", "destination_url"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_export_rows",
            CLIENT_CRAWL_EXPORT_ROWS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "export_name"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_crawl_latest",
            REPORTING_CLIENT_CRAWL_LATEST_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "crawl_status"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_crawl_comparison",
            REPORTING_CLIENT_CRAWL_COMPARISON_SCHEMA,
            partition_field="current_crawl_date",
            cluster_fields=("client_slug", "comparison_status"),
        ),
    ]


def agency_ops_table_specs(config: BigQueryCostConfig) -> list[TableSpec]:
    return [
        *control_table_specs(config),
        TableSpec(
            config.staging_dataset,
            "agency_ops_records",
            STAGING_RECORDS_SCHEMA,
            partition_field="ingested_at",
            expires_in_hours=config.staging_table_expiry_hours,
        ),
        TableSpec(config.memory_dataset, "monday_boards", MONDAY_BOARDS_SCHEMA, partition_field="snapshot_date"),
        TableSpec(config.memory_dataset, "monday_board_columns", MONDAY_BOARD_COLUMNS_SCHEMA, partition_field="snapshot_date"),
        TableSpec(config.memory_dataset, "monday_status_labels", MONDAY_STATUS_LABELS_SCHEMA, partition_field="snapshot_date"),
        TableSpec(
            config.memory_dataset,
            "monday_items",
            MONDAY_ITEMS_SCHEMA,
            partition_field="snapshot_date",
            cluster_fields=("client_slug", "board_id", "normalized_status"),
        ),
        TableSpec(
            config.memory_dataset,
            "monday_item_column_values",
            MONDAY_ITEM_COLUMN_VALUES_SCHEMA,
            partition_field="snapshot_date",
            cluster_fields=("board_id", "item_id"),
        ),
        TableSpec(config.memory_dataset, "client_registry", CLIENT_REGISTRY_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.memory_dataset, "client_onboarding_profiles", CLIENT_ONBOARDING_PROFILES_SCHEMA, partition_field="ingested_at", cluster_fields=("client_slug", "review_status")),
        TableSpec(config.memory_dataset, "client_board_map", CLIENT_BOARD_MAP_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.memory_dataset, "task_alignment", TASK_ALIGNMENT_SCHEMA, partition_field="snapshot_date"),
        TableSpec(config.memory_dataset, "client_timeline_events", CLIENT_TIMELINE_EVENTS_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.memory_dataset, "monthly_report_snapshots", MONTHLY_REPORT_SNAPSHOTS_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(
            config.memory_dataset,
            "client_monthly_api_snapshots",
            CLIENT_MONTHLY_API_SNAPSHOTS_SCHEMA,
            partition_field="month_start",
            cluster_fields=("client_slug",),
        ),
        TableSpec(
            config.memory_dataset,
            "client_finance_monthly",
            CLIENT_FINANCE_MONTHLY_SCHEMA,
            partition_field="month_start",
            cluster_fields=("client_slug", "billing_status"),
        ),
        TableSpec(
            config.memory_dataset,
            "agency_expenses_monthly",
            AGENCY_EXPENSES_MONTHLY_SCHEMA,
            partition_field="month_start",
            cluster_fields=("expense_name", "is_active"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_comms_digest_runs",
            CLIENT_COMMS_DIGEST_RUNS_SCHEMA,
            partition_field="week_start",
        ),
        TableSpec(
            config.memory_dataset,
            "client_comms_weekly_summaries",
            CLIENT_COMMS_WEEKLY_SUMMARIES_SCHEMA,
            partition_field="week_start",
            cluster_fields=("client_slug", "channel"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_roadmap_sources",
            CLIENT_ROADMAP_SOURCES_SCHEMA,
            cluster_fields=("client_slug", "source_type"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_roadmap_items",
            CLIENT_ROADMAP_ITEMS_SCHEMA,
            partition_field="planned_month",
            cluster_fields=("client_slug", "work_type", "planned_status"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_health_assets",
            CLIENT_HEALTH_ASSETS_SCHEMA,
            partition_field="snapshot_date",
            cluster_fields=("client_slug", "asset_type", "presence_status"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_runs",
            CLIENT_CRAWL_RUNS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "crawl_trigger", "crawler"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_url_snapshots",
            CLIENT_CRAWL_URL_SNAPSHOTS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "url_hash"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_issue_rows",
            CLIENT_CRAWL_ISSUE_ROWS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "issue_priority", "issue_type"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_link_rows",
            CLIENT_CRAWL_LINK_ROWS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "source_url", "destination_url"),
        ),
        TableSpec(
            config.memory_dataset,
            "client_crawl_export_rows",
            CLIENT_CRAWL_EXPORT_ROWS_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "export_name"),
        ),
        TableSpec(config.reporting_dataset, "client_task_status", REPORTING_CLIENT_TASK_STATUS_SCHEMA, partition_field="snapshot_date"),
        TableSpec(config.reporting_dataset, "client_delivery_timeline", REPORTING_CLIENT_DELIVERY_TIMELINE_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.reporting_dataset, "client_month_performance", REPORTING_CLIENT_MONTH_PERFORMANCE_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.reporting_dataset, "client_monthly_performance_summary", REPORTING_CLIENT_MONTHLY_PERFORMANCE_SUMMARY_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.reporting_dataset, "client_monthly_report_narrative", REPORTING_CLIENT_MONTHLY_REPORT_NARRATIVE_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.reporting_dataset, "client_monthly_reporting_coverage", REPORTING_CLIENT_MONTHLY_REPORTING_COVERAGE_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(
            config.reporting_dataset,
            "client_monthly_performance_history",
            REPORTING_CLIENT_MONTHLY_PERFORMANCE_HISTORY_SCHEMA,
            partition_field="month_start",
            cluster_fields=("client_slug",),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_monthly_comparison",
            REPORTING_CLIENT_MONTHLY_COMPARISON_SCHEMA,
            partition_field="month_start",
            cluster_fields=("client_slug",),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_trailing_performance",
            REPORTING_CLIENT_TRAILING_PERFORMANCE_SCHEMA,
            partition_field="month_start",
            cluster_fields=("client_slug",),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_benchmark_summary",
            REPORTING_CLIENT_BENCHMARK_SUMMARY_SCHEMA,
            partition_field="month_start",
            cluster_fields=("client_slug",),
        ),
        TableSpec(config.reporting_dataset, "reporting_readiness", REPORTING_READINESS_SCHEMA, cluster_fields=("client_slug",)),
        TableSpec(config.reporting_dataset, "ops_drift_summary", REPORTING_OPS_DRIFT_SUMMARY_SCHEMA, partition_field="snapshot_date"),
        TableSpec(
            config.reporting_dataset,
            "client_comms_attention",
            REPORTING_CLIENT_COMMS_ATTENTION_SCHEMA,
            partition_field="week_start",
            cluster_fields=("client_slug", "signal_type"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_comms_history",
            REPORTING_CLIENT_COMMS_HISTORY_SCHEMA,
            partition_field="week_start",
            cluster_fields=("client_slug", "thread_status"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_roadmap_current",
            REPORTING_CLIENT_ROADMAP_CURRENT_SCHEMA,
            partition_field="planned_month",
            cluster_fields=("client_slug", "delivery_status"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_roadmap_monthly_completion",
            REPORTING_CLIENT_ROADMAP_MONTHLY_COMPLETION_SCHEMA,
            partition_field="planned_month",
            cluster_fields=("client_slug", "status_summary"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_health_check",
            REPORTING_CLIENT_HEALTH_CHECK_SCHEMA,
            partition_field="snapshot_date",
            cluster_fields=("client_slug", "health_status"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_finance_health",
            REPORTING_CLIENT_FINANCE_HEALTH_SCHEMA,
            partition_field="month_start",
            cluster_fields=("client_slug", "finance_status"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_crawl_latest",
            REPORTING_CLIENT_CRAWL_LATEST_SCHEMA,
            partition_field="crawl_date",
            cluster_fields=("client_slug", "crawl_status"),
        ),
        TableSpec(
            config.reporting_dataset,
            "client_crawl_comparison",
            REPORTING_CLIENT_CRAWL_COMPARISON_SCHEMA,
            partition_field="current_crawl_date",
            cluster_fields=("client_slug", "comparison_status"),
        ),
    ]


def ensure_cost_checks_table(client: Any, config: BigQueryCostConfig) -> None:
    """Create the cost-check audit table if it does not already exist."""
    ensure_tables(client, config, control_table_specs(config)[:1])


def ensure_api_smoke_checks_table(client: Any, config: BigQueryCostConfig) -> None:
    """Create the API smoke-check audit table if it does not already exist."""
    ensure_tables(client, config, [TableSpec(config.control_dataset, "api_smoke_checks", API_SMOKE_CHECKS_SCHEMA)])


def ensure_agent_operating_tables(client: Any, config: BigQueryCostConfig) -> None:
    """Create the lightweight SEO Agency OS agent operating tables."""
    ensure_tables(client, config, agent_operating_table_specs(config))


def plan_agent_operating_tables(client: Any, config: BigQueryCostConfig) -> list[dict[str, Any]]:
    """Return a non-mutating plan for the lightweight agent operating tables."""
    return plan_tables(client, config, agent_operating_table_specs(config))


def plan_crawl_memory_tables(client: Any, config: BigQueryCostConfig) -> list[dict[str, Any]]:
    """Return a non-mutating plan for the technical crawl memory tables."""
    return plan_tables(client, config, crawl_memory_table_specs(config))


def ensure_monthly_api_snapshot_tables(client: Any, config: BigQueryCostConfig) -> None:
    """Create the live monthly API snapshot and reporting-history tables."""
    ensure_tables(
        client,
        config,
        [
            TableSpec(
                config.memory_dataset,
                "client_monthly_api_snapshots",
                CLIENT_MONTHLY_API_SNAPSHOTS_SCHEMA,
                partition_field="month_start",
                cluster_fields=("client_slug",),
            ),
            TableSpec(
                config.reporting_dataset,
                "client_monthly_performance_history",
                REPORTING_CLIENT_MONTHLY_PERFORMANCE_HISTORY_SCHEMA,
                partition_field="month_start",
                cluster_fields=("client_slug",),
            ),
        ],
    )


def ensure_comms_memory_tables(client: Any, config: BigQueryCostConfig) -> None:
    """Create the summarized comms memory and attention tables."""
    ensure_tables(
        client,
        config,
        [
            TableSpec(
                config.memory_dataset,
                "client_comms_digest_runs",
                CLIENT_COMMS_DIGEST_RUNS_SCHEMA,
                partition_field="week_start",
            ),
            TableSpec(
                config.memory_dataset,
                "client_comms_weekly_summaries",
                CLIENT_COMMS_WEEKLY_SUMMARIES_SCHEMA,
                partition_field="week_start",
                cluster_fields=("client_slug", "channel"),
            ),
            TableSpec(
                config.reporting_dataset,
                "client_comms_attention",
                REPORTING_CLIENT_COMMS_ATTENTION_SCHEMA,
                partition_field="week_start",
                cluster_fields=("client_slug", "signal_type"),
            ),
            TableSpec(
                config.reporting_dataset,
                "client_comms_history",
                REPORTING_CLIENT_COMMS_HISTORY_SCHEMA,
                partition_field="week_start",
                cluster_fields=("client_slug", "thread_status"),
            ),
        ],
    )


def ensure_roadmap_memory_tables(client: Any, config: BigQueryCostConfig) -> None:
    """Create the summarized client-roadmap memory and reporting tables."""
    ensure_tables(
        client,
        config,
        [
            TableSpec(
                config.memory_dataset,
                "client_roadmap_sources",
                CLIENT_ROADMAP_SOURCES_SCHEMA,
                cluster_fields=("client_slug", "source_type"),
            ),
            TableSpec(
                config.memory_dataset,
                "client_roadmap_items",
                CLIENT_ROADMAP_ITEMS_SCHEMA,
                partition_field="planned_month",
                cluster_fields=("client_slug", "work_type", "planned_status"),
            ),
            TableSpec(
                config.reporting_dataset,
                "client_roadmap_current",
                REPORTING_CLIENT_ROADMAP_CURRENT_SCHEMA,
                partition_field="planned_month",
                cluster_fields=("client_slug", "delivery_status"),
            ),
            TableSpec(
                config.reporting_dataset,
                "client_roadmap_monthly_completion",
                REPORTING_CLIENT_ROADMAP_MONTHLY_COMPLETION_SCHEMA,
                partition_field="planned_month",
                cluster_fields=("client_slug", "status_summary"),
            ),
        ],
    )


def ensure_finance_memory_tables(client: Any, config: BigQueryCostConfig) -> None:
    """Create the local finance memory and reporting tables."""
    ensure_tables(
        client,
        config,
        [
            TableSpec(
                config.memory_dataset,
                "client_finance_monthly",
                CLIENT_FINANCE_MONTHLY_SCHEMA,
                partition_field="month_start",
                cluster_fields=("client_slug", "billing_status"),
            ),
            TableSpec(
                config.memory_dataset,
                "agency_expenses_monthly",
                AGENCY_EXPENSES_MONTHLY_SCHEMA,
                partition_field="month_start",
                cluster_fields=("expense_name", "is_active"),
            ),
            TableSpec(
                config.reporting_dataset,
                "client_finance_health",
                REPORTING_CLIENT_FINANCE_HEALTH_SCHEMA,
                partition_field="month_start",
                cluster_fields=("client_slug", "finance_status"),
            ),
        ],
    )


def ensure_crawl_memory_tables(client: Any, config: BigQueryCostConfig) -> None:
    """Create the technical crawl memory and comparison tables."""
    ensure_tables(client, config, crawl_memory_table_specs(config))


def ensure_agency_ops_tables(client: Any, config: BigQueryCostConfig) -> None:
    """Create all datasets and tables used by the agency-ops memory pilot."""
    ensure_tables(client, config, agency_ops_table_specs(config))


def ensure_tables(client: Any, config: BigQueryCostConfig, specs: list[TableSpec]) -> None:
    try:
        from google.cloud import bigquery
        from google.api_core.exceptions import Conflict
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is not installed. Install requirements.txt before creating BigQuery tables."
        ) from exc

    created_datasets: set[str] = set()
    for spec in specs:
        dataset_id = f"{config.project_id}.{spec.dataset}"
        if dataset_id not in created_datasets:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = config.default_location
            try:
                client.create_dataset(dataset)
            except Conflict:
                pass
            created_datasets.add(dataset_id)

        table = bigquery.Table(
            f"{dataset_id}.{spec.table}",
            schema=[bigquery.SchemaField(name, field_type, mode=mode) for name, field_type, mode in spec.schema],
        )
        if spec.partition_field:
            table.time_partitioning = bigquery.TimePartitioning(field=spec.partition_field)
        if spec.cluster_fields:
            table.clustering_fields = list(spec.cluster_fields)
        if spec.expires_in_hours:
            table.expires = datetime.now(timezone.utc) + timedelta(hours=spec.expires_in_hours)
        try:
            client.create_table(table)
        except Conflict:
            pass
        existing = client.get_table(table)
        existing_names = {field.name for field in existing.schema}
        missing_fields = [
            bigquery.SchemaField(name, field_type, mode=mode)
            for name, field_type, mode in spec.schema
            if name not in existing_names and mode != "REQUIRED"
        ]
        if missing_fields:
            existing.schema = [*existing.schema, *missing_fields]
            client.update_table(existing, ["schema"])


def plan_tables(client: Any, config: BigQueryCostConfig, specs: list[TableSpec]) -> list[dict[str, Any]]:
    """Inspect table existence/schema drift without creating or updating anything."""
    def normalized_type(field_type: str) -> str:
        aliases = {
            "INTEGER": "INT64",
            "BOOLEAN": "BOOL",
            "FLOAT": "FLOAT64",
        }
        upper = str(field_type).upper()
        return aliases.get(upper, upper)

    plan: list[dict[str, Any]] = []
    for spec in specs:
        table_id = f"{config.project_id}.{spec.dataset}.{spec.table}"
        row: dict[str, Any] = {
            "dataset": spec.dataset,
            "table": spec.table,
            "table_id": table_id,
            "status": "unknown",
            "missing_fields": [],
            "type_or_mode_mismatches": [],
            "extra_fields": [],
            "partition_field": spec.partition_field,
            "cluster_fields": list(spec.cluster_fields),
        }
        try:
            existing = client.get_table(table_id)
        except Exception as exc:  # BigQuery NotFound type is optional in test/mocked contexts.
            if type(exc).__name__ == "NotFound":
                row["status"] = "missing"
                row["missing_fields"] = [name for name, _, _ in spec.schema]
                plan.append(row)
                continue
            raise

        expected = spec.schema_by_name
        expected = {name: (normalized_type(field_type), mode) for name, (field_type, mode) in expected.items()}
        actual = {
            field.name: (normalized_type(str(field.field_type)), str(field.mode).upper())
            for field in getattr(existing, "schema", [])
        }
        row["missing_fields"] = [name for name in expected if name not in actual]
        row["extra_fields"] = [name for name in actual if name not in expected]
        row["type_or_mode_mismatches"] = [
            {
                "field": name,
                "expected": {"type": expected_type, "mode": expected_mode},
                "actual": {"type": actual[name][0], "mode": actual[name][1]},
            }
            for name, (expected_type, expected_mode) in expected.items()
            if name in actual and actual[name] != (expected_type, expected_mode)
        ]
        row["status"] = (
            "ok"
            if not row["missing_fields"] and not row["type_or_mode_mismatches"]
            else "drift"
        )
        plan.append(row)
    return plan
