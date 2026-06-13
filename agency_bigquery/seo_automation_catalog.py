from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any

from .agency_ops_ingestion import slugify
from .agent_ops import normalize_action, normalize_finding, stable_hash, utc_now_iso, validate_agent_output


PROJECTS_ROOT = Path("/Users/laurencedeer/Projects/Codex")
DEFAULT_SEO_AUTOMATION_ROOT = PROJECTS_ROOT / "SEO Automation"
ROUTING_MANIFEST = Path("docs/agent/routing-manifest.json")
WORKFLOW_INDEX = Path("docs/agent/workflows/_index.md")
CLIENTS_DIR = Path("docs/agent/clients")

MAX_SUMMARY_CHARS = 360
MAX_LIST_ITEMS = 12
MAX_TIMELINE_ROWS = 5
SCREAMING_FROG_MCP_DEPENDENCY = "Screaming Frog MCP for loaded crawl inspection, progress checks, crawl export, and approved bulk exports"
FORBIDDEN_KEY_RE = re.compile(
    r"(raw|body|comment|update|email|conversation|credential|secret|token|password|private|cookie)",
    re.IGNORECASE,
)
SECRET_TEXT_RE = re.compile(
    r"(?i)(api[_-]?key\s*[=:]|access[_-]?token\s*[=:]|refresh[_-]?token\s*[=:]|"
    r"private_key\s*[=:]|client_secret\s*[=:]|password\s*[=:]|Bearer\s+[A-Za-z0-9._~+/-]{20,}|"
    r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----)"
)


class SeoAutomationCatalogError(ValueError):
    """Raised when SEO Automation metadata cannot be safely summarized."""


@dataclass(frozen=True)
class SeoAutomationRoots:
    root: Path = DEFAULT_SEO_AUTOMATION_ROOT

    @property
    def manifest_path(self) -> Path:
        return self.root / ROUTING_MANIFEST

    @property
    def workflow_index_path(self) -> Path:
        return self.root / WORKFLOW_INDEX

    @property
    def clients_dir(self) -> Path:
        return self.root / CLIENTS_DIR


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _clean_text(value: Any, *, max_chars: int = MAX_SUMMARY_CHARS) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("\n", " ").split())
    if not text:
        return None
    if SECRET_TEXT_RE.search(text):
        raise SeoAutomationCatalogError("secret-like text was found while summarizing SEO Automation metadata")
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "..."
    return text


def _safe_list(values: Any, *, max_items: int = MAX_LIST_ITEMS, max_chars: int = 180) -> list[str]:
    if not isinstance(values, list):
        return []
    safe: list[str] = []
    for value in values[:max_items]:
        cleaned = _clean_text(value, max_chars=max_chars)
        if cleaned:
            safe.append(cleaned)
    return safe


def _workflow_dependencies(values: Any, *, workflow_doc: str, kind: str) -> list[str]:
    dependencies = _safe_list(values)
    text = f"{workflow_doc} {' '.join(dependencies)}".lower()
    if kind == "mcp" and ("screaming frog" in text or "full-site-audit" in text):
        if not any("screaming frog mcp" in dependency.lower() for dependency in dependencies):
            dependencies.append(SCREAMING_FROG_MCP_DEPENDENCY)
    return dependencies[:MAX_LIST_ITEMS]


def _safe_dict(value: Any, *, max_items: int = MAX_LIST_ITEMS) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, child in list(value.items())[:max_items]:
        key_text = str(key)
        if FORBIDDEN_KEY_RE.search(key_text):
            continue
        if isinstance(child, dict):
            safe[key_text] = _safe_dict(child, max_items=max_items)
        elif isinstance(child, list):
            safe[key_text] = _safe_list(child, max_items=max_items)
        else:
            safe[key_text] = _clean_text(child, max_chars=180)
    return {key: val for key, val in safe.items() if val not in (None, "", [], {})}


def load_routing_manifest(root: Path = DEFAULT_SEO_AUTOMATION_ROOT) -> dict[str, Any]:
    path = SeoAutomationRoots(root).manifest_path
    if not path.exists():
        raise SeoAutomationCatalogError(f"SEO Automation routing manifest missing: {path}")
    return _read_json(path)


