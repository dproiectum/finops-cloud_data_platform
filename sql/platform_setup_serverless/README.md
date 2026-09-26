# Serverless platform setup

Use this complete sequence for a Databricks Serverless workspace backed by
Default Storage. Catalog creation deliberately omits MANAGED LOCATION.

Run the numbered SQL files manually in order. The source Parquets remain in
gs://dtl_finops/focus and are registered through external Unity Catalog Volumes.

Sequence:

1. `00` resets the four project catalogs;
2. `01` through `04` recreate RAW, DEV, PROD, and OPS;
3. `05` validates the empty platform;
4. `06` validates the DEV load;
5. `07` checks PROD before its first load;
6. `08` validates the PROD load.

This folder is self-contained. Do not use creation scripts from
`platform_setup_classic_be` in the same workspace.
