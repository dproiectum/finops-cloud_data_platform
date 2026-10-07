# Project Costs — public serving and source preparation

The **Project Costs** tab is under **About the Project** (`/about`), not a separate
main navigation entry. Its cost data is separate from the synthetic Azure dashboard.
The repository ships
an **empty, unapproved** snapshot, not invented costs. Missing data is unavailable,
not zero. The application reads only `snapshot.json`, never live operational
billing data. Demo profiles cannot change this publication scope.

## What is implemented

- Monthly service/SKU aggregates, own year/month/currency filters.
- GCP cost before credits and net cost; signed credits/corrections retained.
- Databricks signed DBUs and published-list cost **estimate**, not paid cost.
- Trend, descending service breakdown, detailed table with two-decimal European
  formatting, extraction date and explicit partial-period status.
- No combined billed total or currency conversion. Databricks Marketplace charges
  in GCP could overlap the separate Databricks estimate.
- Platform sustainability belongs here, not in the synthetic Azure consumption
  page. Databricks emissions are not estimated; energy or hardware/runtime data
  and a documented method would be required. DBUs are not converted to kgCO2e.
- An allowlisted snapshot contract: no project/workspace/job/resource/user IDs,
  paths, principal emails, or additional raw metadata columns.

## Automatic feeding — recommended next rollout (not deployed)

Keep the source process independent of Azure daily/monthly ingestion:

1. Enable GCP **Billing → Billing export → BigQuery export → Standard usage cost**.
   Select the correct billing account/project and a suitable EU dataset. This
   requires billing/export permissions and may incur BigQuery/storage charges.
   Enabling an export does not guarantee that the complete earlier history exists.
2. The owner confirmed the Standard export table on 2026-10-07:
   `global-repeater-355412.finops_billing.gcp_billing_export_v1_01C7B0_D31E31_1E865E`.
   Run `sql/00_check_gcp_export.sql` in **BigQuery** to inspect loaded months,
   first/last available usage dates and currency. Then run
   `sql/01_export_gcp_monthly.sql`; both files use the confirmed table and project
   filter. Estimate processed bytes before execution. Initial billing backfill can
   still be in progress; successful queries alone do not establish completeness.
   Verify cost types, credits and currency before publication.
3. Run `sql/02_export_databricks_monthly.sql` in **Databricks SQL**. The selected
   project workspaces are aggregated together; this is not a per-job cost.
   Missing prices must be resolved, not replaced by zero. Price intervals or month
   boundaries that straddle usage records need an explicitly agreed attribution
   method if present; the initial export attributes usage to its UTC start month.
4. For scheduled feeding, create a **separate monitoring Job** to extract both
   sources into private `finops_ops.monitoring` tables, validate completeness,
   currency, price matches and monthly keys, and produce the same public contract.
   A restricted credential reads BigQuery; the dashboard must not receive access
   to raw billing or `system.billing`. Do not schedule this on the business daily
   Job or repeatedly restart a large All-Purpose cluster for a small aggregation.
5. Serve the approved output through a dedicated public aggregate view or GCS
   object. Switch `load_snapshot()` to that reader with least-privilege read access,
   freshness checks and fail-closed validation. Keep the current reviewed snapshot
   as an explicit deployment mode, never as a silent fallback on access failure.
   The source process, grants, scheduled task and remote reader are **not** installed
   by this change; enable/configure them manually after confirming the export.

This sequence requires a real export table and credential/serving decision before
the scheduled Job can be wired correctly. No cloud resource, new permission,
billable schedule, SQL table or business-pipeline run is created automatically.

## Optional first snapshot (no new recurring infrastructure)

Export the final SELECT from each query as CSV, without altering precision. Keep
exports **outside the Git repository**. The exact columns are:

```text
month,provider,service,currency,cost_before_credits,credits,usage_quantity,usage_unit,cost_basis,period_status
```

Use `YYYY-MM`, numeric decimal points without thousands separators, signed
credits, blank Databricks credits and blank GCP usage. A month remains `partial`
until the extraction coverage is independently confirmed. Do not infer a complete
month from a high measurement-coverage percentage.

From the cloud repository root, after reviewing the aggregates:

```bash
python apps/finops_dashboard/project_costs/publish_snapshot.py \
  --gcp /private/tmp/gcp-monthly.csv \
  --databricks /private/tmp/databricks-monthly.csv \
  --as-of 2026-10-07 \
  --approve-publication
git diff -- apps/finops_dashboard/project_costs/snapshot.json
```

Replace the extraction date each time. Either provider can be supplied alone;
the absent provider remains unavailable. This command replaces the snapshot only
after validation; it does not query clouds, push Git or deploy anything. Rebuild
the dashboard image to publish an updated bundled snapshot. Source data and
Azure/FOCUS processing stay unchanged.

Sources:
https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery
https://docs.cloud.google.com/billing/docs/how-to/bq-examples
https://docs.databricks.com/gcp/en/admin/system-tables/pricing
