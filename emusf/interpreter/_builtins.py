"""Interpréteur Apex — BuiltinsMixin."""

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
    ReturnException, ApexException, AssertException, BreakException, ContinueException,
    format_error, _common_prefix_len, _common_prefix, _unescape_html,
    _json_clean, _apex_str, _field_of, _is_soql_literal, _blob_bytes, _ci_key, ApexToken,
)


_UNHANDLED = object()  # sentinelle : méthode non gérée par un handler de namespace


class BuiltinsMixin:
    def _exec_method_call(self, call: MethodCall):
        """Exécute un appel de méthode sur un objet ou une collection."""
        if call.obj == "this" and self._current_instance is not None:
            obj = self._current_instance
        else:
            obj = self.variables.get(call.obj)
        if (obj is None and call.obj not in self.variables
                and call.obj.lower() not in self._BUILTIN_NAMESPACES
                and call.obj not in self.classes):
            # Variable existante sous une autre casse (Apex est insensible)
            vkey = _ci_key(self.variables, call.obj)
            if vkey is not None:
                obj = self.variables[vkey]
        # Normaliser la casse d'un namespace built-in (sauf si masqué par une
        # variable locale ou une classe utilisateur du même nom)
        if (obj is None and call.obj not in self.classes
                and call.obj.lower() in self._BUILTIN_NAMESPACES
                and call.obj not in self._BUILTIN_NAMESPACES.values()):
            call = MethodCall(obj=self._BUILTIN_NAMESPACES[call.obj.lower()],
                              method=call.method, args=call.args)
        args = [self._eval(a) for a in call.args]
        method = call.method
        meth = method.lower()

        # Null-safe: appeler une méthode sur null retourne null
        if obj is None and call.obj not in self.classes and call.obj not in ("_self", "_super") and call.obj.lower() not in self._BUILTIN_NAMESPACES and not call.obj.endswith("__c") and _ci_key(self.classes, call.obj) is None:
            # Vérifier aussi si c'est une méthode de la classe courante
            if not (self._current_class and call.method in self._current_class.methods):
                return None

        # List, Set and numeric (Decimal/Integer…) methods → _call_on_value
        if isinstance(obj, (list, set)) or (
                isinstance(obj, (int, float)) and not isinstance(obj, bool)):
            return self._call_on_value(obj, method, args)

        # Stub (Test.createStub) : dérouter vers le StubProvider
        if isinstance(obj, dict) and "_stub_provider" in obj:
            return self._invoke_stub(obj, method, args)

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
            if meth == "getrecord":
                return {k: v for k, v in obj.items() if k not in ("_type",)}
            if meth == "getid":
                return obj.get("Id")
            if meth == "view":
                return {"_type": "PageReference", "url": "/" + (obj.get("Id") or "")}

        # Plain dict (Map) methods — ex: JSON.deserializeUntyped retourne des dicts
        # sans _type. Les dicts typés (Blob, Pattern…) vont à _call_map_method qui
        # gère leur type d'abord puis retombe sur les méthodes Map génériques.
        if isinstance(obj, dict) and "_class" not in obj and "_type" not in obj:
            # Méthodes d'instance SObject (réflexion)
            if meth == "getsobjecttype":
                return ApexToken({"_type": "SObjectType",
                                  "name": self._guess_sobject_type(obj) or "SObject"})
            if meth == "getpopulatedfieldsasmap":
                return {k: v for k, v in obj.items() if not k.startswith("_")}
            if meth == "clone":
                preserve_id = bool(args[0]) if args else False
                cloned = {k: v for k, v in obj.items()}
                if not preserve_id:
                    cloned.pop("Id", None)
                    cloned.pop("id", None)
                return cloned
            if meth == "get":
                return obj.get(args[0]) if args else None
            if meth == "put":
                if len(args) >= 2:
                    obj[args[0]] = args[1]
                return None
            if meth == "containskey":
                return args[0] in obj if args else False
            if meth == "keyset":
                return set(k for k in obj.keys() if not k.startswith("_"))
            if meth == "values":
                return [v for k, v in obj.items() if not k.startswith("_")]
            if meth == "size":
                return len([k for k in obj if not k.startswith("_")])
            if meth == "isempty":
                return len(obj) == 0
            if meth == "remove":
                return obj.pop(args[0], None) if args else None

        # All typed dicts (Pattern, Matcher, Date, HttpRequest, HttpResponse, etc.)
        if isinstance(obj, dict) and "_type" in obj and "_class" not in obj:
            return self._call_map_method(obj, method, args)

        # Special typed objects (fallback check) (Pattern, Matcher, Date, etc.)
        elif isinstance(obj, dict) and obj.get("_type") in ("Pattern", "Matcher", "Date", "DateTime"):
            return self._call_map_method(obj, method, args)

        # Map methods
        elif isinstance(obj, dict) and "_sobject_type" not in obj:
            if meth == "put":
                if len(args) >= 2:
                    obj[args[0]] = args[1]
                return None
            elif meth == "get":
                return obj.get(args[0]) if args else None
            elif meth == "containskey":
                return args[0] in obj if args else False
            elif meth == "keyset":
                return list(obj.keys())
            elif meth == "values":
                return list(obj.values())
            elif meth == "size":
                return len(obj)
            elif meth == "isempty":
                return len(obj) == 0
            elif meth == "remove":
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
            if meth == "getrecord":
                return {k: v for k, v in obj.items() if k != "_type"}
            if meth == "getid":
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

        # Appel de méthode statique sur une classe chargée (casse d'Apex libre)
        if call.obj in self.classes:
            return self.call_method(call.obj, method, args)
        if obj is None:
            cls_key = _ci_key(self.classes, call.obj)
            if cls_key is not None:
                return self.call_method(cls_key, method, args)

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

        return self._dispatch_static_ns(call, method, args)

    # Namespaces de la bibliothèque standard Apex -> handler dédié.
    _STATIC_NS = {
        "ApexPages": "_ns_apexpages",
        "String": "_ns_string",
        "Integer": "_ns_integer",
        "JSON": "_ns_json",
        "Pattern": "_ns_pattern",
        "Math": "_ns_math",
        "Formula": "_ns_formula",
        "FormulaEval": "_ns_formulaeval",
        "System": "_ns_system",
        "EventBus": "_ns_eventbus",
        "Type": "_ns_type",
        "UUID": "_ns_uuid",
        "Http": "_ns_http",
        "URL": "_ns_url",
        "Database": "_ns_database",
        "EncodingUtil": "_ns_encodingutil",
        "Crypto": "_ns_crypto",
        "Date": "_ns_date",
        "DateTime": "_ns_datetime",
        "Test": "_ns_test",
        "UserInfo": "_ns_userinfo",
        "Limits": "_ns_limits",
        "Schema": "_ns_schema",
        "SObjectType": "_ns_sobjecttype",
        "Blob": "_ns_blob",
        "blob": "_ns_blob",
        "Id": "_ns_id",
        "Decimal": "_ns_decimal",
        "Double": "_ns_double",
        "Assert": "_ns_assert",
    }

    def _invoke_stub(self, stub, method, args):
        """Appel de méthode sur un stub Test.createStub → StubProvider
        .handleMethodCall(stubbedObject, methodName, returnType,
        paramTypes, paramNames, args)."""
        provider = stub["_stub_provider"]
        if not (isinstance(provider, dict) and "_class" in provider):
            return None
        handler = self._resolve_method_in_chain(
            provider["_class"], "handleMethodCall")
        if handler is None:
            return None
        # Signature de la méthode stubée, si la classe est connue
        return_type, param_types, param_names = None, [], []
        cls = stub.get("_class")
        if cls is not None:
            mdef = self._method_lookup(cls, method)
            if mdef is not None:
                return_type = mdef.return_type
                param_types = [pt for pt, _ in mdef.params]
                param_names = [pn for _, pn in mdef.params]
        return self._invoke_instance_method(
            provider, handler,
            [stub, method, return_type, param_types, param_names, list(args)])

    @staticmethod
    def _guess_sobject_type(record):
        """Type d'un SObject dict : marqueur _sobject_type, sinon préfixe d'Id."""
        name = record.get("_sobject_type")
        if name:
            return name
        rid = record.get("Id") or record.get("id")
        if isinstance(rid, str) and len(rid) >= 3:
            from ..dml import SOBJECT_PREFIX
            for sobj, prefix in SOBJECT_PREFIX.items():
                if rid.startswith(prefix):
                    return sobj
        return None

    def _dispatch_static_ns(self, call, method, args):
        meth = method.lower()
        """Dispatch des méthodes statiques par namespace de la lib Apex."""
        handler = self._STATIC_NS.get(call.obj)
        if handler is not None:
            result = getattr(self, handler)(method, args)
            if result is not _UNHANDLED:
                return result
        if call.obj.endswith("__c") and meth == "getinstance":
            return self._ns_custom_setting(call, method, args)
        raise Exception("Méthode inconnue: {}.{}()".format(call.obj, method))

    def _ns_apexpages(self, method, args):
        meth = method.lower()
        # ApexPages
        if meth in ("addmessage", "addmessage"):
            msg = args[0] if args else {}
            self.variables.setdefault("__apex_messages__", []).append(msg)
            return None
        return _UNHANDLED

    def _ns_string(self, method, args):
        meth = method.lower()
        # String static methods
        if meth == "isblank":
            v = args[0] if args else None
            return v is None or (isinstance(v, str) and v.strip() == "")
        elif meth == "isnotblank":
            v = args[0] if args else None
            return v is not None and isinstance(v, str) and v.strip() != ""
        elif meth == "valueof":
            # String.valueOf(null) rend null (comme Apex), pas 'null'
            if not args or args[0] is None:
                return None
            return _apex_str(args[0])
        elif meth == "isempty":
            v = args[0] if args else None
            return v is None or (isinstance(v, str) and v == "")
        elif meth == "isnotempty":
            v = args[0] if args else None
            return v is not None and isinstance(v, str) and v != ""
        elif meth == "join":
            if len(args) >= 2:
                lst = args[0]
                sep = args[1]
                if isinstance(lst, list):
                    return sep.join(str(x) for x in lst)
            return ""
        elif meth == "format":
            if len(args) >= 2:
                template = args[0] if args else ''
                params = args[1] if len(args) > 1 else []
                if isinstance(params, list):
                    for i, p in enumerate(params):
                        template = template.replace('{' + str(i) + '}', str(p) if p is not None else 'null')
                return template
            return args[0] if args else ''
        elif meth == "fromchararray":
            return ''.join(chr(int(c)) for c in args[0]) if args and isinstance(args[0], list) else ''

        # String static methods
        if meth == "escapesinglequotes":
            return args[0].replace("'", "\\'") if args and isinstance(args[0], str) else (args[0] if args else "")
        if meth == "valueof":
            return _apex_str(args[0]) if args else ""
        if meth == "isblank":
            return args[0] is None or (isinstance(args[0], str) and args[0].strip() == "") if args else True
        if meth == "isnotblank":
            return args[0] is not None and isinstance(args[0], str) and args[0].strip() != "" if args else False
        if meth == "isempty":
            return args[0] is None or args[0] == "" if args else True
        if meth == "join":
            if len(args) >= 2:
                return str(args[1]).join(str(x) for x in args[0]) if isinstance(args[0], list) else str(args[0])
            return ""
        if meth == "format":
            return str(args[0]) if args else ""
        return _UNHANDLED

    def _ns_integer(self, method, args):
        meth = method.lower()
        # Integer static methods
        if meth == "valueof":
            val = args[0] if args else 0
            if val is None:
                raise ApexException("Argument cannot be null")
            return int(val)  # Lève ValueError si pas un nombre — comme Apex
        return _UNHANDLED

    def _ns_json(self, method, args):
        meth = method.lower()
        # JSON static methods
        import json as _json

        def _default(o):
            if isinstance(o, ClassDef):
                return o.name
            if isinstance(o, set):
                return list(o)
            return str(o)

        if meth == "serialize":
            return _json.dumps(_json_clean(args[0]), default=_default) if args else "null"
        elif meth == "serializepretty":
            return _json.dumps(_json_clean(args[0]), indent=2, default=_default) if args else "null"
        elif meth == "deserialize":
            if len(args) >= 2 and isinstance(args[0], str):
                return self._json_convert_dates(_json.loads(args[0]))
            return self._json_convert_dates(_json.loads(args[0])) if args else None
        elif meth == "deserializeuntyped":
            return _json.loads(args[0]) if args and isinstance(args[0], str) else None
        return _UNHANDLED

    def _ns_pattern(self, method, args):
        meth = method.lower()
        # Pattern static methods
        if meth == "compile":
            regex_str = args[0] if args else ""
            import re as _re
            return {"_type": "Pattern", "_compiled": _re.compile(regex_str), "_pattern": regex_str}
        return _UNHANDLED

    def _ns_math(self, method, args):
        meth = method.lower()
        # Math static methods
        if meth == "round":
            return round(args[0]) if args else 0
        elif meth == "abs":
            return abs(args[0]) if args else 0
        elif meth == "max":
            return max(args[0], args[1]) if len(args) >= 2 else (args[0] if args else 0)
        elif meth == "min":
            return min(args[0], args[1]) if len(args) >= 2 else (args[0] if args else 0)
        elif meth == "floor":
            import math
            return int(math.floor(args[0])) if args else 0
        elif meth == "ceil":
            import math
            return int(math.ceil(args[0])) if args else 0
        return _UNHANDLED

    def _ns_formula(self, method, args):
        meth = method.lower()
        # Formula.builder() — System.Formula shorthand
        if meth == "builder":
            return {"_type": "FormulaBuilder", "_context_type": None,
                    "_return_type": None, "_formula": None,
                    "_globals": [], "_template": False}
        elif meth == "recalculateformulas":
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
        return _UNHANDLED

    def _ns_formulaeval(self, method, args):
        meth = method.lower()
        # FormulaEval.FormulaBuilder.builder() — explicit namespace
        if meth == "formulabuilder":
            return {"_type": "FormulaEval.FormulaBuilderClass"}
        return _UNHANDLED

    def _ns_system(self, method, args):
        meth = method.lower()
        # System static methods
        if meth == "debug":
            val = args[0] if args else ""
            self.output.append(str(val))
            print("DEBUG: {}".format(val))
            return None
        elif meth == "enqueuejob":
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
        elif meth == "attachfinalizer":
            return None  # No-op
        elif meth == "currenttimemillis":
            import time
            return int(time.time() * 1000)
        elif meth == "today":
            import datetime
            d = datetime.date.today()
            return {"_type": "Date", "year": d.year, "month": d.month, "day": d.day}
        elif meth == "now":
            import datetime
            d = datetime.datetime.now()
            return {"_type": "DateTime", "year": d.year, "month": d.month, "day": d.day}
        elif meth == "abortjob":
            return None  # No-op

        # System.Label.XXX — custom labels (return empty string)
        if meth == "label":
            return ""

        # System.schedule
        if meth == "schedule":
            return "FakeJobId_001"
        return _UNHANDLED

    def _ns_eventbus(self, method, args):
        meth = method.lower()
        # EventBus.publish — déclenche les triggers de Platform Event en contexte
        if meth == "publish":
            published = args[0] if args else None
            events = published if isinstance(published, list) else [published]
            if self.platform_event_triggers:
                self._fire_platform_event([e for e in events if isinstance(e, dict)])
            return None
        return _UNHANDLED

    def _ns_type(self, method, args):
        meth = method.lower()
        # Type.forName — reflection
        if meth == "forname":
            class_name = args[0] if args else None
            return {"_type": "ApexType", "className": class_name}
        return _UNHANDLED

    def _ns_uuid(self, method, args):
        meth = method.lower()
        # UUID.randomUUID()
        if meth == "randomuuid":
            import uuid
            return str(uuid.uuid4())
        return _UNHANDLED

    def _ns_http(self, method, args):
        meth = method.lower()
        # Http.send() — callout réel, mock, ou défaut
        if meth == "send":
            req = args[0] if args else {}
            if self.named_credentials and isinstance(req, dict):
                from ..callout import execute_callout
                return execute_callout(req, self.named_credentials)
            return self._http_send(req)
        return _UNHANDLED

    def _ns_url(self, method, args):
        meth = method.lower()
        # URL static methods
        if meth == "getorgdomainurl":
            return {"_type": "URL", "_url": "https://test.salesforce.com"}
        return _UNHANDLED

    def _ns_database(self, method, args):
        meth = method.lower()
        # Database static methods
        if meth in ("insert", "update"):
            records = args[0] if args else None
            if isinstance(records, list):
                for r in records:
                    if isinstance(r, dict) and "_sobject_type" in r:
                        sobject = r["_sobject_type"]
                        data = {k: v for k, v in r.items() if k != "_sobject_type"}
                        try:
                            if meth == "insert":
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
                if meth == "insert":
                    result = self.org.insert(sobject, [data])
                    records["Id"] = result.record_ids[0]
                else:
                    self.org.update(sobject, [data])
                return {"_type": "SaveResult", "success": True, "id": records.get("Id")}
            return None
        if meth == "delete":
            records = args[0] if args else None
            # Simplified — just return success
            return [{"_type": "SaveResult", "success": True}]
        if meth == "query":
            soql = args[0] if args else ""
            return self.org.execute_soql("[{}]".format(soql), context=self._soql_context())
        if meth == "querywithbinds":
            soql = args[0] if args else ""
            binds = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
            ctx = dict(self._soql_context())
            ctx.update(binds)
            return self.org.execute_soql("[{}]".format(soql), context=ctx)
        if meth == "countquery":
            soql = args[0] if args else ""
            rows = self.org.execute_soql("[{}]".format(soql), context=self._soql_context())
            return len(rows) if isinstance(rows, list) else (rows or 0)
        if meth == "getquerylocator":
            soql = args[0] if args else ""
            rows = self.org.execute_soql("[{}]".format(soql), context=self._soql_context())
            return {"_type": "QueryLocator", "_rows": rows or [], "_soql": soql}
        if meth == "upsert":
            records = args[0] if args else None
            single = isinstance(records, dict)
            recs = [records] if single else (records or [])
            results = []
            for r in recs:
                if isinstance(r, dict) and "_sobject_type" in r:
                    sobject = r["_sobject_type"]
                    data = {k: v for k, v in r.items() if k != "_sobject_type"}
                    try:
                        if r.get("Id"):
                            self.org.update(sobject, [data])
                        else:
                            result = self.org.insert(sobject, [data])
                            r["Id"] = result.record_ids[0]
                        results.append({"_type": "UpsertResult", "success": True,
                                        "id": r.get("Id"), "created": True})
                    except Exception:
                        results.append({"_type": "UpsertResult", "success": False,
                                        "id": None, "created": False})
            return results[0] if single and results else results
        if meth == "executebatch":
            scope_size = int(args[1]) if len(args) > 1 and args[1] is not None else 200
            return self._execute_batch(args[0] if args else None, scope_size)
        return _UNHANDLED

    def _execute_batch(self, instance, scope_size=200):
        """Database.executeBatch — cycle Batchable start/execute/finish,
        exécuté en synchrone (comme au Test.stopTest en vrai)."""
        if not (isinstance(instance, dict) and "_class" in instance):
            return None
        from ..sf_runtime import generate_job_id
        job_id = generate_job_id()
        bc = {"_type": "BatchableContext", "_job_id": job_id}
        cls = instance["_class"]
        start = self._resolve_method_in_chain(cls, "start")
        scope = self._invoke_instance_method(instance, start, [bc]) if start else []
        if isinstance(scope, dict) and scope.get("_type") == "QueryLocator":
            rows = scope.get("_rows") or []
        elif isinstance(scope, list):
            rows = scope
        else:
            rows = []
        execute = self._resolve_method_in_chain(cls, "execute", [bc, rows[:scope_size]])
        if execute is not None:
            for i in range(0, len(rows), scope_size):
                self._invoke_instance_method(instance, execute, [bc, rows[i:i + scope_size]])
        finish = self._resolve_method_in_chain(cls, "finish")
        if finish is not None:
            self._invoke_instance_method(instance, finish, [bc])
        return job_id

    def _ns_encodingutil(self, method, args):
        meth = method.lower()
        # EncodingUtil static methods
        if meth == "base64encode":
            import base64
            return base64.b64encode(_blob_bytes(args[0])).decode() if args else ""
        if meth == "urlencode":
            import urllib.parse
            return urllib.parse.quote(str(args[0]), safe='') if args else ""
        if meth == "base64decode":
            import base64
            return base64.b64decode(str(args[0])).decode() if args else ""
        if meth == "converttohex":
            return _blob_bytes(args[0]).hex() if args else ""
        if meth == "convertfromhex":
            val = str(args[0]) if args else ""
            return {"_type": "Blob", "_data": bytes.fromhex(val)}
        return _UNHANDLED

    def _ns_crypto(self, method, args):
        meth = method.lower()
        # Crypto static methods
        if meth == "encrypt":
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
        if meth == "generateaeskey":
            import os
            bits = int(args[0]) if args else 128
            return {"_type": "Blob", "_data": os.urandom(bits // 8)}
        if meth == "getrandominteger":
            import random
            return random.randint(-2147483648, 2147483647)
        if meth == "generatemac":
            import hmac, hashlib
            algo = str(args[0]).lower().replace("-", "") if args else "hmacsha256"
            data = _blob_bytes(args[1]) if len(args) > 1 else b""
            key = _blob_bytes(args[2]) if len(args) > 2 else b""
            hash_map = {"hmacsha256": hashlib.sha256, "hmacsha1": hashlib.sha1, "hmacmd5": hashlib.md5}
            hash_fn = hash_map.get(algo, hashlib.sha256)
            return {"_type": "Blob", "_data": hmac.new(key, data, hash_fn).digest()}
        if meth == "generatedigest":
            import hashlib
            algo = str(args[0]).lower().replace("-", "") if args else "sha256"
            data = _blob_bytes(args[1]) if len(args) > 1 else b""
            hash_map = {"sha256": hashlib.sha256, "sha1": hashlib.sha1, "md5": hashlib.md5}
            hash_fn = hash_map.get(algo, hashlib.sha256)
            return {"_type": "Blob", "_data": hash_fn(data).digest()}
        return _UNHANDLED

    def _ns_date(self, method, args):
        meth = method.lower()
        # Date static methods
        if meth == "newinstance":
            if len(args) >= 3:
                return {"_type": "Date", "year": int(args[0]), "month": int(args[1]), "day": int(args[2])}
            return None
        if meth == "today":
            import datetime
            d = datetime.date.today()
            return {"_type": "Date", "year": d.year, "month": d.month, "day": d.day}
        return _UNHANDLED

    def _ns_datetime(self, method, args):
        meth = method.lower()
        # DateTime static methods
        if meth == "newinstance":
            if len(args) >= 3:
                return {"_type": "DateTime", "year": int(args[0]), "month": int(args[1]), "day": int(args[2])}
            return None
        if meth == "now":
            import datetime
            d = datetime.datetime.now()
            return {"_type": "DateTime", "year": d.year, "month": d.month, "day": d.day,
                    "hour": d.hour, "minute": d.minute, "second": d.second}
        if meth == "valueof":
            return {"_type": "DateTime"} if args else None
        return _UNHANDLED

    def _ns_test(self, method, args):
        meth = method.lower()
        # Test static methods
        if meth == "isrunningtest":
            return True
        if meth == "createstub":
            # Test.createStub(SomeType.class, provider) — les appels de méthode
            # sur le stub sont déroutés vers provider.handleMethodCall(...)
            type_name = args[0] if args else "Object"
            provider = args[1] if len(args) > 1 else None
            stub = {"_type": str(type_name), "_stub_provider": provider}
            cls = self._resolve_class(str(type_name))
            if cls is not None:
                stub["_class"] = cls
                stub["_chain"] = self._resolve_class_chain(cls)
            return stub
        if meth == "geteventbus":
            return {"_type": "EventBus"}
        if meth == "setmock":
            # Test.setMock(HttpCalloutMock.class, mockInstance)
            if len(args) >= 2:
                self._http_mock = args[1]
            return None
        if meth in ("starttest", "stoptest", "setcreateddate",
                    "setcurrentpage", "setcurrentpagereference", "setreadonlyapplicationmode",
                    "setfixedsearchresults", "loaddata"):
            return None
        return _UNHANDLED

    def _ns_userinfo(self, method, args):
        meth = method.lower()
        # UserInfo static methods
        _userinfo = {
            "getuserid": "005000000000001AAA",
            "getprofileid": "00e000000000001AAA",
            "getuserroleid": "00E000000000001AAA",
            "getname": "Test User",
            "getfirstname": "Test",
            "getlastname": "User",
            "getusername": "testuser@example.com",
            "getuseremail": "testuser@example.com",
            "getorganizationid": "00D000000000001AAA",
            "getorganizationname": "Test Org",
            "getdefaultcurrency": "EUR",
            "getlocale": "fr_FR",
            "getlanguage": "fr",
            "gettimezone": {"_type": "TimeZone", "id": "Europe/Paris"},
            "getsessionid": "fakesession000000000000000001",
            "ismulticurrencyorganization": False,
            "getuitheme": "Theme4d",
            "getuithemedisplayed": "Theme4d",
        }
        if meth in _userinfo:
            return _userinfo[meth]
        return None
        return _UNHANDLED

    def _ns_limits(self, method, args):
        meth = method.lower()
        # Limits static methods
        # Compteurs internes
        if not hasattr(self, '_limits'):
            self._limits = {"queries": 0, "dml": 0, "soql_rows": 0, "dml_rows": 0,
                            "cpu_time": 0, "heap_size": 0, "callouts": 0, "future_calls": 0,
                            "queueable_jobs": 0, "email_invocations": 0}
        _limit_getters = {
            "getqueries": lambda: self._limits["queries"],
            "getdmlstatements": lambda: self._limits["dml"],
            "getsoqlqueryrows": lambda: self._limits.get("soql_rows", 0),
            "getdmlrows": lambda: self._limits["dml_rows"],
            "getcputime": lambda: self._limits["cpu_time"],
            "getheapsize": lambda: self._limits["heap_size"],
            "getcallouts": lambda: self._limits["callouts"],
            "getfuturecalls": lambda: self._limits["future_calls"],
            "getqueueablejobs": lambda: self._limits["queueable_jobs"],
            "getemailinvocations": lambda: self._limits["email_invocations"],
            # Limites max (governor limits)
            "getlimitqueries": lambda: 100,
            "getlimitdmlstatements": lambda: 150,
            "getlimitsoqlqueryrows": lambda: 50000,
            "getlimitdmlrows": lambda: 10000,
            "getlimitcputime": lambda: 10000,
            "getlimitheapsize": lambda: 6000000,
            "getlimitcallouts": lambda: 100,
            "getlimitfuturecalls": lambda: 50,
            "getlimitqueueablejobs": lambda: 50,
            "getlimitemailinvocations": lambda: 10,
        }
        if meth in _limit_getters:
            return _limit_getters[meth]()
        return 0
        return _UNHANDLED

    def _ns_schema(self, method, args):
        meth = method.lower()
        # Schema static methods
        if meth == "getglobaldescribe":
            # Retourne un Map<String, SObjectType> basé sur les tables connues de l'org
            try:
                tables = self.org.get_sobject_names() if hasattr(self.org, 'get_sobject_names') else []
            except Exception:
                tables = []
            return {t: ApexToken({"_type": "SObjectType", "name": t}) for t in tables}
        if meth == "describesobjects":
            return [ApexToken({"_type": "DescribeSObjectResult", "name": a,
                               "label": a, "isCustom": str(a).endswith("__c"),
                               "isAccessible": True, "isCreateable": True,
                               "isUpdateable": True, "isDeletable": True,
                               "isQueryable": True, "isSearchable": True,
                               "fields": {"_type": "FieldMap", "_sobject": a}})
                    for a in (args[0] if args and isinstance(args[0], list) else [])]
        return _UNHANDLED

    def _ns_sobjecttype(self, method, args):
        # Schema.SObjectType.XXX — e.g. Schema.SObjectType.Account
        sobject_name = method
        return ApexToken({"_type": "SObjectType", "name": sobject_name})
        return _UNHANDLED

    def _ns_blob(self, method, args):
        meth = method.lower()
        # Blob static methods (compléter)
        if meth == "valueof":
            val = str(args[0]) if args else ""
            return {"_type": "Blob", "_data": val.encode('utf-8')}
        if meth == "topdf":
            val = str(args[0]) if args else ""
            return {"_type": "Blob", "_data": val.encode('utf-8')}
        return _UNHANDLED

    def _ns_id(self, method, args):
        meth = method.lower()
        # Id static methods
        if meth == "valueof":
            return str(args[0]) if args else None
        return _UNHANDLED

    def _ns_decimal(self, method, args):
        meth = method.lower()
        # Decimal static methods
        if meth == "valueof":
            try:
                return float(args[0]) if args else 0.0
            except (ValueError, TypeError):
                return 0.0
        return _UNHANDLED

    def _ns_double(self, method, args):
        meth = method.lower()
        # Double static methods
        if meth == "valueof":
            try:
                return float(args[0]) if args else 0.0
            except (ValueError, TypeError):
                return 0.0
        return _UNHANDLED

    def _ns_assert(self, method, args):
        meth = method.lower()
        # Assert class (API 59+)
        if meth in ("istrue", "istrue"):
            if not args or not args[0]:
                msg = args[1] if len(args) > 1 else "Assertion failed: expected true"
                raise AssertException(msg)
            return None
        if meth in ("isfalse", "isfalse"):
            if args and args[0]:
                msg = args[1] if len(args) > 1 else "Assertion failed: expected false"
                raise AssertException(msg)
            return None
        if meth in ("areequal", "areequal"):
            if len(args) >= 2 and args[0] != args[1]:
                msg = args[2] if len(args) > 2 else "Assertion failed: {} != {}".format(args[0], args[1])
                raise AssertException(msg)
            return None
        if meth in ("arenotequal", "arenotequal"):
            if len(args) >= 2 and args[0] == args[1]:
                msg = args[2] if len(args) > 2 else "Assertion failed: values are equal: {}".format(args[0])
                raise AssertException(msg)
            return None
        if meth in ("isnotnull", "isnotnull"):
            if not args or args[0] is None:
                msg = args[1] if len(args) > 1 else "Assertion failed: expected non-null"
                raise AssertException(msg)
            return None
        if meth in ("isnull", "isnull"):
            if args and args[0] is not None:
                msg = args[1] if len(args) > 1 else "Assertion failed: expected null"
                raise AssertException(msg)
            return None
        if meth in ("isinstanceoftype", "isinstanceoftype"):
            # Simplifié — no-op dans l'émulateur
            return None
        if meth == "fail":
            msg = args[0] if args else "Assertion failed"
            raise AssertException(msg)
        return _UNHANDLED

    def _ns_custom_setting(self, call, method, args):
        """Custom Settings : SomeObject__c.getInstance('name')."""
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
