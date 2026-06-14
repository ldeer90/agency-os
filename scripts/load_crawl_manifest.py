#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.schema import CLIENT_CRAWL_RUNS_SCHEMA, ensure_crawl_memory_tables  # noqa: E402


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
TABLE_FIELDS = [name for name, _field_type, _mode in CLIENT_CRAWL_RUNS_SCHEMA]
REQUIRED_FIELDS = {name for name, _field_type, mode in CLIENT_CRAWL_RUNS_SCHEMA if mode == "REQUIRED"}
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_]")
MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")


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
    parser = argparse.ArgumentParser(description="Validate and load a sanitized Screaming Frog crawl manifest into BigQuery.")
    parser.add_argument("--manifest", required=True, help="Path to a crawl manifest JSON file.")
    parser.add_argument("--analysis-summary-json", help="Optional SEO Automation Screaming Frog analysis-summary.json to merge into the crawl run.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--load-env", help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the row without writing to BigQuery.")
    parser.add_argument("--ensure-tables", action="store_true", help="Create/update crawl-memory tables before loading.")
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(MELBOURNE_TIMEZONE).isoformat()


def safe_suffix(value: str) -> str:
    return SAFE_ID_RE.sub("_", value)[:80].strip("_") or "crawl_manifest"


def source_hash(manifest: dict, manifest_path: Path) -> str:
    explicit_hash = str(manifest.get("export_file_sha256") or "").strip()
    if explicit_hash:
        return explicit_hash
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def row_from_manifest(manifest: dict, manifest_path: Path, *, ingested_at: str) -> dict:
    row = {
        "crawl_id": manifest.get("crawl_id"),
        "run_id": manifest.get("run_id") or manifest.get("crawl_id"),
        "crawl_date": manifest.get("crawl_date"),
        "ingested_at": ingested_at,
        "client_slug": manifest.get("client_slug"),
        "client_name": manifest.get("client_name"),
        "crawl_trigger": manifest.get("crawl_trigger"),
        "trigger_ref": manifest.get("trigger_ref"),
        "crawler": manifest.get("crawler") or "screaming_frog_mcp",
        "crawl_scope": manifest.get("crawl_scope"),
        "start_url": manifest.get("start_url"),
        "config_ref": manifest.get("config_ref"),
        "robots_respected": bool(manifest.get("robots_respected", True)),
        "crawl_status": manifest.get("crawl_status"),
        "pages_crawled": manifest.get("pages_crawled"),
        "internal_html_urls": manifest.get("internal_html_urls"),
        "indexable_html_urls": manifest.get("indexable_html_urls"),
        "nonindexable_html_urls": manifest.get("nonindexable_html_urls"),
        "status_2xx_urls": manifest.get("status_2xx_urls"),
        "status_3xx_urls": manifest.get("status_3xx_urls"),
        "status_4xx_urls": manifest.get("status_4xx_urls"),
        "status_5xx_urls": manifest.get("status_5xx_urls"),
        "missing_title_urls": manifest.get("missing_title_urls"),
        "duplicate_title_urls": manifest.get("duplicate_title_urls"),
        "missing_meta_description_urls": manifest.get("missing_meta_description_urls"),
        "duplicate_meta_description_urls": manifest.get("duplicate_meta_description_urls"),
        "missing_h1_urls": manifest.get("missing_h1_urls"),
        "duplicate_h1_urls": manifest.get("duplicate_h1_urls"),
        "canonical_issue_urls": manifest.get("canonical_issue_urls"),
        "low_content_urls": manifest.get("low_content_urls"),
        "issue_counts_json": manifest.get("issue_counts_json")
        or {
            "export_file_size_bytes": manifest.get("export_file_size_bytes"),
            "raw_content_exported": bool(manifest.get("raw_content_exported", False)),
            "visible_text_exported": bool(manifest.get("visible_text_exported", False)),
        },
        "export_manifest_path": str(manifest_path),
        "export_drive_file_id": manifest.get("export_drive_file_id"),
        "source_ref_hash": source_hash(manifest, manifest_path),
        "retention_expires_on": manifest.get("retention_expires_on"),
    }
    return {field: row.get(field) for field in TABLE_FIELDS}


def merge_analysis_summary(row: dict, summary_path: Path) -> dict:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metrics = summary.get("metrics") or {}
    top_issues = summary.get("top_issues") or []
    row = dict(row)
    if metrics.get("internal_rows") is not None:
        existing_pages = row.get("pages_crawled")
        summary_pages = metrics.get("internal_rows")
        if existing_pages in (None, 0) or (summary_pages and summary_pages > existing_pages):
            row["pages_crawled"] = summary_pages
        row["internal_html_urls"] = metrics.get("internal_rows")
    row["status_3xx_urls"] = metrics.get("internal_3xx")
    row["status_4xx_urls"] = metrics.get("internal_4xx_5xx")
    row["status_5xx_urls"] = 0 if metrics.get("internal_4xx_5xx") == 0 else row.get("status_5xx_urls")
    row["nonindexable_html_urls"] = metrics.get("non_indexable")
    row["missing_title_urls"] = metrics.get("missing_titles")
    row["duplicate_title_urls"] = metrics.get("duplicate_titles")
    row["missing_meta_description_urls"] = metrics.get("missing_meta_descriptions")
    row["duplicate_meta_description_urls"] = metrics.get("duplicate_meta_descriptions")
    row["missing_h1_urls"] = metrics.get("missing_h1")
    row["duplicate_h1_urls"] = metrics.get("multiple_h1")
    row["canonical_issue_urls"] = (metrics.get("missing_canonicals") or 0) + (metrics.get("canonicalised") or 0)
    row["issue_counts_json"] = {
        "summary_source": "seo_automation_screaming_frog_analysis",
        "summary_path": str(summary_path),
        "csv_file_count": summary.get("csv_file_count"),
        "metrics": metrics,
        "top_issues": top_issues[:15],
        "raw_content_exported": False,
        "visible_text_exported": False,
    }
    return row


def validate_row(row: dict) -> None:
    missing = sorted(field for field in REQUIRED_FIELDS if row.get(field) is None)
    if missing:
        raise ValueError(f"crawl manifest missing required fields: {', '.join(missing)}")
    if row.get("raw_content_exported") or row.get("visible_text_exported"):
        raise ValueError("raw page content exports are not allowed in crawl-memory manifests")
    issue_counts = row.get("issue_counts_json") or {}
    if isinstance(issue_counts, dict) and (issue_counts.get("raw_content_exported") or issue_counts.get("visible_text_exported")):
        raise ValueError("raw page content exports are not allowed in crawl-memory manifests")


def quote_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"unsafe identifier: {name}")
    return f"`{name}`"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_runs_merge_sql(config: BigQueryCostConfig, staging_table_id: str) -> str:
    target = config.table_id(config.memory_dataset, "client_crawl_runs")
    columns = TABLE_FIELDS
    update_columns = [column for column in columns if column != "crawl_id"]
    update_clause = ", ".join(f"T.{quote_name(column)} = S.{quote_name(column)}" for column in update_columns)
    insert_columns = ", ".join(quote_name(column) for column in columns)
    insert_values = ", ".join(f"S.{quote_name(column)}" for column in columns)
    return f"""
MERGE `{target}` AS T
USING `{staging_table_id}` AS S
ON T.`crawl_id` = S.`crawl_id`
WHEN MATCHED THEN UPDATE SET {update_clause}
WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})
""".strip()


