#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
from dataclasses import dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.capped_query_runner import CappedBigQueryRunner
from agency_bigquery.cost_config import BigQueryCostConfig, DEFAULT_CONFIG_PATH
from agency_bigquery.agency_ops_ingestion import build_reporting_marts
from agency_bigquery.schema import (
    CLIENT_MONTHLY_API_SNAPSHOTS_SCHEMA,
    CLIENT_MONTHLY_PAGE_API_SNAPSHOTS_SCHEMA,
    ensure_monthly_api_snapshot_tables,
)

from scripts.smoke_reporting_apis import (
    DEFAULT_REPORTING_ENV,
    DEFAULT_REPORTING_ROOT,
    DEFAULT_SEO_AUTOMATION_ENV,
    DEFAULT_SE_RANKING_ENV,
    GOOGLE_ENV_KEYS,
    SE_PROJECT_TOKEN_NAMES,
    SE_RANKING_ENV_KEYS,
    google_service,
    load_clients,
    load_dotenv_keys,
    sanitized_error,
)


ORGANIC_CHANNELS = ["Organic Search", "Organic Shopping"]
AI_SOURCES = (
    "chatgpt.com",
    "chat.openai.com",
    "perplexity",
    "perplexity.ai",
    "gemini.google.com",
    "bard.google.com",
    "claude.ai",
    "copilot.microsoft.com",
    "poe.com",
    "you.com",
)
MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")


def melbourne_now() -> datetime:
    return datetime.now(MELBOURNE_TIMEZONE)


def melbourne_today() -> date:
    return melbourne_now().date()


@dataclass(frozen=True)
class MonthSpec:
    period_id: str
    month_start: str
    month_end: str


@dataclass(frozen=True)
class SourceResult:
    status: str
    rows_returned: int = 0
    metrics_by_period: dict[str, dict[str, float | None]] | None = None
    error_message: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class PageSourceResult:
    status: str
    rows_returned: int = 0
    metrics_by_period_page: dict[tuple[str, str], dict[str, float | None]] | None = None
    error_message: str | None = None
    source_ref: str | None = None


def complete_months(months: int, today: date | None = None, end_period: str | None = None) -> list[MonthSpec]:
    if months < 1:
        raise ValueError("--months must be at least 1")
    today = today or melbourne_today()
    if end_period:
        year, month = (int(part) for part in end_period.split("-", 1))
    else:
        first_this_month = today.replace(day=1)
        previous_month = add_months(first_this_month, -1)
        year, month = previous_month.year, previous_month.month
    output = []
    cursor = date(year, month, 1)
    for _ in range(months):
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = date(cursor.year, cursor.month, last_day)
        if cursor.year == today.year and cursor.month == today.month:
            month_end = min(month_end, today)
        output.append(
            MonthSpec(
                period_id=f"{cursor.year:04d}-{cursor.month:02d}",
                month_start=f"{cursor.year:04d}-{cursor.month:02d}-01",
                month_end=month_end.isoformat(),
            )
        )
        cursor = add_months(cursor, -1)
    return list(reversed(output))


def add_months(value: date, delta: int) -> date:
    month_index = value.year * 12 + value.month - 1 + delta
    year, month_zero = divmod(month_index, 12)
    return date(year, month_zero + 1, 1)


def event_metrics() -> list[dict[str, str]]:
    return [
        {"name": "sessions"},
        {"name": "totalUsers"},
        {"name": "engagedSessions"},
        {"name": "ecommercePurchases"},
        {"name": "totalRevenue"},
        {"name": "conversions"},
    ]


def metric_from(row: dict[str, Any], index: int) -> float:
    try:
        return float(row.get("metricValues", [])[index].get("value", 0))
    except Exception:
        return 0.0


def dim_from(row: dict[str, Any], index: int) -> str:
    try:
        return row.get("dimensionValues", [])[index].get("value", "")
    except Exception:
        return ""


def parse_ga4_event_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    output = {}
    for row in rows:
        raw_month = dim_from(row, 0)
        if len(raw_month) == 6 and raw_month.isdigit():
            period_id = f"{raw_month[:4]}-{raw_month[4:]}"
        else:
            continue
        sessions = metric_from(row, 0)
        users = metric_from(row, 1)
        engaged = metric_from(row, 2)
        purchases = metric_from(row, 3)
        revenue = metric_from(row, 4)
        output[period_id] = {
            "sessions": sessions,
            "users": users,
            "engaged_sessions": engaged,
            "purchases": purchases,
            "revenue": revenue,
            "conversion_rate": purchases / sessions if sessions else 0.0,
            "aov": revenue / purchases if purchases else 0.0,
        }
    return output


