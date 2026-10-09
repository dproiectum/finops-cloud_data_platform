# Plan de finalisation Databricks Belgium

Ce plan complète les procédures de reconstruction, de promotion PROD et du
pipeline Daily. L'ingénieur applique les changements et lance les Jobs dans
l'interface Databricks ; le dépôt fournit le code et les contrôles.

Ce document conserve les jalons de migration. Son état de départ n'est pas un
inventaire en temps réel des Jobs : les succès annoncés ensuite doivent être
associés à leurs Job/Run IDs et au commit exécuté. Le déploiement final du
portfolio est Cloud Run, pas une nouvelle Databricks App obligatoire.

Avant une reprise après nettoyage des textes identifiants, suivre
`docs/privacy_rebuild.md`. Cette maintenance conserve les catalogues, RAW et OPS
et rejoue seulement les données déjà actives. Ne pas rattraper de nouveaux daily
ni activer des schedules pendant la reconstruction. Les jalons ci-dessous
décrivent le plan initial; les résultats de nettoyage et de publication sont à
valider séparément, pas à déduire des premiers runs réussis.

## État de départ

- Les quatre catalogues `finops_raw`, `finops_dev`, `finops_prod` et
  `finops_ops` existent dans Belgium.
- Le backfill mensuel `2025-01` à `2026-06` et les contrôles DEV/PROD ont
  réussi d'après les runs confirmés lors de la migration.
- Le premier run Daily a chargé `2026-07-01` en DEV seulement : le saut des
  tâches PROD était normal avec `promote_to_prod=false`.
- Le YAML Daily du dépôt sélectionne maintenant le plus ancien fichier absent
  de PROD et active `promote_to_prod=true` par défaut. Sa mise à jour effective
  dans le Job et un run complet DEV → PROD restent à vérifier dans l'interface.
- Aucun Job de clôture mensuelle Classic n'est encore défini dans le dépôt.

## 1. Figer la version et les preuves

1. Dans le Git Folder Belgium, faire Pull de `main` et noter le commit.
2. Dans Jobs & Pipelines, relever les Job IDs, Run IDs, paramètres, temps
   d'exécution et statuts du backfill DEV et PROD.
3. Conserver une capture des DAGs réussis et des résultats des contrôles.

Critère de sortie : le Git Folder et le dépôt local pointent sur le même commit,
et les runs historiques sont identifiables sans se fier aux noms affichés seuls.

## 2. Terminer le test Daily DEV → PROD

1. Mettre à jour le Job `finops-daily-dev-to-prod` à partir de
   `platform/classic_compute/jobs/daily_dev_to_prod.yml`.
2. Vérifier les paramètres effectifs : `discovery_environment=prod`,
   `processing_date` vide, `source_uri_override` vide et
   `promote_to_prod=true`.
3. Garder `Maximum concurrent runs = 1`, la queue activée et aucun trigger.
4. Lancer le Job complet une fois. La découverte doit sélectionner le plus
   ancien fichier RAW absent de PROD, normalement `2026-07-01` si aucun autre
   run ne l'a déjà promu.
5. Vérifier les neuf tâches : DEV peut écrire zéro ligne pour un fichier déjà
   chargé ; PROD charge puis valide ce même fichier. Contrôler
   `finops_ops.audit.pipeline_run` et le statut `OPEN` du mois dans les deux
   environnements.
6. Relancer volontairement le même fichier via `source_uri_override` une fois
   pour prouver l'idempotence, puis remettre ce paramètre à vide.

Critère de sortie : `validate_daily_dev` et `validate_daily_prod` sont verts,
les lignes Bronze/Silver ne sont pas dupliquées et aucun chemin manuel n'est
nécessaire pour l'exécution normale.

## 3. Traiter le retard Daily de juillet et août

Le Job actuel sélectionne **un fichier par run**. Un schedule quotidien ne
rattraperait donc pas rapidement des dizaines de fichiers en attente.

1. Relever le nombre de fichiers `NEW`, `LOADED` et `CLOSED` avec
   `discover_daily_files.ipynb`, d'abord pour DEV puis pour PROD.
