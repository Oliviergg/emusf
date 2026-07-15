# EMUSF — Émulateur Salesforce

Exécute de l'Apex, du SOQL, des triggers et des flows Salesforce **en local**,
sans org : le code est parsé puis interprété contre une base PostgreSQL qui
simule l'org. Utile pour développer, tester et déboguer hors ligne.

```
source Apex → emusf/antlr/ (grammaire apex-parser) → ast_nodes → emusf/interpreter/ → PostgreSQL
```

## Prérequis

- Python ≥ 3.11
- PostgreSQL accessible (connexion dans `emusf/config.py`)

## Installation

Pur Python, pas de build. On installe les dépendances et on lance depuis la
racine du repo :

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "psycopg2-binary" "antlr4-python3-runtime~=4.13.2" PyYAML requests
pip install pytest flask cryptography   # pour les tests et scénarios
```

Le parser ANTLR est déjà généré et versionné (`emusf/antlr/generated/`) — aucun
Java requis à l'exécution.

## Configuration

`emusf/config.py` lit, dans l'ordre : variables d'environnement, fichier `.env`
(gitignoré), puis des défauts. Copier `.env.example` en `.env` et adapter :

```
EMUSF_DSN=host=127.0.0.1 port=6002 user=postgres password=… dbname=biup
EMUSF_SFDX_OBJECTS=/chemin/vers/force-app/main/default/objects
EMUSF_SF_CLASSES=/chemin/vers/force-app/main/default/classes
```

Deux schémas PostgreSQL : **`test`** (bac à sable jetable) et **`data`**
(données Salesforce exportées, lecture ou DML transactionnel).

## Utilisation — `run.py`

Point d'entrée unique ; le mode dépend de la cible.

```bash
python3 run.py                                   # REPL interactif (bac à sable)
python3 run.py --org data                        # REPL sur les données exportées
python3 run.py apex/AccountDemo.cls [méthode]    # exécute une méthode statique
python3 run.py apex/AccountPgDemo.cls --org data # idem sur les vraies données
python3 run.py scenarios/account_trigger         # scénario (classes + triggers + flows)
```

Options : `--ast` (affiche l'AST), `--trace [normal|verbose]` (trace l'exécution :
appels, statements avec leur ligne source, SOQL, DML), `--no-seed` / `--no-triggers`
(bac à sable), et pour `--org data` : `--commit` (persiste, sinon rollback en fin
de run), `--triggers` (déclenche les triggers DML).

## Les trois orgs

| Org | Schéma | Rôle |
|-----|--------|------|
| `PgTestOrg` | `test` | bac à sable : DML, auto-création de tables, triggers, isolation par run |
| `PgDataOrg` | `data` | DML sur l'export réel, en transaction annulée par défaut (`--commit` pour persister), schéma strict |
| `PgOrg` | `data` | lecture seule des données exportées |

## Tests

```bash
python3 -m pytest tests/ -v          # tests unitaires (Python) de l'émulateur
python3 apex_tests/run_tests.py      # suite de tests écrits en Apex
python3 apex_tests/run_sf_tests.py   # tests du projet SFDX réel (via EMUSF_SF_CLASSES)
```

## Repères

- `emusf/antlr/` — chaîne de parsing (grammaire apex-parser vendorée, voir son README)
- `emusf/interpreter/` — interpréteur (package de mixins par domaine)
- `emusf/pg_*.py` — les orgs PostgreSQL ; `emusf/soql_*.py` — SOQL → SQL
- `scenarios/` — cas de bout en bout ; `web/` — interface web (Flask + SLDS)
- `CLAUDE.md` — architecture détaillée ; `TODO.md` — pistes en cours
