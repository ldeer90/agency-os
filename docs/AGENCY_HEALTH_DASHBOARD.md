# Agency Health Dashboard

The dashboard is a local read-only UI for understanding agency status across client setup, delivery, reporting, performance, comms, roadmaps, agent activity, and data health.

Run instructions live in `dashboard/README.md`.

The dashboard always uses live BigQuery data. It does not include demo or fallback data.

## Health Model

The overall score is a weighted rollup:

- Client setup health: 20%
- Reporting readiness: 14%
- Delivery risk: 16%
- Comms attention: 12%
- Roadmap health: 12% from coverage, validated evidence, completion, and risk
- Performance direction: 16%
- Data and automation health: 10%

Status bands:

- `Healthy`: 85-100
- `Watch`: 70-84
- `Needs attention`: 45-69
- `Critical`: 0-44

## Views

- Overview: overall score, KPI tiles, attention queue, health distribution, missing asset categories, roadmap/report gaps, recent agent activity, and freshness.
- Clients: active reporting clients, sanitized profile metadata, exact missing health assets, report/roadmap/performance/delivery/comms drilldowns.
- Delivery: Monday ops visuals for active reporting clients, including task status by client, status distribution, overdue counts, named task rows, and ops-drift hygiene signals.
- Performance: latest monthly comparison, benchmark status, and 12-13 month trend history.
- Comms: summarized attention queue only.
- Roadmaps: all current roadmap items plus coverage, evidence, completion, risk, and missing-roadmap/missing-evidence flags.
- Reporting: readiness, source coverage, and safe report links/paths from monthly report snapshots.
- Agents: grouped summary of recent completed runs per agent from BigQuery/local logs.
- Data Health: ingestion runs and capped cost-check status.

## Adding Queries

Add new dashboard queries only when they are summary-level, read-only, and backed by approved agency-memory/reporting/control tables. Do not add raw client documents, email bodies, Monday updates/comments, credentials, or private conversation text.

Monday performance in this dashboard means ops hygiene, not staff productivity. Use `agency_reporting.client_task_status` and `agency_reporting.ops_drift_summary` snapshots only; do not call Monday live or display updates, comments, item descriptions, private notes, or files.

Client profile fields are intentionally narrow. `abn`, `primary_contact_name`, and `primary_contact_role` may be loaded only from approved sanitized sidecar metadata; email addresses, phone numbers, and private message content stay out of the dashboard and warehouse.

Use the capped runner path in `dashboard/api/data.py`; do not add direct exploratory `bigquery.Client().query(...)` calls.

## Cost Model

Each dashboard load runs a fixed set of small summary queries through `CappedBigQueryRunner`. The guardrail config uses on-demand pricing, an A$10/month budget target, and a normal `1 GB/query` hard cap.

Every query is dry-run estimated before execution and logged to `agency_control.cost_checks`. If a query estimates above the cap, it should fail closed rather than run.
