# Reconstruction manuelle complète de la plateforme FinOps

Cette procédure suit le plan validé en huit phases. Aucun script n’est exécuté
automatiquement par le dépôt. Toutes les commandes destructives restent sous le
contrôle de l’ingénieur dans Databricks SQL.

Choisir un seul scénario pour tout le workspace :

- `sql/platform_setup_serverless` pour Serverless avec Default Storage;
- `sql/platform_setup_classic_be` pour le compute Classic belge avec le bucket
  géré `gs://dtl_finops-unitycatalog-euw1`.

Les deux dossiers contiennent le workflow complet. Ne pas mélanger leurs scripts
de création. Dans les étapes ci-dessous, utiliser la colonne correspondant au
scénario choisi.

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
   Location `finops_gcs` sont disponibles;
5. pour Classic Belgique, exécuter d’abord
   `sql/platform_setup_classic_be/00_validate_managed_storage.sql` et valider
   le credential `finops_uc_storage_be`, l’External Location
   `finops_uc_managed_be` et le bucket géré régional.

Un Volume externe est un enregistrement Unity Catalog au-dessus d’un chemin
GCS. Supprimer `finops_raw` retire cet enregistrement mais ne supprime pas les
Parquet externes. Les tables gérées dans DEV, PROD et OPS sont en revanche
supprimées avec leurs catalogues.

## Phase 3 — Suppression des quatre catalogues

Ouvrir le script de suppression du scénario choisi :

- Serverless :
  `sql/platform_setup_serverless/00_drop_all_project_catalogs.sql`;
- Classic Belgique :
  `sql/platform_setup_classic_be/01_drop_all_project_catalogs.sql`.

Lire puis exécuter les quatre instructions `DROP CATALOG ... CASCADE` une par
une. Dans le workspace Classic, utiliser un notebook SQL attaché au compute All
Purpose Classic si le SQL Editor ne permet pas d’attacher le compute voulu.

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

Exécuter les scripts de création du même scénario, instruction par instruction
et dans cet ordre :

| Objet | Serverless | Classic Belgique |
|---|---|---|
| RAW | `platform_setup_serverless/01_create_raw.sql` | `platform_setup_classic_be/02_create_raw.sql` |
| DEV | `platform_setup_serverless/02_create_dev.sql` | `platform_setup_classic_be/03_create_dev.sql` |
| PROD | `platform_setup_serverless/03_create_prod.sql` | `platform_setup_classic_be/04_create_prod.sql` |
| OPS | `platform_setup_serverless/04_create_ops.sql` | `platform_setup_classic_be/05_create_ops.sql` |

Dans le workspace classique belge, le métastore n'a pas d'emplacement géré par
défaut. Chaque catalogue utilise donc un sous-chemin dédié du bucket régional
`gs://dtl_finops-unitycatalog-euw1/catalogs/<nom_du_catalogue>`. Unity Catalog y
crée ses propres chemins `__unitystorage` pour les tables gérées. Le bucket
source `gs://dtl_finops` reste réservé aux Parquet externes `focus` et
`focus_archive`. Si un catalogue existe déjà, `CREATE CATALOG IF NOT EXISTS` ne
modifie pas son emplacement actuel.

À ce stade, RAW contient les deux Volumes externes, DEV et PROD contiennent
leurs quatre schémas, et OPS contient cinq tables vides.

### 4.2 Vérifier l’infrastructure

Ouvrir `notebooks/operations/environment_check.ipynb`, définir
`ENVIRONMENT = "dev"`, attacher le compute correspondant au scénario et
exécuter toutes les cellules. Refaire le contrôle avec `ENVIRONMENT = "prod"`.
Ce notebook ne crée et ne charge aucun objet.

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

Exécuter le contrôle du scénario choisi :

- Serverless : `sql/platform_setup_serverless/05_validate_empty_platform.sql`;
- Classic Belgique :
  `sql/platform_setup_classic_be/06_validate_empty_platform.sql`.

Résultats attendus :

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

Exécuter le contrôle chargé DEV du scénario choisi :

- Serverless : `sql/platform_setup_serverless/06_validate_loaded_dev.sql`;
- Classic Belgique : `sql/platform_setup_classic_be/07_validate_loaded_dev.sql`.

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

Après validation du DAG DEV et des captures, suivre la procédure détaillée
`docs/databricks_prod_promotion.md` :

- préparer les autorisations PROD;
- exécuter `platform_setup_serverless/07_validate_prod_ready.sql` ou
  `platform_setup_classic_be/08_validate_prod_ready.sql` avant le premier
  chargement PROD;
- conserver le Job DEV strictement en `environment=dev`, car son contrôle
  `06_validate_loaded_dev.sql` est volontairement spécifique à DEV;
- créer un Job PROD séparé et utiliser
  `platform_setup_serverless/08_validate_loaded_prod.sql` ou
  `platform_setup_classic_be/09_validate_loaded_prod.sql`;
- effectuer un canari PROD sur un mois avant le backfill complet;
- conserver RAW commun et l'archivage désactivé;
- surveiller les runs DEV/PROD dans `finops_ops.audit`;
- synchroniser GitHub et le Git Folder avant chaque déploiement.

La reconstruction principale s'arrête à la validation DEV. Le passage PROD est
une promotion séparée et explicitement contrôlée par la procédure de phase 8.
