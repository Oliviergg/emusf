"""AST nodes pour le langage Apex."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# --- Expressions ---

@dataclass
class Expr:
    """Base pour toutes les expressions."""
    pass


@dataclass
class StringLiteral(Expr):
    value: str


@dataclass
class IntegerLiteral(Expr):
    value: int


@dataclass
class BooleanLiteral(Expr):
    value: bool


@dataclass
class NullLiteral(Expr):
    pass


@dataclass
class Variable(Expr):
    name: str


@dataclass
class FieldAccess(Expr):
    obj: str
    field: str


@dataclass
class BinaryOp(Expr):
    left: Expr
    op: str  # '+', '==', '!=', etc.
    right: Expr


@dataclass
class UnaryOp(Expr):
    op: str  # '!'
    operand: Expr


@dataclass
class NewSObject(Expr):
    sobject_type: str
    fields: dict  # {field_name: Expr}


# --- Statements ---

@dataclass
class Stmt:
    """Base pour tous les statements."""
    pass


@dataclass
class VarDecl(Stmt):
    type_name: str
    var_name: str
    value: Expr


@dataclass
class Assign(Stmt):
    var_name: str
    value: Expr


@dataclass
class FieldSet(Stmt):
    obj: str
    field: str
    value: Expr


@dataclass
class SOQLAssign(Stmt):
    type_name: Optional[str]  # List<Account> ou None
    var_name: str
    soql: str  # la requête brute


@dataclass
class DmlInsert(Stmt):
    var_name: str


@dataclass
class DmlUpdate(Stmt):
    var_name: str


@dataclass
class DmlDelete(Stmt):
    var_name: str


@dataclass
class SystemDebug(Stmt):
    expr: Expr


@dataclass
class ForEach(Stmt):
    iter_type: str
    iter_var: str
    list_expr: Expr  # Variable('accounts') ou FieldAccess('Trigger', 'new')
    body: list  # list[Stmt]


@dataclass
class IfElse(Stmt):
    condition: Expr
    then_body: list  # list[Stmt]
    else_body: list  # list[Stmt] (peut être vide)


@dataclass
class Block(Stmt):
    statements: list  # list[Stmt]
