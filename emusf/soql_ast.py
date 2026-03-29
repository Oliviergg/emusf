"""AST nodes pour les requêtes SOQL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# === Requête principale ===

@dataclass
class SoqlSelect:
    fields: list  # list[SoqlField | SoqlAggregate]
    from_object: str
    where: Optional[SoqlExpr] = None
    subqueries: list = field(default_factory=list)  # list[SoqlSubSelect]
    group_by: Optional[list] = None  # list[str]
    having: Optional[SoqlExpr] = None
    order_by: Optional[list] = None  # list[SoqlOrderItem]
    limit: Optional[int] = None


@dataclass
class SoqlField:
    name: str  # "Name", "Account.Name", "*"
    alias: Optional[str] = None


@dataclass
class SoqlAggregate:
    function: str  # "COUNT", "SUM", "MIN", "MAX", "AVG"
    field: Optional[str] = None  # None pour COUNT()
    alias: Optional[str] = None


@dataclass
class SoqlSubSelect:
    """Sous-requête enfant dans le SELECT : (SELECT Id FROM Contacts)."""
    query: SoqlSelect
    relationship: str  # nom de la relation enfant


@dataclass
class SoqlOrderItem:
    field: str
    direction: str = "ASC"  # "ASC" | "DESC"
    nulls: Optional[str] = None  # "FIRST" | "LAST" | None


# === Expressions WHERE ===

@dataclass
class SoqlExpr:
    """Classe de base pour les expressions."""
    pass


@dataclass
class SoqlAnd(SoqlExpr):
    left: SoqlExpr = None
    right: SoqlExpr = None


@dataclass
class SoqlOr(SoqlExpr):
    left: SoqlExpr = None
    right: SoqlExpr = None


@dataclass
class SoqlNot(SoqlExpr):
    operand: SoqlExpr = None


@dataclass
class SoqlComparison(SoqlExpr):
    field: str = ""
    op: str = ""  # "=", "!=", "<", ">", "<=", ">=", "LIKE"
    value: SoqlValue = None


@dataclass
class SoqlIn(SoqlExpr):
    field: str = ""
    negated: bool = False  # NOT IN
    values: object = None  # list[SoqlValue] | SoqlSelect


@dataclass
class SoqlNullCheck(SoqlExpr):
    field: str = ""
    is_null: bool = True  # True = "= NULL", False = "!= NULL"


# === Valeurs ===

@dataclass
class SoqlValue:
    """Classe de base pour les valeurs."""
    pass


@dataclass
class SoqlLiteral(SoqlValue):
    value: object = None  # str, int, float, bool, None


@dataclass
class SoqlBindVar(SoqlValue):
    path: str = ""  # "varName", "obj.field", "ClassName.CONST"


@dataclass
class SoqlDateLiteral(SoqlValue):
    keyword: str = ""  # "TODAY", "YESTERDAY", etc.
