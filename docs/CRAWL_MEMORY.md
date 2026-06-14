# Crawl Memory

This runbook defines how AgencyOS should use Screaming Frog crawl evidence with BigQuery agency memory.

## Purpose

Keep an 18-month technical crawl history for active SEO clients so the SEO lead can answer:

- What changed since the last monthly baseline?
- Did a completed task improve or damage crawlable site state?
- Which technical issues are persistent, new, or resolved?

BigQuery is the memory and comparison layer. It is not the crawl runner, raw page-body archive, or source of truth for client site access.

## Cadence

Monthly baseline:

- One approved baseline crawl per active recurring SEO/reporting client each month.
- Use the canonical client route and crawl scope from SEO Automation sidecars/briefs.
- Prefer the same Screaming Frog configuration each month so comparisons stay meaningful.

Post-task verification:

- Run after every completed client-scoped SEO task that can affect crawlable site state.
- Scope the crawl to the task. Use affected URLs or site sections for page/content/metadata work.
- Use full-site post-task crawls only for sitewide technical changes, migrations, navigation changes, template changes, deploys, robots/canonical changes, or broad internal-linking work.
- Compare against the latest relevant baseline or previous task crawl for the same scope.

## Storage Model

Store in BigQuery:

- `agency_memory.client_crawl_runs`: crawl-level metadata, trigger, scope, counts, issue totals, manifest reference, and `retention_expires_on`.
- `agency_memory.client_crawl_url_snapshots`: typed core URL facts from `internal_all.csv`, plus `raw_row_json` preserving every original Screaming Frog field for that row.
- `agency_memory.client_crawl_issue_rows`: typed issue fields from `issues_overview_report.csv` and `issues_reports/*.csv`, plus `raw_row_json`.
- `agency_memory.client_crawl_link_rows`: typed inlink/outlink fields, plus `raw_row_json`.
- `agency_memory.client_crawl_export_rows`: generic fallback storage for every allowed CSV/report row, including unknown exports, with `raw_row_json`.
- `agency_reporting.client_crawl_latest`: latest usable crawl summary per client.
- `agency_reporting.client_crawl_comparison`: current-vs-previous deltas for monthly and post-task checks.

Do not store in BigQuery:

- raw HTML or rendered HTML
- visible page text
- scraped page bodies
- screenshots
- cookies, auth headers, request bodies, or response headers with secrets
- complete export archives or zip payloads

Full crawl storage means all allowed Screaming Frog CSV/report fields are stored row-by-row in BigQuery. It does not mean storing `.dbseospider` archives, screenshots, raw HTML, visible text, cookies, request bodies, or other page-body/secret-bearing payloads.

Plan the BigQuery crawl-memory tables without creating or updating anything:

```bash
.venv/bin/python scripts/manage_crawl_memory_tables.py \
  --plan \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Create or verify the approved crawl-memory tables only after the plan has been reviewed:

```bash
.venv/bin/python scripts/manage_crawl_memory_tables.py \
  --ensure \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Dry-run a full Screaming Frog export load:

```bash
.venv/bin/python scripts/load_screaming_frog_export.py \
  --export-dir "/path/to/screaming-frog-export" \
  --client-slug "client-slug" \
  --client-name "Client Name" \
  --crawl-id "client-slug-monthly-YYYY-MM-DD" \
  --crawl-trigger monthly_baseline \
  --crawl-scope full_site \
  --min-urls 100 \
  --dry-run
```

Load a validated export to BigQuery:

```bash
.venv/bin/python scripts/load_screaming_frog_export.py \
  --export-dir "/path/to/screaming-frog-export" \
  --client-slug "client-slug" \
  --client-name "Client Name" \
  --crawl-id "client-slug-monthly-YYYY-MM-DD" \
  --crawl-trigger monthly_baseline \
  --crawl-scope full_site \
  --min-urls 100 \
  --write-bigquery \
  --ensure-tables \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Partial or post-task crawls must be explicit:

```bash
.venv/bin/python scripts/load_screaming_frog_export.py \
  --export-dir "/path/to/screaming-frog-export" \
  --client-slug "client-slug" \
  --crawl-id "client-slug-post-task-YYYY-MM-DD" \
  --crawl-trigger post_task \
  --crawl-scope partial_scope \
  --scope-ref "task or affected URL set" \
  --write-bigquery \
  --load-env "/Users/laurencedeer/Projects/Codex/SEO Automation/.env"
```

Full-site/monthly loads fail coverage validation when `internal_all.csv` has fewer than `--min-urls` rows. Those runs may be stored as `coverage_failed` metadata, but detail rows are not loaded and latest/comparison tables are not promoted.

## Retention

Retain crawl memory for 18 months from `crawl_date`.

Every loaded row must set:

```text
retention_expires_on = crawl_date + 18 months
```

Retention cleanup must delete expired rows from:

- `agency_memory.client_crawl_runs`
- `agency_memory.client_crawl_url_snapshots`
- `agency_memory.client_crawl_issue_rows`
- `agency_memory.client_crawl_link_rows`
- `agency_memory.client_crawl_export_rows`

Reporting tables should be rebuilt after cleanup.

## Agent Ownership

`technical_audit_agent` owns crawl interpretation and comparison. It recommends crawl runs, validates summary evidence, and sends findings to `qa_guardrail`.

`seo_workflow_router` routes monthly crawl scheduling and post-task verification requests to `technical_audit_agent`.

`agency_supervisor` consumes `agency_reporting.client_crawl_latest`, `agency_reporting.client_crawl_comparison`, and QA-approved technical findings for daily/weekly operating views.

`drive_filing_readback_agent` may verify approved raw export destinations and metadata readback, but it must not inspect or ingest raw crawl content.

## Approval Gates

Explicit approval is required before:

- starting, resuming, pausing, or clearing a Screaming Frog crawl
- changing crawl scope or crawler configuration for a live client site
- exporting or uploading raw crawl files
- running bulk page-content exports, especially raw HTML or visible text
- writing crawl rows to production BigQuery for a new client/source shape

Dry-run planning may propose the crawl list, scope, expected table writes, retention cutoff, and comparison target without touching external systems.
