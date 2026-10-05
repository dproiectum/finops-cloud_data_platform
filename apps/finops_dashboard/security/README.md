# Viewer scope enforcement — steps 7 and 8

The implementation is local until reviewed and deployed. No Git push, Cloud Run
change, or Databricks execution is performed by creating these files.

## Boundaries and status

| Mode | Identity | Queries | Intended use |
|---|---|---|---|
| `public` (current default) | None | Existing global datamarts | Existing synthetic portfolio only |
| `demo` | Four fixed synthetic personas | Live entitlement predicates | Local manual authorization tests only |
| `iap` | Verified IAP signed JWT subject | Live entitlement predicates | Future separate private Cloud Run service |

`demo` is rejected when Cloud Run sets `K_SERVICE`. On Cloud Run, `public` is
allowed only for the existing portfolio service named `finops-center`; a new
private service without its IAP configuration fails closed instead of becoming a
public fallback. Do not change the existing public service's mode during these
tests. An environment variable is not viewer authentication.

Authenticated mode accepts only `identity_provider='iap'` assignments using the
verified signed `sub`; it never accepts the `demo` rows or an unsigned email/id
header. An IAP-verified subject can be displayed before permissions are resolved
so an administrator can enroll that subject. This step does not yet enroll real
users or configure IAP on GCP. An expired signed assertion requires a browser
reload to establish a fresh session; unsigned headers are not an alternative.

This is application-level authorization, not a Unity Catalog row-filter policy.
The shared backend identity still reads the serving view globally. Visitors must
not receive backend credentials or direct SQL access. A public synthetic dataset
and its public service are not a secure deployment for confidential business data.
People who already have direct Databricks access retain their separate UC rights.

## Step 7.1 — Create the serving view manually

In SQL Editor of workspace-belgium, using the existing Warehouse
`137166118b7adca0`, execute these files in order and stop on any error:

Prerequisite: run the manual `apply_cost_center_allocation.ipynb` notebook in DEV
then PROD to create Gold `v_cost_allocation`, following the Gold README.

1. `platform/common/sql/security/04_create_dashboard_serving_view.sql`.
2. `platform/common/sql/security/05_validate_dashboard_serving_view.sql`.

The first file creates/replaces only `finops_prod.datamart.v_dashboard_charge_scoped`.
It does not change the fourteen datamart tables, reset catalogs, ingest Parquet, or
write another copy of the dataset. Silver publications are visible through this
ordinary view without another pipeline task. Run setup only after normal PROD
initialization and loading. Recreate the view if the whole catalog is reset.
The 30-business-table inventory controls now exclude views from their counts.

Create it as the existing owner/admin who can read the Gold allocation view
and PROD Silver. For the SQL
Warehouse backend, view consumers need SELECT on the view while the view owner
must retain permissions on its Gold view and the allocation view owner on Silver.
The existing dashboard service
principal's SELECT grant on `finops_prod.datamart` covers this view too; do not
grant that principal SELECT on all Silver tables just to run these tests.
The local tests below instead use your own interactive Databricks profile.

The validation checks charge counts and all four cost-column sums against Silver,
requires both selected applications to have charge rows, and emits per-month
reference totals. Successful assertions return NULL. The final result is:

```text
PASS: serving view preserves source costs; test application enforcement separately
```

Application membership comes from each charge's `ApplicationCode-Symphony` tag.
Unlike Gold's latest resource attributes, it does not retroactively transfer
historical untagged charges to the resource's latest application. Null/unknown
applications are visible to a global FinOps administrator, not restricted viewers.
Other labels also come from charge-grain Silver rather than latest Gold dimensions.
The source has no `ChargeSubcategory`; the serving view and dashboard do not
invent that attribute or rename a pricing subcategory into it. Migrate existing
Gold/datamart structures with the manual notebook described in
`platform/common/sql/gold/README.md` before running the updated loading SQL.
Source cost centers take priority. Missing centers follow the shared synthetic
Europe/Corporate policy; unmatched rows display as `Unallocated Costs`. Original
values and the allocation method remain visible in the serving view. No source
values or cost measures are rewritten. Allocation is not an authorization rule
and does not change application entitlements or infer commitment coverage.
Use the reference totals from this view when comparing application-owner sessions,
not the Type-1 owner datamart's retroactively conformed grouping.

## Step 7.2 — Prepare an isolated local Python environment

From a terminal on your Mac, run each command separately:

```bash
cd "/Users/dtl/Desktop/PFE/FinOps Cloud Data Platform"
python3 -m venv .venv-dashboard
source .venv-dashboard/bin/activate
python -m pip install -r apps/finops_dashboard/requirements.txt
```

This environment is ignored by Git and is separate from the POC environment.
Use Python 3.11 or newer supported by these dashboard dependencies. You do not
need to install the Spark pipeline package to run Streamlit.

Run the offline security tests first; they do not contact Databricks or GCP:

```bash
python -m unittest discover -s tests/unit -p 'test_dashboard_authorization.py' -v
```

The tests use clearly identified fixture data and patched certificate retrieval
for real ES256 signature checks. Passing them is not a live IAP deployment test.

## Step 7.3 — Authenticate locally to the Belgian workspace

