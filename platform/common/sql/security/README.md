# Dashboard authorization metadata — manual setup

These additive scripts support both compute scenarios. They inherit the managed
storage of the existing `finops_ops` catalog. They do not reset catalogs, reload
business data, create a new bucket, change Cloud Run authentication, or enable
viewer authorization. The dashboard still uses global queries until step 7 is
implemented and tested.

## Execute manually in workspace-belgium

1. Open SQL Editor in `https://8259550830613689.9.gcp.databricks.com` and select
   Warehouse `137166118b7adca0`.
2. Run `01_create_security_tables.sql` only if setup has not already been done.
   It matches the DDL previously supplied in the manual instructions. Existing
   tables are not migrated by `IF NOT EXISTS`; inspect their DDL if it differs.
3. Copy `02_load_demo_assignments.sql` into a saved SQL query and execute the
   statements in order. Stop on any assertion error. Do not run concurrently.
4. Run `03_validate_demo_assignments.sql` in the same way.
5. Run step 3 again, then step 4 again to verify repeatability: still two selected
   scopes and three demo permission rows, not four scopes or six permissions.

Successful `assert_true` queries return `NULL`; the final explicit result is
`PASS: demo metadata only; dashboard enforcement is not implemented`.
An inactive or expired permission is deliberately preserved. Validation then
fails, rather than silently restoring access. Inspect and explicitly approve any
required change instead of deleting/resetting these tables.

The project repository on Databricks need not be updated yet: SQL Editor can run
the copied local scripts. No Git push or Cloud Run deployment is required for
this metadata step.

## Selected scopes and test identities

The user-supplied PROD inventory contains these application codes. Repeated
application rows with multiple owner emails are expected at resource grain;
they do not create multiple business scope rows and do not automatically grant
those emails access.

| Demo principal | Role | Environment | Scope |
|---|---|---|---|
| `demo-finops-admin` | `FINOPS_ADMIN` | `prod` | `ALL`, `*` |
| `demo-app-owner-a` | `APPLICATION_OWNER` | `prod` | `APPLICATION`, `APP00013057` — TEN Data Platform |
| `demo-app-owner-b` | `APPLICATION_OWNER` | `prod` | `APPLICATION`, `BSN0003965` — ServiceNow |
| `demo-no-access` | No entitlement | — | Must be denied by the future application |

All three permission rows have `identity_provider = 'demo'`; their emails use
`example.invalid`. These are synthetic test personas, not actual IAP identities
or Databricks administrators. A future authenticated mode must reject demo
identities and validate the real signed identity before resolving entitlements.
Do not identify an authenticated user from a typed email or a persona dropdown.

The environment is `prod` because the inventory and synthetic dataset used for
these tests are PROD. This does not grant any DEV entitlement. Domain and
subdomain IDs remain `NULL` until the application hierarchy is confirmed.
The name is display metadata taken from Gold, never an authorization key. If a
single application has conflicting names, `MAX` selects a deterministic display
label only; that choice does not resolve the data-quality issue.

Entitlement keys are `(identity_provider, principal_id, environment, role,
scope_type, scope_id)`. Scope keys are `(environment, application_code)`.
Uniqueness is checked for the selected records, not enforced by an SQL primary
key. This initial metadata setup has no historical versioning or authorization
change audit; do not claim these features in the thesis.

## Step 7 code available locally; live validation pending

Step 7 code is now under `apps/finops_dashboard/security/`. Execute files 04/05
manually to create/validate the charge-grain serving view, then follow that
directory's README for an isolated local test. First create the shared Gold
allocation view with `operations/apply_cost_center_allocation.ipynb` as explained
in the Gold README. Script 04 reads this view so public and protected Cost Center
allocation use the same synthetic policy. Allocation never changes entitlements.
Signed-identity verification,
live parameterized entitlement predicates, uncached protected results and
deny-by-default handling are implemented locally, not deployed to the public site.
The view preserves existing FOCUS cost semantics, including ContractedCost for Savings.
Script 04 no longer references or invents `ChargeSubcategory`; the actual source
region column is `Region`. Before using the updated Gold loaders with old tables,
follow `platform/common/sql/gold/README.md` for the key-preserving maintenance.
Neither `current_user()` (the shared backend service principal) nor filtering a
global aggregate after retrieval identifies the viewer's authorized charges.

Step 8 must exercise two distinct applications, a global FinOps persona, an
unmapped persona, expiration and revocation, multiple assignments without charge
duplication, all page paths, exports, available periods, and cache/session
isolation. Compare exact authorized subsets and SQL totals: credits mean a
filtered cost is not necessarily smaller than the global total. Global OPS
operational pages must not be exposed to restricted application owners.

These metadata checks are not substitutes for the step 8 authorization tests.
Keep the public portfolio unchanged while testing those controls
separately. Any later IAP deployment requires a separate private-service plan.

## Technical references

- https://docs.databricks.com/gcp/en/sql/language-manual/delta-merge-into
- https://docs.databricks.com/gcp/en/sql/language-manual/functions/assert_true
- https://docs.cloud.google.com/iap/docs/signed-headers-howto
