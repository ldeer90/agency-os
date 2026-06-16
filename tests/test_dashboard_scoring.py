from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from dashboard.api.data import (
    agent_task_row,
    build_finance,
    build_task_ops,
    build_client_details,
    canonical_client_slug,
    enrich_report_links,
    filter_excluded_clients,
    needs_attention,
    overview_details,
    report_period_slug,
    read_client_sidecar_profiles,
    summarize_agent_activity,
)
from dashboard.api.scoring import overall_health, roadmap_health, score_band


class DashboardScoringTests(unittest.TestCase):
    def test_score_band_labels(self) -> None:
        self.assertEqual(score_band(92).label, "Healthy")
        self.assertEqual(score_band(72).label, "Watch")
        self.assertEqual(score_band(60).label, "Needs attention")
        self.assertEqual(score_band(30).label, "Critical")

    def test_overall_health_uses_component_scores(self) -> None:
        payload = {
            "clients": [{"health_score": 1.0, "has_roadmap_items": True, "has_roadmap_content_validated": True}],
            "reporting": [{"readiness_status": "ready"}],
            "delivery": [],
            "comms": [],
            "roadmaps": [{"completion_rate": 1.0}],
            "roadmap_items": [{"client_slug": "client-a", "delivery_status": "done"}],
            "performance": [{"performance_status": "strong"}],
            "data_health": {},
        }
        result = overall_health(payload)
        self.assertGreaterEqual(result["score"], 95)
        self.assertEqual(result["status"], "Healthy")
        self.assertIn("client_setup", result["components"])

    def test_roadmap_health_balances_coverage_evidence_completion_and_risk(self) -> None:
        result = roadmap_health(
            clients=[
                {"client_slug": "client-a", "has_roadmap_items": True, "has_roadmap_content_validated": True},
                {"client_slug": "client-b", "has_roadmap_items": True, "has_roadmap_content_validated": False},
            ],
            roadmaps=[{"planned_items": 4, "completed_items": 0, "missing_evidence_items": 4, "overdue_items": 0, "completion_rate": 0.0}],
            roadmap_items=[
                {"client_slug": "client-a", "priority": "high", "delivery_status": "open"},
                {"client_slug": "client-b", "priority": "medium", "delivery_status": "open"},
            ],
        )

        self.assertEqual(round(result["coverage"]), 100)
        self.assertEqual(round(result["evidence"]), 50)
        self.assertEqual(round(result["completion"]), 0)
        self.assertGreater(result["score"], 0)
        self.assertLess(result["score"], 70)

    def test_overall_health_exposes_roadmap_component_details(self) -> None:
        payload = {
            "clients": [{"health_score": 1.0, "has_roadmap_items": True, "has_roadmap_content_validated": False}],
            "reporting": [{"readiness_status": "ready"}],
            "delivery": [],
            "comms": [],
            "roadmaps": [{"completion_rate": 0.0, "missing_evidence_items": 1}],
            "roadmap_items": [{"client_slug": "client-a", "priority": "high", "delivery_status": "open"}],
            "performance": [{"performance_status": "strong"}],
            "data_health": {},
        }

        result = overall_health(payload)

        self.assertIn("component_details", result)
        self.assertIn("roadmaps", result["component_details"])
        self.assertEqual(result["component_details"]["roadmaps"]["coverage"], 100)
        self.assertEqual(result["component_details"]["roadmaps"]["evidence"], 0)

    def test_needs_attention_is_summary_only(self) -> None:
        payload = {
            "clients": [{"client_slug": "client-a", "client_name": "Client A", "health_status": "needs_attention"}],
            "delivery": [{"client_slug": "client-a", "item_name": "Overdue task", "is_overdue": True, "owner_missing": False}],
            "comms": [{"client_slug": "client-a", "severity": "high", "summary": "Follow-up summary"}],
        }
        items = needs_attention(payload)
        self.assertEqual(len(items), 4)
        self.assertTrue(all("source" in item for item in items))
        self.assertIn("Technical crawl", {item["area"] for item in items})

    def test_filter_excluded_clients_removes_slug_and_name_matches(self) -> None:
        rows = [
            {"client_slug": "bestvpn", "item_name": "Keep out"},
            {"client_slug": "joe-rascal-ducati", "item_name": "Keep out"},
            {"client_slug": None, "item_name": "JoeRascal.com - Keyword Research"},
            {"client_slug": "shop-rongrong", "item_name": "Keep in"},
        ]
        filtered = filter_excluded_clients(rows)
        self.assertEqual(
            filtered,
            [
                {"client_slug": "joe-rascal-ducati", "item_name": "Keep out"},
                {"client_slug": "shop-rongrong", "item_name": "Keep in"},
            ],
        )

    def test_filter_excluded_clients_keeps_restored_active_clients(self) -> None:
        rows = [
            {"client_slug": "acorn-rentals", "client_name": "Acorn Rentals"},
            {"client_slug": "ducati-melbourne", "client_name": "Joe Rascal Ducati"},
            {"client_slug": "joe-rascal-harley", "client_name": "Joe Rascal Harley"},
            {"client_slug": "salad-servers-direct", "client_name": "Salad Servers Direct"},
        ]
        self.assertEqual(filter_excluded_clients(rows), rows)

    def test_task_ops_normalizes_restored_client_alias_tasks(self) -> None:
        payload = {
            "clients": [{"client_slug": "acorn-rentals", "client_name": "Acorn Rentals"}],
            "task_status_by_client": [
                {"client_slug": "acorn-car-rentals", "total_tasks": 30, "open_tasks": 10, "done_tasks": 20}
            ],
            "task_client_detail": [
                {"client_slug": "acorn-car-rentals", "status_label": "In Progress", "is_overdue": False}
            ],
            "ops_drift": [],
        }

        build_task_ops(payload)

        self.assertEqual(payload["task_summary"]["total_tasks"], 30)
        self.assertEqual(payload["task_summary"]["open_tasks"], 10)
        self.assertEqual(payload["task_status_by_client"][0]["client_slug"], "acorn-rentals")
        self.assertEqual(payload["task_client_detail"][0]["client_slug"], "acorn-rentals")

    def test_build_task_ops_summarizes_active_client_tasks(self) -> None:
        payload = {
            "clients": [
                {"client_slug": "client-a", "client_name": "Client A"},
                {"client_slug": "client-b", "client_name": "Client B"},
            ],
            "task_status_by_client": [
                {"client_slug": "client-a", "total_tasks": 3, "open_tasks": 2, "done_tasks": 1, "overdue_tasks": 1, "missing_owner_tasks": 1, "missing_due_date_tasks": 0},
                {"client_slug": "client-b", "total_tasks": 2, "open_tasks": 1, "done_tasks": 1, "overdue_tasks": 0, "missing_owner_tasks": 0, "missing_due_date_tasks": 1},
                {"client_slug": "bestvpn", "total_tasks": 99, "open_tasks": 99, "done_tasks": 0, "overdue_tasks": 99, "missing_owner_tasks": 99, "missing_due_date_tasks": 99},
            ],
            "task_client_detail": [
                {"client_slug": "client-a", "status_label": "In Progress", "is_overdue": True},
                {"client_slug": "client-a", "status_label": "Done", "is_overdue": False},
                {"client_slug": "client-b", "status_label": "Not Started", "is_overdue": False},
                {"client_slug": "bestvpn", "status_label": "In Progress", "is_overdue": True},
            ],
            "ops_drift": [
                {"client_name": "Client A", "status_mismatches": 1, "owner_mismatches": 2, "due_date_mismatches": 0, "stale_client_updates": 3, "drift_issues": 6},
                {"client_name": "BestVPN", "status_mismatches": 50, "owner_mismatches": 0, "due_date_mismatches": 0, "stale_client_updates": 0, "drift_issues": 50},
            ],
        }

        build_task_ops(payload)

        self.assertEqual(payload["task_summary"]["total_tasks"], 5)
        self.assertEqual(payload["task_summary"]["open_tasks"], 3)
        self.assertEqual(payload["task_summary"]["done_tasks"], 2)
        self.assertEqual(payload["task_summary"]["overdue_tasks"], 1)
        self.assertEqual(payload["task_summary"]["missing_owner_tasks"], 1)
        self.assertEqual(payload["task_summary"]["missing_due_date_tasks"], 1)
        self.assertEqual(payload["task_summary"]["drift_issues"], 6)
        self.assertEqual({row["client_slug"] for row in payload["task_status_by_client"]}, {"client-a", "client-b"})
        self.assertEqual({row["client_slug"] for row in payload["task_client_detail"]}, {"client-a", "client-b"})

    def test_build_task_ops_counts_status_distribution_from_named_rows(self) -> None:
        payload = {
            "clients": [{"client_slug": "client-a", "client_name": "Client A"}],
            "task_status_by_client": [{"client_slug": "client-a", "total_tasks": 3, "open_tasks": 2, "done_tasks": 1}],
            "task_client_detail": [
                {"client_slug": "client-a", "status_label": "In Progress", "is_overdue": False},
                {"client_slug": "client-a", "status_label": "In Progress", "is_overdue": True},
                {"client_slug": "client-a", "status_label": "Done", "is_overdue": False},
            ],
            "task_status_distribution": [{"status_label": "stale sql row", "task_count": 99}],
            "ops_drift": [],
        }

        build_task_ops(payload)

        distribution = {row["status_label"]: row for row in payload["task_status_distribution"]}
        self.assertEqual(distribution["In Progress"]["task_count"], 2)
        self.assertEqual(distribution["In Progress"]["overdue_tasks"], 1)
        self.assertEqual(distribution["Done"]["task_count"], 1)
        self.assertNotIn("stale sql row", distribution)

    def test_build_finance_adds_monthly_client_and_health_rows(self) -> None:
        payload = {"clients": [{"client_slug": "acorn-rentals", "client_name": "Acorn Rentals"}]}

        with patch("dashboard.api.data.current_period_id", return_value="2026-06"):
            build_finance(payload)

        self.assertIn("finance_health", payload)
        self.assertGreater(payload["finance_health"]["retainer_total_aud"], 0)
        self.assertGreater(payload["finance_health"]["not_issued_due_amount_aud"], 0)
        self.assertTrue(any(row["period_id"] == "2026-06" for row in payload["finance_monthly"]))
        acorn = next(row for row in payload["finance_clients"] if row["client_slug"] == "acorn-rentals")
        self.assertEqual(acorn["not_issued_due_amount_aud"], 1300)
        self.assertIn(acorn["finance_status"], {"critical", "needs_attention", "watch", "healthy"})

    def test_filter_excluded_clients_checks_ops_drift_client_column(self) -> None:
        rows = [
            {"client": "BestVPN", "drift_issues": 10},
            {"client": "Client A", "drift_issues": 1},
        ]

        self.assertEqual(filter_excluded_clients(rows), [{"client": "Client A", "drift_issues": 1}])

    def test_canonical_client_slug_maps_monday_aliases(self) -> None:
        self.assertEqual(canonical_client_slug("acorn-car-rentals"), "acorn-rentals")
        self.assertEqual(canonical_client_slug("joe-rascal-ducati"), "ducati-melbourne")
        self.assertEqual(canonical_client_slug("salad-servers"), "salad-servers-direct")

    def test_read_client_sidecar_profiles_uses_sanitized_fields_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "client-a.json").write_text(
                json.dumps(
                    {
                        "client": "client-a",
                        "abn": "12 345 678 901",
                        "primary_contact": {"name": "Jane Smith", "role": "Marketing Manager", "email": "jane@example.com"},
                        "domain": "example.com",
                    }
                ),
                encoding="utf-8",
            )
            (root / "client-b.json").write_text(
                json.dumps({"client": "client-b", "primary_contact_name": "person@example.com"}),
                encoding="utf-8",
            )

            profiles = read_client_sidecar_profiles(root)

        self.assertEqual(profiles["client-a"]["abn"], "12 345 678 901")
        self.assertEqual(profiles["client-a"]["primary_contact_name"], "Jane Smith")
        self.assertEqual(profiles["client-a"]["primary_contact_role"], "Marketing Manager")
        self.assertIsNone(profiles["client-b"]["primary_contact_name"])

    def test_build_client_details_shapes_missing_assets_and_related_rows(self) -> None:
        payload = {
            "meta": {},
            "clients": [
                {
                    "client_slug": "client-a",
                    "client_name": "Client A",
                    "missing_required_json": ["GA4 access"],
                    "missing_optional_json": ["Writing style"],
                    "has_roadmap_items": False,
                    "has_roadmap_content_validated": False,
                }
            ],
            "client_profiles": [{"client_slug": "client-a", "client_name": "Client A", "canonical_host": "example.com"}],
            "health_assets": [
                {"client_slug": "client-a", "asset_type": "ga4_access", "asset_label": "Verified GA4 access", "presence_status": "missing", "expected": True},
                {"client_slug": "client-a", "asset_type": "writing_style", "asset_label": "Writing style", "presence_status": "missing", "expected": False},
            ],
            "delivery": [{"client_slug": "client-a", "item_name": "Task"}],
            "performance_history": [{"client_slug": "client-a", "period_id": "2026-06"}],
            "roadmap_items": [],
            "report_links": [{"client_slug": "client-a", "period_id": "2026-06", "share_id": "abc"}],
            "comms": [{"client_slug": "client-a", "summary": "Summary"}],
            "reporting": [{"client_slug": "client-a", "readiness_status": "ready"}],
        }

        details = build_client_details(payload)

        self.assertEqual(details["client-a"]["missing_required"], ["GA4 access"])
        self.assertEqual(len(details["client-a"]["missing_assets"]), 1)
        self.assertTrue(details["client-a"]["roadmap_missing"])
        self.assertEqual(details["client-a"]["reports"][0]["share_id"], "abc")

    def test_report_links_are_enriched_with_public_urls(self) -> None:
        payload = {
            "report_links": [
                {
                    "client_slug": "shop-rongrong",
                    "period_id": "2026-05",
                    "report_month": "2026-05-01",
                    "share_id": "share-123",
                }
            ]
        }

        enrich_report_links(payload, public_base_url="https://reports.example.com")
        row = payload["report_links"][0]

        self.assertEqual(report_period_slug("2026-05"), "may-2026")
        self.assertEqual(row["month_tab"], "2026-05")
        self.assertEqual(row["report_public_path"], "/shop-rongrong/may-2026/share-123/")
        self.assertEqual(row["report_url"], "https://reports.example.com/shop-rongrong/may-2026/share-123/")
        self.assertEqual(row["compact_report_url"], "https://reports.example.com/shop-rongrong/may-2026/share-123/compact/")

    def test_summarize_agent_activity_groups_recent_completed_runs(self) -> None:
        local_runs = [
            {"agent_id": "agent-a", "agent_name": "Agent A", "run_id": "local-1", "status": "succeeded", "completed_at": "2026-06-13T10:00:00Z"},
            {"agent_id": "agent-a", "agent_name": "Agent A", "run_id": "running", "status": "running", "started_at": "2026-06-13T11:00:00Z"},
        ]
        bq_runs = [{"agent_id": "agent-a", "agent_name": "Agent A", "run_id": "bq-1", "status": "failed", "completed_at": "2026-06-13T12:00:00Z"}]
        workflow_runs = [{"agent_id": "agent-b", "run_id": "wf-1", "status": "succeeded", "completed_at": "2026-06-13T09:00:00Z", "summary": "Completed task"}]

        summary = summarize_agent_activity(local_runs, bq_runs, workflow_runs)
        by_agent = {row["agent_id"]: row for row in summary}

        self.assertEqual(by_agent["agent-a"]["failed"], 1)
        self.assertEqual(by_agent["agent-a"]["recent_runs"][0]["run_id"], "bq-1")
        self.assertEqual(by_agent["agent-b"]["recent_runs"][0]["task_summary"], "Completed task")

    def test_agent_task_row_derives_name_and_summary_from_structured_run_json(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_path = root / "reporting_prep_agent" / "run-1.json"
            run_path.parent.mkdir()
            run_path.write_text(
                json.dumps(
                    {
                        "summary": "Reviewed reporting readiness and queued two actions.",
                        "findings": [
                            {
                                "client_slug": "client-a",
                                "finding_type": "reporting_gap",
                                "severity": "medium",
                                "summary": "Reporting source is missing.",
                                "recommended_action": "Connect the missing source.",
                                "qa_status": "needs_review",
                            }
                        ],
                        "actions": [
                            {
                                "client_slug": "client-a",
                                "action_type": "reporting_follow_up",
                                "target_system": "monday",
                                "priority": "medium",
                                "recommended_action": "Create a draft-only follow-up task.",
                                "requires_approval": True,
                                "status": "suggested",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            row = {
                "agent_id": "reporting_prep_agent",
                "agent_name": "Reporting Prep Agent",
                "run_id": "run-1",
                "prompt_version": "reporting_prep_agent/v001",
                "run_json_path": str(run_path),
                "status": "succeeded",
            }

            with patch("dashboard.api.data.AGENT_RUNS_ROOT", root):
                shaped = agent_task_row(row, "data/agent_runs/index.json")

        self.assertEqual(shaped["task_name"], "Review Reporting Follow Up")
        self.assertEqual(shaped["task_summary"], "Reviewed reporting readiness and queued two actions.")
        self.assertEqual(shaped["findings_count"], 1)
        self.assertEqual(shaped["actions_count"], 1)
        self.assertEqual(shaped["findings_preview"][0]["summary"], "Reporting source is missing.")
        self.assertEqual(shaped["actions_preview"][0]["recommended_action"], "Create a draft-only follow-up task.")

    def test_agent_task_row_uses_bigquery_finding_and_action_previews(self) -> None:
        shaped = agent_task_row(
            {"agent_id": "agent-a", "agent_name": "Agent A", "run_id": "bq-1", "status": "succeeded"},
            "agency_control.agent_run_log",
            findings_by_run={
                "bq-1": [
                    {
                        "client_slug": "client-a",
                        "finding_type": "technical_gap",
                        "severity": "high",
                        "summary": "Crawl evidence is stale.",
                        "recommended_action": "Rerun the crawl.",
                        "qa_status": "needs_review",
                    }
                ]
            },
            actions_by_run={
                "bq-1": [
                    {
                        "client_slug": "client-a",
                        "action_type": "crawl_refresh",
                        "target_system": "codex",
                        "priority": "high",
                        "recommended_action": "Run a fresh technical crawl.",
                        "requires_approval": False,
                        "status": "suggested",
                    }
                ]
            },
        )

        self.assertEqual(shaped["findings_preview"][0]["summary"], "Crawl evidence is stale.")
        self.assertEqual(shaped["actions_preview"][0]["recommended_action"], "Run a fresh technical crawl.")

    def test_agent_task_row_uses_workflow_summary_previews(self) -> None:
        shaped = agent_task_row(
            {
                "agent_id": "seo_workflow_router",
                "run_id": "wf-1",
                "workflow_id": "content-brief",
                "client_slug": "client-a",
                "status": "succeeded",
                "blockers_json": [{"summary": "Brief approval is still pending.", "severity": "medium"}],
                "next_actions_json": [{"recommended_action": "Ask for approval before creating the Google Doc.", "priority": "medium"}],
            },
            "agency_memory.seo_workflow_run_summaries",
        )

        self.assertEqual(shaped["findings_preview"][0]["summary"], "Brief approval is still pending.")
        self.assertEqual(shaped["actions_preview"][0]["recommended_action"], "Ask for approval before creating the Google Doc.")

    def test_overview_details_flags_missing_roadmaps_and_reports(self) -> None:
        details = overview_details(
            {
                "meta": {"source_tables": ["table-a"]},
                "clients": [
                    {"client_slug": "client-a", "has_roadmap_items": False, "has_roadmap_content_validated": False, "has_monthly_report_snapshot": False}
                ],
                "health_assets": [{"asset_type": "ga4_access", "presence_status": "missing", "expected": True}],
                "roadmaps": [{"missing_evidence_items": 2, "overdue_items": 1}],
                "roadmap_items": [{"client_slug": "client-a"}],
                "performance_history": [{"period_id": "2026-05"}, {"period_id": "2026-06"}],
                "agent_activity_summary": [{"recent_runs": [{"run_id": "run-1"}]}],
            }
        )

        self.assertEqual(details["missing_assets_by_type"], [{"name": "ga4_access", "value": 1}])
        self.assertEqual(details["roadmap_gap_clients"], ["client-a"])
        self.assertEqual(details["roadmap_coverage"]["clients_total"], 1)
        self.assertEqual(details["roadmap_coverage"]["current_items"], 1)
        self.assertEqual(details["roadmap_coverage"]["missing_evidence_items"], 2)
        self.assertEqual(details["roadmap_coverage"]["overdue_items"], 1)
        self.assertEqual(details["report_gap_clients"], ["client-a"])
        self.assertEqual(details["recent_agent_runs"], 1)

if __name__ == "__main__":
    unittest.main()
