"""Validation rules engine — évalue les formules de validation Salesforce."""

from __future__ import annotations

import re
from typing import Optional


class ValidationError(Exception):
    """Erreur levée quand une validation rule échoue."""

    def __init__(self, rule_name: str, message: str, field: Optional[str] = None):
        self.rule_name = rule_name
        self.field = field
        super().__init__(message)


class ValidationEngine:
    """
    Évalue les validation rules Salesforce sur des records.
    Supporte un sous-ensemble de formules : ISBLANK, ISPICKVAL, AND, OR, NOT.
    """

    def __init__(self):
        self.rules = {}  # {sobject: [rule_dict]}

    def register_rules(self, sobject: str, rules: list):
        """Enregistre les validation rules pour un SObject."""
        self.rules[sobject] = rules

    def validate(self, sobject: str, record: dict):
        """
        Évalue toutes les rules actives sur un record.
        Lève ValidationError si une rule échoue (formule = true).
        """
        rules = self.rules.get(sobject, [])
        for rule in rules:
            if not rule["active"]:
                continue
            formula = rule.get("errorConditionFormula")
            if not formula:
                continue
            try:
                result = self._eval_formula(formula, record)
                if result:
                    raise ValidationError(
                        rule_name=rule["fullName"],
                        message=rule.get("errorMessage", "Validation error"),
                        field=rule.get("errorDisplayField"),
                    )
            except ValidationError:
                raise
            except Exception:
                # Formule non supportée — on skip silencieusement
                pass

    def _eval_formula(self, formula: str, record: dict) -> bool:
        """Évalue une formule de validation Salesforce."""
        formula = formula.strip()

        # Supprimer les références $Permission, $Profile etc. — on ne peut pas les évaluer
        if "$Permission" in formula or "$Profile" in formula or "$User" in formula:
            return False

        return self._eval_expr(formula, record)

    def _eval_expr(self, expr: str, record: dict) -> object:
        """Évalue une expression de formule récursivement."""
        expr = expr.strip()

        # Parenthèses englobantes
        if expr.startswith("(") and self._matching_paren(expr, 0) == len(expr) - 1:
            return self._eval_expr(expr[1:-1], record)

        # AND(...)
        and_match = re.match(r'AND\s*\(', expr, re.IGNORECASE)
        if and_match:
            args = self._extract_func_args(expr, and_match.end() - 1)
            return all(self._eval_expr(a, record) for a in args)

        # OR(...)
        or_match = re.match(r'OR\s*\(', expr, re.IGNORECASE)
        if or_match:
            args = self._extract_func_args(expr, or_match.end() - 1)
            return any(self._eval_expr(a, record) for a in args)

        # NOT(...)
        not_match = re.match(r'NOT\s*\(', expr, re.IGNORECASE)
        if not_match:
            args = self._extract_func_args(expr, not_match.end() - 1)
            if args:
                return not self._eval_expr(args[0], record)

        # ISBLANK(field)
        isblank_match = re.match(r'ISBLANK\s*\(', expr, re.IGNORECASE)
        if isblank_match:
            args = self._extract_func_args(expr, isblank_match.end() - 1)
            if args:
                val = self._resolve_field(args[0].strip(), record)
                return val is None or val == ""

        # ISPICKVAL(field, "value")
        ispickval_match = re.match(r'ISPICKVAL\s*\(', expr, re.IGNORECASE)
        if ispickval_match:
            args = self._extract_func_args(expr, ispickval_match.end() - 1)
            if len(args) >= 2:
                val = self._resolve_field(args[0].strip(), record)
                expected = args[1].strip().strip('"').strip("'")
                return val == expected

        # Opérateurs logiques infix: &&, ||
        parts = self._split_logical(expr, "||")
        if len(parts) > 1:
            return any(self._eval_expr(p, record) for p in parts)

        parts = self._split_logical(expr, "&&")
        if len(parts) > 1:
            return all(self._eval_expr(p, record) for p in parts)

        # Comparaisons: ==, !=
        for op in ("==", "!=", "&lt;&gt;"):
            parts = self._split_logical(expr, op)
            if len(parts) == 2:
                left = self._eval_expr(parts[0], record)
                right = self._eval_expr(parts[1], record)
                if op == "==":
                    return left == right
                return left != right

        # String literal
        if (expr.startswith('"') and expr.endswith('"')) or \
           (expr.startswith("'") and expr.endswith("'")):
            return expr[1:-1]

        # Boolean
        if expr.lower() == "true":
            return True
        if expr.lower() == "false":
            return False

        # Number
        try:
            return float(expr) if "." in expr else int(expr)
        except ValueError:
            pass

        # Field reference
        return self._resolve_field(expr, record)

    def _resolve_field(self, field_name: str, record: dict) -> object:
        """Résout un nom de champ dans un record."""
        field_name = field_name.strip()
        # Gestion de RecordType.DeveloperName etc.
        if "." in field_name:
            parts = field_name.split(".")
            # Simplifié — on ne gère pas les relations imbriquées
            return record.get(field_name)
        return record.get(field_name)

    def _matching_paren(self, s: str, start: int) -> int:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _extract_func_args(self, expr: str, paren_start: int) -> list:
        """Extrait les arguments d'une fonction à partir de la parenthèse ouvrante."""
        end = self._matching_paren(expr, paren_start)
        if end == -1:
            return []
        inner = expr[paren_start + 1:end]
        return self._split_args(inner)

    def _split_args(self, s: str) -> list:
        """Split les arguments par virgule en respectant parenthèses et strings."""
        args = []
        current = ""
        depth = 0
        in_string = False
        quote_char = None

        for ch in s:
            if not in_string and ch in ('"', "'"):
                in_string = True
                quote_char = ch
                current += ch
            elif in_string and ch == quote_char:
                in_string = False
                current += ch
            elif not in_string and ch == "(":
                depth += 1
                current += ch
            elif not in_string and ch == ")":
                depth -= 1
                current += ch
            elif ch == "," and depth == 0 and not in_string:
                args.append(current.strip())
                current = ""
            else:
                current += ch

        if current.strip():
            args.append(current.strip())
        return args

    def _split_logical(self, expr: str, op: str) -> list:
        """Split par opérateur logique en respectant parenthèses et strings."""
        parts = []
        current = ""
        depth = 0
        in_string = False
        i = 0

        while i < len(expr):
            ch = expr[i]
            if not in_string and ch in ('"', "'"):
                in_string = True
                current += ch
            elif in_string and ch in ('"', "'"):
                in_string = False
                current += ch
            elif not in_string and ch == "(":
                depth += 1
                current += ch
            elif not in_string and ch == ")":
                depth -= 1
                current += ch
            elif not in_string and depth == 0 and expr[i:i + len(op)] == op:
                parts.append(current)
                current = ""
                i += len(op)
                continue
            else:
                current += ch
            i += 1

        parts.append(current)
        return [p for p in parts if p.strip()]
