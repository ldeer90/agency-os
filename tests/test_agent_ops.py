from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agency_bigquery.agent_ops import (
    AgentValidationError,
    AgentPermissions,
    agent_activity_for_date,
    agent_activity_markdown,
    agent_run_activity_entry,
    approval_decision_to_action_status,
    build_agent_approval_row,
    build_context_pack,
    daily_brief_markdown,
    load_agent_permissions,
    clean_client_slug,
    mark_agent_run_completed,
    mark_agent_run_started,
    normalize_action,
    normalize_finding,
    promise_tracker_output,
    sanitize_context_pack_sections,
    task_hygiene_issues,
    validate_permissions_safe_default,
)
from agency_bigquery.agency_ops_ingestion import monthly_report_snapshot_status
from agency_bigquery.cost_config import BigQueryCostConfig
from agency_bigquery.schema import agent_operating_table_specs, agency_ops_table_specs, plan_agent_operating_tables


def test_config() -> BigQueryCostConfig:
    return BigQueryCostConfig(
        project_id="seo-agency-work",
        default_location="australia-southeast1",
        pricing_mode="on_demand",
        currency="AUD",
        monthly_budget_amount=10,
        normal_query_cap_bytes=1_073_741_824,
        admin_override_query_cap_bytes=10_737_418_240,
        dry_run_required=True,
        control_dataset="agency_control",
        staging_dataset="agency_staging",
        memory_dataset="agency_memory",
        reporting_dataset="agency_reporting",
        cost_checks_table="cost_checks",
        staging_table_expiry_hours=72,
        budget_alert_thresholds=(0.5, 0.8, 1.0),
        raw_dataset_policy={},
    )


