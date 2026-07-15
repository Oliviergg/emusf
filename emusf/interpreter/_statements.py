"""Interpréteur Apex — StatementsMixin."""

from __future__ import annotations

from ..ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject, NewInstance,
    MethodCall, ChainedCall, Ternary, NewList, NewMap, NewMapInit,
    ArrayAccess, NewArray, CastExpr,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
    ForCStyle, WhileLoop, DoWhile, ThrowStmt, BreakStmt, ContinueStmt, Increment, Decrement,
    MethodDef, ClassDef, NewSet, SwitchWhen, RunAs,
)
from ._helpers import (
    ReturnException, ApexException, BreakException, ContinueException,
    format_error, _common_prefix_len, _common_prefix, _unescape_html,
    _json_clean, _apex_str, _field_of, _is_soql_literal, _blob_bytes, _ci_key, ApexToken,
)


class StatementsMixin:
    def _exec_block(self, block: Block):
        try:
            for stmt in block.statements:
                self._exec_stmt(stmt)
        except ReturnException:
            pass  # return au top level = fin d'exécution

    def _exec_stmt(self, stmt: Stmt):
        # Suivi de la ligne source courante + localisation des erreurs runtime
        if getattr(stmt, "line", None) is not None:
            self._current_line = stmt.line
        try:
            self._exec_stmt_body(stmt)
        except (ReturnException, BreakException, ContinueException):
            raise
        except Exception as e:
            # Attacher la localisation au plus près de l'erreur (la première
            # frame qui l'attrape porte la bonne ligne/classe) ; ne pas écraser
            if not getattr(e, "_emusf_location", None):
                # Classe qui DÉFINIT la méthode courante (pas la classe concrète
                # de l'instance) — la ligne vient de ce fichier-là
                cls = self._current_method_class or (
                    self._current_class.name if self._current_class else None)
                e._emusf_location = (cls, self._current_line)
            raise

    def _exec_stmt_body(self, stmt: Stmt):
        if isinstance(stmt, VarDecl):
            self.variables[stmt.var_name] = self._eval(stmt.value)

        elif isinstance(stmt, Assign):
            val = self._eval(stmt.value)
            # Réutiliser la variable existante quelle que soit sa casse (Apex)
            var_name = stmt.var_name
            if var_name not in self.variables:
                var_name = _ci_key(self.variables, var_name) or var_name
            self.variables[var_name] = val
            # Synchroniser la variable statique si elle existe (ClassName.field)
            if self._current_class and var_name in self._current_class.constants:
                self.variables["{}.{}".format(self._current_class.name, var_name)] = val
            # Synchroniser le champ d'instance si assigné sans this.
            if self._current_instance is not None and var_name not in ("_type", "_class", "_chain"):
                ikey = _ci_key(self._current_instance, var_name)
                if ikey is not None and ikey not in ("_type", "_class", "_chain"):
                    self._current_instance[ikey] = val

        elif isinstance(stmt, FieldSet):
            # this.field = value
            if stmt.obj == "this" and self._current_instance is not None:
                self._current_instance[stmt.field] = self._eval(stmt.value)
                return

            obj = self.variables.get(stmt.obj)
            if obj is None and stmt.obj not in self.variables:
                okey = _ci_key(self.variables, stmt.obj)
                if okey is not None:
                    obj = self.variables[okey]
            if isinstance(obj, list):
                # Array index set: arr[i] = val
                try:
                    # field might be a variable name or expression
                    idx = self.variables.get(stmt.field)
                    if idx is None:
                        idx = int(stmt.field)
                    obj[int(idx)] = self._eval(stmt.value)
                    return
                except (ValueError, TypeError):
                    pass
            if isinstance(obj, dict):
                # Écrire dans le champ existant quelle que soit sa casse
                fkey = _ci_key(obj, stmt.field) or stmt.field
                obj[fkey] = self._eval(stmt.value)
            elif obj is None:
                # Null safety — create the object on the fly (Apex allows setting fields on null refs that were just declared)
                return
            else:
                raise Exception("'{}' n'est pas un SObject".format(stmt.obj))

        elif isinstance(stmt, SOQLAssign):
            results = self.org.execute_soql(stmt.soql, context=self._soql_context())
            # SELECT COUNT() FROM ... → assign integer
            soql_upper = stmt.soql.upper()
            if "COUNT()" in soql_upper and "SELECT COUNT()" in soql_upper:
                self.variables[stmt.var_name] = len(results) if isinstance(results, list) else 0
            elif not stmt.is_list and isinstance(results, list):
                # Single SObject assignment: take first result or None
                self.variables[stmt.var_name] = results[0] if results else None
            else:
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
            # SOQL inline : for (X x : [SELECT ...]) — le builder produit un
            # StringLiteral '[SELECT ...]' qu'il faut exécuter, pas itérer dessus
            if isinstance(stmt.list_expr, StringLiteral) and \
                    _is_soql_literal(stmt.list_expr.value):
                items = self.org.execute_soql(stmt.list_expr.value, context=self._soql_context())
            else:
                items = self._eval(stmt.list_expr)
            if items is None or not hasattr(items, '__iter__') or isinstance(items, (str, dict)):
                items = [] if items is None or isinstance(items, bool) else [items]
            for item in items:
                self.variables[stmt.iter_var] = item
                try:
                    for body_stmt in stmt.body:
                        self._exec_stmt(body_stmt)
                except BreakException:
                    break
                except ContinueException:
                    continue

        elif isinstance(stmt, Return):
            # return [SELECT ...] : exécuter la requête, puis coercer selon le
            # type de retour de la méthode (SObject unique -> 1re ligne,
            # List<X> -> toutes les lignes)
            if isinstance(stmt.value, StringLiteral) and \
                    _is_soql_literal(stmt.value.value):
                rows = self.org.execute_soql(stmt.value.value, context=self._soql_context())
                rt = (self._current_return_type or "").strip()
                is_collection = rt[:5].lower() in ("list<", "set<", "map<") or rt.endswith("[]")
                if is_collection:
                    raise ReturnException(rows)
                raise ReturnException(rows[0] if rows else None)
            value = self._eval(stmt.value) if stmt.value else None
            raise ReturnException(value)

        elif isinstance(stmt, MethodCallStmt):
            self._eval(stmt.call)

        elif isinstance(stmt, SwitchWhen):
            val = self._eval(stmt.expr)
            matched = False
            for case_values, case_body in stmt.cases:
                if case_values is None:
                    continue  # else — handled below
                for cv in case_values:
                    cv_val = self._eval(cv)
                    if cv_val == val:
                        matched = True
                        break
                    # Cas enum : `when BEFORE_INSERT` — l'identifiant n'est pas
                    # une variable ; matcher son nom contre la valeur (string)
                    if (cv_val is None and isinstance(cv, Variable)
                            and isinstance(val, str)
                            and cv.name.lower() == val.lower()):
                        matched = True
                        break
                if matched:
                    for s in case_body:
                        self._exec_stmt(s)
                    break
            if not matched:
                # Execute else clause if present
                for case_values, case_body in stmt.cases:
                    if case_values is None:
                        for s in case_body:
                            self._exec_stmt(s)
                        break

        elif isinstance(stmt, RunAs):
            user = self._eval(stmt.user)
            saved_user = self._current_user
            saved_profile = self._current_profile
            self._current_user = user if isinstance(user, dict) else None
            self._current_profile = self._resolve_profile_name(self._current_user)
            try:
                for s in stmt.body:
                    self._exec_stmt(s)
            finally:
                self._current_user = saved_user
                self._current_profile = saved_profile

        elif isinstance(stmt, ForCStyle):
            if stmt.init:
                self._exec_stmt(stmt.init)
            max_iter = 100000
            count = 0
            while self._is_truthy(self._eval(stmt.condition)):
                try:
                    for s in stmt.body:
                        self._exec_stmt(s)
                except BreakException:
                    break
                except ContinueException:
                    pass
                if stmt.update:
                    self._exec_stmt(stmt.update)
                count += 1
                if count > max_iter:
                    raise Exception("Boucle infinie détectée")

        elif isinstance(stmt, WhileLoop):
            max_iter = 100000
            count = 0
            while self._is_truthy(self._eval(stmt.condition)):
                try:
                    for s in stmt.body:
                        self._exec_stmt(s)
                except BreakException:
                    break
                except ContinueException:
                    pass
                count += 1
                if count > max_iter:
                    raise Exception("Boucle infinie détectée")

        elif isinstance(stmt, DoWhile):
            max_iter = 100000
            count = 0
            while True:
                try:
                    for s in stmt.body:
                        self._exec_stmt(s)
                except BreakException:
                    break
                except ContinueException:
                    pass
                count += 1
                if count > max_iter:
                    raise Exception("Boucle infinie détectée")
                if not self._is_truthy(self._eval(stmt.condition)):
                    break

        elif isinstance(stmt, BreakStmt):
            raise BreakException()

        elif isinstance(stmt, ContinueStmt):
            raise ContinueException()

        elif isinstance(stmt, Increment):
            val = self.variables.get(stmt.var_name, 0)
            self.variables[stmt.var_name] = val + 1

        elif isinstance(stmt, Decrement):
            val = self.variables.get(stmt.var_name, 0)
            self.variables[stmt.var_name] = val - 1

        elif isinstance(stmt, ThrowStmt):
            val = self._eval(stmt.expr)
            if isinstance(val, dict):
                msg = val.get("message", val.get("getMessage", str(val)))
            else:
                msg = str(val) if val else "Exception"
            raise ApexException(msg)

        elif isinstance(stmt, TryCatch):
            try:
                for s in stmt.try_body:
                    self._exec_stmt(s)
            except ReturnException:
                raise
            except (ApexException, Exception) as e:
                self.variables[stmt.catch_var] = {
                    "getMessage": str(e),
                    "message": str(e),
                    "_type": stmt.catch_type,
                }
                for s in stmt.catch_body:
                    self._exec_stmt(s)

        else:
            raise Exception("Statement inconnu: {}".format(type(stmt).__name__))

    # --- DML ---

    def _exec_dml_insert(self, stmt: DmlInsert):
        record = self.variables.get(stmt.var_name)
        if record is None:
            raise Exception("Variable '{}' non définie".format(stmt.var_name))

        # Bulk insert: if record is a list, insert all
        if isinstance(record, list):
            if not record:
                return
            sobject = record[0].get("_sobject_type") if isinstance(record[0], dict) else None
            if not sobject:
                raise Exception("Records sans type SObject")
            data_list = [{k: v for k, v in r.items() if k != "_sobject_type"} for r in record]
            result = self.org.insert(sobject, data_list)
            for i, r in enumerate(record):
                r["Id"] = result.record_ids[i]
            print("DML: INSERT {} x{} -> Ids={}".format(sobject, len(record), result.record_ids[:3]))
            return

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

        if isinstance(record, list):
            if not record:
                return
            sobject = record[0].get("_sobject_type") if isinstance(record[0], dict) else None
            if not sobject:
                return
            data_list = [{k: v for k, v in r.items() if k != "_sobject_type"} for r in record]
            self.org.update(sobject, data_list)
            print("DML: UPDATE {} x{}".format(sobject, len(record)))
            return

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

        if isinstance(record, list):
            if not record:
                return
            sobject = record[0].get("_sobject_type") if isinstance(record[0], dict) else None
            ids = [r.get("Id", r.get("id")) for r in record if isinstance(r, dict)]
            if sobject and ids:
                self.org.delete(sobject, ids)
                print("DML: DELETE {} x{}".format(sobject, len(ids)))
            return

        sobject = record.get("_sobject_type")
        record_id = record.get("Id")
        if not record_id:
            raise Exception("DELETE sans Id")
        self.org.delete(sobject, [record_id])
        print("DML: DELETE {} Id={}".format(sobject, record_id))

    # --- Expression evaluation ---
