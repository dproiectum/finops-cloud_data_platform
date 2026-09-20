# Scripts SQL

Ce dossier est la source de vérité de tous les scripts SQL du projet :

- `infrastructure/` : objets administratifs Unity Catalog et GCS, exécutés
  manuellement avant le premier déploiement
- `gold/table_creation/` : DDL idempotent des dimensions, de la table de faits
  et de la table de pont
- `gold/data_loading/` : chargement des dimensions, tags et faits
- `datamarts/table_refresh/` : transformation puis création ou remplacement
  des quatorze tables analytiques

Ces scripts sont lus dynamiquement par
`src/finops_cloud/sql_runner.py`, puis exécutés par `spark.sql()`. La
configuration de packaging les ajoute aussi à la wheel Databricks comme
fichiers de données. Il n'existe donc pas de seconde copie sous `src/`.

En développement, le runner trouve automatiquement ce dossier à la racine du
projet. Un chemin différent peut être fourni avec `FINOPS_SQL_ROOT` pour un
test contrôlé, sans modifier les scripts Python.

Le modèle et l'ordre d'exécution sont documentés dans `../docs/data_model.md`.
