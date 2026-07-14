"""Équivalence d'AST : frontend ANTLR (défaut) vs parser maison (legacy).

Pour chaque fichier du corpus, construit le ClassDef (ou le trigger) avec les
deux chaînes et vérifie que les AST sont identiques. Filet de sécurité de la
transition ; à retirer avec la chaîne legacy (étape 3 du TODO).
"""

import difflib
import glob
import os
import pprint

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

from emusf import antlr

pytestmark = pytest.mark.skipif(
    not antlr.is_available(),
    reason="Chaîne ANTLR indisponible (voir emusf/antlr/README.md)",
)


def _corpus(extension):
    files = sorted(glob.glob(os.path.join(REPO_ROOT, "**", "*." + extension),
                             recursive=True))
    # Exclut les répertoires cachés et les scénarios LIVE (fixtures
    # d'intégration, pas du corpus de parité parser legacy/ANTLR)
    return [f for f in files if os.sep + "." not in f
            and os.sep + "scenarios" + os.sep not in f]


def _assert_same(maison, antlr):
    if maison == antlr:
        return
    maison_repr = pprint.pformat(maison, width=100).splitlines()
    antlr_repr = pprint.pformat(antlr, width=100).splitlines()
    diff = "\n".join(difflib.unified_diff(
        maison_repr, antlr_repr, fromfile="parser maison", tofile="frontend antlr",
        lineterm="", n=2))
    pytest.fail("AST divergents :\n" + diff, pytrace=False)


@pytest.mark.parametrize(
    "path", _corpus("cls"), ids=lambda p: os.path.relpath(p, REPO_ROOT)
)
def test_class_ast_identique(path):
    with open(path, encoding="utf-8") as f:
        source = f.read()
    from emusf.apex_parser import ApexParser
    maison = ApexParser().parse_full_class_legacy(source)
    par_antlr = antlr.parse_full_class(source)
    _assert_same(maison, par_antlr)


@pytest.mark.parametrize(
    "path", _corpus("trigger"), ids=lambda p: os.path.relpath(p, REPO_ROOT)
)
def test_trigger_ast_identique(path):
    with open(path, encoding="utf-8") as f:
        source = f.read()
    from emusf.trigger_parser import TriggerParser
    maison = TriggerParser().parse_trigger_legacy(source)
    par_antlr = antlr.parse_trigger(source)
    _assert_same(maison, par_antlr)
