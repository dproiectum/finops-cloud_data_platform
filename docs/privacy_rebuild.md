# Reconstruction des données métier nettoyées

Cette maintenance recharge les Parquet vérifiés par les pipelines existants,
d'abord dans DEV puis dans PROD. Elle conserve les quatre catalogues, les schémas,
les Volumes RAW, les chemins GCS, les permissions et l'historique OPS. Elle ne
supprime pas les anciens fichiers Delta, les versions GCS ou les journaux.

Utiliser exclusivement :

`platform/common/notebooks/operations/rebuild_clean_environment.ipynb`

L'ancien `repair_dataset_privacy.ipynb` est un renvoi bloquant. Son APPLY et la
réparation par mapping sont retirés. `docs/manual_platform_rebuild.md` décrit
l'installation avec suppression des catalogues, PAS cette maintenance.

## Préparer les fichiers et le workspace

1. Publier le code relu sur `main` seulement après avoir désactivé le trigger Cloud
   Build de `finops-center`, pour empêcher un déploiement pendant la maintenance.
   Une branche de préparation reste une alternative si le trigger suit `main`.
   Aucun checkpoint, ancien texte nominatif,
   mapping privé, token ou sortie de notebook ne doit être ajouté à Git.
2. Dans le Git Folder belge `finops-cloud_data_platform`, récupérer la branche publiée.
   Sauvegarder les modifications Workspace avant le pull; ne pas faire de reset
   pour contourner un conflit. Redémarrer Python si les modules étaient importés.
3. Suspendre ingestion et promotion. Avant la remise à zéro de PROD, suspendre
   réellement l'accès au site public, pas seulement fermer une fenêtre locale.
   Prévoir le mécanisme de maintenance avant de confirmer `DASHBOARD_PAUSED`.
4. Confirmer que la publication propre a remplacé les mêmes objets GCS : 18
   monthly et 549 daily dans l'inventaire vérifié. Ne pas ajouter les 59 autres
   daily locaux ou les deux Parquet de référence pendant cette opération.
5. Créer soi-même un dossier Workspace privé, hors Git :
   `/Workspace/Users/thailongdam@gmail.com/privacy-rebuild-20261006`.
   Les fichiers `rebuild_dev.json` et `rebuild_prod.json` seront les checkpoints.
   Conserver une copie privée de ces fichiers et des sorties de récupération.
6. Ouvrir le notebook sur le compute Spark Classic choisi dans Belgique. Vérifier
   l'attachement; ne pas sélectionner un SQL Warehouse ou Serverless par défaut.
   Le métastore accepté est
   `gcp:europe-west1:59a04d75-f8cd-4538-a893-9fa79922e4bb`.

## Exécuter PLAN pour DEV

Dans la cellule Paramètres, laisser :

```python
ENVIRONMENT = 'dev'
STAGE = 'plan'
START_MONTH = '2025-01'
END_MONTH = '2026-06'
CONFIRMATION = ''
JOBS_PAUSED = False
DASHBOARD_PAUSED = False
SOURCES_VERIFIED = False
```

Exécuter les cellules d'import, Paramètres puis Exécution. `plan` ne modifie aucune
table; il écrit seulement le checkpoint privé. Attendre `PLAN_READY` et conserver
la sortie des versions de récupération. Contrôler la liste des 18 monthly et des
daily actifs, les mois, les 30 tables et les références financières du JSON.

PLAN bloque si le périmètre mensuel diffère de Silver, si les deux Silver divergent,
si une table n'est pas Delta gérée, si une source manque ou si le contexte change.
Il vérifie les métadonnées/schema des RAW, pas tous leurs contenus. La confirmation
`SOURCES_VERIFIED` porte sur la publication auditée; les pipelines contrôlent à
nouveau les valeurs et le Data Contract avant leurs écritures métier.

Les daily actifs sont déterminés depuis Silver, pas depuis tous les fichiers du
bucket. Les anciennes arrivées Bronze remplacées par un monthly ne sont pas
rejouées. Le nombre historique de lignes Bronze daily peut donc diminuer;
les lignes actives Silver, les coûts, les faits et les périodes doivent rester
conformes au checkpoint. Les événements d'audit de l'ancien chargement restent.