def workflow_family(skill_id: str, workflow_doc: str) -> str:
    text = f"{skill_id} {workflow_doc}".lower()
    if "report" in text:
        return "reporting"
    if "content" in text or "collection" in text or "blog" in text or "internal-link" in text:
        return "content_operations"
    if "audit" in text or "technical" in text or "screaming" in text:
        return "technical"
    if "maintenance" in text or "hygiene" in text or "troubleshoot" in text or "filing" in text:
        return "maintenance"
    if "onboard" in text or "new-client" in text:
        return "client_readiness"
    if "gsc" in text or "opportunity" in text or "roadmap" in text or "keyword" in text:
        return "seo_opportunity"
    return "workflow_routing"


def workflow_title(root: Path, workflow_doc: str) -> str:
    path = root / workflow_doc
    if not path.exists():
        return Path(workflow_doc).stem.replace("-", " ").title()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("# "):
            return _clean_text(line.removeprefix("# "), max_chars=120) or Path(workflow_doc).stem
    return Path(workflow_doc).stem.replace("-", " ").title()


def build_workflow_catalog_rows(
    *,
    root: Path = DEFAULT_SEO_AUTOMATION_ROOT,
    run_id: str,
    synced_at: str | None = None,
) -> list[dict[str, Any]]:
    synced_at = synced_at or utc_now_iso()
    manifest = load_routing_manifest(root)
    rows: list[dict[str, Any]] = []
    for skill_id, skill in sorted((manifest.get("skills") or {}).items()):
        workflow_docs = skill.get("workflow_docs") or []
        if not workflow_docs:
            workflow_docs = [skill.get("skill_doc") or skill_id]
        for workflow_doc in workflow_docs:
            if not workflow_doc:
                continue
            workflow_id = slugify(Path(str(workflow_doc)).stem or skill_id)
            row = {
                "synced_at": synced_at,
                "run_id": run_id,
                "workflow_id": workflow_id,
                "family": workflow_family(skill_id, str(workflow_doc)),
                "skill_id": skill_id,
                "workflow_doc_path": _clean_text(workflow_doc, max_chars=240),
                "title": workflow_title(root, str(workflow_doc)),
                "commands_json": _safe_list(skill.get("commands_or_intents")),
                "required_inputs_json": _safe_list(skill.get("required_preflight_reads")),
                "scripts_json": _safe_list(skill.get("scripts")),
                "validators_json": _safe_list(skill.get("validators")),
                "api_dependencies_json": _safe_list(skill.get("api_dependencies")),
                "mcp_dependencies_json": _workflow_dependencies(skill.get("mcp_dependencies"), workflow_doc=str(workflow_doc), kind="mcp"),
                "write_gates_json": _safe_list(skill.get("write_gates")),
                "proof_fields_json": _safe_list(skill.get("proof_block_fields")),
                "active": True,
                "notes": _clean_text(skill.get("notes"), max_chars=240),
                "source_ref_hash": stable_hash({"skill_id": skill_id, "workflow_doc": workflow_doc}),
            }
            rows.append(row)
    return rows