def build_latest_merge_sql(config: BigQueryCostConfig, client_slug: str) -> str:
    target = config.table_id(config.reporting_dataset, "client_crawl_latest")
    source = config.table_id(config.memory_dataset, "client_crawl_runs")
    return f"""
MERGE `{target}` AS T
USING (
  SELECT
    crawl_date,
    crawl_id,
    client_slug,
    client_name,
    crawl_trigger,
    crawler,
    start_url,
    crawl_status,
    pages_crawled,
    indexable_html_urls,
    nonindexable_html_urls,
    status_4xx_urls,
    status_5xx_urls,
    missing_title_urls,
    duplicate_title_urls,
    missing_meta_description_urls,
    missing_h1_urls,
    canonical_issue_urls,
    low_content_urls,
    issue_counts_json,
    export_manifest_path,
    export_drive_file_id,
    source_ref_hash
  FROM `{source}`
  WHERE client_slug = {sql_string(client_slug)}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY client_slug ORDER BY crawl_date DESC, ingested_at DESC) = 1
) AS S
ON T.`client_slug` = S.`client_slug`
WHEN MATCHED THEN UPDATE SET
  crawl_date = S.crawl_date,
  crawl_id = S.crawl_id,
  client_name = S.client_name,
  crawl_trigger = S.crawl_trigger,
  crawler = S.crawler,
  start_url = S.start_url,
  crawl_status = S.crawl_status,
  pages_crawled = S.pages_crawled,
  indexable_html_urls = S.indexable_html_urls,
  nonindexable_html_urls = S.nonindexable_html_urls,
  status_4xx_urls = S.status_4xx_urls,
  status_5xx_urls = S.status_5xx_urls,
  missing_title_urls = S.missing_title_urls,
  duplicate_title_urls = S.duplicate_title_urls,
  missing_meta_description_urls = S.missing_meta_description_urls,
  missing_h1_urls = S.missing_h1_urls,
  canonical_issue_urls = S.canonical_issue_urls,
  low_content_urls = S.low_content_urls,
  issue_counts_json = S.issue_counts_json,
  export_manifest_path = S.export_manifest_path,
  export_drive_file_id = S.export_drive_file_id,
  source_ref_hash = S.source_ref_hash
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


def load_staging_row(client, config: BigQueryCostConfig, row: dict) -> str:
    from google.cloud import bigquery

    staging_table_id = config.table_id(config.staging_dataset, f"crawl_manifest_{safe_suffix(row['crawl_id'])}")
    staging_dataset = bigquery.Dataset(f"{config.project_id}.{config.staging_dataset}")
    staging_dataset.location = config.default_location
    client.create_dataset(staging_dataset, exists_ok=True)
    staging_table = bigquery.Table(
        staging_table_id,
        schema=[bigquery.SchemaField(name, field_type, mode=mode) for name, field_type, mode in CLIENT_CRAWL_RUNS_SCHEMA],
    )
    staging_table.expires = datetime.now(timezone.utc) + timedelta(hours=config.staging_table_expiry_hours)
    client.create_table(staging_table, exists_ok=True)
    job_config = bigquery.LoadJobConfig(schema=staging_table.schema, write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_json([row], staging_table_id, job_config=job_config, location=config.default_location)
    job.result()
    return staging_table_id


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Manifest does not exist: {manifest_path}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        row = row_from_manifest(manifest, manifest_path.resolve(), ingested_at=utc_now_iso())
        if args.analysis_summary_json:
            row = merge_analysis_summary(row, Path(args.analysis_summary_json).resolve())
        validate_row(row)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "validation_failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 3

    if args.dry_run:
        print(json.dumps({"status": "validated", "row": row}, indent=2, default=str))
        return 0

    if args.load_env:
        load_env_file(Path(args.load_env))
    try:
        from google.cloud import bigquery
    except ModuleNotFoundError:
        print("google-cloud-bigquery is not installed. Run: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    config = BigQueryCostConfig.from_file(args.config)
    client = bigquery.Client(project=config.project_id)
    if args.ensure_tables:
        ensure_crawl_memory_tables(client, config)
    staging_table_id = load_staging_row(client, config, row)
    runner = CappedBigQueryRunner(client, config)
    runs_result, _ = runner.run_query(
        build_runs_merge_sql(config, staging_table_id),
        purpose=f"crawl memory: merge crawl run {row['crawl_id']}",
        labels={"crawl_memory": "runs"},
    )
    latest_result, _ = runner.run_query(
        build_latest_merge_sql(config, row["client_slug"]),
        purpose=f"crawl memory: refresh latest crawl for {row['client_slug']}",
        labels={"crawl_memory": "latest"},
    )
    print(
        json.dumps(
            {
                "status": "succeeded",
                "crawl_id": row["crawl_id"],
                "client_slug": row["client_slug"],
                "staging_table": staging_table_id,
                "runs_merge_job_id": runs_result.job_id,
                "latest_merge_job_id": latest_result.job_id,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
