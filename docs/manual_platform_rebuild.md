# Reconstruction manuelle DEV dans Databricks

Cette procédure permet de comprendre et d’exécuter chaque étape. Les scripts ne
sont jamais lancés automatiquement depuis ce dépôt.

## 1. Mettre à jour le Git Folder Databricks

Dans **Workspace → Git folders**, ouvrir le projet, puis choisir **Pull**. Avant
le pull, conserver ou annuler toute modification locale Databricks afin d’éviter
un conflit.

## 2. Vérifier RAW sans rien modifier

Dans **SQL Editor**, sélectionner un SQL Warehouse et ouvrir
`sql/infrastructure/00_verify_existing_raw.sql`. Exécuter les instructions une
par une. Vérifier que les fichiers `billing-YYYY-MM.parquet` sont listés.

Cette vérification remplace un inventaire complet inutile : son seul but est de
protéger la source avant de déplacer les enregistrements Unity Catalog.

## 3. Enregistrer le RAW commun

Ouvrir `sql/infrastructure/01_create_raw.sql`. Lire puis exécuter chaque bloc.
Le script retire les anciens enregistrements Volume de `finops_dev.raw`, crée
`finops_raw.landing`, puis réenregistre les mêmes chemins GCS.

`DROP VOLUME` ne supprime pas les objets GCS. Ne poursuivez cependant que si
l’étape 2 a confirmé les chemins attendus. Après exécution, vérifier de nouveau
la liste sous `/Volumes/finops_raw/landing/focus/monthly`.

## 4. Créer OPS

Exécuter `sql/infrastructure/03_create_ops.sql`. Il crée
`finops_ops.audit` et ses cinq tables. La colonne `environment` permet aux
exécutions DEV et PROD de rester indépendantes.

## 5. Réinitialiser DEV si nécessaire

Pour un redémarrage complet, exécuter manuellement
`sql/maintenance/00_reset_dev.sql`. Ce script :

- supprime entièrement le catalogue `finops_dev` avec tous ses schémas et
  toutes ses tables;
- supprime seulement les lignes OPS avec `environment = 'dev'`;
- ne touche pas à `finops_raw`, aux fichiers GCS, à PROD, ni aux lignes OPS de
  PROD.

`finops_raw` n’est pas une copie supplémentaire des données. Son Volume externe
affiche directement les Parquet déjà présents dans `gs://dtl_finops/focus`.
Supprimer ce catalogue ne supprimerait pas les fichiers et ne réduirait aucun
doublon; cela retirerait seulement leur enregistrement Unity Catalog.

## 6. Recréer les schémas DEV

Exécuter `sql/infrastructure/02_create_dev_schemas.sql`, puis
`sql/maintenance/01_validate_empty_dev.sql`. Les listes de tables DEV doivent
être vides et tous les compteurs OPS DEV doivent valoir zéro. La liste RAW doit
toujours montrer les Parquet mensuels.

## 7. Vérifier l’environnement dans un notebook

Ouvrir `notebooks/operations/environment_check.ipynb`, mettre
`ENVIRONMENT = "dev"`, attacher du compute Serverless, puis exécuter toutes les
cellules. Le notebook valide les namespaces mais ne les crée pas.

## 8. Charger une période mensuelle

Ouvrir `notebooks/pipelines/03_billing_backfill.ipynb` et définir par exemple :

```python
ENVIRONMENT = "dev"
START_MONTH = "2025-01"
END_MONTH = "2025-12"
ARCHIVE = "false"
```

Exécuter les cellules dans l’ordre. Pour chaque mois, le code lit
`billing-YYYY-MM.parquet`, alimente Bronze, applique le Data Contract, remplace
le mois dans Silver, charge Gold, reconstruit les datamarts, puis écrit les
snapshots et la réconciliation dans OPS.

Les tables Bronze et Silver sont créées lors de leur première écriture. Les
tables Gold et datamarts sont créées par les fichiers SQL référencés depuis
`src/finops_cloud/medallion/gold.py`.

## 9. Contrôler le résultat

Exécuter `sql/maintenance/02_validate_loaded_dev.sql`. Vérifier les volumes de
lignes, un statut par mois, et `after_billing_difference = 0` avec
`status = 'PASSED'` dans les réconciliations. Les requêtes finales doivent aussi
retourner zéro clé Gold dupliquée, zéro `duplicate_charge_ids`, et aucun fichier
source associé à plusieurs exécutions d’ingestion.