With the current Databricks CLI installed, create a separate interactive profile:

```bash
databricks auth login --host https://8259550830613689.9.gcp.databricks.com --profile BELGIUM_DASHBOARD
```

Complete browser sign-in yourself. Do not paste tokens or the Cloud Run client
secret into code, chat, screenshots, or Git. Do not reuse the Frankfurt profile.
In the same terminal configure the read-only test connection:

```bash
export DATABRICKS_CONFIG_PROFILE=BELGIUM_DASHBOARD
export DATABRICKS_HOST=https://8259550830613689.9.gcp.databricks.com
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/137166118b7adca0
export FINOPS_ENVIRONMENT=prod
export FINOPS_DATABRICKS_CATALOG=finops_prod
export FINOPS_AUTH_MODE=demo
```

If this terminal already has service-principal/PAT authentication environment
variables from another task, open a clean terminal rather than mixing them with
this profile. Do not use `databricks auth env` for screenshots: it can reveal
credentials. The browser login authenticates the backend as you; the synthetic
selector separately exercises the application's viewer entitlement rules.

## Step 7.4 — Open the local test dashboard

```bash
python -m streamlit run apps/finops_dashboard/app.py --server.address=127.0.0.1 --server.port=8502
```

Open `http://127.0.0.1:8502`. Keep it bound to loopback, do not expose it with a
tunnel, and do not configure `demo` on the public Cloud Run service. These live
read queries can start the SQL Warehouse and incur Databricks/GCP charges.

## Step 8 — Manual validation on your real synthetic dataset

1. Select `demo-app-owner-a`: only APP00013057 should appear in application-owner
   tables/exports. Choose a loaded month and compare Executive/Savings totals with
   file 05's APP00013057 reference row for exactly the same month.
2. Select `demo-app-owner-b`: only BSN0003965; compare its corresponding references.
   Available years/months must also belong to that identity's scope.
3. Navigate through Executive (monthly, annual, year-over-year when available),
   Drivers (including cumulative services/SKUs), Savings, Allocation and Resources.
   All views and Streamlit table downloads must reflect the selected perimeter.
4. Select `demo-finops-admin`: global PROD charges, including unallocated records,
   are visible. Operations is available, but its queries show only the explicitly
   authorized environment; this app role is not Databricks administrator access.
5. Select `demo-no-access`: no business metrics/data; access refused.
6. Switch repeatedly A → B → A and try opening the bookmarked Operations URL as
   an owner. It must not expose OPS data. Restricted OPS methods also refuse access
   directly, not only through hidden navigation.
7. Use the fixture tests to exercise revocation/expiry, multi-assignment unions,
   invalid identities, duplicated/ambiguous mappings, SQL injection and exports.
   No SQL write/revocation against the live permission tables is automated here.
   A live revocation drill, if later explicitly approved, must record and restore the
   exact test row rather than resetting catalogs or reseeding it blindly.

An optional read-only query check compares application subsets and reference costs:

```bash
cd apps/finops_dashboard
python -m security.validate_live --month 2026-01
```

Use a loaded month with charges for both applications. This command performs live
queries and can incur Warehouse cost, but does not mutate configuration or data.
Its success message explicitly excludes live IAP/browser-deployment validation.

Record the commit/worktree revision, environment, identity, month, reference totals,
and screenshots without secrets. Do not claim that production user authentication
has passed until the separate private-service/IAP tests are executed.

## Enforcement and cost/performance tradeoffs

Every protected business query uses a bound identity/environment and live
entitlement predicates before aggregation. EXISTS implements union permissions
without multiplying charge rows. Application owners and domain/subdomain managers
need a unique active application mapping; unsupported project roles fail closed.
Missing/expired/revoked permissions, configuration errors, or backend failures do
not fall back to global data. The serving view does not expose raw Tags or source
file paths.

Protected query results and entitlements are not cached by Streamlit. Public mode
keeps its existing five-minute global cache. This conservative choice avoids
cross-session leakage and permission staleness but increases read-query cost and
latency. The serving view also parses charge tags at query time. Benchmark this
before enabling a production private dashboard; a separately materialized scoped
serving product and carefully invalidated cache are future optimizations, not
unmeasured savings claimed here. Existing downloads cannot be retroactively erased
by revoking access.

## Future private IAP deployment — do not execute yet

Use a separate service, for example `finops-center-private`, not the public site.
Its expected signed-assertion audience would follow:

```text
/projects/243421621568/locations/europe-west1/services/finops-center-private
```

Configure IAP permissions/OAuth, `FINOPS_AUTH_MODE=iap`, and the verified expected
audience. Enroll actual signed subjects with `identity_provider='iap'`, not the
invented demonstration emails. Validate direct URLs, invalid signature/audience,
unauthorized users and each business scope before giving the private link to users.
No private service, IAP IAM policy or real-user entitlement is created by this change.

Sources:

- https://docs.databricks.com/gcp/en/views
- https://docs.databricks.com/gcp/en/dev-tools/python-sql-connector
- https://docs.databricks.com/gcp/en/dev-tools/auth/config-profiles
- https://docs.streamlit.io/develop/api-reference/caching-and-state/st.context
- https://docs.cloud.google.com/iap/docs/signed-headers-howto
