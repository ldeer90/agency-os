# BigQuery Budget Setup

This project uses code-level query caps plus Google Cloud budget alerts.

## Budget Alert

Create this manually in Google Cloud Console:

| Setting | Value |
| --- | --- |
| Project | `seo-agency-work` |
| Budget name | `Agency Memory BigQuery Pilot` |
| Budget amount | `AUD 10` per month |
| Scope | Google Cloud project `seo-agency-work` |
| Alert thresholds | `50%`, `80%`, `100%` |
| Notification | Email alerts only |

Do not enable hard shutdown automation in v1.

## Query Caps

All Codex-created BigQuery scripts must use:

```bash
python3 scripts/bq_capped_query.py --purpose "qa: smoke test" --sql "SELECT 1"
```

Normal cap:

```text
1 GB/query
```

Manual override cap:

```bash
python3 scripts/bq_capped_query.py \
  --purpose "admin: intentional broader query" \
  --admin-cap-10gb \
  --sql "SELECT ..."
```

The override is capped at:

```text
10 GB/query
```

## First Live Smoke Test

After installing dependencies and authenticating Google credentials:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/bq_capped_query.py \
  --ensure-log-table \
  --purpose "qa: create cost log and run harmless metadata query" \
  --sql "SELECT CURRENT_TIMESTAMP() AS checked_at"
```

Expected:

- The script prints estimated bytes and cap.
- The query uses `maximum_bytes_billed`.
- A row is written to `seo-agency-work.agency_control.cost_checks`.

If this fails with a permission error, follow [BigQuery IAM Setup](BIGQUERY_IAM_SETUP.md) first.

## Guardrail Rule

If a query fails because it exceeds the cap, narrow the date range, use an `agency_memory` or `agency_reporting` table, or run with the explicit 10 GB admin override only when the larger scan is intentional.
