from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "bigquery_cost_guardrails.json"


def bytes_to_human(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} B"


@dataclass(frozen=True)
class BigQueryCostConfig:
    project_id: str
    default_location: str
    pricing_mode: str
    currency: str
    monthly_budget_amount: float
    normal_query_cap_bytes: int
    admin_override_query_cap_bytes: int
    dry_run_required: bool
    control_dataset: str
    staging_dataset: str
    memory_dataset: str
    reporting_dataset: str
    cost_checks_table: str
    staging_table_expiry_hours: int
    budget_alert_thresholds: tuple[float, ...]
    raw_dataset_policy: dict[str, Any]

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "BigQueryCostConfig":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            project_id=str(payload["project_id"]),
            default_location=str(payload["default_location"]),
            pricing_mode=str(payload["pricing_mode"]),
            currency=str(payload["currency"]),
            monthly_budget_amount=float(payload["monthly_budget_amount"]),
            normal_query_cap_bytes=int(payload["normal_query_cap_bytes"]),
            admin_override_query_cap_bytes=int(payload["admin_override_query_cap_bytes"]),
            dry_run_required=bool(payload["dry_run_required"]),
            control_dataset=str(payload["control_dataset"]),
            staging_dataset=str(payload.get("staging_dataset", "agency_staging")),
            memory_dataset=str(payload.get("memory_dataset", "agency_memory")),
            reporting_dataset=str(payload.get("reporting_dataset", "agency_reporting")),
            cost_checks_table=str(payload["cost_checks_table"]),
            staging_table_expiry_hours=int(payload["staging_table_expiry_hours"]),
            budget_alert_thresholds=tuple(float(item) for item in payload["budget_alert_thresholds"]),
            raw_dataset_policy=dict(payload.get("raw_dataset_policy", {})),
        )

    @property
    def cost_checks_table_id(self) -> str:
        return f"{self.project_id}.{self.control_dataset}.{self.cost_checks_table}"

    def table_id(self, dataset: str, table: str) -> str:
        return f"{self.project_id}.{dataset}.{table}"

    def cap_bytes(self, admin_cap_10gb: bool = False) -> int:
        if admin_cap_10gb:
            return self.admin_override_query_cap_bytes
        return self.normal_query_cap_bytes
