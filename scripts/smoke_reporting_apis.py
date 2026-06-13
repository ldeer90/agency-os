#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.cost_config import BigQueryCostConfig, DEFAULT_CONFIG_PATH
from agency_bigquery.schema import ensure_api_smoke_checks_table


PROJECTS_ROOT = Path("/Users/laurencedeer/Projects/Codex")
DEFAULT_SEO_AUTOMATION_ENV = PROJECTS_ROOT / "SEO Automation" / ".env"
DEFAULT_REPORTING_ROOT = PROJECTS_ROOT / "seo-reporting-platform"
DEFAULT_REPORTING_ENV = DEFAULT_REPORTING_ROOT / ".env.local"
DEFAULT_SE_RANKING_ENV = Path.home() / ".codex" / "se-ranking-env.zsh"

GOOGLE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
SE_RANKING_ENV_KEYS = {"SE_RANKING_API_KEY", "PROJECT_API_TOKEN", "DATA_API_TOKEN"}
SE_PROJECT_TOKEN_NAMES = ("SE_RANKING_API_KEY", "PROJECT_API_TOKEN")
SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]


@dataclass(frozen=True)
class SmokeResult:
    checked_at: str
    client_slug: str
    source: str
    status: str
    date_start: str
    date_end: str
    rows_returned: int | None = None
    error_class: str | None = None
    error_message: str | None = None


def load_dotenv_keys(path: Path, allowed_keys: set[str]) -> list[str]:
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8").splitlines():
        assignment = parse_assignment(line, allowed_keys)
        if not assignment:
            continue
        key, value = assignment
        if key == "GOOGLE_APPLICATION_CREDENTIALS":
            credential_path = Path(os.path.expanduser(os.path.expandvars(value)))
            if not credential_path.is_absolute():
                credential_path = path.parent / credential_path
            value = str(credential_path.resolve())
        os.environ[key] = value
        loaded.append(key)
    return loaded


def parse_assignment(line: str, allowed_keys: set[str]) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    try:
        parts = shlex.split(stripped, comments=True, posix=True)
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] == "export":
        parts = parts[1:]
    if len(parts) != 1 or "=" not in parts[0]:
        return None
    key, value = parts[0].split("=", 1)
    if key not in allowed_keys:
        return None
    return key, value


def load_clients(reporting_root: Path) -> list[dict[str, Any]]:
    path = reporting_root / "config" / "clients.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    clients = payload.get("clients") if isinstance(payload, dict) else payload
    if not isinstance(clients, list):
        return []
    return [client for client in clients if isinstance(client, dict)]


def find_client(reporting_root: Path, client_slug: str) -> dict[str, Any]:
    for client in load_clients(reporting_root):
        if client.get("slug") == client_slug:
            return client
    raise RuntimeError(f"Client slug not found in reporting config: {client_slug}")


