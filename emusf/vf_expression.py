"""Résolution des expressions Visualforce {!...}."""

from __future__ import annotations

import re


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
    return _eval_expr(expr, record, instance_vars, loop_vars, org)


def _eval_expr(expr: str, record, instance_vars, loop_vars, org) -> object:
    """Évalue une expression VF complète."""
    expr = expr.strip()

    # Littéraux
    if expr.lower() == "null":
        return None
    if expr.lower() == "true":
        return True
    if expr.lower() == "false":
        return False
    if (expr.startswith("'") and expr.endswith("'")) or \
       (expr.startswith('"') and expr.endswith('"')):
        return expr[1:-1]
    # Nombre
    m = re.match(r'^-?\d+(\.\d+)?$', expr)
    if m:
        return float(expr) if "." in expr else int(expr)

    # Fonctions VF : AND(...), OR(...), NOT(...), IF(c,t,f), ISNULL(x)
    func_match = re.match(r'^(\w+)\s*\(', expr)
    if func_match:
        func_name = func_match.group(1).upper()
        inner = _extract_parens(expr, func_match.start(1) + len(func_match.group(1)))
        if inner is not None:
            args = _split_args(inner)
            ev = lambda e: _eval_expr(e, record, instance_vars, loop_vars, org)

            if func_name == "AND":
                return all(ev(a) for a in args)
            if func_name == "OR":
                return any(ev(a) for a in args)
            if func_name == "NOT":
                return not ev(args[0]) if args else False
            if func_name == "IF":
                if len(args) >= 3:
                    return ev(args[1]) if ev(args[0]) else ev(args[2])
            if func_name == "ISNULL" or func_name == "ISBLANK":
                val = ev(args[0]) if args else None
                return val is None or val == ""
            if func_name == "LEN":
                val = ev(args[0]) if args else ""
                return len(str(val)) if val else 0
            if func_name == "TEXT":
                val = ev(args[0]) if args else None
                return str(val) if val is not None else ""
            if func_name == "URLFOR":
                # Simplifié : retourne le premier argument évalué
                return ev(args[0]) if args else ""
            # Fonction inconnue : essayer comme un nom de variable
            # (ex: {!listWrapper.size > 0} — pas une fonction)

    # Opérateurs de comparaison (hors fonctions)
    # Chercher d'abord avec espaces, puis sans
    for op in (" != ", " == ", " <> ", " >= ", " <= ", " > ", " < ",
               "!=", "==", "<>", ">=", "<="):
        idx = _find_op_outside_parens(expr, op)
        if idx >= 0:
            left = _eval_expr(expr[:idx], record, instance_vars, loop_vars, org)
            right = _eval_expr(expr[idx + len(op):], record, instance_vars, loop_vars, org)
            if op.strip() in ("==", "="):
                return _eq(left, right)
            if op.strip() in ("!=", "<>"):
                return not _eq(left, right)
            if op.strip() == ">":
                return _num(left) > _num(right)
            if op.strip() == "<":
                return _num(left) < _num(right)
            if op.strip() == ">=":
                return _num(left) >= _num(right)
            if op.strip() == "<=":
                return _num(left) <= _num(right)

    # Opérateur logique &&, ||
    for op in (" && ", " || "):
        idx = _find_op_outside_parens(expr, op)
        if idx >= 0:
            left = _eval_expr(expr[:idx], record, instance_vars, loop_vars, org)
            right = _eval_expr(expr[idx + len(op):], record, instance_vars, loop_vars, org)
            if op.strip() == "&&":
                return bool(left) and bool(right)
            return bool(left) or bool(right)

    # Négation : !expr
    if expr.startswith("!"):
        return not _eval_expr(expr[1:], record, instance_vars, loop_vars, org)

    # Chemin pointé avec .size, .length etc.
    parts = _split_dot_path(expr)

    # Résolution du premier segment
    name = parts[0]
    rest = parts[1:]

    val = _resolve_name(name, record, instance_vars, loop_vars)

    # Parcourir le reste du chemin
    return _walk_with_methods(val, rest)


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


def _extract_parens(expr: str, start: int) -> str | None:
    """Extrait le contenu entre parenthèses à partir de start."""
    if start >= len(expr) or expr[start] != "(":
        return None
    depth = 0
    i = start
    while i < len(expr):
        if expr[i] == "(":
            depth += 1
        elif expr[i] == ")":
            depth -= 1
            if depth == 0:
                return expr[start + 1:i]
        i += 1
    return None


def _split_args(s: str) -> list[str]:
    """Split les arguments d'une fonction en respectant les parenthèses et strings."""
    args = []
    current = ""
    depth = 0
    in_string = False
    for ch in s:
        if ch in ("'", '"') and not in_string:
            in_string = True
            current += ch
        elif ch in ("'", '"') and in_string:
            in_string = False
            current += ch
        elif in_string:
            current += ch
        elif ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            args.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        args.append(current.strip())
    return args


def _find_op_outside_parens(expr: str, op: str) -> int:
    """Trouve un opérateur en dehors des parenthèses et strings."""
    depth = 0
    in_string = False
    i = 0
    while i < len(expr) - len(op) + 1:
        ch = expr[i]
        if ch in ("'", '"') and not in_string:
            in_string = True
        elif ch in ("'", '"') and in_string:
            in_string = False
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and expr[i:i + len(op)] == op:
                return i
        i += 1
    return -1


def _eq(a, b) -> bool:
    """Comparaison d'égalité flexible."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    # Comparer comme strings si types différents
    if type(a) != type(b):
        return str(a).lower() == str(b).lower()
    return a == b


def _num(v) -> float:
    """Convertit en nombre pour les comparaisons."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0


def resolve_text(text: str, record: dict | None, instance_vars: dict,
                 loop_vars: dict, org=None) -> str:
    """Résout toutes les expressions {!...} dans une chaîne de texte."""
    def _replacer(m):
        val = resolve(m.group(1), record, instance_vars, loop_vars, org)
        return str(val) if val is not None else ""
    return re.sub(r'\{!([^}]+)\}', _replacer, text)
