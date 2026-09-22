# Phase 9 — Dataviz Streamlit dans Databricks Apps

Cette phase commence après la réussite du chargement et des contrôles PROD. Elle
ne modifie aucune table : l'application interroge uniquement les datamarts
certifiés et les audits OPS en lecture seule.

## 1. Synchroniser le code

Dans le Git Folder Databricks, sélectionner `main`, faire **Pull** et vérifier la
présence de :

```text
apps/finops_dashboard/app.py
apps/finops_dashboard/app.yaml
apps/finops_dashboard/requirements.txt
```

## 2. Créer l'application

1. ouvrir **Databricks Apps**;
2. cliquer sur **Create app** puis **Create a custom app**;
3. utiliser le nom `finops-control-center`;
4. sélectionner le dépôt Git du projet et le dossier
   `apps/finops_dashboard` comme source.

Le nom d'une Databricks App ne peut contenir que des minuscules, chiffres et
tirets et ne peut plus être renommé après sa création.

## 3. Ajouter le SQL Warehouse

Dans **App resources** :

1. cliquer sur **Add resource** puis **SQL warehouse**;
2. sélectionner le Warehouse qui a servi aux contrôles PROD;
3. choisir la permission **Can use**;
4. utiliser exactement la resource key `sql-warehouse`.

`app.yaml` injecte l'identifiant du Warehouse dans
`DATABRICKS_WAREHOUSE_ID`. Le code résout ensuite le HTTP Path avec le SDK. Aucun
identifiant de Warehouse ni token personnel n'est stocké dans Git.

## 4. Accorder la lecture Unity Catalog

Récupérer le nom ou l'application ID du service principal créé pour l'App, puis
exécuter dans un SQL Warehouse en remplaçant le placeholder :

```sql
GRANT USE CATALOG ON CATALOG finops_prod TO `<app-service-principal>`;
GRANT USE SCHEMA ON SCHEMA finops_prod.datamart TO `<app-service-principal>`;
GRANT SELECT ON SCHEMA finops_prod.datamart TO `<app-service-principal>`;

GRANT USE CATALOG ON CATALOG finops_ops TO `<app-service-principal>`;
GRANT USE SCHEMA ON SCHEMA finops_ops.audit TO `<app-service-principal>`;
GRANT SELECT ON SCHEMA finops_ops.audit TO `<app-service-principal>`;
```

Ne pas accorder `MODIFY`, `CREATE TABLE`, `WRITE VOLUME` ou des droits sur RAW,
Bronze, Silver et Gold. Le dashboard n'en a pas besoin.

## 5. Déployer

Cliquer sur **Deploy**. Databricks installe les dépendances de
`requirements.txt`, puis exécute la commande définie par `app.yaml` :

```text
streamlit run app.py
```

Si le déploiement échoue, ouvrir les logs. Les causes les plus probables sont :

- resource key différente de `sql-warehouse`;
- permission **Can use** absente sur le Warehouse;
- `USE CATALOG`, `USE SCHEMA` ou `SELECT` absent;
- Git Folder non synchronisé.

## 6. Vérifier les pages

Contrôler chaque entrée de navigation :

1. **Knowledge Base** : formules, dictionnaire des colonnes, glossaire et cycle
   FinOps;
2. **Executive Overview** : coûts, variation mensuelle, activité et tendances;
3. **Cost Drivers** : services, catégories de charge et SKU;
4. **Savings** : comparaisons List, Contracted et Effective;
5. **Allocation & Accountability** : centres de coûts, abonnements et owners;
6. **Resources** : ressources, régions et Resource Groups;
7. **Operations & Quality** : qualité, derniers runs, réconciliations et séparation
   DEV/PROD;
8. **Architecture** : lineage, Medallion et datamarts certifiés.

Le sélecteur de mois doit proposer les 18 périodes de `2025-01` à `2026-06`.

## 7. Captures de démonstration

Conserver au minimum :

- la page Executive Overview sur `2026-06`;
- la page Cost Drivers;
- la page Knowledge Base avec les formules;
- le dictionnaire des colonnes FOCUS;
- la page Operations avec les statuts PROD;
- la page Architecture & Lineage;
- la configuration des ressources de l'App montrant le Warehouse en **Can use**.