def _timeline_table_rows(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        if row.get("Date") and row.get("Task"):
            rows.append(row)
    return rows


def summarize_timeline(path: Path, *, max_rows: int = MAX_TIMELINE_ROWS) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    if SECRET_TEXT_RE.search(text):
        raise SeoAutomationCatalogError(f"secret-like text found in timeline: {path}")
    rows = _timeline_table_rows(text)
    summaries: list[dict[str, Any]] = []
    for row in rows[-max_rows:]:
        summary = {
            "date": _clean_text(row.get("Date"), max_chars=40),
            "task": _clean_text(row.get("Task"), max_chars=140),
            "outcome": _clean_text(row.get("Outputs"), max_chars=220),
            "decisions": _clean_text(row.get("Decisions"), max_chars=220),
            "caveats": _clean_text(row.get("Caveats"), max_chars=220),
            "next_action": _clean_text(row.get("Next action"), max_chars=220),
            "proof_summary": _clean_text(row.get("Proof summary"), max_chars=260),
            "source_ref_hash": stable_hash(row),
        }
        summaries.append({key: val for key, val in summary.items() if val})
    return summaries


def _sidecar_path_for_client(clients_dir: Path, slug: str) -> Path:
    return clients_dir / f"{slug}.json"


def _brief_path_for_client(clients_dir: Path, slug: str) -> Path:
    return clients_dir / f"{slug}.md"


def _timeline_path_for_client(clients_dir: Path, slug: str) -> Path:
    return clients_dir / f"{slug}-timeline.md"


def client_slugs(root: Path = DEFAULT_SEO_AUTOMATION_ROOT) -> list[str]:
    clients_dir = SeoAutomationRoots(root).clients_dir
    slugs = set()
    for path in clients_dir.glob("*.md"):
        name = path.stem
        if name.startswith("_") or name.startswith("CLIENT") or name.endswith("-timeline") or name.endswith("-writing-style"):
            continue
        slugs.add(name)
    for path in clients_dir.glob("*.json"):
        if path.name.startswith("CLIENT"):
            continue
        slugs.add(path.stem)
    return sorted(slugs)


def build_client_memory_summary_rows(
    *,
    root: Path = DEFAULT_SEO_AUTOMATION_ROOT,
    run_id: str,
    synced_at: str | None = None,
    only_client_slug: str | None = None,
) -> list[dict[str, Any]]:
    synced_at = synced_at or utc_now_iso()
    clients_dir = SeoAutomationRoots(root).clients_dir
    slugs = [slugify(only_client_slug)] if only_client_slug else client_slugs(root)
    rows: list[dict[str, Any]] = []
    for slug in slugs:
        if not slug:
            continue
        sidecar_path = _sidecar_path_for_client(clients_dir, slug)
        brief_path = _brief_path_for_client(clients_dir, slug)
        timeline_path = _timeline_path_for_client(clients_dir, slug)
        sidecar = _read_json(sidecar_path) if sidecar_path.exists() else {}
        if SECRET_TEXT_RE.search(json.dumps(sidecar, default=str)):
            raise SeoAutomationCatalogError(f"secret-like text found in sidecar: {sidecar_path}")
        drive = _safe_dict(sidecar.get("drive"))
        monday = _safe_dict(sidecar.get("monday"))
        se_ranking = _safe_dict(sidecar.get("se_ranking"))
        collections = sidecar.get("collections") if isinstance(sidecar.get("collections"), list) else []
        deliverables = _safe_dict(sidecar.get("deliverables"))
        reports = _safe_dict(sidecar.get("reports"))
        recent_timeline = summarize_timeline(timeline_path)
        row = {
            "synced_at": synced_at,
            "run_id": run_id,
            "client_slug": slug,
            "client_name": _clean_text(sidecar.get("client") or slug.replace("-", " ").title(), max_chars=160),
            "domain": _clean_text(sidecar.get("domain") or (sidecar.get("website") or {}).get("domain"), max_chars=160),
            "site_type": _clean_text(sidecar.get("site_type"), max_chars=80),
            "market_scope": _clean_text(sidecar.get("market_scope"), max_chars=40),
            "workflow_profile": _clean_text(sidecar.get("workflow_profile"), max_chars=80),
            "sidecar_path": _safe_rel(sidecar_path, root) if sidecar_path.exists() else None,
            "brief_path": _safe_rel(brief_path, root) if brief_path.exists() else None,
            "timeline_path": _safe_rel(timeline_path, root) if timeline_path.exists() else None,
            "sidecar_present": sidecar_path.exists(),
            "brief_present": brief_path.exists(),
            "timeline_present": timeline_path.exists(),
            "ga4_property": _clean_text(sidecar.get("ga4_property"), max_chars=80),
            "has_search_console_route": bool((sidecar.get("google_access") or {}).get("search_console") or (sidecar.get("routing") or {}).get("search_console")),
            "has_se_ranking": bool(se_ranking),
            "has_monday_route": bool(monday),
            "has_drive_root": bool(drive),
            "drive_routes_json": drive,
            "monday_routes_json": monday,
            "se_ranking_routes_json": se_ranking,
            "collection_count": len(collections),
            "priority_pages_count": len(sidecar.get("priority_pages") or []),
            "deliverables_json": deliverables,
            "reports_json": reports,
            "recent_timeline_summary_json": recent_timeline,
            "source_ref_hash": stable_hash(
                {
                    "client_slug": slug,
                    "sidecar": sidecar_path.stat().st_mtime if sidecar_path.exists() else None,
                    "brief": brief_path.stat().st_mtime if brief_path.exists() else None,
                    "timeline": timeline_path.stat().st_mtime if timeline_path.exists() else None,
                }
            ),
        }
        rows.append(row)
    return rows


def client_readiness_rows(client_rows: list[dict[str, Any]], *, generated_at: str | None = None) -> list[dict[str, Any]]:
    generated_at = generated_at or utc_now_iso()
    rows: list[dict[str, Any]] = []
    for row in client_rows:
        missing = []
        for field, label in (
            ("brief_present", "client_brief"),
            ("sidecar_present", "sidecar_json"),
            ("timeline_present", "timeline"),
            ("has_drive_root", "drive_route"),
            ("has_monday_route", "monday_route"),
            ("has_se_ranking", "se_ranking_route"),
        ):
            if not row.get(field):
                missing.append(label)
        if not row.get("ga4_property"):
            missing.append("ga4_property")
        status = "ready" if not missing else "blocked" if len(missing) >= 3 else "needs_attention"
        rows.append(
            {
                "generated_at": generated_at,
                "client_slug": row["client_slug"],
                "client_name": row["client_name"],
                "readiness_status": status,
                "missing_inputs_json": missing,
                "recommended_workflow_id": "troubleshoot-access" if missing else "monthly-performance-comment",
                "recommended_agent_id": "seo_maintenance_agent" if missing else "reporting_prep_agent",
                "evidence_json": [
                    {
                        "source": "agency_memory.seo_client_memory_summaries",
                        "source_ref_hash": row["source_ref_hash"],
                        "sidecar_path": row.get("sidecar_path"),
                        "brief_path": row.get("brief_path"),
                        "timeline_path": row.get("timeline_path"),
                    }
                ],
                "source_ref_hash": stable_hash({"client_slug": row["client_slug"], "missing": missing}),
            }
        )
    return rows


def opportunity_rows_from_context(
    *,
    client_rows: list[dict[str, Any]],
    reporting_rows: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> list[dict[str, Any]]:
    generated_at = generated_at or utc_now_iso()
    reporting_by_client = {row.get("client_slug"): row for row in reporting_rows or []}
    opportunities: list[dict[str, Any]] = []
    for row in client_rows:
        client_slug = row["client_slug"]
        reporting = reporting_by_client.get(client_slug, {})
        source_tables = ["agency_memory.seo_client_memory_summaries"]
        if reporting:
            source_tables.append("agency_reporting.client_monthly_reporting_coverage")
        if row.get("collection_count", 0) > 0:
            workflow_id = "collection-seo-full"
            opportunity_type = "content_operations"
            summary = f"{row['client_name']} has {row['collection_count']} collection page(s) available for collection SEO review."
            priority = "medium"
        elif reporting and not reporting.get("has_search_console"):
            workflow_id = "troubleshoot-access"
            opportunity_type = "reporting_gap"
            summary = f"{row['client_name']} is missing Search Console coverage in reporting data."
            priority = "high"
        else:
            workflow_id = "gsc-opportunity-mining"
            opportunity_type = "seo_opportunity"
            summary = f"Review GSC and reporting signals for {row['client_name']} to identify next SEO actions."
            priority = "medium"
        opportunities.append(
            {
                "generated_at": generated_at,
                "client_slug": client_slug,
                "client_name": row["client_name"],
                "opportunity_type": opportunity_type,
                "workflow_id": workflow_id,
                "priority": priority,
                "summary": _clean_text(summary, max_chars=300),
                "recommended_action": f"Run SEO Automation workflow `{workflow_id}` in dry-run/research mode before any external write.",
                "evidence_json": [{"source_tables": source_tables, "source_ref_hash": row["source_ref_hash"]}],
                "source_ref_hash": stable_hash({"client_slug": client_slug, "workflow_id": workflow_id, "summary": summary}),
            }
        )
    return opportunities


def seo_workflow_router_output(
    *,
    request_text: str,
    workflow_rows: list[dict[str, Any]],
    client_rows: list[dict[str, Any]],
    run_id: str,
    created_at: str | None = None,
    agent_id: str = "seo_workflow_router",
    client_slug: str | None = None,
) -> dict[str, Any]:
    created_at = created_at or utc_now_iso()
    request_lc = request_text.lower()
    candidates = workflow_rows
    if "report" in request_lc:
        candidates = [row for row in workflow_rows if row.get("family") == "reporting"] or candidates
    elif "content" in request_lc or "brief" in request_lc or "collection" in request_lc:
        candidates = [row for row in workflow_rows if row.get("family") == "content_operations"] or candidates
    elif "audit" in request_lc or "crawl" in request_lc or "technical" in request_lc:
        candidates = [row for row in workflow_rows if row.get("family") == "technical"] or candidates
    elif "access" in request_lc or "hygiene" in request_lc or "filing" in request_lc:
        candidates = [row for row in workflow_rows if row.get("family") == "maintenance"] or candidates
    selected = candidates[0] if candidates else {}
    scoped_clients = [row for row in client_rows if not client_slug or row["client_slug"] == slugify(client_slug)]
    if not scoped_clients and client_slug:
        scoped_clients = [{"client_slug": slugify(client_slug), "client_name": client_slug, "source_ref_hash": stable_hash(client_slug)}]
    findings = []
    actions = []
    for client in scoped_clients[:20]:
        evidence = [
            {
                "source": "agency_memory.seo_workflow_catalog",
                "workflow_id": selected.get("workflow_id"),
                "workflow_doc_path": selected.get("workflow_doc_path"),
            },
            {
                "source": "agency_memory.seo_client_memory_summaries",
                "client_slug": client.get("client_slug"),
                "source_ref_hash": client.get("source_ref_hash"),
            },
        ]
        finding = normalize_finding(
            {
                "client_slug": client.get("client_slug"),
                "finding_type": "seo_workflow_route",
                "severity": "info",
                "summary": f"Suggested SEO Automation workflow: {selected.get('title') or selected.get('workflow_id')}",
                "evidence": evidence,
                "source_tables": ["agency_memory.seo_workflow_catalog", "agency_memory.seo_client_memory_summaries"],
                "recommended_action": f"Review and run `{selected.get('workflow_id')}` as a dry-run/research workflow.",
                "confidence_score": 0.72,
                "requires_human_review": True,
                "qa_status": "needs_review",
            },
            run_id=run_id,
            agent_id=agent_id,
            created_at=created_at,
        )
        action = normalize_action(
            {
                "client_slug": client.get("client_slug"),
                "finding_id": finding["finding_id"],
                "action_type": "run_seo_automation_workflow",
                "target_system": "codex",
                "recommended_action": f"Prepare SEO Automation workflow `{selected.get('workflow_id')}` for {client.get('client_name')}.",
                "priority": "medium",
                "status": "suggested",
                "requires_approval": False,
                "evidence": evidence,
            },
            run_id=run_id,
            agent_id=agent_id,
            created_at=created_at,
        )
        findings.append(finding)
        actions.append(action)
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": agent_id,
            "created_at": created_at,
            "summary": f"Routed request to {selected.get('workflow_id') or 'no workflow'} for {len(scoped_clients)} client(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {
                "workflow_candidates": len(workflow_rows),
                "clients_considered": len(scoped_clients),
                "selected_workflow_id": selected.get("workflow_id"),
            },
        }
    )


