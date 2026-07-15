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

ÉVOLUTIONS INTERPRÉTEUR — priorisées d'après les tests apex-recipes (apex_tests/run_recipes_tests.py, clone
trailheadapps/apex-recipes, EMUSF_RECIPES_ROOT). Rejouer le runner après chaque item pour mesurer le gain.
Historique : baseline 2026-07-15 = 74/297 (24%) MAIS System.Assert était un no-op (PASS non fiables) ;
baseline honnête après P3 = 55/297 (18%) ; après la passe P1-P10 du 2026-07-15 = 107/321 (33%).

[FAIT 2026-07-15] P1 casse insensible (builtins transformés meth.lower(), méthodes/classes user via
   _method_lookup/_ci_key, variables, champs) · P2 surcharges par arité+type (_arg_type_score, fin des
   52 RecursionError doInsert(SObject)→doInsert(List)) · P3 System.Assert → AssertException + comptage
   (les runners classent FAIL vs ERROR) · P4 sObj.getSObjectType/getPopulatedFieldsAsMap/clone ·
   P5 constantes de trigger fault-tolérantes + contexte Trigger complet (isExecuting, operationType,
   newMap/oldMap) propagé dans les scopes de méthodes · P6 Test.createStub/StubProvider ·
   P7 initialisateurs de champs d'instance évalués à la construction (mock à queue OK) + super()
   implicite + résolution de this.method() · P9 Database.executeBatch/getQueryLocator/queryWithBinds/
   countQuery/upsert · P10 partiel (ListException hors bornes, List.sort(Comparator), tokens hashables
   ApexToken) · P12 partiel (enums top-level+inner → constantes-chaînes, switch sur enum par nom,
   commentaires dans SOQL, bind :UserInfo.getUsername()) · describe fields.getMap() depuis org._tables.
   Piège perf noté : _invoke_method ré-évaluait les initialisateurs d'instance à CHAQUE appel
   (travail exponentiel) — désormais exclus des boucles de constantes.

[FAIT 2026-07-15 soir] P-A — System.runAs + FLS granulaire (116/313 = 37%) :
   nœud AST RunAs + builder (les blocs runAs ne sont plus ignorés) ; contexte user courant
   (_current_user/_current_profile) ; profils seedés par le runner + PermissionSet/Assignment ;
   grants par objet/champ parsés des .permissionset-meta.xml (sfdx_loader.parse_permission_set,
   org.permset_grants) ; describe (SObjectType/SObjectField/describeSObjects) et
   Security.stripInaccessible granulaires (NoAccessException 'No access to entity', strip récursif
   des enfants de sous-requête, champs composés Shipping*→ShippingAddress) ; UserInfo reflète runAs.
   Au passage : Id implicite dans toute requête SOQL (sauf semi-join IN), sous-requêtes enfant OK
   même sans Id explicite + forme qualifiée (FROM Account.Contacts), LIKE→ILIKE (insensible casse),
   SOQL inline exécuté en argument de méthode (stripInaccessible(..., [SELECT...])), types de colonnes
   inférés à l'auto-création (BIGINT/BOOLEAN/DOUBLE au lieu de tout-TEXT) + PgTestOrg.reset_schema(),
   getSObjects('Children') et List.getSObjectType(), JSON.deserialize marque _sobject_type,
   erreurs de @testSetup remontées (status SETUP: …), fix détection @isTest de classe.
   StripInaccessible 1/11→9/10, Safely 2/16→8/16, SOQLRecipes 0→6/19, CustomRestEndpoint débloqué.

Reste à faire (état au run 116/313) :

P-A' — reliquat sécurité : accès à un champ non requêté/strippé devrait lever SObjectException
   (les dicts rendent null) — 2-3 tests 'Negative' en dépendent ; RestContext/RestRequest pour
   CustomRestEndpointRecipes (1/22, les 21 restants sont des sémantiques REST + QueryException).

P-B — DMLException/allOrNone fidèles (~12 méthodes DMLRecipes) : Database.insert(rec, false) doit
   produire des SaveResult d'échec (pas d'exception), insert d'un doublon/champ requis manquant doit
   lever DmlException ('Expected CustomDmlException', 'Expected DML exception').

P-C — addError() sur SObject en trigger before → bloque le DML de la ligne (AccountTriggerHandler
   testBeforeUpdateWithAddError) ; tasks créées par triggers after (Safely.doInsert dans le handler).

P-D — Platform Cache session/org (PlatformCacheRecipes 6/12, OrgShape) : Cache.Session/Org get/put/
   remove/contains + partitions par défaut.

P-E — méthodes valeur manquantes vues au run : String.name()/toString() (EncryptionRecipesTest 0/10 —
   enum .name()), List.getSObjectType(), Crypto.decrypt (casse OK mais absent), page.getRecords()
   (IterableApiClient), 'UPDATE sans Id' après upsert typecast.

P11 — enregistrements customMetadata (.md-meta.xml → lignes __mdt requêtables) : MetadataTriggerHandler
   /Service et CustomMetadataRecipes requêtent Metadata_Driven_Trigger__mdt (tables absentes du schéma).

P13 — DataWeave in Apex (12 méthodes, niche) : DataWeave.Script.createScript(...).execute(...) ;
   faible priorité (CSV/JSON couvert autrement par JSON.deserialize).

Log_Tests : 2 RecursionError restants (Log.get() singleton + surcharges publish sur types proches) —
   creuser _arg_type_score sur LogMessage vs String.

DONE
-- soql merite son propre lexer et resolver
