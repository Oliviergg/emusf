TODO 
-- migrer le parser Apex vers la grammaire ANTLR apex-parser (évaluée OK, voir docs/eval_grammaire_antlr.md) :
   1. test pytest optionnel qui compare les 2 parsers sur le corpus (oracle)
   2. visitor AntlrToAstVisitor qui mappe le parse tree ANTLR vers ast_nodes.py
   3. retirer lexer.py/apex_parser.py une fois la parité atteinte
-- harnais de test différentiel contre une scratch org (exécuter le même Apex sur EMUSF et une vraie org, comparer résultats/exceptions/limits)
-- corriger le parser maison en attendant : implements multiples avec types qualifiés génériques (Database.Batchable<SObject>, Database.Stateful), modificateurs inherited sharing / webservice
-- continuer les test
-- logguer les requetes soql
-- completer la librairie.
-- logger les appels de triggers
-- mettre les flow dans les scénarios

DONE
-- soql merite son propre lexer et resolver
