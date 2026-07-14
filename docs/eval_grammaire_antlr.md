# Évaluation : grammaire ANTLR `apex-dev-tools/apex-parser` pour EMUSF

> **Archive.** Ce rapport a motivé la migration, désormais terminée : la chaîne
> ANTLR est l'unique parser d'EMUSF (`emusf/antlr/`) et l'ancien parser maison
> (lexer/apex_parser/token_parser regex) a été supprimé. Document conservé pour
> la trace de la décision.

Date : 2026-07-14 — Évaluation pratique de la faisabilité de remplacer (ou d'adosser)
le lexer/parser maison d'EMUSF par un parser Python généré depuis la grammaire ANTLR
officielle de la communauté Apex.

## Contexte

- Grammaire évaluée : [`apex-dev-tools/apex-parser`](https://github.com/apex-dev-tools/apex-parser)
  v5.1.0 (ex-`nawforce/apex-parser`), utilisée en production par PMD, apex-ls et le
  Salesforce Extension Pack. Éprouvée sur des millions de lignes d'Apex réel.
- Fichiers : `antlr/BaseApexLexer.g4` (473 lignes) + `antlr/BaseApexParser.g4` (1296 lignes),
  avec des wrappers `npm/antlr/Apex{Lexer,Parser}.g4` qui activent `caseInsensitive = true`.
- Licence : **BSD-3-Clause** — compatible avec une réutilisation dans EMUSF.

## Résultats

### 1. Génération Python : sans friction

```bash
pip install antlr4-python3-runtime
java -jar antlr-4.13.2-complete.jar -Dlanguage=Python3 -visitor ApexLexer.g4 ApexParser.g4
```

- Zéro warning, zéro erreur à la génération (ANTLR 4.13.2).
- La grammaire ne contient **aucune action ni prédicat spécifique à une cible**
  (pas de code Java/JS embarqué) : elle est 100 % portable vers la cible Python.
- L'insensibilité à la casse d'Apex est gérée par l'option native ANTLR
  `caseInsensitive = true` — pas besoin de stream d'entrée custom.

### 2. Couverture syntaxique

**Corpus du repo** (44 fichiers `.cls` + `.trigger`) : 44/44 parsés sans erreur,
par les deux parsers (le corpus a été écrit pour EMUSF, donc attendu).

**Batterie de 23 constructions Apex avancées** (propriétés get/set, switch on sObject,
SOQL agrégats/ROLLUP/FOR UPDATE/TYPEOF, SOSL, safe navigation `?.`, null coalescing `??`,
merge/upsert-avec-champ/undelete, blocs d'init statiques, annotations paramétrées,
mots-clés contextuels utilisés comme identifiants, etc.) :

| Parser | Score | Remarques |
|---|---|---|
| ANTLR apex-parser | 23/23 | A de plus **rejeté correctement** 2 snippets volontairement invalides |
| Parser maison EMUSF | 21/23 | 2 échecs + accepte du code invalide |

Échecs du parser maison (`Exception: Classe non trouvée dans le source`) :
- `implements Database.Batchable<SObject>, Database.Stateful` (implements multiple avec type qualifié générique)
- `global inherited sharing class C` (modificateur `inherited sharing` + `webservice`)

Sur-permissivité du parser maison (accepte de l'Apex invalide que la grammaire rejette) :
- plusieurs types sObject dans un même `when` (`when Contact c, Lead l`)
- notation exponentielle dans les littéraux (`1.5e10`), qui n'existe pas en Apex

### 3. Performance (cible Python — la plus lente des cibles ANTLR)

Sur le plus gros fichier du repo (3,4 Ko, 87 lignes), en régime établi (ATN chaude) :

| | ms / parse |
|---|---|
| ANTLR Python | ~28 ms |
| Parser maison | ~6,5 ms |

Ratio ~×4. Négligeable pour un émulateur de dev/test (le parse est fait une fois
par classe ; l'exécution domine). Si un jour c'est un problème : cache d'AST sur
hash du source, ou cible ANTLR C++ via un binding.

### 4. Forme de l'arbre produit

ANTLR produit un *parse tree* (contexts par règle : `compilationUnit → typeDeclaration
→ classDeclaration → classBody …`), pas directement nos `ast_nodes`. L'intégration
consiste à écrire un **visitor** (`ApexParserVisitor` est généré) qui mappe les
contexts vers les dataclasses existantes de `emusf/ast_nodes.py`. C'est le vrai
coût du chantier : estimé à l'ordre de grandeur de l'actuel `apex_parser.py`
(~1 fois), mais c'est du code mécanique, et l'interpréteur reste inchangé.

Bonus notable : la grammaire embarque **SOQL et SOSL complets** (règles `query`,
`soslLiteral`…). Le visitor peut soit réutiliser ces sous-arbres, soit continuer à
déléguer au `soql_parser.py` maison à partir du texte brut — les deux approches
sont compatibles avec une migration incrémentale.

## Conclusion et stratégie recommandée

La grammaire est **techniquement validée** pour EMUSF : génération Python propre,
couverture syntaxique supérieure au parser maison, fidélité au vrai compilateur
(rejette l'invalide), licence permissive, performance suffisante.

Migration incrémentale proposée :

1. **Court terme — oracle de test** : ajouter un test pytest optionnel qui parse tout
   le corpus avec le parser ANTLR et signale les divergences avec le parser maison.
   Zéro risque, détecte immédiatement les trous de couverture.
2. **Moyen terme — visitor de mapping** : écrire `AntlrToAstVisitor` qui produit les
   `ast_nodes` existants ; basculer classe par classe derrière un flag.
3. **Long terme** : retirer `lexer.py`/`apex_parser.py`/`token_parser.py` une fois la
   parité atteinte ; garder le SOQL maison ou basculer sur les sous-arbres SOQL de la
   grammaire.

Artefacts d'évaluation (scripts + parser généré) : voir `tools/grammar_eval/`
pour reproduire (`README` inclus).
