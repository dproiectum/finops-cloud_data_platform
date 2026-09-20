# Databricks restart and full-load Job

This manual Lakeflow Job resets project tables only when necessary, then loads
every active monthly billing through Bronze, the Data Contract, Silver, Gold,
the fourteen datamarts, reconciliation, and status controls.

## DAG

```text
check_tables_empty
        |
        v
are_tables_empty? ---- false ----> reset_all_tables
        |                                |
        | true                           |
        +---------------+----------------+
                        v
              load_all_monthly_to_gold
```

`load_all_monthly_to_gold` depends on both `check_tables_empty` and
`reset_all_tables` with **Run if = None failed**. Databricks treats the reset
task excluded by the true condition as successful. If the reset actually runs
and fails, the load task does not start.

## Job parameters

Create one job parameter:

| Name | Default |
|---|---|
| `environment` | `dev` |

## Tasks

### 1. `check_tables_empty`

- Type: Notebook
- Notebook: `notebooks/operations/check_tables_empty.ipynb`
- Dependency: none
- Parameter: `environment` = `{{job.parameters.environment}}`

The notebook publishes the boolean task value `tables_empty`.

### 2. `are_tables_empty`

- Type: If/else condition
- Depends on: `check_tables_empty`
- Left operand: `{{tasks.check_tables_empty.values.tables_empty}}`
- Operator: `==`
- Right operand: `true`

### 3. `reset_all_tables`

- Type: Notebook
- Notebook: `notebooks/operations/reset_all_tables.ipynb`
- Depends on: `are_tables_empty (false)`
- Parameters:
  - `environment` = `{{job.parameters.environment}}`
  - `confirm_reset` = `RESET`

This task truncates only project tables. It does not delete GCS Parquet files,
Volumes, schemas, or table definitions.

### 4. `load_all_monthly_to_gold`

- Type: Notebook
- Notebook: `notebooks/pipelines/00_all_monthly_to_gold.ipynb`
- Depends on: `check_tables_empty` and `reset_all_tables`
- Run if dependencies: **None failed**
- Parameters:
  - `environment` = `{{job.parameters.environment}}`
  - `archive_after_success` = `false`

Keeping `archive_after_success=false` is required for a repeatable restart Job:
the source Parquets remain under `gs://dtl_finops/focus/monthly/`. Archival can
be enabled in the operational monthly-close Job after restart validation.

## Compute and permissions

Use the same serverless environment or Job compute for all notebook tasks. It
must provide `PyYAML` and `google-cloud-storage`, and the Job identity needs:

- read access on the `finops_dev.raw.focus` Volume;
- create, select, modify, and usage rights for the `finops_dev` project schemas;
- access to the configured GCS Service Credential only when archival is enabled.

Do not schedule this administrative Job concurrently with Daily, Monthly Close,
Backfill, Archive Retry, dashboard refreshes, or other writers.
