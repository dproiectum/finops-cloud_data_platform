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


def _apply_null_fallbacks(frame, fields):
    """Apply explicit, contract-owned fallbacks before blocking validation."""
    from pyspark.sql import functions as F

    result = frame
    available = set(result.columns)
    for field in fields:
        fallback = field.get("null_fallback")
        if not fallback:
            continue
        target = field["name"]
        source = fallback["source_field"]
        condition_field = fallback.get("condition_field")
        required = {target, source}
        if condition_field:
            required.add(condition_field)
        missing = sorted(required - available)
        if missing:
            raise ValueError(
                f"Data Contract fallback for {target} references missing columns: "
                f"{missing}"
            )

        condition = (
            F.col(target).isNull()
            & F.col(source).isNotNull()
            & (F.trim(F.col(source).cast("string")) != F.lit(""))
        )
        if condition_field:
            condition = condition & (
                F.col(condition_field) == F.lit(fallback["condition_value"])
            )
        result = result.withColumn(
            target,
            F.when(condition, F.col(source).cast("string")).otherwise(F.col(target)),
        )
    return result


def apply_focus_contract(frame, contract_path: Path, currency: str, provider: str):
    """Cast contract fields and reject rows that violate blocking rules."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import DecimalType

    # The YAML contract is the versioned source of truth for columns and types.
    contract = load_contract(contract_path)
    fields = contract["fields"]
    required = [field["name"] for field in fields if field.get("required")]
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"Required FOCUS columns are missing: {missing}")

    # Missing optional fields are created as null; required fields fail immediately.
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

    # Bronze remains untouched. Only fallbacks explicitly declared by the
    # contract can normalize values before the blocking Silver checks.
    result = _apply_null_fallbacks(result, fields)

    # Blocking rules are evaluated before any data is written to Silver.
    blocking_rules = []
    for field in fields:
        if field.get("nullable") is False and field["name"] in result.columns:
            blocking_rules.append(
                (f"not_null_{field['name']}", F.col(field["name"]).isNull())
            )
        allowed_values = field.get("allowed_values")
        if allowed_values and field["name"] in result.columns:
            blocking_rules.append(
                (
                    f"allowed_values_{field['name']}",
                    F.col(field["name"]).isNotNull()
                    & ~F.col(field["name"]).isin(*allowed_values),
                )
            )
    blocking_rules.extend(
        [
            (
                "expected_BillingCurrency",
                F.col("BillingCurrency") != F.lit(currency),
            ),
            ("expected_ProviderName", F.col("ProviderName") != F.lit(provider)),
            (
                "ordered_ChargePeriod",
                F.col("ChargePeriodStart") > F.col("ChargePeriodEnd"),
            ),
            (
                "ordered_BillingPeriod",
                F.col("BillingPeriodStart") > F.col("BillingPeriodEnd"),
            ),
        ]
    )
    # One aggregate scan produces an actionable message without exposing rows.
    counts = result.agg(
        *[
            F.coalesce(
                F.sum(F.when(condition, F.lit(1)).otherwise(F.lit(0))),
                F.lit(0),
            ).alias(name)
            for name, condition in blocking_rules
        ]
    ).first()
    violations = [
        f"{name}={int(counts[name])}"
        for name, _ in blocking_rules
        if int(counts[name]) > 0
    ]
    if violations:
        details = ", ".join(violations)
        raise ValueError(
            f"FOCUS Data Contract validation failed ({details}); "
            "no data was written to Silver"
        )
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
