#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import csv
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.schema import (  # noqa: E402
    CLIENT_CRAWL_EXPORT_ROWS_SCHEMA,
    CLIENT_CRAWL_ISSUE_ROWS_SCHEMA,
    CLIENT_CRAWL_LINK_ROWS_SCHEMA,
    CLIENT_CRAWL_RUNS_SCHEMA,
    CLIENT_CRAWL_URL_SNAPSHOTS_SCHEMA,
    ensure_crawl_memory_tables,
)
MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_]")
RUN_FIELDS = [name for name, _field_type, _mode in CLIENT_CRAWL_RUNS_SCHEMA]
URL_FIELDS = [name for name, _field_type, _mode in CLIENT_CRAWL_URL_SNAPSHOTS_SCHEMA]
ISSUE_FIELDS = [name for name, _field_type, _mode in CLIENT_CRAWL_ISSUE_ROWS_SCHEMA]
LINK_FIELDS = [name for name, _field_type, _mode in CLIENT_CRAWL_LINK_ROWS_SCHEMA]
EXPORT_FIELDS = [name for name, _field_type, _mode in CLIENT_CRAWL_EXPORT_ROWS_SCHEMA]

FORBIDDEN_NAME_PARTS = (
    "raw_html",
    "rendered_html",
    "visible_text",
    "page_text",
    "page_content",
    "screenshot",
    "screenshots",
    "cookies",
    "request_body",
    "response_body",
    "request_headers",
    "response_headers",
    "all_http_request_headers",
    "all_http_response_headers",
    "dbseospider",
)
FORBIDDEN_HEADER_PARTS = (
    "raw html",
    "rendered html",
    "visible text",
    "request body",
    "response body",
)


@dataclass(frozen=True)
class CrawlExportMetadata:
    export_dir: Path
    client_slug: str
    client_name: str
    crawl_id: str
    run_id: str
    crawl_date: date
    crawl_trigger: str
    crawl_scope: str
    scope_ref: str | None
    start_url: str | None
    min_urls: int
    ingested_at: str


