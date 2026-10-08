# Platform Costs — installation manuelle et automatisation

## 1. Périmètre et état des fichiers

Cette chaîne suit les dépenses réelles de la plateforme, indépendamment des
consommations Azure fictives. L'utilisateur exécute toutes les étapes cloud.
Ne pas supprimer de catalogue, de table existante ou de source FOCUS.

```text
BigQuery (export GCP) → export Parquet GCS avec marqueur COMPLETE
                                           │
system.billing Databricks ────────→ notebook de collecte
                                           │
                           finops_ops.monitoring (Delta + audit)
                                           │
                          objet JSON privé et validé dans GCS
                                           │
                           Cloud Run → About the Project → Platform Costs
```

Organisation :

```text
platform/common/sql/monitoring/platform_costs/
  00_check_gcp_export.sql                 # BigQuery, lecture seule
  01_export_gcp_to_gcs.sql                # BigQuery, export sur GCS
  02_collect_databricks_monthly.sql        # Databricks, lecture seule
  03_create_monitoring_objects.sql        # Databricks, création additive
  04_validate_platform_costs.sql          # Databricks, contrôle après collecte
platform/common/notebooks/monitoring/collect_platform_costs.ipynb
platform/classic_compute/jobs/platform_costs_daily.yml
platform/serverless/jobs/platform_costs_daily.yml
src/finops_cloud/monitoring/platform_costs.py
apps/finops_dashboard/platform_costs/     # contrat partagé et affichage
```

Les anciens SQL sous l'application ont été déplacés, pas copiés. L'ancien
`project_costs` est remplacé par `platform_costs`. Le téléchargement CSV et son
publisher local ne font plus partie du parcours. Les transformations Gold,
datamarts, pipelines métier et fichiers de réinitialisation sont conservés :
leurs usages ne sont pas rendus obsolètes par ce suivi de coût.

### Publier le code préparé, puis mettre à jour Databricks

Les changements sont préparés localement ; ce guide ne suppose pas un push déjà
réalisé. Dans le Terminal, depuis le dépôt cloud uniquement :

```bash
cd "/Users/dtl/Desktop/PFE/FinOps Cloud Data Platform"
git status --short
git remote get-url origin
git diff --check
git add -A -- README.md pyproject.toml apps/finops_dashboard platform \
  src/finops_cloud/monitoring tests/unit docs/platform_costs_setup.md
git diff --cached --stat
git commit -m "Add automated Platform Costs monitoring and private GCS serving"
git push origin main
```

Vérifier que le remote est le dépôt **finops-cloud_data_platform**, jamais le POC
ou le mémoire. Relire les fichiers ajoutés avant le commit ; si d'autres
modifications personnelles sont présentes, ne pas les ajouter sans les examiner.
Le trigger Cloud Build actif peut démarrer un build facturable. Dans Databricks
Belgium, ouvrir le Git folder cloud, puis **Git → Pull** sur `main`. Garder le
nouveau Job en pause tant que les étapes ci-dessous ne sont pas validées.

## 2. Vérifier les accès et les emplacements

Dans GCP, sélectionner `global-repeater-355412`. Dans Databricks, travailler
uniquement dans **Belgium**. Le SQL source sélectionne les deux workspaces
FinOps, depuis septembre 2026 ; il ne crée pas de copie de leurs tables système.

Dans **Cloud Storage → dtl_finops → Configuration**, vérifier la localisation
(attendue : `europe-west1`), la confidentialité et l'accès uniforme au bucket.
Le dataset BigQuery est en `EU`. L'export impose une localisation compatible ;
si une erreur de localisation apparaît, arrêter et vérifier la configuration,
ne pas changer silencieusement le dataset ou créer un bucket au hasard.
Ne pas désactiver Public Access Prevention pour cette fonctionnalité.
Un export entre `EU` et un bucket régional Belgium peut entraîner des frais de
transfert : ne pas supposer que le transfert est gratuit parce que les deux sont
en Europe. Ici, seuls de petits agrégats sont exportés, pas la table de billing
complète. Vérifier les frais réellement observés ; conserver le bucket existant
ne justifie pas une promesse de coût nul.

Dans Databricks, vérifier que `finops_gcs` couvre `gs://dtl_finops/` et que son
storage credential peut lire et écrire le nouveau préfixe. Ne pas placer les
fichiers dans le bucket de stockage géré `dtl_finops-unitycatalog-euw1`.

