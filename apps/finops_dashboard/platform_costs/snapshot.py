"""One publication contract shared by the collector and dashboard."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .model import COLUMNS, validate_records


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


def build_payload(records, *, generated_at, gcp_extracted_at):
    generated = utc_timestamp(generated_at)
    check_freshness(gcp_extracted_at, generated)
    frame = validate_records(records)
    if frame.empty or set(frame["provider"]) != {"GCP", "Databricks"}:
        raise ValueError("Automatic publication requires both validated providers.")
    clean = []
    for row in frame.sort_values(["month", "provider", "service", "currency"]).to_dict("records"):
        clean.append({key: str(row[key]) if isinstance(row[key], Decimal) else row[key]
                      for key in COLUMNS})
    return {"schema_version": 2, "approved_for_publication": True,
            "as_of": generated.date().isoformat(), "generated_at": generated.isoformat(),
            "source_as_of": {"GCP": utc_timestamp(gcp_extracted_at).isoformat(),
                             "Databricks": generated.isoformat()}, "records": clean}


def read_payload(payload, *, remote=False, now=None, max_age_hours=48):
    if not isinstance(payload, dict):
        raise ValueError("Expected a platform cost snapshot object.")
    version = payload.get("schema_version")
    expected = {"schema_version", "approved_for_publication", "as_of", "records"}
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("Unsupported platform cost snapshot version.")
    if version == 2:
        expected |= {"generated_at", "source_as_of"}
    if set(payload) != expected or (remote and version != 2):
        raise ValueError("Unexpected snapshot fields or legacy remote snapshot.")
    if type(payload["approved_for_publication"]) is not bool:
        raise ValueError("Publication approval must be a boolean.")
    if payload["approved_for_publication"] is not True:
        return None, validate_records([])
    if not isinstance(payload["as_of"], str):
        raise ValueError("A snapshot needs an extraction date.")
    date.fromisoformat(payload["as_of"])
    if version == 2:
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
    if version == 2 and (frame.empty or set(frame["provider"]) != {"GCP", "Databricks"}):
        raise ValueError("Both providers are required in an automatic snapshot.")
    return payload["as_of"], frame
