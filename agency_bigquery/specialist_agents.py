from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from .agent_ops import build_context_pack, normalize_action, normalize_finding, utc_now_iso, validate_agent_output
from .seo_automation_catalog import DEFAULT_SEO_AUTOMATION_ROOT, build_client_memory_summary_rows


@dataclass(frozen=True)
class SpecialistAgentConfig:
    agent_id: str
    agent_name: str
    prompt_version: str
    task_type: str
    source_tables: tuple[str, ...]


SPECIALIST_AGENT_CONFIGS: dict[str, SpecialistAgentConfig] = {
    "performance_analyst": SpecialistAgentConfig(
        agent_id="performance_analyst",
        agent_name="Performance Analyst",
        prompt_version="performance_analyst/v001",
        task_type="performance_review",
        source_tables=(
            "agency_reporting.client_monthly_comparison",
            "agency_reporting.client_monthly_reporting_coverage",
            "agency_reporting.client_health_check",
        ),
    ),
    "drive_filing_readback_agent": SpecialistAgentConfig(
        agent_id="drive_filing_readback_agent",
        agent_name="Drive Filing Readback Agent",
        prompt_version="drive_filing_readback_agent/v001",
        task_type="drive_filing_readback_review",
        source_tables=(
            "agency_memory.seo_client_memory_summaries",
            "agency_reporting.client_health_check",
        ),
    ),
    "se_ranking_hygiene_agent": SpecialistAgentConfig(
        agent_id="se_ranking_hygiene_agent",
        agent_name="SE Ranking Hygiene Agent",
        prompt_version="se_ranking_hygiene_agent/v001",
        task_type="se_ranking_hygiene_review",
        source_tables=(
            "agency_memory.seo_client_memory_summaries",
            "agency_reporting.client_health_check",
        ),
    ),
    "reporting_portal_qa_agent": SpecialistAgentConfig(
        agent_id="reporting_portal_qa_agent",
        agent_name="Reporting Portal QA Agent",
        prompt_version="reporting_portal_qa_agent/v001",
        task_type="reporting_portal_qa_review",
        source_tables=(
            "agency_reporting.reporting_readiness",
            "agency_reporting.client_monthly_reporting_coverage",
            "agency_memory.seo_client_memory_summaries",
        ),
    ),
    "technical_audit_agent": SpecialistAgentConfig(
        agent_id="technical_audit_agent",
        agent_name="Technical Audit Agent",
        prompt_version="technical_audit_agent/v001",
        task_type="technical_audit_evidence_review",
        source_tables=(
            "agency_memory.seo_client_memory_summaries",
            "agency_reporting.client_health_check",
            "agency_memory.seo_workflow_catalog",
        ),
    ),
    "content_research_agent": SpecialistAgentConfig(
        agent_id="content_research_agent",
        agent_name="Content Research Agent",
        prompt_version="content_research_agent/v001",
        task_type="content_research_readiness_review",
        source_tables=(
            "agency_memory.seo_client_memory_summaries",
            "agency_memory.seo_workflow_catalog",
            "SEO Automation docs/agent/workflows/collection-content-briefs.md",
        ),
    ),
    "content_writer_agent": SpecialistAgentConfig(
        agent_id="content_writer_agent",
        agent_name="Content Writer Agent",
        prompt_version="content_writer_agent/v001",
        task_type="content_writer_readiness_review",
        source_tables=(
            "agency_memory.seo_client_memory_summaries",
            "local content research packs",
            "SEO Automation final content writing workflows",
        ),
    ),
    "system_admin_agent": SpecialistAgentConfig(
        agent_id="system_admin_agent",
        agent_name="System Admin Agent",
        prompt_version="system_admin_agent/v001",
        task_type="agencyos_system_admin_sweep",
        source_tables=(
            "config/bigquery_cost_guardrails.json",
            "data/agent_runs/index.json",
            "data/agent_runs/active/*.json",
            "agency_control.ingestion_runs",
            "agency_control.cost_checks",
            "agency_reporting.client_health_check",
        ),
    ),
}


def _client_name(row: dict[str, Any]) -> str:
    return str(row.get("client_name") or row.get("client_slug") or "client")


