from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agency_bigquery.langfuse_tracing import (
    LANGFUSE_CAPTURE_PAYLOADS_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
    emit_agent_trace,
    langfuse_env_enabled,
)


def run_row() -> dict:
    return {
        "run_id": "run-1",
        "automation_id": None,
        "agent_id": "content_research_agent",
        "agent_name": "Content Research Agent",
        "started_at": "2026-06-16T00:00:00+00:00",
        "completed_at": "2026-06-16T00:01:00+00:00",
        "status": "succeeded",
        "mode": "local_context",
        "prompt_version": "content_research_agent/v001",
        "dry_run": True,
    }


class FakeTrace:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class FakeLangfuse:
    def __init__(self) -> None:
        self.trace_calls: list[dict] = []
        self.trace_obj = FakeTrace()
        self.flushed = False

    def trace(self, **kwargs) -> FakeTrace:
        self.trace_calls.append(kwargs)
        return self.trace_obj

    def flush(self) -> None:
        self.flushed = True


class LangfuseTracingTest(unittest.TestCase):
    def test_env_disabled_without_keys(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(langfuse_env_enabled())
            result = emit_agent_trace(run_row=run_row())
        self.assertEqual(result.status, "skipped")
        self.assertFalse(result.enabled)

    def test_emit_sends_metadata_only_by_default(self) -> None:
        fake = FakeLangfuse()
        env = {
            LANGFUSE_PUBLIC_KEY_ENV: "pk-test",
            LANGFUSE_SECRET_KEY_ENV: "sk-test",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("agency_bigquery.langfuse_tracing._get_langfuse_client", return_value=fake):
                result = emit_agent_trace(
                    run_row=run_row(),
                    findings=[{"summary": "private-ish finding"}],
                    actions=[{"recommended_action": "private-ish action"}],
                    context_pack={"rows": [{"client": "example"}]},
                )

        self.assertEqual(result.status, "emitted")
        self.assertTrue(fake.flushed)
        metadata = fake.trace_calls[0]["metadata"]
        self.assertEqual(metadata["counts"]["findings"], 1)
        self.assertIn("findings_sha256", metadata["hashes"])
        self.assertNotIn("payloads", metadata)

    def test_capture_payloads_requires_explicit_flag(self) -> None:
        fake = FakeLangfuse()
        env = {
            LANGFUSE_PUBLIC_KEY_ENV: "pk-test",
            LANGFUSE_SECRET_KEY_ENV: "sk-test",
            LANGFUSE_CAPTURE_PAYLOADS_ENV: "true",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("agency_bigquery.langfuse_tracing._get_langfuse_client", return_value=fake):
                emit_agent_trace(run_row=run_row(), findings=[{"summary": "captured"}])

        self.assertEqual(fake.trace_calls[0]["metadata"]["payloads"]["findings"][0]["summary"], "captured")


if __name__ == "__main__":
    unittest.main()
