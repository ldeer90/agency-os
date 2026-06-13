# SEO Agency OS Operating Layer

This layer adds controlled Codex workflows around the existing BigQuery agency memory. It does not replace the ingestion pipeline, Monday, Gmail, Drive, Docs, or existing reporting marts.

## Operating Pattern

```text
read approved summaries and marts
→ build a small context pack
→ create findings and suggested actions
→ run QA guardrails
→ write local report/output
→ optionally log to BigQuery after validation
→ require approval before external action
```

## Current MVP Agents

- `agency_supervisor`: creates the daily agency brief.
- `promise_tracker`: detects likely commitments from summarized comms.
- `delivery_manager`: documented role; delivery checks currently feed the daily brief.
- `monday_hygiene`: identifies task metadata cleanup candidates without treating them as delivery failures.
- `qa_guardrail`: validation rules used by the shared agent output contract.

Future agents are documented only: `performance_analyst`, `technical_seo`, `reporting_agent`, and `client_comms_drafting`.

## Safe Defaults

Permissions live in `config/permissions.yaml`.

The MVP defaults to:

- dry-run first
- no email sending
- no Monday writes
- no Drive writes or sharing
- no external publishing
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
```

Offline CI runs:

```bash
.venv/bin/python scripts/validate_operating_layer.py
.venv/bin/python -m compileall agency_bigquery scripts tests
.venv/bin/python -m unittest discover -s tests -v
```
