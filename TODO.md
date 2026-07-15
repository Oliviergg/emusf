TODO 
-- [FAIT] migration du parser Apex vers la grammaire ANTLR apex-parser (voir docs/eval_grammaire_antlr.md) :
   chaîne ANTLR vendorée dans emusf/antlr/ (grammaire + parser généré committé, pas de Java requis) ;
   apex_parser.py/trigger_parser.py sont des façades ; parser maison (lexer/token_parser) supprimé.
-- limitations connues du builder ANTLR (constructions ignorées faute de support interpréteur, voir
   docstring emusf/antlr/builder.py) : décls sans init, upsert/merge/runAs, 2e catch/finally, enums…
-- framework de jobs BTP async : System.enqueueJob->execute->process marche (voir scenarios/queueable_accounts),
   mais QueueManager.enqueueJob complet (Platform Events -> JobEventTrigger -> processNextJob -> CheckQueueJob polling)
   ne s'exécute pas proprement en synchrone (System.enqueueJob imbriqué dans processNextJob n'atteint pas le handler ;
   chemin immediate perd Job_Id ; borné par async_budget). Contournement : createQueueJob + System.enqueueJob direct.
-- harnais de test différentiel contre une scratch org (exécuter le même Apex sur EMUSF et une vraie org, comparer résultats/exceptions/limits)
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
