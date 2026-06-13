from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agency_bigquery.agency_ops_ingestion import (
    AgencyOpsBigQueryIngestor,
    SourcePaths,
    build_comms_reporting_marts,
    build_roadmap_reporting_marts,
    build_reporting_marts,
    client_comms_attention_sql,
    client_health_check_sql,
    client_roadmap_current_sql,
    collect_agency_ops_rows,
    extract_monthly_performance_summary,
    extract_monthly_report_narrative,
    extract_monthly_reporting_coverage,
    normalize_status,
    normalize_comms_summary_row,
    normalize_roadmap_item_row,
    parse_comms_summary_jsonl,
    parse_client_health_assets,
    parse_monday_board_snapshots,
    parse_roadmap_item_jsonl,
    roadmap_source_rows_from_items,
    read_csv_rows,
)
from agency_bigquery.cost_config import BigQueryCostConfig


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_config() -> BigQueryCostConfig:
    return BigQueryCostConfig(
        project_id="seo-agency-work",
        default_location="australia-southeast1",
        pricing_mode="on_demand",
        currency="AUD",
        monthly_budget_amount=10,
        normal_query_cap_bytes=1_073_741_824,
        admin_override_query_cap_bytes=10_737_418_240,
        dry_run_required=True,
        control_dataset="agency_control",
        staging_dataset="agency_staging",
        memory_dataset="agency_memory",
        reporting_dataset="agency_reporting",
        cost_checks_table="cost_checks",
        staging_table_expiry_hours=72,
        budget_alert_thresholds=(0.5, 0.8, 1.0),
        raw_dataset_policy={},
    )


class FakeClient:
    def __init__(self) -> None:
        self.inserted_rows = []

    def insert_rows_json(self, table_id, rows):
        self.inserted_rows.append({"table_id": table_id, "rows": rows})
        return []


class FakeRunner:
    def __init__(self) -> None:
        self.queries = []

    def run_query(self, sql: str, *, purpose: str):
        self.queries.append({"sql": sql, "purpose": purpose})

        class Result:
            status = "succeeded"

        return Result(), []


