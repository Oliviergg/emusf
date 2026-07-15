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

[FAIT 2026-07-15 soir] P-B DMLRecipes 40/40 + P-E Encryption 10/10 (155/313 = 49%) :
   statements upsert/undelete (nœuds DmlUpsert/DmlUndelete, ils étaient ignorés par le builder) ;
   corbeille en mémoire dans PgTestOrg (delete stash → undelete) ; validation des champs requis
   standard (REQUIRED_FIELD_MISSING si champ présent mais nil/'' — tolérant si absent) ;
   update/delete d'un Id inexistant → INVALID_CROSS_REFERENCE_KEY/ENTITY_IS_DELETED (rowcount) ;
   Database.insert/update/delete/upsert/undelete avec vrai allOrNone (SaveResult d'échec + erreurs,
   atomicité par pré-validation) ; SaveResult/UpsertResult/DeleteResult.isSuccess/getId/getErrors
   + Database.Error.getMessage/getStatusCode ; AssertException incapturable par les try/catch Apex
   (comme en vrai) ; Crypto complet (decrypt, encrypt/decryptWithManagedIV, sign/verify RSA via DER,
   verifyHMAC, HMAC-SHA384/512) ; EncodingUtil.base64Decode retourne un Blob (il retournait une
   chaîne décodée UTF-8, corrompant le binaire !) + urlDecode ; String.name()/toString() (enums).

[FAIT 2026-07-15 soir] Bloc trigger-framework (182/313 = 58%, AccountTriggerHandler 9/9) :
   variables statiques partagées entre interpréteurs (org._active_interp : le callback de trigger
   hérite des ClassName.champ de l'appelant et les repropage) ; _invoke_instance_method et les
   constructeurs persistent les écritures de statiques (seul _invoke_method le faisait) ;
   affectation Classe.champ = v (FieldSet sur nom de classe) et résolution lecture/écriture des
   statiques par suffixe (inner class → statique de l'englobante) ; Trigger.new null en delete /
   Trigger.old null en insert (comme SF) + Trigger.old porte les enregistrements complets ;
   addError() bloque le DML (FIELD_CUSTOM_VALIDATION_EXCEPTION) ; ALL ROWS interroge la corbeille
   (IsDeleted) ; X[] var = [SELECT…] exécute le SOQL (déclarations tableau) ; this.champ++ (builder
   l'ignorait) ; System.debug(LoggingLevel, msg) affiche le message ; Database.* devine le type
   des records sans marqueur.

[FAIT 2026-07-15 soir] P-G reliquat trigger-framework (192/313 = 61%, MetadataTriggerHandler 7/8,
   TriggerHandler_Test 12/13) : statiques adressables par nom court dans les appels de méthode et
   les affectations (avec priorité aux champs d'instance — une inversion a causé une régression
   182→132, corrigée) ; VarDecl synchronise la statique (le builder produit des VarDecl pour
   `x = new List<…>()`) ; constantes de la classe de test préchargées par le runner + fallback
   d'évaluation paresseuse ; cast (DateTime) obj lève TypeException avec le type runtime dans le
   message (pattern TestHelper.getUnknownObjectType) ; ALTER TABLE d'auto-extension en autocommit
   (un rollback de validation DML annulait le DDL déjà mémorisé dans _tables → colonnes fantômes,
   c'était LA contamination inter-classes du run complet).
   Piège repro : repro_one.py jette le stdout des tests (DiscardIO) — déboguer via stderr.

Reste à faire (état au run 192/313) :

P-G — reliquat trigger-framework : bypass API (Set statique contains), maxLoopCount (exception au
   dépassement), message d'exception user au getMessage(), MetadataTriggerHandler activeHandler
   (stub + custom metadata), PlatformEventRecipesTriggerHandler.

P-A' — reliquat sécurité : accès à un champ non requêté/strippé devrait lever SObjectException
   (les dicts rendent null) — 2-3 tests 'Negative' en dépendent ; RestContext/RestRequest pour
   CustomRestEndpointRecipes (0/22, sémantiques REST + QueryException).
P-F — gros blocs restants par thème : AccountTriggerHandler 1/9 + TriggerHandler_Test 2/13
   (addError bloquant, compteurs statiques de handler, tasks créées par triggers after) ;
   Queueable* 0/4 (chaînage + finalizers) ; OrgShape 0/6 + PlatformCache* 4/13 (Cache.Session/Org) ;
   DataWeave 0/12 (niche) ; SOSL 0/2 ; CollectionUtils 0/3 (récursions surcharges Map) ;
   Log_Tests 0/2 (récursion Log.get singleton).

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
