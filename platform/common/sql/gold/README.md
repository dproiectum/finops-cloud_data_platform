# Gold schema maintenance

## Remove the unsupported charge-subcategory attribute

The Azure-derived source/contract has no `ChargeSubcategory`. The old Gold model
invented `charge_subcategory = 'Unknown'`; no business information is represented
by it. The maintained DDL, dimension loader, charge-type datamart, serving view
and both dashboard query modes now omit this attribute.

The old SHA-256 key format is intentionally retained in the dimension and fact
loaders. Its literal `Unknown` token is only backward compatibility for already
stored foreign keys, not an exposed field. Removing that token would be a
different migration requiring fact-key rewrites. This maintenance does not do so.

Manual sequence for existing DEV and PROD tables:

1. Update the Databricks Git folder to this code version. Stop scheduled loads
   and avoid dashboard queries during the short schema-maintenance window.
2. Open `platform/common/notebooks/operations/remove_charge_subcategory.ipynb`
   from that Git folder, attached to Spark compute (classic or serverless).
3. Set `ENVIRONMENT = 'dev'` and
   `CONFIRMATION = 'REMOVE_CHARGE_SUBCATEGORY'`. Run the notebook cells in order.
   It blocks on any non-placeholder value, unexpected/duplicate key, or orphan
   fact. It preserves dimension keys, verifies fact counts and costs before and
   after, and rebuilds only `dm_cost_by_charge_type`. Inspect the final `PASS`.
4. Repeat with `ENVIRONMENT = 'prod'` after the DEV checks pass.
5. Execute the updated `platform/common/sql/security/04_create_dashboard_serving_view.sql`
   in PROD, followed by `05_validate_dashboard_serving_view.sql`. This is the
   correction for the original unresolved-column error; do not run an old copy.
6. Verify the dashboard using the updated application code, then resume jobs.
   An application deployment is needed to change the hosted dashboard. This
   repository edit does not deploy it or publish a Git commit automatically.

No source upload, RAW/Bronze/Silver reload, fact rewrite or security-assignment
change is required. `CREATE TABLE IF NOT EXISTS` alone does not migrate existing
tables. New installations use the new three-column dimension directly.

The notebook materializes this small dimension before replacement to avoid
reading the replacement target. Delta `CREATE OR REPLACE TABLE` preserves its
history and grants. The previous version is printed for a manually approved
`RESTORE TABLE` if needed. Do not resume jobs after a failed maintenance step;
correct the cause and rerun. A datamart-refresh failure after dimension replacement
can be retried without writing the dimension again.

Cost-center allocation is a separate manual operation described below. Existing
`CostCenter_APAC`, `CostCenter_IOC` and `CostCenter_NAM` are preserved; their
business meanings still require a confirmed organizational reference.

## Apply the synthetic regional Cost Center policy

This is an explicit project scenario, not a discovery of Azure ownership data.
The policy applies only when the source center is null, blank or a placeholder.

| Priority | Condition | Allocated center | Method |
|---|---|---|---|
| 1 | Usable source `x_CostCenter` | Original code, trimmed for display | `SOURCE` |
| 2 | West Europe, North Europe, France Central, Sweden Central, UK South | `CostCenter_Europe` | `REGION_EUROPE` |
| 3 | Global | `CostCenter_Corporate` | `GLOBAL_CORPORATE` |
| 4 | Explicit headquarters-region allowlist | `CostCenter_Corporate` | `REGION_CORPORATE` |
| 5 | All other cases, including a missing Region | `Unallocated Costs` | `UNALLOCATED` |

The allowlist is initially empty: `[cost_allocation].corporate_regions = []`
in `config/common.toml`. Add only region names explicitly approved for the
central budget. The display bucket "Other regions" is not a region or a rule.
Europe defaults and Global cannot also be added to the Corporate allowlist.

`gold.v_cost_allocation` reads authoritative central Silver at charge grain.
It retains `cost_center_source`, adds `cost_center_allocated`, `allocation_method`
and `allocation_policy_version`, and changes no costs. It is a logical view,
not another copy of the charges. This avoids forcing a single center on all
regions of a subscription through the Type-1 `dim_billing_scope`.
Datamart 03 and the protected serving view both consume this shared policy.

Manual application to already loaded environments:

1. Push the reviewed code and pull the Databricks Git folder. Pause ingestion
   jobs and dashboard queries until both the datamart and serving view agree.
2. Complete the charge-subcategory maintenance above if it is still pending.
3. Open `platform/common/notebooks/operations/apply_cost_center_allocation.ipynb`
   on Spark compute. Set `ENVIRONMENT = 'dev'` and
   `CONFIRMATION = 'APPLY_COST_CENTER_ALLOCATION'`, then run all cells.
4. The notebook first reconciles monthly Silver and Gold fact row counts and
   Billed/Effective/List costs. If they differ, it stops before publication.
   On success it publishes only the Gold view and datamart 03, reconciles
   Billed Cost by month, checks the sources again and prints `PASS` plus shares.
5. Repeat with `ENVIRONMENT = 'prod'`, then execute updated security SQL
   `04_create_dashboard_serving_view.sql` and `05_validate_dashboard_serving_view.sql`.
   The view owner must have access to the new Gold view and underlying Silver.
6. Deploy the updated dashboard, inspect Cost Centers in the public and protected
   modes you use, and resume jobs only after the controls pass.

No Parquet upload, complete backfill, fact rewrite, dimension-key migration or
entitlement change is required. Normal daily/monthly jobs now refresh the allocation
view before rebuilding datamarts, so the policy applies to future loads too.
If maintenance fails after view creation, keep jobs paused, correct the cause
and rerun; the view and datamart refreshes are idempotent, but not one combined
transaction. To revise the policy or allowlist, rerun this manual sequence.

The Allocation coverage metric counts simulated Europe/Corporate assignments as
allocated. It is not a measure of the completeness of original source metadata.

Reference: https://docs.databricks.com/gcp/en/sql/language-manual/sql-ref-syntax-ddl-create-table-using
