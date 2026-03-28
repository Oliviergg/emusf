"""Parser Apex → AST. Transforme du code source Apex en arbre de nœuds."""

from __future__ import annotations

import re
from typing import Optional

from .lexer import Lexer, TokenType
from .token_parser import TokenStream, parse_expression as token_parse_expr

from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject,
    MethodCall, ChainedCall, Ternary, NewList, NewMap,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
    ForCStyle, WhileLoop, DoWhile, ThrowStmt, BreakStmt, ContinueStmt, Increment, Decrement,
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
        instance_fields = {}
        constructors = []
        inner_classes = {}

        self._parse_class_members(class_body, constants, methods,
                                  instance_fields, constructors, inner_classes,
                                  class_name)

        # Extraire parent class
        parent_class = None
        extends_match = re.search(r'\bextends\s+(\w+)', source[:start])
        if extends_match:
            parent_class = extends_match.group(1)

        return ClassDef(
            name=class_name,
            constants=constants,
            methods=methods,
            sharing=sharing,
            instance_fields=instance_fields,
            constructors=constructors,
            inner_classes=inner_classes,
            parent_class=parent_class,
        )

    def _parse_class_members(self, body: str, constants: dict, methods: dict,
                             instance_fields: dict, constructors: list,
                             inner_classes: dict, class_name: str):
        """Parse les membres d'une classe."""
        # Strip single-line comments (but not inside strings)
        cleaned_lines = []
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            # Remove inline // comments (naive but sufficient)
            in_str = False
            for ci, ch in enumerate(line):
                if ch == "'" and not in_str:
                    in_str = True
                elif ch == "'" and in_str:
                    in_str = False
                elif ch == "/" and ci + 1 < len(line) and line[ci + 1] == "/" and not in_str:
                    line = line[:ci]
                    break
            cleaned_lines.append(line)
        body = "\n".join(cleaned_lines)

        # --- 1. Find inner classes first ---
        inner_pattern = re.compile(
            r'(?:public|private|protected|global)\s+'
            r'(?:virtual\s+|abstract\s+)?'
            r'class\s+(\w+)'
            r'(?:\s+extends\s+\w+)?'
            r'(?:\s+implements\s+[\w,\s]+)?'
            r'\s*\{',
        )
        inner_positions = []
        for m in inner_pattern.finditer(body):
            inner_name = m.group(1)
            if inner_name == class_name:
                continue  # Skip the outer class itself
            bstart = m.end()
            depth = 1
            j = bstart
            while j < len(body) and depth > 0:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                j += 1
            inner_body = body[bstart:j - 1]
            inner_positions.append((m.start(), j))

            # Parse inner class recursively
            ic_constants = {}
            ic_methods = {}
            ic_instance_fields = {}
            ic_constructors = []
            ic_inner = {}
            self._parse_class_members(inner_body, ic_constants, ic_methods,
                                      ic_instance_fields, ic_constructors,
                                      ic_inner, inner_name)
            inner_classes[inner_name] = ClassDef(
                name=inner_name,
                constants=ic_constants,
                methods=ic_methods,
                instance_fields=ic_instance_fields,
                constructors=ic_constructors,
                inner_classes=ic_inner,
            )

        # --- 2. Find methods and constructors ---
        method_pattern = re.compile(
            r'(?:(?:public|private|protected|global)\s+)?'
            r'(?:(?:static|override|virtual|abstract)\s+)*'
            r'(\w+(?:<[\w,\s]+>)?(?:\[\])?)\s+'  # return type
            r'(\w+)\s*'  # method name
            r'\(([^)]*)\)\s*\{',  # params
            re.DOTALL
        )

        method_positions = []
        for m in method_pattern.finditer(body):
            # Skip if inside an inner class
            in_inner = False
            for istart, iend in inner_positions:
                if istart <= m.start() <= iend:
                    in_inner = True
                    break
            if in_inner:
                continue

            return_type = m.group(1)
            method_name = m.group(2)
            params_str = m.group(3)

            if return_type == "class":
                continue

            # Extract method body
            bstart = m.end()
            depth = 1
            j = bstart
            while j < len(body) and depth > 0:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                j += 1
            method_body = body[bstart:j - 1]
            method_positions.append((m.start(), j))

            # Parse params
            params = []
            if params_str.strip():
                for p in params_str.split(","):
                    p = p.strip()
                    parts = p.rsplit(None, 1)
                    if len(parts) == 2:
                        params.append((parts[0], parts[1]))

            # Detect static
            prefix_line = body[max(0, m.start() - 150):m.start()].split("\n")[-1]
            full_sig = prefix_line + m.group(0)
            is_static = "static" in full_sig

            method_stmts = self._parse_block(method_body)

            # Constructor: method name == class name
            if method_name == class_name:
                constructors.append(MethodDef(
                    name=method_name,
                    return_type="void",
                    params=params,
                    body=method_stmts,
                    is_static=False,
                ))
            else:
                methods[method_name] = MethodDef(
                    name=method_name,
                    return_type=return_type,
                    params=params,
                    body=method_stmts,
                    is_static=is_static,
                )

        # --- 3. Find fields (static constants and instance variables) ---
        field_header = re.compile(
            r'(?:(?:public|private|protected|global)\s+)'
            r'((?:static\s+)?(?:final\s+)?)'
            r'([\w<>,\s]+?)\s+'
            r'(\w+)\s*'
            r'(?:=\s*|;)',
        )
        for m in field_header.finditer(body):
            # Skip if inside a method or inner class
            in_member = False
            for ms, me in method_positions + inner_positions:
                if ms <= m.start() <= me:
                    in_member = True
                    break
            if in_member:
                continue

            modifiers = m.group(1).strip()
            type_name = m.group(2).strip()
            var_name = m.group(3)
            is_static = "static" in modifiers

            # Check if it has an initializer (=) or just declaration (;)
            matched_end = m.group(0)
            has_init = "=" in matched_end
            if has_init:
                val_start = m.end()
                value_str = self._extract_until_semi(body, val_start)
                if value_str is not None:
                    try:
                        value_expr = self._parse_expr(value_str)
                        if is_static:
                            constants[var_name] = (type_name, value_expr)
                        else:
                            instance_fields[var_name] = type_name
                            constants[var_name] = (type_name, value_expr)
                    except Exception:
                        if not is_static:
                            instance_fields[var_name] = type_name
            else:
                # Declaration without init
                if is_static:
                    pass  # Static without init — skip
                else:
                    instance_fields[var_name] = type_name

    def _extract_until_semi(self, source: str, start: int) -> Optional[str]:
        """Extrait le texte de start jusqu'au ; en respectant {}, () et strings."""
        depth = 0
        in_string = False
        i = start
        while i < len(source):
            ch = source[i]
            if in_string:
                if ch == "\\" and i + 1 < len(source) and source[i + 1] == "'":
                    i += 2
                    continue
                if ch == "'":
                    in_string = False
            else:
                if ch == "'":
                    in_string = True
                elif ch in ("(", "{", "["):
                    depth += 1
                elif ch in (")", "}", "]"):
                    depth -= 1
                elif ch == ";" and depth == 0:
                    return source[start:i].strip()
            i += 1
        return None

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
        """Découpe un bloc en statements bruts (gère les { }, strings et else/catch)."""
        statements = []
        depth = 0
        current = ""
        in_string = False
        i = 0

        while i < len(block):
            char = block[i]
            current += char

            if in_string:
                if char == "\\" and i + 1 < len(block) and block[i + 1] == "'":
                    current += block[i + 1]
                    i += 2
                    continue
                if char == "'":
                    in_string = False
            else:
                if char == "'":
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        rest = block[i + 1:].lstrip()
                        if rest.startswith("else") or rest.startswith("catch"):
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

        # --- for (...) { body } ---
        for_start = re.match(r'for\s*\(', stmt)
        if for_start:
            return self._parse_for(stmt)

        # --- if (...) { ... } else if (...) { ... } else { ... } ---
        if_match = re.match(r'if\s*\((.+?)\)\s*\{', stmt)
        if if_match:
            return self._parse_if(stmt)

        # --- do { body } while (cond); ---
        do_match = re.match(r'do\s*\{(.*)\}\s*while\s*\((.+?)\)\s*;?$', stmt, re.DOTALL)
        if do_match:
            body = self._parse_block(do_match.group(1))
            cond = self._parse_expr(do_match.group(2))
            return DoWhile(condition=cond, body=body)

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

        # --- break; ---
        if stmt.rstrip(";").strip() == "break":
            return BreakStmt()

        # --- continue; ---
        if stmt.rstrip(";").strip() == "continue":
            return ContinueStmt()

        # --- var++ / var-- ---
        inc_match = re.match(r'(\w+)\+\+\s*;?$', stmt)
        if inc_match:
            return Increment(var_name=inc_match.group(1))
        dec_match = re.match(r'(\w+)--\s*;?$', stmt)
        if dec_match:
            return Decrement(var_name=dec_match.group(1))
        # ++var / --var
        inc_match2 = re.match(r'\+\+(\w+)\s*;?$', stmt)
        if inc_match2:
            return Increment(var_name=inc_match2.group(1))
        dec_match2 = re.match(r'--(\w+)\s*;?$', stmt)
        if dec_match2:
            return Decrement(var_name=dec_match2.group(1))

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

        # --- arr[index] = expr; ---
        arr_assign_match = re.match(r'(\w+)\[(.+?)\]\s*=\s*(.+?)\s*;?$', stmt)
        if arr_assign_match:
            arr_name = arr_assign_match.group(1)
            # Encode as FieldSet with index as field (handled by interpreter)
            index_str = arr_assign_match.group(2)
            value_str = arr_assign_match.group(3)
            return FieldSet(
                obj=arr_name,
                field=index_str,  # Will be resolved as index in interpreter
                value=self._parse_expr(value_str),
            )

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

        # --- List<SObject> var = [SOQL]; --- (only if content starts with SELECT)
        soql_match = re.match(
            r'(?:List<(\w+)>\s+)?(\w+)\s*=\s*\[(\s*SELECT.+?)\]\s*;?$',
            stmt, re.DOTALL | re.IGNORECASE
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

        # --- Type var = new Type(...); or Type var = new Type(); ---
        # Delegate to _parse_expr which uses the token parser
        new_match = re.match(
            r'(\w+(?:<[\w,\s]+>)?)\s+(\w+)\s*=\s*(new\s+.+?)\s*;?$',
            stmt, re.DOTALL
        )
        if new_match and "new " in new_match.group(3):
            return VarDecl(
                type_name=new_match.group(1),
                var_name=new_match.group(2),
                value=self._parse_expr(new_match.group(3)),
            )

        # --- Type var = expr; --- (supports Map<String, String>, List<Account>, String[], etc.)
        decl_match = re.match(r'(\w+(?:<[\w,\s]+>)?(?:\[\])?)\s+(\w+)\s*=\s*(.+?)\s*;?$', stmt)
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

    def _parse_for(self, stmt: str):
        """Parse for-each ou for C-style."""
        # Extraire le contenu entre les parenthèses du for(...)
        paren_start = stmt.index("(")
        depth = 1
        i = paren_start + 1
        while i < len(stmt) and depth > 0:
            if stmt[i] == "(":
                depth += 1
            elif stmt[i] == ")":
                depth -= 1
            i += 1
        header = stmt[paren_start + 1:i - 1].strip()
        rest = stmt[i:].strip()

        # Extraire le body { ... }
        if rest.startswith("{"):
            body_start = 1
            depth = 1
            j = body_start
            while j < len(rest) and depth > 0:
                if rest[j] == "{":
                    depth += 1
                elif rest[j] == "}":
                    depth -= 1
                j += 1
            body_str = rest[body_start:j - 1]
        else:
            body_str = rest

        body_stmts = self._parse_block(body_str)

        # Déterminer : for-each (contient ":") ou C-style (contient ";")
        if ":" in header and ";" not in header:
            # for (Type var : expr)
            colon_pos = header.index(":")
            left = header[:colon_pos].strip()
            right = header[colon_pos + 1:].strip()
            parts = left.rsplit(None, 1)
            if len(parts) == 2:
                iter_type, iter_var = parts
            else:
                iter_type, iter_var = "var", parts[0]
            list_expr = self._parse_expr(right)
            return ForEach(
                iter_type=iter_type,
                iter_var=iter_var,
                list_expr=list_expr,
                body=body_stmts,
            )
        else:
            # for (init; condition; update) — C-style
            # Split par ; en respectant les parenthèses
            parts = self._split_for_header(header)
            if len(parts) == 3:
                init_str, cond_str, update_str = parts
                init_stmt = self._parse_statement(init_str + ";") if init_str.strip() else None
                cond_expr = self._parse_expr(cond_str) if cond_str.strip() else BooleanLiteral(value=True)
                update_stmt = self._parse_statement(update_str + ";") if update_str.strip() else None
                return ForCStyle(
                    init=init_stmt,
                    condition=cond_expr,
                    update=update_stmt,
                    body=body_stmts,
                )
            # Fallback — try as for-each
            return None

    def _split_for_header(self, header: str) -> list:
        """Split le header for par ; en respectant parenthèses et strings."""
        parts = []
        current = ""
        depth = 0
        in_string = False
        for ch in header:
            if in_string:
                if ch == "\\" and len(current) > 0:
                    current += ch
                    continue
                if ch == "'":
                    in_string = False
                current += ch
            else:
                if ch == "'":
                    in_string = True
                    current += ch
                elif ch == "(":
                    depth += 1
                    current += ch
                elif ch == ")":
                    depth -= 1
                    current += ch
                elif ch == ";" and depth == 0:
                    parts.append(current.strip())
                    current = ""
                else:
                    current += ch
        parts.append(current.strip())
        return parts

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

    def _parse_expr(self, expr_str: str) -> Expr:
        """Parse une expression Apex via le token-based parser."""
        expr_str = expr_str.strip()
        if not expr_str:
            return NullLiteral()
        try:
            tokens = Lexer(expr_str).tokenize()
            stream = TokenStream(tokens)
            result = token_parse_expr(stream)
            # Vérifier qu'on a bien consommé tous les tokens
            if stream.current().type != TokenType.EOF:
                # Fallback sur l'ancien parser si le token parser ne consomme pas tout
                return self._parse_expr_legacy(expr_str)
            return result
        except Exception:
            return self._parse_expr_legacy(expr_str)

    def _parse_expr_legacy(self, expr: str) -> Expr:
        """Ancien parser regex — fallback."""
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
