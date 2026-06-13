from __future__ import annotations

from datetime import date
import unittest

from scripts.load_monthly_api_snapshots import (
    aggregate_gsc_daily_rows,
    build_snapshot_rows,
    complete_months,
    history_metric_by_month,
    parse_ga4_event_rows,
    SourceResult,
)


class LoadMonthlyApiSnapshotsTest(unittest.TestCase):
    def test_complete_months_defaults_to_previous_complete_month(self) -> None:
        months = complete_months(13, today=date(2026, 6, 12))

        self.assertEqual(months[0].period_id, "2025-05")
        self.assertEqual(months[0].month_start, "2025-05-01")
        self.assertEqual(months[-1].period_id, "2026-05")
        self.assertEqual(months[-1].month_end, "2026-05-31")

    def test_parse_ga4_event_rows_maps_year_month_and_rates(self) -> None:
        rows = [
            {
                "dimensionValues": [{"value": "202605"}],
                "metricValues": [
                    {"value": "100"},
                    {"value": "80"},
                    {"value": "60"},
                    {"value": "10"},
                    {"value": "500"},
                    {"value": "20"},
                ],
            }
        ]

        parsed = parse_ga4_event_rows(rows)

        self.assertEqual(parsed["2026-05"]["sessions"], 100.0)
        self.assertEqual(parsed["2026-05"]["conversion_rate"], 0.1)
        self.assertEqual(parsed["2026-05"]["aov"], 50.0)

    def test_aggregate_gsc_daily_rows_uses_impression_weighted_position(self) -> None:
        months = complete_months(1, end_period="2026-05")
        rows = [
            {"keys": ["2026-05-01"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 4},
            {"keys": ["2026-05-02"], "clicks": 5, "impressions": 300, "ctr": 0.016, "position": 8},
        ]

        parsed = aggregate_gsc_daily_rows(rows, months)

        self.assertEqual(parsed["2026-05"]["gsc_clicks"], 15.0)
        self.assertEqual(parsed["2026-05"]["gsc_impressions"], 400.0)
        self.assertEqual(parsed["2026-05"]["gsc_ctr"], 0.0375)
        self.assertEqual(parsed["2026-05"]["gsc_avg_position"], 7.0)

    def test_history_metric_by_month_extracts_first_last_delta(self) -> None:
        months = complete_months(1, end_period="2026-05")
        payload = {"data": [{"type": "search_engine", "data": [{"date": "2026-05-01", "value": 1.5}, {"date": "2026-05-31", "value": 2.0}]}]}

        parsed = history_metric_by_month(payload, months)

        self.assertEqual(parsed["2026-05"]["start"], 1.5)
        self.assertEqual(parsed["2026-05"]["end"], 2.0)
        self.assertEqual(parsed["2026-05"]["delta"], 0.5)

    def test_build_snapshot_rows_preserves_source_statuses(self) -> None:
        months = complete_months(1, end_period="2026-05")
        client = {
            "slug": "example",
            "name": "Example",
            "ga4": {"property": "properties/1"},
            "searchConsole": {"properties": ["https://example.com/"]},
            "seRanking": {"projectId": 1, "engineId": 2},
        }

        rows = build_snapshot_rows(
            client,
            months,
            "run-1",
            "2026-06-12T00:00:00+00:00",
            SourceResult("succeeded", 1, {"2026-05": {"organic_sessions": 10.0}}),
            SourceResult("failed", error_message="permission denied"),
            SourceResult("missing_config"),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["organic_sessions"], 10.0)
        self.assertEqual(rows[0]["gsc_status"], "failed")
        self.assertEqual(rows[0]["gsc_error"], "permission denied")
        self.assertEqual(rows[0]["se_ranking_status"], "missing_config")


if __name__ == "__main__":
    unittest.main()
