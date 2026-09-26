# Phase 8 — Promotion et exploitation PROD

Cette procédure commence uniquement après la réussite du Job DEV de la phase 7.
Toutes les opérations restent manuelles. Elle ne supprime ni DEV, ni RAW, ni OPS.

## 1. Figer la version validée

1. vérifier que le Git Folder Databricks est sur la branche `main`;
2. faire **Pull**;
3. noter le commit utilisé par le Job DEV;
4. ne modifier ni le Job DEV validé, ni ses paramètres.

Le chargement PROD utilise les mêmes notebooks et le même Data Contract que DEV.
Seuls le paramètre `environment` et le contrôle final changent.

## 2. Vérifier les accès PROD

L'identité qui exécutera le Job doit pouvoir :

- lire le Volume partagé `/Volumes/finops_raw/landing/focus`;
- lire et modifier les tables dans les quatre schémas de `finops_prod`;
- créer ou remplacer les tables Gold et datamarts dans ces schémas;
- lire et modifier les cinq tables de `finops_ops.audit`.

Dans Catalog Explorer, contrôler les permissions sur `finops_raw`, `finops_prod`
et `finops_ops`. Avec une identité de Job dédiée, l'administrateur doit accorder
au minimum les privilèges Unity Catalog adaptés : `USE CATALOG`, `USE SCHEMA`,
`READ VOLUME`, `SELECT`, `MODIFY` et `CREATE TABLE`.

L'archivage reste désactivé dans `config/common.toml`. PROD lit donc les mêmes
Parquet RAW que DEV sans les déplacer.

## 3. Contrôler l'environnement PROD

Ouvrir `platform/common/notebooks/operations/environment_check.ipynb`, sélectionner le compute
du scénario retenu, puis exécuter avec :

```text
environment = prod
```

Le notebook doit afficher `finops_prod`, les quatre schémas, le Volume RAW, les
tables OPS et la liste des fichiers mensuels.

Exécuter ensuite le contrôle commun
`platform/common/sql/controls/03_validate_prod_ready.sql`.

Résultats attendus :

- 2 tables Bronze, 2 Silver, 12 Gold et 14 datamarts;
- 30 tables PROD avec `row_count = 0`;
- aucune ligne OPS avec `environment = 'prod'`;
- les trois assertions finales retournent `NULL`.

Ce contrôle est un prérequis à usage unique : il doit échouer normalement après
le premier chargement PROD.

## 4. Créer le Job de promotion PROD

Dans **Jobs & Pipelines**, créer un nouveau Job nommé :

```text
finops-prod-billing-promotion
```

Ne pas modifier ni cloner par-dessus le Job DEV. Ajouter les paramètres :

| Name | Default |
|---|---|
| `environment` | `prod` |
| `start_month` | `2025-01` |
| `end_month` | `2026-06` |

Configurer `Maximum concurrent runs = 1` et ne pas ajouter de schedule.

Créer le DAG suivant :

```text
check_environment_prod → load_billing_range_prod → validate_loaded_prod
```

### Tâche `check_environment_prod`

- Type : `Notebook`
- Source : `Workspace`
- Notebook : `platform/common/notebooks/operations/environment_check.ipynb`
- Compute : celui du scénario retenu
- Depends on : aucun

### Tâche `load_billing_range_prod`

- Type : `Notebook`
- Source : `Workspace`
- Notebook : `platform/common/notebooks/pipelines/03_billing_backfill.ipynb`
- Compute : celui du scénario retenu
- Depends on : `check_environment_prod`
- Run if dependencies : `All succeeded`

Les widgets reçoivent automatiquement `environment`, `start_month` et
`end_month` lorsque l'interface les affiche comme **pushed down**. Ne pas ajouter
manuellement une valeur `{{job.parameters...}}`.

### Tâche `validate_loaded_prod`

En Serverless :

- Type : `SQL`
- SQL task : `File`
- Source : `Workspace`
- File : `platform/common/sql/controls/04_validate_loaded_prod.sql`
- SQL Warehouse : le Warehouse Serverless ou Pro de validation
- Depends on : `load_billing_range_prod`
- Run if dependencies : `All succeeded`

En Classic Belgique, utiliser le notebook de validation, car un Job qui contient
un SQL task sur SQL Warehouse Classic est limité à une seule tâche :

- Type : `Notebook`
- Source : `Workspace`
- Notebook : `platform/classic_compute/notebooks/validate_loaded_environment_classic.ipynb`
- Compute : le même All-Purpose Classic que les tâches précédentes
- Depends on : `load_billing_range_prod`
- Run if dependencies : `All succeeded`

Le paramètre Job `environment=prod`, automatiquement transmis au widget, fait
exécuter `platform/common/sql/controls/04_validate_loaded_prod.sql`.

## 5. Effectuer un canari sur un mois

Utiliser **Run now with different parameters** :

```text
environment = prod
start_month = 2026-06
end_month = 2026-06
```

Les trois tâches doivent réussir. Le chargement doit produire 199 200 lignes
pour juin 2026 dans Bronze, Silver et Gold. Le statut OPS doit être
`CLOSED_DATA_LOADED`; la réconciliation doit être `PASSED`; toutes les
assertions SQL doivent retourner `NULL`.

En cas d'échec, ne pas supprimer les catalogues. Corriger la cause et utiliser
**Repair run**. Les écritures par fichier/mois sont idempotentes.

## 6. Charger l'historique complet

Après la réussite du canari, relancer le même Job avec :

```text
environment = prod
start_month = 2025-01
end_month = 2026-06
```

Juin 2026 peut être inclus : Bronze ignore le fichier déjà présent et les
couches suivantes remplacent proprement le mois. Résultats complets attendus :

- 18 mois;
- 3 279 613 lignes dans Bronze, dans les deux tables Silver et dans le fait Gold;
- 18 lignes dans `dm_monthly_billing`;
- différences de lignes et de coûts à zéro;
- dernière réconciliation de chaque mois à `PASSED`;
- dernier run de chaque mois à `SUCCESS`;
- aucun doublon et aucun `ServiceName` nul dans Silver.

## 7. Valider l'indépendance DEV/PROD

Le contrôle commun `04_validate_loaded_prod.sql` affiche les nombres de runs
par environnement dans OPS. Vérifier que DEV et PROD sont présents séparément.

Rejouer `platform/common/sql/controls/02_validate_loaded_dev.sql` n'est plus approprié
après le chargement PROD, car sa dernière assertion exige volontairement que
PROD soit vide. Les contrôles métier DEV restent consultables dans ses premiers
résultats, mais le contrôle bloquant officiel de PROD est désormais le fichier
`platform/common/sql/controls/04_validate_loaded_prod.sql`.

## 8. Passage en exploitation

Conserver le Job de promotion sans schedule pour les backfills. Pour un nouveau
mois, utiliser `platform/common/notebooks/pipelines/02_monthly_close.ipynb` avec
`environment=prod` et `month=YYYY-MM`, suivi du contrôle
`validate_loaded_prod.sql` du scénario choisi.

Ne planifier ce futur Job mensuel qu'après avoir défini comment le mois à fermer
est fourni et comment l'arrivée du Parquet est contrôlée. Garder
`Maximum concurrent runs = 1` et l'archivage désactivé tant que DEV et PROD
partagent RAW.

Pour chaque promotion, conserver les captures du DAG, des paramètres, des trois
tâches vertes, des assertions et des lignes `finops_ops.audit`.
