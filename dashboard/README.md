# Agency Health Dashboard

Local read-only dashboard for the Big Query agency-memory project.

## Run

Install the frontend dependencies once:

```bash
cd dashboard/web
npm install
```

Run the API from the project root:

```bash
.venv/bin/python -m dashboard.api.server
```

If port `8787` is already in use, choose another local port:

```bash
DASHBOARD_API_PORT=8788 .venv/bin/python -m dashboard.api.server
```

Run the web app:

```bash
cd dashboard/web
npm run dev -- --host 127.0.0.1
```

When using a non-default API port:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8788 npm run dev -- --host 127.0.0.1
```

Open the Vite URL shown in the terminal. The dashboard always uses live BigQuery data through the capped query runner. If live BigQuery is unavailable, the API returns an error instead of showing demo data.

## Publish Static Snapshot

The public dashboard subdomain uses the same GoDaddy/cPanel pattern as the SEO reporting portal, but with a static JSON snapshot instead of a live browser-facing API.

Dry-run the publish plan:

```bash
.venv/bin/python scripts/publish_dashboard.py --dry-run
```

Build and package locally without uploading:

```bash
.venv/bin/python scripts/publish_dashboard.py --skip-upload --skip-dns --skip-cpanel
```

Publish to `https://dashboard.laurencedeer.com.au`:

```bash
.venv/bin/python scripts/publish_dashboard.py
```

The publisher:

- exports `dashboard/api/data.py` into `dashboard/web/public/dashboard-payload.json`
- builds the Vite app with `VITE_PUBLIC_STATIC_DASHBOARD=1`
- hides Sync controls in the public build
- packages `dashboard/web/dist` into ignored `dist-dashboard-subdomain/`
- writes `robots.txt`, `_headers`, and `.htaccess` noindex/Apache safety files
- enforces Apache Basic Auth with the password file outside `public_html`
- ensures the GoDaddy `dashboard` A record and cPanel document root
- uploads with `rsync` and verifies the live URL

The static snapshot does not expose BigQuery credentials and does not run sync commands from the public browser. Refreshing the live site means rerunning the publisher.

The first publish creates local Basic Auth credentials at:

```text
.secrets/dashboard-basic-auth.json
```

This file is ignored by Git. Do not commit it or paste its values into chat, docs, reports, or tickets.

## Data Sources

The dashboard reads summary tables only:

- `agency_reporting.client_health_check`
- `agency_memory.client_registry`
- `agency_memory.client_health_assets`
- `agency_reporting.reporting_readiness`
- `agency_reporting.client_task_status`
- `agency_reporting.ops_drift_summary`
- `agency_reporting.client_monthly_comparison`
- `agency_reporting.client_monthly_performance_history`
- `agency_reporting.client_benchmark_summary`
- `agency_memory.client_finance_monthly`
- `agency_memory.agency_expenses_monthly`
- `agency_reporting.client_finance_health`
- `agency_reporting.client_comms_attention`
- `agency_reporting.client_roadmap_current`
- `agency_reporting.client_roadmap_monthly_completion`
- `agency_reporting.client_monthly_reporting_coverage`
- `agency_memory.monthly_report_snapshots`
- `agency_control.agent_run_log` when available
- `agency_memory.seo_workflow_run_summaries` when available
- `agency_control.ingestion_runs`
- `agency_control.cost_checks`
- local `data/agent_runs/index.json`
- local `data/finance/client_retainers_2026.json` as the historical finance import/staging source
- local Monday Client Board snapshot `board_5026765711.json` as the current/future retainer source

## Detail Views

- Clients show sanitized profile metadata, exact missing health assets, latest reports, roadmaps, performance history, delivery, and comms.
- Delivery shows Monday ops visuals from BigQuery snapshots: task status by active client, status distribution, overdue counts, named task rows, and ops-drift signals.
- Performance uses monthly history rows so each client has a trend chart rather than only the latest month.
- Roadmaps show all current roadmap items and flag clients with no roadmap rows or missing validated roadmap content.
- Reporting shows month tabs and live report links from monthly report snapshots, including compact links, safe local paths, and share IDs.
- Agents groups recent completed runs per agent from BigQuery agent logs and the local run index.
- Finance shows client retainers from BigQuery finance tables and agency operating expenses from the Monday Expenses board snapshot, with month-by-month totals and health calculations for collection, invoicing, gross margin, and margin rate.
- Syncs is the active operations console. It shows allowlisted local sync commands, queues dry/live runs, polls local command state, and stores sanitized run summaries under ignored `data/sync_ops/`.

## Safety Rules

- No Monday, Drive, Gmail, Outlook, publishing, sharing, or permission writes.
- No raw Drive/Docs/Sheets bodies, Monday comments, email bodies, credentials, private message text, email addresses, or phone numbers.
- No live Monday calls from the dashboard; Monday remains the source system and BigQuery remains the read-only dashboard model.
- Local finance JSON is an approved historical import source for `agency_memory.client_finance_monthly`; the local Monday Client Board snapshot is the approved current/future retainer source; the local Monday Expenses board snapshot is the approved import source for `agency_memory.agency_expenses_monthly`. These finance imports must not include raw invoices, accounting exports, private messages, contact details, or credential values.
- ABN/contact fields are nullable sanitized metadata only; the dashboard does not infer or scrape them from private communications.
- All live BigQuery reads must go through `CappedBigQueryRunner`.
- Every live dashboard query uses a plain-English purpose beginning with `agency-health-dashboard:`.
- Sync controls are allowlisted by `dashboard/api/sync_ops.py`; the browser cannot submit arbitrary shell commands.
- Live sync commands require the configured confirmation phrase before they are queued.

## Cost

This dashboard runs multiple small read-only summary queries each time it loads or refreshes. The project cap is `1 GB/query`, and every query is dry-run estimated before execution. Recent live dashboard checks estimated each query in bytes or kilobytes, not gigabytes.
