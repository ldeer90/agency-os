from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .cost_config import BigQueryCostConfig, bytes_to_human


class MissingPurposeError(ValueError):
    """Raised when a query is missing an audit purpose."""


class QueryCostExceeded(RuntimeError):
    """Raised when a query estimate exceeds the configured byte cap."""

    def __init__(self, message: str, *, result: "CappedQueryResult") -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class CappedQueryResult:
    status: str
    purpose: str
    estimated_bytes: int
    cap_bytes: int
    query_id: str
    job_id: str | None = None
    log_errors: tuple[str, ...] = ()

    @property
    def estimated_human(self) -> str:
        return bytes_to_human(self.estimated_bytes)

    @property
    def cap_human(self) -> str:
        return bytes_to_human(self.cap_bytes)


class CappedBigQueryRunner:
    """Run BigQuery SQL only after dry-run estimation and max-bytes enforcement."""

    def __init__(
        self,
        client: Any,
        config: BigQueryCostConfig,
        *,
        query_job_config_factory: Callable[..., Any] | None = None,
        now: Callable[[], datetime] | None = None,
        log_table_id: str | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self._query_job_config_factory = query_job_config_factory
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.log_table_id = log_table_id or config.cost_checks_table_id

    def estimate_query(self, sql: str, *, purpose: str, location: str | None = None) -> CappedQueryResult:
        purpose = self._require_purpose(purpose)
        query_id = self._new_query_id()
        effective_location = location or self.config.default_location
        job_config = self._query_job_config(dry_run=True, use_query_cache=False)
        dry_run_job = self.client.query(
            sql,
            job_config=job_config,
            location=effective_location,
        )
        estimated_bytes = int(getattr(dry_run_job, "total_bytes_processed", 0) or 0)
        return CappedQueryResult(
            status="estimated",
            purpose=purpose,
            estimated_bytes=estimated_bytes,
            cap_bytes=self.config.normal_query_cap_bytes,
            query_id=query_id,
            job_id=getattr(dry_run_job, "job_id", None),
            log_errors=self._log_cost_check(
                query_id=query_id,
                purpose=purpose,
                status="estimated",
                estimated_bytes=estimated_bytes,
                cap_bytes=self.config.normal_query_cap_bytes,
                job_id=getattr(dry_run_job, "job_id", ""),
                admin_cap_10gb=False,
                location=effective_location,
            ),
        )

    def run_query(
        self,
        sql: str,
        *,
        purpose: str,
        admin_cap_10gb: bool = False,
        location: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> tuple[CappedQueryResult, Any | None]:
        purpose = self._require_purpose(purpose)
        query_id = self._new_query_id()
        cap_bytes = self.config.cap_bytes(admin_cap_10gb=admin_cap_10gb)
        effective_location = location or self.config.default_location

        dry_run_config = self._query_job_config(dry_run=True, use_query_cache=False, labels=self._labels(labels))
        dry_run_job = self.client.query(sql, job_config=dry_run_config, location=effective_location)
        estimated_bytes = int(getattr(dry_run_job, "total_bytes_processed", 0) or 0)

        if estimated_bytes > cap_bytes:
            result = CappedQueryResult(
                status="blocked",
                purpose=purpose,
                estimated_bytes=estimated_bytes,
                cap_bytes=cap_bytes,
                query_id=query_id,
                job_id=getattr(dry_run_job, "job_id", None),
                log_errors=self._log_cost_check(
                    query_id=query_id,
                    purpose=purpose,
                    status="blocked",
                    estimated_bytes=estimated_bytes,
                    cap_bytes=cap_bytes,
                    job_id=getattr(dry_run_job, "job_id", ""),
                    admin_cap_10gb=admin_cap_10gb,
                    location=effective_location,
                ),
            )
            raise QueryCostExceeded(
                f"Blocked BigQuery query {query_id} for purpose '{purpose}': estimated "
                f"{bytes_to_human(estimated_bytes)} exceeds cap {bytes_to_human(cap_bytes)}. "
                "Narrow the date range, query a reporting table, or use --admin-cap-10gb intentionally.",
                result=result,
            )

        run_config = self._query_job_config(
            maximum_bytes_billed=cap_bytes,
            use_query_cache=True,
            labels=self._labels(labels),
        )
        query_job = None
        try:
            query_job = self.client.query(sql, job_config=run_config, location=effective_location)
            query_result = query_job.result()
        except Exception as exc:
            log_errors = self._log_cost_check(
                query_id=query_id,
                purpose=purpose,
                status="failed",
                estimated_bytes=estimated_bytes,
                cap_bytes=cap_bytes,
                job_id=getattr(query_job, "job_id", "") if query_job is not None else "",
                admin_cap_10gb=admin_cap_10gb,
                location=effective_location,
                error_class=type(exc).__name__,
                error_message=str(exc)[:500],
            )
            if log_errors:
                raise RuntimeError(
                    f"BigQuery query {query_id} failed with {type(exc).__name__}; "
                    f"cost-check log also reported: {'; '.join(log_errors)}"
                ) from exc
            raise
        result = CappedQueryResult(
            status="succeeded",
            purpose=purpose,
            estimated_bytes=estimated_bytes,
            cap_bytes=cap_bytes,
            query_id=query_id,
            job_id=getattr(query_job, "job_id", None),
            log_errors=self._log_cost_check(
                query_id=query_id,
                purpose=purpose,
                status="succeeded",
                estimated_bytes=estimated_bytes,
                cap_bytes=cap_bytes,
                job_id=getattr(query_job, "job_id", ""),
                admin_cap_10gb=admin_cap_10gb,
                location=effective_location,
            ),
        )
        return result, query_result

    def _query_job_config(self, **kwargs: Any) -> Any:
        if self._query_job_config_factory:
            return self._query_job_config_factory(**kwargs)
        try:
            from google.cloud import bigquery
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "google-cloud-bigquery is not installed. Install requirements.txt before running live queries."
            ) from exc
        return bigquery.QueryJobConfig(**kwargs)

    def _log_cost_check(
        self,
        *,
        query_id: str,
        purpose: str,
        status: str,
        estimated_bytes: int,
        cap_bytes: int,
        job_id: str,
        admin_cap_10gb: bool,
        location: str,
        error_class: str = "",
        error_message: str = "",
    ) -> tuple[str, ...]:
        row = {
            "logged_at": self._now().isoformat(),
            "query_id": query_id,
            "purpose": purpose,
            "status": status,
            "estimated_bytes": estimated_bytes,
            "cap_bytes": cap_bytes,
            "estimated_human": bytes_to_human(estimated_bytes),
            "cap_human": bytes_to_human(cap_bytes),
            "job_id": job_id,
            "admin_cap_10gb": admin_cap_10gb,
            "location": location,
            "error_class": error_class,
            "error_message": error_message,
        }
        if not hasattr(self.client, "insert_rows_json"):
            return ("client has no insert_rows_json; cost check was not written",)
        errors = self.client.insert_rows_json(self.log_table_id, [row])
        return tuple(str(error) for error in errors or ())

    @staticmethod
    def _require_purpose(purpose: str) -> str:
        cleaned = (purpose or "").strip()
        if not cleaned:
            raise MissingPurposeError("Every BigQuery query must include a non-empty purpose for auditability.")
        return cleaned

    @staticmethod
    def _new_query_id() -> str:
        return uuid4().hex

    @staticmethod
    def _labels(labels: dict[str, str] | None) -> dict[str, str]:
        merged = {"managed_by": "codex", "guardrail": "capped_query"}
        if labels:
            merged.update(labels)
        return merged
