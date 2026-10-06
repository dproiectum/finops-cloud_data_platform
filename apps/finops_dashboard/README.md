# FinOps Control Center

Read-only Streamlit application for the certified `finops_prod.datamart`
tables and the environment-aware `finops_ops.audit` history.

## Functional pages

- **Knowledge Base**: FOCUS column dictionary, cost formulas, interpretation
  limits, glossary and the Inform–Optimize–Operate lifecycle;
- **Executive Overview**: monthly KPIs, month-over-month change and daily/monthly
  trends;
- **Cost Drivers**: services, charge categories and portfolio SKU analysis;
- **Savings**: net price benefit and an effective-cost breakdown by pricing type;
- **Allocation & Accountability**: cost centers, services, subscriptions and
  application owners;
- **Resources**: resources, regions and resource groups;
- **Operations & Quality**: critical completeness, pipeline runs, reconciliation
  and DEV/PROD audit separation;
- **Architecture**: end-to-end lineage, Medallion layers and certified products.

The application never writes to Unity Catalog.

Amounts, percentages and counts use European display formatting (for example,
`912 000,00 €`, `14,66 %` and `164 145`), including financial tables and monetary
chart axes. Monthly charts treat `YYYY-MM` as a category so that each month remains
readable. Formatting does not change stored values. Read-only query changes
aggregate services by name and expose existing cost bases for the new views.
The deployed application receives these changes only after its source is updated
and a new revision is deployed.

## Periods and chart interpretation

- The native top navigation bar replaces the sidebar radio selector. The sidebar
  holds year, month and comparison filters; only the selected page is executed.
- Select a billing year before choosing a month. Executive Overview also offers
  Annual and, when two years are available, Year-over-year views.
- Annual totals include only loaded months. Year-over-year comparisons use the
  intersection of loaded month numbers in the two selected years, not a complete
  year against a partial year. The difference rate is computed from summed cost
  bases, not the average of monthly rates. Distinct monthly resource/service counts
  are not summed into annual distinct counts.
- Savings stacks Effective Cost (dark blue) and Realized Savings (light green).
  Their total equals List Cost. There is no Contract Cost marker or third series.
  If a list/effective cost is negative or missing, or Effective Cost exceeds List
  Cost, the same two series use grouped bars; negative values are never clipped.
  The title and display label are **Realized Savings**, defined as List Cost minus
  Effective Cost. The green-bar tooltip shows List Cost followed by Realized Savings,
  with European currency formatting. The page retains a warning that these synthetic
  cost comparisons do not establish realized organizational or cash savings.
- **Detailed Table** uses business labels in this order: Billing Month, List Cost,
  Contract Cost, Negotiated Savings, Reservation, Savings Plan, Usage On-Demand,
  Usage Dynamic, Adjustment, Effective Cost, Realized Savings, Saving Rate. Commitment Savings is
  no longer displayed. Reservation and Savings Plan are sums of source
  `EffectiveCost` on the corresponding commitment-based Usage rows, not full
  upfront purchase prices. Other Charges appears before Effective Cost only
  when remaining charge types contribute a non-zero net amount.
- Service charts aggregate by service name before applying their top-N limit.
  Each name has one blue bar, with no service-category legend. Allocation provides
  highest-cost-first, lowest-cost-first and alphabetical order for the displayed
  top 30 services. Cost Drivers shows the top 20 and explains charge categories;
  negative charges remain visible to the left of zero.

## One-time Savings datamart update

The five effective-cost components require the updated canonical SQL template:
`platform/common/sql/datamarts/table_refresh/08_dm_savings_monthly.sql`.
The standard datamart refresh already executes this template for DEV and PROD;
no new pipeline task or duplicate setup script is required. Classic compute and
serverless use the same template.

After the GitHub push and Databricks Git Folder pull, **manually** refresh just
this derived table for the dashboard. Attach a Python notebook to your usual
Unity Catalog-compatible compute in the Belgium workspace, restart its Python
session if it imported an older package, then run:

```python
import sys
from pathlib import Path

project_root = Path("/Workspace/Users/thailongdam@gmail.com/finops-cloud_data_platform")
assert (project_root / "src/finops_cloud").is_dir(), "Check the Git Folder path"
sys.path.insert(0, str(project_root / "src"))

from finops_cloud.config import load_config
from finops_cloud.sql.runner import execute_sql_file, table_context

config = load_config("prod", project_root)
execute_sql_file(
    spark,
    "datamarts/table_refresh/08_dm_savings_monthly.sql",
    table_context(config),
)

display(spark.sql("""
    SELECT billing_month, reservation, savings_plan, usage_on_demand,
           usage_dynamic, adjustment, other_effective_cost, effective_cost,
           effective_cost - (
               reservation + savings_plan + usage_on_demand + usage_dynamic
               + adjustment + other_effective_cost
           ) AS breakdown_difference
    FROM finops_prod.datamart.dm_savings_monthly
    ORDER BY billing_month
"""))
spark.sql("""
    SELECT assert_true(count(*) > 0, 'No monthly savings rows'),
           assert_true(
               coalesce(max(abs(effective_cost - (
                   reservation + savings_plan + usage_on_demand + usage_dynamic
                   + adjustment + other_effective_cost
               ))), 0) < 0.01,
               'Effective-cost breakdown does not reconcile'
           )
    FROM finops_prod.datamart.dm_savings_monthly
""").collect()
```