@dataclass
class CrawlExportPayload:
    run_row: dict[str, Any]
    url_rows: list[dict[str, Any]]
    issue_rows: list[dict[str, Any]]
    link_rows: list[dict[str, Any]]
    export_rows: list[dict[str, Any]]
    row_counts: dict[str, int]
    blocked_files: list[str]
    coverage_valid: bool


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Env file does not exist: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key not in SAFE_ENV_KEYS:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if key == "GOOGLE_APPLICATION_CREDENTIALS":
            credential_path = Path(os.path.expanduser(os.path.expandvars(cleaned)))
            if not credential_path.is_absolute():
                credential_path = path.parent / credential_path
            cleaned = str(credential_path.resolve())
        os.environ[key] = cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load full structured Screaming Frog CSV/report exports into BigQuery crawl memory.")
    parser.add_argument("--export-dir", required=True, help="Screaming Frog export directory containing CSV/report files.")
    parser.add_argument("--client-slug", required=True)
    parser.add_argument("--client-name")
    parser.add_argument("--crawl-id", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--crawl-date", help="YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--crawl-trigger", required=True, choices=("monthly_baseline", "post_task"))
    parser.add_argument("--crawl-scope", required=True, choices=("full_site", "partial_scope"))
    parser.add_argument("--scope-ref", help="Required for partial_scope; describes the affected URL, task, or section.")
    parser.add_argument("--start-url")
    parser.add_argument("--min-urls", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-bigquery", action="store_true")
    parser.add_argument("--ensure-tables", action="store_true")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--load-env")
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(MELBOURNE_TIMEZONE).isoformat()


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def normalise_slug_title(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


def safe_suffix(value: str) -> str:
    return SAFE_ID_RE.sub("_", value)[:80].strip("_") or "screaming_frog_export"


def export_name_for(path: Path, export_dir: Path) -> str:
    rel = path.relative_to(export_dir).with_suffix("")
    return "__".join(rel.parts)


def normalised_file_key(path: Path, export_dir: Path) -> str:
    return str(path.relative_to(export_dir)).lower().replace("\\", "/")


def is_forbidden_file(path: Path, export_dir: Path, headers: Iterable[str] | None = None) -> bool:
    key = normalised_file_key(path, export_dir)
    if any(part in key for part in FORBIDDEN_NAME_PARTS):
        return True
    if headers:
        header_text = " | ".join(headers).lower()
        return any(part in header_text for part in FORBIDDEN_HEADER_PARTS)
    return False


def get_first(row: dict[str, Any], *names: str) -> Any:
    lower = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name in row and row[name] not in ("", None):
            return row[name]
        value = lower.get(name.lower())
        if value not in ("", None):
            return value
    return None


def to_int(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return None


def to_bool(value: Any) -> bool | None:
    if value in ("", None):
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "indexable"}:
        return True
    if text in {"false", "no", "n", "0", "non-indexable", "nonindexable"}:
        return False
    return None


def url_hash(url: Any) -> str | None:
    if not url:
        return None
    return hashlib.sha256(str(url).encode("utf-8")).hexdigest()


def source_ref_hash(crawl_id: str, source_file: str, row_number: int, raw_row: dict[str, Any]) -> str:
    payload = json.dumps(raw_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{crawl_id}|{source_file}|{row_number}|{payload}".encode("utf-8")).hexdigest()


def common_detail(meta: CrawlExportMetadata, export_name: str, source_file: str, row_number: int, raw_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "crawl_id": meta.crawl_id,
        "run_id": meta.run_id,
        "crawl_date": meta.crawl_date.isoformat(),
        "ingested_at": meta.ingested_at,
        "client_slug": meta.client_slug,
        "client_name": meta.client_name,
        "export_name": export_name,
        "source_file": source_file,
        "row_number": row_number,
        "raw_row_json": raw_row,
        "source_ref_hash": source_ref_hash(meta.crawl_id, source_file, row_number, raw_row),
        "retention_expires_on": add_months(meta.crawl_date, 18).isoformat(),
    }


def export_row(meta: CrawlExportMetadata, export_name: str, source_file: str, row_number: int, raw_row: dict[str, Any]) -> dict[str, Any]:
    row = common_detail(meta, export_name, source_file, row_number, raw_row)
    row["primary_url"] = get_first(raw_row, "Address", "Source", "Destination", "Final Address", "URL")
    row["row_type"] = export_name
    return {field: row.get(field) for field in EXPORT_FIELDS}


def url_snapshot_row(meta: CrawlExportMetadata, export_name: str, source_file: str, row_number: int, raw_row: dict[str, Any]) -> dict[str, Any]:
    address = get_first(raw_row, "Address", "URL")
    title = get_first(raw_row, "Title 1", "Title")
    description = get_first(raw_row, "Meta Description 1", "Meta Description")
    h1 = get_first(raw_row, "H1-1", "H1")
    canonical = get_first(raw_row, "Canonical Link Element 1", "Canonical")
    status_code = to_int(get_first(raw_row, "Status Code", "Status"))
    indexability = get_first(raw_row, "Indexability")
    row = {
        **common_detail(meta, export_name, source_file, row_number, raw_row),
        "url": address,
        "url_hash": url_hash(address),
        "content_type": get_first(raw_row, "Content Type"),
        "status_code": status_code,
        "status": get_first(raw_row, "Status"),
        "indexability": indexability,
        "indexability_status": get_first(raw_row, "Indexability Status"),
        "title": title,
        "title_length": to_int(get_first(raw_row, "Title 1 Length", "Title Length")),
        "meta_description": description,
        "meta_description_length": to_int(get_first(raw_row, "Meta Description 1 Length", "Meta Description Length")),
        "h1": h1,
        "h1_length": to_int(get_first(raw_row, "H1-1 Length", "H1 Length")),
        "canonical": canonical,
        "robots": get_first(raw_row, "Meta Robots 1", "Meta Robots"),
        "word_count": to_int(get_first(raw_row, "Word Count")),
        "size_bytes": to_int(get_first(raw_row, "Size (Bytes)", "Size")),
        "crawl_depth": to_int(get_first(raw_row, "Crawl Depth")),
        "inlinks": to_int(get_first(raw_row, "Inlinks")),
        "outlinks": to_int(get_first(raw_row, "Outlinks")),
        "is_indexable": to_bool(indexability),
        "has_missing_title": not bool(title),
        "has_duplicate_title": False,
        "has_missing_meta_description": not bool(description),
        "has_duplicate_meta_description": False,
        "has_missing_h1": not bool(h1),
        "has_duplicate_h1": False,
        "has_canonical_issue": False,
        "has_low_content": False,
    }
    return {field: row.get(field) for field in URL_FIELDS}


def issue_row(meta: CrawlExportMetadata, export_name: str, source_file: str, row_number: int, raw_row: dict[str, Any]) -> dict[str, Any]:
    row = {
        **common_detail(meta, export_name, source_file, row_number, raw_row),
        "issue_name": get_first(raw_row, "Issue Name", "Issue", "Name"),
        "issue_type": get_first(raw_row, "Issue Type", "Type"),
        "issue_priority": get_first(raw_row, "Issue Priority", "Priority"),
        "issue_count": to_int(get_first(raw_row, "URLs", "Occurrences", "Count")),
        "address": get_first(raw_row, "Address", "URL"),
        "source_url": get_first(raw_row, "Source"),
        "destination_url": get_first(raw_row, "Destination"),
        "status_code": to_int(get_first(raw_row, "Status Code")),
        "indexability": get_first(raw_row, "Indexability"),
        "indexability_status": get_first(raw_row, "Indexability Status"),
    }
    return {field: row.get(field) for field in ISSUE_FIELDS}


def link_row(meta: CrawlExportMetadata, export_name: str, source_file: str, row_number: int, raw_row: dict[str, Any]) -> dict[str, Any]:
    row = {
        **common_detail(meta, export_name, source_file, row_number, raw_row),
        "link_type": get_first(raw_row, "Type"),
        "source_url": get_first(raw_row, "Source"),
        "destination_url": get_first(raw_row, "Destination"),
        "anchor": get_first(raw_row, "Anchor"),
        "alt_text": get_first(raw_row, "Alt Text"),
        "status_code": to_int(get_first(raw_row, "Status Code")),
        "status": get_first(raw_row, "Status"),
        "crawlability": get_first(raw_row, "Crawlability"),
        "follow": get_first(raw_row, "Follow"),
        "path_type": get_first(raw_row, "Path Type"),
        "link_position": get_first(raw_row, "Link Position"),
    }
    return {field: row.get(field) for field in LINK_FIELDS}


def classify_export(path: Path, export_dir: Path) -> set[str]:
    key = normalised_file_key(path, export_dir)
    kinds: set[str] = {"export"}
    if key == "internal_all.csv":
        kinds.add("url")
    if key.endswith("issues_overview_report.csv") or key.startswith("issues_reports/"):
        kinds.add("issue")
    if "inlinks" in key or "outlinks" in key:
        kinds.add("link")
    return kinds


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [normalise_raw_row(dict(row)) for row in reader]
    return headers, rows


def normalise_raw_row(row: dict[Any, Any]) -> dict[str, Any]:
    normalised: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            normalised["__extra__"] = value
        else:
            normalised[str(key)] = value
    return normalised


def build_export_payload(meta: CrawlExportMetadata) -> CrawlExportPayload:
    if meta.crawl_scope == "partial_scope" and not meta.scope_ref:
        raise ValueError("--scope-ref is required when --crawl-scope=partial_scope")
    csv_paths = sorted(path for path in meta.export_dir.rglob("*.csv") if path.is_file())
    if not csv_paths:
        raise ValueError(f"no CSV exports found in {meta.export_dir}")

    url_rows: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    export_rows: list[dict[str, Any]] = []
    row_counts: dict[str, int] = {}
    blocked_files: list[str] = []
    status_counts = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    indexable_count = 0
    nonindexable_count = 0

    for path in csv_paths:
        headers, rows = read_csv_rows(path)
        rel_file = normalised_file_key(path, meta.export_dir)
        if is_forbidden_file(path, meta.export_dir, headers):
            blocked_files.append(rel_file)
            continue
        export_name = export_name_for(path, meta.export_dir)
        row_counts[rel_file] = len(rows)
        kinds = classify_export(path, meta.export_dir)
        for index, raw_row in enumerate(rows, start=1):
            export_rows.append(export_row(meta, export_name, rel_file, index, raw_row))
            if "url" in kinds:
                mapped = url_snapshot_row(meta, export_name, rel_file, index, raw_row)
                url_rows.append(mapped)
                status_code = mapped.get("status_code")
                if isinstance(status_code, int):
                    if 200 <= status_code <= 299:
                        status_counts["2xx"] += 1
                    elif 300 <= status_code <= 399:
                        status_counts["3xx"] += 1
                    elif 400 <= status_code <= 499:
                        status_counts["4xx"] += 1
                    elif status_code >= 500:
                        status_counts["5xx"] += 1
                if str(mapped.get("indexability") or "").lower() == "indexable":
                    indexable_count += 1
                elif mapped.get("indexability"):
                    nonindexable_count += 1
            if "issue" in kinds:
                issue_rows.append(issue_row(meta, export_name, rel_file, index, raw_row))
            if "link" in kinds:
                link_rows.append(link_row(meta, export_name, rel_file, index, raw_row))

    internal_count = row_counts.get("internal_all.csv", len(url_rows))
    derived_start_url = meta.start_url
    if not derived_start_url and url_rows:
        derived_start_url = url_rows[0].get("url")
    coverage_valid = meta.crawl_scope == "partial_scope" or internal_count >= meta.min_urls
    crawl_status = "completed" if coverage_valid else "coverage_failed"
    issue_summary_rows = [row for row in issue_rows if row.get("source_file") == "issues_overview_report.csv"]
    run_row = {
        "crawl_id": meta.crawl_id,
        "run_id": meta.run_id,
        "crawl_date": meta.crawl_date.isoformat(),
        "ingested_at": meta.ingested_at,
        "client_slug": meta.client_slug,
        "client_name": meta.client_name,
        "crawl_trigger": meta.crawl_trigger,
        "trigger_ref": meta.scope_ref,
        "crawler": "screaming_frog_cli_export",
        "crawl_scope": meta.crawl_scope,
        "start_url": derived_start_url,
        "config_ref": str(meta.export_dir),
        "robots_respected": True,
        "crawl_status": crawl_status,
        "pages_crawled": internal_count,
        "internal_html_urls": internal_count,
        "indexable_html_urls": indexable_count or None,
        "nonindexable_html_urls": nonindexable_count or None,
        "status_2xx_urls": status_counts["2xx"],
        "status_3xx_urls": status_counts["3xx"],
        "status_4xx_urls": status_counts["4xx"],
        "status_5xx_urls": status_counts["5xx"],
        "missing_title_urls": issue_count(issue_summary_rows, "Page Titles: Missing"),
        "duplicate_title_urls": issue_count(issue_summary_rows, "Page Titles: Duplicate"),
        "missing_meta_description_urls": issue_count(issue_summary_rows, "Meta Description: Missing"),
        "duplicate_meta_description_urls": issue_count(issue_summary_rows, "Meta Description: Duplicate"),
        "missing_h1_urls": issue_count(issue_summary_rows, "H1: Missing"),
        "duplicate_h1_urls": issue_count(issue_summary_rows, "H1: Duplicate"),
        "canonical_issue_urls": sum_issue_counts(issue_summary_rows, ("Canonical",)),
        "low_content_urls": issue_count(issue_summary_rows, "Content: Low Content Pages"),
        "issue_counts_json": {
            "storage_model": "full_csv_fields_with_raw_row_json",
            "coverage_status": "valid" if coverage_valid else "coverage_failed",
            "min_urls": meta.min_urls,
            "csv_file_count": len(csv_paths),
            "loaded_csv_file_count": len(row_counts),
            "blocked_files": blocked_files,
            "row_counts_by_export": row_counts,
            "top_issues": issue_summary_rows[:15],
            "raw_content_exported": False,
            "visible_text_exported": False,
        },
        "export_manifest_path": str(meta.export_dir),
        "export_drive_file_id": None,
        "source_ref_hash": directory_hash(meta.export_dir, row_counts),
        "retention_expires_on": add_months(meta.crawl_date, 18).isoformat(),
    }
    run_row = {field: run_row.get(field) for field in RUN_FIELDS}
    if not coverage_valid:
        url_rows = []
        issue_rows = []
        link_rows = []
        export_rows = []
    return CrawlExportPayload(run_row, url_rows, issue_rows, link_rows, export_rows, row_counts, blocked_files, coverage_valid)


def issue_count(rows: list[dict[str, Any]], exact_name: str) -> int | None:
    for row in rows:
        if row.get("issue_name") == exact_name:
            return row.get("issue_count")
    return None


def sum_issue_counts(rows: list[dict[str, Any]], contains: tuple[str, ...]) -> int | None:
    total = 0
    matched = False
    for row in rows:
        name = str(row.get("issue_name") or "")
        if any(part in name for part in contains):
            total += int(row.get("issue_count") or 0)
            matched = True
    return total if matched else None


def directory_hash(export_dir: Path, row_counts: dict[str, int]) -> str:
    digest = hashlib.sha256()
    digest.update(str(export_dir.resolve()).encode("utf-8"))
    digest.update(json.dumps(row_counts, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def quote_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"unsafe identifier: {name}")
    return f"`{name}`"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_runs_merge_sql(config: BigQueryCostConfig, staging_table_id: str) -> str:
    target = config.table_id(config.memory_dataset, "client_crawl_runs")
    update_columns = [column for column in RUN_FIELDS if column != "crawl_id"]
    update_clause = ", ".join(f"T.{quote_name(column)} = S.{quote_name(column)}" for column in update_columns)
    insert_columns = ", ".join(quote_name(column) for column in RUN_FIELDS)
    insert_values = ", ".join(f"S.{quote_name(column)}" for column in RUN_FIELDS)
    return f"""
MERGE `{target}` AS T
USING `{staging_table_id}` AS S
ON T.`crawl_id` = S.`crawl_id`
WHEN MATCHED THEN UPDATE SET {update_clause}
WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})
""".strip()


def build_delete_details_sql(config: BigQueryCostConfig, table_name: str, crawl_id: str) -> str:
    target = config.table_id(config.memory_dataset, table_name)
    return f"DELETE FROM `{target}` WHERE crawl_id = {sql_string(crawl_id)}"


def build_latest_merge_sql(config: BigQueryCostConfig, client_slug: str) -> str:
    target = config.table_id(config.reporting_dataset, "client_crawl_latest")
    source = config.table_id(config.memory_dataset, "client_crawl_runs")
    return f"""
MERGE `{target}` AS T
USING (
  SELECT
    crawl_date, crawl_id, client_slug, client_name, crawl_trigger, crawler, start_url, crawl_status,
    pages_crawled, indexable_html_urls, nonindexable_html_urls, status_4xx_urls, status_5xx_urls,
    missing_title_urls, duplicate_title_urls, missing_meta_description_urls, missing_h1_urls,
    canonical_issue_urls, low_content_urls, issue_counts_json, export_manifest_path, export_drive_file_id,
    source_ref_hash
  FROM `{source}`
  WHERE client_slug = {sql_string(client_slug)} AND crawl_status != 'coverage_failed'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY crawl_date DESC, ingested_at DESC) = 1
) AS S
ON T.`client_slug` = S.`client_slug`
WHEN MATCHED THEN UPDATE SET
  crawl_date = S.crawl_date, crawl_id = S.crawl_id, client_name = S.client_name,
  crawl_trigger = S.crawl_trigger, crawler = S.crawler, start_url = S.start_url,
  crawl_status = S.crawl_status, pages_crawled = S.pages_crawled,
  indexable_html_urls = S.indexable_html_urls, nonindexable_html_urls = S.nonindexable_html_urls,
  status_4xx_urls = S.status_4xx_urls, status_5xx_urls = S.status_5xx_urls,
  missing_title_urls = S.missing_title_urls, duplicate_title_urls = S.duplicate_title_urls,
  missing_meta_description_urls = S.missing_meta_description_urls, missing_h1_urls = S.missing_h1_urls,
  canonical_issue_urls = S.canonical_issue_urls, low_content_urls = S.low_content_urls,
  issue_counts_json = S.issue_counts_json, export_manifest_path = S.export_manifest_path,
  export_drive_file_id = S.export_drive_file_id, source_ref_hash = S.source_ref_hash
WHEN NOT MATCHED THEN INSERT (
  crawl_date, crawl_id, client_slug, client_name, crawl_trigger, crawler, start_url, crawl_status,
  pages_crawled, indexable_html_urls, nonindexable_html_urls, status_4xx_urls, status_5xx_urls,
  missing_title_urls, duplicate_title_urls, missing_meta_description_urls, missing_h1_urls,
  canonical_issue_urls, low_content_urls, issue_counts_json, export_manifest_path, export_drive_file_id,
  source_ref_hash
) VALUES (
  S.crawl_date, S.crawl_id, S.client_slug, S.client_name, S.crawl_trigger, S.crawler, S.start_url, S.crawl_status,
  S.pages_crawled, S.indexable_html_urls, S.nonindexable_html_urls, S.status_4xx_urls, S.status_5xx_urls,
  S.missing_title_urls, S.duplicate_title_urls, S.missing_meta_description_urls, S.missing_h1_urls,
  S.canonical_issue_urls, S.low_content_urls, S.issue_counts_json, S.export_manifest_path, S.export_drive_file_id,
  S.source_ref_hash
)
""".strip()


def build_comparison_merge_sql(config: BigQueryCostConfig, crawl_id: str) -> str:
    target = config.table_id(config.reporting_dataset, "client_crawl_comparison")
    source = config.table_id(config.memory_dataset, "client_crawl_runs")
    return f"""
MERGE `{target}` AS T
USING (
  WITH current_run AS (
    SELECT * FROM `{source}` WHERE crawl_id = {sql_string(crawl_id)} AND crawl_status != 'coverage_failed'
  ),
  previous_run AS (
    SELECT p.*
    FROM `{source}` p
    JOIN current_run c USING (client_slug)
    WHERE p.crawl_id != c.crawl_id AND p.crawl_status != 'coverage_failed'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY p.client_slug ORDER BY p.crawl_date DESC, p.ingested_at DESC) = 1
  )
  SELECT
    c.crawl_id AS comparison_id,
    c.client_slug,
    c.client_name,
    c.crawl_id AS current_crawl_id,
    p.crawl_id AS previous_crawl_id,
    c.crawl_date AS current_crawl_date,
    p.crawl_date AS previous_crawl_date,
    c.crawl_trigger,
    c.pages_crawled - p.pages_crawled AS pages_crawled_delta,
    c.indexable_html_urls - p.indexable_html_urls AS indexable_html_urls_delta,
    c.status_4xx_urls - p.status_4xx_urls AS status_4xx_urls_delta,
    c.status_5xx_urls - p.status_5xx_urls AS status_5xx_urls_delta,
    c.missing_title_urls - p.missing_title_urls AS missing_title_urls_delta,
    c.missing_meta_description_urls - p.missing_meta_description_urls AS missing_meta_description_urls_delta,
    c.missing_h1_urls - p.missing_h1_urls AS missing_h1_urls_delta,
    c.canonical_issue_urls - p.canonical_issue_urls AS canonical_issue_urls_delta,
    c.low_content_urls - p.low_content_urls AS low_content_urls_delta,
    IF(p.crawl_id IS NULL, 'no_previous_crawl', 'ready') AS comparison_status,
    c.source_ref_hash,
    DATE_ADD(c.crawl_date, INTERVAL 18 MONTH) AS retention_expires_on
  FROM current_run c
  LEFT JOIN previous_run p USING (client_slug)
) AS S
ON T.`comparison_id` = S.`comparison_id`
WHEN MATCHED THEN UPDATE SET
  client_slug = S.client_slug, client_name = S.client_name, current_crawl_id = S.current_crawl_id,
  previous_crawl_id = S.previous_crawl_id, current_crawl_date = S.current_crawl_date,
  previous_crawl_date = S.previous_crawl_date, crawl_trigger = S.crawl_trigger,
  pages_crawled_delta = S.pages_crawled_delta, indexable_html_urls_delta = S.indexable_html_urls_delta,
  status_4xx_urls_delta = S.status_4xx_urls_delta, status_5xx_urls_delta = S.status_5xx_urls_delta,
  missing_title_urls_delta = S.missing_title_urls_delta,
  missing_meta_description_urls_delta = S.missing_meta_description_urls_delta,
  missing_h1_urls_delta = S.missing_h1_urls_delta,
  canonical_issue_urls_delta = S.canonical_issue_urls_delta,
  low_content_urls_delta = S.low_content_urls_delta, comparison_status = S.comparison_status,
  source_ref_hash = S.source_ref_hash, retention_expires_on = S.retention_expires_on
WHEN NOT MATCHED THEN INSERT (
  comparison_id, client_slug, client_name, current_crawl_id, previous_crawl_id,
  current_crawl_date, previous_crawl_date, crawl_trigger, pages_crawled_delta,
  indexable_html_urls_delta, status_4xx_urls_delta, status_5xx_urls_delta,
  missing_title_urls_delta, missing_meta_description_urls_delta, missing_h1_urls_delta,
  canonical_issue_urls_delta, low_content_urls_delta, comparison_status, source_ref_hash,
  retention_expires_on
) VALUES (
  S.comparison_id, S.client_slug, S.client_name, S.current_crawl_id, S.previous_crawl_id,
  S.current_crawl_date, S.previous_crawl_date, S.crawl_trigger, S.pages_crawled_delta,
  S.indexable_html_urls_delta, S.status_4xx_urls_delta, S.status_5xx_urls_delta,
  S.missing_title_urls_delta, S.missing_meta_description_urls_delta, S.missing_h1_urls_delta,
  S.canonical_issue_urls_delta, S.low_content_urls_delta, S.comparison_status, S.source_ref_hash,
  S.retention_expires_on
)
""".strip()


def schema_fields(schema: list[tuple[str, str, str]]):
    from google.cloud import bigquery

    return [bigquery.SchemaField(name, field_type, mode=mode) for name, field_type, mode in schema]


def load_staging_run(client: Any, config: BigQueryCostConfig, row: dict[str, Any]) -> str:
    from google.cloud import bigquery

    staging_table_id = config.table_id(config.staging_dataset, f"screaming_frog_run_{safe_suffix(row['crawl_id'])}")
    staging_dataset = bigquery.Dataset(f"{config.project_id}.{config.staging_dataset}")
    staging_dataset.location = config.default_location
    client.create_dataset(staging_dataset, exists_ok=True)
    table = bigquery.Table(staging_table_id, schema=schema_fields(CLIENT_CRAWL_RUNS_SCHEMA))
    client.delete_table(staging_table_id, not_found_ok=True)
    client.create_table(table)
    job_config = bigquery.LoadJobConfig(schema=table.schema, write_disposition="WRITE_TRUNCATE")
    client.load_table_from_json([row], staging_table_id, job_config=job_config, location=config.default_location).result()
    return staging_table_id


def load_rows(client: Any, config: BigQueryCostConfig, table_name: str, schema: list[tuple[str, str, str]], rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    from google.cloud import bigquery

    target = config.table_id(config.memory_dataset, table_name)
    total = 0
    for offset in range(0, len(rows), 5000):
        chunk = rows[offset : offset + 5000]
        job_config = bigquery.LoadJobConfig(schema=schema_fields(schema), write_disposition="WRITE_APPEND")
        client.load_table_from_json(chunk, target, job_config=job_config, location=config.default_location).result()
        total += len(chunk)
    return total


def write_payload_to_bigquery(payload: CrawlExportPayload, config: BigQueryCostConfig) -> dict[str, Any]:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    runner = CappedBigQueryRunner(client, config)
    staging_table_id = load_staging_run(client, config, payload.run_row)
    runs_result, _ = runner.run_query(
        build_runs_merge_sql(config, staging_table_id),
        purpose=f"screaming frog full export: merge crawl run {payload.run_row['crawl_id']}",
        labels={"crawl_memory": "full_export_runs"},
    )
    loaded = {"runs_merge_job_id": runs_result.job_id}
    if payload.coverage_valid:
        for table_name in ("client_crawl_url_snapshots", "client_crawl_issue_rows", "client_crawl_link_rows", "client_crawl_export_rows"):
            runner.run_query(
                build_delete_details_sql(config, table_name, payload.run_row["crawl_id"]),
                purpose=f"screaming frog full export: replace {table_name} for {payload.run_row['crawl_id']}",
                labels={"crawl_memory": "full_export_replace"},
            )
        loaded["url_rows"] = load_rows(client, config, "client_crawl_url_snapshots", CLIENT_CRAWL_URL_SNAPSHOTS_SCHEMA, payload.url_rows)
        loaded["issue_rows"] = load_rows(client, config, "client_crawl_issue_rows", CLIENT_CRAWL_ISSUE_ROWS_SCHEMA, payload.issue_rows)
        loaded["link_rows"] = load_rows(client, config, "client_crawl_link_rows", CLIENT_CRAWL_LINK_ROWS_SCHEMA, payload.link_rows)
        loaded["export_rows"] = load_rows(client, config, "client_crawl_export_rows", CLIENT_CRAWL_EXPORT_ROWS_SCHEMA, payload.export_rows)
        latest_result, _ = runner.run_query(
            build_latest_merge_sql(config, payload.run_row["client_slug"]),
            purpose=f"screaming frog full export: refresh latest crawl for {payload.run_row['client_slug']}",
            labels={"crawl_memory": "full_export_latest"},
        )
        comparison_result, _ = runner.run_query(
            build_comparison_merge_sql(config, payload.run_row["crawl_id"]),
            purpose=f"screaming frog full export: refresh crawl comparison for {payload.run_row['crawl_id']}",
            labels={"crawl_memory": "full_export_comparison"},
        )
        loaded["latest_merge_job_id"] = latest_result.job_id
        loaded["comparison_merge_job_id"] = comparison_result.job_id
    else:
        loaded["coverage_note"] = "coverage_failed metadata loaded; detail rows/latest/comparison were not promoted"
    return loaded


def metadata_from_args(args: argparse.Namespace) -> CrawlExportMetadata:
    crawl_date = date.fromisoformat(args.crawl_date) if args.crawl_date else datetime.now(MELBOURNE_TIMEZONE).date()
    export_dir = Path(args.export_dir).expanduser().resolve()
    if not export_dir.exists() or not export_dir.is_dir():
        raise ValueError(f"export directory does not exist: {export_dir}")
    client_name = args.client_name or normalise_slug_title(args.client_slug)
    return CrawlExportMetadata(
        export_dir=export_dir,
        client_slug=args.client_slug,
        client_name=client_name,
        crawl_id=args.crawl_id,
        run_id=args.run_id or args.crawl_id,
        crawl_date=crawl_date,
        crawl_trigger=args.crawl_trigger,
        crawl_scope=args.crawl_scope,
        scope_ref=args.scope_ref,
        start_url=args.start_url,
        min_urls=args.min_urls,
        ingested_at=utc_now_iso(),
    )


def main() -> int:
    args = parse_args()
    try:
        meta = metadata_from_args(args)
        payload = build_export_payload(meta)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "validation_failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 3
    summary = {
        "status": "validated" if payload.coverage_valid else "coverage_failed",
        "crawl_id": payload.run_row["crawl_id"],
        "client_slug": payload.run_row["client_slug"],
        "crawl_scope": payload.run_row["crawl_scope"],
        "pages_crawled": payload.run_row["pages_crawled"],
        "row_counts": {
            "url_rows": len(payload.url_rows),
            "issue_rows": len(payload.issue_rows),
            "link_rows": len(payload.link_rows),
            "export_rows": len(payload.export_rows),
        },
        "csv_file_count": len(payload.row_counts),
        "blocked_files": payload.blocked_files,
        "retention_expires_on": payload.run_row["retention_expires_on"],
    }
    if args.dry_run or not args.write_bigquery:
        print(json.dumps(summary, indent=2, default=str))
        return 0 if payload.coverage_valid else 4
    if args.load_env:
        load_env_file(Path(args.load_env))
    try:
        from google.cloud import bigquery
    except ModuleNotFoundError:
        print("google-cloud-bigquery is not installed. Run: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 2
    config = BigQueryCostConfig.from_file(args.config)
    if args.ensure_tables:
        client = bigquery.Client(project=config.project_id)
        ensure_crawl_memory_tables(client, config)
    loaded = write_payload_to_bigquery(payload, config)
    summary["status"] = "loaded" if payload.coverage_valid else "coverage_failed_loaded_metadata"
    summary["bigquery"] = loaded
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
