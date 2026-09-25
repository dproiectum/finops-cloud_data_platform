"""Configuration loading used by VS Code, Databricks Connect, and Jobs."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
import os
from pathlib import Path
import tomllib
from typing import Any


# Default repository root used by local Python and Databricks Git execution.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _installed_resource(relative_path: Path) -> Path | None:
    """Locate configuration or contract data embedded in an installed wheel."""
    try:
        package = distribution("finops_cloud")
    except PackageNotFoundError:
        return None
    expected = ("share", "finops_cloud", *relative_path.parts)
    for entry in package.files or ():
        if tuple(entry.parts[-len(expected) :]) == expected:
            candidate = Path(package.locate_file(entry))
            if candidate.is_file():
                return candidate
    return None


def _resource_file(project_root: Path, relative_path: Path) -> Path:
    """Prefer editable source files, then fall back to installed wheel data."""
    source_file = project_root / relative_path
    if source_file.is_file():
        return source_file
    installed_file = _installed_resource(relative_path)
    if installed_file is not None:
        return installed_file
    raise FileNotFoundError(f"Project resource not found: {relative_path}")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge environment overrides into common configuration."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_toml(path: Path) -> dict[str, Any]:
    """Read one TOML file and require a mapping at its root."""
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration must be a mapping: {path}")
    return payload


@dataclass(frozen=True)
class PlatformConfig:
    environment: str
    profile: str
    catalog: str
    raw_catalog: str
    raw_schema: str
    operations_catalog: str
    operations_schema: str
    source_volume: str
    archive_volume: str
    gcs_service_credential: str | None
    gcp_project: str | None
    gcs_bucket: str
    active_prefix: str
    archive_prefix: str
    daily_path_template: str
    daily_month_prefix_template: str
    billing_path_template: str
    archive_daily: bool
    archive_billing: bool
    schemas: dict[str, str]
    tables: dict[str, str]
    contract_path: Path
    contract_version: str
    focus_version: str
    currency: str
    provider: str
    amount_tolerance: str

    def schema(self, layer: str) -> str:
        """Return a fully qualified Unity Catalog schema for a logical layer."""
        if layer == "ops":
            return f"{self.operations_catalog}.{self.operations_schema}"
        return f"{self.catalog}.{self.schemas[layer]}"

    def table(self, key: str, layer: str) -> str:
        """Return a fully qualified table name from a configured table key."""
        return f"{self.schema(layer)}.{self.tables[key]}"

    def daily_volume_uri(self, day: str) -> str:
        """Build the External Volume URI for one YYYY-MM-DD daily file."""
        relative = self.daily_path_template.format(
            year=day[:4],
            month=day[5:7],
            day=day[8:10],
            date=day,
            billing_month=day[:7],
        )
        return f"{self.source_volume}/{relative.lstrip('/')}"

    def billing_volume_uri(self, month: str) -> str:
        """Build the External Volume URI for one YYYY-MM billing file."""
        relative = self.billing_path_template.format(
            year=month[:4],
            month=month[5:7],
            billing_month=month,
        )
        return f"{self.source_volume}/{relative.lstrip('/')}"

    def daily_gcs_month_prefix(self, month: str) -> str:
        """Build the active GCS prefix containing all daily files for a month."""
        relative = self.daily_month_prefix_template.format(
            year=month[:4], month=month[5:7], billing_month=month
        )
        return f"{self.active_prefix}/{relative.lstrip('/')}"

    def billing_gcs_object(self, month: str) -> str:
        """Build the active GCS object name for an authoritative billing month."""
        relative = self.billing_path_template.format(
            year=month[:4], month=month[5:7], billing_month=month
        )
        return f"{self.active_prefix}/{relative.lstrip('/')}"


def load_config(environment: str, root: Path | None = None) -> PlatformConfig:
    """Load, merge, override, and validate configuration for DEV or PROD."""
    if environment not in {"dev", "prod"}:
        raise ValueError("environment must be dev or prod")
    project_root = root or PROJECT_ROOT

    # Common settings define the platform; dev/prod files override differences.
    common = _read_toml(_resource_file(project_root, Path("config/common.toml")))
    selected = _read_toml(
        _resource_file(project_root, Path(f"config/{environment}.toml"))
    )
    raw = _deep_merge(common, selected)

    # Environment variables are optional last-mile overrides for CI/CD and Jobs.
    databricks = raw["databricks"]
    storage = raw["storage"]
    raw_storage = raw["raw"]
    operations = raw["operations"]
    contract = raw["contract"]
    quality = raw["quality"]

    config = PlatformConfig(
        environment=environment,
        profile=os.getenv("FINOPS_DATABRICKS_PROFILE", databricks["profile"]),
        catalog=os.getenv("FINOPS_CATALOG", databricks["catalog"]),
        raw_catalog=os.getenv("FINOPS_RAW_CATALOG", raw_storage["catalog"]),
        raw_schema=os.getenv("FINOPS_RAW_SCHEMA", raw_storage["schema"]),
        operations_catalog=os.getenv(
            "FINOPS_OPERATIONS_CATALOG", operations["catalog"]
        ),
        operations_schema=os.getenv(
            "FINOPS_OPERATIONS_SCHEMA", operations["schema"]
        ),
        source_volume=os.getenv("FINOPS_SOURCE_VOLUME", raw_storage["source_volume"]),
        archive_volume=os.getenv("FINOPS_ARCHIVE_VOLUME", raw_storage["archive_volume"]),
        gcs_service_credential=databricks.get("gcs_service_credential"),
        gcp_project=databricks.get("gcp_project"),
        gcs_bucket=os.getenv("FINOPS_GCS_BUCKET", storage["gcs_bucket"]),
        active_prefix=storage["active_prefix"].strip("/"),
        archive_prefix=storage["archive_prefix"].strip("/"),
        daily_path_template=storage["daily_path_template"],
        daily_month_prefix_template=storage["daily_month_prefix_template"],
        billing_path_template=storage["billing_path_template"],
        archive_daily=bool(storage["archive_daily_after_month_close"]),
        archive_billing=bool(storage["archive_billing_after_month_close"]),
        schemas=dict(raw["schemas"]),
        tables=dict(raw["tables"]),
        contract_path=_resource_file(project_root, Path(contract["path"])).resolve(),
        contract_version=str(contract["version"]),
        focus_version=str(contract["focus_version"]),
        currency=str(quality["currency"]),
        provider=str(quality["provider"]),
        amount_tolerance=str(quality["amount_tolerance"]),
    )

    validate_config(config)
    return config


def validate_config(config: PlatformConfig) -> None:
    """Fail fast when mandatory schemas, tables, or contract files are missing."""
    if config.environment not in {"dev", "prod"}:
        raise ValueError("environment must be dev or prod")
    if not all(
        (
            config.catalog,
            config.raw_catalog,
            config.raw_schema,
            config.operations_catalog,
            config.operations_schema,
        )
    ):
        raise ValueError("data, raw, and operations namespaces are required")
    if not config.gcs_bucket:
        raise ValueError("GCS bucket is required")
    required_schemas = {"bronze", "silver", "gold", "datamart"}
    missing_schemas = required_schemas - set(config.schemas)
    if missing_schemas:
        raise ValueError(f"Missing schema settings: {sorted(missing_schemas)}")
    required_tables = {
        "bronze_daily",
        "bronze_billing",
        "silver_canonical",
        "silver_central",
        "fact_cost_usage",
        "dim_date",
        "dim_billing_scope",
        "dim_resource",
        "dim_service",
        "dim_sku",
        "dim_location",
        "dim_commitment_discount",
        "dim_pricing",
        "dim_charge_type",
        "dim_tag",
        "bridge_resource_tag",
        "dm_monthly_billing",
        "dm_daily_billing",
        "dm_cost_by_scope_service_month",
        "dm_top_services",
        "dm_top_resources",
        "dm_cost_by_charge_type",
        "dm_sku_cost",
        "dm_savings_monthly",
        "dm_executive_summary_monthly",
        "dm_top_resources_monthly",
        "dm_data_quality_monthly",
        "dm_cost_by_resource_group_month",
        "dm_cost_by_subscription_month",
        "dm_cost_by_application_owner_month",
        "month_status",
        "pipeline_run",
        "month_snapshot",
        "reconciliation",
        "file_archive",
    }
    missing_tables = required_tables - set(config.tables)
    if missing_tables:
        raise ValueError(f"Missing table settings: {sorted(missing_tables)}")
    if not config.contract_path.is_file():
        raise FileNotFoundError(f"Data Contract not found: {config.contract_path}")
