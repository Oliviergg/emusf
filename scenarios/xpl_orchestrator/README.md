# Scénario LIVE — orchestrateur XPL

Déroule la première étape de la machine à états de qualification
(`01 - New` → `QUALIFY`) de bout en bout : lit un vrai marché public du
schéma `data`, appelle le LLM (Gemini 2.5 Flash) **en LIVE** via OpenRouter,
parse le score structuré et fait transiter l'analyse vers `10 - Qualified`
ou `99 - Rejected`.

## Prérequis

- La base `data` peuplée (config machine à états + marchés) — voir `.seed_tables`.
- Le Named Credential **OpenRouterAPI** avec une vraie clé, dans un fichier
  gitignoré. Deux emplacements possibles (le plus spécifique gagne) :
  - `scenarios/.credentials.local.yaml` (partagé entre scénarios)
  - `scenarios/xpl_orchestrator/credentials.local.yaml`

  Format :
  ```yaml
  OpenRouterAPI:
    url: https://openrouter.ai/api/v1
    headers:
      Authorization: Bearer sk-or-v1-VOTRE_CLE
      Content-Type: application/json
  ```

## Lancer

```bash
python3 run.py scenarios/xpl_orchestrator
```

Attendu : 4 assertions vertes, un statut final `Qualified`/`Rejected` et une
justification produite par le LLM.