## Remettre à zéro DEV après revue du plan

Seulement lorsque les conditions sont réellement remplies :

```python
STAGE = 'reset'
CONFIRMATION = 'REBUILD_DEV_BUSINESS_DATA'
JOBS_PAUSED = True
DASHBOARD_PAUSED = True
SOURCES_VERIFIED = True
```

Réexécuter Paramètres puis Exécution. La remise à zéro utilise `TRUNCATE TABLE`
sur les 30 tables métier DEV uniquement. Elle ne supprime aucun catalogue, schéma,
Volume, fichier RAW, audit ou entitlement. Attendre `STAGE_PASS`.

Avant de vider les tables, le notebook vérifie les colonnes des deux tables de
charge. Après la remise à zéro, il remplace uniquement les schémas vides qui
contiennent encore l'ancien `charge_subcategory`, en utilisant les définitions
SQL actuelles. Une autre différence de colonnes bloque avant la remise à zéro.

Ne pas lancer `00_drop_all_project_catalogs.sql`, l'initialisation des tables,
les notebooks de maintenance anciens ou un Job normal en parallèle.

## Recharger et valider DEV

Conserver les confirmations et changer seulement `STAGE`, puis réexécuter
Paramètres et Exécution pour chaque étape :

| STAGE | Action | Sortie attendue |
|---|---|---|
| `monthly` | Appelle le même monthly close que `03_billing_backfill`, mois par mois, sans archivage | `STAGE_PASS` |
| `daily` | Rejoue seulement les sources actives sauvegardées, par le pipeline daily et son contrôle | `STAGE_PASS` |
| `validate` | Compare les références, les traces connues, le bridge et le nom de l'application | `PASS` |

Le notebook pilote les fonctions existantes : ne pas exécuter aussi le backfill
ou le daily normal pour le même rechargement. Les étapes ont leurs checkpoints;
une étape réussie n'est pas répétée par un nouvel appel. Les modules ne promettent
pas une durée ou un coût inférieur : les transformations, rafraîchissements de
datamarts et contrôles consomment toujours du compute.

