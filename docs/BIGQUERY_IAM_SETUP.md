# BigQuery IAM Setup

The capped query wrapper is installed locally, but the live smoke test needs Google Cloud IAM permissions before it can run.

## Current Blocker

The configured service account can authenticate, but Google Cloud rejected the smoke test because it is missing:

- `bigquery.jobs.create` on project `seo-agency-work`
- `bigquery.datasets.create` on project `seo-agency-work`

## Minimum Practical Roles

Use predefined BigQuery roles rather than broad basic roles.

| Purpose | Recommended grant |
| --- | --- |
| Run dry-runs and capped queries | `roles/bigquery.jobUser` on project `seo-agency-work` |
| Create the first control dataset/table | temporarily grant `roles/bigquery.user` on project `seo-agency-work`, or have an admin create `agency_control.cost_checks` |
| Write cost-check rows after setup | `roles/bigquery.dataEditor` on dataset `agency_control` |
| Read reporting tables later | `roles/bigquery.dataViewer` on reporting/memory datasets |

After `agency_control.cost_checks` exists, prefer removing broad setup-only access and keeping the service account scoped to:

- project-level `roles/bigquery.jobUser`
- dataset-level edit access only where Codex must write logs, staging data, or curated agency-memory tables
- dataset-level read access for reporting sources

## Why

BigQuery jobs are project-level resources, so query and dry-run jobs need project-level job permission. Table reads/writes should be scoped separately at the dataset or table level where practical.

Official reference: [BigQuery IAM roles and permissions](https://docs.cloud.google.com/bigquery/docs/access-control).
