from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agency_bigquery.agent_logging import agent_logging_table_plans, validate_logging_batch
from agency_bigquery.cost_config import BigQueryCostConfig
from agency_bigquery.schema import agent_operating_table_specs
from agency_bigquery.seo_automation_catalog import (
    SeoAutomationCatalogError,
    agent_output_from_opportunities,
    build_client_memory_summary_rows,
    build_workflow_catalog_rows,
    client_readiness_rows,
    opportunity_rows_from_context,
    seo_workflow_router_output,
)


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


def write_fake_seo_automation(root: Path) -> None:
    (root / "docs/agent/workflows").mkdir(parents=True)
    (root / "docs/agent/clients").mkdir(parents=True)
    (root / "docs/agent/routing-manifest.json").write_text(
        json.dumps(
            {
                "skills": {
                    "ld-seo-audits-reporting": {
                        "commands_or_intents": ["/ldseo-monthly-report <client>", "monthly report"],
                        "workflow_docs": ["docs/agent/workflows/monthly-performance-comment.md"],
                        "required_preflight_reads": ["docs/agent/client-memory.md"],
                        "scripts": ["scripts/run_screaming_frog_audit.py"],
                        "validators": ["scripts/validate_client_json.py"],
                        "api_dependencies": ["GA4", "GSC", "SE Ranking"],
                        "mcp_dependencies": ["Google Drive MCP"],
                        "write_gates": ["do not post before approval"],
                        "proof_block_fields": ["client", "warnings"],
                        "notes": "Reporting route.",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "docs/agent/workflows/monthly-performance-comment.md").write_text(
        "# Monthly Performance Comment\n\nDraft-only report workflow.\n",
        encoding="utf-8",
    )
    (root / "docs/agent/clients/example-client.md").write_text("# Example Client\n", encoding="utf-8")
    (root / "docs/agent/clients/example-client.json").write_text(
        json.dumps(
            {
                "client": "Example Client",
                "domain": "example.com",
                "site_type": "ecommerce",
                "market_scope": "AU",
                "ga4_property": "properties/123",
                "drive": {"client_folder_id": "folder123", "folders": {"07_reports": "reports123"}},
                "monday": {"board_id": "123"},
                "se_ranking": {"project_id": 456, "engines": {"AU": 789}},
                "collections": [{"slug": "shirts"}],
                "raw_email_body": "this should be filtered",
                "private_notes": "this should be filtered",
            }
        ),
        encoding="utf-8",
    )
    (root / "docs/agent/clients/example-client-timeline.md").write_text(
        "# Example Timeline\n\n"
        "| Date | Task | Request / source | Evidence checked | Outputs | Decisions | Caveats | Next action | Proof summary |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| 2026-06-01 | Report draft | User asked for a draft. | GA4 and GSC summaries. | Draft note created. | Draft only. | No raw docs stored. | Review wording. | Validator passed. |\n",
        encoding="utf-8",
    )


class SeoAutomationCatalogTest(unittest.TestCase):
    def test_workflow_catalog_parses_routing_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_seo_automation(root)

            rows = build_workflow_catalog_rows(root=root, run_id="run-1", synced_at="2026-06-13T00:00:00+00:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["workflow_id"], "monthly-performance-comment")
        self.assertEqual(rows[0]["family"], "reporting")
        self.assertEqual(rows[0]["title"], "Monthly Performance Comment")
        self.assertIn("GA4", rows[0]["api_dependencies_json"])

    def test_client_memory_summaries_exclude_raw_private_fields_and_summarize_timeline(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_seo_automation(root)

            rows = build_client_memory_summary_rows(root=root, run_id="run-1", synced_at="2026-06-13T00:00:00+00:00")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["client_slug"], "example-client")
        self.assertTrue(row["brief_present"])
        self.assertTrue(row["sidecar_present"])
        self.assertEqual(row["collection_count"], 1)
        dumped = json.dumps(row)
        self.assertNotIn("raw_email_body", dumped)
        self.assertNotIn("private_notes", dumped)
        self.assertNotIn("User asked for a draft. | GA4", dumped)
        self.assertEqual(row["recent_timeline_summary_json"][0]["task"], "Report draft")
        self.assertIn("source_ref_hash", row["recent_timeline_summary_json"][0])

    def test_secret_like_sidecar_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_seo_automation(root)
            path = root / "docs/agent/clients/example-client.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["notes"] = ["api_key=abc123"]
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SeoAutomationCatalogError):
                build_client_memory_summary_rows(root=root, run_id="run-1")

    def test_readiness_and_opportunity_rows_validate_against_logging_plans(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_seo_automation(root)
            client_rows = build_client_memory_summary_rows(root=root, run_id="run-1")
            readiness = client_readiness_rows(client_rows)
            opportunities = opportunity_rows_from_context(client_rows=client_rows)

        plans = agent_logging_table_plans(test_config())
        validate_logging_batch(plans["seo_client_memory_summaries"], client_rows)
        validate_logging_batch(plans["seo_workflow_readiness"], readiness)
        validate_logging_batch(plans["seo_opportunity_queue"], opportunities)
        self.assertEqual(readiness[0]["readiness_status"], "ready")
        self.assertEqual(opportunities[0]["workflow_id"], "collection-seo-full")

    def test_router_and_opportunity_outputs_use_agent_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_seo_automation(root)
            workflows = build_workflow_catalog_rows(root=root, run_id="run-1")
            clients = build_client_memory_summary_rows(root=root, run_id="run-1")
            opportunities = opportunity_rows_from_context(client_rows=clients)

        routed = seo_workflow_router_output(
            request_text="Prepare the monthly report",
            workflow_rows=workflows,
            client_rows=clients,
            run_id="run-1",
            created_at="2026-06-13T00:00:00+00:00",
        )
        opp_output = agent_output_from_opportunities(
            opportunities=opportunities,
            run_id="run-2",
            agent_id="seo_opportunity_agent",
            created_at="2026-06-13T00:00:00+00:00",
        )
        self.assertEqual(routed["actions"][0]["target_system"], "codex")
        self.assertFalse(routed["actions"][0]["requires_approval"])
        self.assertEqual(opp_output["findings"][0]["qa_status"], "needs_review")

    def test_agent_operating_specs_include_seo_automation_tables(self) -> None:
        table_names = {spec.table for spec in agent_operating_table_specs(test_config())}
        self.assertIn("seo_workflow_catalog", table_names)
        self.assertIn("seo_client_memory_summaries", table_names)
        self.assertIn("seo_workflow_readiness", table_names)
        self.assertIn("seo_opportunity_queue", table_names)


if __name__ == "__main__":
    unittest.main()

