TODO 
-- migrer le parser Apex vers la grammaire ANTLR apex-parser (évaluée OK, voir docs/eval_grammaire_antlr.md) :
   1. [FAIT] test pytest optionnel qui compare les 2 parsers sur le corpus (tests/test_parser_oracle.py)
   2. [FAIT] frontend ANTLR → mêmes ast_nodes (emusf/antlr_frontend.py, activation EMUSF_FRONTEND=antlr,
      équivalence d'AST validée sur tout le corpus par tests/test_ast_equivalence.py)
   3. passer EMUSF_FRONTEND=antlr par défaut, puis retirer lexer.py/apex_parser.py/token_parser.py ;
      assainir alors les quirks du parser maison répliqués par parité (liste en docstring de antlr_frontend.py :
      décls sans init ignorées, premier catch seulement, types de champs avec modificateur absorbé, etc.)
-- harnais de test différentiel contre une scratch org (exécuter le même Apex sur EMUSF et une vraie org, comparer résultats/exceptions/limits)
-- corriger le parser maison en attendant : implements multiples avec types qualifiés génériques (Database.Batchable<SObject>, Database.Stateful), modificateurs inherited sharing / webservice
-- continuer les test
-- logguer les requetes soql
-- completer la librairie.
-- logger les appels de triggers
-- mettre les flow dans les scénarios

DONE
-- soql merite son propre lexer et resolver
