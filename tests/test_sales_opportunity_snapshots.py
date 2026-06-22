from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.load_sales_opportunity_snapshots import (
    SalesOpportunitySite,
    build_quarterly_comparison_sql,
    load_registry,
    parse_quarter,
    parse_se_ranking_payload,
    snapshot_row,
)
from agency_bigquery.cost_config import BigQueryCostConfig


def write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class SalesOpportunitySnapshotTest(unittest.TestCase):
    def registry_payload(self) -> dict:
        return {
            "sites": [
                {
                    "opportunity_slug": "sample-lead",
                    "business_name": "Sample Lead",
                    "domain": "https://www.example.com/path",
                    "site_url": "https://www.example.com/path",
                    "status": "lead",
                    "source": "manual",
                    "owner": "agency_supervisor",
                    "market": "au",
                    "currency": "AUD",
                    "notes_summary": "Approved metadata-only sales opportunity.",
                }
            ]
        }

    def seranking_payload(self) -> dict:
        return {
            "domain_overview": {
                "organic": {
                    "base_domain": "example.com",
                    "price_sum": 897.96,
                    "traffic_sum": 1295,
                    "keywords_new_count": 816,
                    "keywords_down_count": 417,
                    "keywords_up_count": 528,
                    "keywords_equal_count": 6254,
                    "keywords_lost_count": 842,
                    "keywords_count": 6746,
                    "top1_5": 1014,
                    "top6_10": 666,
                    "top11_20": 959,
                    "top21_50": 3019,
                    "top51_100": 2340,
                    "year": 2026,
                    "month": 5,
                }
            },
            "backlinks_summary": {
                "summary": [
                    {
                        "target": "example.com",
                        "backlinks": 57525,
                        "refdomains": 774,
                        "nofollow_backlinks": 12701,
                        "dofollow_backlinks": 44824,
                        "domain_inlink_rank": 43,
                        "pages_with_backlinks": 702,
                    }
                ]
            },
            "retrieved_at": "2026-06-22T10:00:00+10:00",
        }

    def test_registry_normalizes_domain_and_blocks_private_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "sites.json", self.registry_payload())
            sites = load_registry(path)
            self.assertEqual(sites[0].domain, "example.com")
            self.assertEqual(sites[0].site_url, "https://www.example.com/path")

            unsafe = self.registry_payload()
            unsafe["sites"][0]["notes_summary"] = "Call +61 400 000 000 for token handoff"
            unsafe_path = write_json(Path(tmp) / "unsafe.json", unsafe)
            with self.assertRaises(ValueError):
                load_registry(unsafe_path)

    def test_parse_se_ranking_fixture_extracts_sales_metrics(self) -> None:
        parsed = parse_se_ranking_payload(self.seranking_payload(), source="/tmp/seranking.json", market="au")
        self.assertEqual(parsed.status, "succeeded")
        self.assertEqual(parsed.metrics["estimated_organic_traffic"], 1295)
        self.assertEqual(parsed.metrics["organic_keywords_count"], 6746)
        self.assertEqual(parsed.metrics["referring_domains"], 774)
        self.assertEqual(parsed.metrics["domain_inlink_rank"], 43)

    def test_snapshot_row_stores_crawl_references_without_page_body(self) -> None:
        site = SalesOpportunitySite(
            opportunity_slug="sample-lead",
            business_name="Sample Lead",
            domain="example.com",
            status="lead",
            source="manual",
            owner="agency_supervisor",
            market="au",
            currency="AUD",
            site_url="https://example.com",
            notes_summary=None,
        )
        quarter = parse_quarter("2026-Q2")
        parsed = parse_se_ranking_payload(self.seranking_payload(), source="/tmp/seranking.json", market="au")
        row = snapshot_row(
            site,
            quarter,
            parsed,
            snapshot_date=quarter.quarter_end,
            run_id="run-1",
            ingested_at="2026-06-22T10:00:00+10:00",
            crawl_id="sample-lead-quarterly-2026-q2",
            previous_crawl_id="sample-lead-quarterly-2026-q1",
        )
        self.assertEqual(row["quarter_id"], "2026-Q2")
        self.assertEqual(row["crawl_id"], "sample-lead-quarterly-2026-q2")
        self.assertEqual(row["previous_crawl_id"], "sample-lead-quarterly-2026-q1")
        self.assertNotIn("raw_html", json.dumps(row).lower())

    def test_reporting_sql_compares_previous_quarter_and_titles(self) -> None:
        config = BigQueryCostConfig.from_file()
        sql = build_quarterly_comparison_sql(config)
        self.assertIn("sales_opportunity_quarterly_comparison", sql)
        self.assertIn("client_crawl_url_snapshots", sql)
        self.assertIn("title_changed_urls", sql)
        self.assertIn("LAG(estimated_organic_traffic)", sql)
        self.assertIn(" AS\nWITH snapshots AS (", sql)
        self.assertIn("FROM `seo-agency-work.agency_memory.sales_opportunity_seo_snapshots`", sql)
        self.assertIn("FROM enriched", sql)

    def test_dry_run_cli_does_not_require_bigquery_or_live_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = write_json(root / "sites.json", self.registry_payload())
            seranking = write_json(root / "seranking.json", self.seranking_payload())
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/load_sales_opportunity_snapshots.py",
                    "--registry",
                    str(registry),
                    "--opportunity",
                    "sample-lead",
                    "--quarter",
                    "2026-Q2",
                    "--se-ranking-json",
                    str(seranking),
                    "--dry-run",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "planned")
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["snapshot_rows"], 1)


if __name__ == "__main__":
    unittest.main()
