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

## Deployment

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
