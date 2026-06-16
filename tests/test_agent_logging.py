from __future__ import annotations

from datetime import date
import unittest

from agency_bigquery.agent_logging import (
    AgentLoggingError,
    agent_logging_table_plans,
    build_merge_sql,
    build_llm_usage_row,
    build_langfuse_trace_link_row,
    log_agent_output,
    log_langfuse_trace_link,
    log_rows_with_staging_merge,
    validate_logging_batch,
    json_safe_rows,
)
from agency_bigquery.cost_config import BigQueryCostConfig
from agency_bigquery.langfuse_tracing import LangfuseTraceResult


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


def run_row(run_id: str = "run-1") -> dict:
    return {
        "run_id": run_id,
        "agent_id": "promise_tracker",
        "agent_name": "Promise Tracker",
        "started_at": "2026-06-13T00:00:00+00:00",
        "completed_at": "2026-06-13T00:01:00+00:00",
        "status": "succeeded",
        "mode": "local_jsonl",
        "prompt_version": "promise_tracker/v001",
        "context_id": None,
        "input_sources_json": ["local_staged_comms_summary"],
        "output_path": "/tmp/run-1.json",
        "findings_count": 0,
        "actions_count": 0,
        "error_message": None,
        "dry_run": False,
    }


def finding_row(finding_id: str = "finding-1") -> dict:
    return {
        "created_at": "2026-06-13T00:00:00+00:00",
        "run_id": "run-1",
        "agent_id": "promise_tracker",
        "finding_id": finding_id,
        "client_slug": "example-client",
        "finding_type": "promise",
        "severity": "medium",
        "summary": "Potential client commitment.",
        "evidence_json": [{"source": "agency_reporting.client_comms_attention"}],
        "source_tables_json": ["agency_reporting.client_comms_attention"],
        "recommended_action": "Review the commitment.",
        "confidence_score": 0.8,
        "requires_human_review": True,
        "qa_status": "needs_review",
        "status": "open",
        "source_ref_hash": "hash-1",
    }


class FakeJob:
    def __init__(self, job_id: str, *, total_bytes_processed: int = 0) -> None:
        self.job_id = job_id
        self.total_bytes_processed = total_bytes_processed

    def result(self):
        return []


class FakeClient:
    def __init__(self) -> None:
        self.created_datasets = []
        self.created_tables = []
        self.loaded = []
        self.queries = []
        self.inserted = []

    def create_dataset(self, dataset, exists_ok=False):
        self.created_datasets.append({"dataset": dataset, "exists_ok": exists_ok})
        return dataset

    def create_table(self, table, exists_ok=False):
        self.created_tables.append({"table": table, "exists_ok": exists_ok})
        return table

    def load_table_from_json(self, rows, table_id, job_config=None, location=None):
        self.loaded.append({"rows": rows, "table_id": table_id, "job_config": job_config, "location": location})
        return FakeJob("load-job")

    def query(self, sql, job_config=None, location=None):
        self.queries.append({"sql": sql, "job_config": job_config, "location": location})
        is_dry_run = bool(getattr(job_config, "dry_run", False))
        return FakeJob("dry-run-job" if is_dry_run else "merge-job", total_bytes_processed=10_000)

    def insert_rows_json(self, table_id, rows):
        self.inserted.append({"table_id": table_id, "rows": rows})
        return []


