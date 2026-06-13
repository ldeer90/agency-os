from __future__ import annotations

from dataclasses import dataclass
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
