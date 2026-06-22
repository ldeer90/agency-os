# Big Query Agent Guide

This project is the local control folder for Laurence Deer's BigQuery agency memory in Google Cloud project `seo-agency-work`.

Read this file before changing scripts, docs, schemas, or running live BigQuery work from:

```text
/Users/laurencedeer/Projects/Codex/Big Query
```

## Read Order

1. `HANDOVER.md` for the current warehouse state and known next actions.
2. `docs/AGENCY_OPS_MEMORY_V1.md` for the agency-memory model and source-of-truth rules.
3. `docs/QUERY_COOKBOOK.md` before running ad hoc warehouse queries.
4. `docs/DRIVE_FILING_GUIDE.md` before creating or filing client reports in Google Drive.
5. `docs/BIGQUERY_BUDGET_SETUP.md` and `docs/BIGQUERY_IAM_SETUP.md` when cost, IAM, or credential context matters.

## Core Model

BigQuery is the read-only memory and reporting layer for agency operations. It mirrors and summarizes approved sources; it does not write back to Monday, Google Drive, SEO Reporting Platform, GA4, Search Console, or SE Ranking.

Source precedence:

- Monday task state: local `monday-agency-hub` snapshots.
- Client routing and access: SEO Automation client briefs and sidecars.
- Published monthly reporting: SEO Reporting Platform report JSON.
- Live performance history: read-only GA4, Search Console, and SE Ranking API summaries loaded by approved scripts.
- Google Drive filing: SEO Automation Drive rules and client sidecars, not BigQuery guesses.

## Cost Guardrails

All Codex-created BigQuery SQL must use the shared capped query path:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "plain-English reason" \
  --sql "SELECT 1"
