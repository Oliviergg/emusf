"""Chaîne de parsing ANTLR — frontend par défaut d'EMUSF.

- grammar/    : grammaire apex-dev-tools/apex-parser (BSD-3-Clause) vendorée
- generated/  : parser Python généré par ANTLR, committé (pas de Java requis)
- builder.py  : mapping parse tree → ast_nodes d'EMUSF

Voir README.md pour la provenance et la régénération.
"""

from .builder import (  # noqa: F401
    ApexSyntaxError,
    is_available,
    parse_full_class,
    parse_trigger,
)
