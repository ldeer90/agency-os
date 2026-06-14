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

Run the web app:

```bash
cd dashboard/web
npm run dev -- --host 127.0.0.1
```

Open the Vite URL shown in the terminal. The dashboard always uses live BigQuery data through the capped query runner. If live BigQuery is unavailable, the API returns an error instead of showing demo data.

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

## Detail Views

- Clients show sanitized profile metadata, exact missing health assets, latest reports, roadmaps, performance history, delivery, and comms.
- Delivery shows Monday ops visuals from BigQuery snapshots: task status by active client, status distribution, overdue counts, named task rows, and ops-drift signals.
- Performance uses monthly history rows so each client has a trend chart rather than only the latest month.
- Roadmaps show all current roadmap items and flag clients with no roadmap rows or missing validated roadmap content.
- Reporting shows month tabs and live report links from monthly report snapshots, including compact links, safe local paths, and share IDs.
- Agents groups recent completed runs per agent from BigQuery agent logs and the local run index.

## Safety Rules

- No Monday, Drive, Gmail, Outlook, publishing, sharing, or permission writes.
- No raw Drive/Docs/Sheets bodies, Monday comments, email bodies, credentials, private message text, email addresses, or phone numbers.
- No live Monday calls from the dashboard; Monday remains the source system and BigQuery remains the read-only dashboard model.
- ABN/contact fields are nullable sanitized metadata only; the dashboard does not infer or scrape them from private communications.
- All live BigQuery reads must go through `CappedBigQueryRunner`.
- Every live dashboard query uses a plain-English purpose beginning with `agency-health-dashboard:`.

## Cost

This dashboard runs multiple small read-only summary queries each time it loads or refreshes. The project cap is `1 GB/query`, and every query is dry-run estimated before execution. Recent live dashboard checks estimated each query in bytes or kilobytes, not gigabytes.
