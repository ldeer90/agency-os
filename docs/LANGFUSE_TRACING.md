# Langfuse Tracing

This project can optionally emit local agent run traces to Langfuse while keeping BigQuery as the durable agency-memory warehouse.

## Environment

Set these variables in the shell or approved local env file before running an agent:

```text
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
LANGFUSE_HOST
```

`LANGFUSE_HOST` should point at the Langfuse instance, for example the Langfuse Cloud host or a self-hosted URL.

Optional flags:

```text
LANGFUSE_ENABLED=false
LANGFUSE_CAPTURE_PAYLOADS=true
```

Tracing is skipped unless both public and secret keys are present. `LANGFUSE_ENABLED=false` disables tracing even when keys exist.

By default, traces include run metadata, status, counts, and SHA-256 hashes of findings/actions/context. Raw finding/action/context payloads are not sent to Langfuse unless `LANGFUSE_CAPTURE_PAYLOADS=true` is explicitly set.

## Local Agents

The shared specialist runner and system-admin runner call `agency_bigquery.langfuse_tracing.emit_agent_trace()` after each run is validated and written locally. Langfuse failures are reported in the command JSON output but do not fail the agent run.

Examples:

```bash
.venv/bin/python scripts/run_content_research_agent.py --local-context --dry-run
.venv/bin/python scripts/run_system_admin_agent.py --local-only --dry-run
```

## BigQuery Export Notes

Langfuse exports for warehouse-scale analysis should use Langfuse's blob-storage export feature, then load from GCS into BigQuery using this repo's normal capped-query and load-review process. Do not bypass this project's BigQuery cost guardrails for exploratory trace analysis.
