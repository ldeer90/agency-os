# AgencyOS Langfuse Usage Review

This guide turns Codex Langfuse traces into a beginner-friendly usage review. The goal is to answer simple operating questions:

- Which AgencyOS agents appear most in expensive sessions?
- Which task types use the most tokens?
- Which sessions look inefficient?
- What should change before the next run?

## How To Tag Work

Start substantial AgencyOS Codex requests with a compact identity line:

```text
agent=system_admin_agent task=health-check
```

Use these task types first:

| Task type | Use when |
| --- | --- |
| `health-check` | Checking AgencyOS, BigQuery, config, data freshness, or guardrails |
| `reporting` | Monthly reporting, client-safe notes, reporting prep, portal QA |
| `bigquery-query` | Asking for data from BigQuery or reviewing SQL results |
| `debugging` | Fixing failing scripts, tests, runs, or local config |
| `docs` | Updating guides, handovers, runbooks, or operating notes |
| `frontend` | Dashboard UI, browser verification, screenshots |
| `automation` | Recurring jobs, scheduled runs, local agent automation |

Prefer exact AgencyOS agent IDs from `AGENTS.md`, such as `system_admin_agent`, `agency_supervisor`, `qa_guardrail`, `performance_analyst`, `reporting_prep_agent`, and `technical_audit_agent`.

## Run The Report

Generate a local Markdown report:

```bash
.venv/bin/python scripts/langfuse_agencyos_usage_report.py --days 7
```

By default the script reads the ignored Codex config:

```text
.codex/langfuse.json
```

It writes reports under:

```text
reports/langfuse/
```

Use `--stdout` for a quick terminal preview. The script never prints API keys.

For a read-only preview that does not write under `reports/langfuse/`:

```bash
.venv/bin/python scripts/langfuse_agencyos_usage_report.py --days 1 --stdout --no-write --limit 100
```

Row-level observation fetches are metadata-only by default. Use `--include-io` only for approved debugging where prompt/tool input-output fields are truly needed.

## Expensive Session Review

Use this lightweight review before repeating a costly AgencyOS Codex workflow:

1. Run the metadata-only report first:

```bash
.venv/bin/python scripts/langfuse_agencyos_usage_report.py --days 1 --stdout --no-write --limit 100
```

2. Check the highest-token sessions, duplicate trace candidates, input share, observation count, and recommended next actions.
3. If duplicate candidates appear, report both gross cost and likely unique cost. Exact duplicate shapes may indicate duplicate trace emission rather than unique model work.
4. If input share dominates, start a fresh handoff turn instead of continuing a large context. Include only goal, changed files, open decisions, verification status, and next command.
5. If many observations/tool calls appear, batch read-only exploration and split implementation earlier. Keep verification depth unchanged.
6. Use `--include-io` only when Laurence explicitly approves raw prompt/tool input-output inspection for a narrow debugging reason.

## Validated Workflow Fast Path

Once a workflow has run successfully and is captured in a skill or runbook, future sessions should use that route first instead of rediscovering helper code and safety rules.

Default pattern:

1. Start with `agent=<agent_id> task=<task_type>`.
2. Read the most specific skill or runbook for the request.
3. Read only the minimum project guidance needed for safety.
4. Run the known command, query, or API pattern.
5. Keep the same verification depth.
6. Inspect source code only if the workflow fails, changed recently, uses an unfamiliar source, crosses a privacy boundary, or Laurence asks for implementation detail.

Split answer work from system-improvement work. If a client/reporting answer reveals a reusable improvement, finish the answer first and create or update the skill/runbook in a fresh thread unless Laurence explicitly asks to combine them.

## Workflow Classes

Use these classes to keep future AgencyOS work compact while preserving quality.

