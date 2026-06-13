from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
from typing import Any

from .capped_query_runner import CappedBigQueryRunner
from .cost_config import BigQueryCostConfig
from .schema import TableSpec, agent_operating_table_specs, ensure_tables


DEFAULT_MAX_ROWS_PER_BATCH = 500
DEFAULT_MAX_ROW_BYTES = 256 * 1024
DEFAULT_MAX_BATCH_BYTES = 5 * 1024 * 1024
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AgentLoggingError(ValueError):
    """Raised when a BigQuery logging batch fails local safety validation."""


@dataclass(frozen=True)
class LoggingTablePlan:
    logical_name: str
    spec: TableSpec
    merge_keys: tuple[str, ...]

    def table_id(self, config: BigQueryCostConfig) -> str:
        return config.table_id(self.spec.dataset, self.spec.table)


@dataclass(frozen=True)
class LoggingResult:
    table: str
    destination_table_id: str
    rows: int
    dry_run: bool
    staging_table_id: str | None = None
    merge_job_id: str | None = None


def agent_logging_table_plans(config: BigQueryCostConfig) -> dict[str, LoggingTablePlan]:
    specs = {spec.table: spec for spec in agent_operating_table_specs(config)}
    merge_keys = {
        "agent_run_log": ("run_id",),
        "llm_usage_log": ("run_id", "agent_id", "logged_at"),
        "agent_findings": ("finding_id",),
        "agent_actions": ("action_id",),
        "agent_approvals": ("approval_id",),
        "context_packs": ("context_id",),
        "seo_workflow_catalog": ("skill_id", "workflow_id"),
        "seo_client_memory_summaries": ("client_slug",),
        "seo_workflow_run_summaries": ("run_id", "client_slug", "workflow_id"),
        "seo_workflow_readiness": ("client_slug", "source_ref_hash"),
        "seo_opportunity_queue": ("client_slug", "workflow_id", "source_ref_hash"),
    }
    return {
        table: LoggingTablePlan(logical_name=table, spec=specs[table], merge_keys=keys)
        for table, keys in merge_keys.items()
    }


def ensure_agent_logging_tables(client: Any, config: BigQueryCostConfig) -> None:
    ensure_tables(client, config, [plan.spec for plan in agent_logging_table_plans(config).values()])


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def json_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in rows]


def _validate_table_name(name: str) -> None:
    if not _TABLE_NAME_RE.fullmatch(name):
        raise AgentLoggingError(f"unsafe BigQuery identifier: {name}")


def _quote_identifier(name: str) -> str:
    _validate_table_name(name)
    return f"`{name}`"


def _safe_suffix(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)[:80].strip("_") or "batch"


def _required_fields(plan: LoggingTablePlan) -> set[str]:
    return {name for name, _field_type, mode in plan.spec.schema if mode == "REQUIRED"}


def _schema_field_names(plan: LoggingTablePlan) -> list[str]:
    return [name for name, _field_type, _mode in plan.spec.schema]


def validate_logging_batch(
    plan: LoggingTablePlan,
    rows: list[dict[str, Any]],
    *,
    max_rows: int = DEFAULT_MAX_ROWS_PER_BATCH,
    max_row_bytes: int = DEFAULT_MAX_ROW_BYTES,
    max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
) -> None:
    if len(rows) > max_rows:
        raise AgentLoggingError(f"{plan.logical_name} batch has {len(rows)} rows; cap is {max_rows}")

    field_names = set(_schema_field_names(plan))
    required_fields = _required_fields(plan)
    seen_keys: set[tuple[str, ...]] = set()
    batch_bytes = 0

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise AgentLoggingError(f"{plan.logical_name} row {index} must be an object")
        missing = sorted(field for field in required_fields if row.get(field) is None)
        if missing:
            raise AgentLoggingError(f"{plan.logical_name} row {index} missing required fields: {', '.join(missing)}")
        unknown = sorted(set(row) - field_names)
        if unknown:
            raise AgentLoggingError(f"{plan.logical_name} row {index} has unknown fields: {', '.join(unknown)}")

        key = tuple(str(row.get(field) or "") for field in plan.merge_keys)
        if any(not part for part in key):
            raise AgentLoggingError(f"{plan.logical_name} row {index} missing merge key: {', '.join(plan.merge_keys)}")
        if key in seen_keys:
            raise AgentLoggingError(f"{plan.logical_name} duplicate merge key in batch: {key}")
        seen_keys.add(key)

        row_bytes = _json_size(row)
        if row_bytes > max_row_bytes:
            raise AgentLoggingError(f"{plan.logical_name} row {index} is {row_bytes} bytes; cap is {max_row_bytes}")
        batch_bytes += row_bytes
        if batch_bytes > max_batch_bytes:
            raise AgentLoggingError(f"{plan.logical_name} batch is {batch_bytes} bytes; cap is {max_batch_bytes}")