def normalize_page_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "/"
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        text = parsed.path or "/"
    else:
        text = text.split("?", 1)[0].split("#", 1)[0]
    if not text.startswith("/"):
        text = f"/{text}"
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    return text.lower()


def page_url_for(client: dict[str, Any], page_path: str) -> str | None:
    host = (client.get("websiteHosts") or [None])[0]
    if not host:
        return None
    scheme = "https://"
    if str(host).startswith("http://") or str(host).startswith("https://"):
        scheme = ""
    return f"{scheme}{host}{page_path}"


def collection_path_markers(client: dict[str, Any]) -> list[str]:
    configured = client.get("collectionPathContains") or client.get("collectionPathPrefixes")
    if isinstance(configured, str):
        markers = [configured]
    elif isinstance(configured, list):
        markers = [str(value) for value in configured if value]
    else:
        markers = []
    markers.extend(["/collections/", "/collection/", "/collections"])
    return [normalize_page_path(marker) for marker in markers]


def classify_page_path(client: dict[str, Any], page_path: str) -> str:
    normalized = normalize_page_path(page_path)
    if any(normalized == marker or normalized.startswith(f"{marker}/") for marker in collection_path_markers(client)):
        return "collection"
    blog_path = normalize_page_path(client.get("blogPathContains") or "/blog")
    if normalized == blog_path or normalized.startswith(f"{blog_path}/"):
        return "blog"
    return "other"


def parse_ga4_page_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float | None]]:
    output: dict[tuple[str, str], dict[str, float | None]] = {}
    for row in rows:
        raw_month = dim_from(row, 0)
        if len(raw_month) == 6 and raw_month.isdigit():
            period_id = f"{raw_month[:4]}-{raw_month[4:]}"
        else:
            continue
        page_path = normalize_page_path(dim_from(row, 1))
        sessions = metric_from(row, 0)
        users = metric_from(row, 1)
        engaged = metric_from(row, 2)
        purchases = metric_from(row, 3)
        revenue = metric_from(row, 4)
        output[(period_id, page_path)] = {
            "organic_sessions": sessions,
            "organic_users": users,
            "engaged_sessions": engaged,
            "organic_purchases": purchases,
            "organic_revenue": revenue,
            "organic_conversion_rate": purchases / sessions if sessions else 0.0,
            "organic_aov": revenue / purchases if purchases else 0.0,
        }
    return output


def host_filter(client: dict[str, Any]) -> list[dict[str, Any]]:
    hosts = client.get("websiteHosts") or []
    if not hosts:
        return []
    return [{"filter": {"fieldName": "hostName", "inListFilter": {"values": hosts, "caseSensitive": False}}}]


def organic_filter(client: dict[str, Any]) -> dict[str, Any]:
    expressions = [
        {
            "filter": {
                "fieldName": "sessionDefaultChannelGroup",
                "inListFilter": {"values": ORGANIC_CHANNELS, "caseSensitive": False},
            }
        },
        *host_filter(client),
    ]
    return {"andGroup": {"expressions": expressions}}


def ai_filter(client: dict[str, Any], *, blog_only: bool = False) -> dict[str, Any]:
    source_expressions = [
        {"filter": {"fieldName": "sessionSource", "stringFilter": {"matchType": "CONTAINS", "value": source}}}
        for source in AI_SOURCES
    ]
    expressions: list[dict[str, Any]] = [{"orGroup": {"expressions": source_expressions}}, *host_filter(client)]
    if blog_only:
        blog_path = client.get("blogPathContains") or "/blog"
        expressions.append(
            {"filter": {"fieldName": "landingPagePlusQueryString", "stringFilter": {"matchType": "CONTAINS", "value": blog_path}}}
        )
    return {"andGroup": {"expressions": expressions}} if len(expressions) > 1 else expressions[0]


def ga4_report(analytics: Any, property_id: str, start: str, end: str, dimension_filter: dict[str, Any]) -> list[dict[str, Any]]:
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": "yearMonth"}],
        "metrics": event_metrics(),
        "dimensionFilter": dimension_filter,
        "orderBys": [{"dimension": {"dimensionName": "yearMonth"}}],
        "limit": 24,
    }
    return analytics.properties().runReport(property=property_id, body=body).execute().get("rows", [])


