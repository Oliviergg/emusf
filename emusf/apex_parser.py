"""Parser Apex → AST. Transforme du code source Apex en arbre de nœuds."""

from __future__ import annotations

import re
from typing import Optional

from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, NewSObject,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, Block,
)


class ApexParser:
    """Parse du code Apex en AST."""

    def parse_class(self, source: str, method_name: str = "run") -> Block:
        """Parse une classe Apex et retourne le Block de la méthode demandée."""
        body = self._extract_method(source, method_name)
        if body is None:
            raise Exception("Méthode '{}' non trouvée".format(method_name))
        statements = self._parse_block(body)
        return Block(statements=statements)

    def _extract_method(self, source: str, method_name: str) -> Optional[str]:
        pattern = r'(?:public|private)\s+static\s+\w+\s+{}\s*\(\s*\)\s*\{{'.format(
            re.escape(method_name)
        )
        match = re.search(pattern, source)
        if not match:
            return None

        start = match.end()
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1

        return source[start:i - 1]

    def _parse_block(self, block: str) -> list:
        """Parse un bloc de code en liste de Stmt."""
        raw_stmts = self._split_statements(block)
        stmts = []
        for raw in raw_stmts:
            raw = raw.strip()
            if not raw:
                continue
            # Strip comments
            lines = raw.split("\n")
            lines = [l for l in lines if not l.strip().startswith("//")]
            raw = "\n".join(lines).strip()
            if not raw:
                continue
            node = self._parse_statement(raw)
            if node:
                stmts.append(node)
        return stmts

    def _split_statements(self, block: str) -> list:
        """Découpe un bloc en statements bruts (gère les { } imbriqués)."""
        statements = []
        depth = 0
        current = ""

        for char in block:
            current += char
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    statements.append(current.strip())
                    current = ""
            elif char == ";" and depth == 0:
                statements.append(current.strip())
                current = ""

        if current.strip():
            statements.append(current.strip())

        return statements

    def _parse_statement(self, stmt: str) -> Optional[Stmt]:
        """Parse un statement brut en nœud AST."""

        # --- for (Type var : list) { body } ---
        for_match = re.match(
            r'for\s*\(\s*(\w+)\s+(\w+)\s*:\s*(\w+)\s*\)\s*\{(.*)\}',
            stmt, re.DOTALL
        )
        if for_match:
            body_stmts = self._parse_block(for_match.group(4))
            return ForEach(
                iter_type=for_match.group(1),
                iter_var=for_match.group(2),
                list_var=for_match.group(3),
                body=body_stmts,
            )

        # --- System.debug(...) ---
        debug_match = re.match(r"System\.debug\((.+)\)", stmt.rstrip(";"))
        if debug_match:
            expr = self._parse_expr(debug_match.group(1))
            return SystemDebug(expr=expr)

        # --- insert var; ---
        insert_match = re.match(r'insert\s+(\w+)\s*;?$', stmt)
        if insert_match:
            return DmlInsert(var_name=insert_match.group(1))

        # --- update var; ---
        update_match = re.match(r'update\s+(\w+)\s*;?$', stmt)
        if update_match:
            return DmlUpdate(var_name=update_match.group(1))

        # --- delete var; ---
        delete_match = re.match(r'delete\s+(\w+)\s*;?$', stmt)
        if delete_match:
            return DmlDelete(var_name=delete_match.group(1))

        # --- var.Field = expr; ---
        field_set_match = re.match(r'(\w+)\.(\w+)\s*=\s*(.+?)\s*;?$', stmt)
        if field_set_match:
            return FieldSet(
                obj=field_set_match.group(1),
                field=field_set_match.group(2),
                value=self._parse_expr(field_set_match.group(3)),
            )

        # --- List<SObject> var = [SOQL]; ---
        soql_match = re.match(
            r'(?:List<(\w+)>\s+)?(\w+)\s*=\s*\[(.+?)\]\s*;?$',
            stmt, re.DOTALL
        )
        if soql_match:
            return SOQLAssign(
                type_name=soql_match.group(1),
                var_name=soql_match.group(2),
                soql="[{}]".format(soql_match.group(3)),
            )

        # --- Type var = new SObject(...); ---
        new_obj_match = re.match(
            r'(\w+)\s+(\w+)\s*=\s*new\s+(\w+)\((.+?)\)\s*;?$',
            stmt, re.DOTALL
        )
        if new_obj_match:
            fields = self._parse_constructor_args(new_obj_match.group(4))
            return VarDecl(
                type_name=new_obj_match.group(1),
                var_name=new_obj_match.group(2),
                value=NewSObject(
                    sobject_type=new_obj_match.group(3),
                    fields=fields,
                ),
            )

        # --- Type var = expr; ---
        decl_match = re.match(r'(\w+(?:<\w+>)?)\s+(\w+)\s*=\s*(.+?)\s*;?$', stmt)
        if decl_match:
            return VarDecl(
                type_name=decl_match.group(1),
                var_name=decl_match.group(2),
                value=self._parse_expr(decl_match.group(3)),
            )

        # --- var = expr; ---
        assign_match = re.match(r'(\w+)\s*=\s*(.+?)\s*;?$', stmt)
        if assign_match:
            return Assign(
                var_name=assign_match.group(1),
                value=self._parse_expr(assign_match.group(2)),
            )

        return None

    # --- Expression parser ---

    def _parse_expr(self, expr: str) -> Expr:
        """Parse une expression Apex en nœud Expr."""
        expr = expr.strip()

        # Concaténation avec +
        parts = self._split_concat(expr)
        if len(parts) > 1:
            left = self._parse_expr(parts[0])
            for part in parts[1:]:
                right = self._parse_expr(part)
                left = BinaryOp(left=left, op="+", right=right)
            return left

        # String literal
        if expr.startswith("'") and expr.endswith("'"):
            return StringLiteral(value=expr[1:-1])

        # Boolean
        if expr == "true":
            return BooleanLiteral(value=True)
        if expr == "false":
            return BooleanLiteral(value=False)

        # Null
        if expr == "null":
            return NullLiteral()

        # Integer
        if expr.isdigit():
            return IntegerLiteral(value=int(expr))

        # Field access: var.Field
        if "." in expr:
            obj, field = expr.split(".", 1)
            return FieldAccess(obj=obj, field=field)

        # Variable
        return Variable(name=expr)

    def _split_concat(self, expr: str) -> list:
        """Split une expression par + en respectant les strings."""
        parts = []
        current = ""
        in_string = False

        for char in expr:
            if char == "'" and not in_string:
                in_string = True
                current += char
            elif char == "'" and in_string:
                in_string = False
                current += char
            elif char == "+" and not in_string:
                parts.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            parts.append(current.strip())

        return parts

    def _parse_constructor_args(self, args_str: str) -> dict:
        """Parse 'Name = 'Acme', Active__c = true' → {field: Expr}."""
        result = {}
        parts = []
        current = ""
        in_string = False
        for char in args_str:
            if char == "'":
                in_string = not in_string
                current += char
            elif char == "," and not in_string:
                parts.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            parts.append(current.strip())

        for part in parts:
            match = re.match(r'(\w+)\s*=\s*(.+)', part.strip())
            if match:
                field = match.group(1)
                value = self._parse_expr(match.group(2).strip())
                result[field] = value

        return result