def month_range(period_id: str) -> tuple[str, str]:
    year, month = (int(part) for part in period_id.split("-", 1))
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def latest_report_range(reporting_root: Path, client_slug: str) -> tuple[str, str, str]:
    matches: list[tuple[str, str, str]] = []
    for path in sorted((reporting_root / "content" / "reports").glob("*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        client = payload.get("client") or {}
        if client.get("slug") != client_slug:
            continue
        period = client.get("period") or path.parent.name
        if isinstance(period, dict):
            period_id = period.get("id") or path.parent.name
            start = period.get("start")
            end = period.get("end")
            if start and end:
                matches.append((str(period_id), str(start), str(end)))
                continue
        period_id = str(period)
        start, end = month_range(period_id)
        matches.append((period_id, start, end))
    if not matches:
        previous_month = date.today().replace(day=1)
        month = previous_month.month - 1 or 12
        year = previous_month.year if previous_month.month > 1 else previous_month.year - 1
        period_id = f"{year:04d}-{month:02d}"
        start, end = month_range(period_id)
        return period_id, start, end
    return sorted(matches)[-1]


def google_service(subject: str, service_name: str, version: str) -> Any:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install google-api-python-client before running Google API smoke checks.") from exc

    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not configured")
    credentials = service_account.Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return build(service_name, version, credentials=credentials.with_subject(subject), cache_discovery=False)


def ga4_smoke(client: dict[str, Any], start: str, end: str) -> int:
    ga4 = client.get("ga4") or {}
    property_id = ga4.get("property")
    subject = ga4.get("subject")
    if not property_id or not subject:
        raise RuntimeError("Client GA4 property or subject is missing")
    analytics = google_service(subject, "analyticsdata", "v1beta")
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": "sessions"}],
        "limit": 1,
    }
    response = analytics.properties().runReport(property=property_id, body=body).execute()
    return len(response.get("rows", []))


def gsc_smoke(client: dict[str, Any], start: str, end: str) -> int:
    gsc = client.get("searchConsole") or {}
    properties = gsc.get("properties") or []
    subjects = gsc.get("subjects") or []
    if not properties or not subjects:
        raise RuntimeError("Client Search Console property or subject is missing")
    last_error: Exception | None = None
    for subject in subjects:
        for site_url in properties:
            try:
                searchconsole = google_service(subject, "searchconsole", "v1")
                body = {"startDate": start, "endDate": end, "dimensions": ["date"], "rowLimit": 1}
                response = searchconsole.searchanalytics().query(siteUrl=site_url, body=body).execute()
                return len(response.get("rows", []))
            except Exception as exc:
                last_error = exc
                continue
    if last_error:
        raise last_error
    raise RuntimeError("No Search Console property/subject combinations were checked")


def se_project_token() -> str:
    for name in SE_PROJECT_TOKEN_NAMES:
        token = os.environ.get(name)
        if token:
            return token
    return ""


def se_ranking_smoke(client: dict[str, Any], start: str, end: str) -> int:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install httpx before running SE Ranking smoke checks.") from exc

    token = se_project_token()
    if not token:
        raise RuntimeError("SE Ranking project API token is not configured")
    se = client.get("seRanking") or {}
    project_id = se.get("projectId")
    engine_id = se.get("engineId")
    if not project_id or not engine_id:
        raise RuntimeError("Client SE Ranking project or engine ID is missing")
    response = httpx.get(
        "https://api.seranking.com/v1/project-management/sites/positions/history",
        params={
            "site_id": int(project_id),
            "site_engine_id": int(engine_id),
            "date_from": start,
            "date_to": end,
            "type": "visibility_percent",
        },
        headers={"Authorization": f"Token {token}"},
        timeout=45,
    )
    if response.status_code in {401, 403}:
        raise RuntimeError("SE Ranking REST API rejected the configured project API token")
    response.raise_for_status()
    payload = response.json() if response.content else {}
    data = payload.get("data", []) if isinstance(payload, dict) else payload
    return len(data) if isinstance(data, list) else 0


def sanitized_error(exc: Exception) -> tuple[str, str]:
    message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    message = re.sub(r"Token\s+[A-Za-z0-9._~+/=-]+", "Token [redacted]", message)
    message = re.sub(r"(api[_-]?key|token|secret|password)=([^&\s]+)", r"\1=[redacted]", message, flags=re.IGNORECASE)
    message = re.sub(r"-----BEGIN[^\\n]+", "[redacted-private-key]", message)
    return type(exc).__name__, message[:400]


def run_check(source: str, client: dict[str, Any], client_slug: str, start: str, end: str) -> SmokeResult:
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        if source == "ga4":
            rows_returned = ga4_smoke(client, start, end)
        elif source == "gsc":
            rows_returned = gsc_smoke(client, start, end)
        elif source == "se_ranking":
            rows_returned = se_ranking_smoke(client, start, end)
        else:
            raise RuntimeError(f"Unknown smoke source: {source}")
        return SmokeResult(checked_at, client_slug, source, "succeeded", start, end, rows_returned)
    except Exception as exc:
        error_class, error_message = sanitized_error(exc)
        return SmokeResult(checked_at, client_slug, source, "failed", start, end, None, error_class, error_message)


def log_results_to_bigquery(results: list[SmokeResult], config_path: Path) -> None:
    from google.cloud import bigquery

    config = BigQueryCostConfig.from_file(config_path)
    client = bigquery.Client(project=config.project_id)
    ensure_api_smoke_checks_table(client, config)
    rows = [asdict(result) for result in results]
    errors = client.insert_rows_json(config.table_id(config.control_dataset, "api_smoke_checks"), rows)
    if errors:
        raise RuntimeError(f"Could not log API smoke checks: {errors}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only smoke checks for GA4, Search Console, and SE Ranking.")
    parser.add_argument("--client", default="shop-rongrong", help="Client slug from seo-reporting-platform/config/clients.json.")
    parser.add_argument("--period", help="Optional YYYY-MM period. Defaults to the latest local report for the client.")
    parser.add_argument("--reporting-root", type=Path, default=DEFAULT_REPORTING_ROOT)
    parser.add_argument("--google-env", type=Path, default=DEFAULT_SEO_AUTOMATION_ENV)
    parser.add_argument("--reporting-env", type=Path, default=DEFAULT_REPORTING_ENV)
    parser.add_argument("--se-ranking-env", type=Path, default=DEFAULT_SE_RANKING_ENV)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--source", action="append", choices=("ga4", "gsc", "se_ranking"), help="Limit to one or more sources.")
    parser.add_argument("--log-bigquery", action="store_true", help="Write sanitized smoke results to agency_control.api_smoke_checks.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv_keys(args.google_env, GOOGLE_ENV_KEYS)
    load_dotenv_keys(args.reporting_env, GOOGLE_ENV_KEYS | SE_RANKING_ENV_KEYS)
    load_dotenv_keys(args.se_ranking_env, SE_RANKING_ENV_KEYS)

    client = find_client(args.reporting_root, args.client)
    if args.period:
        period_id = args.period
        start, end = month_range(period_id)
    else:
        period_id, start, end = latest_report_range(args.reporting_root, args.client)

    sources = args.source or ["ga4", "gsc", "se_ranking"]
    results = [run_check(source, client, args.client, start, end) for source in sources]
    log_error = None
    if args.log_bigquery:
        try:
            log_results_to_bigquery(results, args.config)
        except Exception as exc:
            error_class, error_message = sanitized_error(exc)
            log_error = {"error_class": error_class, "error_message": error_message}

    print(
        json.dumps(
            {
                "client_slug": args.client,
                "period_id": period_id,
                "date_start": start,
                "date_end": end,
                "bigquery_log_error": log_error,
                "results": [asdict(result) for result in results],
            },
            indent=2,
        )
    )
    return 0 if all(result.status == "succeeded" for result in results) and log_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