def ga4_page_report(
    analytics: Any,
    property_id: str,
    start: str,
    end: str,
    dimension_filter: dict[str, Any],
    *,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": "yearMonth"}, {"name": "landingPagePlusQueryString"}],
        "metrics": event_metrics(),
        "dimensionFilter": dimension_filter,
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": limit,
    }
    return analytics.properties().runReport(property=property_id, body=body).execute().get("rows", [])


def collect_ga4_monthly(client: dict[str, Any], months: list[MonthSpec]) -> SourceResult:
    ga4 = client.get("ga4") or {}
    property_id = ga4.get("property")
    subject = ga4.get("subject")
    if not property_id or not subject:
        return SourceResult("missing_config")
    try:
        analytics = google_service(subject, "analyticsdata", "v1beta")
        start, end = months[0].month_start, months[-1].month_end
        organic_rows = ga4_report(analytics, property_id, start, end, organic_filter(client))
        ai_rows = ga4_report(analytics, property_id, start, end, ai_filter(client))
        ai_blog_rows = ga4_report(analytics, property_id, start, end, ai_filter(client, blog_only=True))
        organic = parse_ga4_event_rows(organic_rows)
        ai = parse_ga4_event_rows(ai_rows)
        ai_blog = parse_ga4_event_rows(ai_blog_rows)
        metrics = {}
        for month in months:
            base = organic.get(month.period_id, {})
            ai_base = ai.get(month.period_id, {})
            ai_blog_base = ai_blog.get(month.period_id, {})
            metrics[month.period_id] = {
                "organic_sessions": base.get("sessions"),
                "organic_users": base.get("users"),
                "engaged_sessions": base.get("engaged_sessions"),
                "organic_purchases": base.get("purchases"),
                "organic_revenue": base.get("revenue"),
                "organic_conversion_rate": base.get("conversion_rate"),
                "organic_aov": base.get("aov"),
                "ai_sessions": ai_base.get("sessions"),
                "ai_users": ai_base.get("users"),
                "ai_revenue": ai_base.get("revenue"),
                "ai_blog_sessions": ai_blog_base.get("sessions"),
            }
        return SourceResult("succeeded", len(organic_rows) + len(ai_rows) + len(ai_blog_rows), metrics, source_ref=property_id)
    except Exception as exc:
        _, message = sanitized_error(exc)
        return SourceResult("failed", error_message=message)


def collect_ga4_monthly_pages(client: dict[str, Any], months: list[MonthSpec]) -> PageSourceResult:
    ga4 = client.get("ga4") or {}
    property_id = ga4.get("property")
    subject = ga4.get("subject")
    if not property_id or not subject:
        return PageSourceResult("missing_config")
    try:
        analytics = google_service(subject, "analyticsdata", "v1beta")
        start, end = months[0].month_start, months[-1].month_end
        rows = ga4_page_report(analytics, property_id, start, end, organic_filter(client))
        metrics = {
            key: value
            for key, value in parse_ga4_page_rows(rows).items()
            if classify_page_path(client, key[1]) == "collection"
        }
        return PageSourceResult("succeeded", len(rows), metrics, source_ref=property_id)
    except Exception as exc:
        _, message = sanitized_error(exc)
        return PageSourceResult("failed", error_message=message)


def collect_gsc_monthly(client: dict[str, Any], months: list[MonthSpec]) -> SourceResult:
    gsc = client.get("searchConsole") or {}
    properties = gsc.get("properties") or []
    subjects = gsc.get("subjects") or []
    if not properties or not subjects:
        return SourceResult("missing_config")
    last_error = None
    for subject in subjects:
        for site_url in properties:
            try:
                searchconsole = google_service(subject, "searchconsole", "v1")
                body = {
                    "startDate": months[0].month_start,
                    "endDate": months[-1].month_end,
                    "dimensions": ["date"],
                    "rowLimit": 5000,
                }
                response = searchconsole.searchanalytics().query(siteUrl=site_url, body=body).execute()
                rows = response.get("rows", [])
                return SourceResult("succeeded", len(rows), aggregate_gsc_daily_rows(rows, months), source_ref=site_url)
            except Exception as exc:
                _, last_error = sanitized_error(exc)
                continue
    return SourceResult("failed", error_message=last_error)


