# BigQuery Agency Memory Handover

Last updated: 2026-06-16.

This folder manages Laurence Deer's BigQuery agency memory for project `seo-agency-work`. It is designed for low-cost, read-only agency ops and performance reporting.

## Current State

Datasets:

- `agency_control`: source registry, ingestion runs, cost checks, API smoke checks.
- `agency_staging`: temporary load tables with expiry.
- `agency_memory`: durable normalized memory tables.
- `agency_reporting`: small agent-facing reporting marts.

Guardrails:

- BigQuery pricing mode: on-demand.
- Budget target: A$10/month with alert-only budget setup.
- Normal query cap: `1 GB/query`.
- Admin/manual cap: `10 GB/query` with explicit `--admin-cap-10gb`.
- All ad hoc SQL should run through `scripts/bq_capped_query.py`.

Local operating-layer MVP:

- Lightweight agent specs now live in `agents/`.
- Versioned prompts now live in `prompts/`.
- Safe operating permissions live in `config/permissions.yaml`.
- `scripts/run_promise_tracker.py` runs a dry-run Promise Tracker from summarized comms.
- `scripts/run_daily_agency_brief.py` writes a dry-run daily brief to `reports/daily/`.
- `scripts/run_system_admin_agent.py` runs a read-only AgencyOS core system sweep and writes local JSON/Markdown reports to `reports/system_admin/`.
- Monday task oddities are currently surfaced as `monday_hygiene` cleanup candidates, not delivery failures.
- Shared validation and output helpers live in `agency_bigquery/agent_ops.py`.
- Agent operating table definitions are available for `agent_run_log`, `agent_findings`, `agent_actions`, `agent_approvals`, `context_packs`, and `llm_usage_log`.
- Agent BigQuery logging uses `agency_bigquery/agent_logging.py`: dry-run validation by default, allowed tables only, row/payload caps, staging tables, and idempotent `MERGE` through the capped query runner.
- Local agent activity is visible with `scripts/agent_activity_today.py`; metadata lives in `data/agent_runs/index.json` and active markers live in `data/agent_runs/active/`.
- This folder is now initialized as a standalone local Git repo on `main`; no commit or remote has been created yet.

Model routing:

- Use `gpt-5.5` with `low` reasoning for normal read-only BigQuery lookups and reporting questions.
- Use `gpt-5.5` with `medium` reasoning for schemas, loaders, marts, API smoke scripts, or implementation changes.
- Use `gpt-5.5` with `high` reasoning for privacy, credential, Drive write-safety, cost-guardrail, or source-of-truth reviews.
- Close subagents after use so the thread pool stays available.

## 2026-06-16 Activity Log

Headroom context-compression evaluation and rollout:

- Created a fenced local pilot in `experiments/headroom-eval/` with safe real-shaped fixtures for BigQuery health output, Monday task metadata, crawl summaries, reporting performance summaries, and terminal logs.
- Added repeatable fixture and evaluation scripts:
  - `experiments/headroom-eval/scripts/make_safe_fixtures.py`
  - `experiments/headroom-eval/scripts/evaluate_headroom.py`
- Ran the evaluation with real Headroom from an isolated experiment venv and confirmed all five fixtures preserved required facts with no privacy flags.
- Latest fixture results:
  - `bigquery_health.json`: 51.2% saved, preserve pass.
  - `crawl_summary.json`: 62.1% saved, preserve pass.
  - `monday_metadata.json`: 58.9% saved, preserve pass.
  - `reporting_performance.json`: 65.5% saved, preserve pass.
  - `terminal_logs.json`: 90.2% saved, preserve pass.
- Decided Headroom is useful for bulky safe outputs, but not for raw credentials, raw Drive/Docs/email content, Monday comments/updates, or live BigQuery runner internals.
- Installed a central Headroom runtime from Codex Master at `/Users/laurencedeer/Projects/Codex/Codex Master/tools/headroom-runtime/.venv`.
- Backed up Codex config to `/Users/laurencedeer/.codex/config.toml.headroom-backup-20260616-050250`, then registered Codex to use the local Headroom provider at `http://127.0.0.1:8787/v1`.
- Installed Headroom persistent service profile `default`; health checks reported `running` and `Healthy: yes` on `127.0.0.1:8787`.
- Added Codex Master monitoring and launcher helpers:
  - `/Users/laurencedeer/Projects/Codex/Codex Master/scripts/headroom_codex_proxy.sh`
  - `/Users/laurencedeer/Projects/Codex/Codex Master/scripts/codex_with_headroom.sh`
  - `/Users/laurencedeer/Projects/Codex/Codex Master/scripts/headroom_run_report.py`
- Ran CLI smoke tests from both `Big Query` and `SEO Automation`; both routed through provider `headroom` and returned `HEADROOM_SMOKE_OK`.
- Current smoke-run monitor result from Codex Master: 6 requests, 127,030 input tokens before optimization, 126,558 after, 472 saved, p95 latency about 4.5 seconds, 0 errors, and no message-content logging detected.
- No live BigQuery queries were run for the Headroom work, and no cost-check rows were written.

