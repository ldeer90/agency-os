# Headroom Evaluation Results

Generated with `HEADROOM_TELEMETRY=off`.

| Fixture | Mode | Before | After | Saved | Preserve | Privacy | Answer | Adopt Signal |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| bigquery_health.json | headroom | 3122 | 1522 | 51.2% | pass | pass | same | yes |
| crawl_summary.json | headroom | 4471 | 1694 | 62.1% | pass | pass | same | yes |
| monday_metadata.json | headroom | 4117 | 1693 | 58.9% | pass | pass | same | yes |
| reporting_performance.json | headroom | 2471 | 853 | 65.5% | pass | pass | same | yes |
| terminal_logs.json | headroom | 3749 | 366 | 90.2% | pass | pass | same | yes |

## Decision

Real Headroom adoption threshold met.

Threshold: 3 of 5 fixtures must use real Headroom, save at least 50%, preserve all required facts, and raise no privacy flags.