def _evidence(row: dict[str, Any], source: str, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = {
        "source": source,
        "client_slug": row.get("client_slug"),
        "source_ref_hash": row.get("source_ref_hash"),
    }
    for key in (
        "period_id",
        "snapshot_date",
        "readiness_status",
        "coverage_status",
        "workflow_id",
        "sidecar_path",
        "brief_path",
        "timeline_path",
    ):
        if row.get(key) is not None:
            payload[key] = row.get(key)
    if extra:
        payload.update(extra)
    return [payload]


def _append_finding_action(
    *,
    findings: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    run_id: str,
    agent_id: str,
    created_at: str,
    row: dict[str, Any],
    finding_type: str,
    severity: str,
    summary: str,
    recommended_action: str,
    evidence: list[dict[str, Any]],
    priority: str = "medium",
    target_system: str = "codex",
    confidence_score: float = 0.68,
) -> None:
    finding = normalize_finding(
        {
            "client_slug": row.get("client_slug"),
            "finding_type": finding_type,
            "severity": severity,
            "summary": summary,
            "evidence": evidence,
            "source_tables": [str(item.get("source") or "local_context") for item in evidence],
            "recommended_action": recommended_action,
            "confidence_score": confidence_score,
            "requires_human_review": True,
            "qa_status": "needs_review",
        },
        run_id=run_id,
        agent_id=agent_id,
        created_at=created_at,
    )
    action = normalize_action(
        {
            "client_slug": row.get("client_slug"),
            "finding_id": finding["finding_id"],
            "action_type": finding_type,
            "target_system": target_system,
            "recommended_action": recommended_action,
            "priority": priority,
            "status": "suggested",
            "requires_approval": target_system not in {"codex", "local_report", "bigquery", "none"},
            "evidence": evidence,
        },
        run_id=run_id,
        agent_id=agent_id,
        created_at=created_at,
    )
    findings.append(finding)
    actions.append(action)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_stale(value: Any, *, created_at: str, max_age_hours: int) -> bool:
    observed = _parse_datetime(value)
    current = _parse_datetime(created_at)
    if not observed or not current:
        return True
    if observed.tzinfo is None and current.tzinfo is not None:
        observed = observed.replace(tzinfo=current.tzinfo)
    if current.tzinfo is None and observed.tzinfo is not None:
        current = current.replace(tzinfo=observed.tzinfo)
    return current - observed > timedelta(hours=max_age_hours)


def performance_analyst_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        client = _client_name(row)
        missing_sources = [
            label
            for field, label in (
                ("has_ga4", "GA4"),
                ("has_search_console", "Search Console"),
                ("has_se_ranking", "SE Ranking"),
            )
            if row.get(field) is False
        ]
        if missing_sources:
            _append_finding_action(
                findings=findings,
                actions=actions,
                run_id=run_id,
                agent_id="performance_analyst",
                created_at=created_at,
                row=row,
                finding_type="performance_source_gap",
                severity="medium",
                summary=f"{client} has missing performance source coverage: {', '.join(missing_sources)}.",
                recommended_action="Review reporting coverage and route missing access through reporting prep or SEO maintenance before drafting performance commentary.",
                evidence=_evidence(row, row.get("source_table") or "agency_reporting.client_monthly_reporting_coverage", {"missing_sources": missing_sources}),
                priority="medium",
            )
        pct = row.get("organic_sessions_mom_pct")
        if isinstance(pct, (int, float)) and abs(pct) >= 0.2:
            direction = "increased" if pct > 0 else "declined"
            _append_finding_action(
                findings=findings,
                actions=actions,
                run_id=run_id,
                agent_id="performance_analyst",
                created_at=created_at,
                row=row,
                finding_type="performance_movement",
                severity="medium" if pct > 0 else "high",
                summary=f"{client} organic sessions {direction} {round(pct * 100, 1)}% month over month.",
                recommended_action="Review GA4, Search Console, SE Ranking, and delivery context before turning this movement into client-facing commentary.",
                evidence=_evidence(row, row.get("source_table") or "agency_reporting.client_monthly_comparison", {"organic_sessions_mom_pct": pct}),
                priority="high" if pct < 0 else "medium",
            )
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "performance_analyst",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} performance row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"rows_reviewed": len(rows), "findings": len(findings), "actions": len(actions)},
        }
    )


