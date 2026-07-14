"""Test-oracle du parser maison (legacy) contre la grammaire ANTLR de référence.

Pour chaque fichier .cls/.trigger du repo, compare le verdict (accepté/rejeté)
du parser maison avec celui de la chaîne ANTLR (emusf/antlr/, grammaire
apex-dev-tools/apex-parser). Toute divergence signale soit un trou de
couverture du parser maison (ANTLR accepte, legacy rejette), soit une
sur-permissivité (ANTLR rejette, legacy accepte).

Filet de sécurité de la transition ; à retirer avec la chaîne legacy
(étape 3 du TODO).
"""

import glob
import os

import pytest

from emusf import antlr
from emusf.antlr import builder as antlr_builder

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

pytestmark = pytest.mark.skipif(
    not antlr.is_available(),
    reason="Chaîne ANTLR indisponible (voir emusf/antlr/README.md)",
)


def _corpus():
    files = sorted(
        glob.glob(os.path.join(REPO_ROOT, "**", "*.cls"), recursive=True)
        + glob.glob(os.path.join(REPO_ROOT, "**", "*.trigger"), recursive=True)
    )
    return [f for f in files if os.sep + "." not in f]


def _antlr_error(text: str, is_trigger: bool):
    """Verdict de la grammaire de référence : None si accepté, l'erreur sinon."""
    entry = "triggerUnit" if is_trigger else "compilationUnit"
    try:
        antlr_builder._parse(text, entry)
        return None
    except antlr.ApexSyntaxError as e:
        return str(e)


def _legacy_error(text: str, is_trigger: bool):
    """Verdict du parser maison : None si accepté, l'erreur sinon."""
    try:
        if is_trigger:
            from emusf.trigger_parser import TriggerParser
            TriggerParser().parse_trigger_legacy(text)
        else:
            from emusf.apex_parser import ApexParser
            ApexParser().parse_full_class_legacy(text)
        return None
    except Exception as e:  # le parser maison signale les rejets par exception
        return "{}: {}".format(type(e).__name__, e)


@pytest.mark.parametrize(
    "path", _corpus(), ids=lambda p: os.path.relpath(p, REPO_ROOT)
)
def test_verdict_identique_au_parser_de_reference(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    is_trigger = path.endswith(".trigger")

    antlr_error = _antlr_error(text, is_trigger)
    legacy_error = _legacy_error(text, is_trigger)

    if antlr_error and legacy_error is None:
        pytest.fail(
            "Sur-permissivité : le parser maison accepte un fichier que la "
            "grammaire de référence rejette :\n  {}".format(antlr_error)
        )
    if not antlr_error and legacy_error is not None:
        pytest.fail(
            "Trou de couverture : le parser maison rejette un fichier que la "
            "grammaire de référence accepte :\n  {}".format(legacy_error)
        )
