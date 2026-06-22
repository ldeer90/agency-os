from __future__ import annotations

import unittest
from datetime import UTC, datetime

from scripts.langfuse_agencyos_usage_report import (
    LangfuseConfig,
    classify_row,
    duplicate_trace_candidates,
    efficiency_flags,
    input_share,
    records_from_observations,
    render_report,
    summarize_daily,
)


class LangfuseUsageReportTest(unittest.TestCase):
    def test_summarize_daily_metrics(self) -> None:
        summary = summarize_daily(
            [
                {
                    "countTraces": 2,
                    "countObservations": 5,
                    "totalCost": 0.25,
                    "usage": [
                        {"model": "gpt-5.5", "inputUsage": 1000, "outputUsage": 500, "totalUsage": 1500},
                        {"model": "gpt-5.5", "inputUsage": 200, "outputUsage": 300, "totalUsage": 500},
                    ],
                }
            ]
        )

        self.assertEqual(summary["traces"], 2)
        self.assertEqual(summary["observations"], 5)
        self.assertEqual(summary["total"], 2000)
        self.assertEqual(summary["models"]["gpt-5.5"], 2000)

    def test_classify_row_defaults_to_metadata_only(self) -> None:
        agent, task = classify_row(
            {
                "input": "agent=system_admin_agent task=health-check please inspect config",
                "traceContext": {"tags": ["agency-os", "codex-app"]},
            }
        )

        self.assertEqual(agent, "unknown")
        self.assertEqual(task, "unknown")

    def test_classify_row_can_opt_into_io_text(self) -> None:
        agent, task = classify_row(
            {
                "input": "agent=system_admin_agent task=health-check please inspect config",
                "traceContext": {"tags": ["agency-os", "codex-app"]},
            },
            include_io=True,
        )

        self.assertEqual(agent, "system_admin_agent")
        self.assertEqual(task, "health-check")

    def test_records_group_observations_by_trace_metadata_only(self) -> None:
        records = records_from_observations(
            [
                {
                    "traceId": "trace-1",
                    "input": "agent=qa_guardrail task=debugging",
                    "usage": {"input": 100, "output": 50},
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"], "name": "Codex Turn"},
                },
                {
                    "traceId": "trace-1",
                    "usage": {"input": 200, "output": 25},
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"], "name": "Codex Turn"},
                },
            ],
            "https://example.langfuse",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].trace_id, "trace-1")
        self.assertEqual(records[0].agent, "unknown")
        self.assertEqual(records[0].task, "unknown")
        self.assertEqual(records[0].total_tokens, 375)
        self.assertEqual(records[0].observation_count, 2)

    def test_records_group_observations_by_trace_with_io_opt_in(self) -> None:
        records = records_from_observations(
            [
                {
                    "traceId": "trace-1",
                    "input": "agent=qa_guardrail task=debugging",
                    "usage": {"input": 100, "output": 50},
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"], "name": "Codex Turn"},
                }
            ],
            "https://example.langfuse",
            include_io=True,
        )

        self.assertEqual(records[0].agent, "qa_guardrail")
        self.assertEqual(records[0].task, "debugging")

    def test_efficiency_flags(self) -> None:
        records = records_from_observations(
            [
                {
                    "traceId": "trace-1",
                    "usage": {"input": 200_000, "output": 1000},
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"], "name": "Codex Turn"},
                }
            ],
            "https://example.langfuse",
        )

        flags = efficiency_flags(records[0])
        self.assertIn("missing agent/task", flags)
        self.assertIn("deep threshold", flags)
        self.assertIn("high input share", flags)
        self.assertIn("low output / high input", flags)

    def test_render_report_contains_beginner_sections(self) -> None:
        report = render_report(
            start=datetime(2026, 6, 1, tzinfo=UTC),
            end=datetime(2026, 6, 2, tzinfo=UTC),
            config=LangfuseConfig("pk", "sk", "https://example.langfuse", ("agency-os", "codex-app")),
            daily_rows=[],
            observation_records=[],
            observation_error=None,
            include_io=False,
        )

        self.assertIn("AgencyOS Langfuse Usage Report", report)
        self.assertIn("Row-level fields: `metadata-only`", report)
        self.assertIn("Duplicate Trace Candidates", report)
        self.assertIn("Beginner Recommendations", report)
        self.assertIn("Agents By Tokens", report)

    def test_duplicate_trace_candidates_estimate_duplicate_cost(self) -> None:
        records = records_from_observations(
            [
                {
                    "traceId": "trace-a",
                    "usage": {"input": 90_000, "output": 1_000},
                    "totalCost": 0.50,
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"]},
                },
                {
                    "traceId": "trace-b",
                    "usage": {"input": 90_000, "output": 1_000},
                    "totalCost": 0.50,
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"]},
                },
                {
                    "traceId": "trace-c",
                    "usage": {"input": 10_000, "output": 1_000},
                    "totalCost": 0.05,
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"]},
                },
            ],
            "https://example.langfuse",
        )

        duplicates = duplicate_trace_candidates(records)

        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].trace_ids, ("trace-a", "trace-b"))
        self.assertEqual(duplicates[0].duplicate_tokens, 91_000)
        self.assertAlmostEqual(duplicates[0].duplicate_cost, 0.50)


    def test_duplicate_trace_candidates_prefer_codex_turn_id(self) -> None:
        records = records_from_observations(
            [
                {
                    "traceId": "trace-retry",
                    "usage": {"input": 80_000, "output": 500},
                    "totalCost": 0.40,
                    "model": "gpt-5.5",
                    "traceContext": {"metadata": {"codex.turn_id": "turn-1"}},
                },
                {
                    "traceId": "trace-final",
                    "usage": {"input": 90_000, "output": 1_000},
                    "totalCost": 0.50,
                    "model": "gpt-5.5",
                    "traceContext": {"metadata": {"codex.turn_id": "turn-1"}},
                },
            ],
            "https://example.langfuse",
        )

        duplicates = duplicate_trace_candidates(records)

        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].trace_ids, ("trace-final", "trace-retry"))
        self.assertEqual(duplicates[0].duplicate_tokens, 80_500)
        self.assertAlmostEqual(duplicates[0].duplicate_cost, 0.40)
        self.assertIn("same codex.turn_id", duplicates[0].reason)

    def test_input_share_and_many_observation_flags(self) -> None:
        records = records_from_observations(
            [
                {
                    "traceId": "trace-1",
                    "usage": {"input": 900, "output": 100},
                    "model": "gpt-5.5",
                    "traceContext": {"metadata": {"agent": "system_admin_agent", "task": "docs"}},
                }
                for _ in range(25)
            ],
            "https://example.langfuse",
        )

        flags = efficiency_flags(records[0])

        self.assertAlmostEqual(input_share(records[0]), 0.9)
        self.assertIn("high input share", flags)
        self.assertIn("many observations", flags)
        self.assertNotIn("missing agent/task", flags)

    def test_render_report_contains_duplicate_cost_and_actions(self) -> None:
        records = records_from_observations(
            [
                {
                    "traceId": "trace-a",
                    "usage": {"input": 90_000, "output": 1_000},
                    "totalCost": 0.50,
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"]},
                },
                {
                    "traceId": "trace-b",
                    "usage": {"input": 90_000, "output": 1_000},
                    "totalCost": 0.50,
                    "model": "gpt-5.5",
                    "traceContext": {"tags": ["agency-os", "codex-app"]},
                },
            ],
            "https://example.langfuse",
        )
        report = render_report(
            start=datetime(2026, 6, 1, tzinfo=UTC),
            end=datetime(2026, 6, 2, tzinfo=UTC),
            config=LangfuseConfig("pk", "sk", "https://example.langfuse", ("agency-os", "codex-app")),
            daily_rows=[],
            observation_records=records,
            observation_error=None,
            include_io=False,
        )

        self.assertIn("Duplicate candidate cost: $0.5000 USD", report)
        self.assertIn("Estimated duplicate cost: `$0.5000` USD", report)
        self.assertIn("Input Share", report)
        self.assertIn("Recommended Next Actions", report)
        self.assertIn("Duplicate traces detected", report)


if __name__ == "__main__":
    unittest.main()
