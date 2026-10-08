"""Validate the deliberately small, public platform-cost snapshot."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import re

import pandas as pd


SNAPSHOT_PATH = Path(__file__).with_name("snapshot.json")
COLUMNS = (
    "month", "provider", "service", "currency", "cost_before_credits", "credits",
    "usage_quantity", "usage_unit", "cost_basis", "period_status",
)
KEY = ("month", "provider", "service", "currency", "cost_basis")


def decimal_value(value, *, optional=False):
    if value is None or value == "":
        if optional:
            return None
        raise ValueError("A required cost is unavailable; do not replace it with zero.")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Use unformatted decimal numbers, for example 1234.56.") from exc
    if not number.is_finite() or abs(number) > Decimal("1e15"):
        raise ValueError("Invalid numeric value in platform cost snapshot.")
    return number


def validate_records(records):
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("Expected a small list of monthly service aggregates.")
    checked, seen = [], set()
    for position, row in enumerate(records, 1):
        try:
            if not isinstance(row, dict) or set(row) != set(COLUMNS):
                raise ValueError("Only the documented aggregate columns are allowed.")
            if not isinstance(row["month"], str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", row["month"]):
                raise ValueError("Month must use YYYY-MM.")
            date.fromisoformat(row["month"] + "-01")
            if row["provider"] not in {"GCP", "Databricks"}:
                raise ValueError("Provider must be GCP or Databricks.")
            if not isinstance(row["currency"], str) or not re.fullmatch(r"[A-Z]{3}", row["currency"]):
                raise ValueError("Use a three-letter currency code; no implicit conversion.")
            service = row["service"]
            if not isinstance(service, str) or not service.strip() or len(service) > 160 or any(
                token in service for token in ("@", "://", "\n", "\r", "<", ">")
            ):
                raise ValueError("Use a reviewed service/SKU label, without URLs or identities.")
            if row["period_status"] not in {"partial", "closed"}:
                raise ValueError("Period status must be partial or closed.")
            expected = "billing_export" if row["provider"] == "GCP" else "list_estimate"
            if row["cost_basis"] != expected:
                raise ValueError("GCP requires billing_export; Databricks requires list_estimate.")
            parsed = dict(row)
            parsed["cost_before_credits"] = decimal_value(row["cost_before_credits"])
            parsed["credits"] = decimal_value(row["credits"], optional=row["provider"] == "Databricks")
            parsed["usage_quantity"] = decimal_value(row["usage_quantity"], optional=row["provider"] == "GCP")
            if row["provider"] == "Databricks":
                if row["usage_unit"] != "DBU" or parsed["credits"] is not None:
                    raise ValueError("Databricks estimates require DBUs and unknown (blank) credits.")
                parsed["reported_cost"] = parsed["cost_before_credits"]
            else:
                if row["usage_unit"] not in {"", None} or parsed["usage_quantity"] is not None:
                    raise ValueError("Do not aggregate incompatible GCP consumption units.")
                with localcontext() as context:
                    context.prec = 80
                    parsed["reported_cost"] = parsed["cost_before_credits"] + parsed["credits"]
            key = tuple(row[column] for column in KEY)
            if key in seen:
                raise ValueError("Duplicate monthly service aggregate; merge sources before publishing.")
            seen.add(key)
            checked.append(parsed)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Platform cost row {position}: {exc}") from exc
    return pd.DataFrame(checked, columns=[*COLUMNS, "reported_cost"])


def load_snapshot(path=SNAPSHOT_PATH):
    from .snapshot import read_payload
    return read_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def amount(value, currency):
    if value is None or pd.isna(value):
        return "—"
    formatted = f"{Decimal(str(value)):,.2f}".replace(",", "\u202f").replace(".", ",")
    return f"{formatted} {currency}"


def provider_total(frame, provider, column):
    rows = frame[frame["provider"] == provider]
    if rows.empty or rows[column].isna().any():
        return None
    with localcontext() as context:
        context.prec = 80
        return sum(rows[column], Decimal("0"))