class AgentLoggingTest(unittest.TestCase):
    def test_schema_plan_is_allowlisted_with_merge_keys(self) -> None:
        plans = agent_logging_table_plans(test_config())

        self.assertTrue(
            {
                "agent_run_log",
                "llm_usage_log",
                "agent_findings",
                "agent_actions",
                "agent_approvals",
                "context_packs",
                "langfuse_trace_links",
                "seo_workflow_catalog",
                "seo_client_memory_summaries",
                "seo_workflow_readiness",
                "seo_opportunity_queue",
            }.issubset(set(plans)),
        )
        self.assertEqual(("run_id",), plans["agent_run_log"].merge_keys)
        self.assertEqual(("run_id",), plans["langfuse_trace_links"].merge_keys)
        self.assertEqual(("finding_id",), plans["agent_findings"].merge_keys)
        self.assertEqual(("skill_id", "workflow_id"), plans["seo_workflow_catalog"].merge_keys)
        self.assertEqual(("client_slug",), plans["seo_client_memory_summaries"].merge_keys)

    def test_dry_run_default_validates_without_client_calls(self) -> None:
        client = FakeClient()

        result = log_rows_with_staging_merge(client, test_config(), "agent_run_log", [run_row()])

        self.assertTrue(result.dry_run)
        self.assertEqual(result.rows, 1)
        self.assertEqual(client.created_tables, [])
        self.assertEqual(client.loaded, [])
        self.assertEqual(client.queries, [])

    def test_rejects_non_allowlisted_table(self) -> None:
        with self.assertRaises(AgentLoggingError):
            log_rows_with_staging_merge(FakeClient(), test_config(), "client_registry", [run_row()])

    def test_rejects_duplicate_merge_keys(self) -> None:
        plan = agent_logging_table_plans(test_config())["agent_findings"]

        with self.assertRaises(AgentLoggingError):
            validate_logging_batch(plan, [finding_row("same"), finding_row("same")])

    def test_rejects_payload_over_row_cap(self) -> None:
        plan = agent_logging_table_plans(test_config())["agent_findings"]
        row = finding_row()
        row["summary"] = "x" * 100

        with self.assertRaises(AgentLoggingError):
            validate_logging_batch(plan, [row], max_row_bytes=40)

    def test_json_safe_rows_convert_nested_dates(self) -> None:
        rows = json_safe_rows([{"sections_json": {"rows": [{"snapshot_date": date(2026, 6, 13)}]}}])

        self.assertEqual(rows[0]["sections_json"]["rows"][0]["snapshot_date"], "2026-06-13")

    def test_build_merge_sql_uses_keys_and_all_columns(self) -> None:
        config = test_config()
        plan = agent_logging_table_plans(config)["agent_run_log"]

        sql = build_merge_sql(plan, config, "seo-agency-work.agency_staging.agent_log_agent_run_log_run_1")

        self.assertIn("MERGE `seo-agency-work.agency_control.agent_run_log` AS T", sql)
        self.assertIn("USING `seo-agency-work.agency_staging.agent_log_agent_run_log_run_1` AS S", sql)
        self.assertIn("T.`run_id` = S.`run_id`", sql)
        self.assertIn("WHEN MATCHED THEN", sql)
        self.assertIn("WHEN NOT MATCHED THEN", sql)

    def test_explicit_write_stages_then_merges(self) -> None:
        client = FakeClient()

        result = log_rows_with_staging_merge(
            client,
            test_config(),
            "agent_run_log",
            [run_row()],
            dry_run=False,
            batch_id="run-1",
        )

        self.assertFalse(result.dry_run)
        self.assertEqual(result.merge_job_id, "merge-job")
        self.assertEqual(len(client.created_datasets), 1)
        self.assertEqual(len(client.created_tables), 1)
        self.assertEqual(client.loaded[0]["table_id"], "seo-agency-work.agency_staging.agent_log_agent_run_log_run_1")
        self.assertEqual(len(client.queries), 2)
        self.assertIn("MERGE `seo-agency-work.agency_control.agent_run_log`", client.queries[0]["sql"])
        self.assertIn("MERGE `seo-agency-work.agency_control.agent_run_log`", client.queries[1]["sql"])
        self.assertEqual(len(client.inserted), 1)

    def test_log_agent_output_returns_counts(self) -> None:
        loaded = log_agent_output(
            FakeClient(),
            test_config(),
            run_row=run_row(),
            findings=[finding_row()],
            actions=[],
        )

        self.assertEqual(loaded["agent_run_log"], 1)
        self.assertEqual(loaded["agent_findings"], 1)
        self.assertEqual(loaded["agent_actions"], 0)
        self.assertEqual(loaded["context_packs"], 0)

    def test_build_llm_usage_row_accepts_openai_style_usage(self) -> None:
        row = build_llm_usage_row(
            run_row=run_row(),
            usage={"model": "gpt-test", "prompt_tokens": 10, "completion_tokens": 5, "cost_estimate_aud": 0.02},
            logged_at="2026-06-13T00:02:00+00:00",
        )

        plan = agent_logging_table_plans(test_config())["llm_usage_log"]
        validate_logging_batch(plan, [row])
        self.assertEqual(row["prompt_version"], "promise_tracker/v001")
        self.assertEqual(row["input_tokens"], 10)
        self.assertEqual(row["output_tokens"], 5)

    def test_langfuse_trace_link_validates_and_uses_run_id_merge_key(self) -> None:
        trace = LangfuseTraceResult(
            status="emitted",
            enabled=True,
            trace_id="trace-1",
            trace_url="https://langfuse.test/trace/trace-1",
            metadata_sha256="abc123",
            session_id="automation-1",
        )
        row = build_langfuse_trace_link_row(run_row=run_row(), trace_result=trace, emitted_at="2026-06-13T00:02:00+00:00")
        plan = agent_logging_table_plans(test_config())["langfuse_trace_links"]

        validate_logging_batch(plan, [row])
        self.assertEqual(row["run_id"], "run-1")
        self.assertEqual(row["langfuse_trace_id"], "trace-1")

        result = log_langfuse_trace_link(FakeClient(), test_config(), run_row=run_row(), trace_result=trace)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.rows, 1)

    def test_langfuse_trace_link_skips_failed_trace(self) -> None:
        trace = LangfuseTraceResult(status="failed", enabled=True, trace_id="run-1", metadata_sha256="abc123")

        self.assertIsNone(build_langfuse_trace_link_row(run_row=run_row(), trace_result=trace))
        self.assertIsNone(log_langfuse_trace_link(FakeClient(), test_config(), run_row=run_row(), trace_result=trace))


if __name__ == "__main__":
    unittest.main()
