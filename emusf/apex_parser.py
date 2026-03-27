"""Parser Apex → AST. Transforme du code source Apex en arbre de nœuds."""

from __future__ import annotations

import re
from typing import Optional

from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject,
    MethodCall, ChainedCall, Ternary, NewList, NewMap,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
    WhileLoop, ThrowStmt,
    MethodDef, ClassDef, NewSet, SwitchWhen,
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

    def parse_full_class(self, source: str) -> ClassDef:
        """Parse une classe Apex complète : constantes, méthodes, etc."""
        # Extraire le nom et le body de la classe
        class_match = re.search(
            r'(?:public|private|global)\s+(?:with\s+sharing\s+|without\s+sharing\s+)?'
            r'class\s+(\w+)(?:\s+extends\s+\w+)?\s*\{',
            source
        )
        if not class_match:
            raise Exception("Classe non trouvée dans le source")

        class_name = class_match.group(1)
        sharing = None
        if "with sharing" in source[:class_match.start() + 50]:
            sharing = "with sharing"

        # Extraire le body de la classe
        start = class_match.end()
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        class_body = source[start:i - 1]

        # Parser les membres
        constants = {}
        methods = {}

        self._parse_class_members(class_body, constants, methods)

        return ClassDef(
            name=class_name,
            constants=constants,
            methods=methods,
            sharing=sharing,
        )

    def _parse_class_members(self, body: str, constants: dict, methods: dict):
        """Parse les membres d'une classe (constantes et méthodes)."""
        # Strip comments
        lines = body.split("\n")
        lines = [l for l in lines if not l.strip().startswith("//")]
        body = "\n".join(lines)

        # Trouver les méthodes
        method_pattern = re.compile(
            r'(?:(?:public|private|protected|global)\s+)?'
            r'(?:static\s+)?'
            r'(\w+(?:<[\w,\s]+>)?)\s+'  # return type
            r'(\w+)\s*'  # method name
            r'\(([^)]*)\)\s*\{',  # params
            re.DOTALL
        )

        pos = 0
        method_positions = []
        for m in method_pattern.finditer(body):
            return_type = m.group(1)
            method_name = m.group(2)
            params_str = m.group(3)

            # Skip inner class definitions
            if return_type == "class":
                continue

            # Extraire le body de la méthode
            body_start = m.end()
            depth = 1
            j = body_start
            while j < len(body) and depth > 0:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                j += 1
            method_body = body[body_start:j - 1]

            # Parser les paramètres
            params = []
            if params_str.strip():
                for p in params_str.split(","):
                    p = p.strip()
                    parts = p.rsplit(None, 1)
                    if len(parts) == 2:
                        params.append((parts[0], parts[1]))

            # Déterminer les modifiers
            prefix = body[max(0, m.start() - 100):m.start()]
            is_static = "static" in m.group(0) or "static" in prefix.split("\n")[-1]

            method_stmts = self._parse_block(method_body)
            methods[method_name] = MethodDef(
                name=method_name,
                return_type=return_type,
                params=params,
                body=method_stmts,
                is_static=is_static,
            )
            method_positions.append((m.start(), j))

        # Trouver les constantes (lignes hors des méthodes)
        const_pattern = re.compile(
            r'(?:public|private|protected)?\s*'
            r'(?:static\s+)?(?:final\s+)?'
            r'(\w+(?:<[\w,\s]+>)?)\s+'
            r'(\w+)\s*=\s*(.+?)\s*;',
            re.DOTALL
        )
        for m in const_pattern.finditer(body):
            # Vérifier qu'on n'est pas dans une méthode
            in_method = False
            for mstart, mend in method_positions:
                if mstart <= m.start() <= mend:
                    in_method = True
                    break
            if not in_method:
                type_name = m.group(1)
                var_name = m.group(2)
                value_str = m.group(3).strip()
                try:
                    value_expr = self._parse_expr(value_str)
                    constants[var_name] = (type_name, value_expr)
                except Exception:
                    pass

    def _extract_method(self, source: str, method_name: str) -> Optional[str]:
        # Supporte les méthodes avec ou sans paramètres, avec ou sans access modifier
        pattern = r'(?:(?:public|private|protected|global)\s+)?(?:static\s+)?(?:(?:testMethod|void|\w+)\s+)?{}\s*\([^)]*\)\s*\{{'.format(
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
                    # Vérifier si un 'else' ou 'catch' suit
                    rest = block[i + 1:].lstrip()
                    if rest.startswith("else") or rest.startswith("catch"):
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

        # --- while (cond) { body } ---
        while_match = re.match(r'while\s*\((.+?)\)\s*\{(.*)\}', stmt, re.DOTALL)
        if while_match:
            cond = self._parse_expr(while_match.group(1))
            body = self._parse_block(while_match.group(2))
            return WhileLoop(condition=cond, body=body)

        # --- throw new Exception('msg'); ---
        throw_match = re.match(r'throw\s+(.+?)\s*;?$', stmt)
        if throw_match:
            return ThrowStmt(expr=self._parse_expr(throw_match.group(1)))

        # --- switch on expr { when ... } ---
        switch_match = re.match(r'switch\s+on\s+(.+?)\s*\{', stmt)
        if switch_match:
            return self._parse_switch(stmt, switch_match)

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
                init_values = self._parse_call_args(init_str)
            return VarDecl(
                type_name="List<{}>".format(elem_type),
                var_name=var_name,
                value=NewList(element_type=elem_type, init_values=init_values),
            )

        # --- Set<T> var = new Set<T>(); or Set<T> var = new Set<T>{...}; ---
        new_set_match = re.match(
            r'(?:Set<(\w+)>\s+)?(\w+)\s*=\s*new\s+Set<(\w+)>\s*(?:\(\s*\)|\{(.*?)\})\s*;?$',
            stmt, re.DOTALL
        )
        if new_set_match:
            elem_type = new_set_match.group(1) or new_set_match.group(3)
            var_name = new_set_match.group(2)
            init_str = new_set_match.group(4)
            init_values = []
            if init_str and init_str.strip():
                init_values = self._parse_call_args(init_str)
            return VarDecl(
                type_name="Set<{}>".format(elem_type),
                var_name=var_name,
                value=NewSet(element_type=elem_type, init_values=init_values),
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

        # --- Type var = expr; --- (supports Map<String, String>, List<Account>, etc.)
        decl_match = re.match(r'(\w+(?:<[\w,\s]+>)?)\s+(\w+)\s*=\s*(.+?)\s*;?$', stmt)
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

    def _parse_switch(self, stmt: str, match) -> SwitchWhen:
        """Parse switch on expr { when 'a' { ... } when else { ... } }"""
        expr = self._parse_expr(match.group(1))

        # Trouver le body principal
        body_start = match.end()
        depth = 1
        i = body_start
        while i < len(stmt) and depth > 0:
            if stmt[i] == "{":
                depth += 1
            elif stmt[i] == "}":
                depth -= 1
            i += 1
        switch_body = stmt[body_start:i - 1]

        # Parser les when clauses
        cases = []
        when_pattern = re.compile(r'when\s+(else|.+?)\s*\{', re.DOTALL)
        pos = 0
        while pos < len(switch_body):
            m = when_pattern.search(switch_body, pos)
            if not m:
                break
            label_str = m.group(1).strip()

            # Extraire le body du when
            when_start = m.end()
            depth = 1
            j = when_start
            while j < len(switch_body) and depth > 0:
                if switch_body[j] == "{":
                    depth += 1
                elif switch_body[j] == "}":
                    depth -= 1
                j += 1
            when_body = self._parse_block(switch_body[when_start:j - 1])

            if label_str == "else":
                cases.append((None, when_body))
            else:
                # Parser les valeurs (peut être: 'a', 'b' séparés par virgule)
                values = []
                for v in self._split_args_str(label_str):
                    v = v.strip()
                    values.append(self._parse_expr(v))
                cases.append((values, when_body))

            pos = j

        return SwitchWhen(expr=expr, cases=cases)

    def _parse_call_args(self, args_str: str) -> list:
        """Parse les arguments d'un appel de méthode en list[Expr]."""
        raw = self._split_args_str(args_str)
        return [self._parse_expr(a) for a in raw if a.strip()]

    def _split_args_str(self, s: str) -> list:
        """Split par virgule en respectant parenthèses et strings (avec escaped quotes)."""
        parts = []
        current = ""
        depth = 0
        in_string = False
        i = 0
        while i < len(s):
            ch = s[i]
            if in_string and ch == "\\" and i + 1 < len(s) and s[i + 1] == "'":
                # Escaped quote — skip
                current += ch + s[i + 1]
                i += 2
                continue
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
            i += 1
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

        # Ternaire : cond ? then : else (priorité la plus basse)
        ternary_parts = self._split_ternary(expr)
        if ternary_parts:
            cond, then_expr, else_expr = ternary_parts
            return Ternary(
                condition=self._parse_expr(cond),
                then_expr=self._parse_expr(then_expr),
                else_expr=self._parse_expr(else_expr),
            )

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

        # String literal (supports escaped quotes: 'Avis d\'annulation')
        if expr.startswith("'") and expr.endswith("'"):
            inner = expr[1:-1].replace("\\'", "'")
            return StringLiteral(value=inner)

        # Boolean
        if expr == "true":
            return BooleanLiteral(value=True)
        if expr == "false":
            return BooleanLiteral(value=False)

        # Null
        if expr == "null":
            return NullLiteral()

        # Integer / Decimal
        if expr.isdigit():
            return IntegerLiteral(value=int(expr))
        if re.match(r'^\d+\.\d+$', expr):
            return IntegerLiteral(value=float(expr))

        # new ClassName('args') as expression (exceptions, inner classes)
        new_expr_match = re.match(r'new\s+(\w+)\((.*)?\)$', expr, re.DOTALL)
        if new_expr_match:
            cls_name = new_expr_match.group(1)
            args_str = new_expr_match.group(2) or ""
            args = self._parse_call_args(args_str) if args_str.strip() else []
            # Pour les exceptions, on retourne un NewSObject avec un champ message
            if args:
                fields = {"message": args[0]}
                return NewSObject(sobject_type=cls_name, fields=fields)
            return NewSObject(sobject_type=cls_name, fields={})

        # Method call: obj.method(args) — peut être chaîné
        method_expr_match = re.match(r'(\w+)\.(\w+)\(', expr, re.DOTALL)
        if method_expr_match:
            return self._parse_method_chain(expr)

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
            if in_string and ch == "\\" and i + 1 < len(expr) and expr[i + 1] == "'":
                current += ch + expr[i + 1]
                i += 2
                continue
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
        """Split une expression par + en respectant les strings (avec escaped quotes)."""
        parts = []
        current = ""
        in_string = False
        i = 0
        while i < len(expr):
            ch = expr[i]
            if in_string and ch == "\\" and i + 1 < len(expr) and expr[i + 1] == "'":
                current += ch + expr[i + 1]
                i += 2
                continue
            if ch == "'" and not in_string:
                in_string = True
                current += ch
            elif ch == "'" and in_string:
                in_string = False
                current += ch
            elif ch == "+" and not in_string:
                parts.append(current.strip())
                current = ""
            else:
                current += ch
            i += 1

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

    def _parse_method_chain(self, expr: str) -> Expr:
        """Parse une chaîne d'appels de méthodes : a.b(c).d(e).f"""
        pos = 0
        # Premier segment : obj.method(args)
        first_match = re.match(r'(\w+)\.(\w+)\(', expr)
        if not first_match:
            return Variable(name=expr)

        obj_name = first_match.group(1)
        method_name = first_match.group(2)
        paren_start = first_match.end() - 1
        paren_end = self._matching_paren(expr, paren_start)

        args_str = expr[paren_start + 1:paren_end]
        args = self._parse_call_args(args_str) if args_str.strip() else []
        result = MethodCall(obj=obj_name, method=method_name, args=args)

        pos = paren_end + 1

        # Chaîner les appels suivants : .method(args)
        while pos < len(expr):
            chain_match = re.match(r'\.(\w+)\(', expr[pos:])
            if not chain_match:
                # Peut être un field access final : .field
                field_match = re.match(r'\.(\w+)$', expr[pos:])
                if field_match:
                    # Wrap dans un ChainedCall sans args (field access sur résultat)
                    result = ChainedCall(target=result, method=field_match.group(1), args=[])
                break

            next_method = chain_match.group(1)
            next_paren_start = pos + chain_match.end() - 1
            next_paren_end = self._matching_paren(expr, next_paren_start)
            next_args_str = expr[next_paren_start + 1:next_paren_end]
            next_args = self._parse_call_args(next_args_str) if next_args_str.strip() else []
            result = ChainedCall(target=result, method=next_method, args=next_args)
            pos = next_paren_end + 1

        return result

    def _split_ternary(self, expr: str):
        """Split une expression ternaire cond ? then : else. Retourne (cond, then, else) ou None."""
        depth = 0
        in_string = False
        q_pos = -1
        for i, ch in enumerate(expr):
            if ch == "'" and not in_string:
                in_string = True
            elif ch == "'" and in_string:
                in_string = False
            elif not in_string:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "?" and depth == 0:
                    q_pos = i
                    break

        if q_pos == -1:
            return None

        cond = expr[:q_pos].strip()
        rest = expr[q_pos + 1:]

        # Trouver le : correspondant
        depth = 0
        in_string = False
        for i, ch in enumerate(rest):
            if ch == "'" and not in_string:
                in_string = True
            elif ch == "'" and in_string:
                in_string = False
            elif not in_string:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == ":" and depth == 0:
                    return (cond, rest[:i].strip(), rest[i + 1:].strip())

        return None