def collect_gsc_monthly_single_property(client: dict[str, Any], months: list[MonthSpec]) -> SourceResult:
    gsc = client.get("searchConsole") or {}
    properties = gsc.get("properties") or []
    subjects = gsc.get("subjects") or []
    site_url = properties[0] if properties else None
    subject = subjects[0] if subjects else None
    if not site_url or not subject:
        return SourceResult("missing_config")
    try:
        searchconsole = google_service(subject, "searchconsole", "v1")
        body = {
            "startDate": months[0].month_start,
            "endDate": months[-1].month_end,
            "dimensions": ["date"],
            "rowLimit": 5000,
        }
        response = searchconsole.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = response.get("rows", [])
        return SourceResult("succeeded", len(rows), aggregate_gsc_daily_rows(rows, months), source_ref=site_url)
    except Exception as exc:
        _, message = sanitized_error(exc)
        return SourceResult("failed", error_message=message)


def aggregate_gsc_daily_rows(rows: list[dict[str, Any]], months: list[MonthSpec]) -> dict[str, dict[str, float | None]]:
    aggregates = {
        month.period_id: {"clicks": 0.0, "impressions": 0.0, "position_weight": 0.0}
        for month in months
    }
    for row in rows:
        keys = row.get("keys") or []
        if not keys:
            continue
        period_id = str(keys[0])[:7]
        if period_id not in aggregates:
            continue
        clicks = float(row.get("clicks") or 0)
        impressions = float(row.get("impressions") or 0)
        position = float(row.get("position") or 0)
        aggregates[period_id]["clicks"] += clicks
        aggregates[period_id]["impressions"] += impressions
        aggregates[period_id]["position_weight"] += position * impressions
    output = {}
    for period_id, values in aggregates.items():
        impressions = values["impressions"]
        clicks = values["clicks"]
        output[period_id] = {
            "gsc_clicks": clicks,
            "gsc_impressions": impressions,
            "gsc_ctr": clicks / impressions if impressions else None,
            "gsc_avg_position": values["position_weight"] / impressions if impressions else None,
        }
    return output


def aggregate_gsc_page_rows(rows: list[dict[str, Any]], months: list[MonthSpec]) -> dict[tuple[str, str], dict[str, float | None]]:
    period_ids = {month.period_id for month in months}
    aggregates: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        period_id = str(keys[0])[:7]
        if period_id not in period_ids:
            continue
        page_path = normalize_page_path(str(keys[1]))
        aggregate = aggregates.setdefault((period_id, page_path), {"clicks": 0.0, "impressions": 0.0, "position_weight": 0.0})
        clicks = float(row.get("clicks") or 0)
        impressions = float(row.get("impressions") or 0)
        position = float(row.get("position") or 0)
        aggregate["clicks"] += clicks
        aggregate["impressions"] += impressions
        aggregate["position_weight"] += position * impressions
    output: dict[tuple[str, str], dict[str, float | None]] = {}
    for key, values in aggregates.items():
        impressions = values["impressions"]
        clicks = values["clicks"]
        output[key] = {
            "gsc_clicks": clicks,
            "gsc_impressions": impressions,
            "gsc_ctr": clicks / impressions if impressions else None,
            "gsc_avg_position": values["position_weight"] / impressions if impressions else None,
        }
    return output


def collect_gsc_monthly_pages(client: dict[str, Any], months: list[MonthSpec]) -> PageSourceResult:
    gsc = client.get("searchConsole") or {}
    properties = gsc.get("properties") or []
    subjects = gsc.get("subjects") or []
    if not properties or not subjects:
        return PageSourceResult("missing_config")
    last_error = None
    for subject in subjects:
        for site_url in properties:
            try:
                searchconsole = google_service(subject, "searchconsole", "v1")
                body = {
                    "startDate": months[0].month_start,
                    "endDate": months[-1].month_end,
                    "dimensions": ["date", "page"],
                    "rowLimit": 25000,
                }
                response = searchconsole.searchanalytics().query(siteUrl=site_url, body=body).execute()
                rows = response.get("rows", [])
                metrics = {
                    key: value
                    for key, value in aggregate_gsc_page_rows(rows, months).items()
                    if classify_page_path(client, key[1]) == "collection"
                }
                return PageSourceResult("succeeded", len(rows), metrics, source_ref=site_url)
            except Exception as exc:
                _, last_error = sanitized_error(exc)
                continue
    return PageSourceResult("failed", error_message=last_error)


