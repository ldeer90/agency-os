# Agency Ops Memory V1

This workflow loads local agency-ops snapshots into BigQuery as a one-way memory layer.

## Agent Handoff Docs

- `../AGENTS.md`: local operating guide for future Codex agents.
- `../HANDOVER.md`: current warehouse state, known good checks, and next work.
- `QUERY_COOKBOOK.md`: capped-runner-safe BigQuery examples for common agent questions.
- `DRIVE_FILING_GUIDE.md`: Google Drive routing rules for reports and delivery files.
- `SEO_AGENCY_OS_OPERATING_LAYER.md`: lightweight agent workflow layer for daily briefs, promise tracking, and suggested actions.

## Source Of Truth

| Area | Source of truth | BigQuery role |
| --- | --- | --- |
| Task status | monday.com snapshots from `monday-agency-hub` | Read-only mirror for reporting and agent memory |
| Client routing/access | SEO Automation client briefs and sidecars | Curated client registry |
| Monthly performance | SEO Reporting Platform report JSON | Reporting snapshot history |
| Client roadmaps | SEO Automation roadmap workflow, client Drive roadmap folders, and staged summary-only roadmap JSONL | Structured agreed-work memory and monthly completion checks |
| Client health assets | SEO Automation sidecars/briefs/timelines plus SEO Reporting config/report metadata | Presence/freshness checklist for the assets the agency brain expects |
| SEO Automation workflow metadata | SEO Automation routing manifest, workflow docs, client sidecars, and sanitized timeline summaries | Workflow catalog, client readiness, and opportunity queues |
| Google Drive filing | SEO Automation client briefs, sidecars, and Drive filing rules | Metadata-only route memory later; no raw Drive contents |

BigQuery does not write back to monday.com in v1.

## Privacy Boundaries

The V1 loader does not ingest monday item descriptions, updates, comments, or Drive/Docs contents.

For monday item column values, it keeps operational fields such as status, owner, dates, time tracking, and explicit client URLs. Free-text notes and email/phone/location-style fields are excluded from column-value rows. File columns are reduced to presence metadata.

## V2 Summarized Roadmap Memory Boundary

Client roadmaps may be loaded only as structured, sanitized agreed-work items. Raw Google Docs/Sheets bodies, private notes, unredacted client contact details, and long copied roadmap text remain excluded.

Allowed roadmap memory fields are client/month, item title, work type, priority, planned status, due date, owner hint, target URL, keyword/theme hint, short paraphrased notes, source type/title, Drive file/folder IDs, hashed source references, completion evidence type/ref, completion summary, and confidence. The loader validates staged JSONL and hard-fails rows containing likely raw private content, credentials, phone-heavy text, raw email addresses, unsafe URLs, or overlong summaries.

## Client Health Asset Boundary

Client health records store metadata-only presence checks for the active recurring reporting clients in `seo-reporting-platform/config/clients.json`. The layer intentionally excludes internal projects, parent brands, pending clients, publisher/prospect entities, board-only Monday accounts, and support docs.

For each active reporting client, health checks cover the assets the agency brain and agency operations expect: sidecar JSON, client brief, timeline, optional writing-style guide, Drive root/roadmap/content/report folder routes, verified Drive folders, verified populated roadmap files, bounded roadmap content validation, Monday board route and snapshot proof, reporting config, GA4/Search Console/SE Ranking routes and smoke checks, monthly report snapshot, and loaded roadmap items.

Health rows may store local file paths, public/client platform IDs already present in approved sidecars/config, hashed source refs, file/folder metadata, freshness dates, and short operational notes. They must not store raw Drive/Docs/Sheets contents, Sheet cell values, client document bodies, Drive comments, permissions payloads, Monday updates/comments, email contents, credential values, or unredacted contact details.

Every health asset carries verification metadata:

- `verification_level`: `route_config`, `local_content`, `metadata_verified`, `bounded_content_validated`, `api_smoke`, or `warehouse_derived`.
- `verified_at`: timestamp for connector/API verification when available.
- `verification_method`: short method name such as `json_parse_required_fields`, `drive_mcp_file_metadata`, or `smoke_reporting_apis`.

Use `unknown` when verification has not been run or no safe evidence is present. Use `missing` only when trusted evidence proves absence, failed access, empty content, or invalid structure.

Roadmap folder routes are not enough to mark a client as roadmap-ready. `drive_roadmap_folder` means the sidecar has a configured route only. `drive_roadmap_folder_verified` means Google Drive MCP metadata verified the folder exists/access works. `drive_roadmap_files` means Google Drive MCP metadata verified that the folder contains one or more populated roadmap files. `drive_roadmap_content` means bounded validation checked headers/limited rows or snippets and stored only validation metadata. If Drive MCP verification evidence is missing, the verified/content assets must be `unknown`; if the folder or file is empty/unusable, they must be `missing`.