| Workflow class | Fast path | Verification | Inspect source when |
| --- | --- | --- | --- |
| Reporting/performance lookup | Use the most specific reporting skill, then run the known BigQuery/API pattern | Date range, source status, capped-query result, API success/failure counts | Metric definition, source freshness, or client route is unclear |
| BigQuery query | Use `bigquery-capped-querying` and the capped runner | Status succeeded, estimate below cap, `cost_check_log_errors` empty | Query shape, schema, or mart meaning is unknown |
| Debugging | Reproduce the failing command once, inspect smallest relevant logs, patch one suspected cause | Failing command passes or produces a clearer failure | Stack trace points into unfamiliar code |
| Docs/runbooks | Read current section and nearby source of truth, then edit narrowly | Readback, link/path sanity, no secrets | Existing guidance conflicts or source of truth is unclear |
| Implementation/test loop | Read ownership files, patch narrowly, run narrow tests first | Narrow tests, then broader verification near final | Public interface, schema, or shared behavior changes |
| Privacy/safety review | Use privacy/safety skill and metadata-first inspection | Source boundaries, credentials not exposed, write approvals confirmed | Private payload inspection is explicitly approved and necessary |
| Connector/API check | Use existing connector/runbook command and sanitized summaries | Success count, failure count, date/window, no raw credentials | API contract changed or sanitized error is ambiguous |

Soft stop triggers:

- Around 20 tool calls in one task.
- Repeated `write_stdin` polling on a long command.
- Any late generation with very large input context.
- Follow-up asks after a data-heavy answer.
- A task drifting from answering the user into improving the reusable system.

When a trigger fires, summarize goal, decisions, files touched, commands run, verification state, and the next exact command before continuing or starting a fresh thread.

## Skill Template

New or updated AgencyOS skills should include these sections when useful:

- `Fast Path`: the shortest validated route for the common case.
- `Fallback If Command Fails`: what to inspect next without broad rediscovery.
- `Do Not Inspect Unless`: files/sources that should stay out of context unless needed.
- `Verification Checklist`: checks that protect quality and safety.
- `Split-Thread Triggers`: when to stop, summarize, and continue fresh.

## How To Read Inefficiency Flags

| Flag | Meaning | Usual fix |
| --- | --- | --- |
| High input share | Most spend came from context being resent | Narrow reads and use a fresh handoff turn |
| Many observations | Lots of model/tool steps in one trace | Batch reads and split repeated command/edit cycles |
| Missing agent/task | Trace cannot be grouped cleanly | Add `agent=... task=...` at the start |
| Review threshold | Session is expensive enough to inspect | Review metadata-only report before repeating |
| Deep threshold | Session is large enough to split soon | Summarize state and restart with smaller context |
| Low output / high input | Model read a lot but produced little | Ask for a compact summary before implementation |
| Duplicate candidates | Multiple traces have identical usage shape | Report gross and likely unique cost; check tracing config |

These are soft review triggers, not hard token budgets. Do not block useful work only because a threshold appears; use it to change the workflow before repeating the same pattern.

Duplicate trace candidates mean multiple traces share the same observation count, token totals, and cost shape. Review them with `$langfuse-cost-investigation` before assuming all reported cost came from unique work.

Starter review bands:

| Size | Total tokens |
| --- | --- |
| Small | Under 25k |
| Medium | 25k-100k |
| Deep | 100k-300k |
| Review | Over 300k |

## Langfuse UI Views To Save

In Langfuse Japan project, save views for:

- AgencyOS only: tag contains `agency-os`
- Codex App only: tag contains `codex-app`
- Highest token sessions
- Highest cost sessions
- Most observations/tool calls
- Missing `agent=` or `task=` in opening prompt
- Recent sessions by task type

## Privacy Notes

Codex traces can include prompts, assistant text, tool inputs, command output, and snippets from local files. This project defaults to metadata-only Codex usage review: token usage, model, trace/session IDs, tags, environment, observation type, and tool names. Keep `.codex/langfuse.json` metadata-first unless debugging needs more detail. Do not enable payload capture for sessions containing data that should not be stored in Langfuse.

## Efficiency Posture

- Keep `gpt-5.5` for orchestration, final synthesis, high-risk privacy/cost review, and client-facing claims.
- Prefer cheaper or low-reasoning workers for bounded read-only scans, file maps, log summaries, and schema lookups.
- Avoid broad local searches across `.venv`, `node_modules`, caches, generated reports, and binary/media files.
- Split long implementation loops after repeated tool/edit cycles; summarize state before continuing.