This replaces only `finops_prod.datamart.dm_savings_monthly` using existing
Silver rows; it does not reload sources, reset catalogs, change GCS files or
rerun ingestion. Use `dev` instead of `prod` and adjust the control query catalog
if you also want to update DEV. Standard future pipeline runs retain these
columns automatically through the shared template.

Before the refresh, the dashboard remains usable with the previous datamart
schema. Missing components show **—**, not fabricated zeroes, and an information
message explains the required refresh. After execution, allow up to five minutes
for the dashboard query cache to expire, then reload the Savings page.

The Knowledge Base documents both `SUM(EffectiveCost)` and the equivalent
component sum. This is a presentation breakdown of existing effective costs,
not a new amortization calculation. The generator preserves/scales the source
cost columns rather than deriving EffectiveCost from ContractedCost.

Source: https://focus.finops.org/docs/specification/v1-0/columns/cost-and-usage/effective-cost/.

## Security boundary

The backend identity and read-only SQL access are separate from viewer
authorization. The public deployment still uses global synthetic datamarts.
Local code supports `public`, local-only `demo`, opt-in public synthetic
`portfolio_demo`, and verified `iap` modes. `portfolio_demo` adds four fixed
profiles; it requires `FINOPS_PORTFOLIO_DATA_APPROVED=true`, blocks raw OPS reads,
and must be checked against clean PROD before deployment. Profile selection is
not user authentication. Follow `security/README.md` for its grants and checks.
Protected queries enforce live viewer entitlements before aggregation and
do not share Streamlit query-result caches. This is application-level enforcement,
not a Unity Catalog row-filter policy. No private IAP service or real-user access
has been deployed by this change. A public portfolio must use synthetic data only;
a demonstration persona selector is not production authentication.

### Implementation and remaining live validation

Manual metadata scripts are available under `platform/common/sql/security/`.
They seed two confirmed PROD application scopes and three synthetic demo
entitlements only. Files 04/05 now create and validate an ordinary charge-grain
serving view, without reloading data. Execute them manually, then follow
`apps/finops_dashboard/security/README.md` for isolated local tests. SQL setup alone
does not enable viewer enforcement on the public site.

1. Confirm the application/project/domain keys and the hierarchy used for scopes.
   The owner datamart retains `application_code`; the scope/service datamart does
   not, and the executive and savings datamarts are global monthly aggregates.
   Filtering only the owner page would leave other pages leaking global data.
2. Create `finops_ops.security.user_entitlement` and `business_scope`, and populate
   approved synthetic assignments for a first controlled demonstration. This is
   additive setup, not a catalog reset or a full data reload.
3. Scoped modes enforce scope before aggregation through bound parameters and
   live entitlement predicates against a charge-grain serving view. Test this
   against the real synthetic dataset. Local demo/IAP OPS is administrator-only;
   public portfolio Admin receives completeness statistics, never raw OPS history.
4. Protected mode disables query-result and permission caches. Test
   both page navigation and table export; hiding navigation is not authorization.
5. For deployed authentication, configure IAP, validate the signed assertion with
   its expected audience and expiry, and reject missing or invalid identities.
   A fixed-persona selector is a synthetic authorization test harness only.
6. Retain denial/isolation tests, deployed revision, sanitized grants and matched
   scoped totals. Chapter 5.3.6 describes the design; chapter 7.5 reports results
   only after execution. Distinguish local implementation, fixture results and
   live deployment evidence rather than reporting them as one completed stage.

Sources: https://docs.cloud.google.com/iap/docs/identity-howto;
https://docs.cloud.google.com/iap/docs/signed-headers-howto.

## Cloud Run deployment: current dashboard

The current service is `finops-center` in project `global-repeater-355412`, region
`europe-west1`. Both URLs address the same service:

```text
https://finops-center-243421621568.europe-west1.run.app/
https://finops-center-wf2b3fv3sq-ew.a.run.app/
```