Le nouveau chemin est `gs://dtl_finops/platform_costs/`. Il se crée avec les
premières écritures ; aucun nouveau bucket n'est nécessaire :

```text
platform_costs/
  extracts/gcp/<extraction UTC + identifiant unique>/
    data-000000000000.parquet
    complete-000000000000.json
  published/latest.json
```

## 3. Préparer l'identité de l'export BigQuery

Pour un premier test manuel, ta propre identité doit pouvoir lancer une requête,
lire la table de billing et écrire dans le préfixe d'export. Pour le planning,
créer dans **IAM & Admin → Service Accounts** un compte dédié, sans clé JSON :

`finops-platform-cost-export@global-repeater-355412.iam.gserviceaccount.com`

Accorder :

| Ressource | Droit |
| --- | --- |
| Projet GCP FinOps | BigQuery Job User (`roles/bigquery.jobUser`) |
| Dataset `finops_billing` | BigQuery Data Viewer (`roles/bigquery.dataViewer`) |
| Objets GCS du préfixe d'export | Storage Object User (`roles/storage.objectUser`) avec condition ci-dessous |

Dans **Cloud Storage → dtl_finops → Permissions → Grant access**, choisir ce
compte, le rôle Storage Object User et une condition IAM nommée
`platform_costs_gcp_export` :

```text
resource.name.startsWith('projects/_/buckets/dtl_finops/objects/platform_costs/extracts/gcp/')
```

L'export BigQuery demande `storage.objects.create` et `storage.objects.delete` ;
le rôle Object Creator seul ne suffit pas. La condition limite ces permissions
aux nouveaux objets d'export. Si le bucket n'a pas l'accès uniforme, les
conditions IAM peuvent ne pas être disponibles : arrêter avant d'accorder un
rôle non conditionnel sur tout le bucket. Vérifier aussi les droits hérités :
ajouter une condition ne réduit pas un autre rôle plus large déjà accordé.

Pour sélectionner le compte dans Scheduled Queries, l'opérateur a besoin de
Service Account User sur ce compte et des droits de gestion du transfert.
Activer BigQuery Data Transfer API si la console le demande. Ne pas distribuer
de clé à Databricks ou au dashboard.

## 4. Exporter GCP vers GCS — BigQuery uniquement

1. Ouvrir **BigQuery → SQL query**, dans le projet FinOps.
2. Exécuter `00_check_gcp_export.sql`. Vérifier les mois et devises disponibles.
3. Ouvrir une nouvelle requête et coller `01_export_gcp_to_gcs.sql`.
4. Dans **Query settings**, choisir la localisation `EU`. Vérifier les octets
   analysés et fixer une limite de facturation appropriée si l'interface le permet.
5. Lancer le script avec ton identité pour ce premier test.
6. Le dernier résultat doit afficher `run_id`, `base_uri`, `extracted_at` et
   `exported_rows > 0`. Dans GCS, vérifier les Parquet **et** le fichier `complete`.

Un répertoire sans marqueur COMPLETE n'est jamais consommé. Chaque export a son
propre répertoire : les shards d'un ancien export ne se mélangent pas au nouveau.
Les montants sont transportés sous forme de décimaux textuels dans le Parquet,
sans formatage européen ni conversion flottante. Les tables Delta utilisent
DECIMAL(38,18) ; une valeur collectée non représentable est refusée. Le coût
Databricks est une estimation calculée en décimaux Spark à précision fixe,
exposée en DECIMAL(38,16), pas en flottants ; les DBU source gardent leur précision.
L'affichage à deux décimales n'intervient qu'au dashboard. Les mois restent
`partial`, même si le script réussit.

Les crédits signés sont conservés. Le filtre ne couvre que le projet FinOps et
la période depuis septembre 2026. Des taxes ou charges sans projet peuvent être
absentes ; c'est un suivi opérationnel par mois d'usage UTC, pas une facture
comptable réconciliée. Un export récent peut toujours avoir un historique incomplet.

## 5. Créer les objets — Databricks Belgium uniquement

Dans SQL Editor, sélectionner ton SQL Warehouse et exécuter
`03_create_monitoring_objects.sql`. Il crée seulement :

- le schéma `finops_ops.monitoring` s'il manque ;
- le Volume externe `finops_ops.monitoring.platform_cost_files` ;
- `platform_cost_monthly`, dernier snapshot validé des agrégats ;
- `platform_cost_collection_run`, historique privé des collectes.

