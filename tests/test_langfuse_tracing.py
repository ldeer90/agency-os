from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agency_bigquery.langfuse_tracing import (
    LANGFUSE_BASE_URL_ENV,
    LANGFUSE_CAPTURE_PAYLOADS_ENV,
    LANGFUSE_HOST_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
    _normalize_langfuse_host_env,
    emit_agent_trace,
    langfuse_env_enabled,
    prompt_metadata_for_agent,
)


def run_row() -> dict:
    return {
        "run_id": "run-1",
        "automation_id": "automation-1",
        "agent_id": "content_research_agent",
        "agent_name": "Content Research Agent",
        "started_at": "2026-06-16T00:00:00+00:00",
        "completed_at": "2026-06-16T00:01:00+00:00",
        "status": "succeeded",
        "mode": "local_context",
        "prompt_version": "content_research_agent/v001",
        "context_id": "context-1",
        "output_path": "/tmp/run-1.json",
        "dry_run": True,
    }


class FakeTrace:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class FakeLangfuse:
    def __init__(self) -> None:
        self.observation_calls: list[dict] = []
        self.trace_obj = FakeTrace()
        self.flushed = False

    def create_trace_id(self, *, seed: str | None = None) -> str:
        return f"trace-{seed or 'generated'}"

    def get_trace_url(self, *, trace_id: str | None = None) -> str:
        return f"https://langfuse.test/trace/{trace_id}"

    def start_observation(self, **kwargs) -> FakeTrace:
        self.observation_calls.append(kwargs)
        return self.trace_obj

    def set_current_trace_io(self, **kwargs) -> None:
        self.trace_io = kwargs

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
                    llm_usage=[{"model": "gpt-test", "input_tokens": 12, "output_tokens": 8, "cost_estimate_aud": 0.01}],
                    bigquery_project="seo-agency-work",
                    bigquery_dataset="agency_control",
                )

        self.assertEqual(result.status, "emitted")
        self.assertEqual(result.trace_id, "trace-run-1")
        self.assertEqual(result.trace_url, "https://langfuse.test/trace/trace-run-1")
        self.assertEqual(result.session_id, "automation-1")
        self.assertTrue(result.metadata_sha256)
        self.assertTrue(fake.flushed)
        metadata = fake.observation_calls[0]["metadata"]
        self.assertEqual(metadata["run_id"], "run-1")
        self.assertEqual(metadata["agent_id"], "content_research_agent")
        self.assertEqual(metadata["context_id"], "context-1")
        self.assertEqual(metadata["bigquery_project"], "seo-agency-work")
        self.assertEqual(metadata["bigquery_dataset"], "agency_control")
        self.assertEqual(metadata["counts"]["findings"], 1)
        self.assertIn("findings_sha256", metadata["hashes"])
        self.assertIn("prompt_sha256", metadata["hashes"])
        self.assertEqual(metadata["prompt"]["agent_id"], "content_research_agent")
        self.assertTrue(metadata["prompt"]["prompts"])
        self.assertNotIn("payloads", metadata)
        generation = fake.observation_calls[1]
        self.assertEqual(generation["as_type"], "generation")
        self.assertEqual(generation["model"], "gpt-test")
        self.assertEqual(generation["usage_details"], {"input": 12, "output": 8, "total": 20})

    def test_prompt_metadata_hashes_versioned_and_current_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "prompts"
            prompt_dir = root / "example_agent"
            prompt_dir.mkdir(parents=True)
            (prompt_dir / "v001.md").write_text("Versioned prompt", encoding="utf-8")
            (prompt_dir / "current.md").write_text("Current prompt", encoding="utf-8")

            metadata = prompt_metadata_for_agent(
                "example_agent",
                "example_agent/v001",
                prompts_root=root,
            )

        self.assertEqual(metadata["agent_id"], "example_agent")
        self.assertEqual(len(metadata["prompts"]), 2)
        self.assertTrue(all("sha256" in item for item in metadata["prompts"]))
        self.assertTrue(all("Versioned prompt" not in str(item) for item in metadata["prompts"]))

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

        self.assertEqual(fake.observation_calls[0]["metadata"]["payloads"]["findings"][0]["summary"], "captured")

    def test_base_url_is_mapped_to_host_for_sdk_compatibility(self) -> None:
        env = {
            LANGFUSE_PUBLIC_KEY_ENV: "pk-test",
            LANGFUSE_SECRET_KEY_ENV: "sk-test",
            LANGFUSE_BASE_URL_ENV: "https://example.langfuse.test",
        }
        with patch.dict(os.environ, env, clear=True):
            _normalize_langfuse_host_env()

            self.assertEqual(os.environ[LANGFUSE_HOST_ENV], "https://example.langfuse.test")


if __name__ == "__main__":
    unittest.main()
