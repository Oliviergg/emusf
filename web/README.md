# Interface web

App Flask qui affiche les objets Salesforce (données exportées, schéma `data`)
avec le Salesforce Lightning Design System : list views, layouts de détail,
édition, recherche et rendu de pages Visualforce.

## Prérequis

- La base PostgreSQL de `emusf/config.py` avec le schéma `data` peuplé
  (export Salesforce)
- Le projet SFDX local (chemins dérivés de `SFDX_OBJECTS` dans
  `emusf/config.py`) pour les layouts, labels et pages VF
- Les assets SLDS :

```bash
cd web
npm install
mkdir -p static/slds
cp -R node_modules/@salesforce-ux/design-system/assets/* static/slds/
```

## Lancer

```bash
python3 web/app.py     # http://localhost:5001
```