API route assets are also separate from API access assets. `ga4_property`, `search_console`, and `se_ranking` are route/config evidence. `ga4_access`, `search_console_access`, and `se_ranking_access` require sanitized read-only smoke evidence from `data/client_health/api_smoke_verifications.json` or the approved smoke workflow.

## V2 Summarized Comms Memory Boundary

Summarized client communications are allowed only through the comms-memory workflow. Raw Monday updates/comments, raw email bodies, raw email addresses, attachments, and verbatim private-message excerpts remain excluded.

Allowed comms memory fields are weekly agent-written summaries, categories, client slugs, channels, urgency, follow-up flags, source counts, confidence, recommended actions, owner/due hints, thread state, timestamps, resolution summaries, and hashed source references. The loader validates staged JSONL and hard-fails rows that look like raw email/Monday content, long quotes, credentials, phone-heavy text, raw email addresses, or overlong summaries.

## Commands

Parse local sources only:

```bash
.venv/bin/python scripts/ingest_agency_ops.py --local-dry-run
```

The normal dry-run and live load run `scripts/validate_client_health_verifications.py` first. That preflight fails if required Drive/API verification assets are still `unknown`, so the inventory cannot silently fall back from verified evidence to route-only evidence. Use `--skip-health-verification-preflight` only for diagnostics.

Create/verify BigQuery datasets and tables:

```bash
.venv/bin/python scripts/ingest_agency_ops.py \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env" \
  --ensure-only
```

Run the full V1 load and capped mart build:

```bash
.venv/bin/python scripts/ingest_agency_ops.py \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Default write mode is `WRITE_TRUNCATE`, making repeated V1 loads idempotent. Use `--write-disposition WRITE_APPEND` only when intentionally building historical snapshots.

## BigQuery Tables

Control:

- `agency_control.data_sources`
- `agency_control.ingestion_runs`
- `agency_control.cost_checks`

Memory:

- `agency_memory.monday_boards`
- `agency_memory.monday_board_columns`
- `agency_memory.monday_status_labels`
- `agency_memory.monday_items`
- `agency_memory.monday_item_column_values`
- `agency_memory.client_registry`
- `agency_memory.client_board_map`
- `agency_memory.task_alignment`
- `agency_memory.client_timeline_events`
- `agency_memory.monthly_report_snapshots`
- `agency_memory.client_comms_digest_runs`
- `agency_memory.client_comms_weekly_summaries`
- `agency_memory.client_roadmap_sources`
- `agency_memory.client_roadmap_items`
- `agency_memory.client_health_assets`

Reporting:

- `agency_reporting.client_task_status`
- `agency_reporting.client_delivery_timeline`
- `agency_reporting.client_month_performance`
- `agency_reporting.client_monthly_performance_summary`
- `agency_reporting.client_monthly_report_narrative`
- `agency_reporting.client_monthly_reporting_coverage`
- `agency_reporting.client_comms_attention`
- `agency_reporting.client_comms_history`
- `agency_reporting.client_roadmap_current`
- `agency_reporting.client_roadmap_monthly_completion`
- `agency_reporting.client_health_check`
- `agency_reporting.reporting_readiness`
- `agency_reporting.ops_drift_summary`

All reporting marts are built through the capped BigQuery runner.

## Monthly Performance Layer

The preferred agent-facing monthly performance tables are:

- `agency_reporting.client_monthly_performance_summary`: one row per client/month with flat GA4, Search Console, SE Ranking, and AI referral metrics.
- `agency_reporting.client_monthly_report_narrative`: report summary, completed work, next focus, and caveats.
- `agency_reporting.client_monthly_reporting_coverage`: source coverage flags and caveats.

These tables are built from existing SEO Reporting Platform report JSON in `agency_memory.monthly_report_snapshots`. They do not call GA4, Search Console, or SE Ranking directly.

Run a read-only live API smoke check after performance mart changes:

```bash
.venv/bin/python scripts/smoke_reporting_apis.py \
  --client shop-rongrong \
  --log-bigquery
