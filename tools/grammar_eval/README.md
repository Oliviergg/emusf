# Évaluation de la grammaire ANTLR apex-parser

Scripts d'évaluation de la grammaire [`apex-dev-tools/apex-parser`](https://github.com/apex-dev-tools/apex-parser)
(cible Python) contre le parser maison d'EMUSF. Résultats et conclusions :
`docs/eval_grammaire_antlr.md`.

## Reproduire

```bash
pip install antlr4-python3-runtime

# Récupérer la grammaire (v5.1.0, licence BSD-3-Clause)
curl -sSfLO https://raw.githubusercontent.com/apex-dev-tools/apex-parser/main/antlr/BaseApexLexer.g4
curl -sSfLO https://raw.githubusercontent.com/apex-dev-tools/apex-parser/main/antlr/BaseApexParser.g4
curl -sSfLO https://raw.githubusercontent.com/apex-dev-tools/apex-parser/main/npm/antlr/ApexLexer.g4
curl -sSfLO https://raw.githubusercontent.com/apex-dev-tools/apex-parser/main/npm/antlr/ApexParser.g4

# Générer le parser Python (nécessite Java 11+)
curl -sSfL -o antlr.jar https://repo1.maven.org/maven2/org/antlr/antlr4/4.13.2/antlr4-4.13.2-complete.jar
java -jar antlr.jar -Dlanguage=Python3 -o gen -visitor ApexLexer.g4 ApexParser.g4

# Lancer les évaluations
python3 eval_grammar.py   # parse tout le corpus .cls/.trigger du repo avec les 2 parsers
python3 eval_tricky.py    # batterie de constructions Apex avancées
```

Le répertoire `gen/` (parser généré, ~2 Mo) n'est pas versionné — le régénérer
avec les commandes ci-dessus.
