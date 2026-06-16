# SEO Agency OS Operating Layer

This layer adds controlled Codex workflows around the existing BigQuery agency memory. It does not replace the ingestion pipeline, Monday, Gmail, Drive, Docs, or existing reporting marts.

## Operating Pattern

```text
identify active agent
→ select required skills
read approved summaries and marts
→ build a small context pack
→ create findings and suggested actions
→ run QA guardrails
→ write local report/output
→ optionally log to BigQuery after validation
→ require approval before external action
```

## Agent Hierarchy

```text
agency_supervisor
→ seo_workflow_router
→ specialist agents
→ qa_guardrail
→ approval/action queue
```

`agency_supervisor` is the SEO lead agent. It receives validated specialist findings, prioritises the daily or weekly operating view, and does not execute external actions.

`seo_workflow_router` is the intake/router. It maps requests and operating signals to canonical SEO Automation workflows and the safest AgencyOS specialist.

`qa_guardrail` is the validation stage for evidence, source boundaries, target systems, duplicate actions, and approval status.

See `AGENT_POOL_REGISTRY.md` for the status of every agent.

## Identity And Delegation

Every substantive AgencyOS task should show which agent is currently doing the work. Use a short identity line in chat and handoffs:

```text
`reporting_prep_agent` reporting for work: checking monthly reporting gaps.
```

`agency_supervisor` orchestrates broad tasks and delegates to specialists when the work can be inspected independently. Specialist agents should be used as actual subagents when parallel read-only checks, specialist review, or source-specific judgment would improve the result. The supervisor must review delegated findings before live BigQuery loads, code changes, approval queues, reports, or external actions.

Delegated subagents must get a bounded task, source scope, stop condition, and compact output contract. Do not use subagents for tiny linear tasks or for unsupervised external writes.

Agents must load the relevant Codex skill instructions before work that matches a skill. Credential awareness is location-only: use the repo credential table and the master credential location map as sanitized maps, and never print raw `.env` values, service-account JSON contents, OAuth tokens, cookies, secret headers, or private key material.

## Current MVP Agents

- `agency_supervisor`: SEO lead agent and daily/weekly operating brief owner.
- `promise_tracker`: detects likely commitments from summarized comms.
- `delivery_manager`: documented role; delivery checks currently feed the daily brief.
- `monday_hygiene`: identifies task metadata cleanup candidates without treating them as delivery failures.
- `qa_guardrail`: validation rules used by the shared agent output contract.
- `performance_analyst`: reviews GA4, Search Console, SE Ranking, and BigQuery performance marts.
- `reporting_agent`: drafts client-safe reporting notes only.
- `technical_audit_agent`: owns monthly and post-task crawl interpretation from Screaming Frog MCP/CLI summaries.
- `system_admin_agent`: sweeps AgencyOS core health, cost guardrails, local agent runs, data freshness, and route verification gaps.

Future or compatibility-only agents: `client_comms_drafting` remains future, and `technical_seo` is a retired alias for `technical_audit_agent`.

## SEO Automation Wrapper Layer

SEO Automation remains the specialist execution/tooling repo. AgencyOS wraps it by syncing safe workflow metadata, client route summaries, and recent timeline summaries into operating tables.

Wrapper agents:

- `seo_workflow_router`: routes requests to the safest SEO Automation workflow.
- `client_readiness`: checks whether each client has the client brief, sidecar, timeline, access routes, Drive routes, Monday route, and reporting/content prerequisites needed for common workflows.
- `seo_opportunity_agent`: turns safe BigQuery and SEO Automation summaries into SEO workflow suggestions.
- `reporting_prep_agent`: prepares draft-only monthly reporting actions and source-coverage warnings.
- `reporting_agent`: drafts monthly or weekly reporting notes from validated performance, delivery, and roadmap evidence.
- `performance_analyst`: interprets monthly GA4/GSC/SE Ranking performance marts and source coverage.
- `search_console_opportunity_agent`: owns GSC opportunity mining and Search Console coverage warnings.
- `se_ranking_hygiene_agent`: reviews SE Ranking route, access, capacity, stale tracking, duplicate, and AI tracker readiness signals.
- `drive_filing_readback_agent`: checks Drive route/readback metadata without raw Drive content.
- `reporting_portal_qa_agent`: reviews reporting portal snapshot, source-caveat, build, privacy, and browser-QA readiness.
- `seo_maintenance_agent`: recommends access, filing, SE Ranking, onboarding, and platform-reference cleanup actions.
- `content_operations_agent`: coordinates content workflow readiness without drafting or publishing.
- `technical_audit_agent`: prioritises Screaming Frog MCP/CLI, SE Ranking, Firecrawl, monthly baseline crawls, and post-task crawl evidence without running crawls automatically.
- `system_admin_agent`: checks BigQuery datasets/tables, ingestion runs, capped-query cost checks, local agent activity, dashboard data-health signals, and route-vs-verified health gaps without performing repairs.

The wrapper layer stores sanitized structured extracts only. It does not store raw timeline markdown, raw Drive/Docs/Sheets content, raw Gmail/Outlook/Monday conversations, credentials, or long private notes.

## Safe Defaults

Permissions live in `config/permissions.yaml`.

The MVP defaults to:

- dry-run first
- no email sending
- no Monday writes
- no Drive writes or sharing
- no external publishing
- no automatic Screaming Frog crawl control, raw export upload, or bulk page-content export
- no automatic monthly or post-task crawl execution without approved client/site/scope
- BigQuery logging only by explicit flag
- approval required for external actions
- production BigQuery logging requires BigQuery-backed context unless an explicit local-test override is passed

## Commands

Run Promise Tracker from the latest local staged comms summaries:

