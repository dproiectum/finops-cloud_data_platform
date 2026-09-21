# Reconstruction manuelle complète de la plateforme FinOps

Cette procédure suit le plan validé en huit phases. Aucun script n’est exécuté
automatiquement par le dépôt. Toutes les commandes destructives restent sous le
contrôle de l’ingénieur dans Databricks SQL.

## Phase 1 — Architecture cible

La plateforme contient quatre catalogues et dix schémas métier :

- `finops_raw.landing`;
- `finops_dev.{bronze,silver,gold,datamart}`;
- `finops_prod.{bronze,silver,gold,datamart}`;
- `finops_ops.audit`.

RAW est commun à DEV et PROD. Les tables OPS séparent les environnements avec la
colonne `environment`. PROD est recréé vide mais n’est pas chargé pendant cette
procédure.

## Phase 2 — Vérifications de sécurité

Avant toute suppression :

1. faire **Pull** dans le Git Folder Databricks;
2. vérifier qu’aucun Job ou notebook Daily, Monthly ou Backfill n’est actif;
3. confirmer dans GCS que `gs://dtl_finops/focus/monthly` contient les fichiers
   `billing-YYYY-MM.parquet`;
4. vérifier que le Storage Credential `finops_gcs_storage_dev` et l’External
   Location `finops_gcs` sont disponibles.

Un Volume externe est un enregistrement Unity Catalog au-dessus d’un chemin
GCS. Supprimer `finops_raw` retire cet enregistrement mais ne supprime pas les
Parquet externes. Les tables gérées dans DEV, PROD et OPS sont en revanche
supprimées avec leurs catalogues.

## Phase 3 — Suppression des quatre catalogues

Ouvrir `sql/platform_setup/00_drop_all_project_catalogs.sql` dans un SQL
Warehouse. Lire puis exécuter les quatre instructions `DROP CATALOG ... CASCADE`
une par une.

Le script supprime uniquement :

- `finops_dev`;
- `finops_prod`;
- `finops_ops`;
- `finops_raw`.

Ne jamais ajouter `main`, `system`, `samples` ou un catalogue extérieur au
projet. Après l’exécution, actualiser Catalog Explorer et vérifier que les quatre
catalogues FinOps ont disparu. Vérifier aussi que les Parquet sont toujours
présents dans GCS.

## Phase 4 — Reconstruction manuelle

### 4.1 Recréer les catalogues et les schémas

Exécuter dans un SQL Warehouse, instruction par instruction et dans cet ordre :

1. `sql/platform_setup/01_create_raw.sql`;
2. `sql/platform_setup/02_create_dev.sql`;
3. `sql/platform_setup/03_create_prod.sql`;
4. `sql/platform_setup/04_create_ops.sql`.

À ce stade, RAW contient les deux Volumes externes, DEV et PROD contiennent
leurs quatre schémas, et OPS contient cinq tables vides.

### 4.2 Vérifier l’infrastructure

Ouvrir `notebooks/operations/environment_check.ipynb`, définir
`ENVIRONMENT = "dev"`, attacher du compute Serverless et exécuter toutes les
cellules. Refaire le contrôle avec `ENVIRONMENT = "prod"`. Ce notebook ne crée
et ne charge aucun objet.

### 4.3 Créer les tables métier vides

Ouvrir `notebooks/operations/initialize_empty_data_tables.ipynb`, puis exécuter
une première fois avec :

```python
ENVIRONMENT = "dev"
SAMPLE_MONTH = "2025-01"
CONFIRMATION = "CREATE_EMPTY_TABLES"
```

Le Parquet `billing-2025-01.parquet` sert uniquement à dériver le schéma exact
de Bronze et Silver. Aucune ligne source ni ligne d’audit n’est écrite.

Exécuter une deuxième fois avec `ENVIRONMENT = "prod"`. Cette seconde exécution
crée uniquement les structures PROD; elle ne charge pas PROD. Pour chaque
environnement, le notebook crée 30 tables vides : 2 Bronze, 2 Silver, 12 Gold
et 14 datamarts. Il refuse de continuer si une table métier existante contient
déjà une ligne.

### 4.4 Prouver que la plateforme est vide