class AgencyOpsIngestionTest(unittest.TestCase):
    def make_fixture(self, root: Path) -> SourcePaths:
        monday = root / "monday-agency-hub"
        seo = root / "SEO Automation"
        reporting = root / "seo-reporting-platform"

        write(
            monday / "data/derived/board_index.csv",
            "board_id,board_name,role,role_label,board_kind,permissions,state,items_count,group_count,column_count,group_titles,column_titles,board_family,alias_risk\n"
            "111,Example Client,client_facing,Client,share,everyone,active,1,1,5,June,Name|Status,,\n"
            "222,Sales,sales_pipeline,Sales,public,everyone,active,1,1,5,Deals,Name|Status,,\n",
        )
        write(
            monday / "data/derived/client_board_matrix.csv",
            "client_slug,client_name,client_board_id,client_board_name,board_kind,permissions,seo_execution_board_id,seo_execution_board_name,notes\n"
            "example-client,Example Client,111,Example Client,share,everyone,5026765957,SEO Tasks,\n",
        )
        write(
            monday / "data/derived/task_alignment_report.csv",
            "client,seo_task_item_id,seo_task_name,seo_status,seo_owner,seo_due_date,client_board_id,client_board_name,client_task_item_id,client_task_name,client_status,client_owner,client_due_date,status_match,owner_match,due_date_match,stale_client_update,mismatch_reason\n"
            "Example Client,10,Example :: Audit,Done,Laurence,2026-06-01,111,Example Client,20,Audit,Working on it,Laurence,2026-06-02,false,true,false,true,status mismatch\n",
        )
        write(
            monday / "data/derived/status_labels.csv",
            "board_id,board_name,role,column_id,column_title,column_type,label_id,label_index,label,color,hex,is_done,is_deactivated,is_subitem\n"
            "111,Example Client,client_facing,status,Status,status,1,0,Done,1,#00c875,true,false,false\n",
        )
        write(
            monday / "data/snapshots/board_111.json",
            json.dumps(
                {
                    "id": "111",
                    "name": "Example Client",
                    "columns": [
                        {"id": "name", "title": "Name", "type": "name", "settings": {}},
                        {"id": "person", "title": "Owner", "type": "people", "settings": {}},
                        {"id": "status", "title": "Status", "type": "status", "settings": {"labels": {"1": {"index": 0, "label": "Done", "color": 1, "hex": "#00c875", "is_done": True, "is_deactivated": False}}}},
                        {"id": "date", "title": "Due date", "type": "date", "settings": {}},
                        {"id": "text9", "title": "Notes", "type": "text", "settings": {}},
                    ],
                    "groups": [{"id": "topics", "title": "June"}],
                    "items_count": 1,
                    "items_page": {
                        "items": [
                            {
                                "id": "123",
                                "name": "Task A",
                                "updated_at": "2026-06-12T00:00:00Z",
                                "group": {"id": "topics", "title": "June"},
                                "column_values": [
                                    {"id": "person", "text": "Laurence"},
                                    {"id": "status", "text": "Done"},
                                    {"id": "date", "text": "2026-06-14"},
                                    {"id": "text9", "text": "Private note should not load as a column value"},
                                ],
                            }
                        ]
                    },
                }
            ),
        )
        write(
            monday / "data/snapshots/board_222.json",
            json.dumps({"id": "222", "name": "Sales", "columns": [], "items_count": 1, "items_page": {"items": [{"id": "999", "name": "Lead"}]}}),
        )
        write(
            seo / "docs/agent/clients/example-client.json",
            json.dumps(
                {
                    "client": "example-client",
                    "brand_display_name": "Example Client",
                    "domain": "example.com",
                    "ga4_property": "properties/123",
                    "monday": {"board_id": "111"},
                    "drive": {
                        "client_folder_id": "driveRoot12345",
                        "folders": {
                            "02_roadmap": "roadmapFolder12345",
                            "05_content": "contentFolder12345",
                            "07_reports": "reportsFolder12345",
                        },
                    },
                    "se_ranking": {"project_id": "999"},
                }
            ),
        )
        write(
            seo / "docs/agent/clients/example-client-timeline.md",
            "| Date | Task | Request / source | Evidence checked | Outputs | Decisions | Caveats | Next action | Proof summary |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| 2026-06-12 | Test task | User request | Brief | None | Keep | None | Next | Passed |\n",
        )
        write(
            reporting / "config/clients.json",
            json.dumps({"schemaVersion": 1, "clients": [{"slug": "example-client", "name": "Example Client", "canonicalHost": "example.com", "websiteHosts": ["example.com"], "template": "standard"}]}),
        )
        write(
            reporting / "content/report-index.json",
            json.dumps({"schemaVersion": 1, "generatedAt": "2026-06-12T00:00:00Z", "reports": []}),
        )
        write(
            reporting / "content/reports/2026-06/report.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "client": {
                        "slug": "example-client",
                        "name": "Example Client",
                        "period": {"id": "2026-06", "start": "2026-06-01", "end": "2026-06-30"},
                        "shareId": "share-1",
                        "generatedAt": "2026-06-12T00:00:00Z",
                    },
                    "ga4": {
                        "current": {
                            "totals": {
                                "sessions": 100,
                                "users": 50,
                                "engagedSessions": 40,
                                "purchases": 5,
                                "revenue": 250,
                                "conversion_rate": 0.05,
                                "aov": 50,
                            }
                        },
                        "caveats": [],
                    },
                    "searchConsole": {"current": {"totals": {"clicks": 20, "impressions": 200, "ctr": 0.1, "position": 8}}, "caveats": []},
                    "seRanking": {
                        "visibility": {"start": 10, "end": 12, "delta": 2},
                        "top10Share": {"start": 0.2, "end": 0.3, "delta": 0.1},
                        "averagePosition": {"start": 9, "end": 8, "delta": -1},
                        "caveats": [],
                    },
                    "aiReferrals": {"scorecards": {"sessions": 3, "users": 2, "revenue": 20, "blogSessions": 1}, "caveats": []},
                    "commentary": {"summary": "Good", "completedWork": ["One"], "nextFocus": ["Two"], "caveats": []},
                }
            ),
        )
        return SourcePaths(monday_hub=monday, seo_automation=seo, seo_reporting=reporting, big_query=root / "Big Query")

    def test_collect_agency_ops_rows_maps_sources_and_privacy_boundaries(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self.make_fixture(Path(tmp))

            rows = collect_agency_ops_rows(paths, run_id="run-1", ingested_at="2026-06-12T00:00:00+00:00", snapshot_date="2026-06-12")

        self.assertEqual(len(rows["agency_memory.monday_boards"]), 1)
        self.assertEqual(len(rows["agency_memory.monday_items"]), 1)
        self.assertEqual(rows["agency_memory.monday_items"][0]["normalized_status"], "Done")
        self.assertEqual(len(rows["agency_memory.monday_status_labels"]), 1)
        self.assertEqual(len(rows["agency_memory.client_board_map"]), 1)
        self.assertEqual(len(rows["agency_memory.task_alignment"]), 1)
        self.assertEqual(len(rows["agency_memory.client_timeline_events"]), 1)
        self.assertEqual(len(rows["agency_memory.monthly_report_snapshots"]), 1)
        self.assertGreaterEqual(len(rows["agency_memory.client_health_assets"]), 14)
        self.assertEqual(rows["agency_memory.monthly_report_snapshots"][0]["period_id"], "2026-06")
        self.assertEqual(rows["agency_memory.monthly_report_snapshots"][0]["report_month"], "2026-06-01")
        loaded_column_titles = {row["column_title"] for row in rows["agency_memory.monday_item_column_values"]}
        self.assertNotIn("Notes", loaded_column_titles)

    def test_monday_snapshot_parser_handles_missing_items_page(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_dir = root / "snapshots"
            snapshot_dir.mkdir()
            write(snapshot_dir / "board_111.json", json.dumps({"id": "111", "name": "Client", "columns": [], "items_count": 3}))

            rows = parse_monday_board_snapshots(
                snapshot_dir,
                board_roles={"111": {"role": "client_facing"}},
                client_by_board={},
                run_id="run-1",
                ingested_at="2026-06-12T00:00:00+00:00",
                snapshot_date="2026-06-12",
            )

        self.assertEqual(rows["monday_items"], [])

    def test_normalize_status_defaults_empty_to_not_started(self) -> None:
        self.assertEqual(normalize_status(""), "Not Started")
        self.assertEqual(normalize_status("Working on it"), "In Progress")
        self.assertEqual(normalize_status("Stuck"), "Blocked")

    def test_ingestion_run_logger_records_failure_without_secret(self) -> None:
        client = FakeClient()
        ingestor = AgencyOpsBigQueryIngestor(client, test_config())

        ingestor.log_ingestion_run(
            run_id="run-1",
            source_id="source",
            started_at="2026-06-12T00:00:00+00:00",
            status="failed",
            source_path="source",
            destination_table="table",
            rows_loaded=0,
            error_message="RuntimeError: permission denied",
        )

        row = client.inserted_rows[0]["rows"][0]
        self.assertEqual(row["status"], "failed")
        self.assertIn("permission denied", row["error_message"])

    def test_monthly_performance_helpers_extract_flat_summary_and_narrative(self) -> None:
        payload = {
            "ga4": {
                "current": {
                    "totals": {
                        "sessions": 100,
                        "users": 80,
                        "engagedSessions": 70,
                        "purchases": 10,
                        "revenue": 500,
                        "purchaseRate": 0.1,
                        "aov": 50,
                    }
                }
            },
            "searchConsole": {"current": {"totals": {"clicks": 30, "impressions": 300, "ctr": 0.1, "position": 7.5}}},
            "seRanking": {
                "visibility": {"start": 1, "end": 2, "delta": 1},
                "top10Share": {"start": 0.2, "end": 0.25, "delta": 0.05},
                "averagePosition": {"start": 12, "end": 10, "delta": -2},
            },
            "aiReferrals": {"scorecards": {"sessions": 4, "users": 3, "revenue": 25, "blogSessions": 2}},
            "commentary": {"summary": "Strong month", "completedWork": ["A", "B"], "nextFocus": ["C"], "caveats": ["D"]},
        }

        summary = extract_monthly_performance_summary(payload)
        narrative = extract_monthly_report_narrative(payload)
        coverage = extract_monthly_reporting_coverage(payload)

        self.assertEqual(summary["organic_sessions"], 100.0)
        self.assertEqual(summary["gsc_clicks"], 30.0)
        self.assertEqual(summary["se_visibility_delta"], 1.0)
        self.assertEqual(summary["ai_blog_sessions"], 2.0)
        self.assertEqual(narrative["completed_work"], "A | B")
        self.assertEqual(narrative["next_focus"], "C")
        self.assertEqual(coverage["coverage_status"], "ready")

    def test_monthly_reporting_coverage_handles_missing_sections(self) -> None:
        coverage = extract_monthly_reporting_coverage({"ga4": {"caveats": ["No access"]}})

        self.assertFalse(coverage["has_search_console"])
        self.assertEqual(coverage["coverage_status"], "missing_core_metrics")
        self.assertEqual(coverage["ga4_caveats"], "No access")

    def test_reporting_marts_include_monthly_summary_tables_through_runner(self) -> None:
        runner = FakeRunner()

        statuses = build_reporting_marts(runner, test_config())

        self.assertEqual(statuses["client_monthly_performance_summary"], "succeeded")
        self.assertEqual(statuses["client_monthly_report_narrative"], "succeeded")
        self.assertEqual(statuses["client_monthly_reporting_coverage"], "succeeded")
        self.assertEqual(statuses["client_monthly_performance_history"], "succeeded")
        self.assertEqual(statuses["client_monthly_comparison"], "succeeded")
        self.assertEqual(statuses["client_trailing_performance"], "succeeded")
        self.assertEqual(statuses["client_benchmark_summary"], "succeeded")
        self.assertEqual(statuses["client_roadmap_current"], "succeeded")
        self.assertEqual(statuses["client_roadmap_monthly_completion"], "succeeded")
        purposes = {query["purpose"] for query in runner.queries}
        self.assertIn("agency-ops-mart: build client_monthly_performance_summary", purposes)
        self.assertIn("agency-ops-mart: build client_benchmark_summary", purposes)
        submitted_sql = "\n".join(query["sql"] for query in runner.queries)
        self.assertIn("client_monthly_performance_summary", submitted_sql)
        self.assertIn("client_monthly_comparison", submitted_sql)
        self.assertIn("client_comms_attention", submitted_sql)
        self.assertIn("client_roadmap_monthly_completion", submitted_sql)
        self.assertIn("client_health_check", submitted_sql)

    def test_client_health_assets_capture_expected_presence_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self.make_fixture(Path(tmp))
            board_rows = read_csv_rows(paths.monday_derived / "client_board_matrix.csv")

            rows = parse_client_health_assets(
                paths,
                board_rows,
                run_id="run-1",
                ingested_at="2026-06-12T00:00:00+00:00",
                snapshot_date="2026-06-12",
            )

        by_type = {row["asset_type"]: row for row in rows if row["client_slug"] == "example-client"}
        self.assertEqual(by_type["sidecar_json"]["presence_status"], "present")
        self.assertEqual(by_type["sidecar_json"]["verification_level"], "local_content")
        self.assertEqual(by_type["client_brief"]["presence_status"], "missing")
        self.assertEqual(by_type["drive_roadmap_folder"]["presence_status"], "present")
        self.assertEqual(by_type["drive_roadmap_folder"]["verification_level"], "route_config")
        self.assertEqual(by_type["drive_roadmap_folder_verified"]["presence_status"], "unknown")
        self.assertEqual(by_type["drive_roadmap_files"]["presence_status"], "unknown")
        self.assertEqual(by_type["drive_roadmap_content"]["presence_status"], "unknown")
        self.assertEqual(by_type["ga4_access"]["presence_status"], "unknown")
        self.assertEqual(by_type["search_console"]["presence_status"], "missing")
        self.assertEqual(by_type["monthly_report_snapshot"]["presence_status"], "present")
        self.assertIsNotNone(by_type["drive_root"]["source_ref_hash"])
        self.assertNotIn("@", json.dumps(rows))

    def test_client_health_assets_require_populated_roadmap_file_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self.make_fixture(Path(tmp))
            verification_path = paths.drive_folder_verifications
            verification_path.parent.mkdir(parents=True, exist_ok=True)
            verification_path.write_text(
                json.dumps(
                    {
                        "folders": [
                            {
                                "client_slug": "example-client",
                                "folder_id": "roadmapFolder12345",
                                "file_count": 1,
                                "populated_file_count": 1,
                                "content_validated_file_count": 1,
                                "latest_modified_date": "2026-05-20",
                                "verified_at": "2026-06-13T00:00:00Z",
                                "content_verified_at": "2026-06-13T00:05:00Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = parse_client_health_assets(
                paths,
                read_csv_rows(paths.monday_derived / "client_board_matrix.csv"),
                run_id="run-1",
                ingested_at="2026-06-12T00:00:00+00:00",
                snapshot_date="2026-06-12",
            )

        by_type = {row["asset_type"]: row for row in rows if row["client_slug"] == "example-client"}
        self.assertEqual(by_type["drive_roadmap_folder"]["presence_status"], "present")
        self.assertEqual(by_type["drive_roadmap_folder_verified"]["presence_status"], "present")
        self.assertEqual(by_type["drive_roadmap_files"]["presence_status"], "present")
        self.assertEqual(by_type["drive_roadmap_files"]["freshness_date"], "2026-05-20")
        self.assertIn("Drive MCP verification", by_type["drive_roadmap_files"]["notes"])
        self.assertEqual(by_type["drive_roadmap_content"]["presence_status"], "present")
        self.assertEqual(by_type["drive_roadmap_content"]["verification_level"], "bounded_content_validated")

    def test_client_health_assets_mark_failed_bounded_roadmap_validation_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self.make_fixture(Path(tmp))
            verification_path = paths.drive_folder_verifications
            verification_path.parent.mkdir(parents=True, exist_ok=True)
            verification_path.write_text(
                json.dumps(
                    {
                        "folders": [
                            {
                                "client_slug": "example-client",
                                "folder_id": "roadmapFolder12345",
                                "file_count": 1,
                                "populated_file_count": 1,
                                "content_validated_file_count": 0,
                                "content_failed_file_count": 1,
                                "latest_modified_date": "2026-05-20",
                                "verified_at": "2026-06-13T00:00:00Z",
                                "content_verified_at": "2026-06-13T00:05:00Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = parse_client_health_assets(
                paths,
                read_csv_rows(paths.monday_derived / "client_board_matrix.csv"),
                run_id="run-1",
                ingested_at="2026-06-12T00:00:00+00:00",
                snapshot_date="2026-06-12",
            )

        by_type = {row["asset_type"]: row for row in rows if row["client_slug"] == "example-client"}
        self.assertEqual(by_type["drive_roadmap_files"]["presence_status"], "present")
        self.assertEqual(by_type["drive_roadmap_content"]["presence_status"], "missing")
        self.assertIn("failed roadmap-shape checks", by_type["drive_roadmap_content"]["notes"])

    def test_client_health_assets_use_api_smoke_verification_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self.make_fixture(Path(tmp))
            verification_path = paths.api_smoke_verifications
            verification_path.parent.mkdir(parents=True, exist_ok=True)
            verification_path.write_text(
                json.dumps(
                    {
                        "checks": [
                            {
                                "client_slug": "example-client",
                                "source": "ga4",
                                "status": "succeeded",
                                "checked_at": "2026-06-13T00:00:00Z",
                                "date_end": "2026-06-12",
                                "rows_returned": 1,
                            },
                            {
                                "client_slug": "example-client",
                                "source": "gsc",
                                "status": "failed",
                                "checked_at": "2026-06-13T00:00:00Z",
                                "error_class": "RuntimeError",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = parse_client_health_assets(
                paths,
                read_csv_rows(paths.monday_derived / "client_board_matrix.csv"),
                run_id="run-1",
                ingested_at="2026-06-12T00:00:00+00:00",
                snapshot_date="2026-06-12",
            )

        by_type = {row["asset_type"]: row for row in rows if row["client_slug"] == "example-client"}
        self.assertEqual(by_type["ga4_access"]["presence_status"], "present")
        self.assertEqual(by_type["ga4_access"]["verification_level"], "api_smoke")
        self.assertEqual(by_type["ga4_access"]["freshness_date"], "2026-06-12")
        self.assertEqual(by_type["search_console_access"]["presence_status"], "missing")
        self.assertIn("error_class=RuntimeError", by_type["search_console_access"]["notes"])

    def test_client_health_assets_use_reporting_clients_only_and_resolve_board_aliases(self) -> None:
        active_clients = [
            ("acorn-rentals", "Acorn Rentals", "101"),
            ("avenue-hampers", "Avenue Hampers", "102"),
            ("ducati-melbourne", "Joe Rascal Ducati", "103"),
            ("joe-rascal-harley", "Joe Rascal Harley", "104"),
            ("little-shop-of-happiness", "Little Shop of Happiness", "105"),
            ("melani-the-label", "Melani the Label", "106"),
            ("salad-servers-direct", "Salad Servers Direct", "107"),
            ("shop-rongrong", "Shop Rongrong", "108"),
            ("travelkon", "TravelKon", "109"),
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SourcePaths(
                monday_hub=root / "monday-agency-hub",
                seo_automation=root / "SEO Automation",
                seo_reporting=root / "seo-reporting-platform",
                big_query=root / "Big Query",
            )
            reporting_clients = [
                {
                    "slug": slug,
                    "name": name,
                    "monday": {"boardId": board_id},
                    "ga4": {"property": f"properties/{board_id}"},
                    "searchConsole": {"properties": [f"https://{slug}.example/"]},
                    "seRanking": {"projectId": f"sr-{board_id}"},
                }
                for slug, name, board_id in active_clients
            ]
            write(paths.reporting_config / "clients.json", json.dumps({"clients": reporting_clients}))
            write(
                paths.monday_derived / "client_board_matrix.csv",
                "client_slug,client_name,client_board_id,client_board_name,board_kind,permissions,seo_execution_board_id,seo_execution_board_name,notes\n"
                "acorn-car-rentals,Acorn Car Rentals,101,Acorn Car Rentals,share,owners,5026765957,SEO Tasks,alias\n"
                "joe-rascal-ducati,Joe Rascal Ducati,103,Joe Rascal Ducati,share,owners,5026765957,SEO Tasks,alias\n"
                "salad-servers,Salad Servers,107,Salad Servers,share,everyone,5026765957,SEO Tasks,alias\n"
                "heiych,HEIYCH,999,HEIYCH,share,everyone,5026765957,SEO Tasks,board-only\n",
            )
            for slug, name, board_id in active_clients:
                write(
                    paths.seo_clients / f"{slug}.json",
                    json.dumps(
                        {
                            "client": name,
                            "brand_display_name": name,
                            "ga4_property": f"properties/{board_id}",
                            "monday": {"board_id": board_id},
                            "drive": {
                                "client_folder_id": f"drive-root-{board_id}",
                                "folders": {
                                    "02_roadmap": f"roadmap-{board_id}",
                                    "05_content": f"content-{board_id}",
                                    "07_reports": f"reports-{board_id}",
                                },
                            },
                            "se_ranking": {"project_id": f"sr-{board_id}"},
                        }
                    ),
                )
                write(paths.seo_clients / f"{slug}.md", f"# {name}\n")
                write(paths.seo_clients / f"{slug}-timeline.md", "| Date | Task |\n")
            write(paths.seo_clients / "agents-digital.md", "# Agents Digital\n")
            write(paths.seo_clients / "bestvpn.json", json.dumps({"client": "BestVPN"}))
            write(paths.seo_clients / "travelkon-internal-linking-map.md", "# TravelKon map\n")

            rows = parse_client_health_assets(
                paths,
                read_csv_rows(paths.monday_derived / "client_board_matrix.csv"),
                run_id="run-1",
                ingested_at="2026-06-12T00:00:00+00:00",
                snapshot_date="2026-06-12",
            )

        slugs = {row["client_slug"] for row in rows}
        self.assertEqual(slugs, {slug for slug, _, _ in active_clients})
        self.assertEqual(len(rows), 9 * 24)
        self.assertNotIn("agents-digital", slugs)
        self.assertNotIn("bestvpn", slugs)
        self.assertNotIn("heiych", slugs)
        self.assertNotIn("travelkon-internal-linking-map", slugs)
        monday_refs = {
            row["client_slug"]: row["source_ref"]
            for row in rows
            if row["asset_type"] == "monday_board"
        }
        self.assertEqual(monday_refs["acorn-rentals"], "101")
        self.assertEqual(monday_refs["ducati-melbourne"], "103")
        self.assertEqual(monday_refs["salad-servers-direct"], "107")

    def test_client_health_check_sql_rolls_up_asset_inventory(self) -> None:
        sql = client_health_check_sql("project", "memory", "reporting")

        self.assertIn("client_health_assets", sql)
        self.assertIn("client_roadmap_items", sql)
        self.assertIn("missing_required_json", sql)
        self.assertIn("health_status", sql)
        self.assertIn("has_roadmap_files", sql)
        self.assertIn("has_roadmap_content_validated", sql)
        self.assertIn("has_ga4_access", sql)

    def test_comms_summary_normalizer_accepts_safe_summary_and_hashes_refs(self) -> None:
        row = normalize_comms_summary_row(
            {
                "week_start": "2026-06-01",
                "week_end": "2026-06-07",
                "client_slug": "Example Client",
                "client_name": "Example Client",
                "channel": "monday",
                "category": "approval",
                "summary": "Client approved the draft report and asked the team to continue with the agreed next fixes.",
                "recommended_action": "Schedule the agreed fixes for next week.",
                "owner_hint": "Laurence",
                "due_hint": "next week",
                "needs_reply": False,
                "blocked": False,
                "waiting_on_client": False,
                "waiting_on_us": True,
                "stale_followup": False,
                "urgency": "medium",
                "sentiment": "positive",
                "source_event_count": 2,
                "source_refs": ["monday-update-123", "gmail-message-456"],
                "thread_ref": "monday-thread-123",
                "thread_status": "waiting_on_us",
                "latest_event_at": "2026-06-12T01:00:00Z",
                "confidence": 0.82,
            },
            run_id="run-1",
            created_at="2026-06-12T00:00:00+00:00",
        )

        self.assertEqual(row["client_slug"], "example-client")
        self.assertEqual(row["validation_status"], "validated")
        self.assertEqual(len(row["source_ref_hashes_json"]), 2)
        self.assertNotIn("monday-update-123", row["source_ref_hashes_json"])
        self.assertEqual(row["thread_status"], "waiting_on_us")
        self.assertRegex(row["thread_ref_hash"], r"^[a-f0-9]{32}$")
        self.assertEqual(row["latest_event_at"], "2026-06-12T01:00:00+00:00")

    def test_comms_summary_normalizer_rejects_raw_private_shapes(self) -> None:
        base = {
            "week_start": "2026-06-01",
            "week_end": "2026-06-07",
            "client_slug": "example-client",
            "client_name": "Example Client",
            "channel": "gmail",
            "category": "client_conversation",
            "summary": "Client asked for a status update on the migration.",
            "source_event_count": 1,
            "confidence": 0.7,
        }
        unsafe_cases = [
            {"summary": "From: person@example.com\nSubject: Project\nPlease send the report."},
            {"summary": "Client wrote \"this is a very long direct quote with many words that should be treated as raw communication content and rejected immediately\"."},
            {"summary": "Call the client on 0412 345 678 about this."},
            {"recommended_action": "Use api_key=secret to fetch the data."},
            {"owner_hint": "person@example.com"},
            {"resolution_summary": "From: person@example.com\nSubject: Raw body"},
        ]
        for override in unsafe_cases:
            with self.subTest(override=override):
                payload = {**base, **override}
                with self.assertRaises(ValueError):
                    normalize_comms_summary_row(payload, run_id="run-1", created_at="2026-06-12T00:00:00+00:00")

    def test_parse_comms_summary_jsonl_reports_line_numbers(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "summaries.jsonl"
            write(
                path,
                json.dumps(
                    {
                        "client_slug": "example-client",
                        "client_name": "Example Client",
                        "channel": "outlook",
                        "category": "client_conversation",
                        "summary": "Safe paraphrased update with no raw private content.",
                        "source_event_count": 1,
                        "confidence": 0.6,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "client_slug": "example-client",
                        "client_name": "Example Client",
                        "channel": "outlook",
                        "category": "client_conversation",
                        "summary": "From: person@example.com\nSubject: Raw body",
                        "source_event_count": 1,
                        "confidence": 0.6,
                    }
                ),
            )

            with self.assertRaisesRegex(ValueError, "line 2"):
                parse_comms_summary_jsonl(
                    path,
                    run_id="run-1",
                    created_at="2026-06-12T00:00:00+00:00",
                    default_week_start="2026-06-01",
                    default_week_end="2026-06-07",
                )

    def test_comms_reporting_mart_uses_capped_runner(self) -> None:
        runner = FakeRunner()

        statuses = build_comms_reporting_marts(runner, test_config())

        self.assertEqual(statuses["client_comms_attention"], "succeeded")
        self.assertEqual(statuses["client_comms_history"], "succeeded")
        purposes = {query["purpose"] for query in runner.queries}
        self.assertIn("comms-memory: build client_comms_attention", purposes)
        self.assertIn("comms-memory: build client_comms_history", purposes)

    def test_comms_attention_sql_keeps_latest_unresolved_thread_state_only(self) -> None:
        sql = client_comms_attention_sql("project", "memory", "reporting")

        self.assertIn("latest_thread_state", sql)
        self.assertIn("PARTITION BY client_slug, effective_thread_ref_hash", sql)
        self.assertIn("effective_thread_status NOT IN ('resolved', 'fyi')", sql)
        self.assertIn("effective_thread_status = 'waiting_on_us'", sql)
        self.assertIn("effective_thread_status = 'waiting_on_client'", sql)
        self.assertNotIn("'positive_momentum' AS signal_type", sql)

    def test_roadmap_item_normalizer_accepts_safe_agreed_work(self) -> None:
        row = normalize_roadmap_item_row(
            {
                "planned_month": "2026-05",
                "client_slug": "Little Shop of Happiness",
                "client_name": "Little Shop of Happiness",
                "item_title": "Refresh hampers Melbourne collection content",
                "work_type": "collection",
                "priority": "high",
                "planned_status": "in_progress",
                "owner_hint": "Laurence",
                "due_date": "2026-05-24",
                "target_url": "/collections/hampers-melbourne",
                "keyword_theme": "gift hampers Melbourne",
                "notes_summary": "Agreed May collection refresh from the roadmap.",
                "source_type": "drive_sheet",
                "source_title": "May roadmap sheet",
                "drive_file_id": "1zOP2c2FNrrprS3iZZqfhils8yB7mNGdYgewIAkzwqxg",
                "drive_folder_id": "1XoCCXy09qu02MFMUh4EjjmBUvb6ejm8z",
                "source_ref": "little-shop-roadmap-row-12",
                "source_row_index": 12,
                "completion_evidence_type": "timeline",
                "completion_evidence_ref": "little-shop-of-happiness-timeline:19",
                "completion_summary": "Drafts and Monday items were created for the agreed collection refresh.",
                "completion_confidence": 0.9,
            },
            run_id="run-1",
            ingested_at="2026-06-12T00:00:00+00:00",
        )

        self.assertEqual(row["client_slug"], "little-shop-of-happiness")
        self.assertEqual(row["planned_month"], "2026-05-01")
        self.assertEqual(row["period_id"], "2026-05")
        self.assertEqual(row["work_type"], "collection")
        self.assertRegex(row["roadmap_item_id"], r"^[a-f0-9]{32}$")
        self.assertRegex(row["source_ref_hash"], r"^[a-f0-9]{32}$")
        self.assertEqual(row["validation_status"], "validated")

    def test_roadmap_item_normalizer_rejects_private_or_raw_shapes(self) -> None:
        base = {
            "planned_month": "2026-05",
            "client_slug": "example-client",
            "client_name": "Example Client",
            "item_title": "Create collection brief",
            "work_type": "collection",
            "source_type": "manual",
            "completion_confidence": 0.5,
        }
        unsafe_cases = [
            {"notes_summary": "From: person@example.com\nSubject: Raw body"},
            {"item_title": "Use api_key=secret for the crawl"},
            {"owner_hint": "person@example.com"},
            {"notes_summary": "Call the client on 0412 345 678 before publishing."},
            {"target_url": "javascript:alert(1)"},
        ]
        for override in unsafe_cases:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    normalize_roadmap_item_row(
                        {**base, **override},
                        run_id="run-1",
                        ingested_at="2026-06-12T00:00:00+00:00",
                    )

    def test_parse_roadmap_item_jsonl_and_sources_report_line_numbers(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "roadmap.jsonl"
            write(
                path,
                json.dumps(
                    {
                        "client_slug": "example-client",
                        "client_name": "Example Client",
                        "item_title": "Publish June blog",
                        "planned_month": "2026-06",
                        "source_type": "drive_sheet",
                        "source_ref": "roadmap-row-1",
                        "completion_confidence": 0.2,
                    }
                )
                + "\n",
            )

            rows = parse_roadmap_item_jsonl(path, run_id="run-1", ingested_at="2026-06-12T00:00:00+00:00")
            sources = roadmap_source_rows_from_items(rows)

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_status"], "active")

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "roadmap.jsonl"
            write(
                path,
                json.dumps(
                    {
                        "client_slug": "example-client",
                        "client_name": "Example Client",
                        "item_title": "Publish June blog",
                        "planned_month": "2026-06",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "client_slug": "example-client",
                        "client_name": "Example Client",
                        "item_title": "From: person@example.com\nSubject: Raw",
                        "planned_month": "2026-06",
                    }
                ),
            )
            with self.assertRaisesRegex(ValueError, "line 2"):
                parse_roadmap_item_jsonl(path, run_id="run-1", ingested_at="2026-06-12T00:00:00+00:00")

    def test_roadmap_reporting_marts_use_capped_runner(self) -> None:
        runner = FakeRunner()

        statuses = build_roadmap_reporting_marts(runner, test_config())

        self.assertEqual(statuses["client_roadmap_current"], "succeeded")
        self.assertEqual(statuses["client_roadmap_monthly_completion"], "succeeded")
        purposes = {query["purpose"] for query in runner.queries}
        self.assertIn("roadmap-memory: build client_roadmap_current", purposes)
        self.assertIn("roadmap-memory: build client_roadmap_monthly_completion", purposes)

    def test_roadmap_current_sql_matches_completion_evidence(self) -> None:
        sql = client_roadmap_current_sql("project", "memory", "reporting")

        self.assertIn("latest_items", sql)
        self.assertIn("client_delivery_timeline", sql)
        self.assertIn("completion_evidence_type", sql)
        self.assertIn("delivery_status", sql)
        self.assertIn("PARTITION BY planned_month", sql)


if __name__ == "__main__":
    unittest.main()
