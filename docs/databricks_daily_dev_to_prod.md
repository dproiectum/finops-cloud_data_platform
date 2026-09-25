# Pipeline quotidien DEV vers PROD

Cette procédure traite les Parquet daily d'un mois encore ouvert. Elle ne
supprime aucune donnée et ne remplace pas le processus de clôture mensuelle.

## 1. Tester chaque étape manuellement

Après Pull du Git Folder, utiliser Serverless et exécuter dans cet ordre avec
le même `source_uri` :

1. `notebooks/operations/environment_check.ipynb`, `environment=dev`;
2. `notebooks/operations/discover_daily_files.ipynb`, `environment=dev`;
3. `notebooks/pipelines/01_daily_incremental.ipynb`, `environment=dev`;
4. `notebooks/operations/validate_daily_load.ipynb`, `environment=dev`;
5. `notebooks/operations/environment_check.ipynb`, `environment=prod`;
6. `notebooks/pipelines/01_daily_incremental.ipynb`, `environment=prod`;
7. `notebooks/operations/validate_daily_load.ipynb`, `environment=prod`.

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
| `processing_date` | vide |
| `source_uri_override` | vide |
| `promote_to_prod` | `false` pendant les tests |

Ne pas créer de paramètre de Job `environment`. Chaque tâche reçoit
explicitement `dev` ou `prod`.

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
- Notebook : `notebooks/operations/discover_daily_files.ipynb`
- Compute : Serverless
- aucun paramètre de tâche : les paramètres de Job homonymes sont pushed down.

### `new_file_gate`

- Type : If/else condition
- gauche : `{{tasks.discover_daily_files.values.has_new_file}}`
- opérateur : `==`
- droite : `true`

### `check_environment_dev`

- Notebook : `notebooks/operations/environment_check.ipynb`
- dépendance : `new_file_gate (true)`
- paramètre `environment=dev`.

### `load_daily_dev`

- Notebook : `notebooks/pipelines/01_daily_incremental.ipynb`
- dépendance : `check_environment_dev`
- paramètres :

```text
environment = dev
source_uri = {{tasks.discover_daily_files.values.source_uri}}
```

### `validate_daily_dev`

- Notebook : `notebooks/operations/validate_daily_load.ipynb`
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

1. tester un fichier avec `promote_to_prod=false`;
2. tester le même fichier avec `promote_to_prod=true`;
3. fixer ensuite la valeur par défaut à `true`;
4. ajouter un schedule quotidien après l'heure d'arrivée des fichiers;
5. conserver les notifications d'échec et les retries techniques;
6. ne jamais utiliser ce Job pour un mois fermé.

Quand le billing mensuel arrive, utiliser `02_monthly_close.ipynb` séparément
pour DEV puis PROD. La clôture rend ensuite le mois immutable aux daily.
