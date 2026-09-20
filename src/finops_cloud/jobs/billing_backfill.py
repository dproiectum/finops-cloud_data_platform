"""Initial history load: invoke the monthly close logic for every billing month."""

from __future__ import annotations

import argparse
from datetime import date
import json

from finops_cloud.jobs.monthly_close import run as close_month


def month_range(start_month: str, end_month: str) -> list[str]:
    start_year, start_number = map(int, start_month.split("-"))
    end_year, end_number = map(int, end_month.split("-"))
    start = date(start_year, start_number, 1)
    end = date(end_year, end_number, 1)
    if start > end:
        raise ValueError("start_month must be before or equal to end_month")
    result = []
    current = start
    while current <= end:
        result.append(current.strftime("%Y-%m"))
        current = date(
            current.year + (1 if current.month == 12 else 0),
            1 if current.month == 12 else current.month + 1,
            1,
        )
    return result


def run(environment: str, start_month: str, end_month: str, archive: bool = True):
    results = []
    for month in month_range(start_month, end_month):
        results.append(close_month(environment, month, archive=archive))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("dev", "prod"), required=True)
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    results = run(
        args.environment,
        args.start_month,
        args.end_month,
        archive=not args.no_archive,
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
