"""Parser Apex → AST. Transforme du code source Apex en arbre de nœuds."""

from __future__ import annotations

import re
from typing import Optional

from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject,
    MethodCall, NewList, NewMap,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
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
        """Découpe un bloc en statements bruts (gère les { } imbriqués et else)."""
        statements = []
        depth = 0
        current = ""
        i = 0

        while i < len(block):
            char = block[i]
            current += char

            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    # Vérifier si un 'else' suit (pour if/else)
                    rest = block[i + 1:].lstrip()
                    if rest.startswith("else"):
                        # Ne pas couper ici — continuer pour inclure le else
                        pass
                    else:
                        statements.append(current.strip())
                        current = ""
            elif char == ";" and depth == 0:
                statements.append(current.strip())
                current = ""

            i += 1

        if current.strip():
            statements.append(current.strip())

        return statements

    def _parse_statement(self, stmt: str) -> Optional[Stmt]:
        """Parse un statement brut en nœud AST."""

        # --- for (Type var : expr) { body } ---
        for_match = re.match(
            r'for\s*\(\s*(\w+)\s+(\w+)\s*:\s*(.+?)\s*\)\s*\{(.*)\}',
            stmt, re.DOTALL
        )
        if for_match:
            body_stmts = self._parse_block(for_match.group(4))
            list_expr = self._parse_expr(for_match.group(3))
            return ForEach(
                iter_type=for_match.group(1),
                iter_var=for_match.group(2),
                list_expr=list_expr,
                body=body_stmts,
            )

        # --- if (...) { ... } else if (...) { ... } else { ... } ---
        if_match = re.match(r'if\s*\((.+?)\)\s*\{', stmt)
        if if_match:
            return self._parse_if(stmt)

        # --- try { ... } catch (Type var) { ... } ---
        try_match = re.match(r'try\s*\{', stmt)
        if try_match:
            return self._parse_try_catch(stmt)

        # --- return expr; ---
        return_match = re.match(r'return\b\s*(.*?)\s*;?$', stmt)
        if return_match:
            expr_str = return_match.group(1).strip()
            value = self._parse_expr(expr_str) if expr_str else None
            return Return(value=value)

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

        # --- obj.method(args); (statement, pas assignment) ---
        method_stmt_match = re.match(r'(\w+)\.(\w+)\((.*)?\)\s*;?$', stmt, re.DOTALL)
        if method_stmt_match:
            # Vérifier que ce n'est pas un field set (pas de = après)
            obj = method_stmt_match.group(1)
            method = method_stmt_match.group(2)
            args_str = method_stmt_match.group(3) or ""
            args = self._parse_call_args(args_str) if args_str.strip() else []
            return MethodCallStmt(call=MethodCall(obj=obj, method=method, args=args))

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

        # --- List<T> var = new List<T>(); or List<T> var = new List<T>{...}; ---
        new_list_match = re.match(
            r'(?:List<(\w+)>\s+)?(\w+)\s*=\s*new\s+List<(\w+)>\s*(?:\(\s*\)|\{(.*?)\})\s*;?$',
            stmt, re.DOTALL
        )
        if new_list_match:
            elem_type = new_list_match.group(1) or new_list_match.group(3)
            var_name = new_list_match.group(2)
            init_str = new_list_match.group(4)
            init_values = []
            if init_str and init_str.strip():
                init_values = [self._parse_expr(a) for a in self._parse_call_args(init_str)]
            return VarDecl(
                type_name="List<{}>".format(elem_type),
                var_name=var_name,
                value=NewList(element_type=elem_type, init_values=init_values),
            )

        # --- Map<K,V> var = new Map<K,V>(); ---
        new_map_match = re.match(
            r'(?:Map<(\w+)\s*,\s*(\w+)>\s+)?(\w+)\s*=\s*new\s+Map<(\w+)\s*,\s*(\w+)>\s*\(\s*\)\s*;?$',
            stmt
        )
        if new_map_match:
            k_type = new_map_match.group(1) or new_map_match.group(4)
            v_type = new_map_match.group(2) or new_map_match.group(5)
            var_name = new_map_match.group(3)
            return VarDecl(
                type_name="Map<{},{}>".format(k_type, v_type),
                var_name=var_name,
                value=NewMap(key_type=k_type, value_type=v_type),
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

        # --- Type var = new SObject(); (empty constructor) ---
        new_empty_match = re.match(
            r'(\w+)\s+(\w+)\s*=\s*new\s+(\w+)\(\s*\)\s*;?$',
            stmt
        )
        if new_empty_match:
            return VarDecl(
                type_name=new_empty_match.group(1),
                var_name=new_empty_match.group(2),
                value=NewSObject(
                    sobject_type=new_empty_match.group(3),
                    fields={},
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

    def _parse_if(self, stmt: str) -> IfElse:
        """Parse if (...) { ... } else if (...) { ... } else { ... }"""
        pos = 0

        # Trouver la condition entre parenthèses
        cond_start = stmt.index("(", pos) + 1
        depth = 1
        i = cond_start
        while i < len(stmt) and depth > 0:
            if stmt[i] == "(":
                depth += 1
            elif stmt[i] == ")":
                depth -= 1
            i += 1
        condition_str = stmt[cond_start:i - 1]
        condition = self._parse_expr(condition_str)

        # Trouver le bloc then { ... }
        then_start = stmt.index("{", i - 1) + 1
        depth = 1
        j = then_start
        while j < len(stmt) and depth > 0:
            if stmt[j] == "{":
                depth += 1
            elif stmt[j] == "}":
                depth -= 1
            j += 1
        then_body = self._parse_block(stmt[then_start:j - 1])

        # Chercher else
        else_body = []
        rest = stmt[j:].strip()
        if rest.startswith("else"):
            rest = rest[4:].strip()
            if rest.startswith("if"):
                # else if → récursif, encapsulé dans la else_body
                else_body = [self._parse_if(rest)]
            elif rest.startswith("{"):
                # else { ... }
                block_start = 1
                depth = 1
                k = block_start
                while k < len(rest) and depth > 0:
                    if rest[k] == "{":
                        depth += 1
                    elif rest[k] == "}":
                        depth -= 1
                    k += 1
                else_body = self._parse_block(rest[block_start:k - 1])

        return IfElse(condition=condition, then_body=then_body, else_body=else_body)

    def _parse_try_catch(self, stmt: str) -> TryCatch:
        """Parse try { ... } catch (Type var) { ... }"""
        # Trouver le bloc try { ... }
        try_start = stmt.index("{") + 1
        depth = 1
        i = try_start
        while i < len(stmt) and depth > 0:
            if stmt[i] == "{":
                depth += 1
            elif stmt[i] == "}":
                depth -= 1
            i += 1
        try_body = self._parse_block(stmt[try_start:i - 1])

        # Chercher catch
        rest = stmt[i:].strip()
        catch_match = re.match(r'catch\s*\(\s*(\w+)\s+(\w+)\s*\)\s*\{', rest)
        catch_type = "Exception"
        catch_var = "e"
        catch_body = []
        if catch_match:
            catch_type = catch_match.group(1)
            catch_var = catch_match.group(2)
            block_start = catch_match.end()
            depth = 1
            j = block_start
            while j < len(rest) and depth > 0:
                if rest[j] == "{":
                    depth += 1
                elif rest[j] == "}":
                    depth -= 1
                j += 1
            catch_body = self._parse_block(rest[block_start:j - 1])

        return TryCatch(
            try_body=try_body,
            catch_type=catch_type,
            catch_var=catch_var,
            catch_body=catch_body,
        )

    def _parse_call_args(self, args_str: str) -> list:
        """Parse les arguments d'un appel de méthode en list[Expr]."""
        raw = self._split_args_str(args_str)
        return [self._parse_expr(a) for a in raw if a.strip()]

    def _split_args_str(self, s: str) -> list:
        """Split par virgule en respectant parenthèses et strings."""
        parts = []
        current = ""
        depth = 0
        in_string = False
        for ch in s:
            if ch == "'" and not in_string:
                in_string = True
                current += ch
            elif ch == "'" and in_string:
                in_string = False
                current += ch
            elif not in_string and ch == "(":
                depth += 1
                current += ch
            elif not in_string and ch == ")":
                depth -= 1
                current += ch
            elif ch == "," and depth == 0 and not in_string:
                parts.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            parts.append(current.strip())
        return parts

    # --- Expression parser ---

    def _parse_expr(self, expr: str) -> Expr:
        """Parse une expression Apex en nœud Expr (avec priorité d'opérateurs)."""
        expr = expr.strip()

        # Parenthèses englobantes
        if expr.startswith("(") and self._matching_paren(expr, 0) == len(expr) - 1:
            return self._parse_expr(expr[1:-1])

        # || (priorité la plus basse)
        parts = self._split_op(expr, "||")
        if len(parts) > 1:
            left = self._parse_expr(parts[0])
            for p in parts[1:]:
                left = BinaryOp(left=left, op="||", right=self._parse_expr(p))
            return left

        # &&
        parts = self._split_op(expr, "&&")
        if len(parts) > 1:
            left = self._parse_expr(parts[0])
            for p in parts[1:]:
                left = BinaryOp(left=left, op="&&", right=self._parse_expr(p))
            return left

        # ==, !=
        for op in ("==", "!="):
            parts = self._split_op(expr, op)
            if len(parts) == 2:
                return BinaryOp(
                    left=self._parse_expr(parts[0]),
                    op=op,
                    right=self._parse_expr(parts[1]),
                )

        # <=, >=, <, > (ordre important : <= avant <)
        for op in ("<=", ">=", "<", ">"):
            parts = self._split_op(expr, op)
            if len(parts) == 2:
                return BinaryOp(
                    left=self._parse_expr(parts[0]),
                    op=op,
                    right=self._parse_expr(parts[1]),
                )

        # + (concaténation / addition)
        parts = self._split_concat(expr)
        if len(parts) > 1:
            left = self._parse_expr(parts[0])
            for part in parts[1:]:
                left = BinaryOp(left=left, op="+", right=self._parse_expr(part))
            return left

        # Unaire : !expr
        if expr.startswith("!"):
            return UnaryOp(op="!", operand=self._parse_expr(expr[1:]))

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

        # Method call: obj.method(args) as expression
        method_expr_match = re.match(r'(\w+)\.(\w+)\((.*)?\)$', expr, re.DOTALL)
        if method_expr_match:
            obj = method_expr_match.group(1)
            method = method_expr_match.group(2)
            args_str = method_expr_match.group(3) or ""
            args = self._parse_call_args(args_str) if args_str.strip() else []
            return MethodCall(obj=obj, method=method, args=args)

        # Field access: var.Field
        if "." in expr:
            obj, field = expr.split(".", 1)
            return FieldAccess(obj=obj, field=field)

        # Variable
        return Variable(name=expr)

    def _matching_paren(self, s: str, start: int) -> int:
        """Trouve la parenthèse fermante correspondante."""
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _split_op(self, expr: str, op: str) -> list:
        """Split par un opérateur en respectant parenthèses et strings."""
        parts = []
        current = ""
        in_string = False
        depth = 0
        i = 0
        while i < len(expr):
            ch = expr[i]
            if ch == "'" and depth == 0:
                in_string = not in_string
                current += ch
            elif not in_string and ch == "(":
                depth += 1
                current += ch
            elif not in_string and ch == ")":
                depth -= 1
                current += ch
            elif (not in_string and depth == 0
                  and expr[i:i + len(op)] == op
                  # Éviter de matcher == quand on cherche = etc.
                  and not (op == "=" and i + 1 < len(expr) and expr[i + 1] == "=")
                  and not (op == "<" and i + 1 < len(expr) and expr[i + 1] == "=")
                  and not (op == ">" and i + 1 < len(expr) and expr[i + 1] == "=")
                  and not (op == "!" and i + 1 < len(expr) and expr[i + 1] == "=")):
                parts.append(current)
                current = ""
                i += len(op)
                continue
            else:
                current += ch
            i += 1
        parts.append(current)
        return parts

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
