# Technical decisions

## Source authority

- Daily files contain provisional data for an open month.
- Monthly billing is the detailed and authoritative version of a closed month.
- Daily and monthly sources are never added together in the fact table.
- Monthly billing atomically replaces the same month in Silver and Gold.

## Retention

- Active GCS files are archived only after the `AFTER` checks and analytical
  product refresh complete successfully.
- Raw/Bronze data and Delta history remain available.
- GCS archival is idempotent and verifies generation, size, and CRC32C.
- A corrected billing file that reuses an object name is preserved under
  `revision=<generation>` instead of overwriting the previous archive.

## Portability

The Data Contract, configuration, and SQL models are independent of notebooks.
Physical Delta, Unity Catalog, and GCS operations remain explicitly adapted to
Databricks/GCP instead of being hidden behind a universal abstraction.

## Analytical model

Gold preserves the complete POC star schema: ten dimensions, one resource/tag
bridge, and `fact_finops_cost_usage`. The fourteen POC datamarts are also
preserved. The model, grain, relationships, and source-schema limitations are
documented in `data_model.md`.

DDL and DML files are the model's source of truth. Python/PySpark loads the SQL
files from the package, injects only qualified identifiers from validated TOML
configuration, and controls their execution order.
