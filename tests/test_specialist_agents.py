from __future__ import annotations

import unittest

from agency_bigquery.specialist_agents import (
    drive_filing_readback_output,
    output_for_agent,
    performance_analyst_output,
    reporting_portal_qa_output,
    se_ranking_hygiene_output,
    technical_audit_output,
)


class SpecialistAgentsTest(unittest.TestCase):
    def test_performance_output_flags_source_gaps_and_metric_movement(self) -> None:
        output = performance_analyst_output(
            [
                {
                    "client_slug": "shop-rongrong",
                    "client_name": "Shop Rongrong",
                    "period_id": "2026-05",
                    "has_ga4": True,
                    "has_search_console": False,
                    "has_se_ranking": True,
                    "organic_sessions_mom_pct": -0.24,
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["agent_id"], "performance_analyst")
        self.assertEqual(len(output["findings"]), 2)
        self.assertTrue(all(finding["evidence_json"] for finding in output["findings"]))
        self.assertTrue(all(action["target_system"] == "codex" for action in output["actions"]))

    def test_drive_output_flags_missing_verification(self) -> None:
        output = drive_filing_readback_output(
            [
                {
                    "client_slug": "travelkon",
                    "client_name": "TravelKon",
                    "has_drive_root": True,
                    "has_drive_root_verified": False,
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["agent_id"], "drive_filing_readback_agent")
        self.assertEqual(output["findings"][0]["finding_type"], "drive_route_readback_gap")

    def test_se_ranking_output_flags_missing_access(self) -> None:
        output = se_ranking_hygiene_output(
            [
                {
                    "client_slug": "travelkon",
                    "client_name": "TravelKon",
                    "has_se_ranking": True,
                    "has_se_ranking_access": False,
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["agent_id"], "se_ranking_hygiene_agent")
        self.assertEqual(output["findings"][0]["finding_type"], "se_ranking_hygiene_gap")

    def test_reporting_portal_output_flags_coverage_gaps(self) -> None:
        output = reporting_portal_qa_output(
            [
                {
                    "client_slug": "travelkon",
                    "client_name": "TravelKon",
                    "readiness_status": "needs_attention",
                    "coverage_status": "partial",
                    "has_ga4": True,
                    "has_search_console": True,
                    "has_se_ranking": False,
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["agent_id"], "reporting_portal_qa_agent")
        self.assertEqual(output["findings"][0]["finding_type"], "reporting_portal_qa_gap")

    def test_technical_audit_output_routes_screaming_frog_review(self) -> None:
        output = technical_audit_output(
            [
                {
                    "client_slug": "travelkon",
                    "client_name": "TravelKon",
                    "domain": "travelkon.com.au",
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["agent_id"], "technical_audit_agent")
        self.assertEqual(output["findings"][0]["finding_type"], "technical_crawl_evidence_review")
        self.assertIn("Screaming Frog MCP", output["actions"][0]["recommended_action"])
        self.assertEqual(output["actions"][0]["target_system"], "codex")

    def test_output_for_agent_rejects_unknown_agent(self) -> None:
        with self.assertRaises(ValueError):
            output_for_agent("missing_agent", [], run_id="run-1", created_at="2026-06-13T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
