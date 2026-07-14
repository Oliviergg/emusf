# Scripts d'évaluation de la grammaire ANTLR

Scripts historiques de l'évaluation qui a validé la grammaire
[`apex-dev-tools/apex-parser`](https://github.com/apex-dev-tools/apex-parser)
pour EMUSF (résultats : `docs/eval_grammaire_antlr.md`). La chaîne ANTLR est
depuis devenue le frontend par défaut, vendorée dans `emusf/antlr/`.

Les scripts utilisent le parser vendoré — aucune génération nécessaire :

```bash
python3 tools/grammar_eval/eval_grammar.py   # corpus .cls/.trigger : ANTLR vs parser maison (legacy)
python3 tools/grammar_eval/eval_tricky.py    # batterie de constructions Apex avancées
```

Les tests pérennes équivalents vivent dans `tests/test_parser_oracle.py`
(verdicts accepté/rejeté) et `tests/test_ast_equivalence.py` (AST identiques).
Pour régénérer le parser après une mise à jour de grammaire :
`emusf/antlr/README.md`.