Les deux Silver conservent exactement leurs nombres de lignes et leurs quatre
coûts par mois. Gold conserve ses lignes et les coûts disponibles dans son fait
(le fait n'expose pas ContractedCost). Le mart mensuel est comparé à sa propre
référence avec la tolérance monétaire configurée. Les textes métiers sont contrôlés
par les motifs connus; les relations tags/ressources et `Data Platform` pour
`APP00013057` sont vérifiées. La dernière étape corrige seulement ce libellé dans
`business_scope` pour l'environnement choisi, sans toucher aux clés ou permissions.

Une divergence laisse la maintenance en échec : pas de publication malgré un
rechargement apparemment réussi. Les empreintes de clés SKU/tags peuvent changer
avec le texte nettoyé; les dimensions et leurs relations sont reconstruites ensemble.

## Refaire séparément pour PROD

Après DEV PASS, conserver le checkpoint DEV. Mettre PROD et le site en maintenance.
Choisir `ENVIRONMENT = 'prod'`, remettre `STAGE = 'plan'`, `CONFIRMATION = ''` et
les trois confirmations à `False`. PLAN capture la référence propre à PROD.

Après revue, utiliser `REBUILD_PROD_BUSINESS_DATA`, confirmer les conditions et
exécuter `reset`, `monthly`, `daily`, `validate` dans cet ordre. Les autres paramètres
et les catalogues ne changent pas. Ne pas comparer PROD à une référence DEV.

Après les deux PASS, exécuter manuellement dans PROD :

1. `platform/common/sql/security/04_create_dashboard_serving_view.sql`;
2. `platform/common/sql/security/05_validate_dashboard_serving_view.sql`.

Les loaders publient déjà `gold.v_cost_allocation`. Aucun nouveau pipeline, bucket
ou changement de chemin n'est nécessaire. Valider les profils et les références
du script 05 comme indiqué dans `apps/finops_dashboard/security/README.md`.

## Traiter une erreur sans perdre la référence

`FAILED` ou `RUNNING` après interruption bloque toute relance automatique. Garder
le checkpoint, les sorties et la dernière source annoncée, puis diagnostiquer.
Ne pas supprimer/éditer le JSON pour passer les contrôles et ne pas recréer PLAN
sur des tables déjà vides. Une remise à zéro multi-table n'est pas une transaction.
Le chargement normal ajoute des audits et actualise les statuts mensuels OPS.

Les versions initiales sont conservées, mais aucune restauration n'est automatique.
Ne pas restaurer seulement une dimension ou un bridge. Une récupération doit
coordonner les tables métier et les statuts OPS devenus dépendants du rechargement.
Ne pas faire de `VACUUM` pendant la fenêtre de maintenance/récupération.

### Reprendre le premier mois après une erreur de schéma de charge

Cette exception concerne uniquement le `MERGE` du premier mois qui attend encore
`charge_subcategory`. Le checkpoint doit indiquer `FAILED`, `failed_stage=monthly`,
`completed=[reset]`, aucun mois ni daily rejoué. La dimension de charge, le fait,
les tags, le bridge, Bronze daily et tous les datamarts doivent être vides. Bronze
billing et les deux Silver doivent contenir uniquement la première source mensuelle
du plan. Les métadonnées de sécurité doivent avoir conservé leurs versions.

Mettre à jour le Git Folder, puis redémarrer Python pour importer le code corrigé.
Dans le même notebook et avec le même dossier de checkpoint, utiliser pour DEV :

```python
ENVIRONMENT = 'dev'
STAGE = 'recover_charge_schema'
CONFIRMATION = 'RECOVER_DEV_FIRST_MONTH_CHARGE_SCHEMA'
JOBS_PAUSED = True
DASHBOARD_PAUSED = True
SOURCES_VERIFIED = True
```

Exécuter Imports, Paramètres puis Exécution, sans utiliser Run all. La reprise
sauvegarde d'abord le checkpoint en échec dans le dossier privé sous
`rebuild_dev.before-charge-schema-recovery.json`. Elle vide de nouveau les 30 tables
métier DEV pour retirer le mois partiel, corrige les deux schémas vides, puis
actualise les versions attendues. Les références financières, versions de
récupération initiales et sources du plan sont conservées. Les événements OPS
en échec restent dans l'historique et aucun entitlement n'est modifié.

Attendre `STAGE_PASS` avec `recovery=CHARGE_SCHEMA_REPAIRED` et `next_stage=monthly`.
Ensuite remettre `STAGE='monthly'` et `CONFIRMATION='REBUILD_DEV_BUSINESS_DATA'`,
réexécuter Paramètres puis Exécution. Une erreur pendant cette reprise bloque
à nouveau : ne pas modifier/supprimer le checkpoint ou son fichier de sauvegarde.
Cette procédure n'autorise aucune reprise générique ni récupération d'un mois
ultérieur. Le `reset` corrigé traite aussi l'ancien schéma en PROD avant son
premier chargement, si cette colonne est encore présente.

Le PASS des motifs connus n'établit pas une anonymisation complète. Examiner aussi
les codes et conventions de nommage avant publication. Les références originales,
anciens snapshots et logs restent privés. Un nettoyage de rétention constitue une
autre opération, pas une raison de supprimer les audits ou les autorisations ici.

## Terminer la publication

Après validation locale sur PROD propre, vérifier les quatre profils en mode
`portfolio_demo`, les exports et les périodes. Si une branche de préparation a
été utilisée, la fusionner dans `main`. Réactiver le trigger et déclencher un build
du code validé, vérifier la révision Cloud Run, puis activer explicitement le mode
portfolio selon le README de sécurité. Ne pas autoriser la publication avant cela.
Reprendre les schedules et l'accès au site seulement après les contrôles finaux.

Références :

- https://docs.databricks.com/gcp/en/sql/language-manual/sql-ref-syntax-ddl-truncate-table
- https://docs.databricks.com/gcp/en/sql/language-manual/functions/current_metastore