```

The smoke command checks GA4, Search Console, and SE Ranking with one small request each. It prints only status/count metadata and can log sanitized results to `agency_control.api_smoke_checks`.

## 13-Month Live Performance History

For comparative analysis, pull live monthly API summaries into:

- `agency_memory.client_monthly_api_snapshots`
- `agency_reporting.client_monthly_performance_history`
- `agency_reporting.client_monthly_comparison`
- `agency_reporting.client_trailing_performance`
- `agency_reporting.client_benchmark_summary`

Default behavior uses the **last 13 complete calendar months**. On June 12, 2026, that means May 2025 through May 2026. The current partial month is excluded.

Plan the run without API calls or BigQuery writes:

```bash
.venv/bin/python scripts/load_monthly_api_snapshots.py --dry-run
```

Run the live pull for all active reporting clients:

```bash
.venv/bin/python scripts/load_monthly_api_snapshots.py
```

The script reads active clients from `seo-reporting-platform/config/clients.json`, calls GA4, Search Console, and SE Ranking read-only APIs, loads one row per client/month, and builds the reporting history mart through the capped BigQuery runner. It does not write source report JSON, Monday, Drive, or client files.

For analysis, use:

- `agency_reporting.client_monthly_comparison` for MoM and YoY deltas.
- `agency_reporting.client_trailing_performance` for rolling 3, 6, and 12 month totals.
- `agency_reporting.client_benchmark_summary` for latest-month client rankings and status.

## Weekly Summarized Comms Memory

Staged summaries from the `comms-activity-digest` workflow load through:

```bash
.venv/bin/python scripts/load_comms_digest.py \
  --input-jsonl data/comms_memory/staging/client_comms_weekly_summaries_YYYY-MM-DD_YYYY-MM-DD.jsonl \
  --week-start YYYY-MM-DD \
  --week-end YYYY-MM-DD \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Use `--dry-run` first to validate summary JSONL without BigQuery writes. Successful loads append to `agency_memory.client_comms_weekly_summaries`, record `agency_memory.client_comms_digest_runs`, enforce 13-month retention, and rebuild `agency_reporting.client_comms_attention` and `agency_reporting.client_comms_history`.

`client_comms_attention` is a current-state queue. It groups by client and thread reference, keeps only the latest thread state, and excludes rows whose latest `thread_status` is `resolved` or `fyi`. Use `client_comms_history` when you need the audit trail of weekly summaries and resolved conversations.

## SEO Automation Workflow Memory

SEO Automation remains the source of truth for workflow docs, client briefs, sidecars, timelines, access routes, and specialist scripts. AgencyOS stores only sanitized operating extracts:

- `agency_memory.seo_workflow_catalog`: workflow family, source doc path, dependencies, validators, write gates, and proof fields.
- `agency_memory.seo_client_memory_summaries`: client route/status metadata, deliverable metadata, and recent timeline summaries.
- `agency_memory.seo_workflow_run_summaries`: future sanitized run outcomes from wrapped SEO Automation workflows.
- `agency_reporting.seo_workflow_readiness`: client readiness/blocker queue.
- `agency_reporting.seo_opportunity_queue`: suggested SEO Automation workflow opportunities.

Do not load raw client timeline markdown, raw Drive/Docs/Sheets contents, raw Gmail/Outlook/Monday conversations, credentials, or long private notes into these tables.

## Client Roadmap Memory

Staged roadmap items load through:

```bash
.venv/bin/python scripts/load_client_roadmaps.py \
  --input-jsonl data/roadmap_memory/staging/client_roadmap_items_YYYY-MM.jsonl \
  --planned-month YYYY-MM \
  --source-type drive_sheet \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Use `--dry-run` first to validate the JSONL without BigQuery writes. Successful loads append to `agency_memory.client_roadmap_items`, derive `agency_memory.client_roadmap_sources`, and rebuild `agency_reporting.client_roadmap_current` plus `agency_reporting.client_roadmap_monthly_completion` through the capped BigQuery runner.

`client_roadmap_current` is the forward-looking work queue. It keeps the latest row per roadmap item and marks items completed when explicit completion evidence exists or when a matching task/timeline delivery appears for that client/month. `client_roadmap_monthly_completion` rolls those rows up so agents can check whether the agreed work for a month was completed.

## Client Health Check

The normal agency-ops ingestion now populates:

- `agency_memory.client_health_assets`: one row per client/asset/check with presence, criticality, source metadata, and freshness date.
- `agency_reporting.client_health_check`: one row per client with health score, status, missing required/optional assets, route booleans, verified metadata booleans, content-validation booleans, and API-smoke booleans for key brain dependencies.

Run it with the normal full refresh:

```bash
.venv/bin/python scripts/ingest_agency_ops.py \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Use this layer to find setup gaps before relying on an active reporting client in the agency brain. It is an inventory/checklist layer, not a replacement source of truth for Drive, Monday, reporting config, or client files.

Drive folder verification metadata lives at `data/client_health/drive_folder_verifications.json`. Build it only from Google Drive MCP folder/file metadata checks plus approved bounded validation metadata. Do not use service-account folder listing as proof that a folder is empty. Do not store raw roadmap document bodies or Sheet cells for this inventory layer.

Sanitized API smoke verification metadata lives at `data/client_health/api_smoke_verifications.json`. Empty checks mean the access smoke has not been run or approved for the local manifest yet, so API access assets remain `unknown`.

Before any normal refresh, this command should pass:

```bash
.venv/bin/python scripts/validate_client_health_verifications.py
```
