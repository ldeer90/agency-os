# BigQuery Query Cookbook

Use these examples from `/Users/laurencedeer/Projects/Codex/Big Query`.

Every query must run through the capped runner and include a plain-English `--purpose`. Keep previews small unless Laurence asks for more rows.

If credentials are not already loaded, load only the approved Google env vars from the local SEO Automation environment. Never print `.env` values or service-account JSON contents.

## What Changed Recently For A Client?

Replace `shop-rongrong` with the client slug.

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: recent client timeline for shop-rongrong" \
  --limit-preview 25 \
  --sql "SELECT event_date, client_slug, event_type, title, status, source_table, source_id FROM \`seo-agency-work.agency_reporting.client_delivery_timeline\` WHERE client_slug = 'shop-rongrong' ORDER BY event_date DESC LIMIT 25"
```

If the delivery timeline is sparse, check recent task status as supporting context:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: recent task status for shop-rongrong" \
  --limit-preview 25 \
  --sql "SELECT client_slug, board_name, item_name, group_title, status, updated_at FROM \`seo-agency-work.agency_reporting.client_task_status\` WHERE client_slug = 'shop-rongrong' ORDER BY updated_at DESC LIMIT 25"
```

## Client Task Status

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: task status summary for active clients" \
  --limit-preview 50 \
  --sql "SELECT client_slug, status, COUNT(*) AS task_count FROM \`seo-agency-work.agency_reporting.client_task_status\` GROUP BY client_slug, status ORDER BY client_slug, task_count DESC"
```

For one client:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: open tasks for ducati-melbourne" \
  --limit-preview 50 \
  --sql "SELECT client_slug, board_name, group_title, item_name, status, owner, due_date FROM \`seo-agency-work.agency_reporting.client_task_status\` WHERE client_slug = 'ducati-melbourne' AND COALESCE(normalized_status, 'Not Started') != 'Done' ORDER BY due_date, item_name LIMIT 50"
```

## Monthly Performance Comparison

Latest month by client:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: latest monthly performance by client" \
  --limit-preview 50 \
  --sql "SELECT client_slug, client_name, period_id, organic_sessions, organic_revenue, gsc_clicks, se_visibility_end FROM \`seo-agency-work.agency_reporting.client_monthly_performance_history\` QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY month_start DESC) = 1 ORDER BY client_slug"
```

Month-over-month and year-over-year comparison for one client:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: performance comparison for shop-rongrong" \
  --limit-preview 13 \
  --sql "SELECT client_slug, period_id, organic_sessions, organic_sessions_mom_delta, organic_sessions_yoy_delta, gsc_clicks, gsc_clicks_mom_delta, gsc_clicks_yoy_delta, organic_revenue, organic_revenue_mom_delta, organic_revenue_yoy_delta FROM \`seo-agency-work.agency_reporting.client_monthly_comparison\` WHERE client_slug = 'shop-rongrong' ORDER BY month_start DESC LIMIT 13"
```

All-client organic sessions direction for a month-over-month question, such as April 2026 to May 2026:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: answer April to May 2026 client organic sessions direction" \
  --limit-preview 50 \
  --sql "SELECT client_slug, client_name, CAST(ROUND(organic_sessions - organic_sessions_mom_delta) AS INT64) AS april_sessions, CAST(ROUND(organic_sessions) AS INT64) AS may_sessions, CAST(ROUND(organic_sessions_mom_delta) AS INT64) AS session_change, ROUND(organic_sessions_mom_pct * 100, 1) AS session_change_pct, CASE WHEN organic_sessions_mom_delta > 0 THEN 'up' WHEN organic_sessions_mom_delta < 0 THEN 'down' WHEN organic_sessions_mom_delta = 0 THEN 'flat' ELSE 'unknown' END AS direction, source_health FROM \`seo-agency-work.agency_reporting.client_monthly_comparison\` WHERE period_id = '2026-05' ORDER BY direction DESC, session_change DESC, client_slug"
```

For other month pairs, set `period_id` to the later month and rename the derived previous/current aliases. The comparison table stores current values plus MoM deltas, so derive the previous month as `current_metric - metric_mom_delta`.

Trailing totals:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: trailing 12 month client performance" \
  --limit-preview 50 \
  --sql "SELECT client_slug, period_id, organic_sessions_t12, gsc_clicks_t12, organic_revenue_t12 FROM \`seo-agency-work.agency_reporting.client_trailing_performance\` QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY month_start DESC) = 1 ORDER BY client_slug"
```