def se_project_token() -> str:
    for name in SE_PROJECT_TOKEN_NAMES:
        token = os.environ.get(name)
        if token:
            return token
    return ""


def collect_se_ranking_monthly(client: dict[str, Any], months: list[MonthSpec]) -> SourceResult:
    token = se_project_token()
    if not token:
        return SourceResult("missing_config", error_message="SE Ranking project API token is not configured")
    se = client.get("seRanking") or {}
    project_id = se.get("projectId")
    engine_id = se.get("engineId")
    if not project_id or not engine_id:
        return SourceResult("missing_config")
    try:
        import httpx

        payloads = {}
        for metric_name in ("visibility_percent", "top10_percent", "avg_pos"):
            response = httpx.get(
                "https://api.seranking.com/v1/project-management/sites/positions/history",
                params={
                    "site_id": int(project_id),
                    "site_engine_id": int(engine_id),
                    "date_from": months[0].month_start,
                    "date_to": months[-1].month_end,
                    "type": metric_name,
                },
                headers={"Authorization": f"Token {token}"},
                timeout=60,
            )
            if response.status_code in {401, 403}:
                raise RuntimeError("SE Ranking REST API rejected the configured project API token")
            response.raise_for_status()
            payloads[metric_name] = response.json() if response.content else {}
        visibility = history_metric_by_month(payloads["visibility_percent"], months)
        top10 = history_metric_by_month(payloads["top10_percent"], months)
        avg_pos = history_metric_by_month(payloads["avg_pos"], months)
        metrics = {}
        for month in months:
            metrics[month.period_id] = {
                "se_visibility_start": visibility[month.period_id]["start"],
                "se_visibility_end": visibility[month.period_id]["end"],
                "se_visibility_delta": visibility[month.period_id]["delta"],
                "se_top10_start": top10[month.period_id]["start"],
                "se_top10_end": top10[month.period_id]["end"],
                "se_top10_delta": top10[month.period_id]["delta"],
                "se_avg_position_start": avg_pos[month.period_id]["start"],
                "se_avg_position_end": avg_pos[month.period_id]["end"],
                "se_avg_position_delta": avg_pos[month.period_id]["delta"],
            }
        rows_returned = sum(len(history_points(payload)) for payload in payloads.values())
        return SourceResult("succeeded", rows_returned, metrics)
    except Exception as exc:
        _, message = sanitized_error(exc)
        return SourceResult("failed", error_message=message)


def history_points(payload: Any) -> list[tuple[str, float]]:
    if isinstance(payload, dict):
        data = payload.get("data", [])
    else:
        data = payload
    if isinstance(data, list) and data and isinstance(data[0], dict) and isinstance(data[0].get("data"), list):
        selected = next((row for row in data if row.get("type") == "search_engine"), data[0])
        data = selected.get("data", [])
    points = []
    if not isinstance(data, list):
        return points
    for row in data:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date") or row.get("datetime") or row.get("day")
        raw_value = row.get("value")
        if raw_value is None:
            raw_value = row.get("val") or row.get("avg_pos") or row.get("visibility") or row.get("top10")
        if not raw_date or raw_value in (None, ""):
            continue
        try:
            points.append((str(raw_date)[:10], float(raw_value)))
        except (TypeError, ValueError):
            continue
    return sorted(points)


def history_metric_by_month(payload: Any, months: list[MonthSpec]) -> dict[str, dict[str, float | None]]:
    points = history_points(payload)
    output = {}
    for month in months:
        selected = [(day, value) for day, value in points if month.month_start <= day <= month.month_end]
        if not selected:
            output[month.period_id] = {"start": None, "end": None, "delta": None}
            continue
        start = selected[0][1]
        end = selected[-1][1]
        output[month.period_id] = {"start": start, "end": end, "delta": end - start}
    return output


