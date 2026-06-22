#!/usr/bin/env python3
"""Load quarterly SEO snapshots for sales leads and lost-sales opportunities.

The loader stores small, structured SE Ranking estimates and Screaming Frog
crawl references only. It does not store raw HTML, page text, or raw crawl
archives in BigQuery.
"""

from __future__ import annotations

import argparse
import calendar
import dataclasses
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import BigQueryCostConfig, DEFAULT_CONFIG_PATH  # noqa: E402
from agency_bigquery.schema import (  # noqa: E402
    SALES_OPPORTUNITY_SEO_SNAPSHOTS_SCHEMA,
    SALES_OPPORTUNITY_SITES_SCHEMA,
    ensure_sales_opportunity_tables,
)
from scripts.smoke_reporting_apis import (  # noqa: E402
    DEFAULT_SEO_AUTOMATION_ENV,
    DEFAULT_SE_RANKING_ENV,
    SE_RANKING_ENV_KEYS,
    load_dotenv_keys,
    sanitized_error,
)

MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "data" / "sales_opportunities" / "sites.json"
VALID_STATUSES = {"lead", "lost", "won", "archived"}
SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,78}[a-z0-9]$")
SAFE_NOTES_RE = re.compile(
    r"(@|\b\+?\d[\d\s().-]{7,}\b|password|token|secret|api[_ -]?key|private[_ -]?key)",
    re.IGNORECASE,
)

SITE_FIELDS = [name for name, _field_type, _mode in SALES_OPPORTUNITY_SITES_SCHEMA]
SNAPSHOT_FIELDS = [name for name, _field_type, _mode in SALES_OPPORTUNITY_SEO_SNAPSHOTS_SCHEMA]


@dataclass(frozen=True)
class SalesOpportunitySite:
    opportunity_slug: str
    business_name: str
    domain: str
    status: str
    source: str | None
    owner: str | None
    market: str
    currency: str
    site_url: str | None
    notes_summary: str | None


@dataclass(frozen=True)
class Quarter:
    quarter_id: str
    quarter_start: date
    quarter_end: date


@dataclass(frozen=True)
class SeRankingSnapshot:
    status: str
    source: str
    retrieved_at: str | None
    metrics: dict[str, Any]
    metadata: dict[str, Any]
    error_class: str | None = None
    error_message: str | None = None


