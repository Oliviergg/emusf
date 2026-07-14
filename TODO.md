TODO 
-- migrer le parser Apex vers la grammaire ANTLR apex-parser (évaluée OK, voir docs/eval_grammaire_antlr.md) :
   1. [FAIT] test pytest optionnel qui compare les 2 parsers sur le corpus (tests/test_parser_oracle.py)
   2. [FAIT] frontend ANTLR → mêmes ast_nodes, équivalence d'AST validée sur tout le corpus
   3. [FAIT] chaîne ANTLR par défaut, vendorée dans emusf/antlr/ (grammaire + parser généré committé,
      pas de Java requis) ; EMUSF_FRONTEND=legacy pour l'ancien parser le temps du rodage
   4. après rodage : retirer lexer.py/apex_parser.py/token_parser.py et les tests croisés,
      puis assainir les quirks maison répliqués par parité (liste en docstring de emusf/antlr/builder.py :
      décls sans init ignorées, premier catch seulement, types de champs avec modificateur absorbé, etc.)
-- harnais de test différentiel contre une scratch org (exécuter le même Apex sur EMUSF et une vraie org, comparer résultats/exceptions/limits)
-- corriger le parser maison en attendant : implements multiples avec types qualifiés génériques (Database.Batchable<SObject>, Database.Stateful), modificateurs inherited sharing / webservice
-- continuer les test
-- logguer les requetes soql
-- completer la librairie.
-- logger les appels de triggers
-- mettre les flow dans les scénarios
-- org data DML : sémantique partial-success de Database.insert/update (allOrNone=false) sur PgDataOrg
-- org data DML : commande REPL /commit pour committer en cours de session
-- org data DML : config des relations SFDX au-delà de Account/Contact (make_org ne charge que ces deux-là)
-- DML sur SOQL inline : 'delete [SELECT ...]' échoue ('str' object has no attribute 'get') — sur toutes les orgs

DONE
-- soql merite son propre lexer et resolver
