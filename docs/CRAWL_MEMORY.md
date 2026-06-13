# Crawl Memory

This runbook defines how AgencyOS should use Screaming Frog crawl evidence with BigQuery agency memory.

## Purpose

Keep an 18-month technical crawl history for active SEO clients so the SEO lead can answer:

- What changed since the last monthly baseline?
- Did a completed task improve or damage crawlable site state?
- Which technical issues are persistent, new, or resolved?

BigQuery is the memory and comparison layer. It is not the crawl runner, raw export store, or source of truth for client site access.

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
- `agency_memory.client_crawl_url_snapshots`: URL-level technical facts and issue flags needed for comparisons.
- `agency_reporting.client_crawl_latest`: latest usable crawl summary per client.
- `agency_reporting.client_crawl_comparison`: current-vs-previous deltas for monthly and post-task checks.

Do not store in BigQuery:

- raw crawl exports
- raw HTML or rendered HTML
- visible page text
- scraped page bodies
- screenshots
- cookies, auth headers, request bodies, or response headers with secrets
- complete export archives or zip payloads

If raw exports are needed for diagnosis, store them only in the approved local or Drive destination after explicit approval for the site, scope, and destination. BigQuery should receive only the sanitized manifest path/ID and hashed source reference.

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

## Retention

Retain crawl memory for 18 months from `crawl_date`.

Every loaded row must set:

```text
retention_expires_on = crawl_date + 18 months
```

Retention cleanup must delete expired rows from:

- `agency_memory.client_crawl_runs`
- `agency_memory.client_crawl_url_snapshots`

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
