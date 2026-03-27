"""Interpréteur Apex — parcourt un AST et exécute."""

from __future__ import annotations

from .org import FakeOrg
from .apex_parser import ApexParser
from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject,
    MethodCall, ChainedCall, Ternary, NewList, NewMap, NewMapInit,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
    WhileLoop, ThrowStmt,
    MethodDef, ClassDef, NewSet, SwitchWhen,
)


class ReturnException(Exception):
    """Signal interne pour return."""

    def __init__(self, value=None):
        self.value = value


class ApexException(Exception):
    """Exception Apex (throw new ...)."""
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

        elif isinstance(stmt, WhileLoop):
            max_iter = 10000
            count = 0
            while self._is_truthy(self._eval(stmt.condition)):
                for s in stmt.body:
                    self._exec_stmt(s)
                count += 1
                if count > max_iter:
                    raise Exception("Boucle infinie détectée (>{} itérations)".format(max_iter))

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
            return expr.value

        elif isinstance(expr, NullLiteral):
            return None

        elif isinstance(expr, Variable):
            return self.variables.get(expr.name)

        elif isinstance(expr, FieldAccess):
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
            return self._call_on_value(target, expr.method, args)

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
        if obj is None and call.obj not in self.classes and call.obj != "_self" and call.obj not in ("String", "Integer", "System", "Test", "Date", "DateTime"):
            # Vérifier aussi si c'est une méthode de la classe courante
            if not (self._current_class and call.method in self._current_class.methods):
                return None

        # List methods
        if isinstance(obj, list):
            if method == "add":
                obj.append(args[0] if args else None)
                return None
            elif method == "size":
                return len(obj)
            elif method == "isEmpty":
                return len(obj) == 0
            elif method == "get":
                return obj[int(args[0])] if args else None
            elif method == "contains":
                return args[0] in obj if args else False
            elif method == "remove":
                idx = int(args[0])
                return obj.pop(idx)
            elif method == "clear":
                obj.clear()
                return None

        # Set methods
        elif isinstance(obj, set):
            if method == "add":
                obj.add(args[0] if args else None)
                return None
            elif method == "contains":
                return args[0] in obj if args else False
            elif method == "size":
                return len(obj)
            elif method == "isEmpty":
                return len(obj) == 0
            elif method == "remove":
                obj.discard(args[0] if args else None)
                return None
            elif method == "addAll":
                if args and hasattr(args[0], '__iter__'):
                    obj.update(args[0])
                return None

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

        # SObject field access via method (e.getMessage() etc.)
        elif isinstance(obj, dict):
            val = obj.get(method)
            if val is not None:
                return val

        # Appel de méthode statique sur une classe chargée
        if call.obj in self.classes:
            return self.call_method(call.obj, method, args)

        # Appel de méthode locale (_self) ou de la même classe (sans préfixe)
        if call.obj == "_self" and self._current_class and method in self._current_class.methods:
            return self._invoke_method(self._current_class, self._current_class.methods[method], args)
        if self._current_class and method in self._current_class.methods:
            return self._invoke_method(self._current_class, self._current_class.methods[method], args)

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
                try:
                    return int(args[0]) if args else 0
                except (ValueError, TypeError):
                    return 0

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
            "split": lambda: __import__('re').split(args[0], s) if args else [s],
            "left": lambda: s[:int(args[0])] if args else s,
            "right": lambda: s[-int(args[0]):] if args else s,
            "removeStart": lambda: s[len(args[0]):] if args and s.startswith(args[0]) else s,
            "removeEnd": lambda: s[:-len(args[0])] if args and s.endswith(args[0]) else s,
            "leftPad": lambda: s.rjust(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "replaceAll": lambda: __import__('re').sub(args[0], args[1], s) if len(args) >= 2 else s,
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

    def _invoke_method(self, class_def, method_def, args):
        """Invoque une méthode avec des arguments, retourne la valeur de retour."""
        saved_class = self._current_class
        self._current_class = class_def

        # Sauvegarder les variables qui vont être écrasées par les params
        param_names = [pname for _, pname in method_def.params]
        saved_params = {p: self.variables.get(p) for p in param_names if p in self.variables}

        # Variables locales ajoutées pendant l'exécution (à nettoyer après)
        vars_before = set(self.variables.keys())

        # Injecter les paramètres
        for i, (ptype, pname) in enumerate(method_def.params):
            self.variables[pname] = args[i] if i < len(args) else None

        # Injecter les constantes de la classe (sans préfixe pour accès interne)
        for name, (type_name, expr) in class_def.constants.items():
            key = "{}.{}".format(class_def.name, name)
            if key not in self.variables:
                self.variables[key] = self._eval(expr)
            self.variables[name] = self.variables[key]

        result = None
        try:
            for stmt in method_def.body:
                self._exec_stmt(stmt)
        except ReturnException as ret:
            result = ret.value

        # Nettoyer : supprimer les variables locales créées pendant l'exécution
        # Mais préserver les constantes de la classe parente si on est en appel imbriqué
        const_names = set(class_def.constants.keys()) if class_def else set()
        vars_after = set(self.variables.keys())
        for v in vars_after - vars_before:
            if not v.startswith(class_def.name + ".") and v not in const_names:
                del self.variables[v]

        # Restaurer les params écrasés
        for p, val in saved_params.items():
            self.variables[p] = val
        for p in param_names:
            if p not in saved_params and p in self.variables:
                del self.variables[p]

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
