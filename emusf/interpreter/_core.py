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
        self._current_method_class = None  # classe qui définit la méthode courante
        self._current_instance = None  # Instance en cours (pour this)
        self.named_credentials = named_credentials or {}  # Named Credentials (YAML)
        self._http_mock = None  # Instance HttpCalloutMock pour Test.setMock
        self._current_user = None  # User courant (System.runAs), None = admin
        self._current_profile = None  # Nom du profil du user courant
        self.job_queue = None  # File de Queueables (SyncJobQueue) si branchée
        # Triggers de Platform Event : {sobject_lower: (event_var, body_stmts)}
        self.platform_event_triggers = {}
        self._flushing_jobs = False  # garde de ré-entrance pour System.enqueueJob
        # Budget d'opérations asynchrones (Platform Events + Queueables) par run.
        # En réel chaque event/job est une transaction séparée avec des limites
        # de gouverneur ; en synchrone une chaîne qui se ré-enfile (polling
        # CheckQueueJob, cascade de la machine à états) tournerait sans fin.
        self.async_budget = 200

    def _resolve_profile_name(self, user):
        """Nom du profil d'un user dict (via la table profile), None sinon."""
        if not isinstance(user, dict):
            return None
        from ._helpers import _ci_key
        pkey = _ci_key(user, "ProfileId")
        profile_id = user.get(pkey) if pkey else None
        if not profile_id:
            return None
        try:
            rows = self.org.execute_soql(
                "[SELECT Name FROM Profile WHERE Id = '{}']".format(profile_id))
            if rows:
                return rows[0].get("Name") or rows[0].get("name")
        except Exception:
            pass
        return None

    def _user_grants(self):
        """Grants (objets/champs) du user courant via ses PermissionSetAssignment
        et le registre org.permset_grants (rempli par le chargeur SFDX/runner).
        None si aucun permission set assigné."""
        user = self._current_user or {}
        from ._helpers import _ci_key
        ukey = _ci_key(user, "Id")
        user_id = user.get(ukey) if ukey else None
        if not user_id:
            return None
        cache = getattr(self, "_grants_cache", None)
        if cache is None:
            cache = self._grants_cache = {}
        if user_id in cache:
            return cache[user_id]
        registry = getattr(self.org, "permset_grants", None) or {}
        merged = None
        try:
            rows = self.org.execute_soql(
                "[SELECT PermissionSetId FROM PermissionSetAssignment "
                "WHERE AssigneeId = '{}']".format(user_id))
            for row in rows or []:
                ps_id = row.get("PermissionSetId") or row.get("permissionsetid")
                if not ps_id:
                    continue
                ps = self.org.execute_soql(
                    "[SELECT Name FROM PermissionSet WHERE Id = '{}']".format(ps_id))
                name = (ps[0].get("Name") or ps[0].get("name") or "").lower() if ps else ""
                grants = registry.get(name)
                if grants:
                    if merged is None:
                        merged = {"objects": {}, "fields": {}}
                    for obj, ops in grants.get("objects", {}).items():
                        cur = merged["objects"].setdefault(obj, {})
                        for op, allowed in ops.items():
                            cur[op] = cur.get(op, False) or allowed
                    for f, ops in grants.get("fields", {}).items():
                        cur = merged["fields"].setdefault(f, {})
                        for op, allowed in ops.items():
                            cur[op] = cur.get(op, False) or allowed
                elif name:
                    # Permission set assigné mais grants inconnus : accès global
                    # (comportement historique binaire)
                    merged = {"objects": {"*": {"read": True, "create": True,
                                                "edit": True, "delete": True}},
                              "fields": {}}
        except Exception:
            pass
        cache[user_id] = merged
        return merged

    def _describe_access(self, sobject=None, field=None, op="read") -> bool:
        """Accès CRUD/FLS du user courant. True hors System.runAs ; sous le
        profil 'Minimum Access - Salesforce', accès selon les permission sets
        assignés (granularité objet/champ via org.permset_grants)."""
        prof = self._current_profile
        if not (prof and "minimum access" in prof.lower()):
            return True
        grants = self._user_grants()
        if grants is None:
            return False
        objects = grants.get("objects", {})
        if "*" in objects:
            return True
        if sobject is None:
            return bool(objects)
        so = sobject.lower()
        if field is not None:
            fl = field.lower()
            fields = grants.get("fields", {})
            f = fields.get(so + "." + fl)
            if f is None:
                # FLS des composants d'adresse portée par le champ composé
                # (ShippingStreet/City/… → ShippingAddress)
                for prefix in ("shipping", "billing", "mailing", "other"):
                    if fl.startswith(prefix) and fl != prefix + "address":
                        f = fields.get(so + "." + prefix + "address")
                        break
            return bool(f and f.get(op if op in ("read", "edit") else "edit"))
        o = objects.get(so)
        return bool(o and o.get(op))

    def _soql_context(self):
        """Contexte de résolution des binds SOQL : variables locales + champs
        de l'instance courante (pour ':champ' référençant this.champ dans une
        méthode d'instance)."""
        if self._current_instance is None:
            return self.variables
        ctx = dict(self._current_instance)
        ctx.update(self.variables)  # les locales masquent les champs d'instance
        ctx["this"] = self._current_instance  # :this.champ
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
        if class_def is None:
            from ._helpers import _ci_key
            key = _ci_key(self.classes, class_name)
            if key is not None:
                class_def = self.classes[key]
        if not class_def:
            raise Exception("Classe '{}' non chargée".format(class_name))
        method = self._resolve_overload(class_def, method_name, args)
        if not method:
            raise Exception("Méthode '{}.{}' non trouvée".format(class_name, method_name))
        return self._invoke_method(class_def, method, args)

    @staticmethod
    def _arg_type_score(param_type: str, arg) -> int:
        """Compatibilité d'un argument avec un type de paramètre déclaré.

        2 = match fort, 1 = compatible, 0 = neutre (inconnu/null), -1 = incompatible.
        Les SObjects sont des dicts marqués _sobject_type ; les instances de
        classes user portent _class/_type ; les résultats SOQL sont des dicts nus.
        """
        import datetime as _dt

        p = param_type.lower().strip()
        if arg is None or p == "object":
            return 1 if p == "object" and arg is not None else 0
        if p.startswith("list<") or p.endswith("[]"):
            return 2 if isinstance(arg, list) else -1
        if p.startswith("set<"):
            return 2 if isinstance(arg, set) else -1
        if p.startswith("map<"):
            return (2 if isinstance(arg, dict)
                    and "_class" not in arg and "_sobject_type" not in arg else -1)
        if p in ("string", "id"):
            return 2 if isinstance(arg, str) else -1
        if p == "boolean":
            return 2 if isinstance(arg, bool) else -1
        if p in ("integer", "int", "long"):
            if isinstance(arg, bool):
                return -1
            return 2 if isinstance(arg, int) else -1
        if p in ("decimal", "double"):
            if isinstance(arg, bool):
                return -1
            return 2 if isinstance(arg, float) else (1 if isinstance(arg, int) else -1)
        if p == "blob":
            return 2 if isinstance(arg, dict) and arg.get("_type") == "Blob" else -1
        if p == "date":
            return 2 if isinstance(arg, _dt.date) or (
                isinstance(arg, dict) and arg.get("_type") == "Date") else -1
        if p in ("datetime",):
            return 2 if isinstance(arg, _dt.datetime) or (
                isinstance(arg, dict) and arg.get("_type") == "DateTime") else -1
        if p == "sobject":
            if isinstance(arg, dict) and "_class" not in arg:
                return 2 if "_sobject_type" in arg else 1
            return -1
        if isinstance(arg, dict):
            # SObject précis (Account, My_Object__c…)
            sobj = arg.get("_sobject_type")
            if sobj is not None:
                return 2 if sobj.lower() == p else -1
            # Instance de classe user : nom exact, puis chaîne d'héritage
            t = arg.get("_type")
            if t is not None and t.lower() == p:
                return 2
            chain = arg.get("_chain")
            if chain and any(c.name.lower() == p for c in chain):
                return 1
            cls = arg.get("_class")
            if cls is not None and p in [i.lower() for i in getattr(cls, "interfaces", [])]:
                return 1
            # Dict nu (résultat SOQL…) face à un type user/SObject précis : plausible
            if "_class" not in arg and "_type" not in arg:
                return 1
            return 0
        if isinstance(arg, (list, set)):
            return -1  # une collection ne matche pas un type scalaire/inconnu
        # Type inconnu (enum user, interface…) avec argument scalaire : neutre
        return 0

    def _resolve_overload(self, class_def, method_name: str, args: list):
        """Résout une surcharge par arité puis compatibilité de type de chaque
        argument. Ne retombe jamais aveuglément sur le premier candidat quand un
        argument est franchement incompatible (sinon les surcharges qui se
        délèguent — doInsert(SObject) → doInsert(List<SObject>) — bouclent)."""
        candidates = self._overloads_lookup(class_def, method_name)
        if not candidates:
            return self._method_lookup(class_def, method_name)

        matching = [m for m in candidates if len(m.params) == len(args)]
        if len(matching) == 1:
            return matching[0]
        if not matching:
            return self._method_lookup(class_def, method_name)

        best, best_score = None, None
        for m in matching:
            score, compatible = 0, True
            for (ptype, _pname), arg in zip(m.params, args):
                s = self._arg_type_score(ptype, arg)
                if s < 0:
                    compatible = False
                    break
                score += s
            if compatible and (best_score is None or score > best_score):
                best, best_score = m, score
        return best or matching[0]

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
        if class_def is None:
            from ._helpers import _ci_key
            key = _ci_key(self.classes, class_name)
            if key is not None:
                class_def = self.classes[key]
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
        if class_def is None:
            from ._helpers import _ci_key
            key = _ci_key(self.classes, class_name)
            if key is not None:
                class_def = self.classes[key]
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
