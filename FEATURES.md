# EMUSF - Fonctionnalités supportées

## Langage Apex

### Types de données
- **Primitifs** : `String`, `Integer`, `Decimal`, `Double`, `Boolean`, `Date`, `DateTime`, `Blob`
- **Collections** : `List<T>`, `Set<T>`, `Map<K,V>`, `T[]` (tableaux)
- **SObjects** : Account, Contact, Opportunity, Case, Lead, Task, Event, User, et custom objects
- **Exceptions** personnalisées avec héritage
- **Cast de type** : `(Type) expr`

### Structures de contrôle
- `if` / `else if` / `else`
- `for` classique : `for (init; condition; update) { }`
- `for-each` : `for (Type var : collection) { }`
- `while` / `do-while`
- `switch on` avec `when` et `when else`
- Opérateur ternaire : `condition ? a : b`
- `break`, `continue`, `return`
- `try` / `catch` / `throw`

### Classes et méthodes
- Déclaration de classes avec `public`, `private`, `global`
- `with sharing` / `without sharing`
- `virtual`, `abstract`, `override`
- Héritage (`extends`) et interfaces (`implements`)
- Classes internes (inner classes)
- Champs statiques et d'instance, `final`
- Blocs d'initialisation statiques (`static { }`)
- Constructeurs (avec surcharge)
- Surcharge de méthodes (method overloading)
- Propriétés `{ get; set; }`

