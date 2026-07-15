"""Parser Apex → AST.

Façade autour de la chaîne ANTLR (emusf/antlr/) : parse le code Apex via la
grammaire apex-dev-tools/apex-parser et produit les nœuds ast_nodes.
"""

from __future__ import annotations

from .ast_nodes import Block, ClassDef


class ApexParser:
    """Parse du code Apex en AST (délègue à la chaîne ANTLR)."""

    def parse_class(self, source: str, method_name: str = "run") -> Block:
        """Parse une classe Apex et retourne le Block de la méthode demandée."""
        from . import antlr
        class_def = antlr.parse_full_class(source)
        method = class_def.methods.get(method_name)
        if method is None:
            raise Exception("Méthode '{}' non trouvée".format(method_name))
        return Block(statements=method.body)

    def parse_full_class(self, source: str) -> ClassDef:
        """Parse une classe Apex complète : constantes, méthodes, etc."""
        from . import antlr
        return antlr.parse_full_class(source)
