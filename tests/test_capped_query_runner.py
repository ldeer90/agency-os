from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from agency_bigquery.cost_config import BigQueryCostConfig
from agency_bigquery.capped_query_runner import (
    CappedBigQueryRunner,
    MissingPurposeError,
    QueryCostExceeded,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BQ_CAPPED_QUERY_PATH = PROJECT_ROOT / "scripts" / "bq_capped_query.py"


def load_bq_capped_query_module():
    spec = importlib.util.spec_from_file_location("bq_capped_query", BQ_CAPPED_QUERY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {BQ_CAPPED_QUERY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeJob:
    def __init__(self, *, total_bytes_processed: int = 0, job_id: str = "fake-job") -> None:
        self.total_bytes_processed = total_bytes_processed
        self.job_id = job_id

    def result(self):
        return [{"ok": True}]


class FakeClient:
    def __init__(self, estimate_bytes: int, *, live_error: Exception | None = None) -> None:
        self.estimate_bytes = estimate_bytes
        self.live_error = live_error
        self.queries = []
        self.inserted_rows = []

    def query(self, sql, job_config=None, location=None):
        self.queries.append({"sql": sql, "job_config": job_config, "location": location})
        if getattr(job_config, "dry_run", False):
            return FakeJob(total_bytes_processed=self.estimate_bytes, job_id="dry-run-job")
        if self.live_error:
            raise self.live_error
        return FakeJob(total_bytes_processed=0, job_id="live-job")

    def insert_rows_json(self, table_id, rows):
        self.inserted_rows.append({"table_id": table_id, "rows": rows})
        return []


class FakeJobConfig:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def fake_config_factory(**kwargs):
    return FakeJobConfig(**kwargs)


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


class CappedQueryRunnerTest(unittest.TestCase):
    def make_runner(self, client: FakeClient) -> CappedBigQueryRunner:
        return CappedBigQueryRunner(
            client,
            test_config(),
            query_job_config_factory=fake_config_factory,
            now=lambda: datetime(2026, 6, 12, tzinfo=timezone.utc),
        )

    def test_blocks_query_above_normal_cap_without_executing(self) -> None:
        client = FakeClient(estimate_bytes=1_073_741_825)
        runner = self.make_runner(client)

        with self.assertRaises(QueryCostExceeded):
            runner.run_query("SELECT * FROM huge_table", purpose="qa: prove cap blocks")

        self.assertEqual(len(client.queries), 1)
        self.assertTrue(client.queries[0]["job_config"].dry_run)
        self.assertEqual(client.inserted_rows[0]["rows"][0]["status"], "blocked")

    def test_blocked_exception_carries_result(self) -> None:
        client = FakeClient(estimate_bytes=1_073_741_825)
        runner = self.make_runner(client)

        with self.assertRaises(QueryCostExceeded) as raised:
            runner.run_query("SELECT * FROM huge_table", purpose="qa: result on block")

        self.assertEqual(raised.exception.result.status, "blocked")
        self.assertIn(raised.exception.result.query_id, str(raised.exception))

    def test_executes_under_cap_with_maximum_bytes_billed(self) -> None:
        client = FakeClient(estimate_bytes=100)
        runner = self.make_runner(client)

        result, rows = runner.run_query("SELECT 1", purpose="qa: under cap")

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(rows, [{"ok": True}])
        self.assertEqual(len(client.queries), 2)
        live_config = client.queries[1]["job_config"]
        self.assertEqual(live_config.maximum_bytes_billed, 1_073_741_824)
        self.assertEqual(client.inserted_rows[0]["rows"][0]["status"], "succeeded")

    def test_admin_override_allows_query_below_10gb(self) -> None:
        client = FakeClient(estimate_bytes=2_000_000_000)
        runner = self.make_runner(client)

        result, _ = runner.run_query("SELECT * FROM wider_table", purpose="admin: broader QA", admin_cap_10gb=True)

        self.assertEqual(result.status, "succeeded")
        live_config = client.queries[1]["job_config"]
        self.assertEqual(live_config.maximum_bytes_billed, 10_737_418_240)

    def test_requires_purpose(self) -> None:
        client = FakeClient(estimate_bytes=100)
        runner = self.make_runner(client)

        with self.assertRaises(MissingPurposeError):
            runner.run_query("SELECT 1", purpose="")

        self.assertEqual(client.queries, [])

    def test_estimate_only_logs_cost_check(self) -> None:
        client = FakeClient(estimate_bytes=123)
        runner = self.make_runner(client)

        result = runner.estimate_query("SELECT 1", purpose="qa: estimate only")

        self.assertEqual(result.status, "estimated")
        self.assertEqual(len(client.queries), 1)
        self.assertEqual(client.inserted_rows[0]["rows"][0]["status"], "estimated")

    def test_failed_live_query_logs_failed_cost_check(self) -> None:
        client = FakeClient(estimate_bytes=100, live_error=RuntimeError("permission denied"))
        runner = self.make_runner(client)

        with self.assertRaises(RuntimeError):
            runner.run_query("SELECT 1", purpose="qa: failed live query")

        row = client.inserted_rows[0]["rows"][0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_class"], "RuntimeError")


class BqCappedQueryScriptTest(unittest.TestCase):
    def test_load_env_file_accepts_credential_paths_with_spaces(self) -> None:
        module = load_bq_capped_query_module()
        old_credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        old_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env_path = Path(tmp) / ".env"
                env_path.write_text(
                    "\n".join(
                        [
                            "GOOGLE_APPLICATION_CREDENTIALS=/tmp/SEO Automation/seo-agency-work.json",
                            "GOOGLE_CLOUD_PROJECT=seo-agency-work",
                            "IGNORED_SECRET=do-not-load",
                        ]
                    ),
                    encoding="utf-8",
                )

                module.load_env_file(env_path)

            self.assertEqual(
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
                str(Path("/tmp/SEO Automation/seo-agency-work.json").resolve()),
            )
            self.assertEqual(os.environ["GOOGLE_CLOUD_PROJECT"], "seo-agency-work")
            self.assertNotIn("IGNORED_SECRET", os.environ)
        finally:
            if old_credentials is None:
                os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            else:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = old_credentials
            if old_project is None:
                os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
            else:
                os.environ["GOOGLE_CLOUD_PROJECT"] = old_project
            os.environ.pop("IGNORED_SECRET", None)


if __name__ == "__main__":
    unittest.main()
