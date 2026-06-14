from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScoreBand:
    label: str
    tone: str


def score_band(score: float) -> ScoreBand:
    if score < 45:
        return ScoreBand("Critical", "critical")
    if score < 70:
        return ScoreBand("Needs attention", "danger")
    if score < 85:
        return ScoreBand("Watch", "warning")
    return ScoreBand("Healthy", "success")


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def average(values: list[float], default: float = 100.0) -> float:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return default
    return sum(clean) / len(clean)


def setup_score(clients: list[dict[str, Any]]) -> float:
    explicit = [float(row.get("health_score") or 0) * 100 for row in clients if row.get("health_score") is not None]
    if explicit:
        return average(explicit)
    status_penalties = {
        "healthy": 100,
        "green": 100,
        "partial": 78,
        "watch": 78,
        "needs_attention": 62,
        "amber": 62,
        "critical_missing": 32,
        "critical": 32,
        "red": 32,
    }
    return average([status_penalties.get(str(row.get("health_status") or "").lower(), 70) for row in clients])


def readiness_score(reporting: list[dict[str, Any]]) -> float:
    penalties = {
        "ready": 100,
        "healthy": 100,
        "complete": 100,
        "partial": 74,
        "needs_attention": 62,
        "missing": 42,
        "blocked": 28,
    }
    return average([penalties.get(str(row.get("readiness_status") or row.get("coverage_status") or "").lower(), 72) for row in reporting])


def delivery_score(delivery: list[dict[str, Any]]) -> float:
    if not delivery:
        return 100
    overdue = sum(1 for row in delivery if row.get("is_overdue") or row.get("due_state") == "overdue")
    missing_owner = sum(1 for row in delivery if row.get("owner_missing") or not row.get("owner"))
    risk = min(75, overdue * 8 + missing_owner * 4 + max(0, len(delivery) - 12))
    return 100 - risk


def comms_score(comms: list[dict[str, Any]]) -> float:
    if not comms:
        return 100
    severity = Counter(str(row.get("severity") or row.get("urgency") or "low").lower() for row in comms)
    risk = min(80, severity["high"] * 15 + severity["medium"] * 8 + severity["low"] * 3 + max(0, len(comms) - 8) * 2)
    return 100 - risk


def roadmap_completion_score(roadmaps: list[dict[str, Any]]) -> float:
    rates = []
    for row in roadmaps:
        if row.get("completion_rate") is not None:
            rates.append(float(row["completion_rate"]) * 100)
        elif row.get("planned_items"):
            rates.append((float(row.get("completed_items") or 0) / float(row["planned_items"])) * 100)
    return average(rates)


def roadmap_coverage_score(clients: list[dict[str, Any]], roadmap_items: list[dict[str, Any]]) -> float:
    if not clients:
        return 100
    clients_with_flags = sum(1 for row in clients if row.get("has_roadmap_items"))
    if clients_with_flags:
        return (clients_with_flags / len(clients)) * 100
    clients_with_items = {str(row.get("client_slug") or "") for row in roadmap_items if row.get("client_slug")}
    return (len(clients_with_items) / len(clients)) * 100


def roadmap_evidence_score(clients: list[dict[str, Any]]) -> float:
    if not clients:
        return 100
    valid = sum(1 for row in clients if row.get("has_roadmap_content_validated"))
    return (valid / len(clients)) * 100


def roadmap_risk_score(roadmaps: list[dict[str, Any]], roadmap_items: list[dict[str, Any]]) -> float:
    missing_evidence = sum(int(row.get("missing_evidence_items") or 0) for row in roadmaps)
    overdue = sum(int(row.get("overdue_items") or 0) for row in roadmaps)
    high_priority_open = sum(
        1
        for row in roadmap_items
        if str(row.get("priority") or "").lower() == "high"
        and str(row.get("delivery_status") or row.get("planned_status") or "").lower() not in {"done", "completed", "complete"}
    )
    risk = min(80, missing_evidence * 8 + overdue * 12 + high_priority_open * 4)
    return 100 - risk


def roadmap_health(clients: list[dict[str, Any]], roadmaps: list[dict[str, Any]], roadmap_items: list[dict[str, Any]]) -> dict[str, float]:
    coverage = roadmap_coverage_score(clients, roadmap_items)
    evidence = roadmap_evidence_score(clients)
    completion = roadmap_completion_score(roadmaps)
    risk = roadmap_risk_score(roadmaps, roadmap_items)
    score = coverage * 0.35 + evidence * 0.25 + completion * 0.25 + risk * 0.15
    return {
        "score": score,
        "coverage": coverage,
        "evidence": evidence,
        "completion": completion,
        "risk": risk,
    }


def performance_score(performance: list[dict[str, Any]]) -> float:
    if not performance:
        return 75
    values = []
    for row in performance:
        direction = str(row.get("performance_status") or row.get("source_health") or "").lower()
        if direction in {"strong", "healthy", "up", "green"}:
            values.append(94)
        elif direction in {"watch", "mixed", "flat", "partial"}:
            values.append(76)
        elif direction in {"down", "needs_attention", "amber"}:
            values.append(58)
        elif direction in {"critical", "red", "missing"}:
            values.append(38)
        else:
            mom = row.get("organic_sessions_mom_pct")
            values.append(82 if mom is not None and float(mom) >= 0 else 66)
    return average(values, default=75)


def data_health_score(data_health: dict[str, Any]) -> float:
    cost_failures = int(data_health.get("cost_failures") or 0)
    ingestion_failures = int(data_health.get("ingestion_failures") or 0)
    stale_tables = int(data_health.get("stale_tables") or 0)
    agent_failures = int(data_health.get("agent_failures") or 0)
    return 100 - min(80, cost_failures * 20 + ingestion_failures * 18 + stale_tables * 10 + agent_failures * 8)


def overall_health(payload: dict[str, Any]) -> dict[str, Any]:
    roadmaps = roadmap_health(
        payload.get("clients", []),
        payload.get("roadmaps", []),
        payload.get("roadmap_items", []),
    )
    components = {
        "client_setup": setup_score(payload.get("clients", [])),
        "reporting": readiness_score(payload.get("reporting", [])),
        "delivery": delivery_score(payload.get("delivery", [])),
        "comms": comms_score(payload.get("comms", [])),
        "roadmaps": roadmaps["score"],
        "performance": performance_score(payload.get("performance", [])),
        "data_health": data_health_score(payload.get("data_health", {})),
    }
    weights = {
        "client_setup": 0.20,
        "reporting": 0.14,
        "delivery": 0.16,
        "comms": 0.12,
        "roadmaps": 0.12,
        "performance": 0.16,
        "data_health": 0.10,
    }
    score = clamp_score(sum(components[key] * weights[key] for key in components))
    band = score_band(score)
    return {
        "score": score,
        "status": band.label,
        "tone": band.tone,
        "components": {key: clamp_score(value) for key, value in components.items()},
        "component_details": {
            "roadmaps": {key: clamp_score(value) for key, value in roadmaps.items() if key != "score"},
        },
    }