def build_snapshot_rows(
    client: dict[str, Any],
    months: list[MonthSpec],
    run_id: str,
    ingested_at: str,
    ga4: SourceResult,
    gsc: SourceResult,
    se_ranking: SourceResult,
) -> list[dict[str, Any]]:
    rows = []
    for month in months:
        ga4_metrics = (ga4.metrics_by_period or {}).get(month.period_id, {})
        gsc_metrics = (gsc.metrics_by_period or {}).get(month.period_id, {})
        se_metrics = (se_ranking.metrics_by_period or {}).get(month.period_id, {})
        rows.append(
            {
                "ingested_at": ingested_at,
                "run_id": run_id,
                "period_id": month.period_id,
                "month_start": month.month_start,
                "month_end": month.month_end,
                "client_slug": client.get("slug") or "",
                "client_name": client.get("name") or client.get("slug") or "",
                "ga4_property": ga4.source_ref or (client.get("ga4") or {}).get("property"),
                "gsc_site_url": gsc.source_ref or ((client.get("searchConsole") or {}).get("properties") or [None])[0],
                "se_ranking_project_id": str((client.get("seRanking") or {}).get("projectId") or "") or None,
                "se_ranking_engine_id": str((client.get("seRanking") or {}).get("engineId") or "") or None,
                "ga4_status": ga4.status,
                "gsc_status": gsc.status,
                "se_ranking_status": se_ranking.status,
                **ga4_metrics,
                **gsc_metrics,
                **se_metrics,
                "ga4_rows_returned": ga4.rows_returned,
                "gsc_rows_returned": gsc.rows_returned,
                "se_ranking_rows_returned": se_ranking.rows_returned,
                "ga4_error": ga4.error_message,
                "gsc_error": gsc.error_message,
                "se_ranking_error": se_ranking.error_message,
            }
        )
    return rows


def build_page_snapshot_rows(
    client: dict[str, Any],
    months: list[MonthSpec],
    run_id: str,
    ingested_at: str,
    ga4_pages: PageSourceResult,
    gsc_pages: PageSourceResult,
) -> list[dict[str, Any]]:
    rows = []
    month_by_period = {month.period_id: month for month in months}
    page_keys = set((ga4_pages.metrics_by_period_page or {}).keys()) | set((gsc_pages.metrics_by_period_page or {}).keys())
    for period_id, page_path in sorted(page_keys):
        month = month_by_period.get(period_id)
        if not month:
            continue
        page_type = classify_page_path(client, page_path)
        if page_type != "collection":
            continue
        ga4_metrics = (ga4_pages.metrics_by_period_page or {}).get((period_id, page_path), {})
        gsc_metrics = (gsc_pages.metrics_by_period_page or {}).get((period_id, page_path), {})
        rows.append(
            {
                "ingested_at": ingested_at,
                "run_id": run_id,
                "period_id": month.period_id,
                "month_start": month.month_start,
                "month_end": month.month_end,
                "client_slug": client.get("slug") or "",
                "client_name": client.get("name") or client.get("slug") or "",
                "page_path": page_path,
                "page_url": page_url_for(client, page_path),
                "page_type": page_type,
                "ga4_property": ga4_pages.source_ref or (client.get("ga4") or {}).get("property"),
                "gsc_site_url": gsc_pages.source_ref or ((client.get("searchConsole") or {}).get("properties") or [None])[0],
                "ga4_status": ga4_pages.status,
                "gsc_status": gsc_pages.status,
                **ga4_metrics,
                **gsc_metrics,
                "ga4_rows_returned": ga4_pages.rows_returned,
                "gsc_rows_returned": gsc_pages.rows_returned,
                "ga4_error": ga4_pages.error_message,
                "gsc_error": gsc_pages.error_message,
            }
        )
    return rows


def build_history_mart(runner: CappedBigQueryRunner, config: BigQueryCostConfig) -> str:
    project = config.project_id
    memory = config.memory_dataset
    reporting = config.reporting_dataset
    sql = f"""
CREATE OR REPLACE TABLE `{project}.{reporting}.client_monthly_performance_history`
PARTITION BY month_start
CLUSTER BY client_slug AS
SELECT
  period_id,
  month_start,
  month_end,
  client_slug,
  client_name,
  ga4_status,
  gsc_status,
  se_ranking_status,
  organic_sessions,
  organic_users,
  engaged_sessions,
  organic_purchases,
  organic_revenue,
  organic_conversion_rate,
  organic_aov,
  ai_sessions,
  ai_users,
  ai_revenue,
  ai_blog_sessions,
  gsc_clicks,
  gsc_impressions,
  gsc_ctr,
  gsc_avg_position,
  se_visibility_start,
  se_visibility_end,
  se_visibility_delta,
  se_top10_start,
  se_top10_end,
  se_top10_delta,
  se_avg_position_start,
  se_avg_position_end,
  se_avg_position_delta
FROM `{project}.{memory}.client_monthly_api_snapshots`
"""
    result, _ = runner.run_query(sql, purpose="monthly-api-snapshots: build performance history mart")
    return result.status


