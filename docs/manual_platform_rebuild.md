# Reconstruction manuelle DEV dans Databricks

Les scripts à exécuter sont regroupés dans `sql/platform_setup`. Leur numéro
indique l’ordre réel. Aucun script n’est lancé automatiquement par le projet.

## Situation des trois catalogues

- `finops_raw` contient les Volumes externes donnant accès aux Parquet GCS. Il
  reste disponible pour permettre le rechargement.
- `finops_dev` contient uniquement les tables générées par le traitement. Il
  est supprimé puis recréé pendant cette procédure.
- `finops_ops` contient les audits. La procédure fonctionne qu’il existe déjà
  ou qu’il ait été supprimé.

Les fichiers visibles dans `finops_raw` ne sont pas des copies supplémentaires :
le Volume affiche directement `gs://dtl_finops/focus`.

## 1. Mettre à jour le Git Folder

Dans **Workspace → Git folders**, ouvrir le projet et sélectionner **Pull**.
Vérifier d’abord qu’aucune modification Databricks non enregistrée ne provoquera
de conflit.

## 2. Supprimer complètement DEV

Exécuter `sql/platform_setup/00_reset_dev.sql` dans un SQL Warehouse. Il
supprime `finops_dev` avec tous ses schémas et toutes ses tables. Il ne consulte
pas OPS et fonctionne donc même si `finops_ops` a déjà été supprimé.

## 3. Créer ou vérifier RAW

Exécuter `sql/platform_setup/01_create_or_verify_raw.sql`.

- si `finops_raw` existe, les `CREATE IF NOT EXISTS` le conservent;
- s’il n’existe pas, le catalogue, le schéma et les Volumes sont créés;
- la dernière instruction doit lister les fichiers
  `monthly/billing-YYYY-MM.parquet`.

Cette étape ne crée aucune table Bronze, Silver, Gold ou datamart et ne modifie
aucun Parquet.

## 4. Recréer DEV vide

Exécuter `sql/platform_setup/02_create_dev.sql`. Le script crée seulement :

- `finops_dev.bronze`;
- `finops_dev.silver`;
- `finops_dev.gold`;
- `finops_dev.datamart`.

## 5. Recréer OPS avant toute validation

Exécuter `sql/platform_setup/03_create_ops.sql`. Il crée `finops_ops.audit` et
les cinq tables opérationnelles avec la colonne `environment`.

Exécuter ensuite `sql/platform_setup/04_clear_dev_ops.sql`. Si OPS vient d’être
recréé, les tables sont déjà vides et les `DELETE` ne suppriment rien. Si OPS
existait auparavant, seules les lignes `environment = 'dev'` sont supprimées;
les lignes PROD sont conservées.

## 6. Vérifier l’état vide

Exécuter `sql/platform_setup/05_validate_empty_dev.sql` seulement maintenant,
après les étapes 4 et 5. Les quatre listes de tables DEV doivent être vides et
les cinq compteurs OPS DEV doivent être égaux à zéro. Les Parquet RAW doivent
toujours être listés.

## 7. Vérifier le contexte Databricks

Ouvrir `notebooks/operations/environment_check.ipynb`, définir
`ENVIRONMENT = "dev"`, attacher du compute Serverless, puis exécuter toutes les
cellules. Ce notebook valide les objets créés sans les créer lui-même.

## 8. Recharger les mois

Ouvrir `notebooks/pipelines/03_billing_backfill.ipynb` et définir la période :

```python
ENVIRONMENT = "dev"
START_MONTH = "2025-01"
END_MONTH = "2025-12"
ARCHIVE = "false"
```

Exécuter toutes les cellules dans l’ordre. Chaque fichier mensuel traverse
Bronze, le Data Contract, Silver, Gold et les datamarts. Les snapshots et les
réconciliations sont enregistrés dans OPS avec `environment = 'dev'`.

## 9. Vérifier le chargement et les doublons

Exécuter `sql/platform_setup/06_validate_loaded_dev.sql`. Les contrôles attendus
sont :

- `status = 'PASSED'` et `after_billing_difference = 0` par mois;
- aucun fichier source associé à plusieurs exécutions d’ingestion;
- `duplicate_keys = 0` dans la table de faits Gold;
- `duplicate_charge_ids = 0` dans les snapshots `AFTER`.
