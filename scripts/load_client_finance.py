#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import calendar
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agency_ops_ingestion import build_finance_reporting_mart, canonical_client_slug, utc_now_iso  # noqa: E402
from agency_bigquery.capped_query_runner import CappedBigQueryRunner  # noqa: E402
from agency_bigquery.cost_config import DEFAULT_CONFIG_PATH, BigQueryCostConfig  # noqa: E402
from agency_bigquery.schema import ensure_finance_memory_tables  # noqa: E402


SAFE_ENV_KEYS = {"GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"}
DEFAULT_ENV_PATH = Path("/Users/laurencedeer/Projects/Codex/SEO Automation/.env")
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "finance" / "client_retainers_2026.json"
DEFAULT_CLIENT_BOARD_SNAPSHOT_PATH = Path("/Users/laurencedeer/Projects/Codex/monday-agency-hub/data/snapshots/board_5026765711.json")
DEFAULT_EXPENSES_SNAPSHOT_PATH = Path("/Users/laurencedeer/Projects/Codex/monday-agency-hub/data/snapshots/board_5027236764.json")
SOURCE_ID = "local_client_retainers_2026"
CLIENT_BOARD_SOURCE_ID = "monday_client_board"
EXPENSE_SOURCE_ID = "monday_expenses_board"
ALLOWED_STATUSES = {"not_client", "paid", "issued", "not_issued", "planned"}


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
    parser = argparse.ArgumentParser(description="Load local client finance retainers into BigQuery agency memory.")
    parser.add_argument("--input-json", default=str(DEFAULT_INPUT_PATH), help="Structured finance JSON path.")
    parser.add_argument("--client-board-snapshot-json", default=str(DEFAULT_CLIENT_BOARD_SNAPSHOT_PATH), help="Local monday-agency-hub Client Board snapshot JSON.")
    parser.add_argument("--expenses-snapshot-json", default=str(DEFAULT_EXPENSES_SNAPSHOT_PATH), help="Local monday-agency-hub Expenses board snapshot JSON.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to BigQuery cost guardrail config.")
    parser.add_argument("--load-env", default=str(DEFAULT_ENV_PATH), help="Optional .env path. Only Google credential keys are loaded.")
    parser.add_argument("--run-id", default=None, help="Optional load run ID. Defaults to generated UUID hex.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print counts without writing to BigQuery.")
    return parser.parse_args()


def safe_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid amount: {value!r}")


def month_start(period_id: str) -> str:
    try:
        parsed = datetime.strptime(period_id, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"Invalid period_id {period_id!r}; expected YYYY-MM") from exc
    return parsed.strftime("%Y-%m-01")


def current_period_id() -> str:
    return datetime.now().astimezone().strftime("%Y-%m")


def month_end(period_id: str) -> str:
    parsed = datetime.strptime(period_id, "%Y-%m")
    last_day = calendar.monthrange(parsed.year, parsed.month)[1]
    return f"{period_id}-{last_day:02d}"


def month_end_date(period_id: str) -> datetime.date:
    return datetime.strptime(month_end(period_id), "%Y-%m-%d").date()


def validate_text(value: object, *, field: str, max_length: int = 160) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_length:
        raise ValueError(f"{field} is too long")
    if "@" in text or "://" in text:
        raise ValueError(f"{field} must not contain private contact or URL-like text")
    return text


def parse_finance_rows(path: Path, *, run_id: str, ingested_at: str) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Finance JSON must contain a rows list")
    output: list[dict] = []
    current_period = current_period_id()
    for client in rows:
        if not isinstance(client, dict):
            raise ValueError("Each finance client row must be an object")
        client_label = validate_text(client.get("client_label"), field="client_label")
        client_slug = canonical_client_slug(client.get("client_slug") or client_label)
        months = client.get("months")
        if not isinstance(months, dict):
            raise ValueError(f"{client_label} months must be an object")
        for period_id, month in sorted(months.items()):
            if not isinstance(month, dict):
                raise ValueError(f"{client_label} {period_id} month row must be an object")
            status = str(month.get("status") or "").strip().lower()
            if status not in ALLOWED_STATUSES:
                raise ValueError(f"{client_label} {period_id} has invalid status {status!r}")
            retainer = safe_float(month.get("retainer_amount_aud"))
            expense = safe_float(month.get("expense_amount_aud"))
            if retainer < 0 or expense < 0:
                raise ValueError(f"{client_label} {period_id} amounts must be non-negative")
            is_billable = retainer > 0 and status != "not_client"
            notes = month.get("notes")
            output.append(
                {
                    "ingested_at": ingested_at,
                    "run_id": run_id,
                    "source_id": SOURCE_ID,
                    "source_path": str(path),
                    "period_id": str(period_id),
                    "month_start": month_start(str(period_id)),
                    "client_slug": client_slug,
                    "client_label": client_label,
                    "billing_status": status,
                    "retainer_amount_aud": retainer,
                    "expense_amount_aud": expense,
                    "net_amount_aud": retainer - expense,
                    "is_billable": is_billable,
                    "is_due": is_billable and str(period_id) <= current_period,
                    "is_paid": status == "paid",
                    "is_issued": status in {"paid", "issued"},
                    "notes": validate_text(notes, field="notes", max_length=240) if notes else None,
                }
            )
    return output


