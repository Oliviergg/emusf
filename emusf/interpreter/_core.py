"""Interpréteur Apex — parcourt un AST et exécute (classe principale)."""

from __future__ import annotations

from ..apex_parser import ApexParser
from ..ast_nodes import (
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
from ._helpers import (
    ReturnException, ApexException, BreakException, ContinueException,
    format_error, _common_prefix_len, _common_prefix, _unescape_html,
    _json_clean, _apex_str, _field_of, _is_soql_literal, _blob_bytes,
)
from ._statements import StatementsMixin
from ._expressions import ExpressionsMixin
from ._builtins import BuiltinsMixin
from ._values import ValuesMixin
from ._classes import ClassesMixin


class ApexInterpreter(StatementsMixin, ExpressionsMixin, BuiltinsMixin,
                      ValuesMixin, ClassesMixin):
    """Interprète un AST Apex. Assemblé de mixins par domaine."""

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
