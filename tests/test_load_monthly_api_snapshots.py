from __future__ import annotations

from datetime import date
import unittest

from scripts.load_monthly_api_snapshots import (
    aggregate_gsc_daily_rows,
    aggregate_gsc_page_rows,
    build_page_snapshot_rows,
    build_snapshot_rows,
    classify_page_path,
    complete_months,
    history_metric_by_month,
    normalize_page_path,
    PageSourceResult,
    parse_ga4_page_rows,
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

    def test_complete_months_caps_explicit_current_month_to_today(self) -> None:
        months = complete_months(1, today=date(2026, 6, 17), end_period="2026-06")

        self.assertEqual(months[0].period_id, "2026-06")
        self.assertEqual(months[0].month_start, "2026-06-01")
        self.assertEqual(months[0].month_end, "2026-06-17")

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

    def test_normalize_page_path_strips_host_query_and_trailing_slash(self) -> None:
        self.assertEqual(
            normalize_page_path("https://example.com/collections/Soup/?utm_source=test#grid"),
            "/collections/soup",
        )

    def test_classify_page_path_detects_collection_paths(self) -> None:
        client = {"blogPathContains": "/blogs"}

        self.assertEqual(classify_page_path(client, "/collections/soup"), "collection")
        self.assertEqual(classify_page_path(client, "/blogs/news"), "blog")
        self.assertEqual(classify_page_path(client, "/pages/about"), "other")

    def test_parse_ga4_page_rows_maps_month_and_page_metrics(self) -> None:
        rows = [
            {
                "dimensionValues": [{"value": "202605"}, {"value": "/collections/soup?variant=1"}],
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

        parsed = parse_ga4_page_rows(rows)
        metrics = parsed[("2026-05", "/collections/soup")]

        self.assertEqual(metrics["organic_sessions"], 100.0)
        self.assertEqual(metrics["organic_conversion_rate"], 0.1)

    def test_aggregate_gsc_page_rows_uses_page_key(self) -> None:
        months = complete_months(1, end_period="2026-05")
        rows = [
            {"keys": ["2026-05-01", "https://example.com/collections/soup"], "clicks": 10, "impressions": 100, "position": 4},
            {"keys": ["2026-05-02", "https://example.com/collections/soup/"], "clicks": 5, "impressions": 300, "position": 3},
        ]

        parsed = aggregate_gsc_page_rows(rows, months)
        metrics = parsed[("2026-05", "/collections/soup")]

        self.assertEqual(metrics["gsc_clicks"], 15.0)
        self.assertAlmostEqual(metrics["gsc_avg_position"], 3.25)

    def test_build_page_snapshot_rows_merges_ga4_and_gsc_collection_sources(self) -> None:
        months = complete_months(1, end_period="2026-05")
        client = {"slug": "example-client", "name": "Example Client", "websiteHosts": ["example.com"]}
        ga4_pages = PageSourceResult(
            "succeeded",
            1,
            {("2026-05", "/collections/soup"): {"organic_sessions": 100.0, "organic_revenue": 500.0}},
            source_ref="properties/123",
        )
        gsc_pages = PageSourceResult(
            "succeeded",
            1,
            {("2026-05", "/collections/soup"): {"gsc_clicks": 20.0, "gsc_impressions": 200.0}},
            source_ref="https://example.com/",
        )

        rows = build_page_snapshot_rows(client, months, "run-1", "2026-06-01T00:00:00+10:00", ga4_pages, gsc_pages)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["page_path"], "/collections/soup")
        self.assertEqual(rows[0]["page_type"], "collection")
        self.assertEqual(rows[0]["page_url"], "https://example.com/collections/soup")
        self.assertEqual(rows[0]["organic_sessions"], 100.0)
        self.assertEqual(rows[0]["gsc_clicks"], 20.0)


if __name__ == "__main__":
    unittest.main()