def parse_additional_amount(value: str) -> float:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0.0
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    if not matches:
        return 0.0
    return sum(float(match) for match in matches)


def column_text(item: dict, column_id: str) -> str:
    for value in item.get("column_values", []):
        if value.get("id") == column_id:
            return str(value.get("text") or "").strip()
    return ""


def safe_optional_date(value: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid Monday expense date: {value!r}") from exc
    return value


def monday_board(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    boards = payload.get("boards") or payload.get("data", {}).get("boards")
    if boards:
        return boards[0]
    return payload


def parse_monday_client_board_rows(path: Path, *, run_id: str, ingested_at: str, periods: list[str], base_rows: list[dict]) -> list[dict]:
    if not path.exists():
        return []
    board = monday_board(path)
    items = board.get("items_page", {}).get("items") or []
    existing_by_client_period = {(row["client_slug"], row["period_id"]): row for row in base_rows}
    current_period = current_period_id()
    rows: list[dict] = []
    for item in items:
        group_title = str((item.get("group") or {}).get("title") or "").strip().lower()
        if group_title != "current clients":
            continue
        client_label = validate_text(item.get("name"), field="client_label")
        client_slug = canonical_client_slug(client_label)
        retainer_text = column_text(item, "numeric_mm0tfsvq")
        if not retainer_text:
            continue
        retainer = safe_float(retainer_text.replace(",", ""))
        retainer += parse_additional_amount(column_text(item, "text_mm2tew4n"))
        if retainer <= 0:
            continue
        start_date = safe_optional_date(column_text(item, "date4"))
        invoice_agreement = column_text(item, "text_mm0z9mb9")
        if invoice_agreement:
            invoice_agreement = validate_text(invoice_agreement, field="invoice_agreement", max_length=120)
        for period_id in periods:
            if period_id < current_period:
                continue
            if start_date and datetime.strptime(start_date, "%Y-%m-%d").date() > month_end_date(period_id):
                continue
            existing = existing_by_client_period.get((client_slug, period_id), {})
            if period_id == current_period and existing.get("billing_status") in {"paid", "issued", "not_issued"}:
                status = existing["billing_status"]
            else:
                status = "planned" if period_id > current_period else "not_issued"
            notes = f"Monday Client Board retainer"
            if invoice_agreement:
                notes = f"{notes}; {invoice_agreement}"
            is_billable = retainer > 0
            rows.append(
                {
                    "ingested_at": ingested_at,
                    "run_id": run_id,
                    "source_id": CLIENT_BOARD_SOURCE_ID,
                    "source_path": str(path),
                    "period_id": period_id,
                    "month_start": month_start(period_id),
                    "client_slug": client_slug,
                    "client_label": client_label,
                    "billing_status": status,
                    "retainer_amount_aud": retainer,
                    "expense_amount_aud": safe_float(existing.get("expense_amount_aud")),
                    "net_amount_aud": retainer - safe_float(existing.get("expense_amount_aud")),
                    "is_billable": is_billable,
                    "is_due": is_billable and period_id <= current_period,
                    "is_paid": status == "paid",
                    "is_issued": status in {"paid", "issued"},
                    "notes": notes,
                }
            )
    return rows


def overlay_rows(base_rows: list[dict], overlay: list[dict]) -> list[dict]:
    merged = {(row["client_slug"], row["period_id"]): row for row in base_rows}
    for row in overlay:
        merged[(row["client_slug"], row["period_id"])] = row
    return sorted(merged.values(), key=lambda row: (row["period_id"], row["client_label"]))


def parse_expense_rows(path: Path, *, run_id: str, ingested_at: str, periods: list[str]) -> list[dict]:
    if not path.exists():
        return []
    board = monday_board(path)
    items = board.get("items_page", {}).get("items") or []
    rows: list[dict] = []
    for item in items:
        name = validate_text(item.get("name"), field="expense_name")
        cost_text = column_text(item, "numeric_mm1gf6c7")
        if not cost_text:
            continue
        cost = safe_float(cost_text.replace(",", ""))
        if cost <= 0:
            continue
        start_date = safe_optional_date(column_text(item, "date4"))
        renewal_date = safe_optional_date(column_text(item, "date_mm0t4anx"))
        schedule_date = safe_optional_date(column_text(item, "date_mm0zjh60"))
        agreement = column_text(item, "text_mm0z9mb9") or None
        if agreement:
            agreement = validate_text(agreement, field="invoice_agreement", max_length=240)
        for period_id in periods:
            period_start = month_start(period_id)
            period_end = month_end(period_id)
            active = (not start_date or start_date <= period_end) and (not renewal_date or renewal_date >= period_start)
            rows.append(
                {
                    "ingested_at": ingested_at,
                    "run_id": run_id,
                    "source_id": EXPENSE_SOURCE_ID,
                    "source_path": str(path),
                    "period_id": period_id,
                    "month_start": period_start,
                    "expense_item_id": str(item.get("id") or ""),
                    "expense_name": name,
                    "cost_per_month_aud": cost,
                    "start_date": start_date,
                    "renewal_date": renewal_date,
                    "invoicing_schedule_date": schedule_date,
                    "invoice_agreement": agreement,
                    "is_active": active,
                }
            )
    return rows


def load_rows(client, table_id: str, rows: list[dict], *, location: str, write_disposition: str) -> int:
    if not rows:
        return 0
    from google.cloud import bigquery

    job_config = bigquery.LoadJobConfig(write_disposition=write_disposition)
    job = client.load_table_from_json(rows, table_id, job_config=job_config, location=location)
    job.result()
    return len(rows)


def log_ingestion_run(client, config: BigQueryCostConfig, *, run_id: str, started_at: str, status: str, source_path: Path, rows_loaded: int, error_message: str | None = None) -> None:
    row = {
        "run_id": run_id,
        "source_id": SOURCE_ID,
        "started_at": started_at,
        "completed_at": utc_now_iso(),
        "status": status,
        "source_path": str(source_path),
        "destination_table": config.table_id(config.memory_dataset, "client_finance_monthly"),
        "rows_loaded": rows_loaded,
        "error_message": error_message,
    }
    errors = client.insert_rows_json(config.table_id(config.control_dataset, "ingestion_runs"), [row])
    if errors:
        raise RuntimeError(f"Could not log ingestion run: {errors}")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_json)
    client_board_path = Path(args.client_board_snapshot_json)
    expenses_path = Path(args.expenses_snapshot_json)
    if not input_path.exists():
        print(f"Input JSON does not exist: {input_path}", file=sys.stderr)
        return 2
    run_id = args.run_id or uuid4().hex
    started_at = utc_now_iso()
    try:
        base_rows = parse_finance_rows(input_path, run_id=run_id, ingested_at=started_at)
        periods = sorted({row["period_id"] for row in base_rows})
        monday_retainer_rows = parse_monday_client_board_rows(client_board_path, run_id=run_id, ingested_at=started_at, periods=periods, base_rows=base_rows)
        rows = overlay_rows(base_rows, monday_retainer_rows)
        expense_rows = parse_expense_rows(expenses_path, run_id=run_id, ingested_at=started_at, periods=periods)
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "validation_failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 3
    summary = {
        "status": "validated",
        "run_id": run_id,
        "source_id": SOURCE_ID,
        "rows": len(rows),
        "clients": len({row["client_slug"] for row in rows}),
        "months": len({row["period_id"] for row in rows}),
        "retainer_total_aud": sum(row["retainer_amount_aud"] for row in rows if row["is_billable"]),
        "client_expense_total_aud": sum(row["expense_amount_aud"] for row in rows if row["is_billable"]),
        "monday_retainer_rows": len(monday_retainer_rows),
        "monday_retainer_total_aud": sum(row["retainer_amount_aud"] for row in monday_retainer_rows if row["is_billable"]),
        "monday_expense_rows": len(expense_rows),
        "monday_monthly_expense_total_aud": sum(row["cost_per_month_aud"] for row in expense_rows if row["is_active"]),
    }
    if args.dry_run:
        print(json.dumps(summary, indent=2))
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
    ensure_finance_memory_tables(client, config)
    table_id = config.table_id(config.memory_dataset, "client_finance_monthly")
    expenses_table_id = config.table_id(config.memory_dataset, "agency_expenses_monthly")
    try:
        loaded = load_rows(client, table_id, rows, location=config.default_location, write_disposition="WRITE_TRUNCATE")
        expense_loaded = load_rows(client, expenses_table_id, expense_rows, location=config.default_location, write_disposition="WRITE_TRUNCATE")
        mart_statuses = build_finance_reporting_mart(CappedBigQueryRunner(client, config), config)
        log_ingestion_run(client, config, run_id=run_id, started_at=started_at, status="succeeded", source_path=input_path, rows_loaded=loaded)
    except Exception as exc:
        log_ingestion_run(
            client,
            config,
            run_id=run_id,
            started_at=started_at,
            status="failed",
            source_path=input_path,
            rows_loaded=0,
            error_message=f"{type(exc).__name__}: {str(exc)[:400]}",
        )
        raise
    print(json.dumps({**summary, "status": "succeeded", "rows_loaded": loaded, "expense_rows_loaded": expense_loaded, "mart_statuses": mart_statuses}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
