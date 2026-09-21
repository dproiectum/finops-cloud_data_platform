# Technical decisions

## Source authority

- `finops_raw.landing` is the single immutable source namespace for DEV and
  PROD.
- Daily files are provisional while a month is open.
- Monthly billing is detailed and authoritative for a closed month.
- Daily and monthly sources are never added together in the fact table.
- Billing atomically replaces the same month in Silver and Gold.

## Catalog isolation

Business tables stay isolated in `finops_dev` and `finops_prod`. The
environment-independent `finops_ops.audit` catalog stores monitoring evidence.
Its five tables have an explicit `environment` column, and all lookups and
writes are scoped to it.

```text
finops_raw.landing
        ├── DEV → finops_dev.{bronze,silver,gold,datamart}
        └── PROD → finops_prod.{bronze,silver,gold,datamart}

DEV + PROD audits → finops_ops.audit
```

## Retention

RAW files stay in `gs://dtl_finops/focus`. Automatic archival is disabled in
`config/common.toml`; otherwise a DEV close could remove the source before PROD
processes it. The archival module remains available for a later retention policy
that coordinates all consuming environments.

## Analytical model

Gold contains ten dimensions, one resource/tag bridge, and
`fact_finops_cost_usage`. Fourteen datamarts reproduce the analytical outputs.
SQL owns physical structures and transformations; Python controls execution and
passes validated identifiers.
