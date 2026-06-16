from __future__ import annotations

import unittest

from agency_bigquery.specialist_agents import (
    content_research_output,
    content_writer_output,
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

    def test_content_research_output_flags_missing_research_inputs(self) -> None:
        output = content_research_output(
            [
                {
                    "client_slug": "joe-rascal-harley",
                    "client_name": "Joe Rascal Harley",
                    "domain": "joerascalharley.com.au",
                    "sidecar_present": True,
                    "brief_present": True,
                    "timeline_present": True,
                    "has_se_ranking": False,
                    "has_search_console_route": True,
                    "has_drive_root": True,
                    "has_monday_route": True,
                    "collection_count": 10,
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["agent_id"], "content_research_agent")
        self.assertEqual(output["findings"][0]["finding_type"], "content_research_readiness_blocker")
        self.assertIn("SE Ranking route", output["findings"][0]["summary"])
        self.assertIn("Local HTML previews", output["actions"][0]["recommended_action"])

    def test_content_research_output_routes_ready_client_to_brief_process(self) -> None:
        output = content_research_output(
            [
                {
                    "client_slug": "joe-rascal-harley",
                    "client_name": "Joe Rascal Harley",
                    "domain": "joerascalharley.com.au",
                    "sidecar_present": True,
                    "brief_present": True,
                    "timeline_present": True,
                    "has_se_ranking": True,
                    "has_search_console_route": True,
                    "has_drive_root": True,
                    "has_monday_route": True,
                    "collection_count": 10,
                    "deliverables_json": {
                        "competitor_serp_json": {"updated": "2026-06-13"},
                        "collection_content_briefs": {"updated": "2026-06-13"},
                    },
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["findings"][0]["finding_type"], "content_research_workflow_ready")
        self.assertIn("ld-seo-collection-seo", output["actions"][0]["recommended_action"])
        self.assertIn("Salad Servers", output["actions"][0]["recommended_action"])
        self.assertIn("local HTML", output["actions"][0]["recommended_action"])
        self.assertIn("content_writer_agent", output["actions"][0]["recommended_action"])
        self.assertIn("agency_supervisor", output["actions"][0]["recommended_action"])
        self.assertIn("Monday task", output["actions"][0]["recommended_action"])

    def test_content_writer_output_blocks_when_no_approved_targets(self) -> None:
        output = content_writer_output(
            [
                {
                    "client_slug": "joe-rascal-harley",
                    "client_name": "Joe Rascal Harley",
                    "domain": "joerascalharley.com.au",
                    "sidecar_present": True,
                    "brief_present": True,
                    "timeline_present": True,
                    "has_se_ranking": True,
                    "has_search_console_route": True,
                    "collection_count": 0,
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["agent_id"], "content_writer_agent")
        self.assertEqual(output["findings"][0]["finding_type"], "content_writer_readiness_blocker")
        self.assertIn("same local research files", output["actions"][0]["recommended_action"])

    def test_content_writer_output_routes_ready_client_to_local_html_drafting(self) -> None:
        output = content_writer_output(
            [
                {
                    "client_slug": "joe-rascal-harley",
                    "client_name": "Joe Rascal Harley",
                    "domain": "joerascalharley.com.au",
                    "sidecar_present": True,
                    "brief_present": True,
                    "timeline_present": True,
                    "has_se_ranking": True,
                    "has_search_console_route": True,
                    "collection_count": 5,
                    "source_ref_hash": "abc",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(output["findings"][0]["finding_type"], "content_writer_workflow_ready")
        self.assertIn("same local research pack", output["actions"][0]["recommended_action"])
        self.assertIn("agency_supervisor", output["actions"][0]["recommended_action"])
        self.assertIn("approval", output["actions"][0]["recommended_action"])

    def test_output_for_agent_rejects_unknown_agent(self) -> None:
        with self.assertRaises(ValueError):
            output_for_agent("missing_agent", [], run_id="run-1", created_at="2026-06-13T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