def drive_filing_readback_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        client = _client_name(row)
        missing = []
        if row.get("has_drive_root") is False:
            missing.append("Drive root route")
        if row.get("has_drive_root_verified") is False:
            missing.append("Drive root metadata verification")
        if row.get("has_reports_folder_verified") is False:
            missing.append("reports folder verification")
        if row.get("has_content_folder_verified") is False:
            missing.append("content folder verification")
        if not missing and row.get("has_drive_root") in (None, ""):
            drive_routes = row.get("drive_routes_json")
            if not drive_routes:
                missing.append("Drive route summary")
        if missing:
            _append_finding_action(
                findings=findings,
                actions=actions,
                run_id=run_id,
                agent_id="drive_filing_readback_agent",
                created_at=created_at,
                row=row,
                finding_type="drive_route_readback_gap",
                severity="medium",
                summary=f"{client} needs Drive filing/readback verification: {', '.join(missing)}.",
                recommended_action="Verify the target Drive route with the Google Drive MCP before filing or trusting report readback metadata.",
                evidence=_evidence(row, row.get("source_table") or "agency_memory.seo_client_memory_summaries", {"missing": missing}),
                priority="medium",
            )
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "drive_filing_readback_agent",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} Drive route/readback row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"rows_reviewed": len(rows), "findings": len(findings), "actions": len(actions)},
        }
    )


def se_ranking_hygiene_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        client = _client_name(row)
        missing = []
        if row.get("has_se_ranking") is False:
            missing.append("SE Ranking route")
        if row.get("has_se_ranking_access") is False:
            missing.append("SE Ranking access smoke")
        if not missing and row.get("has_se_ranking") in (None, "") and not row.get("se_ranking_routes_json"):
            missing.append("SE Ranking route summary")
        if missing:
            _append_finding_action(
                findings=findings,
                actions=actions,
                run_id=run_id,
                agent_id="se_ranking_hygiene_agent",
                created_at=created_at,
                row=row,
                finding_type="se_ranking_hygiene_gap",
                severity="medium",
                summary=f"{client} needs SE Ranking hygiene review: {', '.join(missing)}.",
                recommended_action="Run the SEO Automation SE Ranking hygiene workflow in dry-run/research mode before changing any project, keyword, or AI tracker state.",
                evidence=_evidence(row, row.get("source_table") or "agency_memory.seo_client_memory_summaries", {"missing": missing}),
                priority="medium",
            )
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "se_ranking_hygiene_agent",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} SE Ranking hygiene row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"rows_reviewed": len(rows), "findings": len(findings), "actions": len(actions)},
        }
    )


def reporting_portal_qa_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        client = _client_name(row)
        gaps = []
        readiness = str(row.get("readiness_status") or "").lower()
        coverage = str(row.get("coverage_status") or "").lower()
        if readiness and readiness not in {"ready", "green", "complete"}:
            gaps.append(f"readiness is {readiness}")
        if coverage and coverage not in {"complete", "ready", "green"}:
            gaps.append(f"coverage is {coverage}")
        for field, label in (("has_ga4", "GA4"), ("has_search_console", "Search Console"), ("has_se_ranking", "SE Ranking")):
            if row.get(field) is False:
                gaps.append(f"missing {label}")
        if gaps:
            _append_finding_action(
                findings=findings,
                actions=actions,
                run_id=run_id,
                agent_id="reporting_portal_qa_agent",
                created_at=created_at,
                row=row,
                finding_type="reporting_portal_qa_gap",
                severity="medium",
                summary=f"{client} reporting portal QA has blockers or caveats: {', '.join(gaps)}.",
                recommended_action="Resolve or explicitly document reporting source caveats before publishing, sharing, or treating the portal as client-ready.",
                evidence=_evidence(row, row.get("source_table") or "agency_reporting.reporting_readiness", {"gaps": gaps}),
                priority="medium",
            )
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "reporting_portal_qa_agent",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} reporting portal QA row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"rows_reviewed": len(rows), "findings": len(findings), "actions": len(actions)},
        }
    )


