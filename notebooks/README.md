# Notebooks Databricks

Ces notebooks sont les interfaces interactives des pipelines. Ils définissent
les paramètres, appellent les fonctions maintenues dans `src/finops_cloud` et
affichent les résultats. Ils ne dupliquent ni la logique Python ni les scripts
SQL.

- `00_environment_check.ipynb` : vérification du catalogue et des volumes
- `01_daily_incremental.ipynb` : ingestion quotidienne
- `02_monthly_close.ipynb` : clôture et remplacement mensuels
- `03_billing_backfill.ipynb` : chargement initial d'une plage de mois
- `04_archive_retry.ipynb` : reprise d'un archivage GCS

Les paramètres sont exposés avec des widgets Databricks. Dans un Job, le Bundle
les renseigne automatiquement. Pour une démonstration, ils peuvent être
modifiés puis exécutés cellule par cellule. Les sorties ne doivent pas être
enregistrées dans Git.
