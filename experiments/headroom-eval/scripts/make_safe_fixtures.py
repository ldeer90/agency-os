#!/usr/bin/env python3
"""Create safe real-shaped fixtures for Headroom evaluation."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def write_fixture(name: str, payload: dict) -> None:
    path = FIXTURES / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bigquery_health() -> dict:
    rows = [
        {
            "dataset": "agency_memory",
            "table": f"client_table_{idx:02d}",
            "row_count": 120 + idx,
            "latest_loaded_at": "2026-06-15T09:30:00+10:00",
            "status": "ok",
            "note": "routine memory table",
        }
        for idx in range(1, 42)
    ]
    rows.extend(
        [
            {
                "dataset": "agency_memory",
                "table": "monthly_report_snapshots",
                "row_count": 0,
                "latest_loaded_at": None,
                "status": "empty",
                "note": "must investigate: expected published report summaries",
            },
            {
                "dataset": "agency_reporting",
                "table": "client_finance_health",
                "row_count": 120,
                "latest_loaded_at": "2026-06-10T08:00:00+10:00",
                "status": "stale",
                "note": "stale by 6 days",
            },
        ]
    )
    return {
        "workflow": "bigquery_health",
        "privacy_level": "safe_metadata_only",
        "must_preserve": ["monthly_report_snapshots", "client_finance_health", "empty", "stale"],
        "questions": [
            "Which tables need attention?",
            "Which table is empty?",
            "Which table is stale?",
        ],
        "rows": rows,
    }


def monday_metadata() -> dict:
    rows = [
        {
            "board_name": "Agency Delivery",
            "item_id": 700000 + idx,
            "client_slug": f"client-{idx % 9}",
            "item_name": f"SEO task metadata {idx}",
            "status": "Done" if idx % 4 else "Working on it",
            "due_date": "2026-06-20",
            "owner": "agency-team",
        }
        for idx in range(1, 55)
    ]
    rows.append(
        {
            "board_name": "Agency Delivery",
            "item_id": 799999,
            "client_slug": "little-shop-of-happiness",
            "item_name": "June roadmap approval follow-up",
            "status": "Blocked",
            "due_date": "2026-06-12",
            "owner": "agency-team",
        }
    )
    return {
        "workflow": "monday_metadata",
        "privacy_level": "safe_task_metadata_no_updates",
        "must_preserve": ["little-shop-of-happiness", "June roadmap approval follow-up", "Blocked", "2026-06-12"],
        "questions": [
            "Which task is blocked?",
            "Which client needs follow-up?",
            "What date is overdue?",
        ],
        "rows": rows,
    }


def crawl_summary() -> dict:
    rows = [
        {
            "client_slug": "shop-rongrong",
            "url": f"https://example.com/product/{idx}",
            "status_code": 200,
            "indexability": "Indexable",
            "title_status": "ok",
            "canonical_status": "self",
        }
        for idx in range(1, 70)
    ]
    rows.extend(
        [
            {
                "client_slug": "shop-rongrong",
                "url": "https://example.com/products/retired-kit",
                "status_code": 404,
                "indexability": "Non-Indexable",
                "title_status": "missing",
                "canonical_status": "none",
            },
            {
                "client_slug": "shop-rongrong",
                "url": "https://example.com/collections/new-arrivals?page=2",
                "status_code": 200,
                "indexability": "Indexable",
                "title_status": "duplicate",
                "canonical_status": "canonicalised-to-page-1",
            },
        ]
    )
    return {
        "workflow": "crawl_summary",
        "privacy_level": "public_url_crawl_metadata",
        "must_preserve": ["retired-kit", "404", "missing", "canonicalised-to-page-1"],
        "questions": [
            "Which URL has a 404?",
            "Which issue affects page 2?",
            "What should be checked first?",
        ],
        "rows": rows,
    }


def reporting_performance() -> dict:
    rows = [
        {
            "client_slug": f"client-{idx}",
            "period_id": "2026-05",
            "organic_sessions": 1000 + idx * 20,
            "organic_sessions_mom_pct": 0.03,
            "gsc_clicks": 500 + idx * 8,
            "source_health": "ok",
        }
        for idx in range(1, 35)
    ]
    rows.extend(
        [
            {
                "client_slug": "ducati-melbourne",
                "period_id": "2026-05",
                "organic_sessions": 420,
                "organic_sessions_mom_pct": -0.62,
                "gsc_clicks": 210,
                "source_health": "route_changed",
            },
            {
                "client_slug": "travelkon",
                "period_id": "2026-05",
                "organic_sessions": 9820,
                "organic_sessions_mom_pct": 0.41,
                "gsc_clicks": 4120,
                "source_health": "ok",
            },
        ]
    )
    return {
        "workflow": "reporting_performance",
        "privacy_level": "summary_metrics_only",
        "must_preserve": ["ducati-melbourne", "-0.62", "route_changed", "travelkon", "0.41"],
        "questions": [
            "Which client dropped sharply?",
            "Which client grew strongly?",
            "What source-health warning exists?",
        ],
        "rows": rows,
    }


def terminal_logs() -> dict:
    lines = [
        f"INFO test_agency_ops_ingestion case_{idx:03d} passed in 0.02s"
        for idx in range(1, 180)
    ]
    lines.insert(96, "WARNING cost_check_log_errors empty but verify write count manually")
    lines.insert(131, "ERROR test_system_admin_agent failed: expected stale table client_finance_health")
    lines.insert(160, "TRACE run_id=headroom-eval-safe-fixture no secret values present")
    return {
        "workflow": "terminal_logs",
        "privacy_level": "local_test_log_no_secrets",
        "must_preserve": ["ERROR", "test_system_admin_agent", "client_finance_health", "WARNING"],
        "questions": [
            "Which test failed?",
            "What warning should be checked?",
            "Was any secret included?",
        ],
        "lines": lines,
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    write_fixture("bigquery_health", bigquery_health())
    write_fixture("monday_metadata", monday_metadata())
    write_fixture("crawl_summary", crawl_summary())
    write_fixture("reporting_performance", reporting_performance())
    write_fixture("terminal_logs", terminal_logs())
    print(f"Wrote fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
