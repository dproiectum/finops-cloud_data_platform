# Décisions techniques

## Autorité des sources

- Daily : données provisoires d'un mois ouvert.
- Monthly billing : version détaillée et définitive du mois.
- Les deux sources ne sont jamais additionnées dans la fact.
- Le billing remplace atomiquement le même mois dans Silver et Gold.

## Conservation

- Les fichiers GCS actifs sont archivés seulement après les contrôles `AFTER`
  et le rafraîchissement des produits analytiques.
- Les données Raw/Bronze et l'historique Delta restent disponibles.
- L'archivage GCS est idempotent et vérifie génération, taille et CRC32C.
- Une rectification qui réutilise le même nom de billing est conservée sous un
  sous-dossier `revision=<generation>` au lieu d'écraser l'archive précédente.

## Portabilité

Le Data Contract, les configurations et les modèles SQL sont indépendants des
notebooks. Les opérations physiques Delta, Unity Catalog et GCS restent
explicitement adaptées à Databricks/GCP au lieu d'être masquées par une
abstraction universelle.

## Modèle analytique

Gold reprend le schéma en étoile complet du POC : dix dimensions, une table de
pont ressource/tag et `fact_finops_cost_usage`. Les quatorze datamarts du POC
sont également conservés. Le modèle, le grain, les relations et les écarts dus
au schéma source sont détaillés dans `data_model.md`.

Les DDL et DML sont la source de vérité du modèle. Python/PySpark charge ces
fichiers SQL depuis le package, injecte uniquement les noms qualifiés issus des
configurations TOML, puis pilote leur exécution.
