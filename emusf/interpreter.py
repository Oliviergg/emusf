"""Interpréteur Apex — parcourt un AST et exécute."""

from __future__ import annotations

from .org import FakeOrg
from .apex_parser import ApexParser
from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject, NewInstance,
    MethodCall, ChainedCall, Ternary, NewList, NewMap, NewMapInit,
    ArrayAccess, NewArray, CastExpr,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
    ForCStyle, WhileLoop, DoWhile, ThrowStmt, BreakStmt, ContinueStmt, Increment, Decrement,
    MethodDef, ClassDef, NewSet, SwitchWhen,
)


class ReturnException(Exception):
    """Signal interne pour return."""

    def __init__(self, value=None):
        self.value = value


class ApexException(Exception):
    """Exception Apex (throw new ...)."""
    pass


class BreakException(Exception):
    pass


class ContinueException(Exception):
    pass


class ApexInterpreter:
    """
    Interprète un AST Apex.
    Le parsing est délégué à ApexParser.
    """

    def __init__(self, org):
        self.org = org
        self.parser = ApexParser()
        self.variables = {}
        self.output = []
        self.classes = {}  # {class_name: ClassDef}
        self._current_class = None  # ClassDef en cours d'exécution
        self._current_instance = None  # Instance en cours (pour this)

    def load_class(self, path_or_source: str, is_path: bool = True):
        """Charge une classe Apex dans l'interpréteur."""
        if is_path:
            with open(path_or_source) as f:
                source = path_or_source = f.read()
        else:
            source = path_or_source
        class_def = self.parser.parse_full_class(source)
        self.classes[class_def.name] = class_def
        # Charger les constantes dans les variables sous namespace ClassName.CONST
        for name, (type_name, expr) in class_def.constants.items():
            self.variables["{}.{}".format(class_def.name, name)] = self._eval(expr)
        return class_def

    def call_method(self, class_name: str, method_name: str, args: list = None):
        """Appelle une méthode statique d'une classe chargée."""
        if args is None:
            args = []
        class_def = self.classes.get(class_name)
        if not class_def:
            raise Exception("Classe '{}' non chargée".format(class_name))
        method = class_def.methods.get(method_name)
        if not method:
            raise Exception("Méthode '{}.{}' non trouvée".format(class_name, method_name))
        return self._invoke_method(class_def, method, args)

    def execute_file(self, path: str, method: str = "run"):
        """Charge un .cls, parse en AST, puis exécute."""
        with open(path) as f:
            source = f.read()
        ast = self.parser.parse_class(source, method)
        self._exec_block(ast)

    # --- Statement execution ---

    def _exec_block(self, block: Block):
        try:
            for stmt in block.statements:
                self._exec_stmt(stmt)
        except ReturnException:
            pass  # return au top level = fin d'exécution

    def _exec_stmt(self, stmt: Stmt):
        if isinstance(stmt, VarDecl):
            self.variables[stmt.var_name] = self._eval(stmt.value)

        elif isinstance(stmt, Assign):
            self.variables[stmt.var_name] = self._eval(stmt.value)

        elif isinstance(stmt, FieldSet):
            # this.field = value
            if stmt.obj == "this" and self._current_instance is not None:
                self._current_instance[stmt.field] = self._eval(stmt.value)
                return

            obj = self.variables.get(stmt.obj)
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
                obj[stmt.field] = self._eval(stmt.value)
            elif obj is None:
                raise Exception("'{}' is null".format(stmt.obj))
            else:
                raise Exception("'{}' n'est pas un SObject".format(stmt.obj))

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
                try:
                    for body_stmt in stmt.body:
                        self._exec_stmt(body_stmt)
                except BreakException:
                    break
                except ContinueException:
                    continue

        elif isinstance(stmt, Return):
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
                    if self._eval(cv) == val:
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

    def _eval(self, expr: Expr):
        if isinstance(expr, StringLiteral):
            return expr.value

        elif isinstance(expr, IntegerLiteral):
            return expr.value

        elif isinstance(expr, BooleanLiteral):
            return expr.value

        elif isinstance(expr, NullLiteral):
            return None

        elif isinstance(expr, Variable):
            if expr.name == "this":
                return self._current_instance
            return self.variables.get(expr.name)

        elif isinstance(expr, FieldAccess):
            # this.field
            if expr.obj == "this" and self._current_instance is not None:
                return self._current_instance.get(expr.field)

            # System.Label → return empty string for custom labels
            if expr.obj == "System" and expr.field == "Label":
                return {"_type": "SystemLabel"}
            # ParentJobResult.SUCCESS / FAILURE
            if expr.obj == "ParentJobResult":
                return expr.field

            # Constante de classe : ClassName.CONST
            class_key = "{}.{}".format(expr.obj, expr.field)
            if class_key in self.variables:
                return self.variables[class_key]
            obj = self.variables.get(expr.obj)
            if isinstance(obj, dict):
                return obj.get(expr.field, "null")
            if isinstance(obj, list):
                return "null"
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
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    return left + right
                return str(left) + str(right)
            elif expr.op == "-":
                return left - right
            elif expr.op == "*":
                return left * right
            elif expr.op == "/":
                return left / right
            elif expr.op == "==":
                return left == right
            elif expr.op == "!=":
                return left != right
            elif expr.op == "<":
                if left is None or right is None:
                    return False
                return left < right
            elif expr.op == ">":
                if left is None or right is None:
                    return False
                return left > right
            elif expr.op == "<=":
                if left is None or right is None:
                    return False
                return left <= right
            elif expr.op == ">=":
                if left is None or right is None:
                    return False
                return left >= right
            elif expr.op == "&&":
                return self._is_truthy(left) and self._is_truthy(right)
            elif expr.op == "||":
                return self._is_truthy(left) or self._is_truthy(right)
            raise Exception("Opérateur inconnu: {}".format(expr.op))

        elif isinstance(expr, NewSObject):
            # Special system types
            if expr.sobject_type in ("HttpRequest", "Http", "HttpResponse"):
                obj = {"_type": expr.sobject_type}
                for field, val_expr in expr.fields.items():
                    obj[field] = self._eval(val_expr)
                return obj

            # Check if it's a class (empty constructor: new ClassName())
            if not expr.fields:
                class_def = self._resolve_class(expr.sobject_type)
                if class_def and (class_def.constructors or class_def.instance_fields or
                                  any(not m.is_static for m in class_def.methods.values())):
                    return self._create_instance(class_def, [])

            # SObject with named fields
            record = {"_sobject_type": expr.sobject_type}
            for field, val_expr in expr.fields.items():
                record[field] = self._eval(val_expr)
            return record

        elif isinstance(expr, NewList):
            return [self._eval(v) for v in expr.init_values]

        elif isinstance(expr, NewMap):
            return {}

        elif isinstance(expr, NewMapInit):
            return {self._eval(k): self._eval(v) for k, v in expr.entries}

        elif isinstance(expr, NewInstance):
            args = [self._eval(a) for a in expr.args]
            class_def = self._resolve_class(expr.class_name)
            if class_def is not None:
                instance = self._create_instance(class_def, args)
                return instance
            # Fallback: exception or unknown class
            obj = {"_sobject_type": expr.class_name}
            if args:
                obj["message"] = args[0]
            return obj

        elif isinstance(expr, NewSet):
            return set(self._eval(v) for v in expr.init_values)

        elif isinstance(expr, Ternary):
            cond = self._eval(expr.condition)
            if self._is_truthy(cond):
                return self._eval(expr.then_expr)
            return self._eval(expr.else_expr)

        elif isinstance(expr, ChainedCall):
            target = self._eval(expr.target)
            args = [self._eval(a) for a in expr.args]

            # Instance method call
            if isinstance(target, dict) and "_class" in target:
                cls = target["_class"]
                if expr.method in cls.methods:
                    return self._invoke_instance_method(target, cls.methods[expr.method], args)
                # Field access on instance
                if expr.method in target:
                    return target[expr.method]

            # Field access on dict when no args
            if not args and isinstance(target, dict) and expr.method in target:
                return target[expr.method]
            if not args and isinstance(target, dict) and expr.method not in target:
                for k, v in target.items():
                    if k.lower() == expr.method.lower():
                        return v
                return None
            return self._call_on_value(target, expr.method, args)

        elif isinstance(expr, ArrayAccess):
            arr = self._eval(expr.array)
            idx = self._eval(expr.index)
            if isinstance(arr, list) and isinstance(idx, (int, float)):
                return arr[int(idx)]
            if isinstance(arr, dict):
                return arr.get(idx)
            return None

        elif isinstance(expr, NewArray):
            size = self._eval(expr.size)
            return [None] * int(size)

        elif isinstance(expr, CastExpr):
            val = self._eval(expr.expr)
            if expr.target_type in ("Integer", "int"):
                return int(val) if val is not None else 0
            elif expr.target_type in ("Double", "double", "Decimal"):
                return float(val) if val is not None else 0.0
            elif expr.target_type == "String":
                return str(val)
            elif expr.target_type == "Boolean":
                return bool(val)
            return val  # passthrough pour les types inconnus

        elif isinstance(expr, MethodCall):
            return self._exec_method_call(expr)

        else:
            raise Exception("Expression inconnue: {}".format(type(expr).__name__))

    def _exec_method_call(self, call: MethodCall):
        """Exécute un appel de méthode sur un objet ou une collection."""
        obj = self.variables.get(call.obj)
        args = [self._eval(a) for a in call.args]
        method = call.method

        # Null-safe: appeler une méthode sur null retourne null
        if obj is None and call.obj not in self.classes and call.obj not in ("_self", "_super") and call.obj not in ("String", "Integer", "System", "Test", "Date", "DateTime", "Pattern", "Matcher", "Math", "JSON", "EncodingUtil", "Crypto", "Blob", "Database", "Schema", "URL", "UserInfo", "Http", "HttpRequest", "HttpResponse", "Limits", "EventBus", "Type", "UUID"):
            # Vérifier aussi si c'est une méthode de la classe courante
            if not (self._current_class and call.method in self._current_class.methods):
                return None

        # List and Set methods → delegate to _call_on_value
        if isinstance(obj, (list, set)):
            return self._call_on_value(obj, method, args)

        # Instance method call (obj has _class) — BEFORE typed dict check
        if isinstance(obj, dict) and "_class" in obj:
            # Polymorphic: search in concrete class + parent chain
            resolved = self._resolve_method_in_chain(obj["_class"], method)
            if resolved:
                if resolved.is_static:
                    return self._invoke_method(obj["_class"], resolved, args)
                else:
                    return self._invoke_instance_method(obj, resolved, args)
            # Instance field access
            if method in obj:
                return obj[method]

        # All typed dicts (Pattern, Matcher, Date, HttpRequest, HttpResponse, etc.)
        if isinstance(obj, dict) and "_type" in obj and "_class" not in obj:
            return self._call_map_method(obj, method, args)

        # Special typed objects (fallback check) (Pattern, Matcher, Date, etc.)
        elif isinstance(obj, dict) and obj.get("_type") in ("Pattern", "Matcher", "Date", "DateTime"):
            return self._call_map_method(obj, method, args)

        # Map methods
        elif isinstance(obj, dict) and "_sobject_type" not in obj:
            if method == "put":
                if len(args) >= 2:
                    obj[args[0]] = args[1]
                return None
            elif method == "get":
                return obj.get(args[0]) if args else None
            elif method == "containsKey":
                return args[0] in obj if args else False
            elif method == "keySet":
                return list(obj.keys())
            elif method == "values":
                return list(obj.values())
            elif method == "size":
                return len(obj)
            elif method == "isEmpty":
                return len(obj) == 0
            elif method == "remove":
                return obj.pop(args[0], None) if args else None

        # String methods — delegate to _call_string_method
        elif isinstance(obj, str):
            return self._call_string_method(obj, method, args)

        # Instance method call (obj has _class)
        elif isinstance(obj, dict) and "_class" in obj:
            cls = obj["_class"]
            if method in cls.methods:
                return self._invoke_instance_method(obj, cls.methods[method], args)
            # Field access
            val = obj.get(method)
            if val is not None:
                return val

        # SObject field access via method (e.getMessage() etc.)
        elif isinstance(obj, dict):
            val = obj.get(method)
            if val is not None:
                return val

        # super(args) — appel du constructeur parent
        if call.obj == "_super" and call.method == "_init":
            if self._current_instance and "_class" in self._current_instance:
                concrete = self._current_instance["_class"]
                if concrete.parent_class:
                    parent_cls = self.classes.get(concrete.parent_class)
                    if parent_cls:
                        ctor = self._find_constructor(parent_cls, len(args))
                        if ctor:
                            self._run_constructor(self._current_instance, parent_cls, ctor, args)
            return None

        # Appel de méthode statique sur une classe chargée
        if call.obj in self.classes:
            return self.call_method(call.obj, method, args)

        # Appel de méthode locale (_self) — polymorphisme via instance concrète
        if call.obj == "_self" or (obj is None and self._current_class):
            # Chercher d'abord dans la classe concrète de l'instance (polymorphisme)
            if self._current_instance and "_class" in self._current_instance:
                concrete_class = self._current_instance["_class"]
                resolved = self._resolve_method_in_chain(concrete_class, method)
                if resolved:
                    if resolved.is_static:
                        return self._invoke_method(concrete_class, resolved, args)
                    else:
                        return self._invoke_instance_method(self._current_instance, resolved, args)
            # Fallback: chercher dans la classe courante + héritage
            if self._current_class:
                resolved = self._resolve_method_in_chain(self._current_class, method)
                if resolved:
                    return self._invoke_method(self._current_class, resolved, args)

        # String static methods
        if call.obj == "String":
            if method == "isBlank":
                v = args[0] if args else None
                return v is None or (isinstance(v, str) and v.strip() == "")
            elif method == "isNotBlank":
                v = args[0] if args else None
                return v is not None and isinstance(v, str) and v.strip() != ""
            elif method == "valueOf":
                return str(args[0]) if args else ""
            elif method == "join":
                if len(args) >= 2:
                    lst = args[0]
                    sep = args[1]
                    if isinstance(lst, list):
                        return sep.join(str(x) for x in lst)
                return ""

        # Integer static methods
        if call.obj == "Integer":
            if method == "valueOf":
                val = args[0] if args else 0
                if val is None:
                    raise ApexException("Argument cannot be null")
                return int(val)  # Lève ValueError si pas un nombre — comme Apex

        # JSON static methods
        if call.obj == "JSON":
            import json as _json
            if method == "serialize":
                return _json.dumps(args[0]) if args else "null"
            elif method == "serializePretty":
                return _json.dumps(args[0], indent=2) if args else "null"
            elif method == "deserialize":
                if len(args) >= 2 and isinstance(args[0], str):
                    return _json.loads(args[0])
                return _json.loads(args[0]) if args else None
            elif method == "deserializeUntyped":
                return _json.loads(args[0]) if args and isinstance(args[0], str) else None

        # Pattern static methods
        if call.obj == "Pattern":
            if method == "compile":
                regex_str = args[0] if args else ""
                import re as _re
                return {"_type": "Pattern", "_compiled": _re.compile(regex_str), "_pattern": regex_str}

        # Math static methods
        if call.obj == "Math":
            if method == "round":
                return round(args[0]) if args else 0
            elif method == "abs":
                return abs(args[0]) if args else 0
            elif method == "max":
                return max(args[0], args[1]) if len(args) >= 2 else (args[0] if args else 0)
            elif method == "min":
                return min(args[0], args[1]) if len(args) >= 2 else (args[0] if args else 0)
            elif method == "floor":
                import math
                return int(math.floor(args[0])) if args else 0
            elif method == "ceil":
                import math
                return int(math.ceil(args[0])) if args else 0

        # System static methods
        if call.obj == "System":
            if method == "debug":
                val = args[0] if args else ""
                self.output.append(str(val))
                print("DEBUG: {}".format(val))
                return None
            elif method == "enqueueJob":
                # Queueable pattern
                instance = args[0] if args else None
                if self.job_queue and isinstance(instance, dict) and "_class" in instance:
                    job_id = self.job_queue.enqueue(instance)
                    return job_id
                return None
            elif method == "attachFinalizer":
                return None  # No-op
            elif method == "currentTimeMillis":
                import time
                return int(time.time() * 1000)
            elif method == "today":
                import datetime
                d = datetime.date.today()
                return {"_type": "Date", "year": d.year, "month": d.month, "day": d.day}
            elif method == "now":
                import datetime
                d = datetime.datetime.now()
                return {"_type": "DateTime", "year": d.year, "month": d.month, "day": d.day}
            elif method == "abortJob":
                return None  # No-op

        # System.Label.XXX — custom labels (return empty string)
        if call.obj == "System" and method == "Label":
            return ""

        # EventBus.publish — platform events (no-op)
        if call.obj == "EventBus" and method == "publish":
            return None

        # Type.forName — reflection
        if call.obj == "Type" and method == "forName":
            class_name = args[0] if args else None
            return {"_type": "ApexType", "className": class_name}

        # UUID.randomUUID()
        if call.obj == "UUID" and method == "randomUUID":
            import uuid
            return str(uuid.uuid4())

        # Http.send() — mock (also check when obj is the Http dict)
        if call.obj == "Http":
            if method == "send":
                return {"_type": "HttpResponse", "_statusCode": 200, "_body": "{}",
                        "_headers": {}}

        # URL static methods
        if call.obj == "URL":
            if method == "getOrgDomainUrl":
                return {"_type": "URL", "_url": "https://test.salesforce.com"}

        # Blob static methods
        if call.obj == "Blob":
            if method == "valueOf":
                return args[0] if args else ""

        # EncodingUtil static methods
        if call.obj == "EncodingUtil":
            if method == "base64Encode":
                import base64
                val = args[0] if args else ""
                if isinstance(val, str):
                    return base64.b64encode(val.encode()).decode()
                return ""
            if method == "urlEncode":
                import urllib.parse
                return urllib.parse.quote(str(args[0]), safe='') if args else ""
            if method == "base64Decode":
                import base64
                return base64.b64decode(str(args[0])).decode() if args else ""

        # Date static methods
        if call.obj == "Date":
            if method == "newInstance":
                if len(args) >= 3:
                    return {"_type": "Date", "year": int(args[0]), "month": int(args[1]), "day": int(args[2])}
                return None
            if method == "today":
                import datetime
                d = datetime.date.today()
                return {"_type": "Date", "year": d.year, "month": d.month, "day": d.day}

        # DateTime static methods
        if call.obj == "DateTime":
            if method == "newInstance":
                if len(args) >= 3:
                    return {"_type": "DateTime", "year": int(args[0]), "month": int(args[1]), "day": int(args[2])}
                return None

        raise Exception("Méthode inconnue: {}.{}()".format(call.obj, method))

    def _call_on_value(self, obj, method, args):
        """Appelle une méthode sur une valeur (pour le chaînage)."""
        if isinstance(obj, str):
            return self._call_string_method(obj, method, args)
        if isinstance(obj, list):
            return self._call_list_method(obj, method, args)
        if isinstance(obj, set):
            return self._call_set_method(obj, method, args)
        if isinstance(obj, dict):
            return self._call_map_method(obj, method, args)
        raise Exception("Impossible d'appeler .{}() sur {}".format(method, type(obj).__name__))

    def _call_string_method(self, s, method, args):
        methods = {
            "length": lambda: len(s),
            "contains": lambda: args[0] in s if args else False,
            "startsWith": lambda: s.startswith(args[0]) if args else False,
            "endsWith": lambda: s.endswith(args[0]) if args else False,
            "toLowerCase": lambda: s.lower(),
            "toUpperCase": lambda: s.upper(),
            "trim": lambda: s.strip(),
            "substring": lambda: s[int(args[0]):int(args[1])] if len(args) >= 2 else s[int(args[0]):],
            "indexOf": lambda: s.find(args[0]) if args else -1,
            "replace": lambda: s.replace(args[0], args[1]) if len(args) >= 2 else s,
            "split": lambda: list(s) if args and args[0] == '' else (__import__('re').split(args[0], s) if args else [s]),
            "left": lambda: s[:int(args[0])] if args else s,
            "right": lambda: s[-int(args[0]):] if args else s,
            "removeStart": lambda: s[len(args[0]):] if args and s.startswith(args[0]) else s,
            "removeEnd": lambda: s[:-len(args[0])] if args and s.endswith(args[0]) else s,
            "leftPad": lambda: s.rjust(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "replaceAll": lambda: __import__('re').sub(args[0], args[1], s) if len(args) >= 2 else s,
            "equals": lambda: s == args[0] if args else False,
            "equalsIgnoreCase": lambda: s.lower() == args[0].lower() if args and isinstance(args[0], str) else False,
            "charAt": lambda: s[int(args[0])] if args else '',
        }
        if method in methods:
            return methods[method]()
        raise Exception("String.{}() non supporté".format(method))

    def _call_list_method(self, lst, method, args):
        methods = {
            "add": lambda: lst.append(args[0]) if args else None,
            "addAll": lambda: lst.extend(args[0]) if args else None,
            "size": lambda: len(lst),
            "isEmpty": lambda: len(lst) == 0,
            "get": lambda: lst[int(args[0])] if args else None,
            "contains": lambda: args[0] in lst if args else False,
            "remove": lambda: lst.pop(int(args[0])),
            "clear": lambda: lst.clear(),
            "sort": lambda: lst.sort(),
            "addAll": lambda: lst.extend(args[0]) if args else None,
        }
        if method in methods:
            return methods[method]()
        raise Exception("List.{}() non supporté".format(method))

    def _call_set_method(self, s, method, args):
        methods = {
            "add": lambda: s.add(args[0]) if args else None,
            "contains": lambda: args[0] in s if args else False,
            "size": lambda: len(s),
            "isEmpty": lambda: len(s) == 0,
            "remove": lambda: s.discard(args[0]) if args else None,
            "addAll": lambda: s.update(args[0]) if args and hasattr(args[0], '__iter__') else None,
        }
        if method in methods:
            return methods[method]()
        raise Exception("Set.{}() non supporté".format(method))

    def _call_map_method(self, m, method, args):
        # Pattern object
        if m.get("_type") == "Pattern":
            if method == "matcher":
                import re as _re
                text = args[0] if args else ""
                return {
                    "_type": "Matcher",
                    "_compiled": m["_compiled"],
                    "_text": str(text) if text is not None else "",
                    "_match": None,
                }
            if method == "pattern":
                return m.get("_pattern", "")

        # Matcher object
        if m.get("_type") == "Matcher":
            import re as _re
            if method == "find":
                match = m["_compiled"].search(m["_text"])
                m["_match"] = match
                return match is not None
            if method == "group":
                match = m.get("_match")
                if match is None:
                    return None
                idx = int(args[0]) if args else 0
                try:
                    return match.group(idx)
                except (IndexError, _re.error):
                    return None
            if method == "matches":
                match = m["_compiled"].fullmatch(m["_text"])
                m["_match"] = match
                return match is not None

        # SystemLabel — System.Label.XXX returns ''
        if m.get("_type") == "SystemLabel":
            return ""  # All custom labels return empty string

        # ApexType — Type.forName().newInstance()
        if m.get("_type") == "ApexType":
            if method == "newInstance":
                class_name = m.get("className")
                if class_name:
                    class_def = self._resolve_class(class_name)
                    if class_def:
                        return self._create_instance(class_def, [])
                return None

        # FinalizerContext
        if m.get("_type") == "FinalizerContext":
            if method == "getAsyncApexJobId":
                return m.get("asyncApexJobId")
            if method == "getResult":
                return m.get("result")

        # QueueableContext
        if m.get("_type") == "QueueableContext":
            if method == "getJobId":
                return m.get("jobId")

        # Http mock
        if m.get("_type") == "Http":
            if method == "send":
                return {"_type": "HttpResponse", "_statusCode": 200, "_body": "{}",
                        "_headers": {}}

        # HttpRequest mock
        if m.get("_type") == "HttpRequest":
            if method in ("setEndpoint", "setMethod", "setHeader", "setBody", "setTimeout"):
                m["_" + method[3:].lower() if method.startswith("set") else method] = args[0] if args else None
                return None
            if method == "getEndpoint":
                return m.get("_endpoint", "")
            if method == "getMethod":
                return m.get("_method", "GET")
            if method == "getBody":
                return m.get("_body", "")
            return None

        # HttpResponse mock
        if m.get("_type") == "HttpResponse":
            if method == "getStatusCode":
                return m.get("_statusCode", 200)
            if method == "getBody":
                return m.get("_body", "")
            if method == "getHeader":
                return m.get("_headers", {}).get(args[0], "") if args else ""
            if method in ("setStatusCode", "setBody", "setHeader"):
                if method == "setStatusCode":
                    m["_statusCode"] = args[0] if args else 200
                elif method == "setBody":
                    m["_body"] = args[0] if args else ""
                elif method == "setHeader" and len(args) >= 2:
                    if "_headers" not in m:
                        m["_headers"] = {}
                    m["_headers"][args[0]] = args[1]
                return None
            return None

        # URL object
        if m.get("_type") == "URL":
            if method == "toExternalForm":
                return m.get("_url", "")
            if method == "getHost":
                return m.get("_url", "").split("//")[-1].split("/")[0]
            return m.get("_url", "")

        # Date object
        if m.get("_type") == "Date":
            if method == "year":
                return m.get("year")
            if method == "month":
                return m.get("month")
            if method == "day":
                return m.get("day")
            if method == "addDays":
                import datetime
                d = datetime.date(m["year"], m["month"], m["day"])
                d2 = d + datetime.timedelta(days=int(args[0]) if args else 0)
                return {"_type": "Date", "year": d2.year, "month": d2.month, "day": d2.day}
            if method == "addMonths":
                month = m["month"] + (int(args[0]) if args else 0)
                year = m["year"] + (month - 1) // 12
                month = (month - 1) % 12 + 1
                return {"_type": "Date", "year": year, "month": month, "day": m["day"]}
            if method == "date":
                return m  # Already a Date
            if method == "format":
                return "{}-{:02d}-{:02d}".format(m["year"], m["month"], m["day"])

        if "_sobject_type" in m:
            val = m.get(method)
            if val is not None:
                return val
        methods = {
            "put": lambda: m.__setitem__(args[0], args[1]) if len(args) >= 2 else None,
            "get": lambda: m.get(args[0]) if args else None,
            "containsKey": lambda: args[0] in m if args else False,
            "keySet": lambda: set(m.keys()),
            "values": lambda: list(m.values()),
            "size": lambda: len(m),
            "isEmpty": lambda: len(m) == 0,
            "remove": lambda: m.pop(args[0], None) if args else None,
        }
        if method in methods:
            return methods[method]()
        raise Exception("Map.{}() non supporté".format(method))

    def _resolve_class_chain(self, class_def):
        """Retourne la liste [class, parent, grandparent, ...] pour l'héritage."""
        chain = [class_def]
        visited = {class_def.name}
        current = class_def
        while current.parent_class and current.parent_class not in visited:
            parent = self.classes.get(current.parent_class)
            if parent is None:
                break
            chain.append(parent)
            visited.add(parent.name)
            current = parent
        return chain

    def _resolve_method_in_chain(self, class_def, method_name):
        """Cherche une méthode en remontant la chaîne d'héritage."""
        for cls in self._resolve_class_chain(class_def):
            if method_name in cls.methods:
                return cls.methods[method_name]
        return None

    def _resolve_class(self, name: str):
        """Résout un nom de classe (direct, inner, ou qualifié)."""
        # Direct match
        if name in self.classes:
            return self.classes[name]

        # Inner class: check current class
        if self._current_class and name in self._current_class.inner_classes:
            return self._current_class.inner_classes[name]

        # Qualified name: OuterClass.InnerClass
        if "." in name:
            parts = name.split(".", 1)
            outer = self.classes.get(parts[0])
            if outer and parts[1] in outer.inner_classes:
                return outer.inner_classes[parts[1]]

        # Check all loaded classes for inner class
        for cls in self.classes.values():
            if name in cls.inner_classes:
                return cls.inner_classes[name]

        return None

    def _create_instance(self, class_def, args):
        """Crée une instance avec support de l'héritage."""
        chain = self._resolve_class_chain(class_def)

        instance = {
            "_type": class_def.name,
            "_class": class_def,
            "_chain": chain,  # Pour résolution polymorphe
        }

        # Initialiser les champs d'instance de toute la chaîne (parent d'abord)
        for cls in reversed(chain):
            for field_name in cls.instance_fields:
                if field_name not in instance:
                    instance[field_name] = None

        # Trouver et exécuter le constructeur
        constructor = None
        for cls in chain:
            ctor = self._find_constructor(cls, len(args))
            if ctor:
                constructor = ctor
                break
        if constructor:
            self._run_constructor(instance, class_def, constructor, args)

        return instance

    def _instantiate_class(self, class_def, new_expr):
        """Crée une instance d'une classe."""
        instance = {
            "_type": class_def.name,
            "_class": class_def,
        }

        # Initialize instance fields with defaults
        for field_name, field_type in class_def.instance_fields.items():
            instance[field_name] = None

        # If new_expr has fields (SObject-style: new Cls(field = val)), set them
        if new_expr.fields:
            # Check if it's named fields or positional args
            first_key = next(iter(new_expr.fields.keys()), None)
            if first_key == "message":
                # Exception-style: new Exception('msg')
                args = [self._eval(v) for v in new_expr.fields.values()]
            else:
                # Named fields
                for field, val_expr in new_expr.fields.items():
                    instance[field] = self._eval(val_expr)
                args = []
        else:
            args = []

        # Run matching constructor
        constructor = self._find_constructor(class_def, len(args))
        if constructor and args:
            self._run_constructor(instance, class_def, constructor, args)
        elif constructor and not args and constructor.params:
            pass  # No args but constructor needs params → skip
        elif constructor:
            self._run_constructor(instance, class_def, constructor, args)

        return instance

    def _find_constructor(self, class_def, num_args: int):
        """Trouve le constructeur qui matche le nombre d'args."""
        for ctor in class_def.constructors:
            if len(ctor.params) == num_args:
                return ctor
        # Fallback: any constructor
        return class_def.constructors[0] if class_def.constructors else None

    def _run_constructor(self, instance, class_def, constructor, args):
        """Exécute un constructeur sur une instance."""
        saved_instance = self._current_instance
        saved_class = self._current_class
        saved_vars = self.variables.copy()

        self._current_instance = instance
        self._current_class = class_def

        new_scope = {}
        # Copy class constants
        for k, v in saved_vars.items():
            if "." in k:
                new_scope[k] = v
        for name, (type_name, expr_val) in class_def.constants.items():
            key = "{}.{}".format(class_def.name, name)
            if key not in new_scope:
                try:
                    new_scope[key] = self._eval(expr_val)
                except Exception:
                    pass
            new_scope[name] = new_scope.get(key)

        # Inject params
        for i, (ptype, pname) in enumerate(constructor.params):
            new_scope[pname] = args[i] if i < len(args) else None

        self.variables = new_scope

        try:
            for stmt in constructor.body:
                self._exec_stmt(stmt)
        except ReturnException:
            pass

        self.variables = saved_vars
        self._current_instance = saved_instance
        self._current_class = saved_class

    def _invoke_instance_method(self, instance, method_def, args):
        """Invoque une méthode d'instance sur un objet."""
        class_def = instance.get("_class")
        if not class_def:
            return None

        saved_instance = self._current_instance
        saved_class = self._current_class
        saved_vars = self.variables.copy()

        self._current_instance = instance
        self._current_class = class_def

        new_scope = {}
        for k, v in saved_vars.items():
            if "." in k:
                new_scope[k] = v
        for name, (type_name, expr_val) in class_def.constants.items():
            key = "{}.{}".format(class_def.name, name)
            if key not in new_scope:
                try:
                    new_scope[key] = self._eval(expr_val)
                except Exception:
                    pass
            new_scope[name] = new_scope.get(key)

        for i, (ptype, pname) in enumerate(method_def.params):
            new_scope[pname] = args[i] if i < len(args) else None

        self.variables = new_scope

        result = None
        try:
            for stmt in method_def.body:
                self._exec_stmt(stmt)
        except ReturnException as ret:
            result = ret.value

        self.variables = saved_vars
        self._current_instance = saved_instance
        self._current_class = saved_class
        return result

    def _invoke_method(self, class_def, method_def, args):
        """Invoque une méthode avec un scope isolé (stack de variables)."""
        saved_class = self._current_class
        saved_vars = self.variables.copy()
        self._current_class = class_def

        # Nouveau scope : on garde les constantes de classe et les classes
        new_scope = {}

        # Copier les constantes de toutes les classes chargées
        for k, v in saved_vars.items():
            if "." in k:  # ClassName.CONST
                new_scope[k] = v

        # Injecter les constantes de la classe courante (nom court)
        for name, (type_name, expr) in class_def.constants.items():
            key = "{}.{}".format(class_def.name, name)
            if key not in new_scope:
                new_scope[key] = self._eval(expr)
            new_scope[name] = new_scope[key]

        # Injecter les paramètres
        for i, (ptype, pname) in enumerate(method_def.params):
            new_scope[pname] = args[i] if i < len(args) else None

        self.variables = new_scope

        result = None
        try:
            for stmt in method_def.body:
                self._exec_stmt(stmt)
        except ReturnException as ret:
            result = ret.value

        # Restaurer le scope précédent
        self.variables = saved_vars
        self._current_class = saved_class
        return result

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