def technical_audit_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        client = _client_name(row)
        has_domain = bool(row.get("domain") or row.get("start_url") or row.get("site_url"))
        if not has_domain:
            continue
        crawl_id = row.get("crawl_id")
        if crawl_id:
            if row.get("crawl_status") == "coverage_failed":
                _append_finding_action(
                    findings=findings,
                    actions=actions,
                    run_id=run_id,
                    agent_id="technical_audit_agent",
                    created_at=created_at,
                    row=row,
                    finding_type="technical_crawl_coverage_blocker",
                    severity="high",
                    summary=f"{client} has a crawl export that failed coverage validation and should not be used for technical prioritisation.",
                    recommended_action="Rerun the crawl with an approved full-site scope, or reload it as an explicit partial-scope crawl with a scope reference before sending findings to the SEO lead.",
                    evidence=_evidence(
                        row,
                        row.get("source_table") or "agency_reporting.client_crawl_latest",
                        {
                            "crawl_id": crawl_id,
                            "crawl_date": row.get("crawl_date"),
                            "pages_crawled": row.get("pages_crawled"),
                            "crawl_status": row.get("crawl_status"),
                            "issue_counts_json": row.get("issue_counts_json"),
                        },
                    ),
                    priority="high",
                    confidence_score=0.9,
                )
                continue
            issue_metrics = {
                "status_4xx_urls": row.get("status_4xx_urls"),
                "status_5xx_urls": row.get("status_5xx_urls"),
                "missing_title_urls": row.get("missing_title_urls"),
                "duplicate_title_urls": row.get("duplicate_title_urls"),
                "missing_meta_description_urls": row.get("missing_meta_description_urls"),
                "missing_h1_urls": row.get("missing_h1_urls"),
                "canonical_issue_urls": row.get("canonical_issue_urls"),
                "low_content_urls": row.get("low_content_urls"),
            }
            known_issues = {key: value for key, value in issue_metrics.items() if value not in (None, 0, "0")}
            issue_counts = row.get("issue_counts_json") or {}
            top_issues = issue_counts.get("top_issues") if isinstance(issue_counts, dict) else None
            if top_issues:
                known_issues["top_issues"] = top_issues[:10]
                known_issues["summary_source"] = issue_counts.get("summary_source")
            issue_examples = row.get("crawl_issue_examples_json")
            if issue_examples:
                try:
                    parsed_examples = json.loads(issue_examples)
                except (TypeError, json.JSONDecodeError):
                    parsed_examples = issue_examples
                if parsed_examples:
                    known_issues["affected_url_examples"] = parsed_examples[:10] if isinstance(parsed_examples, list) else parsed_examples
            if known_issues:
                _append_finding_action(
                    findings=findings,
                    actions=actions,
                    run_id=run_id,
                    agent_id="technical_audit_agent",
                    created_at=created_at,
                    row=row,
                    finding_type="technical_crawl_issue_summary",
                    severity="medium",
                    summary=f"{client} latest crawl has technical issue counts that need SEO lead review.",
                    recommended_action="Review the issue-count summary, prioritise commercial-impact fixes, and route any implementation tasks through qa_guardrail before action.",
                    evidence=_evidence(row, row.get("source_table") or "agency_reporting.client_crawl_latest", known_issues),
                    priority="medium",
                    confidence_score=0.78,
                )
            else:
                _append_finding_action(
                    findings=findings,
                    actions=actions,
                    run_id=run_id,
                    agent_id="technical_audit_agent",
                    created_at=created_at,
                    row=row,
                    finding_type="technical_crawl_summary_missing_issue_counts",
                    severity="medium",
                    summary=f"{client} has a completed crawl ({row.get('pages_crawled')} URLs), but issue-count fields are not loaded yet.",
                    recommended_action="Ask the SEO lead to queue a sanitized Screaming Frog summary export/load so technical issues can be prioritised from counts without storing raw HTML or visible text.",
                    evidence=_evidence(
                        row,
                        row.get("source_table") or "agency_reporting.client_crawl_latest",
                        {
                            "crawl_id": crawl_id,
                            "crawl_date": row.get("crawl_date"),
                            "pages_crawled": row.get("pages_crawled"),
                            "crawl_status": row.get("crawl_status"),
                            "export_manifest_path": row.get("export_manifest_path"),
                        },
                    ),
                    priority="high",
                    confidence_score=0.86,
                )
        _append_finding_action(
            findings=findings,
            actions=actions,
            run_id=run_id,
            agent_id="technical_audit_agent",
            created_at=created_at,
            row=row,
            finding_type="technical_crawl_evidence_review",
            severity="info",
            summary=f"{client} is eligible for Screaming Frog technical audit evidence review.",
            recommended_action="Check for an existing Screaming Frog crawl/export first; use the Screaming Frog MCP only for loaded crawl inspection, progress checks, and approved exports before considering a new crawl.",
            evidence=_evidence(
                row,
                row.get("source_table") or "agency_memory.seo_client_memory_summaries",
                {"screaming_frog_mcp_role": "inspect loaded crawls, check progress, export approved crawl data"},
            ),
            priority="low",
            confidence_score=0.62,
        )
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "technical_audit_agent",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} technical audit route row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"rows_reviewed": len(rows), "findings": len(findings), "actions": len(actions)},
        }
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _has_nested_key(value: Any, *keys: str) -> bool:
    current: Any = _json_object(value)
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return current not in (None, "", [], {})


