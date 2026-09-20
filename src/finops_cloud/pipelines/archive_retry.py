"""Retry only the GCS archival phase for a closed month."""

from __future__ import annotations

import argparse
import json

from finops_cloud.archive import archive_month, write_archive_audit
from finops_cloud.audit_runs import finish_run, set_month_status, start_run
from finops_cloud.audit_snapshots import ensure_audit_tables
from finops_cloud.config import load_config
from finops_cloud.runtime import ensure_schemas, get_spark


def run(environment: str, month: str):
    """Retry GCS archival for a loaded month without reloading Delta tables."""
    config = load_config(environment)
    spark = get_spark(config.profile)
    ensure_schemas(spark, config)
    ensure_audit_tables(spark, config)
    run_id = start_run(spark, config, "archive_retry", month)
    try:
        records = archive_month(config, month)
        write_archive_audit(spark, config, run_id, month, records)
        set_month_status(spark, config, month, "CLOSED", "MONTHLY_BILLING", run_id)
        finish_run(spark, config, run_id, "SUCCESS")
        return {"run_id": run_id, "month": month, "archive_objects": len(records)}
    except Exception as exc:
        finish_run(spark, config, run_id, "FAILED", str(exc))
        raise


def main() -> None:
    """Parse Python Script Task arguments and run an archive retry."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("dev", "prod"), required=True)
    parser.add_argument("--month", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.environment, args.month), indent=2))


if __name__ == "__main__":
    main()