### Opérateurs
- Arithmétiques : `+`, `-`, `*`, `/`
- Comparaison : `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logiques : `&&`, `||`, `!`
- `instanceof`
- Incrémentation/décrémentation : `++`, `--`

---

## Fonctions Apex supportées

### System
| Méthode | Description |
|---------|-------------|
| `System.debug(msg)` | Affiche un message de debug |
| `System.assert(condition, [msg])` | Assertion booléenne |
| `System.assertEquals(expected, actual, [msg])` | Assertion d'égalité |
| `System.assertNotEquals(expected, actual, [msg])` | Assertion d'inégalité |
| `System.currentTimeMillis()` | Timestamp actuel en millisecondes |
| `System.today()` | Date du jour |
| `System.now()` | DateTime actuel |
| `System.schedule(jobName, cron, cls)` | Planifier un job |
| `System.enqueueJob(queueable)` | Mettre un job en file |
| `System.abortJob(jobId)` | Annuler un job |
| `System.Label.*` | Accès aux custom labels (retourne chaîne vide) |

### String (méthodes statiques)
| Méthode | Description |
|---------|-------------|
| `String.isBlank(str)` | Vérifie si null/vide/espaces |
| `String.isNotBlank(str)` | Inverse de isBlank |
| `String.isEmpty(str)` | Vérifie si vide |
| `String.valueOf(obj)` | Conversion en String |
| `String.join(list, separator)` | Joindre une liste |
| `String.format(template, args)` | Formatage de chaîne |
| `String.escapeSingleQuotes(str)` | Échappe les apostrophes |

### String (méthodes d'instance)
| Méthode | Description |
|---------|-------------|
| `length()` | Longueur de la chaîne |
| `contains(substring)` | Contient une sous-chaîne |
| `startsWith(prefix)` | Commence par |
| `endsWith(suffix)` | Se termine par |
| `toLowerCase()` | En minuscules |
| `toUpperCase()` | En majuscules |
| `trim()` | Supprime les espaces |
| `substring(start, [end])` | Extraction |
| `indexOf(substring)` | Position d'une sous-chaîne |
| `replace(old, new)` | Remplacement |
| `replaceAll(regex, replacement)` | Remplacement par regex |
| `split(delimiter)` | Découpage |
| `left(n)` | N caractères à gauche |
| `right(n)` | N caractères à droite |
| `removeStart(prefix)` | Supprime un préfixe |
| `removeEnd(suffix)` | Supprime un suffixe |
| `leftPad(length, [char])` | Padding à gauche |
| `equals(str)` | Égalité stricte |
| `equalsIgnoreCase(str)` | Égalité sans casse |
| `charAt(index)` | Caractère à un index |
| `repeat(count)` | Répétition |
| `abbreviate(maxWidth)` | Abréviation avec `...` |
| `capitalize()` | Première lettre en majuscule |
| `normalizeSpace()` | Normalise les espaces |
| `countMatches(substring)` | Compte les occurrences |
| `size()` | Alias de length() |
| `escapeSingleQuotes()` | Échappe les apostrophes |

### List
| Méthode | Description |
|---------|-------------|
| `add(element)` | Ajouter un élément |
| `addAll(collection)` | Ajouter tous les éléments |
| `size()` | Nombre d'éléments |
| `isEmpty()` | Vide ou non |
| `get(index)` | Élément à un index |
| `contains(element)` | Vérifie la présence |
| `remove(index)` | Supprimer par index |
| `clear()` | Vider la liste |
| `sort()` | Trier |

### Set
| Méthode | Description |
|---------|-------------|
| `add(element)` | Ajouter un élément |
| `addAll(collection)` | Ajouter tous les éléments |
| `contains(element)` | Vérifie la présence |
| `size()` | Nombre d'éléments |
| `isEmpty()` | Vide ou non |
| `remove(element)` | Supprimer un élément |

### Map
| Méthode | Description |
|---------|-------------|
| `put(key, value)` | Ajouter/mettre à jour |
| `get(key)` | Obtenir une valeur |
| `containsKey(key)` | Vérifie la clé |
| `keySet()` | Ensemble des clés |
| `values()` | Liste des valeurs |
| `size()` | Nombre d'entrées |
| `isEmpty()` | Vide ou non |
| `remove(key)` | Supprimer par clé |
| `clone()` | Cloner la map |

### Math
| Méthode | Description |
|---------|-------------|
| `Math.round(value)` | Arrondi |
| `Math.abs(value)` | Valeur absolue |
| `Math.max(a, b)` | Maximum |
| `Math.min(a, b)` | Minimum |
| `Math.floor(value)` | Arrondi inférieur |
| `Math.ceil(value)` | Arrondi supérieur |

### Date
| Méthode | Description |
|---------|-------------|
| `Date.newInstance(y, m, d)` | Créer une date |
| `Date.today()` | Date du jour |
| `year()`, `month()`, `day()` | Composants |
| `addDays(n)`, `addMonths(n)` | Ajout de jours/mois |
| `format()` | Formatage texte |

### DateTime
| Méthode | Description |
|---------|-------------|
| `DateTime.newInstance(y, m, d, [h, mn, s])` | Créer un DateTime |
| `DateTime.now()` | DateTime actuel |
| `DateTime.valueOf(timestamp)` | Depuis un timestamp |
| `date()` | Extraire la date |
| `year()`, `month()`, `day()` | Composants date |
| `hour()`, `minute()`, `second()` | Composants heure |
| `addDays(n)` | Ajout de jours |
| `format()` | Formatage texte |
| `getTime()` | Timestamp en ms |

### Integer
| Méthode | Description |
|---------|-------------|
| `Integer.valueOf(value)` | Conversion en entier |

### JSON
| Méthode | Description |
|---------|-------------|
| `JSON.serialize(obj)` | Sérialiser en JSON |
| `JSON.serializePretty(obj)` | Sérialiser formaté |
| `JSON.deserialize(str, type)` | Désérialiser typé |
| `JSON.deserializeUntyped(str)` | Désérialiser non typé |

### Database
| Méthode | Description |
|---------|-------------|
| `Database.insert(records)` | Insert avec SaveResult |
| `Database.update(records)` | Update avec SaveResult |
| `Database.delete(records)` | Delete avec SaveResult |
| `Database.query(soqlString)` | Requête SOQL dynamique |

### HTTP (Callouts)
| Classe / Méthode | Description |
|---------|-------------|
| `Http.send(request)` | Exécuter un appel HTTP |
| `HttpRequest.setEndpoint(url)` | Définir l'URL |
| `HttpRequest.setMethod(method)` | GET, POST, PUT, DELETE, PATCH |
| `HttpRequest.setBody(body)` | Corps de la requête |
| `HttpRequest.setTimeout(ms)` | Timeout |
| `HttpRequest.setHeader(name, value)` | En-tête |
| `HttpRequest.getEndpoint/Method/Body/Header()` | Getters |
| `HttpResponse.getStatusCode()` | Code HTTP |
| `HttpResponse.getStatus()` | Texte du statut |
| `HttpResponse.getBody()` | Corps de la réponse |
| `HttpResponse.getHeader(name)` | En-tête de réponse |
| `HttpResponse.setStatusCode/Body/Header()` | Setters (pour les mocks) |

### Pattern & Matcher (Regex)
| Méthode | Description |
|---------|-------------|
| `Pattern.compile(regex)` | Compiler un pattern |
| `pattern.matcher(text)` | Créer un matcher |
| `matcher.find()` | Trouver la correspondance suivante |
| `matcher.matches()` | Correspondance complète |
| `matcher.group([index])` | Groupe capturé |

### Crypto & Encoding
| Méthode | Description |
|---------|-------------|
| `EncodingUtil.base64Encode(value)` | Encodage Base64 |
| `EncodingUtil.base64Decode(str)` | Décodage Base64 |
| `EncodingUtil.urlEncode(value)` | Encodage URL |
| `EncodingUtil.convertToHex(bytes)` | Bytes vers hexadécimal |
| `EncodingUtil.convertFromHex(hex)` | Hexadécimal vers bytes |
| `Crypto.encrypt(algo, key, iv, data)` | Chiffrement AES |
| `Crypto.generateAesKey(bits)` | Génération de clé AES |
| `Crypto.generateMac(algo, data, key)` | HMAC |
| `Crypto.generateDigest(algo, data)` | Hash |
| `Crypto.getRandomInteger()` | Entier aléatoire |

### Autres
| Méthode | Description |
|---------|-------------|
| `UUID.randomUUID()` | Générer un UUID |
| `URL.getOrgDomainUrl()` | URL du domaine org |
| `Blob.valueOf(value)` | Conversion en Blob |
| `Type.forName(className)` | Réflexion - obtenir un type |
| `Type.newInstance()` | Instanciation par réflexion |
| `EventBus.publish(event)` | Publication d'événement (no-op) |
| `ApexPages.addMessage(msg)` | Message de page VF |

---

## DML

- `insert` / `Database.insert()` - insertion de records
- `update` / `Database.update()` - mise à jour de records
- `delete` / `Database.delete()` - suppression de records
- Génération automatique d'IDs Salesforce réalistes (18 caractères, préfixes par objet)
- `SaveResult` avec `isSuccess()`, `getId()`, `getErrors()`

---

## SOQL

### Clauses supportées
- `SELECT` avec alias de champs
- `FROM`
- `WHERE` avec `AND`, `OR`, `NOT`
- `GROUP BY`
- `HAVING`
- `ORDER BY` avec `ASC`/`DESC` et `NULLS FIRST`/`NULLS LAST`
- `LIMIT`

### Opérateurs WHERE
- Comparaison : `=`, `!=`, `<`, `>`, `<=`, `>=`, `LIKE`
- Ensemble : `IN`, `NOT IN`
- Null : `= NULL`, `!= NULL`

### Fonctions d'agrégation
- `COUNT()`, `COUNT(field)`
- `SUM(field)`
- `AVG(field)`
- `MIN(field)`
- `MAX(field)`

### Fonctionnalités avancées
- **Sous-requêtes** : `SELECT (SELECT fields FROM childRelation) FROM parent`
- **Relations parent** : `Account.Name`, `Contact.Account.Name` (traversée `__r`)
- **Date literals** : `TODAY`, `YESTERDAY`, `NEXT_N_DAYS`, `THIS_MONTH`, etc.
- **Variables liées** : `:variableName`, `:className.fieldName`

---

## Triggers

### Événements supportés
- `before insert`, `before update`, `before delete`
- `after insert`, `after update`, `after delete`

### Variables de contexte
- `Trigger.new` - liste des nouveaux records
- `Trigger.old` - liste des anciens records (update/delete)

### Fonctionnement
- Déclaration multi-événements : `trigger Name on SObject (before insert, after insert)`
- Exécution complète du corps Apex dans le trigger
- Chaînage : before → DML → after

---

## Flows (Salesforce Flows)

### Types de flow
- `AutoLaunchedFlow` - flows automatiques/headless
- `Flow` - screen flows
- `Workflow` - processus workflow

### Éléments supportés
| Élément | Description |
|---------|-------------|
| `FlowStart` | Point d'entrée (record-triggered, scheduled, screen) |
| `FlowAssignment` | Affectation avec opérateurs (Assign, Add, Subtract) |
| `FlowDecision` | Branchement conditionnel avec règles |
| `FlowRecordLookup` | Requête SOQL |
| `FlowRecordCreate` | Insert DML |
| `FlowRecordUpdate` | Update DML |
| `FlowRecordDelete` | Delete DML |
| `FlowLoop` | Itération sur collections |

### Ressources
- `FlowVariable` - String, Number, Date, DateTime, Boolean, SObject, Currency
- `FlowFormula` - Expressions calculées (NOW(), TODAY(), etc.)
- `FlowConstant` - Constantes
- `FlowTextTemplate` - Templates avec merge fields

### Déclencheurs
- `Create`, `Update`, `CreateAndUpdate`, `Delete`
- `RecordBeforeSave`, `RecordAfterSave`

---

## Infrastructure de test

### Assertions
- `System.assert(condition, [msg])`
- `System.assertEquals(expected, actual, [msg])`
- `System.assertNotEquals(expected, actual, [msg])`

### Contexte de test
| Méthode | Description |
|---------|-------------|
| `Test.isRunningTest()` | Détecte le contexte de test |
| `Test.setMock(type, mock)` | Mock des callouts HTTP |
| `Test.startTest()` / `Test.stopTest()` | Délimiter le test |
| `Test.setCreatedDate(record, dt)` | Fixer la date de création |
| `Test.loadData(sObjectType, csv)` | Charger des données de test |

### Org de test (PgTestOrg)
- Isolation par `SAVEPOINT`/`ROLLBACK`
- Troncature entre les tests
- Déclenchement automatique des triggers sur DML
