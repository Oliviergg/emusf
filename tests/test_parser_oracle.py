"""Test-oracle du parser Apex maison contre le parser ANTLR apex-parser.

Pour chaque fichier .cls/.trigger du repo, compare le verdict (accepté/rejeté)
du parser maison avec celui du parser de référence généré depuis la grammaire
apex-dev-tools/apex-parser. Toute divergence signale soit un trou de couverture
du parser maison (ANTLR accepte, EMUSF rejette), soit une sur-permissivité
(ANTLR rejette, EMUSF accepte).

Test optionnel : sauté si le parser ANTLR n'a pas été généré.
Génération : voir tools/grammar_eval/README.md.
"""

import glob
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GEN_DIR = os.path.join(REPO_ROOT, "tools", "grammar_eval", "gen")

try:
    import antlr4  # noqa: F401
    HAS_ANTLR_RUNTIME = True
except ImportError:
    HAS_ANTLR_RUNTIME = False

HAS_GEN = os.path.isfile(os.path.join(GEN_DIR, "ApexParser.py"))

pytestmark = pytest.mark.skipif(
    not (HAS_ANTLR_RUNTIME and HAS_GEN),
    reason="Parser ANTLR non disponible (voir tools/grammar_eval/README.md pour le générer)",
)

if HAS_ANTLR_RUNTIME and HAS_GEN:
    sys.path.insert(0, GEN_DIR)


def _corpus():
    files = sorted(
        glob.glob(os.path.join(REPO_ROOT, "**", "*.cls"), recursive=True)
        + glob.glob(os.path.join(REPO_ROOT, "**", "*.trigger"), recursive=True)
    )
    return [f for f in files if os.sep + "." not in f]


def _antlr_errors(text: str, is_trigger: bool) -> list:
    """Parse avec le parser de référence ; retourne la liste des erreurs de syntaxe."""
    from antlr4 import CommonTokenStream, InputStream
    from antlr4.error.ErrorListener import ErrorListener
    from ApexLexer import ApexLexer
    from ApexParser import ApexParser

    class Collect(ErrorListener):
        def __init__(self):
            self.errors = []

        def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
            self.errors.append(f"L{line}:{column} {msg}")

    errs = Collect()
    lexer = ApexLexer(InputStream(text))
    lexer.removeErrorListeners()
    lexer.addErrorListener(errs)
    parser = ApexParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(errs)
    if is_trigger:
        parser.triggerUnit()
    else:
        parser.compilationUnit()
    return errs.errors


def _emusf_error(text: str, is_trigger: bool):
    """Parse avec le parser maison ; retourne None si accepté, l'erreur sinon."""
    try:
        if is_trigger:
            from emusf.trigger_parser import TriggerParser
            TriggerParser().parse_trigger(text)
        else:
            from emusf.apex_parser import ApexParser as EmusfParser
            EmusfParser().parse_full_class(text)
        return None
    except Exception as e:  # le parser maison signale les rejets par exception
        return f"{type(e).__name__}: {e}"


@pytest.mark.parametrize(
    "path", _corpus(), ids=lambda p: os.path.relpath(p, REPO_ROOT)
)
def test_verdict_identique_au_parser_de_reference(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    is_trigger = path.endswith(".trigger")

    antlr_errors = _antlr_errors(text, is_trigger)
    emusf_error = _emusf_error(text, is_trigger)

    if antlr_errors and emusf_error is None:
        pytest.fail(
            "Sur-permissivité : le parser maison accepte un fichier que la "
            f"grammaire de référence rejette :\n  {antlr_errors[0]}"
        )
    if not antlr_errors and emusf_error is not None:
        pytest.fail(
            "Trou de couverture : le parser maison rejette un fichier que la "
            f"grammaire de référence accepte :\n  {emusf_error}"
        )
