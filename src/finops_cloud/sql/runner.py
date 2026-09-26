"""Render and execute packaged Databricks SQL templates.

SQL owns the physical Gold/datamart model. Python only supplies trusted table
identifiers from TOML configuration and controls execution order.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution
import os
from pathlib import Path
import re
from string import Formatter
from typing import Mapping


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _installed_sql_path(relative_path: Path) -> Path | None:
    """Locate SQL data embedded in an installed wheel."""
    try:
        package = distribution("finops_cloud")
    except PackageNotFoundError:
        return None
    expected = ("share", "finops_cloud", "sql", *relative_path.parts)
    for entry in package.files or ():
        if tuple(entry.parts[-len(expected) :]) == expected:
            candidate = Path(package.locate_file(entry))
            if candidate.is_file():
                return candidate
    return None


def sql_text(relative_path: str) -> str:
    """Read a safe project-relative SQL template from source or a wheel."""
    requested = Path(relative_path)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError(f"SQL path must be relative to the SQL root: {relative_path}")

    # FINOPS_SQL_ROOT supports CI or alternative layouts without code changes.
    configured_root = os.getenv("FINOPS_SQL_ROOT")
    source_root = (
        Path(configured_root).resolve()
        if configured_root
        else _PROJECT_ROOT / "platform" / "common" / "sql"
    )
    source_file = source_root / requested
    if source_file.is_file():
        return source_file.read_text(encoding="utf-8")

    installed_file = _installed_sql_path(requested)
    if installed_file is not None:
        return installed_file.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"SQL file not found in {source_root} or the installed wheel: {relative_path}"
    )


def placeholders(template: str) -> set[str]:
    """Return the format-variable names required by a SQL template."""
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(template)
        if field_name
    }


def render_sql(relative_path: str, values: Mapping[str, str]) -> str:
    """Render one SQL template after checking that every variable is supplied."""
    template = sql_text(relative_path)
    missing = placeholders(template) - set(values)
    if missing:
        raise KeyError(f"Missing SQL variables for {relative_path}: {sorted(missing)}")
    return template.format_map(values)


def split_statements(script: str) -> list[str]:
    """Split SQL without treating semicolons in comments or quoted text as separators."""
    statements: list[str] = []
    buffer: list[str] = []
    state = "sql"
    has_executable_sql = False
    position = 0

    while position < len(script):
        character = script[position]
        following = script[position + 1] if position + 1 < len(script) else ""

        if state == "sql":
            if character == "-" and following == "-":
                buffer.extend((character, following))
                state = "line_comment"
                position += 2
                continue
            if character == "/" and following == "*":
                buffer.extend((character, following))
                state = "block_comment"
                position += 2
                continue
            if character in {"'", '"', "`"}:
                buffer.append(character)
                state = {"'": "single_quote", '"': "double_quote", "`": "backtick"}[
                    character
                ]
                has_executable_sql = True
                position += 1
                continue
            if character == ";":
                if has_executable_sql:
                    statements.append("".join(buffer).strip())
                buffer = []
                has_executable_sql = False
                position += 1
                continue
            buffer.append(character)
            if not character.isspace():
                has_executable_sql = True
            position += 1
            continue

        buffer.append(character)

        if state == "line_comment":
            if character == "\n":
                state = "sql"
            position += 1
            continue

        if state == "block_comment":
            if character == "*" and following == "/":
                buffer.append(following)
                state = "sql"
                position += 2
            else:
                position += 1
            continue

        quote = {"single_quote": "'", "double_quote": '"', "backtick": "`"}[state]
        if character == "\\" and following:
            buffer.append(following)
            position += 2
            continue
        if character == quote:
            if following == quote:
                buffer.append(following)
                position += 2
                continue
            state = "sql"
        position += 1

    if has_executable_sql:
        statements.append("".join(buffer).strip())
    return statements


def execute_sql_file(spark, relative_path: str, values: Mapping[str, str]) -> int:
    """Render and execute all statements in one SQL file, preserving order."""
    # Keep transformations in SQL while Python controls parameters and order.
    rendered = render_sql(relative_path, values)
    statements = split_statements(rendered)
    for statement in statements:
        spark.sql(statement)
    return len(statements)


def table_context(config) -> dict[str, str]:
    """Return only validated, fully qualified identifiers from configuration."""
    layers = {
        "silver_canonical": "silver",
        "silver_central": "silver",
        "fact_cost_usage": "gold",
        "dim_date": "gold",
        "dim_billing_scope": "gold",
        "dim_resource": "gold",
        "dim_service": "gold",
        "dim_sku": "gold",
        "dim_location": "gold",
        "dim_commitment_discount": "gold",
        "dim_pricing": "gold",
        "dim_charge_type": "gold",
        "dim_tag": "gold",
        "bridge_resource_tag": "gold",
        "dm_monthly_billing": "datamart",
        "dm_daily_billing": "datamart",
        "dm_cost_by_scope_service_month": "datamart",
        "dm_top_services": "datamart",
        "dm_top_resources": "datamart",
        "dm_cost_by_charge_type": "datamart",
        "dm_sku_cost": "datamart",
        "dm_savings_monthly": "datamart",
        "dm_executive_summary_monthly": "datamart",
        "dm_top_resources_monthly": "datamart",
        "dm_data_quality_monthly": "datamart",
        "dm_cost_by_resource_group_month": "datamart",
        "dm_cost_by_subscription_month": "datamart",
        "dm_cost_by_application_owner_month": "datamart",
    }
    # Only configured table identifiers are allowed into SQL template placeholders.
    result = {key: config.table(key, layer) for key, layer in layers.items()}
    unsafe = {key: value for key, value in result.items() if not _SAFE_IDENTIFIER.fullmatch(value)}
    if unsafe:
        raise ValueError(f"Unsafe SQL identifiers in configuration: {unsafe}")
    return result
