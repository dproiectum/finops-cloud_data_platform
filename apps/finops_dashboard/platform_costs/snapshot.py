"""One publication contract shared by the collector and dashboard."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .model import COLUMNS, DAILY_COLUMNS, KEY, monthly_from_daily, validate_records


def utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Expected an ISO timestamp with a UTC offset.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A timestamp must include its UTC offset.")
    return parsed.astimezone(timezone.utc)


def check_freshness(value, now, max_age_hours=48):
    moment = utc_timestamp(value)
    if moment > now + timedelta(minutes=5) or now - moment > timedelta(hours=max_age_hours):
        raise ValueError("Platform cost data is stale or dated in the future.")
    return moment


def _clean(frame, columns):
    return [{key: str(row[key]) if isinstance(row[key], Decimal) else row[key]
             for key in columns} for row in frame.sort_values(list(columns[:1]) + ["provider", "service", "currency"]).to_dict("records")]


def _check_daily(daily_records, monthly, source_as_of):
    daily = validate_records(daily_records, daily=True)
    if daily.empty or set(daily["provider"]) != {"GCP", "Databricks"}:
        raise ValueError("Both daily cost sources are required.")
    for row in daily.to_dict("records"):
        source = 'GCP' if row['cost_basis'] == 'billing_export' else 'Databricks'
        if date.fromisoformat(row["usage_date"]) > utc_timestamp(source_as_of[source]).date():
            raise ValueError("Usage date follows source extraction.")
    derived = monthly_from_daily(daily_records)
    if derived.sort_values(list(KEY)).to_dict("records") != monthly.sort_values(list(KEY)).to_dict("records"):
        raise ValueError("Monthly costs do not reconcile with the daily records.")
    return daily


def _check_billing_scope(frame, *, marketplace):
    billed = frame[frame['cost_basis'] == 'billing_export']
    has_marketplace = 'Databricks' in set(billed['provider'])
    if marketplace:
        if set(billed['provider']) != {'GCP', 'Databricks'} or not (frame['cost_basis'] == 'list_estimate').any():
            raise ValueError('Marketplace publication requires GCP services, Databricks billing and DBU estimates.')
        if set(frame.loc[frame['cost_basis'] == 'list_estimate', 'currency']) != {'USD'}:
            raise ValueError('Marketplace reference estimates must retain their published USD currency.')
    elif has_marketplace:
        raise ValueError('Marketplace billing requires snapshot version 4.')


def build_payload(records, *, generated_at, gcp_extracted_at, daily_records=None):
    generated = utc_timestamp(generated_at)
    check_freshness(gcp_extracted_at, generated)
    frame = validate_records(records)
    if frame.empty or set(frame["provider"]) != {"GCP", "Databricks"}:
        raise ValueError("Automatic publication requires both validated providers.")
    sources = {"GCP": utc_timestamp(gcp_extracted_at).isoformat(), "Databricks": generated.isoformat()}
    payload = {"schema_version": 2, "approved_for_publication": True,
            "as_of": generated.date().isoformat(), "generated_at": generated.isoformat(),
            "source_as_of": sources, "records": _clean(frame, COLUMNS)}
    if daily_records is not None:
        daily = _check_daily(daily_records, frame, sources)
        marketplace = bool(((frame.provider == 'Databricks') & (frame.cost_basis == 'billing_export')).any())
        _check_billing_scope(frame, marketplace=marketplace)
        payload.update(schema_version=4 if marketplace else 3, daily_records=_clean(daily, DAILY_COLUMNS))
    else:
        _check_billing_scope(frame, marketplace=False)
    return payload


def read_payload(payload, *, remote=False, now=None, max_age_hours=48):
    if not isinstance(payload, dict):
        raise ValueError("Expected a platform cost snapshot object.")
    version = payload.get("schema_version")
    expected = {"schema_version", "approved_for_publication", "as_of", "records"}
    if type(version) is not int or version not in {1, 2, 3, 4}:
        raise ValueError("Unsupported platform cost snapshot version.")
    if version >= 2:
        expected |= {"generated_at", "source_as_of"}
    if version >= 3:
        expected.add("daily_records")
    if set(payload) != expected or (remote and version not in {2, 3, 4}):
        raise ValueError("Unexpected snapshot fields or legacy remote snapshot.")
    if type(payload["approved_for_publication"]) is not bool:
        raise ValueError("Publication approval must be a boolean.")
    if payload["approved_for_publication"] is not True:
        return None, validate_records([])
    if not isinstance(payload["as_of"], str):
        raise ValueError("A snapshot needs an extraction date.")
    date.fromisoformat(payload["as_of"])
    if version >= 2:
        now = now or datetime.now(timezone.utc)
        generated = check_freshness(payload["generated_at"], now, max_age_hours)
        if payload["as_of"] != generated.date().isoformat():
            raise ValueError("Inconsistent snapshot date.")
        if not isinstance(payload["source_as_of"], dict) or set(payload["source_as_of"]) != {"GCP", "Databricks"}:
            raise ValueError("Both source extraction timestamps are required.")
        for timestamp in payload["source_as_of"].values():
            check_freshness(timestamp, now, max_age_hours)
            if utc_timestamp(timestamp) > generated + timedelta(minutes=5):
                raise ValueError("A source timestamp cannot follow publication.")
    frame = validate_records(payload["records"])
    if version >= 2 and (frame.empty or set(frame["provider"]) != {"GCP", "Databricks"}):
        raise ValueError("Both providers are required in an automatic snapshot.")
    _check_billing_scope(frame, marketplace=version == 4)
    if version == 4:
        frame.attrs['marketplace_billing'] = True
        frame.attrs['source_as_of'] = dict(payload['source_as_of'])
    if version >= 3:
        daily = _check_daily(payload["daily_records"], frame, payload["source_as_of"])
        frame.attrs["daily_records"] = _clean(daily, DAILY_COLUMNS)
    return payload["as_of"], frame