The enabled Cloud Build trigger watches `main` in
`https://github.com/dproiectum/finops-cloud_data_platform`, uses
`apps/finops_dashboard/Dockerfile`, and deploys that service. Its ID is
`aadfa4c5-3885-4a5f-83ff-5fd12e7829a5`; the trigger region is `global`, distinct
from the service region. This was read from the live configuration on 4 October
2026. There are currently no included/ignored-file filters, so any push to that
branch can initiate deployment. The inspected service has invoker IAM checking
disabled; this is not evidence of IAP or user-level scope protection.

After review, publish only the related changes from the Cloud platform repo:

```bash
cd "/Users/dtl/Desktop/PFE/FinOps Cloud Data Platform"
git add -- apps/finops_dashboard/app.py apps/finops_dashboard/charts.py apps/finops_dashboard/formatting.py apps/finops_dashboard/queries.py apps/finops_dashboard/knowledge.py apps/finops_dashboard/README.md platform/common/sql/datamarts/table_refresh/08_dm_savings_monthly.sql tests/unit/test_dashboard.py tests/unit/test_dashboard_presentation.py tests/unit/test_sql_model.py
git diff --cached --check
git diff --cached --stat
git commit -m "Clarify Savings dashboard and expose effective cost components"
git push origin main
```

Do not include unrelated working-tree changes. If Git rejects the push because
the remote advanced, fetch and reconcile the commits rather than forcing it.
The push triggers a new build and deployment, which can incur GCP charges.

1. Open Cloud Build **History**, choose region **Global**, and find the build for
   the pushed commit. Wait for success, not just a successful image build step.
2. Open Cloud Run **finops-center > Revisions** and verify the new ready revision
   receives traffic and its commit label matches the pushed commit.
3. Reload the dashboard. Verify European metrics/table/hover formats, the top
   navigation, sorting, Savings and both annual views. Preserve a C5 screenshot
   only after this verification.
4. Run only the targeted Savings datamart refresh above to populate its new
   components. No ingestion pipeline or catalog-creation SQL needs to run.
   Keep the existing credentials and SQL Warehouse config.

If the trigger did not run, the operator can launch it manually:

```bash
gcloud builds triggers run aadfa4c5-3885-4a5f-83ff-5fd12e7829a5 --branch=main --region=global --project=global-repeater-355412
```

This starts a build/deployment. Do not run it again if the pushed commit already
has a successful deployed build. Restarting Streamlit or redeploying the old image
alone does not incorporate changed source code.

Source: https://docs.cloud.google.com/run/docs/continuous-deployment.

## Alternative: Databricks App resources

Create a custom Databricks App and add the SQL Warehouse with resource key:

```text
sql-warehouse
```

Select permission **Can use**. `app.yaml` maps that resource to
`DATABRICKS_WAREHOUSE_ID`; the application resolves its ODBC connection details
through the Databricks SDK. No warehouse ID, token or hostname is committed.

In **Databricks Apps > finops-center > Authorization**, copy the app service
principal's **Service principal ID** (`applicationId`). Do not use the short
display label such as `app-1wgoyz`; Unity Catalog identifies a service principal
by its application ID.

Grant that application ID read-only access to the required namespaces:

```sql
GRANT USE CATALOG ON CATALOG finops_prod TO `<service-principal-application-id>`;
GRANT USE SCHEMA ON SCHEMA finops_prod.datamart TO `<service-principal-application-id>`;
GRANT SELECT ON SCHEMA finops_prod.datamart TO `<service-principal-application-id>`;

GRANT USE CATALOG ON CATALOG finops_ops TO `<service-principal-application-id>`;
GRANT USE SCHEMA ON SCHEMA finops_ops.audit TO `<service-principal-application-id>`;
GRANT SELECT ON SCHEMA finops_ops.audit TO `<service-principal-application-id>`;
```

Keep the backticks around the application ID. If your
governance policy requires table-level grants, grant `SELECT` only on the
datamarts and the `pipeline_run` and `monthly_reconciliation` audit tables.

## Alternative: Databricks App deployment

1. Pull the latest `main` branch into the Databricks Git Folder.
2. Open **Databricks Apps** and create a custom app named `finops-center`.
3. Configure the project Git repository and the `main` branch.
4. At deployment, select **From Git** and set **Source code path** exactly to
   `apps/finops_dashboard`. If replacing a previous deployment, use
   **Deploy using a different source**.
5. Add the SQL Warehouse resource using the key `sql-warehouse` and permission
   **Can use**.
6. Apply the read-only Unity Catalog grants above.
7. Deploy and inspect the application logs if the health check fails.

The default environment is PROD. A separate deployment can set
`FINOPS_ENVIRONMENT=dev` and `FINOPS_DATABRICKS_CATALOG=finops_dev` without code
changes.