Other Codex/AgencyOS activity visible in the working tree:

- `system_admin_agent`, `content_research_agent`, and `content_writer_agent` local agent files/prompts/scripts/tests are present as uncommitted work.
- Dashboard/API sync, scoring, UI, and publish-related files are present as uncommitted work.
- Finance load work is present locally, including `scripts/load_client_finance.py`, finance tests, and `data/finance/`.
- A content refresh note exists at `docs/avenue-hampers-fathers-day-dad-content-refresh-2026-06-16.md`.
- These existing changes were treated as user/local work and were not reverted or committed during the Headroom rollout.

## Key Tables

Agency ops memory:

- `agency_memory.client_registry`
- `agency_memory.client_board_map`
- `agency_memory.client_timeline_events`
- `agency_memory.monday_boards`
- `agency_memory.monday_board_columns`
- `agency_memory.monday_status_labels`
- `agency_memory.monday_items`
- `agency_memory.monday_item_column_values`
- `agency_memory.monthly_report_snapshots`
- `agency_memory.client_comms_digest_runs`
- `agency_memory.client_comms_weekly_summaries`
- `agency_memory.client_roadmap_sources`
- `agency_memory.client_roadmap_items`
- `agency_memory.client_health_assets`
- `agency_memory.client_finance_monthly`
- `agency_memory.agency_expenses_monthly`

Agent-facing reporting:

- `agency_reporting.client_task_status`
- `agency_reporting.client_delivery_timeline`
- `agency_reporting.client_month_performance`
- `agency_reporting.client_monthly_performance_summary`
- `agency_reporting.client_monthly_report_narrative`
- `agency_reporting.client_monthly_reporting_coverage`
- `agency_reporting.client_monthly_performance_history`
- `agency_reporting.client_monthly_comparison`
- `agency_reporting.client_trailing_performance`
- `agency_reporting.client_benchmark_summary`
- `agency_reporting.client_comms_attention`
- `agency_reporting.client_comms_history`
- `agency_reporting.client_roadmap_current`
- `agency_reporting.client_roadmap_monthly_completion`
- `agency_reporting.client_health_check`
- `agency_reporting.client_finance_health`
- `agency_reporting.reporting_readiness`
- `agency_reporting.ops_drift_summary`

## Recent Known Good State

- Monthly live performance history was loaded for 9 active reporting clients.
- `agency_reporting.client_monthly_performance_history`: 117 rows.
- `agency_reporting.client_monthly_comparison`: 117 rows.
- `agency_reporting.client_trailing_performance`: 117 rows.
- `agency_reporting.client_benchmark_summary`: 9 rows.
- The latest 13-month period covered May 2025 through May 2026. The current partial month was intentionally excluded.
- Recent successful 13-month loader run ID: `edae8f1756194809b9e4fd43139ba508`.
- Earlier 13-month loader run ID: `a96eff21b5d241bba0ddcdac3e61fab3`.
- Shop Rongrong API smoke succeeded for GA4, Google Search Console, and SE Ranking, and wrote sanitized smoke-check rows.

## Client Notes

- Ducati Melbourne uses the public legacy domain `ducatimelbourne.com.au`, but the active Search Console route should use `sc-domain:joerascalducati.com.au` because the domain redirected.
- The loader fallback produced 13/13 successful GSC months for Ducati after that correction.
- BigQuery should keep client aliases and redirects visible for future analysis, but SEO Automation client briefs and sidecars remain the routing source of truth.
- Client roadmap memory now has a summary-only staging loader. It is ready for structured roadmap rows from Drive sheets/docs, but raw roadmap document bodies should not be stored in BigQuery.
- Client health check tracks metadata-only presence of the assets the agency brain expects for active recurring reporting clients only. Its authoritative client set is `seo-reporting-platform/config/clients.json`; internal, parent, pending, publisher, board-only, and support-doc entities are excluded.
- Client health assets now distinguish route/config evidence from verified evidence with `verification_level`, `verified_at`, and `verification_method`. Route assets such as Drive folder IDs, Monday board IDs, GA4 properties, Search Console routes, and SE Ranking project IDs do not prove access.
- Verified companion assets include Drive folder metadata checks, bounded roadmap content validation, local Monday board snapshot proof, and sanitized GA4/Search Console/SE Ranking API smoke checks. Missing live verification evidence should remain `unknown`, not be silently treated as present.
- Normal `scripts/ingest_agency_ops.py` runs `scripts/validate_client_health_verifications.py` before dry-runs and live loads, blocking required verified Drive/API assets that are still `unknown`. Use `--skip-health-verification-preflight` only for diagnostics.
- Latest live health-hardening refresh run ID: `089d8f8cace146b1a0d5b80b591c256e`.
- Client finance retainers are loaded into BigQuery from `data/finance/client_retainers_2026.json` with current/future retainer amounts overlaid from the local Monday Client Board snapshot `board_5026765711.json`.
- Agency operating expenses are loaded into `agency_memory.agency_expenses_monthly` from the local Monday Expenses board snapshot at `/Users/laurencedeer/Projects/Codex/monday-agency-hub/data/snapshots/board_5027236764.json`.
- Latest finance load run ID: `44dc8718df044e33b963e72ffb1e9a22`.
- `agency_memory.client_finance_monthly`: 120 rows.
- `agency_memory.agency_expenses_monthly`: 221 rows.
- `agency_reporting.client_finance_health`: 120 rows.
- Current 13-month finance projection has A$239,240 billable retainers and A$35,954.50 active projected Monday expenses. TravelKon is projected at A$14,200/month from August 2026 through January 2027, and other primary client retainers are projected flat into January 2027 unless Laurence says otherwise.

