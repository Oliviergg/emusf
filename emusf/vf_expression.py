"""Résolution des expressions Visualforce {!...}.

Délègue l'évaluation au FormulaEngine unifié, avec un resolver
spécifique au contexte Visualforce (loop_vars, instance_vars, record).
"""

from __future__ import annotations

import re

from .formula_engine import FormulaEngine, FormulaError


def resolve(expr: str, record: dict | None, instance_vars: dict,
            loop_vars: dict, org=None) -> object:
    """Résout une expression VF.

    Supporte :
      - Chemins pointés : Account.Name, wrp.isSelected
      - Fonctions : AND(...), OR(...), NOT(...), IF(c,t,f), ISNULL(x), LEN(x)
      - Comparaisons : a == b, a != b, a > b, a < b
      - Littéraux : null, true, false, 'string', 123
      - Propriété .size sur les listes

    Ordre de résolution des noms :
      1. loop_vars
      2. instance_vars
      3. record (via nom du SObject ou accès direct)
    """
    expr = expr.strip()

    def vf_resolver(ref: str):
        """Résout une référence dans le contexte VF."""
        parts = _split_dot_path(ref)
        if not parts:
            return None

        name = parts[0]
        rest = parts[1:]

        # Résolution du premier segment
        val = _resolve_name(name, record, instance_vars, loop_vars)

        # Parcourir le reste du chemin
        return _walk_with_methods(val, rest)

    engine = FormulaEngine(vf_resolver)
    try:
        return engine.evaluate(expr)
    except FormulaError:
        # Fallback : tenter comme une référence simple (chemin pointé)
        return vf_resolver(expr)


def _resolve_name(name, record, instance_vars, loop_vars):
    """Résout un nom simple dans les différents scopes."""
    if name in loop_vars:
        return loop_vars[name]
    if name in instance_vars:
        return instance_vars[name]
    if record:
        sobject_type = record.get("_sobject_type", "")
        if name.lower() == sobject_type.lower():
            return record
        if name in record:
            return record[name]
        # Case-insensitive
        for k, v in record.items():
            if k.lower() == name.lower():
                return v
    return None


def _walk_with_methods(obj, parts: list[str]):
    """Parcourt un chemin avec support de .size, .length, etc."""
    current = obj
    for part in parts:
        if current is None:
            return None
        # Méthodes / propriétés sur les types Python
        if part.lower() == "size" and isinstance(current, (list, dict)):
            current = len(current)
        elif part.lower() == "length" and isinstance(current, str):
            current = len(current)
        elif isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                lower = part.lower()
                found = False
                for k, v in current.items():
                    if k.lower() == lower:
                        current = v
                        found = True
                        break
                if not found:
                    return None
        else:
            current = getattr(current, part, None)
    return current


def _split_dot_path(expr: str) -> list[str]:
    """Split un chemin pointé en respectant les parenthèses."""
    parts = []
    current = ""
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "." and depth == 0:
            if current:
                parts.append(current)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def resolve_text(text: str, record: dict | None, instance_vars: dict,
                 loop_vars: dict, org=None) -> str:
    """Résout toutes les expressions {!...} dans une chaîne de texte."""
    def _replacer(m):
        val = resolve(m.group(1), record, instance_vars, loop_vars, org)
        return str(val) if val is not None else ""
    return re.sub(r'\{!([^}]+)\}', _replacer, text)
