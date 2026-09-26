# Création manuelle du Job Databricks et captures du DAG

Commencer uniquement après la réussite de la phase 6 du guide
`manual_platform_rebuild.md`.

## 1. Créer le Job

Dans la barre latérale Databricks, ouvrir **Jobs & Pipelines**, cliquer sur
**Create**, puis **Job**. Nom recommandé :

```text
finops-dev-billing-orchestration
```

Dans les paramètres du Job, créer :

| Name | Default |
|---|---|
| `environment` | `dev` |
| `start_month` | `2025-01` |
| `end_month` | `2025-12` |

Les paramètres de Job sont automatiquement transmis aux tâches Notebook qui
utilisent les widgets portant les mêmes noms. Il n’est donc pas nécessaire de
saisir manuellement `{{job.parameters.environment}}` si l’interface affiche les
valeurs comme **pushed down**.

Configurer **Maximum concurrent runs** à `1`. Ne pas ajouter de schedule pour
le premier test. Ce Job est strictement un Job DEV : ne pas remplacer
`environment` par `prod`, car la tâche SQL finale contrôle volontairement que
PROD reste vide.

Avant de créer les tâches, conserver le même scénario que pendant la
reconstruction : compute Serverless avec `platform_setup_serverless`, ou compute
Classic belge avec `platform_setup_classic_be`.

## 2. Tâche `check_environment`

- Task name : `check_environment`
- Type : `Notebook`
- Source : `Workspace`
- Notebook : `notebooks/operations/environment_check.ipynb` dans le Git Folder
- Compute : celui du scénario retenu
- Depends on : aucun

Enregistrer la tâche.

## 3. Tâche `load_billing_range`

- Task name : `load_billing_range`
- Type : `Notebook`
- Source : `Workspace`
- Notebook : `notebooks/pipelines/03_billing_backfill.ipynb`
- Compute : celui du scénario retenu
- Depends on : `check_environment`
- Run if dependencies : `All succeeded`

Les widgets `environment`, `start_month` et `end_month` reçoivent les paramètres
du Job par transmission automatique.

## 4. Tâche `validate_loaded_data`

- Task name : `validate_loaded_data`
- Type : `SQL`
- SQL task : `File`
- Source : `Workspace`
- File Serverless : `sql/platform_setup_serverless/06_validate_loaded_dev.sql`
- File Classic Belgique : `sql/platform_setup_classic_be/07_validate_loaded_dev.sql`
- SQL Warehouse : sélectionner le Warehouse utilisé pendant la reconstruction
- Depends on : `load_billing_range`
- Run if dependencies : `All succeeded`

Un SQL task de type **File** accepte plusieurs instructions séparées par des
points-virgules. Les dernières instructions du fichier sont des assertions :
la tâche devient rouge si les couches ne se réconcilient pas, si des doublons
sont détectés ou si PROD n’est plus vide. Enregistrer la tâche.

## 5. Vérifier et capturer le graphe

Le DAG doit afficher exactement :

```text
check_environment → load_billing_range → validate_loaded_data
```

Avant l’exécution, capturer :

1. le graphe complet avec les trois tâches;
2. les paramètres du Job;
3. les dépendances de chaque tâche;
4. le compute du scénario et le SQL Warehouse sélectionné.

## 6. Tester le Job

Cliquer sur **Run now with different parameters**. Pour éviter de retraiter toute
la période lors du premier test du DAG, utiliser un seul mois déjà chargé, par
exemple :

```text
environment = dev
start_month = 2025-01
end_month = 2025-01
```

Le rechargement est idempotent pour les tables métier : Bronze n’ajoute pas une
seconde copie du fichier, Silver et Gold remplacent le mois, et les datamarts
sont reconstruits. OPS conserve cependant une nouvelle trace d’exécution, ce
qui est attendu.

Après le run, capturer :

1. le DAG avec les trois tâches en vert;
2. la page de détail du run;
3. les paramètres résolus;
4. le résultat SQL de `validate_loaded_data`;
5. les nouvelles lignes DEV dans `finops_ops.audit.pipeline_run`.

En cas d’échec, ouvrir la tâche rouge, conserver la capture du message, corriger
la cause, puis utiliser **Repair run** au lieu de relancer toutes les tâches.