def content_research_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        client = _client_name(row)
        if not row.get("domain"):
            continue
        blockers: list[str] = []
        warnings: list[str] = []
        if not row.get("sidecar_present"):
            blockers.append("client sidecar JSON")
        if not row.get("brief_present"):
            blockers.append("client Markdown brief")
        if not row.get("timeline_present"):
            blockers.append("client timeline")
        if not row.get("has_se_ranking"):
            blockers.append("SE Ranking route")
        if not row.get("has_search_console_route"):
            warnings.append("Search Console route/opportunity source")
        if not row.get("has_drive_root"):
            blockers.append("Drive route for eventual content brief filing")
        if not row.get("has_monday_route"):
            warnings.append("Monday route for eventual task creation")
        collection_count = row.get("collection_count")
        if not isinstance(collection_count, int):
            try:
                collection_count = int(collection_count or 0)
            except (TypeError, ValueError):
                collection_count = 0
        if collection_count <= 0:
            blockers.append("SEO-priority collection set")
        deliverables = _json_object(row.get("deliverables_json"))
        if not _has_nested_key(deliverables, "competitor_serp_json"):
            warnings.append("fresh structured SERP JSON")
        if not _has_nested_key(deliverables, "collection_content_briefs"):
            warnings.append("existing collection brief coverage/readback")
        evidence = _evidence(
            row,
            row.get("source_table") or "agency_memory.seo_client_memory_summaries",
            {
                "workflow_route": "SEO Automation ld-seo-collection-seo -> ld-seo-content-briefs",
                "preferred_doc_format": [
                    "Overview table",
                    "Keywords To Work Into The Page table",
                    "Internal Links table",
                    "Recommended Heading Hierarchy table",
                    "SEO Review table",
                    "Example Copy or Article Requirements section",
                ],
                "collection_count": collection_count,
                "blockers": blockers,
                "warnings": warnings,
            },
        )
        if blockers:
            _append_finding_action(
                findings=findings,
                actions=actions,
                run_id=run_id,
                agent_id="content_research_agent",
                created_at=created_at,
                row=row,
                finding_type="content_research_readiness_blocker",
                severity="high",
                summary=f"{client} is not ready for client-facing content research/brief generation: {', '.join(blockers)}.",
                recommended_action=(
                    "Route setup gaps through SEO Automation maintenance/onboarding first. "
                    "Do not create Google Docs, Monday tasks, live Shopify updates, or SE Ranking changes until the client sidecar, collection state, and required evidence validate. "
                    "Local HTML previews may be drafted only after validation and lead-agent sense-check."
                ),
                evidence=evidence,
                priority="high",
                confidence_score=0.86,
            )
            continue
        _append_finding_action(
            findings=findings,
            actions=actions,
            run_id=run_id,
            agent_id="content_research_agent",
            created_at=created_at,
            row=row,
            finding_type="content_research_workflow_ready",
            severity="info" if not warnings else "medium",
            summary=f"{client} can be routed into the SEO Automation content research pipeline with {collection_count} collection page(s) in scope.",
            recommended_action=(
                "Run `ld-seo-collection-seo` for keyword research, SERP review, product/page grounding, and metadata opportunities; "
                "then run `ld-seo-content-briefs` only after collection SEO validation passes. "
                "Draft local HTML brief previews first; for final content writing, hand off to `content_writer_agent` so the final HTML is written into the same local research pack/files. "
                "Send local HTML outputs to `agency_supervisor` for sense-check, then ask Laurence for approval. "
                "Only after approval should the Google Doc be created in the approved content folder using the Salad Servers table-led format with native Google Docs tables. "
                "After Doc creation/readback, ask Laurence whether to update or create the related Monday task."
            ),
            evidence=evidence,
            priority="medium" if warnings else "low",
            confidence_score=0.8,
        )
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "content_research_agent",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} content research readiness row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"rows_reviewed": len(rows), "findings": len(findings), "actions": len(actions)},
        }
    )