## Reporting Readiness

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: reporting readiness" \
  --limit-preview 50 \
  --sql "SELECT client_slug, client_name, monday_board_id, ga4_property, has_report_snapshot, latest_report_month, readiness_status FROM \`seo-agency-work.agency_reporting.reporting_readiness\` ORDER BY readiness_status, client_slug"
```

Monthly coverage from report JSON summaries:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: monthly reporting coverage" \
  --limit-preview 50 \
  --sql "SELECT client_slug, period_id, coverage_status, has_ga4, has_search_console, has_se_ranking, has_ai_referrals FROM \`seo-agency-work.agency_reporting.client_monthly_reporting_coverage\` ORDER BY period_id DESC, client_slug LIMIT 50"
```

## Comms Attention

Latest weekly client comms signals from summarized Monday/email memory:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: latest client comms attention queue" \
  --limit-preview 50 \
  --sql "SELECT week_start, week_end, client_slug, client_name, signal_type, severity, channel, category, summary, recommended_action, owner_hint, due_hint FROM \`seo-agency-work.agency_reporting.client_comms_attention\` QUALIFY RANK() OVER (ORDER BY week_start DESC) = 1 ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, client_slug, signal_type LIMIT 50"
```

The comms source table stores weekly summaries only. Do not use BigQuery to retrieve raw email bodies, Monday comments, attachments, or unredacted contact details.

Historical comms summaries, including resolved threads:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: historical summarized comms for little-shop-of-happiness" \
  --limit-preview 50 \
  --sql "SELECT week_start, week_end, client_slug, thread_status, channel, category, summary, recommended_action, resolution_summary, latest_event_at FROM \`seo-agency-work.agency_reporting.client_comms_history\` WHERE client_slug = 'little-shop-of-happiness' ORDER BY latest_event_at DESC LIMIT 50"
```

## Client Roadmaps

Current open roadmap work for a client/month:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: current June roadmap work for little-shop-of-happiness" \
  --limit-preview 50 \
  --sql "SELECT planned_month, client_slug, item_title, work_type, priority, delivery_status, owner_hint, due_date, target_url, keyword_theme, completion_summary FROM \`seo-agency-work.agency_reporting.client_roadmap_current\` WHERE client_slug = 'little-shop-of-happiness' AND planned_month = DATE '2026-06-01' AND delivery_status NOT IN ('completed', 'deferred', 'cancelled') ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, due_date, item_title"
```

Check whether agreed roadmap work was completed for a month:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: May 2026 agreed roadmap completion by client" \
  --limit-preview 50 \
  --sql "SELECT planned_month, client_slug, client_name, planned_items, completed_items, missing_evidence_items, overdue_items, ROUND(completion_rate * 100, 1) AS completion_rate_pct, status_summary FROM \`seo-agency-work.agency_reporting.client_roadmap_monthly_completion\` WHERE planned_month = DATE '2026-05-01' ORDER BY status_summary, client_slug"
```

Roadmap memory stores structured agreed-work summaries only. Do not use BigQuery to retrieve raw Drive roadmap sheet/doc bodies.

## Client Health Check

Latest active reporting-client setup health across the agency brain:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: latest client health check" \
  --limit-preview 50 \
  --sql "SELECT snapshot_date, client_slug, client_name, health_status, ROUND(health_score * 100, 1) AS health_score_pct, critical_missing_assets, missing_required_assets, has_drive_root, has_drive_root_verified, has_roadmap_route, has_roadmap_folder_verified, has_roadmap_files, has_roadmap_content_validated, has_ga4_property, has_ga4_access, has_search_console, has_search_console_access, has_se_ranking, has_se_ranking_access, missing_required_json, latest_report_month FROM \`seo-agency-work.agency_reporting.client_health_check\` QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1 ORDER BY CASE health_status WHEN 'critical_missing' THEN 1 WHEN 'needs_attention' THEN 2 WHEN 'partial' THEN 3 ELSE 4 END, missing_required_assets DESC, client_slug"
```