```

Rules:

- Normal cap is `1 GB/query`.
- Manual override cap is `10 GB/query` and requires `--admin-cap-10gb`.
- Use on-demand BigQuery pricing with the A$10/month budget target.
- Do not use shell `bq` as the primary path.
- Do not call `bigquery.Client().query(...)` directly for exploratory or transform SQL unless editing the capped runner itself.
- Treat an over-cap query failure as the guardrail working; narrow the query instead of bypassing it.

## Required Skills

Use the relevant Codex skill when the task matches it:

- `bigquery-agency-memory`: ingestion, schema, reporting marts, source precedence.
- `bigquery-capped-querying`: ad hoc SQL, estimates, cost logs, query verification.
- `agency-memory-privacy-guard`: source boundaries, credentials, Drive/Monday/email privacy.
- `agency-bigquery-health-check`: warehouse health, IAM, row counts, smoke checks.
- `monday-bigquery-snapshot-export`: safe Monday metadata snapshot refreshes.
- `agency-memory-safety-review`: final review for cost, privacy, and source-of-truth mistakes.

- `langfuse-cost-investigation`: expensive Langfuse/Codex session diagnosis, duplicate trace checks, token/cost review.

## Efficiency Guardrails

This project optimizes for balanced efficiency: preserve safety and client-quality review, but avoid repeated full-context spend.

- Use the validated workflow fast path when a task matches an existing skill or runbook. Read the most specific skill first, then read only the minimum project guidance needed for safety. Do not re-inspect helper source, schemas, or long docs unless the workflow fails, changed recently, the source boundary is unclear, or Laurence asks for implementation detail.
- Prefer targeted discovery: `rg --files`, narrow `rg`, and bounded `sed` ranges. Exclude `.venv`, `node_modules`, `dist`, `__pycache__`, ignored caches, generated reports, binary/media files, and large local artifacts unless the task specifically requires them.
- Use low-cost exploration first: file maps, metadata-only API checks, row counts, schemas, compact logs, and summarized command output before broad synthesis.
- Keep `gpt-5.5` for orchestration, final synthesis, high-risk privacy/cost review, and client-facing claims. Prefer cheaper or low-reasoning workers for bounded read-only scans, file mapping, log summaries, and other narrow exploration.
- For long implementation loops, split the work after repeated tool/edit cycles or when context has clearly grown large. Summarize current state, open decisions, files changed, and verification status before continuing.
- Treat these as soft review triggers, not hard budgets: high input share, many observations/tool calls, duplicate trace candidates, repeated failed commands, or late generations with very large input context.
- After about 20 tool calls, repeated `write_stdin` polling, or a follow-up that would reuse a large context, pause to summarize and narrow. Prefer longer command waits, sanitized temp files, and compact summaries over chat-loop polling.
- Separate user-answer work from reusable-system work. If a client/reporting answer suggests a skill, doc, or helper improvement, finish the answer first and make the reusable improvement in a fresh thread unless Laurence explicitly asks to combine them.
- Langfuse/Codex usage reviews should be metadata-only by default. Fetch prompt/tool input-output payloads only for approved debugging and only at the smallest useful scope.

## Codex Cost Hygiene

Cost controls are advisory-first: reduce repeated input spend without skipping verification, privacy review, client-facing checks, or required dry-runs.

- Start each substantive AgencyOS Codex session with `agent=<agent_id> task=<task_type>`, then the active-agent identity sentence.
- Batch independent read-only inspection where useful, but keep reads targeted and summarized before synthesis.
- Split or restart a turn when work has many tool calls, repeated command/edit cycles, or context is already large. The handoff should include only goal, files changed, open decisions, verification status, and next command.
- When a Langfuse report flags duplicate traces, high input share, many observations, or missing metadata, treat it as a review trigger for the next run. Do not let the flag block necessary quality work.
- For expensive-session reviews, report gross cost and likely unique cost when duplicate trace candidates appear.

## Active Agent Identity And Delegation

Every Codex session in this project should make the active operating role visible.

At the start of substantive work, identify the active agent in chat using this style:

```text
`system_admin_agent` reporting for work: checking AgencyOS health and guardrails.
```

## Langfuse Usage Tracking

For every substantive AgencyOS Codex task, start the first assistant update with a machine-readable tracking line before the normal identity sentence:

```text
agent=<agent_id> task=<task_type>
```

Example:

```text
agent=system_admin_agent task=health-check
`system_admin_agent` reporting for work: checking AgencyOS health and guardrails.
```

This lets `scripts/langfuse_agencyos_usage_report.py` group Codex token usage by agent and task type in Langfuse.

Use the task types from `docs/AGENCYOS_LANGFUSE_USAGE.md` unless a task clearly needs a new category. Starter task types:

| Task type | Use when |
| --- | --- |
| `health-check` | AgencyOS, BigQuery, config, data freshness, guardrails |
| `reporting` | Monthly reporting, client-safe notes, reporting prep, portal QA |
| `bigquery-query` | BigQuery data questions, capped SQL, query result review |
| `debugging` | Failing scripts, tests, local runs, config fixes |
| `docs` | Guides, handovers, runbooks, operating notes |
| `frontend` | Dashboard UI, browser verification, screenshots |
| `automation` | Recurring jobs, scheduled runs, local agent automation |
| `privacy-review` | Credential, source-boundary, Drive/Monday/email safety checks |

Use existing agent IDs from the active-agent mapping below. Do not include client secrets, credential values, raw private content, or Langfuse keys in tracking metadata.

Use the most specific project agent for the task. If the user asks a general BigQuery agency-memory question, default to `agency_supervisor` for orchestration. Switch to a specialist identity when the work clearly belongs to that specialist, and state the switch briefly.

Recommended default mapping:

| Work type | Active agent |
| --- | --- |
| Cross-client operating view, prioritisation, daily/weekly brief | `agency_supervisor` |
| Workflow routing, matching requests to SEO Automation workflows | `seo_workflow_router` |
| BigQuery health, cost guardrails, local agent runs, data freshness | `system_admin_agent` |
| Ingestion, schema, reporting marts, table planning | `agency_supervisor` with `bigquery-agency-memory` skill |
| Ad hoc BigQuery SQL, row counts, smoke checks | `system_admin_agent` with `bigquery-capped-querying` skill |
| Privacy, credentials, source-boundary review | `qa_guardrail` with `agency-memory-privacy-guard` skill |
| Final safety review before live loads or operating-layer writes | `qa_guardrail` with `agency-memory-safety-review` skill |
| Monday snapshot metadata refresh | `monday_hygiene` with `monday-bigquery-snapshot-export` skill |
| Client setup/readiness and route gaps | `client_readiness` or `seo_maintenance_agent` |
| Reporting prep, reporting notes, portal QA | `reporting_prep_agent`, `reporting_agent`, or `reporting_portal_qa_agent` |
| GA4/GSC/SE Ranking performance interpretation | `performance_analyst` |
| Search Console opportunity mining | `search_console_opportunity_agent` |
| SE Ranking hygiene, routes, stale tracking, capacity | `se_ranking_hygiene_agent` |
| Drive route/readback metadata checks | `drive_filing_readback_agent` |
| Crawl memory, Screaming Frog evidence, technical audit interpretation | `technical_audit_agent` |
| Content research, keyword/SERP/product evidence, and brief-format gating | `content_research_agent` |
| Final local HTML content writing from approved research packs | `content_writer_agent` |
| Content workflow readiness | `content_operations_agent` |

Use actual subagents when the work benefits from independent specialist review or parallel read-only exploration. Good delegation cases include:

- `agency_supervisor` delegates a route decision to `seo_workflow_router`.
- `system_admin_agent` delegates a privacy/cost review to `qa_guardrail`.
- `seo_workflow_router` delegates crawl evidence to `technical_audit_agent`, reporting gaps to `reporting_prep_agent`, or SE Ranking issues to `se_ranking_hygiene_agent`.
- `agency_supervisor` delegates bounded read-only row-count/schema checks to a low-risk explorer, then reviews the findings before changing code or running live work.

Do not delegate tiny linear tasks, write-heavy changes across the same files, or decisions involving credentials, publishing, Drive permissions, Monday writes, live loads, or external systems without the orchestrating agent reviewing the result first.

When delegating, give the subagent:

- its agent identity
- the exact files, tables, or docs to inspect
- the stop condition
- the expected concise output: findings, evidence paths, risks, recommended action, confidence

All final decisions about external writes, live BigQuery loads, credentials, deleting/moving files, publishing, commits, pushes, and client-facing claims stay with the active orchestrating agent and Laurence's explicit approval.

## Model Routing

Prefer the lowest reasoning level that safely handles the task. This file cannot force the current chat model, but it is the operating standard for future agents, subagents, and automations in this project.

Defaults:

- Read-only BigQuery lookup, row-count check, client timeline lookup, task summary, or monthly performance query: `gpt-5.5` with `low` reasoning.
- Routine documentation updates, query cookbook additions, or non-risky local verification: `gpt-5.5` with `low` reasoning.
- Schema, ingestion, loader, mart, or API smoke-test code changes: `gpt-5.5` with `medium` reasoning.
- Privacy, credential, Drive write-safety, cost-guardrail, or source-of-truth review: `gpt-5.5` with `high` reasoning.

When spawning subagents:

- Use low reasoning for bounded read-only BigQuery/query-cookbook checks.
- Use medium reasoning for implementation workers.
- Use high reasoning for reviewers checking cost, privacy, credentials, or Drive permissions.
- Close subagents when their work is no longer needed so the pool does not block future delegation.

## Privacy Boundaries

Do not ingest or document raw private content unless Laurence explicitly approves a new source and scope.

Excluded from agency-memory V1:

- Monday updates, comments, item descriptions, and private notes.
- Raw Drive, Docs, Sheets, Gmail, Outlook, or private conversation contents.
- Credential values, service-account JSON contents, OAuth tokens, cookies, or secret headers.
- Lead-gen, Sales, Link OS, Instantly, Guest Post, BuiltWith, publisher, or prospecting data.

Allowed by default:

- BigQuery table names, row counts, cost-check status, and run IDs.
- Client slugs, public domains, report months, task metadata, status labels, and summary metrics.
- Drive folder routing metadata only when sourced from approved SEO Automation docs.

## Google Drive Rules

Before saving or filing reports, read `docs/DRIVE_FILING_GUIDE.md`.

High-level rules:

- Canonical tree: `My Drive / Agents Digital / Clients`.
- Output owner for new Docs/Sheets: `hello@agents.digital`.
- Primary working account for most client access: `seo@agents.digital`.
- Use SEO Automation client briefs/sidecars and `config/drive_filing_rules.json` as the source of truth.
- Prefer Google Drive MCP folder checks using `parentId='<folder_id>'`.
- Never create, move, delete, share, or permission-change Drive files or folders without explicit user approval.
- Never ingest raw Drive/Docs content into BigQuery.

## Credentials

Sanitized credential map for this project:

| Path or variable | Purpose | Approval notes |
| --- | --- | --- |
| `/Users/laurencedeer/Projects/Codex/SEO Automation/.env` | Usual local source for `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, delegated Google subjects, and reporting API env vars | Load only needed variables. Never print values. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Service-account JSON path for BigQuery and approved Google API reads | Do not open or print the JSON contents. |
| `GOOGLE_CLOUD_PROJECT` | Google Cloud project, expected `seo-agency-work` | Safe to mention project ID. |
| `config/bigquery_cost_guardrails.json` | Local BigQuery budget and query cap config | Safe to inspect; contains guardrail settings, not secrets. |