def build_merge_sql(plan: LoggingTablePlan, config: BigQueryCostConfig, staging_table_id: str) -> str:
    columns = _schema_field_names(plan)
    for column in columns:
        _validate_table_name(column)
    on_clause = " AND ".join(f"T.{_quote_identifier(key)} = S.{_quote_identifier(key)}" for key in plan.merge_keys)
    update_columns = [column for column in columns if column not in plan.merge_keys]
    update_clause = ", ".join(f"{_quote_identifier(column)} = S.{_quote_identifier(column)}" for column in update_columns)
    insert_columns = ", ".join(_quote_identifier(column) for column in columns)
    insert_values = ", ".join(f"S.{_quote_identifier(column)}" for column in columns)
    return f"""
MERGE `{plan.table_id(config)}` AS T
USING `{staging_table_id}` AS S
ON {on_clause}
WHEN MATCHED THEN
  UPDATE SET {update_clause}
WHEN NOT MATCHED THEN
  INSERT ({insert_columns})
  VALUES ({insert_values})
""".strip()


def log_rows_with_staging_merge(
    client: Any,
    config: BigQueryCostConfig,
    table: str,
    rows: list[dict[str, Any]],
    *,
    dry_run: bool = True,
    ensure_tables_first: bool = False,
    batch_id: str | None = None,
    purpose: str = "agent operating log write",
    max_rows: int = DEFAULT_MAX_ROWS_PER_BATCH,
    max_row_bytes: int = DEFAULT_MAX_ROW_BYTES,
    max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
) -> LoggingResult:
    plans = agent_logging_table_plans(config)
    if table not in plans:
        raise AgentLoggingError(f"BigQuery logging table is not allowlisted: {table}")
    plan = plans[table]
    rows = json_safe_rows(rows)
    validate_logging_batch(
        plan,
        rows,
        max_rows=max_rows,
        max_row_bytes=max_row_bytes,
        max_batch_bytes=max_batch_bytes,
    )
    destination_table_id = plan.table_id(config)
    if dry_run or not rows:
        return LoggingResult(table=table, destination_table_id=destination_table_id, rows=len(rows), dry_run=True)

    from google.cloud import bigquery

    if ensure_tables_first:
        ensure_agent_logging_tables(client, config)

    suffix = _safe_suffix(batch_id or rows[0].get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
    staging_table_id = config.table_id(config.staging_dataset, f"agent_log_{table}_{suffix}")
    staging_dataset = bigquery.Dataset(f"{config.project_id}.{config.staging_dataset}")
    staging_dataset.location = config.default_location
    client.create_dataset(staging_dataset, exists_ok=True)
    staging_table = bigquery.Table(
        staging_table_id,
        schema=[bigquery.SchemaField(name, field_type, mode=mode) for name, field_type, mode in plan.spec.schema],
    )
    staging_table.expires = datetime.now(timezone.utc) + timedelta(hours=config.staging_table_expiry_hours)
    client.create_table(staging_table, exists_ok=True)

    load_config = bigquery.LoadJobConfig(
        schema=staging_table.schema,
        write_disposition="WRITE_TRUNCATE",
    )
    load_job = client.load_table_from_json(rows, staging_table_id, job_config=load_config, location=config.default_location)
    load_job.result()

    merge_result, _ = CappedBigQueryRunner(client, config).run_query(
        build_merge_sql(plan, config, staging_table_id),
        purpose=f"{purpose}: merge {table}",
        labels={"agent_table": table[:63]},
    )
    return LoggingResult(
        table=table,
        destination_table_id=destination_table_id,
        rows=len(rows),
        dry_run=False,
        staging_table_id=staging_table_id,
        merge_job_id=merge_result.job_id,
    )


def log_agent_output(
    client: Any,
    config: BigQueryCostConfig,
    *,
    run_row: dict[str, Any],
    findings: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    context_pack: dict[str, Any] | None = None,
    llm_usage: list[dict[str, Any]] | None = None,
    dry_run: bool = True,
    ensure_tables_first: bool = False,
    batch_id: str | None = None,
    purpose: str = "agent operating log write",
) -> dict[str, int]:
    if ensure_tables_first and not dry_run:
        ensure_agent_logging_tables(client, config)
    batches: list[tuple[str, list[dict[str, Any]]]] = [
        ("context_packs", [context_pack] if context_pack else []),
        ("agent_findings", findings or []),
        ("agent_actions", actions or []),
        ("llm_usage_log", llm_usage or []),
        ("agent_run_log", [run_row]),
    ]
    loaded: dict[str, int] = {}
    for table, rows in batches:
        result = log_rows_with_staging_merge(
            client,
            config,
            table,
            rows,
            dry_run=dry_run,
            ensure_tables_first=False,
            batch_id=batch_id or run_row.get("run_id"),
            purpose=purpose,
        )
        loaded[table] = result.rows
    return loaded