def agent_output_from_opportunities(
    *,
    opportunities: list[dict[str, Any]],
    run_id: str,
    agent_id: str,
    created_at: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    created_at = created_at or utc_now_iso()
    selected = opportunities[:limit] if limit else opportunities
    findings = []
    actions = []
    for opportunity in selected:
        evidence = opportunity.get("evidence_json") or [{"source": "agency_reporting.seo_opportunity_queue"}]
        finding = normalize_finding(
            {
                "client_slug": opportunity["client_slug"],
                "finding_type": opportunity["opportunity_type"],
                "severity": "medium" if opportunity.get("priority") == "high" else "low",
                "summary": opportunity["summary"],
                "evidence": evidence,
                "source_tables": ["agency_reporting.seo_opportunity_queue"],
                "recommended_action": opportunity["recommended_action"],
                "confidence_score": 0.7,
                "requires_human_review": True,
                "qa_status": "needs_review",
            },
            run_id=run_id,
            agent_id=agent_id,
            created_at=created_at,
        )
        action = normalize_action(
            {
                "client_slug": opportunity["client_slug"],
                "finding_id": finding["finding_id"],
                "action_type": "seo_workflow_review",
                "target_system": "codex",
                "recommended_action": opportunity["recommended_action"],
                "priority": opportunity.get("priority") or "medium",
                "status": "suggested",
                "requires_approval": False,
                "evidence": evidence,
            },
            run_id=run_id,
            agent_id=agent_id,
            created_at=created_at,
        )
        findings.append(finding)
        actions.append(action)
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": agent_id,
            "created_at": created_at,
            "summary": f"Reviewed {len(selected)} SEO Automation opportunity row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"opportunities_reviewed": len(selected), "actions_suggested": len(actions)},
        }
    )
