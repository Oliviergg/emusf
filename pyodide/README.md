# EMUSF dans le navigateur — GitHub Pages + Pyodide

Un REPL Apex/SOQL 100 % côté client : l'interpréteur emusf tourne dans
[Pyodide](https://pyodide.org) (CPython compilé en WebAssembly) et la base
« PostgreSQL » est remplacée par SQLite en mémoire via un shim psycopg2.
Aucun serveur, aucune donnée ne quitte l'onglet.

```
navigateur
└── Pyodide (Python 3.14 / wasm)
    ├── emusf/            ← le package du repo, inchangé
    ├── antlr4/           ← runtime ANTLR (wheel PyPI, pur Python)
    └── psycopg2/         ← shim/psycopg2 : API psycopg2 → sqlite3 (stdlib)
        └── SQLite en mémoire (schéma "test", PgTestOrg)
```

## Contenu

- `web/index.html` — la page : charge Pyodide depuis le CDN jsdelivr,
  décompresse `emusf_bundle.zip`, expose le REPL (SOQL, Apex, triggers,
  exécution des classes de démo `apex/*.cls`).
- `web/emusf_web.py` — bootstrap Python : crée le `PgTestOrg`, seed de démo
  (mêmes données que `run.py`), boucle REPL (`run_line`, `run_class`, `reset`).
- `shim/psycopg2/` — émulation du sous-ensemble psycopg2 utilisé par emusf,
  adossée à `sqlite3` : placeholders `%s`, `RealDictCursor`,
  `errors.UndefinedTable/UndefinedColumn`, schémas PG (bases `ATTACH`-ées),
  `information_schema`/`pg_tables`, `TRUNCATE`, `ILIKE`, cast `::boolean`…
- `build.py` — construit `dist/` (page + `emusf_bundle.zip`).
- `.github/workflows/pages.yml` — build + déploiement GitHub Pages.

## Déploiement

Le workflow publie automatiquement à chaque push sur `main`.
**Une seule action manuelle** : dans le repo GitHub,
*Settings → Pages → Build and deployment → Source = « GitHub Actions »*.

La page est ensuite servie sur : `https://<owner>.github.io/emusf/`

## Développement local

```bash
python3 pyodide/build.py          # produit pyodide/dist/ (réseau requis : PyPI)
cd pyodide/dist && python3 -m http.server 8000
# → http://localhost:8000  (Pyodide est chargé depuis le CDN jsdelivr)
```

Sans accès au CDN, servir une distribution locale et la passer en query
param : `npm pack pyodide@314.0.2`, extraire, puis
`http://localhost:8000/?pyodide=/chemin/vers/package/`.

## Bonus : la suite de tests sans PostgreSQL

Le shim fonctionne aussi sous CPython — pratique pour lancer les tests sans
serveur PG :

```bash
PYTHONPATH=pyodide/shim python3 -m pytest tests/ --ignore=tests/test_pg_data_org.py
```

(`test_pg_data_org.py` reste exclu : il vérifie la visibilité transactionnelle
entre connexions concurrentes, ce qu'une base SQLite en mémoire par connexion
ne peut pas simuler.)

## Limites connues dans le navigateur

- `PgDataOrg` (export de données réelles) n'est pas proposé — l'org du REPL
  est le bac à sable `PgTestOrg`, réinitialisé à chaque rechargement.
- Les callouts HTTP Apex (`Http.send`) dépendent de `requests`, non chargé.
- Sémantique SQLite ≠ PostgreSQL sur les cas exotiques (collations, types
  stricts) — la suite pytest passe intégralement hors `test_pg_data_org.py`.
