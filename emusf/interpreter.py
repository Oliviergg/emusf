"""Interpréteur Apex — parcourt un AST et exécute."""

from __future__ import annotations

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


def format_error(exc) -> str:
    """Message d'erreur runtime préfixé de sa localisation Apex si connue :
    'XPLPrepareService:73 — <message>'. L'interpréteur attache _emusf_location
    (nom de classe, ligne) à l'exception au plus près du statement fautif."""
    loc = getattr(exc, "_emusf_location", None)
    if loc:
        cls, line = loc
        where = "{}:{}".format(cls, line) if cls else "ligne {}".format(line)
        if line is not None:
            return "{} — {}".format(where, exc)
    return str(exc)


class BreakException(Exception):
    pass


class ContinueException(Exception):
    pass


def _common_prefix_len(a, b):
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return i if i < max(len(a), len(b)) else -1


def _common_prefix(a, b):
    n = _common_prefix_len(a, b)
    return a[:n] if n >= 0 else a


def _unescape_html(s):
    import html
    return html.unescape(s)


from decimal import Decimal as _Decimal

_NUM_RE = __import__("re").compile(r"-?\d+(\.\d+)?$")


def _json_clean(value):
    """Prépare une valeur Apex pour JSON.serialize :
    - retire les clés internes de l'émulateur (_type, _class, _chain, _sobject_type)
    - convertit les nombres stockés en TEXT ('0.7', '2025') en vrais nombres
      (les tables auto-créées stockent tout en TEXT, mais les API attendent des
      nombres pour temperature, max_tokens, etc.)
    """
    internal = {"_type", "_class", "_chain", "_sobject_type", "_context_type"}
    if isinstance(value, dict):
        return {k: _json_clean(v) for k, v in value.items()
                if not (isinstance(k, str) and k.startswith("_")) and k not in internal}
    if isinstance(value, (list, tuple, set)):
        return [_json_clean(v) for v in value]
    if isinstance(value, str) and _NUM_RE.match(value):
        # Ne pas convertir les Id/refs (préfixes alphanumériques) : _NUM_RE
        # n'accepte que des nombres purs
        return float(value) if "." in value else int(value)
    if isinstance(value, _Decimal):
        # Decimal (colonnes numériques PG) → nombre JSON, pas une chaîne
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _apex_str(value) -> str:
    """String.valueOf(value) façon Apex.

    Pour une instance de classe, Salesforce renvoie 'NomClasse:[champ=val, ...]'
    (le préfixe 'NomClasse:' est utilisé par des frameworks comme QueueableJob
    via String.valueOf(this).split(':')[0] pour retrouver le type)."""
    if isinstance(value, dict):
        cls = value.get("_class")
        name = value.get("_type")
        if cls is not None and name:
            fields = {k: v for k, v in value.items() if not k.startswith("_")}
            body = ", ".join("{}={}".format(k, _apex_str(v)) for k, v in fields.items())
            return "{}:[{}]".format(name, body)
        if value.get("_type") == "Blob":
            data = value.get("_data", b"")
            return data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _field_of(record, field):
    """Accès champ insensible à la casse sur un SObject (dict)."""
    if not isinstance(record, dict):
        return None
    if field in record:
        return record[field]
    fl = field.lower()
    for k, v in record.items():
        if k.lower() == fl:
            return v
    return None


def _is_soql_literal(s) -> bool:
    """True si la chaîne est un littéral SOQL/SOSL inline '[SELECT ...]'."""
    if not isinstance(s, str):
        return False
    t = s.strip()
    return t.startswith("[") and t.endswith("]") and \
        t[1:].lstrip()[:6].upper() in ("SELECT", "FIND")


def _blob_bytes(val) -> bytes:
    """Normalise un Blob Apex en bytes : accepte le wrapper
    {'_type': 'Blob', '_data': ...}, des bytes bruts ou une chaîne."""
    if isinstance(val, dict) and val.get("_type") == "Blob":
        val = val.get("_data", b"")
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    if isinstance(val, str):
        return val.encode("utf-8")
    return b""