def load_rows_to_bigquery(
    config: BigQueryCostConfig,
    rows: list[dict[str, Any]],
    page_rows: list[dict[str, Any]],
    write_disposition: str,
) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    ensure_monthly_api_snapshot_tables(client, config)
    table_id = config.table_id(config.memory_dataset, "client_monthly_api_snapshots")
    job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        schema=[bigquery.SchemaField(name, field_type, mode=mode) for name, field_type, mode in CLIENT_MONTHLY_API_SNAPSHOTS_SCHEMA],
    )
    job = client.load_table_from_json(rows, table_id, job_config=job_config, location=config.default_location)
    job.result()
    page_table_id = config.table_id(config.memory_dataset, "client_monthly_page_api_snapshots")
    page_job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        schema=[bigquery.SchemaField(name, field_type, mode=mode) for name, field_type, mode in CLIENT_MONTHLY_PAGE_API_SNAPSHOTS_SCHEMA],
    )
    page_job = client.load_table_from_json(page_rows, page_table_id, job_config=page_job_config, location=config.default_location)
    page_job.result()
    build_reporting_marts(CappedBigQueryRunner(client, config), config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull 13 complete monthly GA4/GSC/SE Ranking snapshots into BigQuery.")
    parser.add_argument("--months", type=int, default=13)
    parser.add_argument("--end-period", help="Optional final complete month YYYY-MM. Defaults to the previous calendar month.")
    parser.add_argument("--client", action="append", help="Limit to one or more reporting client slugs.")
    parser.add_argument("--reporting-root", type=Path, default=DEFAULT_REPORTING_ROOT)
    parser.add_argument("--google-env", type=Path, default=DEFAULT_SEO_AUTOMATION_ENV)
    parser.add_argument("--reporting-env", type=Path, default=DEFAULT_REPORTING_ENV)
    parser.add_argument("--se-ranking-env", type=Path, default=DEFAULT_SE_RANKING_ENV)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Print planned clients/months without API calls or BigQuery writes.")
    parser.add_argument("--write-disposition", default="WRITE_TRUNCATE", choices=("WRITE_TRUNCATE", "WRITE_APPEND"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    months = complete_months(args.months, end_period=args.end_period)
    clients = load_clients(args.reporting_root)
    if args.client:
        wanted = set(args.client)
        clients = [client for client in clients if client.get("slug") in wanted]
    clients = [client for client in clients if client.get("slug")]
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "planned",
                    "client_count": len(clients),
                    "clients": [client.get("slug") for client in clients],
                    "months": [month.period_id for month in months],
                    "expected_rows": len(clients) * len(months),
                },
                indent=2,
            )
        )
        return 0

    load_dotenv_keys(args.google_env, GOOGLE_ENV_KEYS)
    load_dotenv_keys(args.reporting_env, GOOGLE_ENV_KEYS | SE_RANKING_ENV_KEYS)
    load_dotenv_keys(args.se_ranking_env, SE_RANKING_ENV_KEYS)

    run_id = uuid4().hex
    ingested_at = melbourne_now().isoformat()
    rows = []
    page_rows = []
    statuses = []
    for client in clients:
        ga4 = collect_ga4_monthly(client, months)
        gsc = collect_gsc_monthly(client, months)
        se_ranking = collect_se_ranking_monthly(client, months)
        ga4_pages = collect_ga4_monthly_pages(client, months)
        gsc_pages = collect_gsc_monthly_pages(client, months)
        rows.extend(build_snapshot_rows(client, months, run_id, ingested_at, ga4, gsc, se_ranking))
        page_rows.extend(build_page_snapshot_rows(client, months, run_id, ingested_at, ga4_pages, gsc_pages))
        statuses.append(
            {
                "client_slug": client.get("slug"),
                "ga4": ga4.status,
                "gsc": gsc.status,
                "se_ranking": se_ranking.status,
                "ga4_pages": ga4_pages.status,
                "gsc_pages": gsc_pages.status,
            }
        )

    config = BigQueryCostConfig.from_file(args.config)
    load_rows_to_bigquery(config, rows, page_rows, args.write_disposition)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "run_id": run_id,
                "client_count": len(clients),
                "month_count": len(months),
                "rows_loaded": len(rows),
                "page_rows_loaded": len(page_rows),
                "month_start": months[0].month_start,
                "month_end": months[-1].month_end,
                "source_statuses": statuses,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