The private credential recovery vault is outside this project. Do not read it unless Laurence explicitly asks for credential recovery.

Agents should know where credentials are without reading or exposing secret values. Use the table above and `/Users/laurencedeer/Projects/Codex/Codex Master/notes/CREDENTIAL_LOCATION_MAP.md` as sanitized maps only. If a task needs credentials, load only the required environment variables through the approved script flags, never print `.env` contents, service-account JSON, OAuth tokens, cookies, secret headers, or private key material.

## Delegation Guidance

Use subagents for bounded read-heavy or review-heavy tasks when helpful:

- Explorer: schema drift checks, source shape inspection, row-count comparisons.
- Worker: isolated doc or ingestion-module changes with a clearly owned file set.
- Reviewer: cost safety, privacy boundaries, Drive write risk, and source-of-truth compliance.

Keep write-heavy work coordinated through one main agent unless Laurence explicitly asks for parallel implementation.

## Verification

Useful local checks:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/ingest_agency_ops.py --local-dry-run
```

Useful live checks, only when credentials are loaded and the task calls for live BigQuery:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "health check: list agency tables" \
  --limit-preview 20 \
  --sql "SELECT table_schema, table_name FROM \`seo-agency-work.region-australia-southeast1\`.INFORMATION_SCHEMA.TABLES WHERE table_schema IN ('agency_control','agency_memory','agency_reporting') ORDER BY table_schema, table_name"
```

Report what passed, what was not run, and whether any live queries wrote cost-check rows.