## Source Of Truth Rules

- Monday remains the task source of truth. BigQuery mirrors snapshots only.
- SEO Automation remains the source of truth for client routing, access, Drive folders, and workflow rules.
- SEO Reporting Platform report JSON remains the source of truth for published monthly reports.
- BigQuery reporting marts are the preferred read layer for future agents.
- BigQuery must not write back to Monday or Google Drive in V1.

## Google Drive Filing

Before creating or filing reports, read `docs/DRIVE_FILING_GUIDE.md`.

Important defaults:

- Canonical tree: `My Drive / Agents Digital / Clients`.
- Output owner: `hello@agents.digital`.
- Primary working account for most client access: `seo@agents.digital`.
- Folder routes should come from SEO Automation client briefs/sidecars and `config/drive_filing_rules.json`.
- Use Google Drive MCP folder checks with `parentId='<folder_id>'` where possible.
- For roadmap/report-like health checks, bounded validation may inspect headers plus 10-20 non-empty rows or small headings/snippets, but only validation metadata may be stored.
- Do not use BigQuery as a Drive writer or raw Drive content store.

## Useful Commands

Local parser check:

```bash
.venv/bin/python scripts/ingest_agency_ops.py --local-dry-run
```

Strict health verification preflight:

```bash
.venv/bin/python scripts/validate_client_health_verifications.py
```

Unit tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Dry-run operating layer:

```bash
.venv/bin/python scripts/run_promise_tracker.py
.venv/bin/python scripts/run_daily_agency_brief.py
.venv/bin/python scripts/run_system_admin_agent.py --dry-run
```

Refresh local Monday snapshots, then load finance retainers and Monday board costs:

```bash
cd "/Users/laurencedeer/Projects/Codex/monday-agency-hub"
./scripts/map_workspace.sh

cd "/Users/laurencedeer/Projects/Codex/Big Query"
.venv/bin/python scripts/load_client_finance.py --dry-run
.venv/bin/python scripts/load_client_finance.py
```

Offline operating-layer validation:

```bash
.venv/bin/python scripts/validate_operating_layer.py
.venv/bin/python -m compileall agency_bigquery scripts tests
```

Plan/ensure agent operating tables:

```bash
.venv/bin/python scripts/manage_agent_operating_tables.py \
  --plan \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Record an approval decision without executing external work:

```bash
.venv/bin/python scripts/record_agent_approval.py \
  --action-id ACTION_ID \
  --run-id RUN_ID \
  --client-slug CLIENT_SLUG \
  --decision approved
```

Safe ad hoc BigQuery query:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "handover: verify latest ingestion runs" \
  --limit-preview 10 \
  --sql "SELECT source_id, status, started_at, completed_at, rows_loaded FROM \`seo-agency-work.agency_control.ingestion_runs\` ORDER BY started_at DESC LIMIT 10"
```

## Recommended Next Work

1. Run the first weekly comms summarizer dry run and inspect the staged JSONL validation result before trusting the automation cadence.
2. Run the first client roadmap extraction dry run from one Drive roadmap sheet, stage summary-only JSONL, and load it with `scripts/load_client_roadmaps.py`.
3. Review `agency_reporting.client_health_check` after each full refresh and backfill missing high-criticality client assets first, separating route gaps from metadata/content/API verification gaps.
4. Add metadata-only Drive route memory, probably `agency_memory.client_drive_routes`, sourced from SEO Automation sidecars and Drive filing rules.
5. Run the first approved `manage_agent_operating_tables.py --plan`, review missing/drifted agent tables, then run `--ensure` only after the plan is accepted.
6. Run one approved Daily Agency Brief with `--from-bigquery --write-bigquery --ensure-tables`, then verify cost-check rows and agent log row counts through `scripts/bq_capped_query.py`.
7. Add Codex Automations for weekday Daily Agency Brief, weekly Promise Review, and weekly Monday Hygiene Review after the first BigQuery logging run is verified.
8. Add a reporting automation workflow that creates client-ready summaries from `agency_reporting.client_monthly_performance_history`.
9. Add a Drive filing readback step for generated reports: record title, file ID, URL, folder route, created timestamp, and proof of readback, but never raw document contents.
10. After the first manual `system_admin_agent` dry run is reviewed, add a weekly read-only automation for the system admin sweep.
11. Keep expanding `docs/QUERY_COOKBOOK.md` with real questions future agents ask.
