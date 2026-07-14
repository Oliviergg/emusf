# Chaîne de parsing ANTLR

Frontend de parsing par défaut d'EMUSF : la grammaire Apex de référence
[`apex-dev-tools/apex-parser`](https://github.com/apex-dev-tools/apex-parser)
(v5.1.0, licence BSD-3-Clause — voir `grammar/LICENSE`), compilée vers Python
par ANTLR, puis mappée vers les `ast_nodes` d'EMUSF par `builder.py`.

## Contenu

- `grammar/` — les fichiers `.g4` vendorés depuis apex-dev-tools/apex-parser,
  avec leur licence. `ApexLexer.g4`/`ApexParser.g4` sont des wrappers qui
  activent `caseInsensitive = true` et importent les grammaires de base.
- `generated/` — le parser Python généré par ANTLR 4.13.2, **committé** pour
  que l'utilisation d'EMUSF ne requière pas Java. Seul prérequis à
  l'exécution : `antlr4-python3-runtime` (déclaré dans `pyproject.toml`),
  dont la version doit correspondre à celle du générateur (4.13.x).
- `builder.py` — le visitor qui produit les `ast_nodes`. Il reproduit
  volontairement certains quirks du parser maison historique (documentés dans
  sa docstring) pour garantir des AST identiques pendant la transition.

## Bascule de frontend

Le frontend ANTLR est le défaut. `EMUSF_FRONTEND=legacy` réactive l'ancien
parser maison (`emusf/lexer.py` + `emusf/apex_parser.py`), conservé le temps
du rodage. Les tests croisés `tests/test_ast_equivalence.py` et
`tests/test_parser_oracle.py` vérifient l'accord entre les deux chaînes.

## Régénérer le parser

Après mise à jour de la grammaire (nécessite Java 11+) :

```bash
cd emusf/antlr/grammar
curl -sSfL -o /tmp/antlr.jar https://repo1.maven.org/maven2/org/antlr/antlr4/4.13.2/antlr4-4.13.2-complete.jar
java -jar /tmp/antlr.jar -Dlanguage=Python3 -visitor -o ../generated ApexLexer.g4 ApexParser.g4
# Ne committer que ApexLexer.py, ApexParser.py, ApexParserVisitor.py
rm -f ../generated/*.interp ../generated/*.tokens ../generated/ApexParserListener.py
```

Pour mettre à jour la grammaire elle-même :

```bash
for f in BaseApexLexer.g4 BaseApexParser.g4; do
  curl -sSfLO https://raw.githubusercontent.com/apex-dev-tools/apex-parser/main/antlr/$f
done
for f in ApexLexer.g4 ApexParser.g4; do
  curl -sSfLO https://raw.githubusercontent.com/apex-dev-tools/apex-parser/main/npm/antlr/$f
done
```