Ne pas exécuter les scripts `00_drop...` ni recréer les catalogues.
L'identité de création doit disposer des droits UC requis sur `finops_ops`,
`monitoring` et l'external location `finops_gcs`.

Pour le premier lancement, utiliser ton identité propriétaire. Pour un Job avec
un principal dédié, lui accorder USE CATALOG/SCHEMA, SELECT et MODIFY sur ces
deux tables seulement, READ VOLUME et WRITE VOLUME sur ce Volume, ainsi que la
lecture de `system.billing.usage` et `system.billing.list_prices` avec USE sur
leur catalogue/schéma. Le dashboard ne reçoit **aucun** de ces nouveaux droits.
Ne pas accorder SELECT sur tout `finops_ops` aux profils de démonstration.

## 6. Tester le notebook, puis publier — Databricks

Mettre à jour le Git folder cloud dans Databricks. Ouvrir :

`platform/common/notebooks/monitoring/collect_platform_costs`

Attacher le compute UC existant (Runtime 17.3 convient), depuis le Git folder
complet. Les dossiers `src` et `apps` doivent être présents ; ne pas copier
uniquement ce notebook dans un autre dossier. Aucune installation `%pip` n'est
nécessaire dans ce Runtime. Redémarrer la session Python après une mise à jour
des modules si le notebook était déjà ouvert et exécuté.

Premier lancement :

```text
dry_run = true
confirmation = (vide)
```

Résultat attendu : `PREVIEW`, deux nombres de lignes positifs et le timestamp
de l'export GCP. Aucune table ni aucun objet de publication n'est écrit.

Après validation du périmètre et des libellés destinés au site public :

```text
dry_run = false
confirmation = PUBLISH_PLATFORM_COSTS
```

Résultat attendu : `PUBLISHED`. Le Job remplace atomiquement le snapshot Delta
des tables dédiées au lieu d'ajouter les mêmes coûts. Les corrections ultérieures
sont donc prises en compte. Il écrit ensuite un seul objet GCS `latest.json` et
l'audit. Exécuter `04_validate_platform_costs.sql` dans SQL Editor : les assertions
réussies renvoient NULL, puis les totaux et l'historique sont affichés.

Les deux sources sont exigées. Des prix absents, ambigus ou ne couvrant pas tout
l'intervalle d'usage Databricks empêchent la publication. Les exports GCP doivent
dater de moins de 48 heures. Un échec de validation n'efface pas le dernier objet.
Delta, GCS et audit ne forment pas une transaction distribuée : une panne après
la mise à jour Delta peut laisser le dashboard sur son ancien objet, et une panne
d'audit après l'écriture GCS peut laisser un objet valide déjà publié. Corriger
l'erreur et relancer ; le remplacement est idempotent. Ne pas fabriquer de zéro
ou marquer artificiellement le run comme réussi.

## 7. Donner à Cloud Run la lecture du seul résumé

Dans **Cloud Run → finops-center → Security**, identifier le **runtime service
account**, différent du compte Cloud Build. Ne pas remplacer ce compte sans
revoir les accès aux secrets et au backend Databricks existants.

Sur le bucket `dtl_finops`, accorder à ce compte Storage Object Viewer avec la
condition IAM `platform_costs_dashboard_read` :

```text
resource.name == 'projects/_/buckets/dtl_finops/objects/platform_costs/published/latest.json'
```

Ne pas rendre le bucket public. Ne pas donner au dashboard l'accès à BigQuery,
aux extracts, aux tables de monitoring ou à `system.billing`. Revoir les rôles
hérités pour confirmer qu'aucun accès plus large ne les contourne.

Dans **Cloud Run → Edit & deploy new revision → Variables & Secrets**, ajouter
ces variables **sans supprimer les variables/secrets existants** :

```text
FINOPS_PLATFORM_COSTS_MODE=gcs
FINOPS_PLATFORM_COSTS_GCS_URI=gs://dtl_finops/platform_costs/published/latest.json
FINOPS_PLATFORM_COSTS_MAX_AGE_HOURS=48
```

Déployer la nouvelle version du code via le push/trigger Cloud Build normal,
puis vérifier que la révision conserve ces variables. Ouvrir **About the Project
→ Platform Costs**, recharger après cinq minutes maximum pour le cache, et
choisir EUR pour GCP / USD pour Databricks. Les données ne sont pas converties
entre devises et ne sont pas additionnées en une facture totale.

