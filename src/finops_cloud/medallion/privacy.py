"""Block known identifying text BEFORE any new Bronze business-data write.

The independent generator owns text sanitization. The platform rejects dirty
sources instead of silently masking their dashboard labels. This targeted check
does not establish complete anonymity; internal business codes are retained.
"""
from __future__ import annotations

POLICY_VERSION = 'organization-text-v1'
ORGANIZATION_PATTERN = r'(?i)(technip|(?<![a-z0-9])t[.]?en(?![a-z0-9])|ten[.]com)'
EMAIL_PATTERN = r'[a-zA-Z0-9_.+%-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
PSEUDONYMOUS_EMAIL_PATTERN = r'(?i)^user_[0-9a-f]+@anonymized-corp[.]internal$'


def _quoted(column: str) -> str:
    return '`' + column.replace('`', '``') + '`'


def privacy_expressions(columns: list[str]) -> list[str]:
    """Spark SQL raw strings keep the regex unchanged across both computes."""
    expressions = []
    for name in columns:
        column = _quoted(name)
        condition = privacy_condition(name)
        expressions.append(f'count_if({condition}) AS {column}')
    return expressions


def privacy_condition(name: str) -> str:
    column = _quoted(name)
    return (
        f"regexp_like({column}, r'{ORGANIZATION_PATTERN}') OR "
        f"exists(regexp_extract_all({column}, r'{EMAIL_PATTERN}', 0), "
        f"address -> NOT regexp_like(address, r'{PSEUDONYMOUS_EMAIL_PATTERN}'))"
    )


def assert_source_privacy(frame, source_uri: str) -> None:
    """One aggregate pass; failure reveals column counts, not identifying text.

    Run/audit metadata may already exist at this point. No business row from this
    source is appended to Bronze, Silver or Gold before this guard passes.
    """
    columns = [field.name for field in frame.schema.fields if field.dataType.simpleString() == 'string']
    if not columns:
        return
    result = frame.selectExpr(*privacy_expressions(columns)).collect()[0].asDict()
    findings = {name: int(count) for name, count in result.items() if count}
    if findings:
        raise ValueError(
            f'Source privacy validation failed ({POLICY_VERSION}); no business rows '
            f'from this source were written. source={source_uri}; columns={findings}. '
            'Publish a verified anonymized Parquet, not a dashboard-only label fix.'
        )
