"""Validation rules engine — évalue les formules de validation Salesforce."""

from __future__ import annotations

from typing import Optional

from .formula_engine import FormulaEngine


class ValidationError(Exception):
    """Erreur levée quand une validation rule échoue."""

    def __init__(self, rule_name: str, message: str, field: Optional[str] = None):
        self.rule_name = rule_name
        self.field = field
        super().__init__(message)


class ValidationEngine:
    """
    Évalue les validation rules Salesforce sur des records.
    Délègue l'évaluation des formules au FormulaEngine unifié.
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
                # Ignorer les formules avec des références non supportées
                if "$Permission" in formula or "$Profile" in formula or "$User" in formula:
                    continue

                def _make_resolver(rec):
                    def resolver(ref):
                        if ref in rec:
                            return rec[ref]
                        # Gestion des chemins pointés (RecordType.DeveloperName)
                        parts = ref.split(".")
                        obj = rec
                        for p in parts:
                            if isinstance(obj, dict) and p in obj:
                                obj = obj[p]
                            else:
                                return None
                        return obj
                    return resolver

                engine = FormulaEngine(_make_resolver(record))
                result = engine.evaluate(formula)
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
