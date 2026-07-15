"""Interpréteur Apex — ExpressionsMixin."""

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


class ExpressionsMixin:
    def _eval_arg(self, expr: Expr):
        """Évalue un argument d'appel : un littéral SOQL inline est exécuté
        (méthode([SELECT ...]) reçoit les lignes, pas la chaîne)."""
        if isinstance(expr, StringLiteral) and _is_soql_literal(expr.value):
            return self.org.execute_soql(expr.value, context=self._soql_context())
        return self._eval(expr)

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
            if val is None and expr.name not in self.variables:
                # Fallback insensible à la casse (Apex l'est)
                key = _ci_key(self.variables, expr.name)
                if key is not None:
                    return self.variables[key]
                # Fallback: champ d'instance implicite (sans this.)
                if self._current_instance is not None:
                    ikey = _ci_key(self._current_instance, expr.name)
                    if ikey is not None and ikey not in ("_type", "_class", "_chain"):
                        return self._current_instance[ikey]
                # Fallback: statique d'une classe visible (X.varName)
                nl = expr.name.lower()
                for k in self.variables:
                    if "." in k and k.split(".", 1)[1].lower() == nl:
                        return self.variables[k]
            return val

        elif isinstance(expr, FieldAccess):
            # this.field
            if expr.obj == "this" and self._current_instance is not None:
                return self._current_instance.get(expr.field)

            # System.Label → return empty string for custom labels
            if expr.obj == "System" and expr.field == "Label":
                return {"_type": "SystemLabel"}

            # Schema.sObjectType → map des describes (Schema.sObjectType.X.isAccessible())
            if expr.obj.lower() == "schema" and expr.field.lower() == "sobjecttype":
                return {"_type": "SchemaSObjectTypeMap"}

            # SObjectType.Account → token SObjectType (getDescribe(), newSObject())
            if expr.obj == "SObjectType" and expr.obj not in self.variables:
                return ApexToken({"_type": "SObjectType", "name": expr.field})

            # Account.sObjectType → même token (l'objet n'est pas une variable)
            if (expr.field.lower() == "sobjecttype"
                    and expr.obj not in self.variables
                    and expr.obj[:1].isupper()):
                return ApexToken({"_type": "SObjectType", "name": expr.obj})
            # ParentJobResult.SUCCESS / FAILURE
            if expr.obj == "ParentJobResult":
                return expr.field

            # AccessType.READABLE / CREATABLE / UPDATABLE / UPSERTABLE (enum)
            if expr.obj == "AccessType" and expr.obj not in self.variables:
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
            if obj is None and expr.obj not in self.variables:
                # Fallbacks insensibles à la casse, hors chemin chaud
                vkey = _ci_key(self.variables, expr.obj)
                if vkey is not None:
                    obj = self.variables[vkey]
                else:
                    ck = _ci_key(self.variables, class_key)
                    if ck is not None:
                        return self.variables[ck]
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
            # Constante d'une classe/enum chargée mais non préchargée en
            # variables (enums inner : TriggerContext.BEFORE_INSERT, …)
            cls = self._resolve_class(expr.obj)
            if cls is not None:
                const = cls.constants.get(expr.field)
                if const is None:
                    k = _ci_key(cls.constants, expr.field)
                    const = cls.constants[k] if k is not None else None
                if const is not None and const[1] is not None:
                    try:
                        return self._eval(const[1])
                    except Exception:
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
            args = [self._eval_arg(a) for a in expr.args]

            # System.X.method() — résoudre comme X.method() pour tout namespace
            # builtin qualifié par System (System.Assert, System.JSON, System.Test…)
            if target is None and isinstance(expr.target, FieldAccess):
                fa = expr.target
                if isinstance(fa.obj, str) and fa.obj.lower() == "system":
                    ns = self._BUILTIN_NAMESPACES.get(fa.field.lower())
                    if ns is not None:
                        call = MethodCall(obj=ns, method=expr.method, args=expr.args)
                        return self._exec_method_call(call)

            # Stub (Test.createStub) : dérouter vers le StubProvider
            if isinstance(target, dict) and "_stub_provider" in target:
                return self._invoke_stub(target, expr.method, args)

            # Instance method call
            if isinstance(target, dict) and "_class" in target:
                cls = target["_class"]
                resolved = self._resolve_method_in_chain(cls, expr.method, args)
                if resolved is not None:
                    if resolved.is_static:
                        return self._invoke_method(cls, resolved, args)
                    return self._invoke_instance_method(target, resolved, args)
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
                i = int(idx)
                if i < 0 or i >= len(arr):
                    raise ApexException(
                        "List index out of bounds: {}".format(i))
                return arr[i]
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
            "String", "Integer", "Pattern", "Formula", "FormulaEval",
            "Assert", "Decimal", "Double", "Id", "SObjectType",
            "Matcher", "HttpRequest", "HttpResponse", "Security",
        )
    }
