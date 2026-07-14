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
    ReturnException, ApexException, BreakException, ContinueException,
    format_error, _common_prefix_len, _common_prefix, _unescape_html,
    _json_clean, _apex_str, _field_of, _is_soql_literal, _blob_bytes,
)


_UNHANDLED = object()  # sentinelle : méthode non gérée par un handler de namespace


class BuiltinsMixin:
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

    def _dispatch_static_ns(self, call, method, args):
        """Dispatch des méthodes statiques par namespace de la lib Apex."""
        handler = self._STATIC_NS.get(call.obj)
        if handler is not None:
            result = getattr(self, handler)(method, args)
            if result is not _UNHANDLED:
                return result
        if call.obj.endswith("__c") and method == "getInstance":
            return self._ns_custom_setting(call, method, args)
        raise Exception("Méthode inconnue: {}.{}()".format(call.obj, method))

    def _ns_apexpages(self, method, args):
        # ApexPages
        if method in ("addMessage", "addmessage"):
            msg = args[0] if args else {}
            self.variables.setdefault("__apex_messages__", []).append(msg)
            return None
        return _UNHANDLED

    def _ns_string(self, method, args):
        # String static methods
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

        # String static methods
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
        return _UNHANDLED

    def _ns_integer(self, method, args):
        # Integer static methods
        if method == "valueOf":
            val = args[0] if args else 0
            if val is None:
                raise ApexException("Argument cannot be null")
            return int(val)  # Lève ValueError si pas un nombre — comme Apex
        return _UNHANDLED

    def _ns_json(self, method, args):
        # JSON static methods
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
        return _UNHANDLED

    def _ns_pattern(self, method, args):
        # Pattern static methods
        if method == "compile":
            regex_str = args[0] if args else ""
            import re as _re
            return {"_type": "Pattern", "_compiled": _re.compile(regex_str), "_pattern": regex_str}
        return _UNHANDLED

    def _ns_math(self, method, args):
        # Math static methods
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
        return _UNHANDLED

    def _ns_formula(self, method, args):
        # Formula.builder() — System.Formula shorthand
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
        return _UNHANDLED

    def _ns_formulaeval(self, method, args):
        # FormulaEval.FormulaBuilder.builder() — explicit namespace
        if method == "FormulaBuilder":
            return {"_type": "FormulaEval.FormulaBuilderClass"}
        return _UNHANDLED

    def _ns_system(self, method, args):
        # System static methods
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
        if method == "Label":
            return ""

        # System.schedule
        if method == "schedule":
            return "FakeJobId_001"
        return _UNHANDLED

    def _ns_eventbus(self, method, args):
        # EventBus.publish — déclenche les triggers de Platform Event en contexte
        if method == "publish":
            published = args[0] if args else None
            events = published if isinstance(published, list) else [published]
            if self.platform_event_triggers:
                self._fire_platform_event([e for e in events if isinstance(e, dict)])
            return None
        return _UNHANDLED

    def _ns_type(self, method, args):
        # Type.forName — reflection
        if method == "forName":
            class_name = args[0] if args else None
            return {"_type": "ApexType", "className": class_name}
        return _UNHANDLED

    def _ns_uuid(self, method, args):
        # UUID.randomUUID()
        if method == "randomUUID":
            import uuid
            return str(uuid.uuid4())
        return _UNHANDLED

    def _ns_http(self, method, args):
        # Http.send() — callout réel, mock, ou défaut
        if method == "send":
            req = args[0] if args else {}
            if self.named_credentials and isinstance(req, dict):
                from ..callout import execute_callout
                return execute_callout(req, self.named_credentials)
            return self._http_send(req)
        return _UNHANDLED

    def _ns_url(self, method, args):
        # URL static methods
        if method == "getOrgDomainUrl":
            return {"_type": "URL", "_url": "https://test.salesforce.com"}
        return _UNHANDLED

    def _ns_database(self, method, args):
        # Database static methods
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
        return _UNHANDLED

    def _ns_encodingutil(self, method, args):
        # EncodingUtil static methods
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
        return _UNHANDLED

    def _ns_crypto(self, method, args):
        # Crypto static methods
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
        return _UNHANDLED

    def _ns_date(self, method, args):
        # Date static methods
        if method == "newInstance":
            if len(args) >= 3:
                return {"_type": "Date", "year": int(args[0]), "month": int(args[1]), "day": int(args[2])}
            return None
        if method == "today":
            import datetime
            d = datetime.date.today()
            return {"_type": "Date", "year": d.year, "month": d.month, "day": d.day}
        return _UNHANDLED

    def _ns_datetime(self, method, args):
        # DateTime static methods
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
        return _UNHANDLED

    def _ns_test(self, method, args):
        # Test static methods
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
        return _UNHANDLED

    def _ns_userinfo(self, method, args):
        # UserInfo static methods
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
        return _UNHANDLED

    def _ns_limits(self, method, args):
        # Limits static methods
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
        return _UNHANDLED

    def _ns_schema(self, method, args):
        # Schema static methods
        if method == "getGlobalDescribe":
            # Retourne un Map<String, SObjectType> basé sur les tables connues de l'org
            try:
                tables = self.org.get_sobject_names() if hasattr(self.org, 'get_sobject_names') else []
            except Exception:
                tables = []
            return {t: {"_type": "SObjectType", "name": t} for t in tables}
        if method == "describeSObjects":
            return [{"_type": "DescribeSObjectResult", "name": a} for a in (args[0] if args and isinstance(args[0], list) else [])]
        return _UNHANDLED

    def _ns_sobjecttype(self, method, args):
        # Schema.SObjectType.XXX — e.g. Schema.SObjectType.Account
        sobject_name = method
        return {"_type": "SObjectType", "name": sobject_name}
        return _UNHANDLED

    def _ns_blob(self, method, args):
        # Blob static methods (compléter)
        if method == "valueOf":
            val = str(args[0]) if args else ""
            return {"_type": "Blob", "_data": val.encode('utf-8')}
        if method == "toPdf":
            val = str(args[0]) if args else ""
            return {"_type": "Blob", "_data": val.encode('utf-8')}
        return _UNHANDLED

    def _ns_id(self, method, args):
        # Id static methods
        if method == "valueOf":
            return str(args[0]) if args else None
        return _UNHANDLED

    def _ns_decimal(self, method, args):
        # Decimal static methods
        if method == "valueOf":
            try:
                return float(args[0]) if args else 0.0
            except (ValueError, TypeError):
                return 0.0
        return _UNHANDLED

    def _ns_double(self, method, args):
        # Double static methods
        if method == "valueOf":
            try:
                return float(args[0]) if args else 0.0
            except (ValueError, TypeError):
                return 0.0
        return _UNHANDLED

    def _ns_assert(self, method, args):
        # Assert class (API 59+)
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
