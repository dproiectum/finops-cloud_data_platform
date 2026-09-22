# FinOps Control Center

Read-only Streamlit application for the certified `finops_prod.datamart`
tables and the environment-aware `finops_ops.audit` history.

## Functional pages

- **Knowledge Base**: FOCUS column dictionary, cost formulas, interpretation
  limits, glossary and the Inform–Optimize–Operate lifecycle;
- **Executive Overview**: monthly KPIs, month-over-month change and daily/monthly
  trends;
- **Cost Drivers**: services, charge categories and portfolio SKU analysis;
- **Savings**: list, contracted and effective cost comparisons;
- **Allocation & Accountability**: cost centers, services, subscriptions and
  application owners;
- **Resources**: resources, regions and resource groups;
- **Operations & Quality**: critical completeness, pipeline runs, reconciliation
  and DEV/PROD audit separation;
- **Architecture**: end-to-end lineage, Medallion layers and certified products.

The application never writes to Unity Catalog.

## Databricks App resources

Create a custom Databricks App and add the SQL Warehouse with resource key:

```text
sql-warehouse
```

Select permission **Can use**. `app.yaml` maps that resource to
`DATABRICKS_WAREHOUSE_ID`; the application resolves its ODBC connection details
through the Databricks SDK. No warehouse ID, token or hostname is committed.

Grant the app service principal read-only access to the required namespaces:

```sql
GRANT USE CATALOG ON CATALOG finops_prod TO `<app-service-principal>`;
GRANT USE SCHEMA ON SCHEMA finops_prod.datamart TO `<app-service-principal>`;
GRANT SELECT ON SCHEMA finops_prod.datamart TO `<app-service-principal>`;

GRANT USE CATALOG ON CATALOG finops_ops TO `<app-service-principal>`;
GRANT USE SCHEMA ON SCHEMA finops_ops.audit TO `<app-service-principal>`;
GRANT SELECT ON SCHEMA finops_ops.audit TO `<app-service-principal>`;
```

Replace the placeholder with the service principal created for the app. If your
governance policy requires table-level grants, grant `SELECT` only on the
datamarts and the `pipeline_run` and `monthly_reconciliation` audit tables.

## Deployment

1. Pull the latest `main` branch into the Databricks Git Folder.
2. Open **Databricks Apps** and create a custom app named
   `finops-control-center`.
3. Configure the Git source to `apps/finops_dashboard`.
4. Add the SQL Warehouse resource using the key `sql-warehouse` and permission
   **Can use**.
5. Apply the read-only Unity Catalog grants above.
6. Deploy and inspect the application logs if the health check fails.

The default environment is PROD. A separate deployment can set
`FINOPS_ENVIRONMENT=dev` and `FINOPS_DATABRICKS_CATALOG=finops_dev` without code
changes.
