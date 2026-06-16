from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dataclasses import replace

from scripts.sync_langfuse_prompts import prompt_sync_plans, summarize_results, sync_prompt_plan


class ExistingPrompt:
    def __init__(self, prompt: str, version: int = 3) -> None:
        self.prompt = prompt
        self.version = version


class FakeLangfusePrompts:
    def __init__(self, existing_prompt: str | None = None) -> None:
        self.existing_prompt = existing_prompt
        self.created: list[dict] = []

    def get_prompt(self, name: str, *, label: str, type: str) -> ExistingPrompt:
        if self.existing_prompt is None:
            raise RuntimeError("not found")
        return ExistingPrompt(self.existing_prompt)

    def create_prompt(self, **kwargs):
        self.created.append(kwargs)
        return ExistingPrompt(kwargs["prompt"], version=4)


class SyncLangfusePromptsTest(unittest.TestCase):
    def test_prompt_sync_plans_labels_current_matching_version(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "prompts"
            agent_dir = root / "example_agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "v001.md").write_text("Prompt body", encoding="utf-8")
            (agent_dir / "current.md").write_text("Prompt body", encoding="utf-8")

            plans = prompt_sync_plans(root)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].name, "agency-os/example_agent")
        self.assertEqual(plans[0].labels, ("v001", "current"))
        self.assertTrue(plans[0].sha256)

    def test_sync_skips_unchanged_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "prompts"
            agent_dir = root / "example_agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "v001.md").write_text("Prompt body", encoding="utf-8")
            plan = prompt_sync_plans(root)[0]

        fake = FakeLangfusePrompts(existing_prompt="Prompt body")
        result = sync_prompt_plan(fake, plan, dry_run=False)

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(fake.created, [])

    def test_sync_creates_changed_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "prompts"
            agent_dir = root / "example_agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "v001.md").write_text("Prompt body", encoding="utf-8")
            plan = prompt_sync_plans(root)[0]

        fake = FakeLangfusePrompts(existing_prompt="Old prompt")
        result = sync_prompt_plan(fake, plan, dry_run=False)

        self.assertEqual(result["status"], "created")
        self.assertEqual(fake.created[0]["name"], "agency-os/example_agent")

    def test_extra_labels_are_preserved_when_creating_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "prompts"
            agent_dir = root / "example_agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "v001.md").write_text("Prompt body", encoding="utf-8")
            plan = prompt_sync_plans(root)[0]
            plan = replace(plan, labels=(*plan.labels, "staging"))

        fake = FakeLangfusePrompts(existing_prompt=None)
        sync_prompt_plan(fake, plan, dry_run=False)

        self.assertIn("staging", fake.created[0]["labels"])

    def test_summary_counts_statuses(self) -> None:
        summary = summarize_results([
            {"status": "created"},
            {"status": "created"},
            {"status": "unchanged"},
        ])

        self.assertEqual(summary, {"created": 2, "unchanged": 1})


if __name__ == "__main__":
    unittest.main()