class AgentOpsTest(unittest.TestCase):
    def test_monthly_report_snapshot_status_accepts_dict_or_string_json(self) -> None:
        report = {
            "report_month": "2026-06-01",
            "headline_metrics_json": {
                "ga4_current": {"sessions": 100},
                "search_console_summary": {"clicks": 10},
            },
            "commentary_json": {"summary": "Good month."},
        }

        self.assertEqual(monthly_report_snapshot_status(report)[0], "present")
        string_report = {
            **report,
            "headline_metrics_json": json.dumps(report["headline_metrics_json"]),
            "commentary_json": json.dumps(report["commentary_json"]),
        }
        self.assertEqual(monthly_report_snapshot_status(string_report)[0], "present")

    def test_permissions_yaml_defaults_to_no_external_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "permissions.yaml"
            path.write_text(
                "dry_run_default: true\n"
                "allow_email_send: false\n"
                "allow_monday_write: false\n"
                "allow_drive_write: false\n"
                "require_approval_for_external_actions: true\n",
                encoding="utf-8",
            )

            permissions = load_agent_permissions(path)

        validate_permissions_safe_default(permissions)
        self.assertTrue(permissions.dry_run_default)
        self.assertFalse(permissions.allow_email_send)
        self.assertFalse(permissions.allow_monday_write)
        self.assertFalse(permissions.allow_drive_write)

        with self.assertRaises(AgentValidationError):
            validate_permissions_safe_default(AgentPermissions(allow_monday_write=True))

    def test_permissions_fail_closed_for_unknown_enabled_allow_key(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "permissions.yaml"
            path.write_text("allow_surprise_external_write: true\n", encoding="utf-8")

            with self.assertRaises(AgentValidationError):
                load_agent_permissions(path)

    def test_findings_require_evidence(self) -> None:
        with self.assertRaises(AgentValidationError):
            normalize_finding(
                {
                    "client_slug": "example-client",
                    "summary": "Traffic dropped.",
                    "severity": "medium",
                    "confidence_score": 0.7,
                },
                run_id="run-1",
                agent_id="qa_guardrail",
            )

    def test_client_aliases_are_normalized(self) -> None:
        self.assertEqual(clean_client_slug("acorn-car-rentals"), "acorn-rentals")
        self.assertEqual(clean_client_slug("joe-rascal-ducati"), "ducati-melbourne")
        self.assertEqual(clean_client_slug("salad-servers"), "salad-servers-direct")

    def test_task_hygiene_flags_metadata_issues(self) -> None:
        issues = task_hygiene_issues(
            {
                "client_slug": "acorn-car-rentals",
                "item_name": "Update service pages",
                "owner": "",
                "due_date": "2026-03-17",
                "normalized_status": "Not Started",
            },
            today=date(2026, 6, 13),
        )

        self.assertIn("client_alias_needs_normalisation", issues)
        self.assertIn("missing_owner", issues)
        self.assertIn("stale_or_overdue_due_date", issues)

    def test_context_pack_sanitises_private_or_raw_fields(self) -> None:
        sections = sanitize_context_pack_sections(
            {
                "client_health": [
                    {
                        "client_slug": "travelkon",
                        "raw_email_body": "do not store",
                        "private_notes": "do not store",
                        "summary": "x" * 800,
                    }
                ],
                "metadata": {"credential_path": "/tmp/secret.json", "status": "ok"},
            }
        )

        self.assertEqual(sections["client_health"][0]["summary"], "x" * 500)
        self.assertNotIn("raw_email_body", sections["client_health"][0])
        self.assertNotIn("private_notes", sections["client_health"][0])
        self.assertNotIn("credential_path", sections["metadata"])

    def test_build_context_pack_uses_sanitised_sections(self) -> None:
        context_pack = build_context_pack(
            agent_id="agency_supervisor",
            source_tables=["agency_reporting.client_health_check"],
            sections={"raw_message": "forbidden", "summary": "safe"},
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )

        self.assertNotIn("raw_message", context_pack["sections_json"])
        self.assertEqual(context_pack["sections_json"]["summary"], "safe")

    def test_crawl_memory_table_specs_are_partitioned_and_sanitised(self) -> None:
        specs = {(spec.dataset, spec.table): spec for spec in agency_ops_table_specs(test_config())}

        runs = specs[("agency_memory", "client_crawl_runs")]
        urls = specs[("agency_memory", "client_crawl_url_snapshots")]
        latest = specs[("agency_reporting", "client_crawl_latest")]
        comparison = specs[("agency_reporting", "client_crawl_comparison")]

        self.assertEqual(runs.partition_field, "crawl_date")
        self.assertEqual(urls.partition_field, "crawl_date")
        self.assertEqual(latest.partition_field, "crawl_date")
        self.assertEqual(comparison.partition_field, "current_crawl_date")
        self.assertIn("retention_expires_on", runs.schema_by_name)
        self.assertIn("retention_expires_on", urls.schema_by_name)
        self.assertNotIn("raw_html", urls.schema_by_name)
        self.assertNotIn("visible_text", urls.schema_by_name)
        self.assertEqual(runs.cluster_fields, ("client_slug", "crawl_trigger", "crawler"))
        self.assertEqual(urls.cluster_fields, ("client_slug", "url_hash"))

    def test_external_actions_require_approval_and_valid_status(self) -> None:
        evidence = [{"source": "agency_reporting.client_task_status", "item_id": "123"}]

        with self.assertRaises(AgentValidationError):
            normalize_action(
                {
                    "client_slug": "example-client",
                    "target_system": "monday",
                    "recommended_action": "Create a task.",
                    "priority": "medium",
                    "status": "suggested",
                    "requires_approval": False,
                    "evidence": evidence,
                },
                run_id="run-1",
                agent_id="promise_tracker",
            )

        action = normalize_action(
            {
                "client_slug": "example-client",
                "target_system": "monday",
                "recommended_action": "Review the source task.",
                "priority": "medium",
                "status": "needs_review",
                "requires_approval": True,
                "evidence": evidence,
            },
            run_id="run-1",
            agent_id="promise_tracker",
        )
        self.assertEqual(action["status"], "needs_review")

    def test_approval_rows_validate_and_map_decisions_to_action_status(self) -> None:
        approval = build_agent_approval_row(
            action_id="action-1",
            run_id="run-1",
            client_slug="Example Client",
            decision="approved",
            decided_by="laurence",
            decided_at="2026-06-13T00:00:00+00:00",
        )

        self.assertEqual(approval["client_slug"], "example-client")
        self.assertEqual(approval["decision"], "approved")
        self.assertEqual(approval_decision_to_action_status("completed"), "completed")
        with self.assertRaises(AgentValidationError):
            approval_decision_to_action_status("maybe")

    def test_promise_tracker_detects_clear_and_uncertain_promises(self) -> None:
        output = promise_tracker_output(
            [
                {
                    "client_slug": "Example Client",
                    "summary": "We will send the audit update by Friday.",
                    "recommended_action": "Confirm the audit update is scheduled.",
                    "week_start": "2026-06-08",
                    "week_end": "2026-06-12",
                    "urgency": "medium",
                    "source_table": "agency_reporting.client_comms_attention",
                },
                {
                    "client_slug": "Example Client",
                    "summary": "Check whether the client is still waiting on us.",
                    "recommended_action": "Review whether a follow-up is needed.",
                    "waiting_on_us": True,
                    "week_start": "2026-06-08",
                    "week_end": "2026-06-12",
                },
                {
                    "client_slug": "Example Client",
                    "summary": "Client said thanks.",
                    "week_start": "2026-06-08",
                    "week_end": "2026-06-12",
                },
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )

        self.assertEqual(output["metrics"]["promises_found"], 2)
        self.assertEqual(len(output["actions"]), 2)
        self.assertIn("needs_review", {action["status"] for action in output["actions"]})
        self.assertTrue(all(action["requires_approval"] for action in output["actions"]))

    def test_daily_brief_has_required_sections(self) -> None:
        promise_output = promise_tracker_output(
            [
                {
                    "client_slug": "travelkon",
                    "summary": "We will include this in next month.",
                    "recommended_action": "Check whether next month's work includes this.",
                    "week_start": "2026-06-08",
                    "week_end": "2026-06-12",
                }
            ],
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )

        markdown = daily_brief_markdown(
            brief_date=date(2026, 6, 13),
            client_health=[{"client_slug": "travelkon", "health_status": "needs_attention", "critical_missing_assets": 1}],
            delivery_items=[{"client_slug": "travelkon", "item_name": "June blog", "due_date": "2026-06-12", "normalized_status": "In Progress"}],
            promise_output=promise_output,
            activity={
                "metrics": {"runs_today": 1, "active_runs": 0, "failed": 0},
                "runs": [{"agent_id": "promise_tracker", "status": "succeeded", "run_id": "run-1", "output_path": "/tmp/run-1.json"}],
            },
        )

        for heading in (
            "## Focus Today",
            "## Client Health",
            "## Promises And Follow-Ups",
            "## Monday Hygiene",
            "## SEO Automation Workflows",
            "## Suggested Actions",
            "## Actions Needing Approval",
            "## Agent Activity Visibility",
            "## Safety Notes",
        ):
            self.assertIn(heading, markdown)
        self.assertNotIn("## Delivery Risks", markdown)

    def test_local_agent_activity_index_and_active_marker(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            index_path = base / "index.json"
            active_dir = base / "active"
            run_entry = agent_run_activity_entry(
                run_id="run-1",
                automation_id="auto-1",
                agent_id="promise_tracker",
                agent_name="Promise Tracker",
                started_at="2026-06-13T01:00:00+00:00",
                status="running",
                mode="local_jsonl",
                input_sources=["input.jsonl"],
                output_path="/tmp/run-1.json",
                run_json_path="/tmp/run-1.json",
                dry_run=True,
            )

            mark_agent_run_started(index_path, active_dir, run_entry)
            active = agent_activity_for_date(index_path, active_dir, date(2026, 6, 13))
            self.assertEqual(active["metrics"]["active_runs"], 1)
            self.assertEqual(active["metrics"]["runs_today"], 1)
            self.assertEqual(active["runs"][0]["automation_id"], "auto-1")

            completed = {
                **run_entry,
                "status": "succeeded",
                "completed_at": "2026-06-13T01:01:00+00:00",
                "findings_count": 2,
                "actions_count": 1,
            }
            mark_agent_run_completed(index_path, active_dir, completed)
            summary = agent_activity_for_date(index_path, active_dir, date(2026, 6, 13))
            self.assertEqual(summary["metrics"]["active_runs"], 0)
            self.assertEqual(summary["metrics"]["succeeded"], 1)
            self.assertIn("promise_tracker: succeeded run run-1", agent_activity_markdown(summary))

    def test_agent_operating_table_specs_include_required_tables(self) -> None:
        table_names = {spec.table for spec in agent_operating_table_specs(test_config())}
        run_log_fields = {name for name, _, _ in next(spec.schema for spec in agent_operating_table_specs(test_config()) if spec.table == "agent_run_log")}

        self.assertTrue(
            {
                "agent_run_log",
                "llm_usage_log",
                "agent_findings",
                "agent_actions",
                "agent_approvals",
                "context_packs",
                "seo_workflow_catalog",
                "seo_client_memory_summaries",
                "seo_workflow_readiness",
                "seo_opportunity_queue",
            }.issubset(table_names)
        )
        self.assertIn("automation_id", run_log_fields)

    def test_agent_operating_table_plan_reports_missing_without_mutation(self) -> None:
        class NotFound(Exception):
            pass

        class FakeClient:
            def __init__(self) -> None:
                self.get_table_calls = []
                self.create_table_calls = []

            def get_table(self, table_id):
                self.get_table_calls.append(table_id)
                raise NotFound("missing")

        client = FakeClient()
        plan = plan_agent_operating_tables(client, test_config())

        self.assertTrue(plan)
        self.assertTrue(all(row["status"] == "missing" for row in plan))
        self.assertEqual(client.create_table_calls, [])


if __name__ == "__main__":
    unittest.main()
