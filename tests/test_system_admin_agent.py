from __future__ import annotations

import unittest

from agency_bigquery.specialist_agents import system_admin_output


CREATED_AT = "2026-06-14T10:00:00+10:00"


def system_row(**overrides: object) -> dict:
    row = {
        "client_slug": "agency-system",
        "check_category": "bigquery_schema",
        "check_name": "dataset:agency_control",
        "check_status": "ok",
        "summary": "BigQuery dataset agency_control is present.",
        "source": "test",
        "details": {},
        "observed_at": CREATED_AT,
    }
    row.update(overrides)
    return row


class SystemAdminAgentTest(unittest.TestCase):
    def test_healthy_sweep_returns_no_findings(self) -> None:
        output = system_admin_output(
            [
                system_row(),
                system_row(check_category="cost_guardrails", check_name="local_cost_config"),
            ],
            run_id="run-1",
            created_at=CREATED_AT,
        )
        self.assertEqual(output["agent_id"], "system_admin_agent")
        self.assertEqual(output["findings"], [])
        self.assertEqual(output["metrics"]["checks_ok"], 2)

    def test_missing_stale_ingestion_run_creates_codex_action(self) -> None:
        output = system_admin_output(
            [
                system_row(
                    check_category="ingestion",
                    check_name="recent_ingestion_runs",
                    check_status="missing",
                    summary="No recent ingestion run rows were found.",
                    finding_type="system_admin_ingestion_gap",
                    severity="high",
                    recommended_action="Run the local dry-run parser before any live reload.",
                )
            ],
            run_id="run-1",
            created_at=CREATED_AT,
        )
        self.assertEqual(output["findings"][0]["finding_type"], "system_admin_ingestion_gap")
        self.assertEqual(output["findings"][0]["severity"], "high")
        self.assertEqual(output["actions"][0]["target_system"], "codex")
        self.assertFalse(output["actions"][0]["requires_approval"])

    def test_failed_or_over_cap_cost_check_is_high_priority(self) -> None:
        output = system_admin_output(
            [
                system_row(
                    check_category="cost_guardrails",
                    check_name="cost_check:large query",
                    check_status="over_cap",
                    summary="Recent capped query was blocked.",
                    finding_type="system_admin_cost_guardrail_event",
                    severity="high",
                )
            ],
            run_id="run-1",
            created_at=CREATED_AT,
        )
        self.assertEqual(output["findings"][0]["severity"], "high")
        self.assertEqual(output["actions"][0]["priority"], "high")

    def test_active_stale_agent_marker_is_flagged(self) -> None:
        output = system_admin_output(
            [
                system_row(
                    check_category="agent_runs",
                    check_name="stale_active_marker:performance_analyst",
                    check_status="stale",
                    summary="Active run marker for performance_analyst appears stale or unreadable.",
                    finding_type="system_admin_stale_agent_marker",
                    severity="medium",
                )
            ],
            run_id="run-1",
            created_at=CREATED_AT,
        )
        self.assertEqual(output["findings"][0]["finding_type"], "system_admin_stale_agent_marker")
        self.assertEqual(output["actions"][0]["target_system"], "codex")

    def test_route_only_health_evidence_is_not_overclaimed(self) -> None:
        output = system_admin_output(
            [
                system_row(
                    client_slug="travelkon",
                    check_category="client_health",
                    check_name="route_verification:travelkon",
                    check_status="warn",
                    summary="TravelKon has route/config evidence that still needs verification: GA4 API access verification.",
                    finding_type="route_verification_gap",
                    details={"route_verification_gaps": ["GA4 API access verification"]},
                    recommended_action="Run the approved read-only verification workflow; do not treat route/config evidence as proven access.",
                )
            ],
            run_id="run-1",
            created_at=CREATED_AT,
        )
        finding = output["findings"][0]
        self.assertEqual(finding["client_slug"], "travelkon")
        self.assertEqual(finding["finding_type"], "route_verification_gap")
        self.assertIn("still needs verification", finding["summary"])
        self.assertNotIn("verified access is available", finding["summary"].lower())


if __name__ == "__main__":
    unittest.main()