2. Choisir une méthode de rattrapage : plusieurs runs successifs du Job
   existant, ou une boucle d'orchestration dédiée qui traite la liste des
   candidats dans l'ordre avec une seule promotion active à la fois.
3. Exécuter le rattrapage sans paralléliser deux écritures sur le même mois.
4. Relancer la découverte jusqu'à `has_new_file=false` pour PROD, puis
   comparer DEV et PROD par mois (lignes et `BilledCost`).

Critère de sortie : tous les fichiers Daily attendus sont présents dans PROD,
les deux environnements se réconcilient et aucun mois clôturé n'a été modifié.

## 4. Construire la clôture mensuelle DEV → PROD

Le notebook partagé `platform/common/notebooks/pipelines/02_monthly_close.ipynb`
et le module `src/finops_cloud/pipelines/monthly_close.py` existent. Il manque
l'orchestration Classic qui vérifie l'arrivée du billing, ferme DEV, valide
DEV, puis ferme et valide PROD pour **un mois précis**.

1. Vérifier que `billing-YYYY-MM.parquet` existe dans le Volume RAW. Ne pas
   fermer un mois en l'absence du fichier mensuel définitif.
2. Définir la règle de sélection du mois et le garde empêchant les Daily de
   poursuivre pendant sa clôture. Prévoir le cas où un mois est déjà fermé
   en DEV mais reste à promouvoir vers PROD.
3. Créer un YAML Classic distinct du Job de backfill historique, avec
   `Maximum concurrent runs = 1` et sans schedule initial.
4. Ajouter des contrôles propres au mois chargé : `month_status`, snapshots
   `BEFORE/SOURCE/AFTER`, réconciliation `PASSED`, absence de doublons et
   égalité du résultat final DEV/PROD. Le contrôle DEV historique complet
   `02_validate_loaded_dev.sql` ne convient plus car il exige PROD vide.
5. Tester la clôture sur un mois dont le billing est réellement présent,
   puis tester une relance idempotente avant d'activer un trigger.

Critère de sortie : le billing mensuel devient la source d'autorité dans DEV
et PROD ; les Daily du mois fermé ne sont plus ingérés ; l'audit OPS conserve
deux historiques séparés.

## 5. Activer l'exploitation

1. Daily : choisir un trigger adapté à l'arrivée des Parquet sur le Volume
   RAW, ou un schedule après l'heure habituelle de dépôt. Vérifier son
   comportement sur un jour sans fichier. Un run sans candidat doit se
   terminer sans chargement.
2. Monthly : n'activer son trigger qu'après les tests de clôture et la
   vérification de la disponibilité du billing mensuel.
3. Configurer notifications d'échec, retries limités et `Maximum concurrent
   runs = 1` ; documenter la procédure `Repair run` pour chaque Job.
4. Définir l'auto-termination du cluster All-Purpose ou comparer son coût à
   un Job Compute Classic. Conserver une seule configuration mesurée par
   scénario de benchmark.

Critère de sortie : un nouveau fichier Daily et un nouveau billing mensuel
suivent le cycle complet sans saisie de chemin ni modification manuelle du
Job.

## 6. Mesurer les coûts et finaliser la démonstration

1. Utiliser `platform/common/sql/monitoring/01_job_run_dbu_and_list_cost.sql`
   pour les durées, DBU et coûts Databricks au tarif catalogue.
2. Pour Classic, ajouter les coûts des VM, disques et réseau depuis GCP Cloud
   Billing. Noter la période et le cluster ID de chaque comparaison.
3. Vérifier le dashboard Cloud Run avec
   `apps/finops_dashboard/README.md` : connexion SQL à PROD, scopes autorisés et
   lecture du résumé Platform Costs approuvé. Suivre
   `docs/platform_costs_setup.md` pour la collecte indépendante. Databricks Apps
   reste une alternative documentée dans `docs/databricks_streamlit_app.md`,
   pas un second déploiement requis.
4. Conserver les captures des DAGs, contrôles, tables OPS, dashboard et coûts.

Critère de fin : chargement historique, Daily, clôture mensuelle, surveillance
et dataviz sont reproductibles à partir des fichiers du dépôt et de la
documentation, avec les mêmes catalogues dans le workspace Belgium.
