from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.validate_operating_layer import (
    ALLOWED_BIGQUERY_WRITE_PURPOSES,
    ValidationError,
    parse_simple_yaml,
    validate,
)


def write_valid_fixture(root: Path) -> None:
    (root / "config").mkdir()
    (root / "agents").mkdir()
    (root / "prompts" / "qa_guardrail").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)

    (root / "config" / "permissions.yaml").write_text(
        "\n".join(
            [
                "dry_run_default: true",
                "allow_email_send: false",
                "allow_email_draft_create: false",
                "allow_monday_write: false",
                "allow_drive_write: false",
                "allow_drive_share: false",
                "allow_external_publish: false",
                "allow_bigquery_logging: true",
                "require_approval_for_external_actions: true",
                "allowed_bigquery_write_purposes:",
                *[f"  - {purpose}" for purpose in sorted(ALLOWED_BIGQUERY_WRITE_PURPOSES)],
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "prompts" / "qa_guardrail" / "current.md").write_text(
        "# QA Guardrail Prompt current\n\nCurrent approved version: `v001.md`.\n",
        encoding="utf-8",
    )
    (root / "prompts" / "qa_guardrail" / "v001.md").write_text(
        "# QA Guardrail Prompt v001\n\nRequire evidence. Do not approve external writes.\n",
        encoding="utf-8",
    )
    (root / "agents" / "qa_guardrail.md").write_text(
        "# QA Guardrail\n\n"
        "## Purpose\n\nValidate outputs.\n\n"
        "## Outputs\n\nFindings and actions.\n\n"
        "## Safety\n\nDo not approve unsupported claims. Require evidence.\n",
        encoding="utf-8",
    )


class OperatingLayerValidationTest(unittest.TestCase):
    def test_valid_fixture_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_valid_fixture(root)

            self.assertEqual(validate(root), [])

    def test_permission_write_flip_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_valid_fixture(root)
            permissions = root / "config" / "permissions.yaml"
            permissions.write_text(
                permissions.read_text(encoding="utf-8").replace("allow_monday_write: false", "allow_monday_write: true"),
                encoding="utf-8",
            )

            errors = validate(root)

        self.assertIn("config/permissions.yaml must keep allow_monday_write: false", errors)

    def test_prompt_current_must_point_to_existing_version(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_valid_fixture(root)
            (root / "prompts" / "qa_guardrail" / "current.md").write_text(
                "Current approved version: `v999.md`.\n",
                encoding="utf-8",
            )

            errors = validate(root)

        self.assertIn("prompts/qa_guardrail/current.md points to missing prompts/qa_guardrail/v999.md", errors)

    def test_simple_yaml_rejects_unsupported_lines(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "permissions.yaml"
            path.write_text("dry_run_default true\n", encoding="utf-8")

            with self.assertRaises(ValidationError):
                parse_simple_yaml(path)


if __name__ == "__main__":
    unittest.main()

