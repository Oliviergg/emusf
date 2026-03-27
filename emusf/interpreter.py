"""Interpréteur Apex — parcourt un AST et exécute."""

from __future__ import annotations

from .org import FakeOrg
from .apex_parser import ApexParser
from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Block,
)


class ApexInterpreter:
    """
    Interprète un AST Apex.
    Le parsing est délégué à ApexParser.
    """

    def __init__(self, org: FakeOrg):
        self.org = org
        self.parser = ApexParser()
        self.variables = {}
        self.output = []

    def execute_file(self, path: str, method: str = "run"):
        """Charge un .cls, parse en AST, puis exécute."""
        with open(path) as f:
            source = f.read()
        ast = self.parser.parse_class(source, method)
        self._exec_block(ast)

    # --- Statement execution ---

    def _exec_block(self, block: Block):
        for stmt in block.statements:
            self._exec_stmt(stmt)

    def _exec_stmt(self, stmt: Stmt):
        if isinstance(stmt, VarDecl):
            self.variables[stmt.var_name] = self._eval(stmt.value)

        elif isinstance(stmt, Assign):
            self.variables[stmt.var_name] = self._eval(stmt.value)

        elif isinstance(stmt, FieldSet):
            obj = self.variables.get(stmt.obj)
            if not isinstance(obj, dict):
                raise Exception("'{}' n'est pas un SObject".format(stmt.obj))
            obj[stmt.field] = self._eval(stmt.value)

        elif isinstance(stmt, SOQLAssign):
            results = self.org.execute_soql(stmt.soql, context=self.variables)
            self.variables[stmt.var_name] = results

        elif isinstance(stmt, DmlInsert):
            self._exec_dml_insert(stmt)

        elif isinstance(stmt, DmlUpdate):
            self._exec_dml_update(stmt)

        elif isinstance(stmt, DmlDelete):
            self._exec_dml_delete(stmt)

        elif isinstance(stmt, SystemDebug):
            value = self._eval(stmt.expr)
            self.output.append(str(value))
            print("DEBUG: {}".format(value))

        elif isinstance(stmt, IfElse):
            cond = self._eval(stmt.condition)
            if self._is_truthy(cond):
                for s in stmt.then_body:
                    self._exec_stmt(s)
            else:
                for s in stmt.else_body:
                    self._exec_stmt(s)

        elif isinstance(stmt, ForEach):
            items = self._eval(stmt.list_expr)
            if items is None:
                items = []
            for item in items:
                self.variables[stmt.iter_var] = item
                for body_stmt in stmt.body:
                    self._exec_stmt(body_stmt)

        else:
            raise Exception("Statement inconnu: {}".format(type(stmt).__name__))

    # --- DML ---

    def _exec_dml_insert(self, stmt: DmlInsert):
        record = self.variables.get(stmt.var_name)
        if record is None:
            raise Exception("Variable '{}' non définie".format(stmt.var_name))
        sobject = record.get("_sobject_type")
        if not sobject:
            raise Exception("Record sans type SObject")
        data = {k: v for k, v in record.items() if k != "_sobject_type"}
        result = self.org.insert(sobject, [data])
        record["Id"] = result.record_ids[0]
        print("DML: INSERT {} -> Id={}".format(sobject, record["Id"]))

    def _exec_dml_update(self, stmt: DmlUpdate):
        record = self.variables.get(stmt.var_name)
        if record is None:
            raise Exception("Variable '{}' non définie".format(stmt.var_name))
        sobject = record.get("_sobject_type")
        if not sobject:
            raise Exception("Record sans type SObject")
        if "Id" not in record:
            raise Exception("UPDATE sans Id")
        data = {k: v for k, v in record.items() if k != "_sobject_type"}
        self.org.update(sobject, [data])
        print("DML: UPDATE {} Id={}".format(sobject, record["Id"]))

    def _exec_dml_delete(self, stmt: DmlDelete):
        record = self.variables.get(stmt.var_name)
        if record is None:
            raise Exception("Variable '{}' non définie".format(stmt.var_name))
        sobject = record.get("_sobject_type")
        record_id = record.get("Id")
        if not record_id:
            raise Exception("DELETE sans Id")
        self.org.delete(sobject, [record_id])
        print("DML: DELETE {} Id={}".format(sobject, record_id))

    # --- Expression evaluation ---

    def _eval(self, expr: Expr):
        if isinstance(expr, StringLiteral):
            return expr.value

        elif isinstance(expr, IntegerLiteral):
            return expr.value

        elif isinstance(expr, BooleanLiteral):
            return 1 if expr.value else 0

        elif isinstance(expr, NullLiteral):
            return None

        elif isinstance(expr, Variable):
            return self.variables.get(expr.name)

        elif isinstance(expr, FieldAccess):
            obj = self.variables.get(expr.obj)
            if isinstance(obj, dict):
                return obj.get(expr.field, "null")
            return "null"

        elif isinstance(expr, UnaryOp):
            val = self._eval(expr.operand)
            if expr.op == "!":
                return not self._is_truthy(val)
            raise Exception("Opérateur unaire inconnu: {}".format(expr.op))

        elif isinstance(expr, BinaryOp):
            left = self._eval(expr.left)
            right = self._eval(expr.right)
            if expr.op == "+":
                # Si les deux sont des nombres, additionner
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    return left + right
                return str(left) + str(right)
            elif expr.op == "==":
                return left == right
            elif expr.op == "!=":
                return left != right
            elif expr.op == "<":
                return left < right
            elif expr.op == ">":
                return left > right
            elif expr.op == "<=":
                return left <= right
            elif expr.op == ">=":
                return left >= right
            elif expr.op == "&&":
                return self._is_truthy(left) and self._is_truthy(right)
            elif expr.op == "||":
                return self._is_truthy(left) or self._is_truthy(right)
            raise Exception("Opérateur inconnu: {}".format(expr.op))

        elif isinstance(expr, NewSObject):
            record = {"_sobject_type": expr.sobject_type}
            for field, val_expr in expr.fields.items():
                record[field] = self._eval(val_expr)
            return record

        else:
            raise Exception("Expression inconnue: {}".format(type(expr).__name__))

    def _is_truthy(self, val) -> bool:
        """Évalue la vérité d'une valeur Apex."""
        if val is None:
            return False
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return len(val) > 0
        return True