def melbourne_now() -> datetime:
    return datetime.now(MELBOURNE_TIMEZONE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load sales opportunity SEO snapshots into BigQuery.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--opportunity", action="append", help="Limit to one opportunity slug. Repeatable.")
    parser.add_argument("--quarter", required=True, help="Quarter to load, formatted YYYY-QN, for example 2026-Q2.")
    parser.add_argument("--snapshot-date", help="Snapshot date YYYY-MM-DD. Defaults to today's Melbourne date.")
    parser.add_argument("--se-ranking-json", action="append", help="Saved SE Ranking JSON export. Repeatable.")
    parser.add_argument("--crawl-id", help="Approved Screaming Frog crawl_id to attach to this opportunity snapshot.")
    parser.add_argument("--previous-crawl-id", help="Previous crawl_id for page-title comparison reporting.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-bigquery", action="store_true")
    parser.add_argument("--ensure-tables", action="store_true")
    parser.add_argument("--load-env", default=str(DEFAULT_SEO_AUTOMATION_ENV))
    parser.add_argument("--se-ranking-env", default=str(DEFAULT_SE_RANKING_ENV))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--write-disposition", default="WRITE_APPEND", choices=("WRITE_APPEND", "WRITE_TRUNCATE"))
    return parser.parse_args()


def parse_quarter(value: str) -> Quarter:
    match = re.fullmatch(r"(20\d{2})-Q([1-4])", value.strip().upper())
    if not match:
        raise ValueError(f"Quarter must be formatted YYYY-QN, got: {value}")
    year = int(match.group(1))
    quarter = int(match.group(2))
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    end_day = calendar.monthrange(year, end_month)[1]
    return Quarter(
        quarter_id=f"{year}-Q{quarter}",
        quarter_start=date(year, start_month, 1),
        quarter_end=date(year, end_month, end_day),
    )


def normalize_domain(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("domain is required")
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = parsed.netloc or parsed.path
    host = host.split("/", 1)[0].removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host):
        raise ValueError(f"domain is not a valid host: {value}")
    return host


def normalize_site_url(value: Any, domain: str) -> str | None:
    if not value:
        return f"https://{domain}"
    text = str(value).strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if not parsed.netloc:
        return f"https://{domain}"
    return f"{parsed.scheme or 'https'}://{parsed.netloc}{parsed.path or ''}".rstrip("/")


def safe_text(value: Any, *, field_name: str, max_chars: int = 240, required: bool = False) -> str | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    text = str(value).strip()
    if len(text) > max_chars:
        raise ValueError(f"{field_name} exceeds {max_chars} characters")
    if field_name == "notes_summary" and SAFE_NOTES_RE.search(text):
        raise ValueError("notes_summary looks like private contact detail or credential-like text")
    return text


def load_registry(path: Path, *, opportunity_slugs: set[str] | None = None) -> list[SalesOpportunitySite]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sites") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("sales opportunity registry must be a list or contain a sites list")

    sites: list[SalesOpportunitySite] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("registry rows must be objects")
        slug = safe_text(raw.get("opportunity_slug"), field_name="opportunity_slug", required=True)
        assert slug is not None
        if not SAFE_SLUG_RE.fullmatch(slug):
            raise ValueError(f"opportunity_slug must be lowercase slug text: {slug}")
        if opportunity_slugs and slug not in opportunity_slugs:
            continue
        if slug in seen:
            raise ValueError(f"duplicate opportunity_slug: {slug}")
        seen.add(slug)

        domain = normalize_domain(str(raw.get("domain") or raw.get("site_url") or ""))
        status = safe_text(raw.get("status"), field_name="status", required=True)
        assert status is not None
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}, got: {status}")
        market = safe_text(raw.get("market", "au"), field_name="market", max_chars=12) or "au"
        currency = safe_text(raw.get("currency", "AUD"), field_name="currency", max_chars=3) or "AUD"
        sites.append(
            SalesOpportunitySite(
                opportunity_slug=slug,
                business_name=safe_text(raw.get("business_name"), field_name="business_name", required=True) or slug,
                domain=domain,
                status=status,
                source=safe_text(raw.get("source"), field_name="source", max_chars=120),
                owner=safe_text(raw.get("owner"), field_name="owner", max_chars=120),
                market=market.lower(),
                currency=currency.upper(),
                site_url=normalize_site_url(raw.get("site_url"), domain),
                notes_summary=safe_text(raw.get("notes_summary"), field_name="notes_summary", max_chars=240),
            )
        )
    if opportunity_slugs and opportunity_slugs - {site.opportunity_slug for site in sites}:
        missing = ", ".join(sorted(opportunity_slugs - {site.opportunity_slug for site in sites}))
        raise ValueError(f"opportunity slug not found in registry: {missing}")
    return sites


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def first_object(value: Any, *, preferred_source: str | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        if preferred_source:
            for item in value:
                if isinstance(item, dict) and str(item.get("source", "")).lower() == preferred_source.lower():
                    return item
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def metric_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row.get(name)
    tops = row.get("positions_tops")
    if isinstance(tops, dict):
        for name in names:
            if name in tops:
                return tops.get(name)
    return None


def parse_se_ranking_payload(payload: dict[str, Any], *, source: str, market: str) -> SeRankingSnapshot:
    overview = payload.get("domain_overview", payload)
    backlink_payload = payload.get("backlinks_summary", payload.get("backlinks", {}))
    organic = first_object(overview.get("organic"), preferred_source=market) if isinstance(overview, dict) else {}
    backlink_summary = first_object(backlink_payload.get("summary"), preferred_source=None) if isinstance(backlink_payload, dict) else {}
    if not backlink_summary and isinstance(backlink_payload, dict):
        backlink_summary = backlink_payload

    metrics = {
        "estimated_organic_traffic": to_int(metric_value(organic, "traffic_sum")),
        "organic_keywords_count": to_int(metric_value(organic, "keywords_count")),
        "organic_traffic_value": to_float(metric_value(organic, "price_sum")),
        "organic_keywords_new_count": to_int(metric_value(organic, "keywords_new_count", "positions_new_count")),
        "organic_keywords_up_count": to_int(metric_value(organic, "keywords_up_count", "positions_up_count")),
        "organic_keywords_down_count": to_int(metric_value(organic, "keywords_down_count", "positions_down_count")),
        "organic_keywords_equal_count": to_int(metric_value(organic, "keywords_equal_count", "positions_equal_count")),
        "organic_keywords_lost_count": to_int(metric_value(organic, "keywords_lost_count", "positions_lost_count")),
        "organic_top1_5": to_int(metric_value(organic, "top1_5")),
        "organic_top6_10": to_int(metric_value(organic, "top6_10")),
        "organic_top11_20": to_int(metric_value(organic, "top11_20")),
        "organic_top21_50": to_int(metric_value(organic, "top21_50")),
        "organic_top51_100": to_int(metric_value(organic, "top51_100")),
        "referring_domains": to_int(backlink_summary.get("refdomains")),
        "backlinks": to_int(backlink_summary.get("backlinks")),
        "dofollow_backlinks": to_int(backlink_summary.get("dofollow_backlinks")),
        "nofollow_backlinks": to_int(backlink_summary.get("nofollow_backlinks")),
        "domain_inlink_rank": to_int(backlink_summary.get("domain_inlink_rank")),
        "pages_with_backlinks": to_int(backlink_summary.get("pages_with_backlinks")),
    }
    status = "succeeded" if any(value is not None for value in metrics.values()) else "missing_metrics"
    metadata = {
        "provider": "se_ranking",
        "source": source,
        "market": market,
        "organic_year": organic.get("year"),
        "organic_month": organic.get("month"),
        "domain_overview_shape": sorted(overview.keys()) if isinstance(overview, dict) else [],
        "backlinks_shape": sorted(backlink_payload.keys()) if isinstance(backlink_payload, dict) else [],
    }
    retrieved_at = payload.get("retrieved_at") or melbourne_now().isoformat()
    return SeRankingSnapshot(status=status, source=source, retrieved_at=retrieved_at, metrics=metrics, metadata=metadata)


def load_se_ranking_exports(paths: list[str] | None, *, market: str) -> list[SeRankingSnapshot]:
    snapshots = []
    for path_text in paths or []:
        path = Path(path_text)
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshots.append(parse_se_ranking_payload(payload, source=str(path), market=market))
    return snapshots


def se_ranking_token() -> str:
    return os.environ.get("DATA_API_TOKEN") or os.environ.get("SE_RANKING_API_KEY") or ""


def fetch_se_ranking_live(site: SalesOpportunitySite) -> SeRankingSnapshot:
    token = se_ranking_token()
    if not token:
        return SeRankingSnapshot(
            status="missing_config",
            source="se_ranking_api",
            retrieved_at=melbourne_now().isoformat(),
            metrics={},
            metadata={"provider": "se_ranking", "market": site.market},
            error_class="MissingConfig",
            error_message="SE Ranking Data API token is not configured.",
        )
    try:
        import httpx

        headers = {"Authorization": f"Token {token}"}
        overview = httpx.get(
            "https://api.seranking.com/v1/domain/overview/db",
            params={"source": site.market, "domain": site.domain, "with_subdomains": 1},
            headers=headers,
            timeout=60,
        )
        overview.raise_for_status()
        backlinks = httpx.get(
            "https://api.seranking.com/v1/backlinks/summary",
            params={"target": site.domain, "mode": "host", "output": "json"},
            headers=headers,
            timeout=60,
        )
        backlinks.raise_for_status()
        payload = {
            "domain_overview": overview.json() if overview.content else {},
            "backlinks_summary": backlinks.json() if backlinks.content else {},
            "retrieved_at": melbourne_now().isoformat(),
        }
        return parse_se_ranking_payload(payload, source="se_ranking_api", market=site.market)
    except Exception as exc:
        error_class, error_message = sanitized_error(exc)
        return SeRankingSnapshot(
            status="failed",
            source="se_ranking_api",
            retrieved_at=melbourne_now().isoformat(),
            metrics={},
            metadata={"provider": "se_ranking", "market": site.market},
            error_class=error_class,
            error_message=error_message,
        )


def choose_se_ranking_snapshot(
    site: SalesOpportunitySite,
    *,
    exports: list[SeRankingSnapshot],
    dry_run: bool,
) -> SeRankingSnapshot:
    if exports:
        return exports[0]
    if dry_run:
        return SeRankingSnapshot(
            status="planned",
            source="se_ranking_api",
            retrieved_at=None,
            metrics={},
            metadata={"provider": "se_ranking", "market": site.market, "dry_run": True},
        )
    return fetch_se_ranking_live(site)


def site_row(site: SalesOpportunitySite, *, registry_path: Path, run_id: str, ingested_at: str) -> dict[str, Any]:
    row = {
        "registered_at": ingested_at,
        "updated_at": ingested_at,
        "run_id": run_id,
        "opportunity_slug": site.opportunity_slug,
        "business_name": site.business_name,
        "domain": site.domain,
        "site_url": site.site_url,
        "status": site.status,
        "source": site.source,
        "owner": site.owner,
        "market": site.market,
        "currency": site.currency,
        "notes_summary": site.notes_summary,
        "registry_path": str(registry_path),
    }
    row["source_ref_hash"] = stable_hash(row)
    return {field: row.get(field) for field in SITE_FIELDS}


def snapshot_row(
    site: SalesOpportunitySite,
    quarter: Quarter,
    se_ranking: SeRankingSnapshot,
    *,
    snapshot_date: date,
    run_id: str,
    ingested_at: str,
    crawl_id: str | None,
    previous_crawl_id: str | None,
) -> dict[str, Any]:
    snapshot_id = f"{site.opportunity_slug}-{quarter.quarter_id}"
    row = {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date.isoformat(),
        "quarter_id": quarter.quarter_id,
        "quarter_start": quarter.quarter_start.isoformat(),
        "quarter_end": quarter.quarter_end.isoformat(),
        "ingested_at": ingested_at,
        "run_id": run_id,
        "opportunity_slug": site.opportunity_slug,
        "business_name": site.business_name,
        "domain": site.domain,
        "status": site.status,
        "market": site.market,
        "currency": site.currency,
        "se_ranking_status": se_ranking.status,
        "se_ranking_source": se_ranking.source,
        "se_ranking_retrieved_at": se_ranking.retrieved_at,
        "crawl_id": crawl_id,
        "previous_crawl_id": previous_crawl_id,
        "metadata_json": se_ranking.metadata,
        "error_class": se_ranking.error_class,
        "error_message": se_ranking.error_message,
        **se_ranking.metrics,
    }
    row["source_ref_hash"] = stable_hash(row)
    return {field: row.get(field) for field in SNAPSHOT_FIELDS}


def build_quarterly_comparison_sql(config: BigQueryCostConfig) -> str:
    project = config.project_id
    memory = config.memory_dataset
    reporting = config.reporting_dataset
    return f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.sales_opportunity_quarterly_comparison`
PARTITION BY snapshot_date
CLUSTER BY opportunity_slug, quarter_id, comparison_status AS
WITH snapshots AS (
  SELECT *
  FROM `{project}.{memory}.sales_opportunity_seo_snapshots`
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY opportunity_slug, quarter_id
    ORDER BY ingested_at DESC, snapshot_id DESC
  ) = 1
),
snapshots_with_previous AS (
  SELECT
    s.*,
    LAG(estimated_organic_traffic) OVER site_order AS previous_estimated_organic_traffic,
    LAG(organic_keywords_count) OVER site_order AS previous_organic_keywords_count,
    LAG(referring_domains) OVER site_order AS previous_referring_domains,
    LAG(backlinks) OVER site_order AS previous_backlinks,
    COALESCE(previous_crawl_id, LAG(crawl_id) OVER site_order) AS comparison_previous_crawl_id
  FROM snapshots s
  WINDOW site_order AS (PARTITION BY opportunity_slug ORDER BY quarter_start)
),
crawl_runs AS (
  SELECT
    crawl_id,
    pages_crawled,
    missing_title_urls,
    duplicate_title_urls,
    missing_meta_description_urls,
    missing_h1_urls,
    crawl_status
  FROM `{project}.{memory}.client_crawl_runs`
),
url_counts AS (
  SELECT crawl_id, COUNT(*) AS crawl_url_snapshot_rows
  FROM `{project}.{memory}.client_crawl_url_snapshots`
  GROUP BY crawl_id
),
title_changes AS (
  SELECT
    curr.crawl_id,
    prev.crawl_id AS previous_crawl_id,
    COUNTIF(COALESCE(curr.title, '') != COALESCE(prev.title, '')) AS title_changed_urls
  FROM `{project}.{memory}.client_crawl_url_snapshots` curr
  JOIN `{project}.{memory}.client_crawl_url_snapshots` prev
    ON curr.url_hash = prev.url_hash
  GROUP BY curr.crawl_id, prev.crawl_id
),
enriched AS (
  SELECT
    s.*,
    current_crawl.crawl_status AS current_crawl_status,
    current_crawl.pages_crawled AS crawl_pages_crawled,
    previous_crawl.pages_crawled AS previous_pages_crawled,
    current_crawl.missing_title_urls AS crawl_missing_title_urls,
    previous_crawl.missing_title_urls AS previous_missing_title_urls,
    current_crawl.duplicate_title_urls AS crawl_duplicate_title_urls,
    previous_crawl.duplicate_title_urls AS previous_duplicate_title_urls,
    current_crawl.missing_meta_description_urls AS crawl_missing_meta_description_urls,
    previous_crawl.missing_meta_description_urls AS previous_missing_meta_description_urls,
    current_crawl.missing_h1_urls AS crawl_missing_h1_urls,
    previous_crawl.missing_h1_urls AS previous_missing_h1_urls,
    url_counts.crawl_url_snapshot_rows AS joined_crawl_url_snapshot_rows,
    title_changes.title_changed_urls AS joined_title_changed_urls
  FROM snapshots_with_previous s
  LEFT JOIN crawl_runs current_crawl ON current_crawl.crawl_id = s.crawl_id
  LEFT JOIN crawl_runs previous_crawl ON previous_crawl.crawl_id = s.comparison_previous_crawl_id
  LEFT JOIN url_counts ON url_counts.crawl_id = s.crawl_id
  LEFT JOIN title_changes
    ON title_changes.crawl_id = s.crawl_id
    AND title_changes.previous_crawl_id = s.comparison_previous_crawl_id
)
SELECT
  quarter_id,
  snapshot_date,
  opportunity_slug,
  business_name,
  domain,
  status,
  market,
  currency,
  estimated_organic_traffic,
  estimated_organic_traffic - previous_estimated_organic_traffic AS estimated_organic_traffic_delta,
  SAFE_DIVIDE(estimated_organic_traffic - previous_estimated_organic_traffic, previous_estimated_organic_traffic) AS estimated_organic_traffic_pct,
  organic_keywords_count,
  organic_keywords_count - previous_organic_keywords_count AS organic_keywords_count_delta,
  SAFE_DIVIDE(organic_keywords_count - previous_organic_keywords_count, previous_organic_keywords_count) AS organic_keywords_count_pct,
  referring_domains,
  referring_domains - previous_referring_domains AS referring_domains_delta,
  SAFE_DIVIDE(referring_domains - previous_referring_domains, previous_referring_domains) AS referring_domains_pct,
  backlinks,
  backlinks - previous_backlinks AS backlinks_delta,
  SAFE_DIVIDE(backlinks - previous_backlinks, previous_backlinks) AS backlinks_pct,
  crawl_id,
  comparison_previous_crawl_id AS previous_crawl_id,
  crawl_pages_crawled AS pages_crawled,
  crawl_pages_crawled - previous_pages_crawled AS pages_crawled_delta,
  crawl_missing_title_urls AS missing_title_urls,
  crawl_missing_title_urls - previous_missing_title_urls AS missing_title_urls_delta,
  crawl_duplicate_title_urls AS duplicate_title_urls,
  crawl_duplicate_title_urls - previous_duplicate_title_urls AS duplicate_title_urls_delta,
  crawl_missing_meta_description_urls AS missing_meta_description_urls,
  crawl_missing_meta_description_urls - previous_missing_meta_description_urls AS missing_meta_description_urls_delta,
  crawl_missing_h1_urls AS missing_h1_urls,
  crawl_missing_h1_urls - previous_missing_h1_urls AS missing_h1_urls_delta,
  joined_crawl_url_snapshot_rows AS crawl_url_snapshot_rows,
  joined_title_changed_urls AS title_changed_urls,
  CASE
    WHEN previous_estimated_organic_traffic IS NULL
      AND previous_organic_keywords_count IS NULL
      AND previous_referring_domains IS NULL
      THEN IF(se_ranking_status = 'succeeded', 'baseline', 'partial')
    WHEN se_ranking_status != 'succeeded' THEN 'partial'
    ELSE 'compared'
  END AS comparison_status,
  se_ranking_status,
  source_ref_hash
FROM enriched
""".strip()

def load_rows_to_bigquery(
    config: BigQueryCostConfig,
    site_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    *,
    write_disposition: str,
) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    ensure_sales_opportunity_tables(client, config)
    site_table_id = config.table_id(config.memory_dataset, "sales_opportunity_sites")
    snapshot_table_id = config.table_id(config.memory_dataset, "sales_opportunity_seo_snapshots")
    site_job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        schema=[bigquery.SchemaField(name, field_type, mode=mode) for name, field_type, mode in SALES_OPPORTUNITY_SITES_SCHEMA],
    )
    snapshot_job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        schema=[
            bigquery.SchemaField(name, field_type, mode=mode)
            for name, field_type, mode in SALES_OPPORTUNITY_SEO_SNAPSHOTS_SCHEMA
        ],
    )
    if site_rows:
        client.load_table_from_json(site_rows, site_table_id, job_config=site_job_config, location=config.default_location).result()
    if snapshot_rows:
        client.load_table_from_json(
            snapshot_rows,
            snapshot_table_id,
            job_config=snapshot_job_config,
            location=config.default_location,
        ).result()
    CappedBigQueryRunner(client, config).run_query(
        build_quarterly_comparison_sql(config),
        purpose="sales opportunity quarterly comparison refresh",
    )


def main() -> int:
    args = parse_args()
    if args.write_bigquery and args.dry_run:
        raise SystemExit("--write-bigquery cannot be combined with --dry-run")
    if args.write_bigquery or args.ensure_tables:
        load_dotenv_keys(Path(args.load_env), {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"} | SE_RANKING_ENV_KEYS)
        load_dotenv_keys(Path(args.se_ranking_env), SE_RANKING_ENV_KEYS)

    registry_path = Path(args.registry)
    quarter = parse_quarter(args.quarter)
    snapshot_date = date.fromisoformat(args.snapshot_date) if args.snapshot_date else melbourne_now().date()
    run_id = uuid4().hex
    ingested_at = melbourne_now().isoformat()
    opportunities = set(args.opportunity or []) or None
    sites = load_registry(registry_path, opportunity_slugs=opportunities)

    site_rows = [site_row(site, registry_path=registry_path, run_id=run_id, ingested_at=ingested_at) for site in sites]
    snapshot_rows = []
    statuses = []
    for site in sites:
        exports = load_se_ranking_exports(args.se_ranking_json, market=site.market)
        se_ranking = choose_se_ranking_snapshot(site, exports=exports, dry_run=args.dry_run or not args.write_bigquery)
        snapshot_rows.append(
            snapshot_row(
                site,
                quarter,
                se_ranking,
                snapshot_date=snapshot_date,
                run_id=run_id,
                ingested_at=ingested_at,
                crawl_id=args.crawl_id,
                previous_crawl_id=args.previous_crawl_id,
            )
        )
        statuses.append(
            {
                "opportunity_slug": site.opportunity_slug,
                "domain": site.domain,
                "se_ranking_status": se_ranking.status,
                "se_ranking_source": se_ranking.source,
            }
        )

    if args.ensure_tables:
        from google.cloud import bigquery

        config = BigQueryCostConfig.from_file(args.config)
        ensure_sales_opportunity_tables(bigquery.Client(project=config.project_id), config)

    if args.write_bigquery:
        config = BigQueryCostConfig.from_file(args.config)
        load_rows_to_bigquery(config, site_rows, snapshot_rows, write_disposition=args.write_disposition)

    print(
        json.dumps(
            {
                "status": "succeeded" if args.write_bigquery else "planned",
                "dry_run": bool(args.dry_run or not args.write_bigquery),
                "run_id": run_id,
                "quarter_id": quarter.quarter_id,
                "site_rows": len(site_rows),
                "snapshot_rows": len(snapshot_rows),
                "statuses": statuses,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
