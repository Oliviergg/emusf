"""Pretty-printer pour l'AST Apex."""

from __future__ import annotations

from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject,
    MethodCall, NewList, NewMap,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
)

# Couleurs ANSI
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
BLUE = "\033[34m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_ast(block: Block):
    """Affiche un AST en arbre indenté avec couleurs."""
    for i, stmt in enumerate(block.statements):
        is_last = i == len(block.statements) - 1
        _print_stmt(stmt, "", is_last)


def _conn(is_last):
    return "└── " if is_last else "├── "


def _child(prefix, is_last):
    return prefix + ("    " if is_last else "│   ")


def _print_stmt(stmt, prefix, is_last):
    c = _conn(is_last)
    cp = _child(prefix, is_last)

    if isinstance(stmt, VarDecl):
        print(prefix + c + CYAN + "VarDecl" + RESET + " " + DIM + stmt.type_name + RESET)
        _print_leaf(cp, "name", stmt.var_name, False)
        _print_expr(stmt.value, cp, True)

    elif isinstance(stmt, Assign):
        print(prefix + c + CYAN + "Assign" + RESET)
        _print_leaf(cp, "name", stmt.var_name, False)
        _print_expr(stmt.value, cp, True)

    elif isinstance(stmt, FieldSet):
        print(prefix + c + CYAN + "FieldSet" + RESET + " " + stmt.obj + "." + stmt.field)
        _print_expr(stmt.value, cp, True)

    elif isinstance(stmt, SOQLAssign):
        print(prefix + c + BLUE + "SOQLAssign" + RESET + " " + stmt.var_name)
        _print_leaf(cp, "soql", stmt.soql, True)

    elif isinstance(stmt, DmlInsert):
        print(prefix + c + RED + "INSERT" + RESET + " " + stmt.var_name)

    elif isinstance(stmt, DmlUpdate):
        print(prefix + c + RED + "UPDATE" + RESET + " " + stmt.var_name)

    elif isinstance(stmt, DmlDelete):
        print(prefix + c + RED + "DELETE" + RESET + " " + stmt.var_name)

    elif isinstance(stmt, SystemDebug):
        print(prefix + c + YELLOW + "System.debug" + RESET)
        _print_expr(stmt.expr, cp, True)

    elif isinstance(stmt, IfElse):
        print(prefix + c + MAGENTA + "if" + RESET)
        _print_expr(stmt.condition, cp, False)
        # then
        print(cp + "├── " + DIM + "then:" + RESET)
        then_cp = cp + "│   "
        for j, s in enumerate(stmt.then_body):
            _print_stmt(s, then_cp, j == len(stmt.then_body) - 1)
        # else (si présent)
        if stmt.else_body:
            print(cp + "└── " + DIM + "else:" + RESET)
            else_cp = cp + "    "
            for j, s in enumerate(stmt.else_body):
                _print_stmt(s, else_cp, j == len(stmt.else_body) - 1)
        else:
            # Fermer proprement l'arbre
            pass

    elif isinstance(stmt, Return):
        print(prefix + c + MAGENTA + "return" + RESET)
        if stmt.value:
            _print_expr(stmt.value, cp, True)

    elif isinstance(stmt, MethodCallStmt):
        call = stmt.call
        args_str = ", ".join(_expr_inline(a) for a in call.args)
        print(prefix + c + YELLOW + call.obj + "." + call.method + RESET + "(" + args_str + ")")

    elif isinstance(stmt, TryCatch):
        print(prefix + c + MAGENTA + "try" + RESET)
        try_cp = cp + "│   "
        print(cp + "├── " + DIM + "try:" + RESET)
        for j, s in enumerate(stmt.try_body):
            _print_stmt(s, try_cp, j == len(stmt.try_body) - 1)
        print(cp + "└── " + DIM + "catch" + RESET + " (" + stmt.catch_type + " " + stmt.catch_var + ")")
        catch_cp = cp + "    "
        for j, s in enumerate(stmt.catch_body):
            _print_stmt(s, catch_cp, j == len(stmt.catch_body) - 1)

    elif isinstance(stmt, ForEach):
        list_str = _expr_inline(stmt.list_expr)
        print(prefix + c + MAGENTA + "for" + RESET
              + " (" + stmt.iter_type + " " + stmt.iter_var + " : " + list_str + ")")
        for j, s in enumerate(stmt.body):
            _print_stmt(s, cp, j == len(stmt.body) - 1)

    else:
        print(prefix + c + str(stmt))


def _print_expr(expr, prefix, is_last):
    c = _conn(is_last)
    cp = _child(prefix, is_last)

    if isinstance(expr, StringLiteral):
        print(prefix + c + GREEN + "'" + expr.value + "'" + RESET)

    elif isinstance(expr, IntegerLiteral):
        print(prefix + c + YELLOW + str(expr.value) + RESET)

    elif isinstance(expr, BooleanLiteral):
        print(prefix + c + YELLOW + str(expr.value) + RESET)

    elif isinstance(expr, NullLiteral):
        print(prefix + c + DIM + "null" + RESET)

    elif isinstance(expr, Variable):
        print(prefix + c + expr.name)

    elif isinstance(expr, FieldAccess):
        print(prefix + c + expr.obj + "." + expr.field)

    elif isinstance(expr, UnaryOp):
        print(prefix + c + BOLD + expr.op + RESET)
        _print_expr(expr.operand, cp, True)

    elif isinstance(expr, BinaryOp):
        print(prefix + c + BOLD + expr.op + RESET)
        _print_expr(expr.left, cp, False)
        _print_expr(expr.right, cp, True)

    elif isinstance(expr, NewSObject):
        print(prefix + c + CYAN + "new " + expr.sobject_type + RESET)
        fields = list(expr.fields.items())
        for j, (field, val) in enumerate(fields):
            fl = j == len(fields) - 1
            fc = _conn(fl)
            fcp = _child(cp, fl)
            print(cp + fc + field + " =")
            _print_expr(val, fcp, True)

    elif isinstance(expr, MethodCall):
        args_str = ", ".join(_expr_inline(a) for a in expr.args)
        print(prefix + c + expr.obj + "." + BOLD + expr.method + RESET + "(" + args_str + ")")

    elif isinstance(expr, NewList):
        inits = ", ".join(_expr_inline(v) for v in expr.init_values) if expr.init_values else ""
        print(prefix + c + CYAN + "new List<" + expr.element_type + ">" + RESET + "{" + inits + "}")

    elif isinstance(expr, NewMap):
        print(prefix + c + CYAN + "new Map<" + expr.key_type + "," + expr.value_type + ">" + RESET + "()")

    else:
        print(prefix + c + str(expr))


def _expr_inline(expr):
    """Représentation inline courte d'une expression pour les labels."""
    if isinstance(expr, Variable):
        return expr.name
    elif isinstance(expr, FieldAccess):
        return expr.obj + "." + expr.field
    elif isinstance(expr, StringLiteral):
        return "'" + expr.value + "'"
    elif isinstance(expr, IntegerLiteral):
        return str(expr.value)
    elif isinstance(expr, BooleanLiteral):
        return str(expr.value)
    elif isinstance(expr, MethodCall):
        args = ", ".join(_expr_inline(a) for a in expr.args)
        return expr.obj + "." + expr.method + "(" + args + ")"
    return str(expr)


def _print_leaf(prefix, label, value, is_last):
    c = _conn(is_last)
    print(prefix + c + DIM + label + ": " + RESET + value)
