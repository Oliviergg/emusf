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


@dataclass
class MethodCall(Expr):
    """obj.method(args) ou Class.method(args)"""
    obj: str
    method: str
    args: list  # list[Expr]


@dataclass
class NewList(Expr):
    """new List<Type>() ou new List<Type>{expr, ...}"""
    element_type: str
    init_values: list  # list[Expr]


@dataclass
class NewMap(Expr):
    """new Map<K,V>()"""
    key_type: str
    value_type: str


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
class Return(Stmt):
    value: Optional[Expr]  # None pour return;


@dataclass
class MethodCallStmt(Stmt):
    """Statement wrapper pour un appel de méthode (sans assignation)."""
    call: MethodCall


@dataclass
class TryCatch(Stmt):
    try_body: list  # list[Stmt]
    catch_type: str  # ex: 'Exception'
    catch_var: str  # ex: 'e'
    catch_body: list  # list[Stmt]


@dataclass
class Block(Stmt):
    statements: list  # list[Stmt]


# --- Class-level structures ---

@dataclass
class MethodDef:
    """Définition d'une méthode Apex."""
    name: str
    return_type: str  # 'void', 'String', 'Integer', etc.
    params: list  # list[(type, name)]
    body: list  # list[Stmt]
    is_static: bool = True
    access: str = "public"


@dataclass
class ClassDef:
    """Définition d'une classe Apex."""
    name: str
    constants: dict  # {name: (type, Expr)}
    methods: dict  # {name: MethodDef}
    sharing: Optional[str] = None  # 'with sharing', 'without sharing'