```bash
.venv/bin/python scripts/run_promise_tracker.py
```

Run Daily Agency Brief from local staged comms plus any optional local JSON context:

```bash
.venv/bin/python scripts/run_daily_agency_brief.py
```

The daily brief currently treats odd task rows as Monday hygiene signals, not delivery failures. Typical hygiene signals include missing client mapping, alias slugs, missing owners, missing due dates, stale due dates, and empty task names.

Inspect local agent visibility without running BigQuery:

```bash
.venv/bin/python scripts/agent_activity_today.py
```

Sync the SEO Automation workflow catalog locally:

```bash
.venv/bin/python scripts/sync_seo_automation_catalog.py --dry-run
```

Sync sanitized SEO Automation client memory locally:

```bash
.venv/bin/python scripts/sync_seo_client_memory.py --dry-run
```

Run the SEO workflow router locally:

```bash
.venv/bin/python scripts/run_seo_workflow_router.py --dry-run
```

Run opportunity and reporting-prep wrappers locally:

```bash
.venv/bin/python scripts/run_seo_opportunity_agent.py --dry-run
.venv/bin/python scripts/run_reporting_prep_agent.py --dry-run
```

Run read-only specialist wrappers locally:

```bash
.venv/bin/python scripts/run_performance_analyst.py --dry-run
.venv/bin/python scripts/run_drive_filing_readback_agent.py --dry-run
.venv/bin/python scripts/run_se_ranking_hygiene_agent.py --dry-run
.venv/bin/python scripts/run_reporting_portal_qa_agent.py --dry-run
.venv/bin/python scripts/run_technical_audit_agent.py --dry-run
.venv/bin/python scripts/run_system_admin_agent.py --dry-run
```

Local runner metadata is indexed in `data/agent_runs/index.json`, and in-progress markers live under `data/agent_runs/active/`. Runners accept `--automation-id` or `SEO_AGENCY_OS_AUTOMATION_ID` so scheduled workflows can be tied back to their automation identity in local output and the optional run log.

Plan the live BigQuery operating tables before creating/updating anything:

```bash
.venv/bin/python scripts/manage_agent_operating_tables.py \
  --plan \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Create or verify the approved operating tables only after the plan has been reviewed:

```bash
.venv/bin/python scripts/manage_agent_operating_tables.py \
  --ensure \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Plan the crawl-memory tables for monthly and post-task technical comparisons:

```bash
.venv/bin/python scripts/manage_crawl_memory_tables.py \
  --plan \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Run against BigQuery reporting marts only when credentials are loaded and the task calls for live warehouse reads:

```bash
.venv/bin/python scripts/run_daily_agency_brief.py \
  --from-bigquery \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Log validated output to BigQuery only when explicitly approved for the run:

```bash
.venv/bin/python scripts/run_daily_agency_brief.py \
  --from-bigquery \
  --write-bigquery \
  --ensure-tables \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Record a human approval decision without executing the action:

```bash
.venv/bin/python scripts/record_agent_approval.py \
  --action-id ACTION_ID \
  --run-id RUN_ID \
  --client-slug CLIENT_SLUG \
  --decision approved \
  --decided-by laurence
```

`record_agent_approval.py` can log approval rows to BigQuery with `--write-bigquery`, but it does not create Monday tasks, send emails, share Drive files, or publish anything externally.

## BigQuery Tables

The operating layer defines:

- `agency_control.agent_run_log`
- `agency_control.llm_usage_log`
- `agency_memory.agent_findings`
- `agency_memory.agent_actions`
- `agency_memory.agent_approvals`
- `agency_memory.context_packs`
- `agency_memory.seo_workflow_catalog`
- `agency_memory.seo_client_memory_summaries`
- `agency_memory.seo_workflow_run_summaries`
- `agency_memory.client_crawl_runs`
- `agency_memory.client_crawl_url_snapshots`
- `agency_reporting.seo_workflow_readiness`
- `agency_reporting.seo_opportunity_queue`
- `agency_reporting.client_crawl_latest`
- `agency_reporting.client_crawl_comparison`

These are for internal operating memory only. They are not sources of truth for Monday, Gmail, Drive, Docs, or client reporting.

Live writes use an expiring staging table in `agency_staging`, then an idempotent `MERGE` into the approved operating table. Merge SQL runs through the capped query runner so cost-check rows are still written.

## Verification

Use the normal project checks:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/ingest_agency_ops.py --local-dry-run
```

Then smoke-test the operating layer locally:

```bash
.venv/bin/python scripts/run_promise_tracker.py
.venv/bin/python scripts/run_daily_agency_brief.py
.venv/bin/python scripts/sync_seo_automation_catalog.py --dry-run
.venv/bin/python scripts/sync_seo_client_memory.py --dry-run
.venv/bin/python scripts/run_seo_workflow_router.py --dry-run
.venv/bin/python scripts/run_seo_opportunity_agent.py --dry-run
.venv/bin/python scripts/run_reporting_prep_agent.py --dry-run
.venv/bin/python scripts/run_performance_analyst.py --dry-run
.venv/bin/python scripts/run_drive_filing_readback_agent.py --dry-run
.venv/bin/python scripts/run_se_ranking_hygiene_agent.py --dry-run
.venv/bin/python scripts/run_reporting_portal_qa_agent.py --dry-run
.venv/bin/python scripts/run_technical_audit_agent.py --dry-run
.venv/bin/python scripts/run_system_admin_agent.py --dry-run
```

Offline CI runs:

```bash
.venv/bin/python scripts/validate_operating_layer.py
.venv/bin/python -m compileall agency_bigquery scripts tests
.venv/bin/python -m unittest discover -s tests -v
```