Le mode GCS ne revient jamais au JSON embarqué en cas de panne. Pour revenir
volontairement au mode hors ligne, définir `FINOPS_PLATFORM_COSTS_MODE=bundled` ;
le snapshot fourni reste vide, pas un exemple financier inventé.

## 8. Activer les deux plannings après les tests

**BigQuery :** depuis le script `01_export_gcp_to_gcs.sql`, créer une Scheduled
Query `finops-platform-costs-gcp-export`, région `EU`, tous les jours à
**05:17 UTC**, avec le compte dédié de l'étape 3. Ne pas configurer une table
de destination : le script contient son export et sa table temporaire. Vérifier
le premier run planifié sous cette identité ; un test sous ton compte personnel
ne prouve pas les droits du compte de service.

**Databricks Belgium :** créer un seul Job `finops-platform-costs-daily`, une tâche
Notebook vers `collect_platform_costs`, `max_concurrent_runs=1`, paramètres Job
`dry_run=false` et `confirmation=PUBLISH_PLATFORM_COSTS`. Choisir l'All-Purpose
existant pour le premier essai Classic, puis vérifier que son ID est encore
`5925-212130-elwuj3uu`. Ne pas créer une tâche SQL Classic.

Les YAML sont des modèles manuels, non inclus dans `databricks.yml` : choisir
uniquement `platform/classic_compute/jobs/platform_costs_daily.yml` dans Belgium.
Le modèle Serverless est une alternative, pas un second Job à déployer.
Vérifier le chemin du Git folder. Les paramètres Job sont transmis au notebook.
Faire **Run now** une fois, puis vérifier l'audit et le dashboard. Le planning du
modèle est **PAUSED** : l'activer ensuite à **08:43 Europe/Paris**, après l'export
GCP (06:43 UTC en été / 07:43 UTC en hiver). Ne pas anticiper l'activation.

Une collecte réussie actualise le dashboard sans push ni rebuild. Le délai inclut
la disponibilité des sources et le cache de cinq minutes. BigQuery Scheduled
Queries et Databricks Jobs sont deux plannings, pas une dépendance transactionnelle :
le notebook choisit le dernier export COMPLETE récent, pas nécessairement celui
du même jour. Surveiller les deux historiques et les timestamps publiés.

## 9. Coût et exploitation

Ce processus ajoute des requêtes BigQuery, un petit export GCS, des lectures
Databricks, du stockage Delta et l'exécution du Job. Ne pas laisser le cluster
All-Purpose actif toute la journée uniquement pour cette collecte : vérifier
son auto-termination et relever durée/DBU/coût VM après les premiers runs.
Le gain économique n'est pas mesuré tant que ces données ne sont pas recueillies.
Le timeout du Job est 30 minutes ; ce petit suivi n'est pas un full load métier.

La première version recalcule toute l'histoire sélectionnée depuis septembre 2026
pour conserver les corrections, au lieu d'un append naïf. À plus grande échelle,
réduire le périmètre de recalcul et réconcilier les corrections historiques.
Les répertoires d'export ne sont pas supprimés automatiquement ; définir plus
tard une rétention limitée à `platform_costs/extracts/gcp/`, jamais au préfixe FOCUS.
Un échec de source ou un snapshot vieux de plus de 48 h rend le coût indisponible.
Configurer les notifications d'échec dans les deux interfaces avec ton email.

## 10. Vérification finale

- BigQuery : export sous le compte planifié réussi, Parquet + COMPLETE présents.
- Databricks : preview puis publication réussis, assertions OK, un seul Job actif.
- GCS : `latest.json` privé, aucun identifiant brut/credential dans les records.
- Cloud Run : mode GCS actif, données visibles, EUR/USD séparés, périodes partial.
- Deuxième run : mêmes clés mensuelles, pas de lignes dupliquées ; les valeurs
  peuvent évoluer si la facturation a reçu des corrections.
- Surveiller une première exécution réellement planifiée avant de déclarer
  l'automatisation opérationnelle. Tests locaux ne valident pas les IAM cloud.

Sources officielles (pour les prérequis, sans promesse de coût nul) :

- https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/export-statements
- https://docs.cloud.google.com/bigquery/docs/exporting-data
- https://docs.cloud.google.com/bigquery/docs/scheduling-queries
- https://docs.cloud.google.com/storage/docs/access-control/iam-roles
- https://docs.cloud.google.com/storage/docs/consistency
- https://cloud.google.com/bigquery/pricing
- https://docs.databricks.com/gcp/en/volumes/
- https://docs.databricks.com/gcp/en/admin/system-tables/pricing
