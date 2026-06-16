from __future__ import annotations

import subprocess
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from dashboard.api import sync_ops


class DashboardSyncOpsTests(unittest.TestCase):
    def test_build_command_rejects_unknown_sync(self) -> None:
        with self.assertRaises(sync_ops.SyncValidationError):
            sync_ops.build_command("bad_sync", "dry_run")

    def test_build_command_rejects_unsupported_client_scope(self) -> None:
        with self.assertRaises(sync_ops.SyncValidationError):
            sync_ops.build_command("seo_catalog_sync", "dry_run", {"client_slug": "shop-rongrong"})

    def test_build_command_builds_live_client_memory_command(self) -> None:
        command, cwd = sync_ops.build_command(
            "seo_client_memory_sync",
            "live",
            {"client_slug": "shop-rongrong", "ensure_tables": True},
        )

        self.assertEqual(cwd, sync_ops.PROJECT_ROOT)
        self.assertIn("scripts/sync_seo_client_memory.py", command)
        self.assertIn("--write-bigquery", command)
        self.assertIn("--ensure-tables", command)
        self.assertEqual(command[-2:], ["--client-slug", "shop-rongrong"])

    def test_master_sync_builds_allowlisted_steps(self) -> None:
        steps = sync_ops.build_master_steps("live", {"ensure_tables": True})
        step_ids = [step["sync_id"] for step in steps]

        self.assertEqual(
            step_ids,
            ["monday_state_refresh", "agency_ops_ingest", "seo_catalog_sync", "seo_client_memory_sync", "finance_sync", "agent_work_update"],
        )
        self.assertTrue(all(step["command_display"] for step in steps))
        self.assertIn("--write-bigquery", steps[-1]["command"])

    def test_master_dry_run_skips_monday_live_snapshot(self) -> None:
        steps = sync_ops.build_master_steps("dry_run")

        self.assertNotIn("monday_state_refresh", [step["sync_id"] for step in steps])
        self.assertTrue(all(step["mode"] == "dry_run" for step in steps))

    def test_live_queue_requires_confirmation(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(sync_ops, "SYNC_STATE_ROOT", Path(temp_dir)), patch.object(
            sync_ops, "COMMANDS_PATH", Path(temp_dir) / "commands" / "index.jsonl"
        ), patch.object(sync_ops, "RUNS_ROOT", Path(temp_dir) / "runs"):
            with self.assertRaises(sync_ops.SyncValidationError):
                sync_ops.queue_command("seo_catalog_sync", "live", confirmation="wrong", auto_start=False)

    def test_queue_and_execute_success_sanitizes_run_output(self) -> None:
        def fake_runner(*_args, **_kwargs):
            return subprocess.CompletedProcess(args=["ok"], returncode=0, stdout="token=abc123\nall good", stderr="")

        with TemporaryDirectory() as temp_dir, patch.object(sync_ops, "SYNC_STATE_ROOT", Path(temp_dir)), patch.object(
            sync_ops, "COMMANDS_PATH", Path(temp_dir) / "commands" / "index.jsonl"
        ), patch.object(sync_ops, "RUNS_ROOT", Path(temp_dir) / "runs"):
            command = sync_ops.queue_command("seo_catalog_sync", "dry_run", auto_start=False)
            updated = sync_ops.execute_command(command["command_id"], runner=fake_runner)
            state = sync_ops.command_state(command["command_id"])

        self.assertEqual(updated["status"], "succeeded")
        self.assertEqual(state["run"]["status"], "succeeded")
        self.assertIn("[REDACTED]", state["run"]["stdout"])
        self.assertNotIn("abc123", state["run"]["stdout"])

    def test_execute_failure_records_failed_state(self) -> None:
        def fake_runner(*_args, **_kwargs):
            return subprocess.CompletedProcess(args=["bad"], returncode=2, stdout="", stderr="failed")

        with TemporaryDirectory() as temp_dir, patch.object(sync_ops, "SYNC_STATE_ROOT", Path(temp_dir)), patch.object(
            sync_ops, "COMMANDS_PATH", Path(temp_dir) / "commands" / "index.jsonl"
        ), patch.object(sync_ops, "RUNS_ROOT", Path(temp_dir) / "runs"):
            command = sync_ops.queue_command("seo_catalog_sync", "dry_run", auto_start=False)
            updated = sync_ops.execute_command(command["command_id"], runner=fake_runner)
            state = sync_ops.command_state(command["command_id"])

        self.assertEqual(updated["status"], "failed")
        self.assertEqual(state["run"]["exit_code"], 2)
        self.assertEqual(state["run"]["stderr"], "failed")

    def test_execute_master_records_step_results_and_stops_on_failure(self) -> None:
        calls = []

        def fake_runner(command, *_args, **_kwargs):
            calls.append(command)
            returncode = 2 if len(calls) == 2 else 0
            return subprocess.CompletedProcess(args=command, returncode=returncode, stdout="ok", stderr="bad" if returncode else "")

        with TemporaryDirectory() as temp_dir, patch.object(sync_ops, "SYNC_STATE_ROOT", Path(temp_dir)), patch.object(
            sync_ops, "COMMANDS_PATH", Path(temp_dir) / "commands" / "index.jsonl"
        ), patch.object(sync_ops, "RUNS_ROOT", Path(temp_dir) / "runs"):
            command = sync_ops.queue_command("master_sync", "dry_run", auto_start=False)
            updated = sync_ops.execute_command(command["command_id"], runner=fake_runner)
            state = sync_ops.command_state(command["command_id"])

        self.assertEqual(updated["status"], "failed")
        self.assertEqual(len(state["run"]["step_results"]), 2)


if __name__ == "__main__":
    unittest.main()
