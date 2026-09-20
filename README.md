# FinOps Cloud Data Platform

Projet actif Databricks/GCP issu du POC local. Le code est développé dans VS
Code, exécuté sur Databricks DEV avec Databricks Connect, puis déployé en PROD
avec un Databricks Asset Bundle.

Le prototype historique reste dans `../FinOps Data Platform - POC`. Le dataset
synthétique unique est produit par `../FinOps Data Generator`.

## Architecture

```text
FinOps Data Generator
        ↓ publication sans régénération
gs://dtl_finops/focus
        ↓
Databricks Bronze → Data Contract → Silver canonique + table centrale
        ↓                            ↑
Gold dimensions/fact                 │ remplacement mensuel atomique
        ↓                            │
Datamarts                    Billing mensuel
        ↓
SQL Warehouse / Dashboard

Après clôture : gs://dtl_finops/focus → gs://dtl_finops/focus_archive
```

## Trois jobs, deux logiques métier

- `finops-daily` ajoute les nouveaux fichiers quotidiens aux mois ouverts.
- `finops-monthly` capture `BEFORE`, `SOURCE` et `AFTER`, remplace le mois
  atomiquement par le billing, recalcule Gold/datamarts et archive les sources.
- `finops-backfill` appelle le même traitement mensuel pour chaque mois de
  l'historique. Il ne duplique pas la logique de clôture.
- `finops-archive` reprend uniquement un archivage GCS en attente.

Raw et Bronze ne sont jamais supprimés. Le remplacement concerne Silver, la
table centrale et la partition logique mensuelle de la fact Gold.

## Modèle Gold et datamarts

Le modèle cloud reprend le schéma en étoile du POC : dix dimensions, la table
de pont `bridge_resource_tag`, la fact `fact_finops_cost_usage` et quatorze
datamarts. Les structures et transformations sont définies en SQL puis
exécutées par PySpark.

- Documentation : `docs/data_model.md`
- DDL et chargements Gold : `sql/gold`
- Datamarts : `sql/datamarts`
- Exécuteur commun : `src/finops_cloud/sql_runner.py`

## Zones à adapter

Les valeurs communes se trouvent dans `config/common.toml`. Les seules zones
propres aux environnements sont :

```text
config/dev.toml
config/prod.toml
databricks.yml
```

À modifier avant la première exécution :

1. Les profils Databricks `finops-gcp-dev` et `finops-prod`.
2. Les catalogues `finops_dev` et `finops_prod`.
3. Les deux External Volumes pointant vers `focus` et `focus_archive`.
4. Le bucket GCS si son nom diffère de `dtl_finops`.
5. Le projet GCP et les Service Credentials `finops-gcs-dev/prod` utilisés par
   le SDK pendant l'archivage.
6. La version de `databricks-connect` pour qu'elle corresponde au Runtime.

Aucun token, secret GCP ou fichier de compte de service ne doit être ajouté au
dépôt. L'authentification Databricks utilise les profils OAuth. Les External
Volumes utilisent une Storage Credential Unity Catalog ; le SDK d'archivage
utilise une Service Credential Unity Catalog dans un Job, ou les Application
Default Credentials pendant un test local.

La procédure administrative détaillée se trouve dans
`docs/databricks_gcs_setup.md`.

## Environnement VS Code

Le POC existant utilise Python 3.14. Le projet Databricks doit utiliser un
environnement séparé compatible avec le Runtime, par exemple Python 3.12 :

```bash
cd "/Users/dtl/Desktop/PFE/FinOps Cloud Data Platform"
python3.12 -m venv .venv-databricks
.venv-databricks/bin/python -m pip install -e '.[databricks,dev]'
```

La contrainte `databricks-connect>=17.3,<17.4` est une valeur de départ. Elle
doit être ajustée avant installation si le compute choisi utilise un autre
Databricks Runtime.

## Exécution depuis VS Code

Fichier quotidien précis :

```bash
.venv-databricks/bin/finops-daily \
  --environment dev \
  --source-uri /Volumes/finops_dev/raw/focus/daily/year=2026/month=07/day=01/focus-2026-07-01.parquet
```

Clôture mensuelle :

```bash
.venv-databricks/bin/finops-monthly --environment dev --month 2026-07
```

Backfill initial :

```bash
.venv-databricks/bin/finops-backfill \
  --environment dev \
  --start-month 2025-01 \
  --end-month 2026-06
```

## Déploiement

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run -t dev daily_incremental \
  --params source_uri=/Volumes/finops_dev/raw/focus/daily/year=2026/month=07/day=01/focus-2026-07-01.parquet
```

Après validation DEV, le même artefact est déployé en PROD :

```bash
databricks bundle validate -t prod
databricks bundle deploy -t prod
```

## Audit mensuel

Le schéma `ops` contient :

- `pipeline_run` : début, fin et statut de chaque exécution ;
- `month_snapshot` : métriques `BEFORE`, `SOURCE` et `AFTER` ;
- `monthly_reconciliation` : écarts Daily/Billing et contrôle technique ;
- `month_status` : `OPEN`, `RECONCILING`, `CLOSED_ARCHIVE_PENDING`, `CLOSED` ;
- `file_archive` : URI, générations, CRC32C et statut de chaque objet déplacé.

Si le chargement réussit mais que GCS échoue, le mois devient
`CLOSED_ARCHIVE_PENDING`. Une relance du job mensuel ou de `finops-archive`
reprend uniquement l'archivage, sans recharger Silver.

## Tests locaux

Les tests locaux ne démarrent pas Spark et ne contactent ni Databricks ni GCS :

```bash
PYTHONPATH=src python -m unittest discover -s tests/unit -v
```

Les tests d'intégration seront exécutés dans le catalogue DEV lorsque le
workspace, le Runtime et les External Volumes auront été renseignés.
