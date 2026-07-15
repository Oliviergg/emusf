"""Interpréteur Apex — ClassesMixin."""

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
    MethodDef, ClassDef, NewSet, SwitchWhen,
)
from ._helpers import (
    ReturnException, ApexException, BreakException, ContinueException,
    format_error, _common_prefix_len, _common_prefix, _unescape_html,
    _json_clean, _apex_str, _field_of, _is_soql_literal, _blob_bytes, _ci_key, ApexToken,
)


class ClassesMixin:
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

    @staticmethod
    def _method_lookup(cls, method_name):
        """Méthode d'une classe, insensible à la casse (comme Apex)."""
        m = cls.methods.get(method_name)
        if m is not None:
            return m
        ml = method_name.lower()
        for name, mdef in cls.methods.items():
            if name.lower() == ml:
                return mdef
        return None

    @staticmethod
    def _overloads_lookup(cls, method_name):
        """Surcharges d'une méthode, insensible à la casse. None si aucune."""
        overloads = getattr(cls, "overloads", None)
        if not overloads:
            return None
        found = overloads.get(method_name)
        if found is not None:
            return found
        ml = method_name.lower()
        for name, defs in overloads.items():
            if name.lower() == ml:
                return defs
        return None

    def _resolve_method_in_chain(self, class_def, method_name, args=None):
        """Cherche une méthode en remontant la chaîne d'héritage."""
        for cls in self._resolve_class_chain(class_def):
            if args is not None and self._overloads_lookup(cls, method_name):
                resolved = self._resolve_overload(cls, method_name, args)
                if resolved:
                    return resolved
            found = self._method_lookup(cls, method_name)
            if found is not None:
                return found
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

        # Fallback insensible à la casse (Apex l'est) — top-level puis inner
        key = _ci_key(self.classes, name)
        if key is not None:
            return self.classes[key]
        nl = name.lower()
        for cls in self.classes.values():
            for iname, idef in cls.inner_classes.items():
                if iname.lower() == nl:
                    return idef

        return None

    def _init_instance_fields(self, instance, chain):
        """Évalue les initialisateurs de champs d'instance (parent d'abord),
        avec this = instance : `List<X> queue = new List<X>();`,
        `private Organization orgShape = getOrgShape();`…
        Un initialisateur qui plante laisse le champ à null."""
        saved_instance = self._current_instance
        saved_class = self._current_class
        self._current_instance = instance
        try:
            for cls in reversed(chain):
                self._current_class = cls
                for field_name in cls.instance_fields:
                    const = cls.constants.get(field_name)
                    if const and const[1] is not None and instance.get(field_name) is None:
                        try:
                            instance[field_name] = self._eval(const[1])
                        except Exception:
                            pass
        finally:
            self._current_instance = saved_instance
            self._current_class = saved_class

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
        self._init_instance_fields(instance, chain)

        # Trouver et exécuter le constructeur
        constructor = None
        ctor_idx = 0
        for i, cls in enumerate(chain):
            ctor = self._find_constructor(cls, len(args))
            if ctor:
                constructor = ctor
                ctor_idx = i
                break
        if constructor:
            # super() implicite (comme Apex) : exécuter les constructeurs sans
            # argument des ancêtres (racine d'abord), sauf si le constructeur
            # commence par un super(...) explicite
            explicit_super = (bool(constructor.body)
                              and isinstance(constructor.body[0], MethodCallStmt)
                              and getattr(constructor.body[0].call, "obj", None) == "_super")
            if not explicit_super:
                for ancestor in reversed(chain[ctor_idx + 1:]):
                    parent_ctor = self._find_constructor(ancestor, 0)
                    if parent_ctor and not parent_ctor.params:
                        self._run_constructor(instance, ancestor, parent_ctor, [])
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
        self._init_instance_fields(instance, [class_def])

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
        # Contexte global Trigger : visible dans toutes les méthodes (comme Apex)
        if "Trigger" in saved_vars:
            new_scope["Trigger"] = saved_vars["Trigger"]
        for name, (type_name, expr_val) in class_def.constants.items():
            # Les champs d'instance initialisés sont aussi dans constants (builder) :
            # ils sont gérés à la construction, pas à chaque invocation (sinon
            # ré-exécution exponentielle des initialisateurs, et écrasement des
            # valeurs portées par l'instance).
            if name in class_def.instance_fields:
                continue
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
        saved_mc = self._current_method_class

        self._current_instance = instance
        self._current_class = class_def
        self._current_return_type = getattr(method_def, "return_type", None)
        self._current_method_class = getattr(method_def, "owner_class", None)

        new_scope = {}
        for k, v in saved_vars.items():
            if "." in k:
                new_scope[k] = v
        # Contexte global Trigger : visible dans toutes les méthodes (comme Apex)
        if "Trigger" in saved_vars:
            new_scope["Trigger"] = saved_vars["Trigger"]
        for name, (type_name, expr_val) in class_def.constants.items():
            # Les champs d'instance initialisés sont aussi dans constants (builder) :
            # ils sont gérés à la construction, pas à chaque invocation (sinon
            # ré-exécution exponentielle des initialisateurs, et écrasement des
            # valeurs portées par l'instance).
            if name in class_def.instance_fields:
                continue
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
        self._current_method_class = saved_mc
        return result

    def _invoke_method(self, class_def, method_def, args):
        """Invoque une méthode avec un scope isolé (stack de variables)."""
        saved_class = self._current_class
        saved_vars = self.variables.copy()
        saved_rt = self._current_return_type
        saved_mc = self._current_method_class
        self._current_class = class_def
        self._current_return_type = getattr(method_def, "return_type", None)
        self._current_method_class = getattr(method_def, "owner_class", None)

        # Nouveau scope : on garde les constantes de classe et les classes
        new_scope = {}

        # Copier les constantes de toutes les classes chargées
        for k, v in saved_vars.items():
            if "." in k:  # ClassName.CONST
                new_scope[k] = v
        # Contexte global Trigger : visible dans toutes les méthodes (comme Apex)
        if "Trigger" in saved_vars:
            new_scope["Trigger"] = saved_vars["Trigger"]

        # Injecter les constantes de la classe courante (nom court) — sans les
        # champs d'instance (gérés à la construction, voir _init_instance_fields)
        for name, (type_name, expr) in class_def.constants.items():
            if name in class_def.instance_fields:
                continue
            key = "{}.{}".format(class_def.name, name)
            if key not in new_scope:
                if expr is not None:
                    try:
                        new_scope[key] = self._eval(expr)
                    except Exception:
                        new_scope[key] = None
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
        self._current_method_class = saved_mc
        return result