def content_writer_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        client = _client_name(row)
        if not row.get("domain"):
            continue
        blockers: list[str] = []
        warnings: list[str] = []
        if not row.get("sidecar_present"):
            blockers.append("client sidecar JSON")
        if not row.get("brief_present"):
            blockers.append("client Markdown brief")
        if not row.get("timeline_present"):
            warnings.append("client timeline")
        if not row.get("has_se_ranking"):
            warnings.append("SE Ranking route/volume evidence")
        if not row.get("has_search_console_route"):
            warnings.append("Search Console route/opportunity evidence")
        collection_count = row.get("collection_count")
        try:
            collection_count_int = int(collection_count or 0)
        except (TypeError, ValueError):
            collection_count_int = 0
        if collection_count_int <= 0:
            blockers.append("approved research/brief target pages")
        evidence = _evidence(
            row,
            row.get("source_table") or "agency_memory.seo_client_memory_summaries",
            {
                "writer_flow": [
                    "read approved research/brief inputs from the local research pack",
                    "write final content HTML into the same local pack/file set",
                    "run the matching SEO Automation validator",
                    "send draft to agency_supervisor for sense-check",
                    "ask Laurence for approval before Google Doc, Monday, Shopify, or publishing writes",
                ],
                "blockers": blockers,
                "warnings": warnings,
            },
        )
        if blockers:
            _append_finding_action(
                findings=findings,
                actions=actions,
                run_id=run_id,
                agent_id="content_writer_agent",
                created_at=created_at,
                row=row,
                finding_type="content_writer_readiness_blocker",
                severity="high",
                summary=f"{client} is not ready for final local HTML writing: {', '.join(blockers)}.",
                recommended_action=(
                    "Complete the content research/brief pack first. The writer may only draft final content HTML into the same local research files after approved inputs exist."
                ),
                evidence=evidence,
                priority="high",
                confidence_score=0.84,
            )
            continue
        _append_finding_action(
            findings=findings,
            actions=actions,
            run_id=run_id,
            agent_id="content_writer_agent",
            created_at=created_at,
            row=row,
            finding_type="content_writer_workflow_ready",
            severity="medium" if warnings else "info",
            summary=f"{client} can be routed to local final-content HTML drafting once the approved research/brief pack is selected.",
            recommended_action=(
                "Use the matching SEO Automation writing workflow (`ld-seo-shopify-collection-writing`, `ld-seo-shopify-blog-writing`, or `ld-seo-content-writing`) "
                "to write final content HTML into the same local research pack/files as the brief. Validate the HTML, send it to `agency_supervisor` for sense-check, "
                "then ask Laurence for approval before creating the Google Doc or making any Monday/Shopify/publishing changes."
            ),
            evidence=evidence,
            priority="medium" if warnings else "low",
            confidence_score=0.8,
        )
    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "content_writer_agent",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} content writer readiness row(s).",
            "findings": findings,
            "actions": actions,
            "metrics": {"rows_reviewed": len(rows), "findings": len(findings), "actions": len(actions)},
        }
    )