Exécuter `sql/platform_setup/05_validate_empty_platform.sql`. Résultats attendus :

- 2, 2, 12 et 14 tables par couche dans chacun des catalogues DEV et PROD;
- 60 tables métier listées avec `row_count = 0`;
- les cinq tables OPS avec `row_count = 0`;
- les Volumes RAW et les Parquet mensuels toujours visibles.

## Phase 5 — Chargement manuel DEV

Ouvrir `notebooks/pipelines/03_billing_backfill.ipynb` et définir la période :

```python
ENVIRONMENT = "dev"
START_MONTH = "2025-01"
END_MONTH = "2025-12"
```

Choisir `START_MONTH` et `END_MONTH` à partir de la liste obtenue dans RAW. La
période est inclusive; le notebook doit retourner un résultat
`CLOSED_DATA_LOADED` par mois. Un fichier absent ou un contrôle invalide arrête
le backfill et empêche de considérer la phase comme terminée.

Exécuter toutes les cellules dans l’ordre et ne pas lancer une seconde copie du
notebook en parallèle. Pour chaque mois, le traitement exécute :

```text
RAW → Bronze → Data Contract → Silver → Gold → Datamarts
                                      ↘ OPS
```

Bronze ignore un `_source_file` déjà enregistré. Silver et le fait Gold
remplacent le mois concerné. Les datamarts vides sont reconstruits avec les
données chargées. Les tables OPS conservent une ligne par exécution afin de
préserver l’historique d’audit.

Après la réussite du chargement manuel et de la phase 6, suivre
`docs/databricks_jobs_manual_setup.md` pour créer soi-même le graphe dans
**Jobs & Pipelines** et capturer les écrans du DAG et du résultat.

## Phase 6 — Contrôles

Exécuter `sql/platform_setup/06_validate_loaded_dev.sql` dans un SQL Warehouse.

Contrôles structurels :

- les tables attendues existent dans Bronze, Silver, Gold et datamart;
- les 30 tables PROD existent mais restent vides;
- aucune exécution OPS n’est enregistrée avec `environment = 'prod'`.

Contrôles de réconciliation par mois :

- lignes Bronze = lignes Silver = lignes Gold;
- coût Bronze = coût Silver = coût Gold;
- `monthly_reconciliation.status = 'PASSED'`;
- `after_billing_difference = 0`;
- la dernière exécution DEV de chaque pipeline/mois est en statut `SUCCESS`.

Contrôles de doublons et de qualité :

- aucun `_source_file` associé à plusieurs runs Bronze;
- `duplicate_keys = 0` dans le fait Gold;
- les valeurs `ServiceName` nulles de Bronze ne subsistent pas dans Silver;
- `duplicate_charge_ids = 0` et `null_critical_count = 0` dans les snapshots
  `AFTER`.

Les dernières instructions utilisent `assert_true`. Le contrôle SQL échoue et
la tâche du Job devient rouge si une règle bloquante est violée. Capturer les
résultats des requêtes et les assertions réussies pour la démonstration et la
traçabilité.

## Phase 7 — Orchestration Databricks

Créer manuellement le Job multi-tâches après validation du chargement DEV. Le
graphe recommandé est :

```text
check_environment → load_billing_range → validate_loaded_data
```

La procédure détaillée est dans `docs/databricks_jobs_manual_setup.md`. Garder
`max_concurrent_runs = 1` et commencer sans déclencheur planifié.

## Phase 8 — Promotion et exploitation

Après validation du DAG DEV et des captures :

- préparer les autorisations PROD;
- conserver le Job actuel strictement en `environment=dev`, car son contrôle
  `06_validate_loaded_dev.sql` est volontairement spécifique à DEV;
- créer plus tard un Job et un contrôle PROD séparés avant le premier chargement
  PROD, uniquement après accord;
- conserver RAW commun et l’archivage désactivé;
- surveiller les runs DEV/PROD dans `finops_ops.audit`;
- synchroniser GitHub et le Git Folder avant chaque déploiement.

La présente procédure s’arrête au chargement et à la validation DEV. Elle crée
les structures PROD mais n’y charge aucune donnée.