class ApexInterpreter:
    """
    Interprète un AST Apex.
    Le parsing est délégué à ApexParser.
    """

    def __init__(self, org, named_credentials=None):
        self.org = org
        self.parser = ApexParser()
        self.variables = {}
        self.output = []
        self.classes = {}  # {class_name: ClassDef}
        self._current_class = None  # ClassDef en cours d'exécution
        self._current_return_type = None  # type de retour de la méthode en cours
        self._current_line = None  # ligne source du statement en cours d'exécution
        self._current_instance = None  # Instance en cours (pour this)
        self.named_credentials = named_credentials or {}  # Named Credentials (YAML)
        self._http_mock = None  # Instance HttpCalloutMock pour Test.setMock
        self.job_queue = None  # File de Queueables (SyncJobQueue) si branchée
        # Triggers de Platform Event : {sobject_lower: (event_var, body_stmts)}
        self.platform_event_triggers = {}
        self._flushing_jobs = False  # garde de ré-entrance pour System.enqueueJob
        # Budget d'opérations asynchrones (Platform Events + Queueables) par run.
        # En réel chaque event/job est une transaction séparée avec des limites
        # de gouverneur ; en synchrone une chaîne qui se ré-enfile (polling
        # CheckQueueJob, cascade de la machine à états) tournerait sans fin.
        self.async_budget = 200

    def _soql_context(self):
        """Contexte de résolution des binds SOQL : variables locales + champs
        de l'instance courante (pour ':champ' référençant this.champ dans une
        méthode d'instance)."""
        if self._current_instance is None:
            return self.variables
        ctx = dict(self._current_instance)
        ctx.update(self.variables)  # les locales masquent les champs d'instance
        return ctx

    def register_platform_event_trigger(self, sobject, event_var, body_stmts):
        """Enregistre un trigger sur un Platform Event (__e), déclenché par
        EventBus.publish plutôt que par du DML."""
        self.platform_event_triggers[sobject.lower()] = (event_var, body_stmts)

    def _fire_platform_event(self, events, _depth=[0]):
        """Déclenche les triggers de Platform Event pour une liste d'events
        publiés (dicts avec _sobject_type). Sémantique 'after insert'.

        Garde de profondeur : en réel les Platform Events sont asynchrones
        (transactions séparées) ; en synchrone une chaîne d'events pourrait
        récurser sans fin."""
        if _depth[0] >= 40 or self.async_budget <= 0:
            return
        self.async_budget -= 1
        by_type = {}
        for evt in events:
            if isinstance(evt, dict):
                st = (evt.get("_sobject_type") or "").lower()
                by_type.setdefault(st, []).append(evt)
        for st, evs in by_type.items():
            handler = self.platform_event_triggers.get(st)
            if not handler:
                continue
            event_var, body_stmts = handler
            saved_trigger = self.variables.get("Trigger")
            self.variables["Trigger"] = {"new": evs, "old": [], "isInsert": True,
                                         "isAfter": True, "isExecuting": True}
            _depth[0] += 1
            try:
                for stmt in body_stmts:
                    self._exec_stmt(stmt)
            except ReturnException:
                pass
            finally:
                _depth[0] -= 1
                if saved_trigger is not None:
                    self.variables["Trigger"] = saved_trigger
                else:
                    self.variables.pop("Trigger", None)

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
            self.variables["{}.{}".format(class_def.name, name)] = self._eval(expr) if expr is not None else None
        return class_def

    def call_method(self, class_name: str, method_name: str, args: list = None):
        """Appelle une méthode statique d'une classe chargée."""
        if args is None:
            args = []
        class_def = self.classes.get(class_name)
        if not class_def:
            raise Exception("Classe '{}' non chargée".format(class_name))
        method = self._resolve_overload(class_def, method_name, args)
        if not method:
            raise Exception("Méthode '{}.{}' non trouvée".format(class_name, method_name))
        return self._invoke_method(class_def, method, args)

    @staticmethod
    def _resolve_overload(class_def, method_name: str, args: list):
        """Résout une surcharge de méthode par nombre et type d'arguments."""
        candidates = getattr(class_def, 'overloads', {}).get(method_name)
        if candidates:
            # Filtrer par nombre de params
            matching = [m for m in candidates if len(m.params) == len(args)]
            if len(matching) == 1:
                return matching[0]
            if len(matching) > 1:
                # Discriminer par type du premier argument
                for m in matching:
                    param_type = m.params[0][0].lower() if m.params else ""
                    arg = args[0] if args else None
                    if isinstance(arg, dict) and "map" in param_type:
                        return m
                    if isinstance(arg, list) and "list" in param_type:
                        return m
                    if isinstance(arg, set) and "set" in param_type:
                        return m
                    if isinstance(arg, str) and param_type in ("string", "id"):
                        return m
                    if isinstance(arg, (int, float)) and param_type in ("integer", "int", "decimal", "double", "long"):
                        return m
                # Pas de match par type, retourner le premier
                return matching[0]
        # Pas de surcharge, version par défaut
        return class_def.methods.get(method_name)

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
                cls = self._current_class.name if self._current_class else None
                e._emusf_location = (cls, self._current_line)
            raise

    def _exec_stmt_body(self, stmt: Stmt):
        if isinstance(stmt, VarDecl):
            self.variables[stmt.var_name] = self._eval(stmt.value)

        elif isinstance(stmt, Assign):
            val = self._eval(stmt.value)
            self.variables[stmt.var_name] = val
            # Synchroniser la variable statique si elle existe (ClassName.field)
            if self._current_class and stmt.var_name in self._current_class.constants:
                self.variables["{}.{}".format(self._current_class.name, stmt.var_name)] = val
            # Synchroniser le champ d'instance si assigné sans this.
            if self._current_instance is not None and stmt.var_name in self._current_instance and stmt.var_name not in ("_type", "_class", "_chain"):
                self._current_instance[stmt.var_name] = val

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
            val = self.variables.get(expr.name)
            # Fallback: champ d'instance implicite (sans this.)
            if val is None and expr.name not in self.variables and self._current_instance is not None:
                if expr.name in self._current_instance and expr.name not in ("_type", "_class", "_chain"):
                    return self._current_instance[expr.name]
            return val

        elif isinstance(expr, FieldAccess):
            # this.field
            if expr.obj == "this" and self._current_instance is not None:
                return self._current_instance.get(expr.field)

            # System.Label → return empty string for custom labels
            if expr.obj == "System" and expr.field == "Label":
                return {"_type": "SystemLabel"}

            # Schema.sObjectType → map des describes (Schema.sObjectType.X.isAccessible())
            if expr.obj == "Schema" and expr.field == "sObjectType":
                return {"_type": "SchemaSObjectTypeMap"}
            # ParentJobResult.SUCCESS / FAILURE
            if expr.obj == "ParentJobResult":
                return expr.field

            # ApexPages.severity → enum marker
            if expr.obj == "ApexPages" and expr.field.lower() == "severity":
                return {"_type": "ApexPages.severity"}

            # FormulaEval namespace — enums and classes
            if expr.obj == "FormulaEval":
                field = expr.field
                if field == "FormulaReturnType":
                    return {"_type": "FormulaEval.FormulaReturnType"}
                if field == "FormulaGlobal":
                    return {"_type": "FormulaEval.FormulaGlobal"}
                if field == "FormulaBuilder":
                    return {"_type": "FormulaEval.FormulaBuilderClass"}
                if field == "FormulaInstance":
                    return {"_type": "FormulaEval.FormulaInstanceClass"}
            # system.today() parsé comme FieldAccess puis ChainedCall
            if expr.obj.lower() == "system" and expr.field.lower() == "today":
                from datetime import date
                return date.today()
            # Constante de classe : ClassName.CONST
            class_key = "{}.{}".format(expr.obj, expr.field)
            if class_key in self.variables:
                return self.variables[class_key]
            obj = self.variables.get(expr.obj)
            if isinstance(obj, dict):
                val = obj.get(expr.field)
                if val is None and expr.field not in obj:
                    # Fallback case-insensitive (PG stocke en minuscules)
                    key_lower = expr.field.lower()
                    for k in obj:
                        if k.lower() == key_lower:
                            return obj[k]
                return val
            if isinstance(obj, list):
                return None
            return None

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
                if left is None:
                    left = 0
                if right is None:
                    right = 0
                return left - right
            elif expr.op == "*":
                if left is None:
                    left = 0
                if right is None:
                    right = 0
                return left * right
            elif expr.op == "/":
                if left is None:
                    left = 0
                if right is None:
                    right = 0
                return left / right
            elif expr.op == "==":
                return left == right
            elif expr.op == "!=":
                return left != right
            elif expr.op == "<":
                if left is None or right is None:
                    return False
                try:
                    return left < right
                except TypeError:
                    return False
            elif expr.op == ">":
                if left is None or right is None:
                    return False
                try:
                    return left > right
                except TypeError:
                    return False
            elif expr.op == "<=":
                if left is None or right is None:
                    return False
                try:
                    return left <= right
                except TypeError:
                    return False
            elif expr.op == ">=":
                if left is None or right is None:
                    return False
                try:
                    return left >= right
                except TypeError:
                    return False
            elif expr.op == "&&":
                return self._is_truthy(left) and self._is_truthy(right)
            elif expr.op == "||":
                return self._is_truthy(left) or self._is_truthy(right)
            elif expr.op == "instanceof":
                # Check _type or _sobject_type on left against right class name
                type_name = None
                if isinstance(right, str):
                    type_name = right
                elif isinstance(expr.right, Variable):
                    type_name = expr.right.name
                if type_name and isinstance(left, dict):
                    obj_type = left.get("_type") or left.get("_sobject_type") or ""
                    cls = left.get("_class")
                    if cls:
                        # Walk inheritance chain
                        while cls:
                            if cls.name == type_name:
                                return True
                            if cls.parent_class:
                                cls = self.classes.get(cls.parent_class)
                            else:
                                break
                    return obj_type == type_name
                return False
            raise Exception("Opérateur inconnu: {}".format(expr.op))

        elif isinstance(expr, NewSObject):
            # Special system types
            if expr.sobject_type in ("HttpRequest", "Http", "HttpResponse"):
                obj = {"_type": expr.sobject_type}
                for field, val_expr in expr.fields.items():
                    obj[field] = self._eval(val_expr)
                return obj

            # ApexPages.Message(severity, summary)
            if expr.sobject_type in ("ApexPages.Message", "ApexPages.message"):
                args = [self._eval(v) for v in expr.fields.values()]
                return {"_type": "ApexPages.Message",
                        "severity": args[0] if args else "ERROR",
                        "summary": args[1] if len(args) > 1 else ""}
            # PageReference
            if expr.sobject_type == "PageReference":
                args = [self._eval(v) for v in expr.fields.values()]
                return {"_type": "PageReference",
                        "url": args[0] if args else "/"}

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
            # [SELECT ... ].champ — accès direct au champ du 1er enregistrement
            if isinstance(expr.target, StringLiteral) and \
                    _is_soql_literal(expr.target.value):
                rows = self.org.execute_soql(expr.target.value, context=self._soql_context())
                if not expr.args:  # accès champ, pas appel de méthode
                    if not rows:
                        raise ApexException("List has no rows for assignment to SObject")
                    return _field_of(rows[0], expr.method)

            target = self._eval(expr.target)
            args = [self._eval(a) for a in expr.args]

            # System.JSON.method() — résoudre comme JSON.method()
            if target is None and isinstance(expr.target, FieldAccess):
                fa = expr.target
                if fa.obj == "System" and fa.field == "JSON":
                    call = MethodCall(obj="JSON", method=expr.method, args=expr.args)
                    return self._exec_method_call(call)

            # Instance method call
            if isinstance(target, dict) and "_class" in target:
                cls = target["_class"]
                if expr.method in cls.methods:
                    return self._invoke_instance_method(target, cls.methods[expr.method], args)
                # Field access on instance
                if expr.method in target:
                    return target[expr.method]

            # ApexPages enum: ApexPages.severity.INFO → "INFO"
            if isinstance(target, dict) and target.get("_type") == "ApexPages.severity":
                return expr.method  # "INFO", "ERROR", "WARNING", "CONFIRM"

            # FormulaEval enums
            if isinstance(target, dict) and target.get("_type") == "FormulaEval.FormulaReturnType":
                return expr.method  # STRING, BOOLEAN, NUMBER, DATE, DATETIME
            if isinstance(target, dict) and target.get("_type") == "FormulaEval.FormulaGlobal":
                return expr.method  # LABEL, PROFILE, USER

            # FormulaEval.FormulaBuilder.builder() → static call
            if isinstance(target, dict) and target.get("_type") == "FormulaEval.FormulaBuilderClass":
                if expr.method == "builder":
                    return {"_type": "FormulaBuilder", "_context_type": None,
                            "_return_type": None, "_formula": None,
                            "_globals": [], "_template": False}

            # FormulaBuilder fluent methods
            if isinstance(target, dict) and target.get("_type") == "FormulaBuilder":
                return self._call_formula_builder(target, expr.method, args)

            # FormulaInstance methods
            if isinstance(target, dict) and target.get("_type") == "FormulaInstance":
                return self._call_formula_instance(target, expr.method, args)

            # new ApexPages.message(...) parsé comme NewSObject("ApexPages").message(...)
            if (isinstance(target, dict) and target.get("_sobject_type") == "ApexPages"
                    and expr.method.lower() == "message"):
                return {"_type": "ApexPages.Message",
                        "severity": args[0] if args else "ERROR",
                        "summary": args[1] if len(args) > 1 else ""}

            # new ApexPages.StandardController(record).view()
            if (isinstance(target, dict) and target.get("_sobject_type") == "ApexPages"
                    and expr.method.lower() == "standardcontroller"):
                rec = args[0] if args else {}
                ctrl = dict(rec) if isinstance(rec, dict) else {"Id": rec}
                ctrl["_type"] = "ApexPages.StandardController"
                return ctrl

            # ApexPages.StandardController(record).view()
            if isinstance(target, dict) and target.get("_type") == "ApexPages.StandardController":
                if expr.method == "view":
                    return {"_type": "PageReference", "url": "/" + (target.get("Id") or "")}
                if expr.method == "getRecord":
                    return {k: v for k, v in target.items() if k != "_type"}

            # Schema.sObjectType.X → DescribeSObjectResult (avant le fallback
            # d'accès champ, sinon .Lead renverrait None)
            if isinstance(target, dict) and target.get("_type") == "SchemaSObjectTypeMap":
                return self._call_on_value(target, expr.method, args)

            # Field access on dict when no args — UNIQUEMENT pour les records
            # (pas les objets typés built-in comme ApexType/Blob/Matcher dont
            # les méthodes sans argument, ex: newInstance(), doivent s'exécuter)
            is_typed_object = isinstance(target, dict) and "_type" in target \
                and "_class" not in target
            if not args and isinstance(target, dict) and not is_typed_object:
                if expr.method in target:
                    return target[expr.method]
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

    # Namespaces système built-in : Apex est insensible à la casse, donc
    # 'system.enqueueJob' == 'System.enqueueJob'. On normalise la casse quand
    # ce n'est ni une variable ni une classe utilisateur.
    _BUILTIN_NAMESPACES = {
        n.lower(): n for n in (
            "System", "Test", "Date", "DateTime", "Time", "Math", "JSON",
            "EncodingUtil", "Crypto", "Blob", "Database", "Schema", "URL",
            "UserInfo", "Http", "Limits", "EventBus", "Type", "UUID",
            "ApexPages", "Messaging",
        )
    }

    def _exec_method_call(self, call: MethodCall):
        """Exécute un appel de méthode sur un objet ou une collection."""
        obj = self.variables.get(call.obj)
        # Normaliser la casse d'un namespace built-in (sauf si masqué par une
        # variable locale ou une classe utilisateur du même nom)
        if (obj is None and call.obj not in self.classes
                and call.obj.lower() in self._BUILTIN_NAMESPACES
                and call.obj not in self._BUILTIN_NAMESPACES.values()):
            call = MethodCall(obj=self._BUILTIN_NAMESPACES[call.obj.lower()],
                              method=call.method, args=call.args)
        args = [self._eval(a) for a in call.args]
        method = call.method

        # Null-safe: appeler une méthode sur null retourne null
        if obj is None and call.obj not in self.classes and call.obj not in ("_self", "_super") and call.obj not in ("String", "Integer", "System", "Test", "Date", "DateTime", "Pattern", "Matcher", "Math", "JSON", "EncodingUtil", "Crypto", "Blob", "blob", "Database", "Schema", "URL", "UserInfo", "Http", "HttpRequest", "HttpResponse", "Limits", "EventBus", "Type", "UUID", "Formula", "FormulaEval") and not call.obj.endswith("__c"):
            # Vérifier aussi si c'est une méthode de la classe courante
            if not (self._current_class and call.method in self._current_class.methods):
                return None

        # List and Set methods → delegate to _call_on_value
        if isinstance(obj, (list, set)):
            return self._call_on_value(obj, method, args)

        # Instance method call (obj has _class) — BEFORE typed dict check
        if isinstance(obj, dict) and "_class" in obj:
            # Polymorphic: search in concrete class + parent chain
            resolved = self._resolve_method_in_chain(obj["_class"], method, args)
            if resolved:
                if resolved.is_static:
                    return self._invoke_method(obj["_class"], resolved, args)
                else:
                    return self._invoke_instance_method(obj, resolved, args)
            # Instance field access
            if method in obj:
                return obj[method]

        # ApexPages.StandardController instance methods
        if isinstance(obj, dict) and obj.get("_type") == "ApexPages.StandardController":
            if method == "getRecord":
                return {k: v for k, v in obj.items() if k not in ("_type",)}
            if method == "getId":
                return obj.get("Id")
            if method == "view":
                return {"_type": "PageReference", "url": "/" + (obj.get("Id") or "")}

        # Plain dict (Map) methods — ex: JSON.deserializeUntyped retourne des dicts sans _type
        if isinstance(obj, dict) and "_class" not in obj:
            if method == "get":
                return obj.get(args[0]) if args else None
            if method == "put":
                if len(args) >= 2:
                    obj[args[0]] = args[1]
                return None
            if method == "containsKey":
                return args[0] in obj if args else False
            if method == "keySet":
                return set(k for k in obj.keys() if not k.startswith("_"))
            if method == "values":
                return [v for k, v in obj.items() if not k.startswith("_")]
            if method == "size":
                return len([k for k in obj if not k.startswith("_")])
            if method == "isEmpty":
                return len(obj) == 0
            if method == "remove":
                return obj.pop(args[0], None) if args else None

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

        # ApexPages.StandardController methods
        elif isinstance(obj, dict) and obj.get("_type") == "ApexPages.StandardController":
            if method == "getRecord":
                return {k: v for k, v in obj.items() if k != "_type"}
            if method == "getId":
                return obj.get("Id")

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

        # Inner class: si call.obj est une inner class de la classe courante,
        # chercher la méthode dans la classe outer
        if self._current_class and call.obj in self._current_class.inner_classes:
            resolved = self._resolve_method_in_chain(self._current_class, method, args)
            if resolved:
                return self._invoke_method(self._current_class, resolved, args)

        # Appel de méthode locale (_self) — polymorphisme via instance concrète
        if call.obj == "_self" or (obj is None and self._current_class):
            # Chercher d'abord dans la classe concrète de l'instance (polymorphisme)
            if self._current_instance and "_class" in self._current_instance:
                concrete_class = self._current_instance["_class"]
                resolved = self._resolve_method_in_chain(concrete_class, method, args)
                if resolved:
                    if resolved.is_static:
                        return self._invoke_method(concrete_class, resolved, args)
                    else:
                        return self._invoke_instance_method(self._current_instance, resolved, args)
            # Fallback: chercher dans la classe courante + héritage
            if self._current_class:
                resolved = self._resolve_method_in_chain(self._current_class, method, args)
                if resolved:
                    return self._invoke_method(self._current_class, resolved, args)

        # ApexPages
        if call.obj == "ApexPages":
            if method in ("addMessage", "addmessage"):
                msg = args[0] if args else {}
                self.variables.setdefault("__apex_messages__", []).append(msg)
                return None

        # String static methods
        if call.obj == "String":
            if method == "isBlank":
                v = args[0] if args else None
                return v is None or (isinstance(v, str) and v.strip() == "")
            elif method == "isNotBlank":
                v = args[0] if args else None
                return v is not None and isinstance(v, str) and v.strip() != ""
            elif method == "valueOf":
                return _apex_str(args[0]) if args else ""
            elif method == "isEmpty":
                v = args[0] if args else None
                return v is None or (isinstance(v, str) and v == "")
            elif method == "isNotEmpty":
                v = args[0] if args else None
                return v is not None and isinstance(v, str) and v != ""
            elif method == "join":
                if len(args) >= 2:
                    lst = args[0]
                    sep = args[1]
                    if isinstance(lst, list):
                        return sep.join(str(x) for x in lst)
                return ""
            elif method == "format":
                if len(args) >= 2:
                    template = args[0] if args else ''
                    params = args[1] if len(args) > 1 else []
                    if isinstance(params, list):
                        for i, p in enumerate(params):
                            template = template.replace('{' + str(i) + '}', str(p) if p is not None else 'null')
                    return template
                return args[0] if args else ''
            elif method == "fromCharArray":
                return ''.join(chr(int(c)) for c in args[0]) if args and isinstance(args[0], list) else ''

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

            def _default(o):
                if isinstance(o, ClassDef):
                    return o.name
                if isinstance(o, set):
                    return list(o)
                return str(o)

            if method == "serialize":
                return _json.dumps(_json_clean(args[0]), default=_default) if args else "null"
            elif method == "serializePretty":
                return _json.dumps(_json_clean(args[0]), indent=2, default=_default) if args else "null"
            elif method == "deserialize":
                if len(args) >= 2 and isinstance(args[0], str):
                    return self._json_convert_dates(_json.loads(args[0]))
                return self._json_convert_dates(_json.loads(args[0])) if args else None
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

        # Formula.builder() — System.Formula shorthand
        if call.obj == "Formula":
            if method == "builder":
                return {"_type": "FormulaBuilder", "_context_type": None,
                        "_return_type": None, "_formula": None,
                        "_globals": [], "_template": False}
            elif method == "recalculateFormulas":
                records = args[0] if args else []
                results = []
                for rec in (records if isinstance(records, list) else [records]):
                    results.append({
                        "_type": "FormulaRecalcResult",
                        "_record": rec,
                        "_success": True,
                        "_errors": [],
                    })
                return results

        # FormulaEval.FormulaBuilder.builder() — explicit namespace
        if call.obj == "FormulaEval":
            if method == "FormulaBuilder":
                return {"_type": "FormulaEval.FormulaBuilderClass"}

        # System static methods
        if call.obj == "System":
            if method == "debug":
                val = args[0] if args else ""
                self.output.append(str(val))
                print("DEBUG: {}".format(val))
                return None
            elif method == "enqueueJob":
                # Queueable : enqueue puis exécution synchrone (comme
                # Test.stopTest). La garde _flushing_jobs évite qu'un enqueue
                # imbriqué relance un second flush — le flush courant le prend.
                instance = args[0] if args else None
                # enqueueJob(job, delayInMinutes) : job de polling différé
                # (ex: CheckQueueJob) — ignoré, sinon boucle infinie en synchrone
                if len(args) >= 2:
                    return None
                if self.job_queue and isinstance(instance, dict) and "_class" in instance:
                    job_id = self.job_queue.enqueue(instance)
                    if not self._flushing_jobs:
                        self._flushing_jobs = True
                        try:
                            self.job_queue.flush(self)
                        finally:
                            self._flushing_jobs = False
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

        # EventBus.publish — déclenche les triggers de Platform Event en contexte
        if call.obj == "EventBus" and method == "publish":
            published = args[0] if args else None
            events = published if isinstance(published, list) else [published]
            if self.platform_event_triggers:
                self._fire_platform_event([e for e in events if isinstance(e, dict)])
            return None

        # Type.forName — reflection
        if call.obj == "Type" and method == "forName":
            class_name = args[0] if args else None
            return {"_type": "ApexType", "className": class_name}

        # UUID.randomUUID()
        if call.obj == "UUID" and method == "randomUUID":
            import uuid
            return str(uuid.uuid4())

        # Http.send() — callout réel, mock, ou défaut
        if call.obj == "Http":
            if method == "send":
                req = args[0] if args else {}
                if self.named_credentials and isinstance(req, dict):
                    from .callout import execute_callout
                    return execute_callout(req, self.named_credentials)
                return self._http_send(req)

        # URL static methods
        if call.obj == "URL":
            if method == "getOrgDomainUrl":
                return {"_type": "URL", "_url": "https://test.salesforce.com"}

        # Database static methods
        if call.obj == "Database":
            if method in ("insert", "update"):
                records = args[0] if args else None
                if isinstance(records, list):
                    for r in records:
                        if isinstance(r, dict) and "_sobject_type" in r:
                            sobject = r["_sobject_type"]
                            data = {k: v for k, v in r.items() if k != "_sobject_type"}
                            try:
                                if method == "insert":
                                    result = self.org.insert(sobject, [data])
                                    r["Id"] = result.record_ids[0]
                                else:
                                    self.org.update(sobject, [data])
                            except Exception:
                                pass  # Partial success mode
                    # Return list of SaveResult
                    return [{"_type": "SaveResult", "success": True, "id": r.get("Id")} for r in records]
                elif isinstance(records, dict) and "_sobject_type" in records:
                    sobject = records["_sobject_type"]
                    data = {k: v for k, v in records.items() if k != "_sobject_type"}
                    if method == "insert":
                        result = self.org.insert(sobject, [data])
                        records["Id"] = result.record_ids[0]
                    else:
                        self.org.update(sobject, [data])
                    return {"_type": "SaveResult", "success": True, "id": records.get("Id")}
                return None
            if method == "delete":
                records = args[0] if args else None
                # Simplified — just return success
                return [{"_type": "SaveResult", "success": True}]
            if method == "query":
                soql = args[0] if args else ""
                return self.org.execute_soql("[{}]".format(soql), context=self._soql_context())

        # EncodingUtil static methods
        if call.obj == "EncodingUtil":
            if method == "base64Encode":
                import base64
                return base64.b64encode(_blob_bytes(args[0])).decode() if args else ""
            if method == "urlEncode":
                import urllib.parse
                return urllib.parse.quote(str(args[0]), safe='') if args else ""
            if method == "base64Decode":
                import base64
                return base64.b64decode(str(args[0])).decode() if args else ""
            if method == "convertToHex":
                return _blob_bytes(args[0]).hex() if args else ""
            if method == "convertFromHex":
                val = str(args[0]) if args else ""
                return {"_type": "Blob", "_data": bytes.fromhex(val)}

        # Crypto static methods
        if call.obj == "Crypto":
            if method == "encrypt":
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                algo = str(args[0]) if args else ""
                key = _blob_bytes(args[1]) if len(args) > 1 else b""
                iv = _blob_bytes(args[2]) if len(args) > 2 else b""
                data = _blob_bytes(args[3]) if len(args) > 3 else b""
                # PKCS7 padding
                block_size = 16
                pad_len = block_size - (len(data) % block_size)
                data = data + bytes([pad_len]) * pad_len
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
                encryptor = cipher.encryptor()
                return {"_type": "Blob",
                        "_data": encryptor.update(data) + encryptor.finalize()}
            if method == "generateAesKey":
                import os
                bits = int(args[0]) if args else 128
                return os.urandom(bits // 8)
            if method == "getRandomInteger":
                import random
                return random.randint(-2147483648, 2147483647)
            if method == "generateMac":
                import hmac, hashlib
                algo = str(args[0]).lower().replace("-", "") if args else "hmacsha256"
                data = _blob_bytes(args[1]) if len(args) > 1 else b""
                key = _blob_bytes(args[2]) if len(args) > 2 else b""
                hash_map = {"hmacsha256": hashlib.sha256, "hmacsha1": hashlib.sha1, "hmacmd5": hashlib.md5}
                hash_fn = hash_map.get(algo, hashlib.sha256)
                return hmac.new(key, data, hash_fn).digest()
            if method == "generateDigest":
                import hashlib
                algo = str(args[0]).lower().replace("-", "") if args else "sha256"
                data = _blob_bytes(args[1]) if len(args) > 1 else b""
                hash_map = {"sha256": hashlib.sha256, "sha1": hashlib.sha1, "md5": hashlib.md5}
                hash_fn = hash_map.get(algo, hashlib.sha256)
                return hash_fn(data).digest()

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
            if method == "now":
                import datetime
                d = datetime.datetime.now()
                return {"_type": "DateTime", "year": d.year, "month": d.month, "day": d.day,
                        "hour": d.hour, "minute": d.minute, "second": d.second}
            if method == "valueOf":
                return {"_type": "DateTime"} if args else None

        # Test static methods
        if call.obj == "Test":
            if method == "isRunningTest":
                return True
            if method == "getEventBus":
                return {"_type": "EventBus"}
            if method == "setMock":
                # Test.setMock(HttpCalloutMock.class, mockInstance)
                if len(args) >= 2:
                    self._http_mock = args[1]
                return None
            if method in ("startTest", "stopTest", "setCreatedDate",
                          "setCurrentPage", "setCurrentPageReference", "setReadOnlyApplicationMode",
                          "setFixedSearchResults", "loadData"):
                return None

        # String static methods
        if call.obj == "String":
            if method == "escapeSingleQuotes":
                return args[0].replace("'", "\\'") if args and isinstance(args[0], str) else (args[0] if args else "")
            if method == "valueOf":
                return _apex_str(args[0]) if args else ""
            if method == "isBlank":
                return args[0] is None or (isinstance(args[0], str) and args[0].strip() == "") if args else True
            if method == "isNotBlank":
                return args[0] is not None and isinstance(args[0], str) and args[0].strip() != "" if args else False
            if method == "isEmpty":
                return args[0] is None or args[0] == "" if args else True
            if method == "join":
                if len(args) >= 2:
                    return str(args[1]).join(str(x) for x in args[0]) if isinstance(args[0], list) else str(args[0])
                return ""
            if method == "format":
                return str(args[0]) if args else ""

        # System.schedule
        if call.obj == "System" and method == "schedule":
            return "FakeJobId_001"

        # UserInfo static methods
        if call.obj == "UserInfo":
            _userinfo = {
                "getUserId": "005000000000001AAA",
                "getProfileId": "00e000000000001AAA",
                "getUserRoleId": "00E000000000001AAA",
                "getName": "Test User",
                "getFirstName": "Test",
                "getLastName": "User",
                "getUserName": "testuser@example.com",
                "getUserEmail": "testuser@example.com",
                "getOrganizationId": "00D000000000001AAA",
                "getOrganizationName": "Test Org",
                "getDefaultCurrency": "EUR",
                "getLocale": "fr_FR",
                "getLanguage": "fr",
                "getTimeZone": {"_type": "TimeZone", "id": "Europe/Paris"},
                "getSessionId": "fakesession000000000000000001",
                "isMultiCurrencyOrganization": False,
                "getUiTheme": "Theme4d",
                "getUiThemeDisplayed": "Theme4d",
            }
            if method in _userinfo:
                return _userinfo[method]
            return None

        # Limits static methods
        if call.obj == "Limits":
            # Compteurs internes
            if not hasattr(self, '_limits'):
                self._limits = {"queries": 0, "dml": 0, "soql_rows": 0, "dml_rows": 0,
                                "cpu_time": 0, "heap_size": 0, "callouts": 0, "future_calls": 0,
                                "queueable_jobs": 0, "email_invocations": 0}
            _limit_getters = {
                "getQueries": lambda: self._limits["queries"],
                "getDmlStatements": lambda: self._limits["dml"],
                "getSoqlQueryRows": lambda: self._limits.get("soql_rows", 0),
                "getDmlRows": lambda: self._limits["dml_rows"],
                "getCpuTime": lambda: self._limits["cpu_time"],
                "getHeapSize": lambda: self._limits["heap_size"],
                "getCallouts": lambda: self._limits["callouts"],
                "getFutureCalls": lambda: self._limits["future_calls"],
                "getQueueableJobs": lambda: self._limits["queueable_jobs"],
                "getEmailInvocations": lambda: self._limits["email_invocations"],
                # Limites max (governor limits)
                "getLimitQueries": lambda: 100,
                "getLimitDmlStatements": lambda: 150,
                "getLimitSoqlQueryRows": lambda: 50000,
                "getLimitDmlRows": lambda: 10000,
                "getLimitCpuTime": lambda: 10000,
                "getLimitHeapSize": lambda: 6000000,
                "getLimitCallouts": lambda: 100,
                "getLimitFutureCalls": lambda: 50,
                "getLimitQueueableJobs": lambda: 50,
                "getLimitEmailInvocations": lambda: 10,
            }
            if method in _limit_getters:
                return _limit_getters[method]()
            return 0

        # Schema static methods
        if call.obj == "Schema":
            if method == "getGlobalDescribe":
                # Retourne un Map<String, SObjectType> basé sur les tables connues de l'org
                try:
                    tables = self.org.get_sobject_names() if hasattr(self.org, 'get_sobject_names') else []
                except Exception:
                    tables = []
                return {t: {"_type": "SObjectType", "name": t} for t in tables}
            if method == "describeSObjects":
                return [{"_type": "DescribeSObjectResult", "name": a} for a in (args[0] if args and isinstance(args[0], list) else [])]

        # Schema.SObjectType.XXX — e.g. Schema.SObjectType.Account
        if call.obj == "SObjectType":
            sobject_name = method
            return {"_type": "SObjectType", "name": sobject_name}

        # Blob static methods (compléter)
        if call.obj in ("Blob", "blob"):
            if method == "valueOf":
                val = str(args[0]) if args else ""
                return {"_type": "Blob", "_data": val.encode('utf-8')}
            if method == "toPdf":
                val = str(args[0]) if args else ""
                return {"_type": "Blob", "_data": val.encode('utf-8')}

        # Id static methods
        if call.obj == "Id" and method == "valueOf":
            return str(args[0]) if args else None

        # Decimal static methods
        if call.obj == "Decimal":
            if method == "valueOf":
                try:
                    return float(args[0]) if args else 0.0
                except (ValueError, TypeError):
                    return 0.0

        # Double static methods
        if call.obj == "Double":
            if method == "valueOf":
                try:
                    return float(args[0]) if args else 0.0
                except (ValueError, TypeError):
                    return 0.0

        # Assert class (API 59+)
        if call.obj == "Assert":
            if method in ("isTrue", "istrue"):
                if not args or not args[0]:
                    msg = args[1] if len(args) > 1 else "Assertion failed: expected true"
                    raise ApexException(msg)
                return None
            if method in ("isFalse", "isfalse"):
                if args and args[0]:
                    msg = args[1] if len(args) > 1 else "Assertion failed: expected false"
                    raise ApexException(msg)
                return None
            if method in ("areEqual", "areequal"):
                if len(args) >= 2 and args[0] != args[1]:
                    msg = args[2] if len(args) > 2 else "Assertion failed: {} != {}".format(args[0], args[1])
                    raise ApexException(msg)
                return None
            if method in ("areNotEqual", "arenotequal"):
                if len(args) >= 2 and args[0] == args[1]:
                    msg = args[2] if len(args) > 2 else "Assertion failed: values are equal: {}".format(args[0])
                    raise ApexException(msg)
                return None
            if method in ("isNotNull", "isnotnull"):
                if not args or args[0] is None:
                    msg = args[1] if len(args) > 1 else "Assertion failed: expected non-null"
                    raise ApexException(msg)
                return None
            if method in ("isNull", "isnull"):
                if args and args[0] is not None:
                    msg = args[1] if len(args) > 1 else "Assertion failed: expected null"
                    raise ApexException(msg)
                return None
            if method in ("isInstanceOfType", "isinstanceoftype"):
                # Simplifié — no-op dans l'émulateur
                return None
            if method == "fail":
                msg = args[0] if args else "Assertion failed"
                raise ApexException(msg)

        # Custom Settings: SomeObject__c.getInstance('name')
        if call.obj.endswith("__c") and method == "getInstance":
            sobject = call.obj
            name = args[0] if args else "default"
            import contextlib
            import psycopg2.extras
            # Sur PgDataOrg, le savepoint protège les écritures DML en attente ;
            # sinon rollback complet (sans récupération la transaction resterait
            # 'aborted' et toutes les requêtes suivantes échoueraient)
            savepoint = getattr(self.org, "_savepoint", None)
            try:
                with savepoint() if savepoint else contextlib.nullcontext():
                    cur = self.org.conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute(
                        "SELECT * FROM {}.{} WHERE name = %s LIMIT 1".format(
                            self.org.schema_name, sobject.lower()),
                        [name],
                    )
                    row = cur.fetchone()
                    cur.close()
                if row:
                    result = {"_sobject_type": sobject}
                    result.update(row)
                    return result
            except Exception:
                if not savepoint:
                    self.org.conn.rollback()
            return {"_sobject_type": sobject}

        raise Exception("Méthode inconnue: {}.{}()".format(call.obj, method))

    def _call_on_value(self, obj, method, args):
        """Appelle une méthode sur une valeur (pour le chaînage)."""
        if obj is None:
            # Null-safe: return sensible defaults
            if method in ("size", "length", "indexOf"):
                return 0
            if method in ("isEmpty",):
                return True
            if method in ("contains", "containsKey", "startsWith", "endsWith"):
                return False
            return None
        if isinstance(obj, str):
            return self._call_string_method(obj, method, args)
        if isinstance(obj, list):
            return self._call_list_method(obj, method, args)
        if isinstance(obj, set):
            return self._call_set_method(obj, method, args)
        if isinstance(obj, dict):
            return self._call_map_method(obj, method, args)
        if isinstance(obj, (int, float)):
            _num_methods = {
                "intValue": lambda: int(obj),
                "longValue": lambda: int(obj),
                "doubleValue": lambda: float(obj),
                "format": lambda: str(obj),
                "abs": lambda: abs(obj),
                "setScale": lambda: round(float(obj), int(args[0])) if args else float(obj),
                "scale": lambda: len(str(float(obj)).split('.')[-1]) if '.' in str(float(obj)) else 0,
                "precision": lambda: len(str(abs(obj)).replace('.', '').lstrip('0')) or 1,
                "round": lambda: round(obj),
                "stripTrailingZeros": lambda: float(str(float(obj)).rstrip('0').rstrip('.')),
                "toPlainString": lambda: str(obj),
                "valueOf": lambda: obj,
                "compareTo": lambda: (0 if obj == args[0] else (-1 if obj < args[0] else 1)) if args else 0,
                "min": lambda: min(obj, args[0]) if args else obj,
                "max": lambda: max(obj, args[0]) if args else obj,
                "pow": lambda: obj ** int(args[0]) if args else obj,
                "divide": lambda: float(obj) / float(args[0]) if args and len(args) >= 2 else float(obj) / float(args[0]) if args else float(obj),
            }
            if method in _num_methods:
                return _num_methods[method]()
            return obj
        raise Exception("Impossible d'appeler .{}() sur {}".format(method, type(obj).__name__))

    def _call_string_method(self, s, method, args):
        import re as _re

        def _split():
            if args and args[0] == '':
                return list(s)
            if len(args) >= 2:
                return _re.split(args[0], s, maxsplit=int(args[1]) - 1) if int(args[1]) > 0 else _re.split(args[0], s)
            return _re.split(args[0], s) if args else [s]

        def _substring_between():
            if len(args) >= 2:
                start = s.find(args[0])
                if start == -1:
                    return None
                start += len(args[0])
                end = s.find(args[1], start)
                return s[start:end] if end != -1 else None
            tag = args[0] if args else ''
            start = s.find(tag)
            if start == -1:
                return None
            start += len(tag)
            end = s.find(tag, start)
            return s[start:end] if end != -1 else None

        methods = {
            # --- Existants ---
            "length": lambda: len(s),
            "contains": lambda: args[0] in s if args else False,
            "startsWith": lambda: s.startswith(args[0]) if args else False,
            "endsWith": lambda: s.endswith(args[0]) if args else False,
            "toLowerCase": lambda: s.lower(),
            "toUpperCase": lambda: s.upper(),
            "trim": lambda: s.strip(),
            "substring": lambda: s[int(args[0]):int(args[1])] if len(args) >= 2 else s[int(args[0]):],
            "indexOf": lambda: s.find(args[0], int(args[1])) if len(args) >= 2 else (s.find(args[0]) if args else -1),
            "replace": lambda: s.replace(args[0], args[1]) if len(args) >= 2 else s,
            "split": _split,
            "left": lambda: s[:int(args[0])] if args else s,
            "right": lambda: s[-int(args[0]):] if args else s,
            "removeStart": lambda: s[len(args[0]):] if args and s.startswith(args[0]) else s,
            "removeEnd": lambda: s[:-len(args[0])] if args and s.endswith(args[0]) else s,
            "leftPad": lambda: s.rjust(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "replaceAll": lambda: _re.sub(args[0], args[1], s) if len(args) >= 2 else s,
            "equals": lambda: s == args[0] if args else False,
            "equalsIgnoreCase": lambda: s.lower() == args[0].lower() if args and isinstance(args[0], str) else False,
            "charAt": lambda: s[int(args[0])] if args else '',
            "repeat": lambda: s * int(args[0]) if args else s,
            "abbreviate": lambda: (s[:int(args[0]) - 3] + "...") if args and len(s) > int(args[0]) else s,
            "capitalize": lambda: s[0].upper() + s[1:] if s else s,
            "escapeSingleQuotes": lambda: s.replace("'", "\\'"),
            "normalizeSpace": lambda: " ".join(s.split()),
            "countMatches": lambda: s.count(args[0]) if args else 0,
            "size": lambda: len(s),
            # --- Nouveaux : recherche & comparaison ---
            "containsIgnoreCase": lambda: args[0].lower() in s.lower() if args and isinstance(args[0], str) else False,
            "startsWithIgnoreCase": lambda: s.lower().startswith(args[0].lower()) if args and isinstance(args[0], str) else False,
            "endsWithIgnoreCase": lambda: s.lower().endswith(args[0].lower()) if args and isinstance(args[0], str) else False,
            "indexOfIgnoreCase": lambda: s.lower().find(args[0].lower(), int(args[1])) if len(args) >= 2 else (s.lower().find(args[0].lower()) if args else -1),
            "lastIndexOf": lambda: s.rfind(args[0], 0, int(args[1]) + 1) if len(args) >= 2 else (s.rfind(args[0]) if args else -1),
            "lastIndexOfIgnoreCase": lambda: s.lower().rfind(args[0].lower(), 0, int(args[1]) + 1) if len(args) >= 2 else (s.lower().rfind(args[0].lower()) if args else -1),
            "compareTo": lambda: (0 if s == args[0] else (-1 if s < args[0] else 1)) if args else 0,
            # --- Nouveaux : manipulation ---
            "mid": lambda: s[int(args[0]):int(args[0]) + int(args[1])] if len(args) >= 2 else s,
            "reverse": lambda: s[::-1],
            "rightPad": lambda: s.ljust(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "center": lambda: s.center(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "remove": lambda: s.replace(args[0], '') if args else s,
            "removeStartIgnoreCase": lambda: s[len(args[0]):] if args and s.lower().startswith(args[0].lower()) else s,
            "removeEndIgnoreCase": lambda: s[:-len(args[0])] if args and s.lower().endswith(args[0].lower()) else s,
            "replaceFirst": lambda: _re.sub(args[0], args[1], s, count=1) if len(args) >= 2 else s,
            "uncapitalize": lambda: s[0].lower() + s[1:] if s else s,
            "swapCase": lambda: s.swapcase(),
            "deleteWhitespace": lambda: ''.join(c for c in s if not c.isspace()),
            "stripHtmlTags": lambda: _re.sub(r'<[^>]+>', '', s),
            # --- Nouveaux : substring helpers ---
            "substringAfter": lambda: s[s.find(args[0]) + len(args[0]):] if args and s.find(args[0]) != -1 else '',
            "substringAfterLast": lambda: s[s.rfind(args[0]) + len(args[0]):] if args and s.rfind(args[0]) != -1 else '',
            "substringBefore": lambda: s[:s.find(args[0])] if args and s.find(args[0]) != -1 else s,
            "substringBeforeLast": lambda: s[:s.rfind(args[0])] if args and s.rfind(args[0]) != -1 else s,
            "substringBetween": _substring_between,
            # --- Nouveaux : tests de contenu ---
            "isAllLowerCase": lambda: s.islower() if s else False,
            "isAllUpperCase": lambda: s.isupper() if s else False,
            "isAlpha": lambda: s.isalpha() if s else False,
            "isAlphanumeric": lambda: s.isalnum() if s else False,
            "isAlphaSpace": lambda: all(c.isalpha() or c == ' ' for c in s) if s else False,
            "isAlphanumericSpace": lambda: all(c.isalnum() or c == ' ' for c in s) if s else False,
            "isNumeric": lambda: s.isdigit() if s else False,
            "isNumericSpace": lambda: all(c.isdigit() or c == ' ' for c in s) if s else False,
            "isWhitespace": lambda: s.isspace() if s else True,
            "containsWhitespace": lambda: any(c.isspace() for c in s),
            "containsAny": lambda: any(c in s for c in args[0]) if args else False,
            "containsNone": lambda: not any(c in s for c in args[0]) if args else True,
            "containsOnly": lambda: all(c in args[0] for c in s) if args else False,
            "isAsciiPrintable": lambda: all(32 <= ord(c) <= 126 for c in s) if s else True,
            # --- Nouveaux : char & code ---
            "getChars": lambda: [ord(c) for c in s],
            "hashCode": lambda: hash(s),
            "indexOfChar": lambda: s.find(chr(int(args[0])), int(args[1])) if len(args) >= 2 else (s.find(chr(int(args[0]))) if args else -1),
            # --- Nouveaux : distance ---
            "difference": lambda: args[0][len(_common_prefix(s, args[0])):] if args else '',
            "indexOfDifference": lambda: _common_prefix_len(s, args[0]) if args else -1,
            # --- Escape / unescape ---
            "escapeHtml4": lambda: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'),
            "escapeHtml3": lambda: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'),
            "escapeXml": lambda: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;'),
            "escapeJava": lambda: s.encode('unicode_escape').decode('ascii'),
            "escapeEcmaScript": lambda: s.encode('unicode_escape').decode('ascii').replace("'", "\\'"),
            "unescapeHtml4": lambda: _unescape_html(s),
            "unescapeHtml3": lambda: _unescape_html(s),
            "unescapeXml": lambda: s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'"),
            "unescapeJava": lambda: s.encode().decode('unicode_escape'),
        }
        if method in methods:
            return methods[method]()
        # Méthodes d'Id (les Id sont des chaînes) : getSObjectType via le préfixe
        if method == "getSObjectType":
            from .dml import SOBJECT_PREFIX
            prefix = s[:3]
            name = next((k for k, v in SOBJECT_PREFIX.items() if v == prefix), None)
            return {"_type": "SObjectType", "name": name or "Name"}
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
                # Support itératif : reprendre après le dernier match
                start = m.get("_pos", 0)
                match = m["_compiled"].search(m["_text"], start)
                m["_match"] = match
                if match:
                    m["_pos"] = match.end()
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
            if method == "replaceAll":
                return m["_compiled"].sub(args[0], m["_text"]) if args else m["_text"]
            if method == "replaceFirst":
                return m["_compiled"].sub(args[0], m["_text"], count=1) if args else m["_text"]
            if method == "reset":
                m["_pos"] = 0
                m["_match"] = None
                if args:
                    m["_text"] = str(args[0])
                return m
            if method == "start":
                match = m.get("_match")
                return match.start(int(args[0]) if args else 0) if match else -1
            if method == "end":
                match = m.get("_match")
                return match.end(int(args[0]) if args else 0) if match else -1
            if method == "groupCount":
                match = m.get("_match")
                return len(match.groups()) if match else 0
            if method == "hitEnd":
                return m.get("_pos", 0) >= len(m["_text"])
            if method == "lookingAt":
                match = m["_compiled"].match(m["_text"])
                m["_match"] = match
                return match is not None
            if method == "pattern":
                return m.get("_pattern", "")

        # Blob object
        if m.get("_type") == "Blob":
            data = m.get("_data", b"")
            if method == "toString":
                return data.decode('utf-8') if isinstance(data, bytes) else str(data)
            if method == "size":
                return len(data) if isinstance(data, bytes) else len(str(data).encode('utf-8'))

        # Schema.sObjectType.X → DescribeSObjectResult (token Apex) ; permet
        # Schema.sObjectType.Lead.isAccessible() et .fields
        if m.get("_type") == "SchemaSObjectTypeMap":
            return {
                "_type": "DescribeSObjectResult",
                "name": method,
                "label": method,
                "labelPlural": method + "s",
                "keyPrefix": method[:3].lower(),
                "isCustom": method.endswith("__c"),
                "isAccessible": True,
                "isCreateable": True,
                "isUpdateable": True,
                "isDeletable": True,
                "isQueryable": True,
                "isSearchable": True,
            }

        # SObjectType object (Schema describe)
        if m.get("_type") == "SObjectType":
            sobj_name = m.get("name", "")
            if method == "getDescribe":
                return {
                    "_type": "DescribeSObjectResult",
                    "name": sobj_name,
                    "label": sobj_name,
                    "labelPlural": sobj_name + "s",
                    "keyPrefix": sobj_name[:3].lower(),
                    "isCustom": sobj_name.endswith("__c"),
                    "isAccessible": True,
                    "isCreateable": True,
                    "isUpdateable": True,
                    "isDeletable": True,
                    "isQueryable": True,
                    "isSearchable": True,
                }
            if method == "newSObject":
                return {"_sobject_type": sobj_name}

        # DescribeSObjectResult
        if m.get("_type") == "DescribeSObjectResult":
            if method == "fields":
                return {"_type": "FieldMap", "_sobject": m.get("name", "")}
            if method == "getRecordTypeInfosByDeveloperName":
                return {}
            if method == "getRecordTypeInfosByName":
                return {}
            # Getter pour propriétés
            if method in m:
                return m[method]
            if method.startswith("get"):
                key = method[3:]
                key = key[0].lower() + key[1:] if key else ""
                return m.get(key)
            if method.startswith("is"):
                key = method
                return m.get(key, False)

        # TimeZone object
        if m.get("_type") == "TimeZone":
            if method == "getID":
                return m.get("id", "GMT")
            if method == "toString":
                return m.get("id", "GMT")

        # FormulaBuilder instance methods (fluent)
        if m.get("_type") == "FormulaBuilder":
            return self._call_formula_builder(m, method, args)

        # FormulaInstance methods
        if m.get("_type") == "FormulaInstance":
            return self._call_formula_instance(m, method, args)

        # FormulaRecalcResult
        if m.get("_type") == "FormulaRecalcResult":
            if method == "isSuccess":
                return m.get("_success", True)
            if method == "getSObject":
                return m.get("_record", {})
            if method == "getErrors":
                return m.get("_errors", [])

        # SystemLabel — System.Label.XXX returns ''
        if m.get("_type") == "SystemLabel":
            return ""  # All custom labels return empty string

        # SaveResult
        if m.get("_type") == "SaveResult":
            if method == "isSuccess":
                return m.get("success", True)
            if method == "getId":
                return m.get("id")
            if method == "getErrors":
                return m.get("errors", [])

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

        # Http — callout réel, mock, ou défaut
        if m.get("_type") == "Http":
            if method == "send":
                req = args[0] if args else {}
                if self.named_credentials and isinstance(req, dict):
                    from .callout import execute_callout
                    return execute_callout(req, self.named_credentials)
                return self._http_send(req)

        # HttpRequest
        if m.get("_type") == "HttpRequest":
            if method == "setHeader":
                if "_headers" not in m:
                    m["_headers"] = {}
                if len(args) >= 2:
                    m["_headers"][args[0]] = args[1]
                return None
            if method == "getHeader":
                return m.get("_headers", {}).get(args[0], "") if args else ""
            if method in ("setEndpoint", "setMethod", "setBody", "setTimeout"):
                m["_" + method[3:].lower()] = args[0] if args else None
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
            if method == "getStatus":
                code = m.get("_statusCode", 200)
                statuses = {200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request",
                            401: "Unauthorized", 404: "Not Found", 500: "Internal Server Error"}
                return statuses.get(code, "Unknown")
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

        # DateTime object
        if m.get("_type") == "DateTime":
            if method == "date":
                return {"_type": "Date", "year": m.get("year"), "month": m.get("month"), "day": m.get("day")}
            if method == "year":
                return m.get("year")
            if method == "month":
                return m.get("month")
            if method == "day":
                return m.get("day")
            if method == "format":
                return "{}-{:02d}-{:02d}".format(m.get("year", 0), m.get("month", 0), m.get("day", 0))
            if method == "getTime":
                import datetime
                dt = datetime.datetime(m.get("year", 2000), m.get("month", 1), m.get("day", 1),
                                       m.get("hour", 0), m.get("minute", 0), m.get("second", 0))
                return int(dt.timestamp() * 1000)
            if method == "addDays":
                import datetime
                d = datetime.date(m["year"], m["month"], m["day"])
                d2 = d + datetime.timedelta(days=int(args[0]) if args else 0)
                return {"_type": "DateTime", "year": d2.year, "month": d2.month, "day": d2.day}

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
        # Exception-like dicts: getMessage(), getTypeName(), etc.
        if method == "getMessage":
            return m.get("getMessage", m.get("message", str(m)))
        if method == "getTypeName":
            return m.get("_type", "Exception")
        if method == "getStackTraceString":
            return ""

        methods = {
            "put": lambda: m.__setitem__(args[0], args[1]) if len(args) >= 2 else None,
            "get": lambda: m.get(args[0]) if args else None,
            "containsKey": lambda: args[0] in m if args else False,
            "keySet": lambda: set(m.keys()),
            "values": lambda: list(m.values()),
            "size": lambda: len(m),
            "isEmpty": lambda: len(m) == 0,
            "remove": lambda: m.pop(args[0], None) if args else None,
            "clone": lambda: dict(m),
        }
        if method in methods:
            return methods[method]()
        # Fallback: try field access (covers SObject-like dicts without _sobject_type)
        if method in m:
            return m[method]
        raise Exception("Map.{}() non supporté".format(method))

    # ------------------------------------------------------------------
    # FormulaEval namespace support
    # ------------------------------------------------------------------

    def _call_formula_builder(self, builder, method, args):
        """Méthodes fluentes du FormulaBuilder — retourne toujours le builder."""
        if method == "withType":
            builder["_context_type"] = args[0] if args else None
            return builder
        if method == "withReturnType":
            builder["_return_type"] = args[0] if args else None
            return builder
        if method == "withFormula":
            builder["_formula"] = args[0] if args else None
            return builder
        if method == "withGlobalVariables":
            builder["_globals"] = args[0] if args else []
            return builder
        if method == "parseAsTemplate":
            builder["_template"] = bool(args[0]) if args else False
            return builder
        if method == "build":
            formula_expr = builder.get("_formula", "")
            if not formula_expr:
                raise Exception("FormulaValidationException: formula expression is required")
            # Extraire les champs référencés
            import re
            refs = set()
            # Références dans les formules normales : identifiants simples
            for tok in re.finditer(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', formula_expr):
                word = tok.group()
                upper = word.upper()
                # Exclure les mots-clés et fonctions
                if upper not in ("AND", "OR", "NOT", "IF", "ISBLANK", "ISNULL",
                                 "ISPICKVAL", "TRUE", "FALSE", "NULL", "LEN", "TEXT",
                                 "TRIM", "UPPER", "LOWER", "LEFT", "RIGHT", "MID",
                                 "SUBSTITUTE", "CONTAINS", "BEGINS", "FIND",
                                 "CONCATENATE", "NOW", "TODAY", "YEAR", "MONTH", "DAY",
                                 "DATE", "ABS", "CEILING", "FLOOR", "ROUND", "MAX",
                                 "MIN", "MOD", "SQRT", "LOG", "LN", "EXP", "VALUE",
                                 "CASE", "BLANKVALUE", "NULLVALUE", "BR", "REGEX",
                                 "HYPERLINK", "IMAGE", "URLFOR", "ADDMONTHS",
                                 "DATETIMEVALUE", "DATEVALUE", "INCLUDES"):
                    refs.add(word)
            # Merge fields en mode template
            if builder.get("_template"):
                for m in re.finditer(r'\{!([^}]+)\}', formula_expr):
                    refs.add(m.group(1))
            return {
                "_type": "FormulaInstance",
                "_formula": formula_expr,
                "_return_type": builder.get("_return_type"),
                "_context_type": builder.get("_context_type"),
                "_globals": builder.get("_globals", []),
                "_template": builder.get("_template", False),
                "_referenced_fields": refs,
            }
        raise Exception("FormulaBuilder.{}() non supporté".format(method))

    def _call_formula_instance(self, instance, method, args):
        """Méthodes de FormulaInstance — evaluate() et getReferencedFields()."""
        if method == "getReferencedFields":
            return instance.get("_referenced_fields", set())
        if method == "evaluate":
            context_obj = args[0] if args else {}
            formula_expr = instance["_formula"]
            is_template = instance.get("_template", False)

            from .formula_engine import FormulaEngine, resolve_merge_fields

            # Construire le resolver depuis l'objet contexte
            def _resolver(ref):
                if isinstance(context_obj, dict):
                    # Chercher le champ directement
                    if ref in context_obj:
                        return context_obj[ref]
                    # Chemin pointé
                    parts = ref.split(".")
                    obj = context_obj
                    for p in parts:
                        if isinstance(obj, dict) and p in obj:
                            obj = obj[p]
                        else:
                            # Case-insensitive fallback
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    if k.lower() == p.lower():
                                        obj = v
                                        break
                                else:
                                    return None
                            else:
                                return None
                    return obj
                return None

            if is_template:
                # Mode template : résoudre {!Field} en texte
                return resolve_merge_fields(formula_expr, _resolver)

            engine = FormulaEngine(_resolver)
            result = engine.evaluate(formula_expr)

            # Coercion selon le return type
            ret_type = instance.get("_return_type", "").upper() if instance.get("_return_type") else ""
            if ret_type == "BOOLEAN":
                return bool(result)
            if ret_type == "STRING":
                return str(result) if result is not None else ""
            if ret_type == "NUMBER":
                if result is None:
                    return 0
                if isinstance(result, (int, float)):
                    return result
                try:
                    return float(result)
                except (ValueError, TypeError):
                    return 0

            return result
        raise Exception("FormulaInstance.{}() non supporté".format(method))

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

    def _resolve_method_in_chain(self, class_def, method_name, args=None):
        """Cherche une méthode en remontant la chaîne d'héritage."""
        for cls in self._resolve_class_chain(class_def):
            if args is not None and hasattr(cls, 'overloads') and method_name in cls.overloads:
                resolved = self._resolve_overload(cls, method_name, args)
                if resolved:
                    return resolved
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
        elif args:
            # Auto-constructeur pour les classes Exception sans constructeur explicite
            is_exception = any(
                c.parent_class and "Exception" in (c.parent_class or "")
                for c in chain
            )
            if is_exception:
                instance["message"] = args[0]
                instance["getMessage"] = args[0]

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

    @staticmethod
    def _json_convert_dates(obj):
        """Convertit les strings ISO datetime en dicts DateTime Apex."""
        import re as _re
        iso_pat = _re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')

        def _convert(val):
            if isinstance(val, str) and iso_pat.match(val):
                try:
                    parts = val.split("T")
                    date_parts = parts[0].split("-")
                    return {
                        "_type": "DateTime",
                        "year": int(date_parts[0]),
                        "month": int(date_parts[1]),
                        "day": int(date_parts[2]),
                    }
                except (ValueError, IndexError):
                    return val
            if isinstance(val, dict):
                return {k: _convert(v) for k, v in val.items()}
            if isinstance(val, list):
                return [_convert(v) for v in val]
            return val

        return _convert(obj)

    def _http_send(self, request):
        """Exécute Http.send() — délègue au mock si Test.setMock a été appelé,
        sinon fait un vrai appel HTTP."""
        if self._http_mock and isinstance(self._http_mock, dict) and "_class" in self._http_mock:
            respond = self._resolve_method_in_chain(self._http_mock["_class"], "respond")
            if respond:
                return self._invoke_instance_method(self._http_mock, respond, [request])
        # Vrai appel HTTP
        import requests
        endpoint = request.get("_endpoint", "")
        method = (request.get("_method", "GET") or "GET").upper()
        body = request.get("_body", "")
        headers = dict(request.get("_headers", {}) or {})
        timeout = request.get("_timeout")
        timeout_s = (timeout / 1000.0) if timeout else 30
        try:
            resp = requests.request(
                method=method, url=endpoint, headers=headers,
                data=body if body else None, timeout=timeout_s,
            )
            return {
                "_type": "HttpResponse",
                "_statusCode": resp.status_code,
                "_body": resp.text,
                "_headers": dict(resp.headers),
            }
        except Exception as e:
            print("HTTP callout failed: {}".format(e))
            return {"_type": "HttpResponse", "_statusCode": 500, "_body": str(e), "_headers": {}}

    def _invoke_instance_method(self, instance, method_def, args):
        """Invoque une méthode d'instance sur un objet."""
        class_def = instance.get("_class")
        if not class_def:
            return None

        saved_instance = self._current_instance
        saved_class = self._current_class
        saved_vars = self.variables.copy()
        saved_rt = self._current_return_type

        self._current_instance = instance
        self._current_class = class_def
        self._current_return_type = getattr(method_def, "return_type", None)

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
        self._current_return_type = saved_rt
        return result

    def _invoke_method(self, class_def, method_def, args):
        """Invoque une méthode avec un scope isolé (stack de variables)."""
        saved_class = self._current_class
        saved_vars = self.variables.copy()
        saved_rt = self._current_return_type
        self._current_class = class_def
        self._current_return_type = getattr(method_def, "return_type", None)

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
                if expr is not None:
                    new_scope[key] = self._eval(expr)
                else:
                    new_scope[key] = None
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

        # Persister les modifications de variables statiques (ClassName.field)
        for k, v in self.variables.items():
            if "." in k and k in saved_vars and saved_vars[k] != v:
                saved_vars[k] = v
            elif "." in k and k not in saved_vars:
                saved_vars[k] = v

        # Restaurer le scope précédent
        self.variables = saved_vars
        self._current_class = saved_class
        self._current_return_type = saved_rt
        return result

    def create_instance(self, class_name: str, constructor_args: list = None):
        """Instancie une classe : exécute le constructeur et retourne l'état d'instance."""
        if constructor_args is None:
            constructor_args = []
        class_def = self.classes.get(class_name)
        if not class_def:
            raise Exception("Classe '{}' non chargée".format(class_name))

        # Initialiser les propriétés {get;set;} à None
        instance_vars = {}
        for prop_name in class_def.properties:
            instance_vars[prop_name] = None

        # Trouver le constructeur (méthode dont le nom = nom de classe)
        constructor = class_def.methods.get(class_name)
        if constructor:
            saved_class = self._current_class
            saved_vars = self.variables.copy()
            self._current_class = class_def

            new_scope = dict(instance_vars)
            # Copier les constantes
            for k, v in saved_vars.items():
                if "." in k:
                    new_scope[k] = v
            for name, (type_name, expr) in class_def.constants.items():
                key = "{}.{}".format(class_def.name, name)
                if key not in new_scope:
                    new_scope[key] = self._eval(expr) if expr is not None else None
                new_scope[name] = new_scope[key]
            # Injecter les paramètres du constructeur
            for i, (ptype, pname) in enumerate(constructor.params):
                new_scope[pname] = constructor_args[i] if i < len(constructor_args) else None

            self.variables = new_scope
            try:
                for stmt in constructor.body:
                    self._exec_stmt(stmt)
            except ReturnException:
                pass

            # Capturer l'état d'instance (tout sauf les constantes ClassName.X)
            instance_vars = {k: v for k, v in self.variables.items()
                            if "." not in k}

            self.variables = saved_vars
            self._current_class = saved_class

        return instance_vars

    def call_instance_method(self, class_name: str, method_name: str,
                             instance_vars: dict, args: list = None):
        """Appelle une méthode d'instance avec un état pré-existant."""
        if args is None:
            args = []
        class_def = self.classes.get(class_name)
        if not class_def:
            raise Exception("Classe '{}' non chargée".format(class_name))
        method = class_def.methods.get(method_name)
        if not method:
            raise Exception("Méthode '{}.{}' non trouvée".format(class_name, method_name))

        saved_class = self._current_class
        saved_vars = self.variables.copy()
        self._current_class = class_def

        new_scope = dict(instance_vars)
        for k, v in saved_vars.items():
            if "." in k:
                new_scope[k] = v
        for name, (type_name, expr) in class_def.constants.items():
            key = "{}.{}".format(class_def.name, name)
            if key not in new_scope:
                new_scope[key] = self._eval(expr) if expr is not None else None
            new_scope[name] = new_scope[key]
        for i, (ptype, pname) in enumerate(method.params):
            new_scope[pname] = args[i] if i < len(args) else None

        self.variables = new_scope
        result = None
        try:
            for stmt in method.body:
                self._exec_stmt(stmt)
        except ReturnException as ret:
            result = ret.value

        # Mettre à jour l'état d'instance
        instance_vars.update({k: v for k, v in self.variables.items()
                              if "." not in k})

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