def system_admin_output(rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    metrics = {
        "rows_reviewed": len(rows),
        "checks_ok": 0,
        "checks_warn": 0,
        "checks_failed": 0,
        "route_verification_gaps": 0,
    }
    for row in rows:
        category = str(row.get("check_category") or "system").strip()
        status = str(row.get("check_status") or "ok").strip().lower()
        client_slug = row.get("client_slug") or "agency-system"
        evidence_source = row.get("source_table") or row.get("source") or category
        evidence = [
            {
                "source": evidence_source,
                "client_slug": client_slug,
                "check_category": category,
                "check_name": row.get("check_name"),
                "check_status": status,
                "observed_at": row.get("observed_at"),
                "source_ref_hash": row.get("source_ref_hash"),
                "details": row.get("details"),
            }
        ]

        if status in {"ok", "healthy", "present"}:
            metrics["checks_ok"] += 1
            continue
        if status in {"warn", "warning", "stale", "unknown"}:
            metrics["checks_warn"] += 1
        else:
            metrics["checks_failed"] += 1

        finding_type = str(row.get("finding_type") or f"system_admin_{category}_gap").strip().lower()
        severity = str(row.get("severity") or ("high" if status in {"failed", "missing", "over_cap"} else "medium")).strip().lower()
        if finding_type == "route_verification_gap":
            metrics["route_verification_gaps"] += 1
            severity = "medium"
        recommended_action = str(row.get("recommended_action") or "Review the system-admin finding and decide whether a follow-up workflow is needed.").strip()
        _append_finding_action(
            findings=findings,
            actions=actions,
            run_id=run_id,
            agent_id="system_admin_agent",
            created_at=created_at,
            row={**row, "client_slug": client_slug},
            finding_type=finding_type,
            severity=severity,
            summary=str(row.get("summary") or f"{category} check needs review: {row.get('check_name') or status}.").strip(),
            recommended_action=recommended_action,
            evidence=evidence,
            priority=str(row.get("priority") or ("high" if severity in {"critical", "high"} else "medium")).strip().lower(),
            target_system=str(row.get("target_system") or "codex").strip().lower(),
            confidence_score=float(row.get("confidence_score") if row.get("confidence_score") is not None else 0.78),
        )

    return validate_agent_output(
        {
            "run_id": run_id,
            "agent_id": "system_admin_agent",
            "created_at": created_at,
            "summary": f"Reviewed {len(rows)} AgencyOS system admin check row(s) and found {len(findings)} item(s) needing review.",
            "findings": findings,
            "actions": actions,
            "metrics": {**metrics, "findings": len(findings), "actions": len(actions)},
        }
    )


def local_client_rows(
    *,
    run_id: str,
    seo_automation_root: str | Path = DEFAULT_SEO_AUTOMATION_ROOT,
    client_slug: str | None = None,
) -> list[dict[str, Any]]:
    return build_client_memory_summary_rows(
        root=Path(seo_automation_root),
        run_id=run_id,
        only_client_slug=client_slug,
    )


def output_for_agent(agent_id: str, rows: list[dict[str, Any]], *, run_id: str, created_at: str) -> dict[str, Any]:
    if agent_id == "performance_analyst":
        return performance_analyst_output(rows, run_id=run_id, created_at=created_at)
    if agent_id == "drive_filing_readback_agent":
        return drive_filing_readback_output(rows, run_id=run_id, created_at=created_at)
    if agent_id == "se_ranking_hygiene_agent":
        return se_ranking_hygiene_output(rows, run_id=run_id, created_at=created_at)
    if agent_id == "reporting_portal_qa_agent":
        return reporting_portal_qa_output(rows, run_id=run_id, created_at=created_at)
    if agent_id == "technical_audit_agent":
        return technical_audit_output(rows, run_id=run_id, created_at=created_at)
    if agent_id == "content_research_agent":
        return content_research_output(rows, run_id=run_id, created_at=created_at)
    if agent_id == "content_writer_agent":
        return content_writer_output(rows, run_id=run_id, created_at=created_at)
    if agent_id == "system_admin_agent":
        return system_admin_output(rows, run_id=run_id, created_at=created_at)
    raise ValueError(f"unsupported specialist agent: {agent_id}")


def context_pack_for_output(
    *,
    agent_id: str,
    run_id: str,
    created_at: str,
    rows: list[dict[str, Any]],
    output: dict[str, Any],
    client_slug: str | None = None,
) -> dict[str, Any]:
    config = SPECIALIST_AGENT_CONFIGS[agent_id]
    return build_context_pack(
        agent_id=agent_id,
        run_id=run_id,
        created_at=created_at,
        task_type=config.task_type,
        source_tables=list(config.source_tables),
        client_slug=client_slug,
        sections={
            "metrics": output.get("metrics", {}),
            "rows_reviewed": len(rows),
            "sample_client_slugs": [row.get("client_slug") for row in rows[:20]],
        },
    )
