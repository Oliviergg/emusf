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
    _json_clean, _apex_str, _field_of, _is_soql_literal, _blob_bytes,
)


class ValuesMixin:
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
            from ..dml import SOBJECT_PREFIX
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
                    from ..callout import execute_callout
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
