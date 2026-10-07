"""Build a reviewed public snapshot from normalized, monthly CSV exports.

Run locally, not as a dashboard callback. No cloud connection or credentials.
Raw identifiers / additional columns are refused rather than silently published.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_costs.model import COLUMNS, SNAPSHOT_PATH, validate_records


def read_aggregate_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(COLUMNS) or set(reader.fieldnames) != set(COLUMNS):
            raise ValueError("Expected exactly the documented monthly aggregate CSV columns.")
        return list(reader)


def build_payload(records, as_of):
    date.fromisoformat(as_of)
    frame = validate_records(records)
    if frame.empty:
        raise ValueError("No cost rows to publish.")
    clean = []
    for row in frame.sort_values(["month", "provider", "service", "currency"]).to_dict("records"):
        clean.append({key: str(row[key]) if isinstance(row[key], Decimal) else row[key]
                      for key in COLUMNS})
    return {"schema_version": 1, "approved_for_publication": True,
            "as_of": as_of, "records": clean}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcp", type=Path, help="Normalized monthly GCP CSV, kept outside Git.")
    parser.add_argument("--databricks", type=Path, help="Normalized monthly Databricks CSV, kept outside Git.")
    parser.add_argument("--as-of", required=True, help="Extraction date, YYYY-MM-DD.")
    parser.add_argument("--approve-publication", action="store_true",
                        help="Confirm that every row/label is approved for the public portfolio.")
    args = parser.parse_args()
    if not args.approve_publication:
        parser.error("Review the aggregates, then explicitly pass --approve-publication.")
    if not args.gcp and not args.databricks:
        parser.error("Provide at least one aggregate CSV.")
    try:
        rows = [row for path in (args.gcp, args.databricks) if path
                for row in read_aggregate_csv(path)]
        payload = build_payload(rows, args.as_of)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    # Atomic replacement: a failed export/validation cannot destroy the last snapshot.
    temporary = SNAPSHOT_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(SNAPSHOT_PATH)
    print(f"Prepared {len(payload['records'])} approved monthly aggregates. Review the Git diff before pushing.")


if __name__ == "__main__":
    main()
