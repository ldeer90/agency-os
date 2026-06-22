#!/usr/bin/env python3
"""Audit AgencyOS Markdown signage for stale or incomplete agent instructions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "system_admin"
DEFAULT_SKILL_ROOT = Path("/Users/laurencedeer/.codex/skills")

CORE_DOCS = (
    "AGENTS.md",
    "HANDOVER.md",
    "docs/QUERY_COOKBOOK.md",
    "docs/AGENT_POOL_REGISTRY.md",
    "docs/AGENCY_OPS_MEMORY_V1.md",
)

REQUIRED_AGENT_HEADINGS = ("identity", "purpose", "inputs", "outputs", "safety")
ACTIVE_REGISTRY_STATUSES = {"lead", "active-runner", "docs-only-active", "embedded"}
STALE_SCHEMA_TERMS = ("source_name", "created_at", "check_time")
NEGATION_HINTS = (
    "not ",
    "not `",
    "do not",
    "don't",
    "rather than",
    "instead of",
    "avoid",
    "stale",
    "schema note",
    "current schema",
)
PRIVACY_HINTS = (
    "credential",
    "credentials",
    "secret",
    "secrets",
    "raw drive",
    "raw docs",
    "raw email",
    "raw private",
    "do not read",
    "do not print",
    "do not store",
    "never print",
    "never read",
)


@dataclass(frozen=True)
class SignageIssue:
    severity: str
    check: str
    path: str
    message: str
    line: int | None = None


def rel_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def markdown_headings(text: str) -> set[str]:
    headings: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.add(match.group(1).strip().lower())
    return headings


def is_retired_or_alias(text: str) -> bool:
    lower = text.lower()
    return "retired" in lower or "compatibility alias" in lower or "legacy alias" in lower


def has_privacy_signage(text: str) -> bool:
    lower = text.lower()
    return any(hint in lower for hint in PRIVACY_HINTS)


def line_is_negated(line: str) -> bool:
    lower = line.lower()
    return any(hint in lower for hint in NEGATION_HINTS)


def markdown_files(root: Path, skill_root: Path = DEFAULT_SKILL_ROOT) -> list[Path]:
    paths: list[Path] = []
    for rel in CORE_DOCS:
        path = root / rel
        if path.exists():
            paths.append(path)
    for directory in (root / "agents", root / "prompts"):
        if directory.exists():
            paths.extend(sorted(directory.glob("**/*.md")))
    if skill_root.exists():
        paths.extend(sorted(skill_root.glob("bigquery-*/**/*.md")))
    return sorted(dict.fromkeys(paths))


def active_registry_agents(root: Path) -> set[str]:
    registry = root / "docs" / "AGENT_POOL_REGISTRY.md"
    if not registry.exists():
        return set()
    agents: set[str] = set()
    for line in read_text(registry).splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() in {"agent", "---"}:
            continue
        agent_id = cells[0].strip("` ")
        status = cells[1].strip("` ").lower()
        if agent_id and status in ACTIVE_REGISTRY_STATUSES:
            agents.add(agent_id)
    return agents


def audit_stale_schema_terms(paths: list[Path], root: Path) -> list[SignageIssue]:
    issues: list[SignageIssue] = []
    for path in paths:
        for line_no, line in enumerate(read_text(path).splitlines(), start=1):
            lower = line.lower()
            if not any(term in lower for term in STALE_SCHEMA_TERMS):
                continue
            if not ("ingestion_runs" in lower or "cost_checks" in lower):
                continue
            if line_is_negated(line):
                continue
            issues.append(
                SignageIssue(
                    severity="warning",
                    check="stale_schema_terms",
                    path=rel_path(path, root),
                    line=line_no,
                    message="Possible active guidance uses stale control-table schema term.",
                )
            )
    return issues


def audit_current_schema_signage(paths: list[Path], root: Path) -> list[SignageIssue]:
    combined = "\n".join(read_text(path).lower() for path in paths if path.exists())
    checks = (
        ("ingestion_runs", "source_path", "Missing current signage that ingestion_runs uses source_path."),
        ("cost_checks", "logged_at", "Missing current signage that cost_checks uses logged_at."),
    )
    issues: list[SignageIssue] = []
    for table, field, message in checks:
        if table not in combined or field not in combined:
            issues.append(
                SignageIssue(
                    severity="error",
                    check="current_schema_signage",
                    path=str(root),
                    line=None,
                    message=message,
                )
            )
    return issues


def audit_agent_specs(root: Path) -> list[SignageIssue]:
    issues: list[SignageIssue] = []
    agents_dir = root / "agents"
    if not agents_dir.exists():
        return [
            SignageIssue(
                severity="error",
                check="agent_identity_coverage",
                path="agents",
                line=None,
                message="Missing agents/ directory.",
            )
        ]
    for path in sorted(agents_dir.glob("*.md")):
        text = read_text(path)
        if is_retired_or_alias(text):
            continue
        headings = markdown_headings(text)
        for heading in REQUIRED_AGENT_HEADINGS:
            if heading not in headings:
                issues.append(
                    SignageIssue(
                        severity="error",
                        check="agent_identity_coverage",
                        path=rel_path(path, root),
                        line=None,
                        message=f"Agent spec missing ## {heading.title()} section.",
                    )
                )
        if not has_privacy_signage(text):
            issues.append(
                SignageIssue(
                    severity="warning",
                    check="privacy_safety_signage",
                    path=rel_path(path, root),
                    line=None,
                    message="Agent spec should mention credential/raw-private-content safety boundaries.",
                )
            )
    return issues


def audit_registry_coverage(root: Path) -> list[SignageIssue]:
    issues: list[SignageIssue] = []
    for agent_id in sorted(active_registry_agents(root)):
        spec_path = root / "agents" / f"{agent_id}.md"
        prompt_path = root / "prompts" / agent_id / "current.md"
        if not spec_path.exists():
            issues.append(
                SignageIssue(
                    severity="error",
                    check="prompt_spec_coverage",
                    path=rel_path(spec_path, root),
                    line=None,
                    message=f"Active registry agent {agent_id} has no matching agent spec.",
                )
            )
        if not prompt_path.exists():
            issues.append(
                SignageIssue(
                    severity="error",
                    check="prompt_spec_coverage",
                    path=rel_path(prompt_path, root),
                    line=None,
                    message=f"Active registry agent {agent_id} has no prompts/{agent_id}/current.md.",
                )
            )
    return issues


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit_prompt_version_drift(root: Path) -> list[SignageIssue]:
    issues: list[SignageIssue] = []
    prompts_root = root / "prompts"
    if not prompts_root.exists():
        return []
    for current_path in sorted(prompts_root.glob("*/current.md")):
        current_text = read_text(current_path)
        current_hash = sha256_text(current_text)
        version_paths = sorted(path for path in current_path.parent.glob("v*.md") if path.name != "current.md")
        if not version_paths:
            issues.append(
                SignageIssue(
                    severity="warning",
                    check="prompt_version_drift",
                    path=rel_path(current_path, root),
                    line=None,
                    message="Prompt current.md has no versioned v*.md sibling.",
                )
            )
            continue
        approved_match = re.search(r"Current approved version:\s*`?([A-Za-z0-9_.-]+\.md)`?", current_text)
        if approved_match and (current_path.parent / approved_match.group(1)).exists():
            continue
        if current_hash not in {sha256_text(read_text(path)) for path in version_paths}:
            issues.append(
                SignageIssue(
                    severity="warning",
                    check="prompt_version_drift",
                    path=rel_path(current_path, root),
                    line=None,
                    message="Prompt current.md does not exactly match any versioned v*.md sibling.",
                )
            )
    return issues


def audit_handover_freshness(root: Path) -> list[SignageIssue]:
    path = root / "HANDOVER.md"
    if not path.exists():
        return [
            SignageIssue(
                severity="error",
                check="handover_freshness",
                path="HANDOVER.md",
                line=None,
                message="Missing HANDOVER.md.",
            )
        ]
    text = read_text(path)
    lower = text.lower()
    issues: list[SignageIssue] = []
    if "source_path" not in lower or "ingestion_runs" not in lower:
        issues.append(
            SignageIssue(
                severity="error",
                check="handover_freshness",
                path="HANDOVER.md",
                line=None,
                message="HANDOVER.md should include ingestion_runs verification with source_path.",
            )
        )
    if "logged_at" not in lower or "cost_checks" not in lower:
        issues.append(
            SignageIssue(
                severity="warning",
                check="handover_freshness",
                path="HANDOVER.md",
                line=None,
                message="HANDOVER.md should include cost_checks verification with logged_at.",
            )
        )
    issues.extend(audit_stale_schema_terms([path], root))
    return issues


def audit_core_privacy_signage(root: Path) -> list[SignageIssue]:
    issues: list[SignageIssue] = []
    for rel in CORE_DOCS:
        path = root / rel
        if not path.exists():
            continue
        if not has_privacy_signage(read_text(path)):
            issues.append(
                SignageIssue(
                    severity="warning",
                    check="privacy_safety_signage",
                    path=rel,
                    line=None,
                    message="Core signage should mention credential/raw-private-content safety boundaries.",
                )
            )
    return issues


def audit(root: Path = PROJECT_ROOT, *, skill_root: Path = DEFAULT_SKILL_ROOT) -> dict[str, object]:
    paths = markdown_files(root, skill_root=skill_root)
    issues: list[SignageIssue] = []
    issues.extend(audit_stale_schema_terms(paths, root))
    issues.extend(audit_current_schema_signage(paths, root))
    issues.extend(audit_agent_specs(root))
    issues.extend(audit_registry_coverage(root))
    issues.extend(audit_prompt_version_drift(root))
    issues.extend(audit_handover_freshness(root))
    issues.extend(audit_core_privacy_signage(root))
    counts = Counter(issue.severity for issue in issues)
    return {
        "status": "completed",
        "generated_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "scanned": {
            "markdown_files": len(paths),
            "active_registry_agents": len(active_registry_agents(root)),
        },
        "counts": {
            "error": counts.get("error", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
            "total": len(issues),
        },
        "issues": [asdict(issue) for issue in issues],
    }


def render_summary(report: dict[str, object], *, max_issues: int = 20) -> str:
    counts = report["counts"]
    scanned = report["scanned"]
    issues = report["issues"]
    assert isinstance(counts, dict)
    assert isinstance(scanned, dict)
    assert isinstance(issues, list)
    lines = [
        "Agent Signage Markdown Audit",
        f"Root: {report['root']}",
        f"Scanned: {scanned['markdown_files']} markdown files, {scanned['active_registry_agents']} active registry agents",
        f"Issues: {counts['error']} errors, {counts['warning']} warnings, {counts['total']} total",
    ]
    if issues:
        lines.append("")
        lines.append("Top issues:")
        for issue in issues[:max_issues]:
            location = issue["path"]
            if issue.get("line"):
                location = f"{location}:{issue['line']}"
            lines.append(f"- [{issue['severity']}] {issue['check']} {location} - {issue['message']}")
        remaining = len(issues) - max_issues
        if remaining > 0:
            lines.append(f"- ... {remaining} more issues")
    return "\n".join(lines)


def write_report(report: dict[str, object], report_dir: Path = DEFAULT_REPORT_DIR) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / f"agent-signage-audit-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="Project root to audit.")
    parser.add_argument("--skill-root", default=str(DEFAULT_SKILL_ROOT), help="Skill root containing bigquery-* skill references.")
    parser.add_argument("--write-report", action="store_true", help="Write JSON report under reports/system_admin/.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for --write-report JSON output.")
    parser.add_argument("--max-issues", type=int, default=20, help="Maximum issues to show in console summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(Path(args.root), skill_root=Path(args.skill_root))
    print(render_summary(report, max_issues=args.max_issues))
    if args.write_report:
        path = write_report(report, Path(args.report_dir))
        print(f"JSON report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
