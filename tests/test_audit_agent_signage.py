from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_agent_signage import (
    audit,
    audit_agent_specs,
    audit_registry_coverage,
    audit_stale_schema_terms,
    rel_path,
    write_report,
)


def write_base_fixture(root: Path) -> None:
    (root / "docs").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "prompts" / "example_agent").mkdir(parents=True)
    (root / "AGENTS.md").write_text(
        "Do not print credentials or store raw private content.\n",
        encoding="utf-8",
    )
    (root / "HANDOVER.md").write_text(
        "Use `agency_control.ingestion_runs` with `source_path`.\n"
        "Use `agency_control.cost_checks` with `logged_at`.\n"
        "Do not print credentials.\n",
        encoding="utf-8",
    )
    (root / "docs" / "QUERY_COOKBOOK.md").write_text(
        "Schema note: `agency_control.ingestion_runs` uses `source_path`, not `source_name`.\n"
        "Schema note: `agency_control.cost_checks` uses `logged_at`, not `created_at` or `check_time`.\n"
        "Do not read raw Drive or credential values.\n",
        encoding="utf-8",
    )
    (root / "docs" / "AGENCY_OPS_MEMORY_V1.md").write_text(
        "BigQuery is read-only. Do not store credentials or raw private content.\n",
        encoding="utf-8",
    )
    (root / "docs" / "AGENT_POOL_REGISTRY.md").write_text(
        "| Agent | Status | Role | Runner |\n"
        "| --- | --- | --- | --- |\n"
        "| `example_agent` | active-runner | Example | `scripts/run_example_agent.py` |\n"
        "Do not expose credentials.\n",
        encoding="utf-8",
    )
    (root / "agents" / "example_agent.md").write_text(
        "# Example Agent\n\n"
        "## Identity\nIdentify as `example_agent`.\n\n"
        "## Purpose\nCheck docs.\n\n"
        "## Inputs\nMarkdown files.\n\n"
        "## Outputs\nFindings.\n\n"
        "## Safety\nDo not print credentials or store raw private content.\n",
        encoding="utf-8",
    )
    prompt = "# Example Prompt\n\nUse evidence. Do not expose secrets.\n"
    (root / "prompts" / "example_agent" / "current.md").write_text(prompt, encoding="utf-8")
    (root / "prompts" / "example_agent" / "v001.md").write_text(prompt, encoding="utf-8")


class AgentSignageAuditTest(unittest.TestCase):
    def test_stale_schema_terms_ignore_do_not_use_notes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "doc.md"
            doc.write_text(
                "Schema note: `agency_control.ingestion_runs` uses `source_path`, not `source_name`.\n"
                "Active query: SELECT source_name FROM `agency_control.ingestion_runs`.\n"
                "Do not use `created_at` or `check_time` for `agency_control.cost_checks`.\n",
                encoding="utf-8",
            )

            issues = audit_stale_schema_terms([doc], root)

            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0].path, rel_path(doc, root))
            self.assertEqual(issues[0].line, 2)

    def test_missing_agent_sections_are_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agents").mkdir()
            spec = root / "agents" / "example_agent.md"
            spec.write_text("# Example\n\n## Identity\nExample.\n", encoding="utf-8")

            messages = [issue.message for issue in audit_agent_specs(root)]

            self.assertIn("Agent spec missing ## Purpose section.", messages)
            self.assertIn("Agent spec missing ## Inputs section.", messages)
            self.assertIn("Agent spec missing ## Outputs section.", messages)
            self.assertIn("Agent spec missing ## Safety section.", messages)

    def test_registry_agents_without_prompt_or_spec_are_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "AGENT_POOL_REGISTRY.md").write_text(
                "| Agent | Status | Role | Runner |\n"
                "| --- | --- | --- | --- |\n"
                "| `missing_agent` | active-runner | Missing | planned runner |\n",
                encoding="utf-8",
            )

            issue_paths = {issue.path for issue in audit_registry_coverage(root)}

            self.assertIn("agents/missing_agent.md", issue_paths)
            self.assertIn("prompts/missing_agent/current.md", issue_paths)

    def test_current_prompt_matching_version_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_base_fixture(root)

            report = audit(root, skill_root=root / "missing-skills")
            drift = [issue for issue in report["issues"] if issue["check"] == "prompt_version_drift"]

            self.assertEqual(drift, [])

    def test_current_prompt_pointer_to_existing_version_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_base_fixture(root)
            (root / "prompts" / "example_agent" / "current.md").write_text(
                "# Example Prompt current\n\nCurrent approved version: `v001.md`.\n",
                encoding="utf-8",
            )

            report = audit(root, skill_root=root / "missing-skills")
            drift = [issue for issue in report["issues"] if issue["check"] == "prompt_version_drift"]

            self.assertEqual(drift, [])

    def test_json_report_shape_is_stable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_base_fixture(root)
            report_dir = root / "reports"

            report = audit(root, skill_root=root / "missing-skills")
            path = write_report(report, report_dir)
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(payload["status"], "completed")
            self.assertIn("generated_at", payload)
            self.assertEqual(payload["counts"], {"error": 0, "info": 0, "total": 0, "warning": 0})
            self.assertEqual(payload["issues"], [])
            self.assertEqual(payload["scanned"]["active_registry_agents"], 1)


if __name__ == "__main__":
    unittest.main()
