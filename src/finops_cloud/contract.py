"""FOCUS Data Contract application independent from notebook execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_contract(path: Path) -> dict[str, Any]:
    """Load the versioned YAML Data Contract and validate its basic structure."""
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "fields" not in payload:
        raise ValueError(f"Invalid Data Contract: {path}")
    return payload


def apply_focus_contract(frame, contract_path: Path, currency: str, provider: str):
    """Cast contract fields and reject rows that violate blocking rules."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import DecimalType

    contract = load_contract(contract_path)
    fields = contract["fields"]
    required = [field["name"] for field in fields if field.get("required")]
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"Required FOCUS columns are missing: {missing}")

    result = frame
    period_dates = {"BillingPeriodStart", "BillingPeriodEnd"}
    timestamps = {
        "ChargePeriodStart",
        "ChargePeriodEnd",
        "x_ServicePeriodStart",
        "x_ServicePeriodEnd",
        "x_BillingExchangeRateDate",
    }
    for field in fields:
        name = field["name"]
        if name not in result.columns:
            result = result.withColumn(name, F.lit(None))
        target_type = field.get("type", "string")
        if name in period_dates:
            result = result.withColumn(name, F.to_date(F.col(name)))
        elif name in timestamps:
            result = result.withColumn(name, F.to_timestamp(F.col(name)))
        elif target_type == "decimal":
            result = result.withColumn(name, F.col(name).cast(DecimalType(38, 18)))
        elif target_type == "integer":
            result = result.withColumn(name, F.col(name).cast("long"))
        elif target_type == "boolean":
            result = result.withColumn(name, F.col(name).cast("boolean"))
        else:
            result = result.withColumn(name, F.col(name).cast("string"))

    blocking_conditions = []
    for field in fields:
        if field.get("nullable") is False and field["name"] in result.columns:
            blocking_conditions.append(F.col(field["name"]).isNull())
        allowed_values = field.get("allowed_values")
        if allowed_values and field["name"] in result.columns:
            blocking_conditions.append(
                F.col(field["name"]).isNotNull()
                & ~F.col(field["name"]).isin(*allowed_values)
            )
    blocking_conditions.extend(
        [
            F.col("BillingCurrency") != F.lit(currency),
            F.col("ProviderName") != F.lit(provider),
            F.col("ChargePeriodStart") > F.col("ChargePeriodEnd"),
            F.col("BillingPeriodStart") > F.col("BillingPeriodEnd"),
        ]
    )
    invalid = blocking_conditions[0]
    for condition in blocking_conditions[1:]:
        invalid = invalid | condition
    invalid_rows = result.filter(invalid).limit(1).count()
    if invalid_rows:
        raise ValueError("FOCUS Data Contract validation failed; no data was written")
    return result


def validate_single_month(frame, month: str) -> None:
    """Require an authoritative billing DataFrame to contain exactly one month."""
    from pyspark.sql import functions as F

    expected = f"{month}-01"
    values = [
        row[0]
        for row in frame.select(
            F.date_format(F.col("BillingPeriodStart"), "yyyy-MM-dd")
        )
        .distinct()
        .limit(2)
        .collect()
    ]
    if values != [expected]:
        raise ValueError(
            f"Billing source must contain only {month}; found {sorted(values)}"
        )
