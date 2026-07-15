"""Interpréteur Apex — ValuesMixin."""

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
    _json_clean, _apex_str, _field_of, _is_soql_literal, _blob_bytes, ApexToken,
)


class ValuesMixin:
    def _call_on_value(self, obj, method, args):
        meth = method.lower()
        """Appelle une méthode sur une valeur (pour le chaînage)."""
        if obj is None:
            # Null-safe: return sensible defaults
            if meth in ("size", "length", "indexof"):
                return 0
            if meth in ("isempty",):
                return True
            if meth in ("contains", "containskey", "startswith", "endswith"):
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
                "intvalue": lambda: int(obj),
                "longvalue": lambda: int(obj),
                "doublevalue": lambda: float(obj),
                "format": lambda: str(obj),
                "abs": lambda: abs(obj),
                "setscale": lambda: round(float(obj), int(args[0])) if args else float(obj),
                "scale": lambda: len(str(float(obj)).split('.')[-1]) if '.' in str(float(obj)) else 0,
                "precision": lambda: len(str(abs(obj)).replace('.', '').lstrip('0')) or 1,
                "round": lambda: round(obj),
                "striptrailingzeros": lambda: float(str(float(obj)).rstrip('0').rstrip('.')),
                "toplainstring": lambda: str(obj),
                "valueof": lambda: obj,
                "compareto": lambda: (0 if obj == args[0] else (-1 if obj < args[0] else 1)) if args else 0,
                "min": lambda: min(obj, args[0]) if args else obj,
                "max": lambda: max(obj, args[0]) if args else obj,
                "pow": lambda: obj ** int(args[0]) if args else obj,
                "divide": lambda: float(obj) / float(args[0]) if args and len(args) >= 2 else float(obj) / float(args[0]) if args else float(obj),
            }
            if meth in _num_methods:
                return _num_methods[meth]()
            return obj
        raise Exception("Impossible d'appeler .{}() sur {}".format(method, type(obj).__name__))

    def _call_string_method(self, s, method, args):
        meth = method.lower()
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
            "startswith": lambda: s.startswith(args[0]) if args else False,
            "endswith": lambda: s.endswith(args[0]) if args else False,
            "tolowercase": lambda: s.lower(),
            "touppercase": lambda: s.upper(),
            "trim": lambda: s.strip(),
            "substring": lambda: s[int(args[0]):int(args[1])] if len(args) >= 2 else s[int(args[0]):],
            "indexof": lambda: s.find(args[0], int(args[1])) if len(args) >= 2 else (s.find(args[0]) if args else -1),
            "replace": lambda: s.replace(args[0], args[1]) if len(args) >= 2 else s,
            "split": _split,
            "left": lambda: s[:int(args[0])] if args else s,
            "right": lambda: s[-int(args[0]):] if args else s,
            "removestart": lambda: s[len(args[0]):] if args and s.startswith(args[0]) else s,
            "removeend": lambda: s[:-len(args[0])] if args and s.endswith(args[0]) else s,
            "leftpad": lambda: s.rjust(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "replaceall": lambda: _re.sub(args[0], args[1], s) if len(args) >= 2 else s,
            "equals": lambda: s == args[0] if args else False,
            "equalsignorecase": lambda: s.lower() == args[0].lower() if args and isinstance(args[0], str) else False,
            "charat": lambda: s[int(args[0])] if args else '',
            "repeat": lambda: s * int(args[0]) if args else s,
            "abbreviate": lambda: (s[:int(args[0]) - 3] + "...") if args and len(s) > int(args[0]) else s,
            "capitalize": lambda: s[0].upper() + s[1:] if s else s,
            "escapesinglequotes": lambda: s.replace("'", "\\'"),
            "normalizespace": lambda: " ".join(s.split()),
            "countmatches": lambda: s.count(args[0]) if args else 0,
            "size": lambda: len(s),
            "tostring": lambda: s,
            # Les valeurs d'enum sont des chaînes : AES256.name() / .ordinal()
            "name": lambda: s,
            # --- Nouveaux : recherche & comparaison ---
            "containsignorecase": lambda: args[0].lower() in s.lower() if args and isinstance(args[0], str) else False,
            "startswithignorecase": lambda: s.lower().startswith(args[0].lower()) if args and isinstance(args[0], str) else False,
            "endswithignorecase": lambda: s.lower().endswith(args[0].lower()) if args and isinstance(args[0], str) else False,
            "indexofignorecase": lambda: s.lower().find(args[0].lower(), int(args[1])) if len(args) >= 2 else (s.lower().find(args[0].lower()) if args else -1),
            "lastindexof": lambda: s.rfind(args[0], 0, int(args[1]) + 1) if len(args) >= 2 else (s.rfind(args[0]) if args else -1),
            "lastindexofignorecase": lambda: s.lower().rfind(args[0].lower(), 0, int(args[1]) + 1) if len(args) >= 2 else (s.lower().rfind(args[0].lower()) if args else -1),
            "compareto": lambda: (0 if s == args[0] else (-1 if s < args[0] else 1)) if args else 0,
            # --- Nouveaux : manipulation ---
            "mid": lambda: s[int(args[0]):int(args[0]) + int(args[1])] if len(args) >= 2 else s,
            "reverse": lambda: s[::-1],
            "rightpad": lambda: s.ljust(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "center": lambda: s.center(int(args[0]), args[1] if len(args) > 1 else ' ') if args else s,
            "remove": lambda: s.replace(args[0], '') if args else s,
            "removestartignorecase": lambda: s[len(args[0]):] if args and s.lower().startswith(args[0].lower()) else s,
            "removeendignorecase": lambda: s[:-len(args[0])] if args and s.lower().endswith(args[0].lower()) else s,
            "replacefirst": lambda: _re.sub(args[0], args[1], s, count=1) if len(args) >= 2 else s,
            "uncapitalize": lambda: s[0].lower() + s[1:] if s else s,
            "swapcase": lambda: s.swapcase(),
            "deletewhitespace": lambda: ''.join(c for c in s if not c.isspace()),
            "striphtmltags": lambda: _re.sub(r'<[^>]+>', '', s),
            # --- Nouveaux : substring helpers ---
            "substringafter": lambda: s[s.find(args[0]) + len(args[0]):] if args and s.find(args[0]) != -1 else '',
            "substringafterlast": lambda: s[s.rfind(args[0]) + len(args[0]):] if args and s.rfind(args[0]) != -1 else '',
            "substringbefore": lambda: s[:s.find(args[0])] if args and s.find(args[0]) != -1 else s,
            "substringbeforelast": lambda: s[:s.rfind(args[0])] if args and s.rfind(args[0]) != -1 else s,
            "substringbetween": _substring_between,
            # --- Nouveaux : tests de contenu ---
            "isalllowercase": lambda: s.islower() if s else False,
            "isalluppercase": lambda: s.isupper() if s else False,
            "isalpha": lambda: s.isalpha() if s else False,
            "isalphanumeric": lambda: s.isalnum() if s else False,
            "isalphaspace": lambda: all(c.isalpha() or c == ' ' for c in s) if s else False,
            "isalphanumericspace": lambda: all(c.isalnum() or c == ' ' for c in s) if s else False,
            "isnumeric": lambda: s.isdigit() if s else False,
            "isnumericspace": lambda: all(c.isdigit() or c == ' ' for c in s) if s else False,
            "iswhitespace": lambda: s.isspace() if s else True,
            "containswhitespace": lambda: any(c.isspace() for c in s),
            "containsany": lambda: any(c in s for c in args[0]) if args else False,
            "containsnone": lambda: not any(c in s for c in args[0]) if args else True,
            "containsonly": lambda: all(c in args[0] for c in s) if args else False,
            "isasciiprintable": lambda: all(32 <= ord(c) <= 126 for c in s) if s else True,
            # --- Nouveaux : char & code ---
            "getchars": lambda: [ord(c) for c in s],
            "hashcode": lambda: hash(s),
            "indexofchar": lambda: s.find(chr(int(args[0])), int(args[1])) if len(args) >= 2 else (s.find(chr(int(args[0]))) if args else -1),
            # --- Nouveaux : distance ---
            "difference": lambda: args[0][len(_common_prefix(s, args[0])):] if args else '',
            "indexofdifference": lambda: _common_prefix_len(s, args[0]) if args else -1,
            # --- Escape / unescape ---
            "escapehtml4": lambda: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'),
            "escapehtml3": lambda: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'),
            "escapexml": lambda: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;'),
            "escapejava": lambda: s.encode('unicode_escape').decode('ascii'),
            "escapeecmascript": lambda: s.encode('unicode_escape').decode('ascii').replace("'", "\\'"),
            "unescapehtml4": lambda: _unescape_html(s),
            "unescapehtml3": lambda: _unescape_html(s),
            "unescapexml": lambda: s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'"),
            "unescapejava": lambda: s.encode().decode('unicode_escape'),
        }
        if meth in methods:
            return methods[meth]()
        # Méthodes d'Id (les Id sont des chaînes) : getSObjectType via le préfixe
        if meth == "getsobjecttype":
            from ..dml import SOBJECT_PREFIX
            prefix = s[:3]
            name = next((k for k, v in SOBJECT_PREFIX.items() if v == prefix), None)
            return ApexToken({"_type": "SObjectType", "name": name or "Name"})
        raise Exception("String.{}() non supporté".format(method))

    def _sort_list(self, lst, args):
        """List.sort() / List.sort(Comparator) — null d'abord, comme Apex."""
        import functools

        comparator = args[0] if args else None
        if isinstance(comparator, dict) and "_class" in comparator:
            compare = self._resolve_method_in_chain(comparator["_class"], "compare")
            if compare is None:
                raise ApexException("Sort order cannot be null")

            def cmp(a, b):
                r = self._invoke_instance_method(comparator, compare, [a, b])
                return int(r) if r is not None else 0
            lst.sort(key=functools.cmp_to_key(cmp))
            return None

        def cmp_default(a, b):
            if a is None and b is None:
                return 0
            if a is None:
                return -1
            if b is None:
                return 1
            try:
                return -1 if a < b else (1 if a > b else 0)
            except TypeError:
                sa, sb = str(a), str(b)
                return -1 if sa < sb else (1 if sa > sb else 0)
        lst.sort(key=functools.cmp_to_key(cmp_default))
        return None

    def _call_list_method(self, lst, method, args):
        meth = method.lower()
        methods = {
            "add": lambda: lst.append(args[0]) if args else None,
            "addall": lambda: lst.extend(args[0]) if args else None,
            "size": lambda: len(lst),
            "isempty": lambda: len(lst) == 0,
            "get": lambda: lst[int(args[0])] if args else None,
            "contains": lambda: args[0] in lst if args else False,
            "remove": lambda: lst.pop(int(args[0])),
            "clear": lambda: lst.clear(),
            "sort": lambda: self._sort_list(lst, args),
            "getsobjecttype": lambda: ApexToken({
                "_type": "SObjectType",
                "name": (self._guess_sobject_type(lst[0]) if lst and isinstance(lst[0], dict) else None) or "SObject"}),
        }
        if meth in methods:
            return methods[meth]()
        raise Exception("List.{}() non supporté".format(method))

    def _call_set_method(self, s, method, args):
        meth = method.lower()
        methods = {
            "add": lambda: s.add(args[0]) if args else None,
            "contains": lambda: args[0] in s if args else False,
            "size": lambda: len(s),
            "isempty": lambda: len(s) == 0,
            "remove": lambda: s.discard(args[0]) if args else None,
            "addall": lambda: s.update(args[0]) if args and hasattr(args[0], '__iter__') else None,
        }
        if meth in methods:
            return methods[meth]()
        raise Exception("Set.{}() non supporté".format(method))

    def _call_map_method(self, m, method, args):
        meth = method.lower()
        # Pattern object
        if m.get("_type") == "Pattern":
            if meth == "matcher":
                import re as _re
                text = args[0] if args else ""
                return {
                    "_type": "Matcher",
                    "_compiled": m["_compiled"],
                    "_text": str(text) if text is not None else "",
                    "_match": None,
                }
            if meth == "pattern":
                return m.get("_pattern", "")

        # Matcher object
        if m.get("_type") == "Matcher":
            import re as _re
            if meth == "find":
                # Support itératif : reprendre après le dernier match
                start = m.get("_pos", 0)
                match = m["_compiled"].search(m["_text"], start)
                m["_match"] = match
                if match:
                    m["_pos"] = match.end()
                return match is not None
            if meth == "group":
                match = m.get("_match")
                if match is None:
                    return None
                idx = int(args[0]) if args else 0
                try:
                    return match.group(idx)
                except (IndexError, _re.error):
                    return None
            if meth == "matches":
                match = m["_compiled"].fullmatch(m["_text"])
                m["_match"] = match
                return match is not None
            if meth == "replaceall":
                return m["_compiled"].sub(args[0], m["_text"]) if args else m["_text"]
            if meth == "replacefirst":
                return m["_compiled"].sub(args[0], m["_text"], count=1) if args else m["_text"]
            if meth == "reset":
                m["_pos"] = 0
                m["_match"] = None
                if args:
                    m["_text"] = str(args[0])
                return m
            if meth == "start":
                match = m.get("_match")
                return match.start(int(args[0]) if args else 0) if match else -1
            if meth == "end":
                match = m.get("_match")
                return match.end(int(args[0]) if args else 0) if match else -1
            if meth == "groupcount":
                match = m.get("_match")
                return len(match.groups()) if match else 0
            if meth == "hitend":
                return m.get("_pos", 0) >= len(m["_text"])
            if meth == "lookingat":
                match = m["_compiled"].match(m["_text"])
                m["_match"] = match
                return match is not None
            if meth == "pattern":
                return m.get("_pattern", "")

        # Blob object
        if m.get("_type") == "Blob":
            data = m.get("_data", b"")
            if meth == "tostring":
                return data.decode('utf-8') if isinstance(data, bytes) else str(data)
            if meth == "size":
                return len(data) if isinstance(data, bytes) else len(str(data).encode('utf-8'))

        # Schema.sObjectType.X → DescribeSObjectResult (token Apex) ; permet
        # Schema.sObjectType.Lead.isAccessible() et .fields
        if m.get("_type") == "SchemaSObjectTypeMap":
            acc = self._describe_access(method)
            return {
                "_type": "DescribeSObjectResult",
                "name": method,
                "label": method,
                "labelPlural": method + "s",
                "keyPrefix": method[:3].lower(),
                "isCustom": method.endswith("__c"),
                "isAccessible": acc,
                "isCreateable": self._describe_access(method, op="create"),
                "isUpdateable": self._describe_access(method, op="edit"),
                "isDeletable": self._describe_access(method, op="delete"),
                "isQueryable": acc,
                "isSearchable": acc,
                "fields": {"_type": "FieldMap", "_sobject": method},
            }

        # SObjectType object (Schema describe)
        if m.get("_type") == "SObjectType":
            sobj_name = m.get("name", "")
            if meth == "getdescribe":
                acc = self._describe_access(sobj_name)
                return ApexToken({
                    "_type": "DescribeSObjectResult",
                    "name": sobj_name,
                    "label": sobj_name,
                    "labelPlural": sobj_name + "s",
                    "keyPrefix": sobj_name[:3].lower(),
                    "isCustom": sobj_name.endswith("__c"),
                    "isAccessible": acc,
                    "isCreateable": self._describe_access(sobj_name, op="create"),
                    "isUpdateable": self._describe_access(sobj_name, op="edit"),
                    "isDeletable": self._describe_access(sobj_name, op="delete"),
                    "isQueryable": acc,
                    "isSearchable": acc,
                    "isUndeletable": acc,
                    "fields": {"_type": "FieldMap", "_sobject": sobj_name},
                })
            if meth == "newsobject":
                return {"_sobject_type": sobj_name}

        # FieldMap (describe.fields) — champs depuis le schéma de l'org si connu
        if m.get("_type") == "FieldMap":
            sobj = m.get("_sobject") or ""

            def _field_token(fname):
                return ApexToken({"_type": "SObjectField", "name": fname,
                                  "_sobject": sobj})
            if meth == "getmap":
                cols = getattr(self.org, "_tables", {}).get(sobj.lower()) or []
                return {c: _field_token(c) for c in cols}
            if meth == "get":
                return _field_token(args[0]) if args else None

        # SObjectField (token de champ)
        if m.get("_type") == "SObjectField":
            if meth == "getdescribe":
                fname = m.get("name", "")
                fsobj = m.get("_sobject") or ""
                return ApexToken({
                    "_type": "DescribeFieldResult",
                    "name": fname,
                    "label": fname,
                    "isAccessible": self._describe_access(fsobj, fname, "read"),
                    "isCreateable": self._describe_access(fsobj, fname, "edit"),
                    "isUpdateable": self._describe_access(fsobj, fname, "edit"),
                    "isFilterable": True,
                    "isNillable": True,
                })

        # DescribeFieldResult — getters génériques
        if m.get("_type") == "DescribeFieldResult":
            if method in m:
                return m[method]
            if meth.startswith("get"):
                key = method[3:]
                key = key[0].lower() + key[1:] if key else ""
                return m.get(key, m.get(key.lower()))
            if meth.startswith("is"):
                # Les flags d'accès explicites sont dans le token ; le reste
                # (isAutoNumber, isCalculated, isUnique…) est False par défaut
                return m.get(method, False)

        # DescribeSObjectResult
        if m.get("_type") == "DescribeSObjectResult":
            if meth == "fields":
                return {"_type": "FieldMap", "_sobject": m.get("name") or ""}
            if meth == "getrecordtypeinfosbydevelopername":
                return {}
            if meth == "getrecordtypeinfosbyname":
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
            if meth == "getid":
                return m.get("id", "GMT")
            if meth == "tostring":
                return m.get("id", "GMT")

        # FormulaBuilder instance methods (fluent)
        if m.get("_type") == "FormulaBuilder":
            return self._call_formula_builder(m, method, args)

        # FormulaInstance methods
        if m.get("_type") == "FormulaInstance":
            return self._call_formula_instance(m, method, args)

        # FormulaRecalcResult
        if m.get("_type") == "FormulaRecalcResult":
            if meth == "issuccess":
                return m.get("_success", True)
            if meth == "getsobject":
                return m.get("_record", {})
            if meth == "geterrors":
                return m.get("_errors", [])

        # SystemLabel — System.Label.XXX returns ''
        if m.get("_type") == "SystemLabel":
            return ""  # All custom labels return empty string

        # SaveResult
        if m.get("_type") == "SaveResult":
            if meth == "issuccess":
                return m.get("success", True)
            if meth == "getid":
                return m.get("id")
            if meth == "geterrors":
                return m.get("errors", [])

        # ApexType — Type.forName().newInstance()
        if m.get("_type") == "ApexType":
            if meth == "newinstance":
                class_name = m.get("className")
                if class_name:
                    class_def = self._resolve_class(class_name)
                    if class_def:
                        return self._create_instance(class_def, [])
                return None

        # FinalizerContext
        if m.get("_type") == "FinalizerContext":
            if meth == "getasyncapexjobid":
                return m.get("asyncApexJobId")
            if meth == "getresult":
                return m.get("result")

        # QueueableContext
        if m.get("_type") == "QueueableContext":
            if meth == "getjobid":
                return m.get("jobId")

        # Résultats DML (Database.insert/update/upsert/delete/undelete)
        if m.get("_type") in ("SaveResult", "UpsertResult", "DeleteResult", "UndeleteResult"):
            if meth == "issuccess":
                return bool(m.get("success"))
            if meth == "getid":
                return m.get("id")
            if meth == "geterrors":
                return m.get("errors") or []
            if meth == "iscreated":
                return bool(m.get("created"))

        # Database.Error (élément de getErrors())
        if m.get("_type") == "Database.Error":
            if meth == "getmessage":
                return m.get("message")
            if meth == "getstatuscode":
                return m.get("statusCode")
            if meth == "getfields":
                return m.get("fields") or []

        # SObjectAccessDecision (Security.stripInaccessible)
        if m.get("_type") == "SObjectAccessDecision":
            if meth == "getrecords":
                return m.get("_records") or []
            if meth == "getremovedfields":
                return m.get("_removed") or {}

        # BatchableContext (Database.executeBatch)
        if m.get("_type") == "BatchableContext":
            if meth in ("getjobid", "getchildjobid"):
                return m.get("_job_id")

        # QueryLocator (Database.getQueryLocator)
        if m.get("_type") == "QueryLocator":
            if meth == "getquery":
                return m.get("_soql", "")
            if meth == "iterator":
                return list(m.get("_rows") or [])

        # Http — callout réel, mock, ou défaut
        if m.get("_type") == "Http":
            if meth == "send":
                req = args[0] if args else {}
                if self.named_credentials and isinstance(req, dict):
                    from ..callout import execute_callout
                    return execute_callout(req, self.named_credentials)
                return self._http_send(req)

        # HttpRequest
        if m.get("_type") == "HttpRequest":
            if meth == "setheader":
                if "_headers" not in m:
                    m["_headers"] = {}
                if len(args) >= 2:
                    m["_headers"][args[0]] = args[1]
                return None
            if meth == "getheader":
                return m.get("_headers", {}).get(args[0], "") if args else ""
            if meth in ("setendpoint", "setmethod", "setbody", "settimeout"):
                m["_" + method[3:].lower()] = args[0] if args else None
                return None
            if meth == "getendpoint":
                return m.get("_endpoint", "")
            if meth == "getmethod":
                return m.get("_method", "GET")
            if meth == "getbody":
                return m.get("_body", "")
            return None

        # HttpResponse mock
        if m.get("_type") == "HttpResponse":
            if meth == "getstatuscode":
                return m.get("_statusCode", 200)
            if meth == "getstatus":
                code = m.get("_statusCode", 200)
                statuses = {200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request",
                            401: "Unauthorized", 404: "Not Found", 500: "Internal Server Error"}
                return statuses.get(code, "Unknown")
            if meth == "getbody":
                return m.get("_body", "")
            if meth == "getheader":
                return m.get("_headers", {}).get(args[0], "") if args else ""
            if meth in ("setstatuscode", "setbody", "setheader"):
                if meth == "setstatuscode":
                    m["_statusCode"] = args[0] if args else 200
                elif meth == "setbody":
                    m["_body"] = args[0] if args else ""
                elif meth == "setheader" and len(args) >= 2:
                    if "_headers" not in m:
                        m["_headers"] = {}
                    m["_headers"][args[0]] = args[1]
                return None
            return None

        # URL object
        if m.get("_type") == "URL":
            if meth == "toexternalform":
                return m.get("_url", "")
            if meth == "gethost":
                return m.get("_url", "").split("//")[-1].split("/")[0]
            return m.get("_url", "")

        # DateTime object
        if m.get("_type") == "DateTime":
            if meth == "date":
                return {"_type": "Date", "year": m.get("year"), "month": m.get("month"), "day": m.get("day")}
            if meth == "year":
                return m.get("year")
            if meth == "month":
                return m.get("month")
            if meth == "day":
                return m.get("day")
            if meth == "format":
                return "{}-{:02d}-{:02d}".format(m.get("year", 0), m.get("month", 0), m.get("day", 0))
            if meth == "gettime":
                import datetime
                dt = datetime.datetime(m.get("year", 2000), m.get("month", 1), m.get("day", 1),
                                       m.get("hour", 0), m.get("minute", 0), m.get("second", 0))
                return int(dt.timestamp() * 1000)
            if meth == "adddays":
                import datetime
                d = datetime.date(m["year"], m["month"], m["day"])
                d2 = d + datetime.timedelta(days=int(args[0]) if args else 0)
                return {"_type": "DateTime", "year": d2.year, "month": d2.month, "day": d2.day}

        # Date object
        if m.get("_type") == "Date":
            if meth == "year":
                return m.get("year")
            if meth == "month":
                return m.get("month")
            if meth == "day":
                return m.get("day")
            if meth == "adddays":
                import datetime
                d = datetime.date(m["year"], m["month"], m["day"])
                d2 = d + datetime.timedelta(days=int(args[0]) if args else 0)
                return {"_type": "Date", "year": d2.year, "month": d2.month, "day": d2.day}
            if meth == "addmonths":
                month = m["month"] + (int(args[0]) if args else 0)
                year = m["year"] + (month - 1) // 12
                month = (month - 1) % 12 + 1
                return {"_type": "Date", "year": year, "month": month, "day": m["day"]}
            if meth == "date":
                return m  # Already a Date
            if meth == "format":
                return "{}-{:02d}-{:02d}".format(m["year"], m["month"], m["day"])

        if "_sobject_type" in m:
            val = m.get(method)
            if val is not None:
                return val
        # Exception-like dicts: getMessage(), getTypeName(), etc.
        if meth == "getmessage":
            return m.get("getMessage", m.get("message", str(m)))
        if meth == "gettypename":
            return m.get("_type", "Exception")
        if meth == "getstacktracestring":
            return ""

        methods = {
            "put": lambda: m.__setitem__(args[0], args[1]) if len(args) >= 2 else None,
            "get": lambda: m.get(args[0]) if args else None,
            "containskey": lambda: args[0] in m if args else False,
            "keyset": lambda: set(m.keys()),
            "values": lambda: list(m.values()),
            "size": lambda: len(m),
            "isempty": lambda: len(m) == 0,
            "remove": lambda: m.pop(args[0], None) if args else None,
            "clone": lambda: dict(m),
        }
        if meth in methods:
            return methods[meth]()
        # Fallback: try field access (covers SObject-like dicts without _sobject_type)
        if method in m:
            return m[method]
        raise Exception("Map.{}() non supporté".format(method))

    # ------------------------------------------------------------------
    # FormulaEval namespace support
    # ------------------------------------------------------------------

    def _call_formula_builder(self, builder, method, args):
        meth = method.lower()
        """Méthodes fluentes du FormulaBuilder — retourne toujours le builder."""
        if meth == "withtype":
            builder["_context_type"] = args[0] if args else None
            return builder
        if meth == "withreturntype":
            builder["_return_type"] = args[0] if args else None
            return builder
        if meth == "withformula":
            builder["_formula"] = args[0] if args else None
            return builder
        if meth == "withglobalvariables":
            builder["_globals"] = args[0] if args else []
            return builder
        if meth == "parseastemplate":
            builder["_template"] = bool(args[0]) if args else False
            return builder
        if meth == "build":
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
        meth = method.lower()
        """Méthodes de FormulaInstance — evaluate() et getReferencedFields()."""
        if meth == "getreferencedfields":
            return instance.get("_referenced_fields", set())
        if meth == "evaluate":
            context_obj = args[0] if args else {}
            formula_expr = instance["_formula"]
            is_template = instance.get("_template", False)

            from ..formula_engine import FormulaEngine, resolve_merge_fields

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