Asset-level drilldown for one client:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: missing brain assets for little-shop-of-happiness" \
  --limit-preview 50 \
  --sql "SELECT snapshot_date, asset_type, asset_label, presence_status, expected, criticality, verification_level, verified_at, verification_method, source_system, source_path, freshness_date, notes FROM \`seo-agency-work.agency_memory.client_health_assets\` WHERE client_slug = 'little-shop-of-happiness' QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1 ORDER BY expected DESC, CASE criticality WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, asset_type"
```

The health layer is scoped to active clients in `seo-reporting-platform/config/clients.json` and stores file/folder/config metadata only. Do not use it to retrieve raw Drive docs, Sheets contents, Monday updates/comments, email content, or secrets.

Clients missing verified populated roadmap files:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: clients missing verified populated roadmap files" \
  --limit-preview 50 \
  --sql "SELECT snapshot_date, client_slug, client_name, health_status, has_roadmap_route, has_roadmap_folder_verified, has_roadmap_files, has_roadmap_content_validated, missing_required_json FROM \`seo-agency-work.agency_reporting.client_health_check\` WHERE has_roadmap_files = FALSE OR has_roadmap_content_validated = FALSE QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1 ORDER BY client_slug"
```

`has_roadmap_route` only means the sidecar has a configured roadmap folder. `has_roadmap_folder_verified` requires Drive MCP folder metadata. `has_roadmap_files` requires Drive MCP file metadata from `data/client_health/drive_folder_verifications.json`. `has_roadmap_content_validated` requires bounded content validation metadata, never raw Sheet/Doc content. Service-account folder checks are not valid evidence that a roadmap folder is empty or populated.

Route-only health gaps:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: route-only client health gaps" \
  --limit-preview 50 \
  --sql "SELECT client_slug, client_name, has_drive_root, has_drive_root_verified, has_roadmap_route, has_roadmap_folder_verified, has_roadmap_files, has_roadmap_content_validated, has_content_route, has_content_folder_verified, has_reports_route, has_reports_folder_verified, has_monday_board, has_monday_board_snapshot, has_ga4_property, has_ga4_access, has_search_console, has_search_console_access, has_se_ranking, has_se_ranking_access FROM \`seo-agency-work.agency_reporting.client_health_check\` QUALIFY RANK() OVER (ORDER BY snapshot_date DESC) = 1 ORDER BY client_slug"
```

Latest verification-level counts:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent question: client health verification level counts" \
  --limit-preview 50 \
  --sql "SELECT asset_type, verification_level, presence_status, COUNT(*) AS row_count FROM \`seo-agency-work.agency_memory.client_health_assets\` WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM \`seo-agency-work.agency_memory.client_health_assets\`) GROUP BY asset_type, verification_level, presence_status ORDER BY asset_type, verification_level, presence_status"
```

Local preflight before ingesting:

```bash
.venv/bin/python scripts/validate_client_health_verifications.py
```

Normal `scripts/ingest_agency_ops.py` runs this preflight automatically unless `--skip-health-verification-preflight` is used for diagnostics.

## Finding Source Tables And Freshness

List agency tables:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent check: list agency memory and reporting tables" \
  --limit-preview 100 \
  --sql "SELECT table_schema, table_name, creation_time FROM \`seo-agency-work.region-australia-southeast1\`.INFORMATION_SCHEMA.TABLES WHERE table_schema IN ('agency_control', 'agency_memory', 'agency_reporting') ORDER BY table_schema, table_name"
```

Latest ingestion runs:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent check: latest agency ingestion runs" \
  --limit-preview 25 \
  --sql "SELECT run_id, source_id, status, started_at, completed_at, destination_table, rows_loaded, error_message FROM \`seo-agency-work.agency_control.ingestion_runs\` ORDER BY started_at DESC LIMIT 25"
```

Latest cost checks:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "agent check: latest cost guardrail logs" \
  --limit-preview 25 \
  --sql "SELECT logged_at, purpose, status, estimated_bytes, cap_bytes, job_id FROM \`seo-agency-work.agency_control.cost_checks\` ORDER BY logged_at DESC LIMIT 25"
```

## Safety Notes

- Do not query raw staging tables for routine agent answers.
- Prefer `agency_reporting` first, then `agency_memory` when more detail is needed.
- Keep `--limit-preview` low.
- Do not add `--admin-cap-10gb` unless Laurence explicitly approves a broader query.
- Do not use these queries to retrieve raw Drive, Docs, email, Monday updates, comments, or item descriptions.
