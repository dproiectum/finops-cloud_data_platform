# Pipeline quotidien DEV vers PROD

Cette procédure traite les Parquet daily d'un mois encore ouvert. Elle ne
supprime aucune donnée et ne remplace pas le processus de clôture mensuelle.

## 1. Tester chaque étape manuellement

Après Pull du Git Folder, utiliser le compute du scénario retenu — Serverless
ou All-Purpose Classic — et exécuter dans cet ordre avec le même `source_uri` :

1. `platform/common/notebooks/operations/environment_check.ipynb`, `environment=dev`;
2. `platform/common/notebooks/operations/discover_daily_files.ipynb`, `environment=dev`;
3. `platform/common/notebooks/pipelines/01_daily_incremental.ipynb`, `environment=dev`;
4. `platform/common/notebooks/operations/validate_daily_load.ipynb`, `environment=dev`;
5. `platform/common/notebooks/operations/environment_check.ipynb`, `environment=prod`;
6. `platform/common/notebooks/pipelines/01_daily_incremental.ipynb`, `environment=prod`;
7. `platform/common/notebooks/operations/validate_daily_load.ipynb`, `environment=prod`.

Exemple de fichier d'un mois ouvert :

```text
/Volumes/finops_raw/landing/focus/daily/2026/07/2026-07-01.parquet
```

La validation PROD compare également le mois Gold avec DEV. Relancer ensuite
le même fichier dans les deux environnements : les écritures Bronze et Silver
doivent retourner zéro et les contrôles doivent toujours passer.

## 2. Créer le Job

Créer `finops-daily-dev-to-prod`, choisir `Maximum concurrent runs = 1` et
ajouter les paramètres :

| Name | Default |
|---|---|
| `discovery_environment` | `prod` en exploitation |
| `processing_date` | vide |
| `source_uri_override` | vide |
| `promote_to_prod` | `true` en exploitation |

Ne pas créer de paramètre de Job `environment`. Chaque tâche reçoit
explicitement `dev` ou `prod`.

Pour le scénario Classic Belgique, le modèle YAML prêt à importer est :

```text
platform/classic_compute/jobs/daily_dev_to_prod.yml
```

Il utilise le cluster All-Purpose belge pour toutes les tâches Notebook, garde
`promote_to_prod=false` par défaut et ne crée aucun schedule avant les tests.

Construire le DAG :

```text
discover_daily_files
        ↓
new_file_gate ── false → fin du run sans erreur
        ↓ true
check_environment_dev
        ↓
load_daily_dev
        ↓
validate_daily_dev
        ↓
promotion_gate ── false → fin DEV uniquement
        ↓ true
check_environment_prod
        ↓
load_daily_prod
        ↓
validate_daily_prod
```

## 3. Paramétrer les tâches

### `discover_daily_files`

- Type : Notebook
- Notebook : `platform/common/notebooks/operations/discover_daily_files.ipynb`
- Compute : celui du scénario retenu
- paramètres :

```text
environment = {{job.parameters.discovery_environment}}
processing_date = {{job.parameters.processing_date}}
source_uri_override = {{job.parameters.source_uri_override}}
```

En exploitation, la découverte utilise `environment=prod`. Elle choisit donc
le plus ancien fichier absent de PROD, y compris si ce fichier a déjà réussi en
DEV lors d'une exécution précédente. Les tâches DEV restent placées avant les
tâches PROD et sont idempotentes.

### `new_file_gate`

- Type : If/else condition
- gauche : `{{tasks.discover_daily_files.values.has_new_file}}`
- opérateur : `==`
- droite : `true`

### `check_environment_dev`

- Notebook : `platform/common/notebooks/operations/environment_check.ipynb`
- dépendance : `new_file_gate (true)`
- paramètre `environment=dev`.

### `load_daily_dev`

- Notebook : `platform/common/notebooks/pipelines/01_daily_incremental.ipynb`
- dépendance : `check_environment_dev`
- paramètres :

```text
environment = dev
source_uri = {{tasks.discover_daily_files.values.source_uri}}
```

### `validate_daily_dev`

- Notebook : `platform/common/notebooks/operations/validate_daily_load.ipynb`
- dépendance : `load_daily_dev`
- mêmes paramètres que `load_daily_dev`.

### `promotion_gate`

- Type : If/else condition
- dépendance : `validate_daily_dev`
- gauche : `{{job.parameters.promote_to_prod}}`
- opérateur : `==`
- droite : `true`.

### Tâches PROD

Reproduire les trois tâches DEV avec les noms `check_environment_prod`,
`load_daily_prod`, `validate_daily_prod`, la dépendance initiale
`promotion_gate (true)` et `environment=prod`. Le `source_uri` reste exactement
la task value de `discover_daily_files`.

## 4. Activer l'exploitation quotidienne

1. pour le test DEV seul, utiliser `discovery_environment=dev` et
   `promote_to_prod=false`;
2. après sa réussite, utiliser `discovery_environment=prod` et
   `promote_to_prod=true`; le Job retrouve automatiquement le fichier encore
   absent de PROD, sans `source_uri_override`;
3. conserver ensuite ces deux valeurs comme valeurs par défaut;
4. ajouter un schedule quotidien après l'heure d'arrivée des fichiers;
5. conserver les notifications d'échec et les retries techniques;
6. ne jamais utiliser ce Job pour un mois fermé.

Quand le billing mensuel arrive, utiliser `02_monthly_close.ipynb` séparément
pour DEV puis PROD. La clôture rend ensuite le mois immutable aux daily.
