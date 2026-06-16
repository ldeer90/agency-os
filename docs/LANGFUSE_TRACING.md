# Langfuse Tracing

This project can optionally emit local agent run traces to Langfuse while keeping BigQuery as the durable agency-memory warehouse.

## Environment

Set these variables in the shell or approved local env file before running an agent:

```text
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
LANGFUSE_BASE_URL
```

`LANGFUSE_BASE_URL` should point at the Langfuse instance, for example the Langfuse Cloud host or a self-hosted URL. `LANGFUSE_HOST` is also supported for SDK compatibility.
The agent runners' `--load-env` allowlist includes only Google BigQuery credential variables and these Langfuse variables.

Optional flags:

```text
LANGFUSE_ENABLED=false
LANGFUSE_CAPTURE_PAYLOADS=true
```

Tracing is skipped unless both public and secret keys are present. `LANGFUSE_ENABLED=false` disables tracing even when keys exist.

By default, traces include run metadata, status, counts, prompt file paths, prompt SHA-256 hashes, and SHA-256 hashes of findings/actions/context. Raw finding/action/context payloads are not sent to Langfuse unless `LANGFUSE_CAPTURE_PAYLOADS=true` is explicitly set.

## ID Map

Use the same IDs in Langfuse and BigQuery:

| Concept | BigQuery field | Langfuse field |
| --- | --- | --- |
| Agent run | `run_id` | Metadata `run_id`; trace ID is deterministically derived from it |
| Agent identity | `agent_id` | Observation name and prompt namespace |
| Prompt version | `prompt_version` | Prompt label and trace metadata |
| Context pack | `context_id` | Trace metadata |
| Automation/session | `automation_id` | Trace metadata and `session_id`; manual runs use `manual:<date>` |

## Local Agents

The shared specialist runner, system-admin runner, and SEO workflow router call `agency_bigquery.langfuse_tracing.emit_agent_trace()` after each run is validated and written locally. Langfuse failures are reported in the command JSON output but do not fail the agent run.

Examples:

```bash
.venv/bin/python scripts/run_content_research_agent.py --dry-run
.venv/bin/python scripts/run_system_admin_agent.py --dry-run
```

## Prompt Sync

Agency OS prompt files can be synced into Langfuse prompt management with a dry-run default:

```bash
.venv/bin/python scripts/sync_langfuse_prompts.py
```

To write prompt versions to Langfuse after loading local credentials:

```bash
.venv/bin/python scripts/sync_langfuse_prompts.py --load-env .env --write
```

The sync checks existing Langfuse prompts by label and skips unchanged prompt text. Prompt names use `agency-os/<agent_id>` and labels use the local prompt version, with `current` added when the version matches `current.md`.

Optional promotion labels can be added when creating prompt versions:

```bash
.venv/bin/python scripts/sync_langfuse_prompts.py --load-env .env --write --extra-label staging
```

Keep Git prompt files canonical. Treat Langfuse as the prompt review, trace-linking, and future evaluation layer unless this rule is explicitly changed.

## BigQuery Link Table

Langfuse trace links are validated through the same allowlisted staging-merge logging path as other agent tables.

Table:

```text
agency_control.langfuse_trace_links
```

Join keys:

- `run_id` is the merge key and primary BigQuery correlation ID.
- `langfuse_trace_id` and `langfuse_trace_url` point back to Langfuse.
- `metadata_sha256` lets BigQuery confirm the trace metadata payload that was emitted without storing raw trace payloads.

Example capped-query join:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "langfuse: inspect recent agent trace links" \
  --limit-preview 20 \
  --sql "SELECT r.run_id, r.agent_id, r.status, r.mode, r.prompt_version, l.trace_status, l.langfuse_trace_url, l.emitted_at FROM \`seo-agency-work.agency_control.agent_run_log\` r LEFT JOIN \`seo-agency-work.agency_control.langfuse_trace_links\` l USING (run_id) ORDER BY COALESCE(l.emitted_at, r.started_at) DESC LIMIT 20"
```

## Token Usage

LLM wrappers should pass usage rows to both:

- `emit_agent_trace(..., llm_usage=[...])` for Langfuse `generation` observations.
- `log_agent_output(..., llm_usage=[...])` for `agency_control.llm_usage_log`.

Use `agency_bigquery.agent_logging.build_llm_usage_row()` to normalize token usage from OpenAI-style fields (`prompt_tokens`, `completion_tokens`) or local fields (`input_tokens`, `output_tokens`). Each row should keep the same `run_id`, `agent_id`, and `prompt_version` as the agent run.

Token usage by prompt:

```bash
.venv/bin/python scripts/bq_capped_query.py \
  --purpose "langfuse: token use by prompt version" \
  --limit-preview 50 \
  --sql "SELECT prompt_version, agent_id, model, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) AS total_tokens, SUM(cost_estimate_aud) AS cost_estimate_aud FROM \`seo-agency-work.agency_control.llm_usage_log\` GROUP BY prompt_version, agent_id, model ORDER BY total_tokens DESC"
```

## BigQuery Export Notes

Langfuse exports for warehouse-scale analysis should use Langfuse's blob-storage export feature, then load from GCS into BigQuery using this repo's normal capped-query and load-review process. Do not bypass this project's BigQuery cost guardrails for exploratory trace analysis.
