# FinOps Cloud Data Platform

Active Databricks/GCP implementation evolved from the local POC. Code is
versioned in GitHub, developed either in VS Code or a Databricks Git Folder,
executed in Databricks DEV, and promoted to PROD through a Databricks Bundle.

The historical prototype remains in `../FinOps Data Platform - POC`. The shared
synthetic dataset is produced by `../FinOps Data Generator`.

## Databricks notebooks

The `notebooks/` directory provides interactive pipeline entry points. Each
notebook separates runtime parameters, the call to maintained Python code, and
result inspection. Business logic remains centralized in `src/` and `sql/`.

Engineers open these notebooks from a Databricks Git Folder and run one cell at
a time for demonstrations and troubleshooting. Automated Bundle Jobs execute
thin Python entry points from `scripts/`; both interfaces call the same modules
under `src/`.

## Job execution model

The four Jobs are Python script tasks. Each run checks out the configured
GitHub branch and executes one file from `scripts/`. The scripts only expose a
command-line entry point; pipeline logic remains in `src/finops_cloud`.

The Bundle deploys Job configuration, parameters, and runtime dependencies. It
does not package the project into a wheel for these Jobs.

## Python source layout

`src/finops_cloud` is deliberately organized around the processing flow:

- `contract.py`: FOCUS Data Contract loading, casts, and blocking checks;
- `delta.py`: idempotent append and atomic monthly replacement primitives;
- `silver.py`: canonical Silver metadata and month controls;
- `gold.py`: execution order for Gold SQL and datamart refresh;
- `audit_runs.py` and `audit_snapshots.py`: operational traceability;
- `archive.py`: verified and resumable GCS archival;
- `pipelines/`: end-to-end daily, monthly, backfill, and archive orchestration;
- `config.py`, `runtime.py`, and `sql_runner.py`: shared platform utilities.

Every function has an English docstring describing its responsibility.

## Architecture

```text
FinOps Data Generator
        ↓ publish without regeneration
gs://dtl_finops/focus
        ↓
Databricks Bronze → Data Contract → canonical Silver + central table
        ↓                            ↑
Gold dimensions/fact                 │ atomic monthly replacement
        ↓                            │
Datamarts                    Monthly billing
        ↓
SQL Warehouse / Dashboard

After close: gs://dtl_finops/focus → gs://dtl_finops/focus_archive
```

## Four Jobs, two business flows

- `finops-daily` appends new daily files to open months.
- `finops-monthly` captures `BEFORE`, `SOURCE`, and `AFTER`, atomically replaces
  the month with billing data, refreshes Gold/datamarts, and archives sources.
- `finops-backfill` invokes the same monthly close for every historical month;
  it does not duplicate close logic.
- `finops-archive` retries only a pending GCS archive operation.

Raw and Bronze are never deleted. Replacement applies to Silver, the central
table, and the logical monthly partition of the Gold fact table.

## Gold model and datamarts

The cloud model preserves the POC star schema: ten dimensions,
`bridge_resource_tag`, `fact_finops_cost_usage`, and fourteen datamarts. SQL
owns the physical structures and transformations; PySpark controls execution.

- Model documentation: `docs/data_model.md`
- Gold table creation: `sql/gold/table_creation`
- Gold data loading: `sql/gold/data_loading`
- Datamart refresh: `sql/datamarts/table_refresh`
- Shared SQL runner: `src/finops_cloud/sql_runner.py`

## Environment-specific settings

Common values live in `config/common.toml`. Environment-specific values are
limited to:

```text
config/dev.toml
config/prod.toml
databricks.yml
```

Review before the first execution:

1. Databricks profiles `finops-gcp-dev` and `finops-prod`.
2. Catalogs `finops_dev` and `finops_prod`.
3. External Volumes pointing to `focus` and `focus_archive`.
4. The GCS bucket when it differs from `dtl_finops`.
5. The GCP project and `finops-gcs-dev/prod` Service Credentials used by the
   SDK during archival.
6. The `databricks-connect` version so it matches the selected Runtime.

Never commit tokens, GCP secrets, or service-account key files. Databricks
authentication uses OAuth profiles. External Volumes use a Unity Catalog
Storage Credential. The archival SDK uses a Unity Catalog Service Credential
in Jobs or Application Default Credentials during controlled local tests.

See `docs/databricks_gcs_setup.md` for the administrative setup procedure.

## VS Code environment

Use a dedicated Python version compatible with the Databricks Runtime, for
example Python 3.12:

```bash
cd "/Users/dtl/Desktop/PFE/FinOps Cloud Data Platform"
python3.12 -m venv .venv-databricks
.venv-databricks/bin/python -m pip install -e '.[databricks,dev]'
```

`databricks-connect>=17.3,<17.4` is the initial constraint. Adjust it when the
selected compute uses a different Databricks Runtime.

## Run from VS Code

One daily file:

```bash
.venv-databricks/bin/finops-daily \
  --environment dev \
  --source-uri /Volumes/finops_dev/raw/focus/daily/year=2026/month=07/day=01/focus-2026-07-01.parquet
```

Monthly close:

```bash
.venv-databricks/bin/finops-monthly --environment dev --month 2026-07
```

Initial backfill:

```bash
.venv-databricks/bin/finops-backfill \
  --environment dev \
  --start-month 2025-01 \
  --end-month 2026-06
```

## Deployment

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run -t dev daily_incremental \
  --params source_uri=/Volumes/finops_dev/raw/focus/daily/year=2026/month=07/day=01/focus-2026-07-01.parquet
```

After DEV validation, promote the same artifact to PROD:

```bash
databricks bundle validate -t prod
databricks bundle deploy -t prod
```

## Monthly audit

The `ops` schema contains:

- `pipeline_run`: start, end, and status of each execution;
- `month_snapshot`: `BEFORE`, `SOURCE`, and `AFTER` metrics;
- `monthly_reconciliation`: Daily/Billing differences and technical controls;
- `month_status`: `OPEN`, `RECONCILING`, `CLOSED_ARCHIVE_PENDING`, or `CLOSED`;
- `file_archive`: URI, generations, CRC32C, and status of each moved object.

If loading succeeds but GCS archival fails, the month becomes
`CLOSED_ARCHIVE_PENDING`. A new monthly or `finops-archive` run retries only
archival and does not reload Silver.

## Local tests

Local tests do not start Spark or contact Databricks or GCS:

```bash
PYTHONPATH=src python -m unittest discover -s tests/unit -v
```

Integration tests run against the DEV catalog after the workspace, Runtime,
and External Volumes are configured.
