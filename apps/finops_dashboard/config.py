"""Configuration for the read-only Databricks FinOps dashboard."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re


def _identifier(value: str, variable: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{variable} contains an invalid SQL identifier: {value}")
    return value


@dataclass(frozen=True)
class DashboardConfig:
    """Unity Catalog namespaces used by the dashboard."""

    data_catalog: str
    datamart_schema: str
    operations_catalog: str
    operations_schema: str
    environment: str

    @classmethod
    def from_environment(cls) -> "DashboardConfig":
        environment = os.getenv("FINOPS_ENVIRONMENT", "prod").strip().lower()
        if environment not in {"dev", "prod"}:
            raise ValueError("FINOPS_ENVIRONMENT must be dev or prod")
        default_catalog = f"finops_{environment}"
        return cls(
            data_catalog=_identifier(
                os.getenv("FINOPS_DATABRICKS_CATALOG", default_catalog),
                "FINOPS_DATABRICKS_CATALOG",
            ),
            datamart_schema=_identifier(
                os.getenv("FINOPS_DATAMART_SCHEMA", "datamart"),
                "FINOPS_DATAMART_SCHEMA",
            ),
            operations_catalog=_identifier(
                os.getenv("FINOPS_OPERATIONS_CATALOG", "finops_ops"),
                "FINOPS_OPERATIONS_CATALOG",
            ),
            operations_schema=_identifier(
                os.getenv("FINOPS_OPERATIONS_SCHEMA", "audit"),
                "FINOPS_OPERATIONS_SCHEMA",
            ),
            environment=environment,
        )

    def datamart(self, name: str) -> str:
        table = _identifier(name, "datamart table")
        return f"`{self.data_catalog}`.`{self.datamart_schema}`.`{table}`"

    def audit(self, name: str) -> str:
        table = _identifier(name, "audit table")
        return f"`{self.operations_catalog}`.`{self.operations_schema}`.`{table}`"
