#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_FALSE_PERMISSIONS = {
    "allow_email_send",
    "allow_email_draft_create",
    "allow_monday_write",
    "allow_drive_write",
    "allow_drive_share",
    "allow_external_publish",
}
REQUIRED_TRUE_PERMISSIONS = {
    "dry_run_default",
    "allow_bigquery_logging",
    "require_approval_for_external_actions",
}
ALLOWED_BIGQUERY_WRITE_PURPOSES = {
    "agent_run_log",
    "agent_findings",
    "agent_actions",
    "agent_approvals",
    "context_packs",
    "llm_usage_log",
}
SECRET_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
        r"access[_-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._~+/\-]{20,}",
        r"refresh[_-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._~+/\-]{20,}",
        r"client[_-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
        r"private_key\s*[:=]\s*['\"]?-{5}BEGIN",
        r"bearer\s+[A-Za-z0-9._~+/\-]{20,}",
    )
]


class ValidationError(ValueError):
    pass


def parse_simple_yaml(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    scalars: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        stripped = line_without_comment.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            if not current_list_key:
                raise ValidationError(f"{path}: list item without a key: {raw_line.strip()}")
            lists.setdefault(current_list_key, []).append(stripped[2:].strip())
            continue
        current_list_key = None
        if ":" not in stripped:
            raise ValidationError(f"{path}: unsupported line: {raw_line.strip()}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            scalars[key] = value
        else:
            lists.setdefault(key, [])
            current_list_key = key
    return scalars, lists


def parse_bool(value: str, *, key: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on", "1"}:
        return True
    if lowered in {"false", "no", "off", "0"}:
        return False
    raise ValidationError(f"{key} must be a boolean, got {value!r}")


def validate_permissions(root: Path) -> list[str]:
    errors: list[str] = []
    path = root / "config" / "permissions.yaml"
    if not path.exists():
        return [f"missing {path.relative_to(root)}"]
    scalars, lists = parse_simple_yaml(path)

    for key in sorted(REQUIRED_TRUE_PERMISSIONS):
        if key not in scalars:
            errors.append(f"config/permissions.yaml missing {key}")
            continue
        if not parse_bool(scalars[key], key=key):
            errors.append(f"config/permissions.yaml must keep {key}: true")

    for key in sorted(REQUIRED_FALSE_PERMISSIONS):
        if key not in scalars:
            errors.append(f"config/permissions.yaml missing {key}")
            continue
        if parse_bool(scalars[key], key=key):
            errors.append(f"config/permissions.yaml must keep {key}: false")

    purposes = set(lists.get("allowed_bigquery_write_purposes", []))
    if purposes != ALLOWED_BIGQUERY_WRITE_PURPOSES:
        errors.append(
            "config/permissions.yaml allowed_bigquery_write_purposes must be exactly "
            f"{sorted(ALLOWED_BIGQUERY_WRITE_PURPOSES)}"
        )
    return errors


def validate_prompt_versions(root: Path) -> list[str]:
    errors: list[str] = []
    prompts_root = root / "prompts"
    if not prompts_root.exists():
        return ["missing prompts/"]
    current_files = sorted(prompts_root.glob("*/current.md"))
    if not current_files:
        return ["no prompt current.md files found"]

    for current in current_files:
        text = current.read_text(encoding="utf-8")
        match = re.search(r"Current approved version:\s*`?([A-Za-z0-9_.-]+\.md)`?", text)
        rel_current = current.relative_to(root)
        if not match:
            errors.append(f"{rel_current} missing Current approved version reference")
            continue
        version_path = current.with_name(match.group(1))
        if not version_path.exists():
            errors.append(f"{rel_current} points to missing {version_path.relative_to(root)}")
            continue
        version_text = version_path.read_text(encoding="utf-8").lower()
        if "evidence" not in version_text:
            errors.append(f"{version_path.relative_to(root)} must require evidence")
        if "do not" not in version_text and "never" not in version_text:
            errors.append(f"{version_path.relative_to(root)} must include explicit safety prohibitions")
    return errors


def validate_agent_specs(root: Path) -> list[str]:
    errors: list[str] = []
    prompt_ids = {path.parent.name for path in (root / "prompts").glob("*/current.md")}
    for agent_id in sorted(prompt_ids):
        spec_path = root / "agents" / f"{agent_id}.md"
        if not spec_path.exists():
            errors.append(f"missing agents/{agent_id}.md for active prompt")
            continue
        text = spec_path.read_text(encoding="utf-8")
        lower_text = text.lower()
        for heading in ("## purpose", "## outputs", "## safety"):
            if heading not in lower_text:
                errors.append(f"{spec_path.relative_to(root)} missing {heading.title()}")
        if "evidence" not in lower_text:
            errors.append(f"{spec_path.relative_to(root)} must mention evidence requirements")
        if "do not" not in lower_text and "never" not in lower_text:
            errors.append(f"{spec_path.relative_to(root)} must include explicit safety prohibitions")
    return errors


def validate_no_secret_literals(root: Path) -> list[str]:
    errors: list[str] = []
    checked_roots = [root / "agents", root / "config", root / "docs", root / "prompts", root / ".github" / "workflows"]
    for checked_root in checked_roots:
        if not checked_root.exists():
            continue
        for path in sorted(p for p in checked_root.rglob("*") if p.is_file()):
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(f"{path.relative_to(root)} may contain a secret literal matching {pattern.pattern}")
                    break
    return errors


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_permissions(root))
    errors.extend(validate_prompt_versions(root))
    errors.extend(validate_agent_specs(root))
    errors.extend(validate_no_secret_literals(root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate offline SEO Agency OS operating-layer safety contracts.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate(root)
    if errors:
        print("Operating-layer validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Operating-layer validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
