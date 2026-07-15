"""Frontend ANTLR : parse Apex via la grammaire apex-dev-tools/apex-parser
et produit les nœuds ast_nodes d'EMUSF.

Le parse tree ANTLR est mappé vers les dataclasses ast_nodes, avec ces
conventions : obj='_self' pour les appels locaux, SOQL en texte brut,
type_name normalisé pour les collections.

Le parser généré est vendoré dans emusf/antlr/generated/ (pas de dépendance
Java à l'exécution) ; la grammaire source et sa licence BSD-3-Clause sont dans
emusf/antlr/grammar/. Régénération : voir emusf/antlr/README.md.

Limitations connues (constructions ignorées faute de support côté interpréteur) :
- déclaration sans initialisation (`Integer i;`) ignorée
- statements non supportés par l'interpréteur ignorés (upsert, merge, runAs…)
- seul le premier catch d'un try est conservé, finally ignoré
- méthodes abstraites/interfaces et enums ignorés
- propriétés {get; set;} uniquement en forme automatique
- `without sharing` et `inherited sharing` → sharing=None
"""

from __future__ import annotations

import os
import re
import sys

from ..ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject, NewInstance,
    MethodCall, ChainedCall, Ternary, NewList, NewMap, NewSet, NewMapInit,
    ArrayAccess, NewArray, CastExpr,
    Stmt, VarDecl, Assign, FieldSet, SOQLAssign,
    DmlInsert, DmlUpdate, DmlDelete,
    SystemDebug, ForEach, IfElse, Return, MethodCallStmt, TryCatch, Block,
    ForCStyle, WhileLoop, DoWhile, ThrowStmt, BreakStmt, ContinueStmt,
    Increment, Decrement, SwitchWhen, RunAs,
    MethodDef, ClassDef,
)


class ApexSyntaxError(Exception):
    """Erreur de syntaxe signalée par le parser ANTLR."""


class _Unsupported(Exception):
    """Construction sans équivalent dans les ast_nodes actuels."""


_runtime = None  # (ApexLexer, ApexParser, InputStream, CommonTokenStream, ErrorListener)


def _gen_dir() -> str:
    env = os.environ.get("EMUSF_ANTLR_GEN")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")


def _load():
    """Charge paresseusement le runtime antlr4 et le parser généré."""
    global _runtime
    if _runtime is None:
        gen = _gen_dir()
        if not os.path.isfile(os.path.join(gen, "ApexParser.py")):
            raise RuntimeError(
                "Parser ANTLR introuvable dans {} — voir emusf/antlr/README.md".format(gen)
            )
        if gen not in sys.path:
            sys.path.insert(0, gen)
        from antlr4 import CommonTokenStream, InputStream
        from antlr4.error.ErrorListener import ErrorListener
        from ApexLexer import ApexLexer
        from ApexParser import ApexParser
        _runtime = (ApexLexer, ApexParser, InputStream, CommonTokenStream, ErrorListener)
    return _runtime


def is_available() -> bool:
    try:
        _load()
        return True
    except Exception:
        return False


def _parse(source: str, entry: str):
    """Parse le source et retourne (tree, ApexParser). Lève ApexSyntaxError."""
    ApexLexer, ApexParser, InputStream, CommonTokenStream, ErrorListener = _load()

    class _Collect(ErrorListener):
        def __init__(self):
            self.errors = []

        def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
            self.errors.append("L{}:{} {}".format(line, column, msg))

    errs = _Collect()
    lexer = ApexLexer(InputStream(source))
    lexer.removeErrorListeners()
    lexer.addErrorListener(errs)
    parser = ApexParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(errs)
    tree = getattr(parser, entry)()
    if errs.errors:
        raise ApexSyntaxError("; ".join(errs.errors[:5]))
    return tree, ApexParser


def _src(ctx) -> str:
    """Texte source original couvert par un contexte (espaces préservés)."""
    return ctx.start.getInputStream().getText(ctx.start.start, ctx.stop.stop)


_ESCAPES = {"\\'": "'", "\\\\": "\\", "\\n": "\n", "\\t": "\t"}


def _unquote(text: str) -> str:
    """'abc\\'d' → abc'd — mêmes séquences que le lexer maison."""
    inner = text[1:-1]
    return re.sub(r"\\['\\nt]", lambda m: _ESCAPES[m.group(0)], inner)


class _Builder:
    """Mappe le parse tree ANTLR vers les ast_nodes d'EMUSF."""

    def __init__(self, parser_cls):
        self.AP = parser_cls
        self.warnings = []  # constructions ignorées (parité parser maison)
        self._dml_counter = 0  # variables temporaires pour DML inline

    # ------------------------------------------------------------------ #
    # Classes
    # ------------------------------------------------------------------ #

    def build_compilation_unit(self, tree) -> ClassDef:
        td = tree.typeDeclaration()
        cd = td.classDeclaration()
        if cd is None:
            ed = td.enumDeclaration()
            if ed is not None:
                return self.build_enum(ed)
            raise _Unsupported("interface top-level")
        mods = [m.getText().lower() for m in td.modifier()]
        return self.build_class(cd, mods, top_level=True)

    def build_enum(self, ctx) -> ClassDef:
        """Enum Apex → ClassDef à constantes-chaînes : Season.WINTER == 'WINTER'
        (cohérent avec Trigger.operationType et le match par nom des switch)."""
        name = ctx.id_().getText()
        constants = {}
        ec = ctx.enumConstants()
        if ec is not None:
            for cid in ec.id_():
                vname = cid.getText()
                constants[vname] = ("String", StringLiteral(vname))
        return ClassDef(name=name, constants=constants, methods={})

    def build_class(self, ctx, mods, top_level: bool) -> ClassDef:
        name = ctx.id_().getText()
        parent = _src(ctx.typeRef()) if ctx.EXTENDS() else None
        sharing = "with sharing" if "withsharing" in mods and top_level else None

        constants, methods, instance_fields = {}, {}, {}
        constructors, inner_classes, properties, overloads = [], {}, {}, {}
        static_init = []

        for cbd in ctx.classBody().classBodyDeclaration():
            if cbd.block() is not None:
                # Bloc d'initialisation static { ... } (instance ignoré, parité)
                if cbd.STATIC() is not None and top_level:
                    static_init.extend(self._block_stmts(cbd.block()))
                continue
            member = cbd.memberDeclaration()
            if member is None:
                continue
            member_mods = [m.getText().lower() for m in cbd.modifier()]

            if member.methodDeclaration() is not None:
                self._add_method(member.methodDeclaration(), member_mods,
                                 methods, overloads if top_level else None)
            elif member.constructorDeclaration() is not None:
                cons = member.constructorDeclaration()
                constructors.append(MethodDef(
                    name=cons.qualifiedName().getText(),
                    return_type="void",
                    params=self._params(cons.formalParameters()),
                    body=self._block_stmts(cons.block()),
                    is_static=False,
                ))
            elif member.fieldDeclaration() is not None:
                self._add_field(member.fieldDeclaration(), member_mods,
                                cbd.modifier(), constants, instance_fields)
            elif member.propertyDeclaration() is not None and top_level:
                self._add_property(member.propertyDeclaration(), properties)
            elif member.classDeclaration() is not None:
                inner = self.build_class(member.classDeclaration(),
                                         member_mods, top_level=False)
                inner_classes[inner.name] = inner
            elif member.enumDeclaration() is not None:
                enum_def = self.build_enum(member.enumDeclaration())
                inner_classes[enum_def.name] = enum_def
            else:
                self.warnings.append("membre ignoré : {}".format(
                    _src(member)[:60]))

        # Tagger chaque méthode avec sa classe propriétaire (pour localiser les
        # erreurs dans le bon fichier lors des appels de méthodes héritées)
        for md in list(methods.values()) + constructors:
            md.owner_class = name
        for ov_list in overloads.values():
            for md in ov_list:
                md.owner_class = name

        return ClassDef(
            name=name,
            constants=constants,
            methods=methods,
            properties=properties,
            sharing=sharing,
            instance_fields=instance_fields,
            constructors=constructors,
            inner_classes=inner_classes,
            parent_class=parent,
            overloads=overloads,
            static_init=static_init,
        )

    def _add_method(self, ctx, mods, methods, overloads):
        if ctx.block() is None:
            self.warnings.append("méthode abstraite ignorée : {}".format(
                ctx.id_().getText()))
            return
        name = ctx.id_().getText()
        method = MethodDef(
            name=name,
            return_type=_src(ctx.typeRef()) if ctx.typeRef() else "void",
            params=self._params(ctx.formalParameters()),
            body=self._block_stmts(ctx.block()),
            is_static="static" in mods,
        )
        if name in methods and overloads is not None:
            if name not in overloads:
                overloads[name] = [methods[name]]
            overloads[name].append(method)
        methods[name] = method

    def _params(self, ctx) -> list:
        result = []
        if ctx.formalParameterList() is not None:
            for p in ctx.formalParameterList().formalParameter():
                result.append((_src(p.typeRef()), p.id_().getText()))
        return result

    def _add_field(self, ctx, mods, modifier_ctxs, constants, instance_fields):
        type_name = self._field_type(modifier_ctxs, ctx.typeRef())
        is_static = "static" in mods
        for decl in ctx.variableDeclarators().variableDeclarator():
            var_name = decl.id_().getText()
            expr_ctx = decl.expression()
            if expr_ctx is not None:
                value = self.expr(expr_ctx)
                if is_static:
                    constants[var_name] = (type_name, value)
                else:
                    instance_fields[var_name] = type_name
                    constants[var_name] = (type_name, value)
            else:
                if is_static:
                    constants[var_name] = (type_name, None)
                else:
                    instance_fields[var_name] = type_name

    @staticmethod
    def _field_type(modifier_ctxs, type_ctx) -> str:
        """Parité maison : les modificateurs d'accès sont absorbés dans le type
        du champ ('public String'), et static/final en sont retirés en laissant
        leurs espaces ('public   String')."""
        mods = [m for m in modifier_ctxs if m.annotation() is None]
        if mods:
            raw = type_ctx.start.getInputStream().getText(
                mods[0].start.start, type_ctx.stop.stop)
        else:
            raw = _src(type_ctx)
        return re.sub(r"\b(static|final)\b", "", raw).strip()

    def _add_property(self, ctx, properties):
        """Propriété automatique {get; set;} uniquement (parité maison)."""
        blocks = ctx.propertyBlock()
        has_auto_get = has_auto_set = False
        for pb in blocks:
            if pb.getter() is not None:
                if pb.getter().SEMI() is None:
                    return  # corps de getter → maison l'ignore
                has_auto_get = True
            if pb.setter() is not None:
                if pb.setter().SEMI() is None:
                    return
                has_auto_set = True
        if has_auto_get and has_auto_set:
            properties[ctx.id_().getText()] = _src(ctx.typeRef())

    # ------------------------------------------------------------------ #
    # Statements
    # ------------------------------------------------------------------ #

    def _block_stmts(self, block_ctx) -> list:
        stmts = []
        for st in block_ctx.statement():
            stmts.extend(self.stmt(st))
        return stmts

    def stmt(self, ctx) -> list:
        """Mappe un statement ; retourne une liste (0, 1 ou n nœuds).

        Estampille chaque nœud avec sa ligne source (attribut dynamique .line)
        pour permettre à l'interpréteur de situer les erreurs dans le .cls."""
        try:
            nodes = self._stmt(ctx)
        except _Unsupported as exc:
            self.warnings.append("statement ignoré ({}) : {}".format(
                exc, _src(ctx)[:60]))
            return []
        line = ctx.start.line
        for node in nodes:
            if getattr(node, "line", None) is None:
                try:
                    node.line = line
                except (AttributeError, TypeError):
                    pass  # nœud à slots ou immuable — on ignore
        return nodes

    def _stmt(self, ctx) -> list:
        AP = self.AP
        if ctx.block() is not None:
            return self._block_stmts(ctx.block())
        if ctx.ifStatement() is not None:
            return [self._if(ctx.ifStatement())]
        if ctx.switchStatement() is not None:
            return [self._switch(ctx.switchStatement())]
        if ctx.forStatement() is not None:
            return self._for(ctx.forStatement())
        if ctx.whileStatement() is not None:
            w = ctx.whileStatement()
            body = self._stmt_or_empty(w.statement())
            return [WhileLoop(condition=self.expr(w.parExpression().expression()),
                              body=body)]
        if ctx.doWhileStatement() is not None:
            d = ctx.doWhileStatement()
            return [DoWhile(condition=self.expr(d.parExpression().expression()),
                            body=self._block_stmts(d.block()))]
        if ctx.tryStatement() is not None:
            return [self._try(ctx.tryStatement())]
        if ctx.returnStatement() is not None:
            r = ctx.returnStatement()
            value = self.expr(r.expression()) if r.expression() else None
            return [Return(value=value)]
        if ctx.throwStatement() is not None:
            return [ThrowStmt(expr=self.expr(ctx.throwStatement().expression()))]
        if ctx.breakStatement() is not None:
            return [BreakStmt()]
        if ctx.continueStatement() is not None:
            return [ContinueStmt()]
        if ctx.insertStatement() is not None:
            return self._dml(ctx.insertStatement().expression(), DmlInsert)
        if ctx.updateStatement() is not None:
            return self._dml(ctx.updateStatement().expression(), DmlUpdate)
        if ctx.deleteStatement() is not None:
            return self._dml(ctx.deleteStatement().expression(), DmlDelete)
        if ctx.localVariableDeclarationStatement() is not None:
            return self._local_decl(
                ctx.localVariableDeclarationStatement().localVariableDeclaration())
        if ctx.expressionStatement() is not None:
            return self._expr_stmt(ctx.expressionStatement().expression())
        if ctx.runAsStatement() is not None:
            ras = ctx.runAsStatement()
            exprs = (ras.expressionList().expression()
                     if ras.expressionList() is not None else [])
            user_expr = self.expr(exprs[0]) if exprs else NullLiteral()
            return [RunAs(user=user_expr, body=self._block_stmts(ras.block()))]
        # upsert, merge, undelete : non supportés par l'interpréteur
        raise _Unsupported(type(ctx.getChild(0)).__name__)

    def _stmt_or_empty(self, statement_ctx) -> list:
        return self.stmt(statement_ctx) if statement_ctx is not None else []

    def _dml(self, expr_ctx, node_cls) -> list:
        target = self.expr(expr_ctx)
        if isinstance(target, Variable):
            return [node_cls(var_name=target.name)]
        # DML sur une expression inline (insert new X(...), insert maListe())
        # → variable temporaire puis DML dessus
        self._dml_counter += 1
        tmp = "__dml_tmp_{}".format(self._dml_counter)
        return [
            VarDecl(type_name="SObject", var_name=tmp, value=target),
            node_cls(var_name=tmp),
        ]

    def _if(self, ctx) -> IfElse:
        condition = self.expr(ctx.parExpression().expression())
        statements = ctx.statement()
        then_body = self.stmt(statements[0])
        else_body = self.stmt(statements[1]) if len(statements) > 1 else []
        return IfElse(condition=condition, then_body=then_body, else_body=else_body)

    def _try(self, ctx) -> TryCatch:
        try_body = self._block_stmts(ctx.block())
        catch_type, catch_var, catch_body = "Exception", "e", []
        catches = ctx.catchClause()
        if catches:
            first = catches[0]
            catch_type = first.qualifiedName().getText()
            catch_var = first.id_().getText()
            catch_body = self._block_stmts(first.block())
            if len(catches) > 1:
                self.warnings.append("catch multiples : seul le premier est conservé")
        if ctx.finallyBlock() is not None:
            self.warnings.append("finally ignoré")
        return TryCatch(try_body=try_body, catch_type=catch_type,
                        catch_var=catch_var, catch_body=catch_body)

    def _switch(self, ctx) -> SwitchWhen:
        expr = self.expr(ctx.expression())
        cases = []
        for wc in ctx.whenControl():
            body = self._block_stmts(wc.block())
            wv = wc.whenValue()
            if wv.ELSE() is not None:
                cases.append((None, body))
            elif wv.typeRef() is not None:
                cases.append(([Variable(name=_src(wv.typeRef()))], body))
            else:
                values = [self._when_literal(wl) for wl in wv.whenLiteral()]
                cases.append((values, body))
        return SwitchWhen(expr=expr, cases=cases)

    def _when_literal(self, ctx) -> Expr:
        if ctx.whenLiteral() is not None:  # parenthèses
            return self._when_literal(ctx.whenLiteral())
        if ctx.IntegerLiteral() is not None or ctx.LongLiteral() is not None:
            tok = ctx.IntegerLiteral() or ctx.LongLiteral()
            value = int(tok.getText().rstrip("lL"))
            if len(ctx.SUB()) % 2 == 1:
                value = -value
            return IntegerLiteral(value=value)
        if ctx.StringLiteral() is not None:
            return StringLiteral(value=_unquote(ctx.StringLiteral().getText()))
        if ctx.NULL() is not None:
            return NullLiteral()
        if ctx.qualifiedName() is not None:
            parts = ctx.qualifiedName().getText().split(".")
            if len(parts) == 1:
                return Variable(name=parts[0])
            return FieldAccess(obj=parts[0], field=".".join(parts[1:]))
        raise _Unsupported("when literal")

    def _for(self, ctx) -> list:
        body = self._stmt_or_empty(ctx.statement())
        fc = ctx.forControl()
        if fc.enhancedForControl() is not None:
            efc = fc.enhancedForControl()
            return [ForEach(
                iter_type=_src(efc.typeRef()),
                iter_var=efc.id_().getText(),
                list_expr=self.expr(efc.expression()),
                body=body,
            )]
        init = self._flatten(self._for_init(fc.forInit())) if fc.forInit() else None
        condition = (self.expr(fc.expression()) if fc.expression()
                     else BooleanLiteral(value=True))
        update = None
        if fc.forUpdate() is not None:
            update_stmts = []
            for e in fc.forUpdate().expressionList().expression():
                update_stmts.extend(self._expr_stmt(e))
            update = self._flatten(update_stmts)
        return [ForCStyle(init=init, condition=condition, update=update, body=body)]

    def _for_init(self, ctx) -> list:
        if ctx.localVariableDeclaration() is not None:
            return self._local_decl(ctx.localVariableDeclaration())
        stmts = []
        for e in ctx.expressionList().expression():
            stmts.extend(self._expr_stmt(e))
        return stmts

    @staticmethod
    def _flatten(stmts: list):
        if not stmts:
            return None
        if len(stmts) == 1:
            return stmts[0]
        return Block(statements=stmts)

    def _local_decl(self, ctx) -> list:
        type_name = _src(ctx.typeRef())
        stmts = []
        for decl in ctx.variableDeclarators().variableDeclarator():
            var_name = decl.id_().getText()
            expr_ctx = decl.expression()
            if expr_ctx is None:
                # Parité maison : déclaration sans init ignorée
                self.warnings.append("déclaration sans init ignorée : {}".format(var_name))
                continue
            stmts.append(self._decl_with_value(type_name, var_name, expr_ctx))
        return stmts

    def _decl_with_value(self, type_name, var_name, expr_ctx) -> Stmt:
        soql = self._soql_text(expr_ctx)
        if soql is not None:
            m = re.fullmatch(r"List<(\w+)>", type_name)
            if m:
                return SOQLAssign(type_name=m.group(1), var_name=var_name,
                                  soql=soql, is_list=True)
            if re.fullmatch(r"\w+", type_name):
                return SOQLAssign(type_name=type_name, var_name=var_name,
                                  soql=soql, is_list=False)
            return VarDecl(type_name=type_name, var_name=var_name,
                           value=StringLiteral(value=soql))
        value = self.expr(expr_ctx)
        normalized = self._normalize_collection_decl(type_name, value)
        if normalized is not None:
            return VarDecl(type_name=normalized[0], var_name=var_name,
                           value=normalized[1])
        return VarDecl(type_name=type_name, var_name=var_name, value=value)

    def _normalize_collection_decl(self, type_name, value):
        """Reproduit la normalisation maison des types collection.

        `List<X> l = new List<X>()` → type_name 'List<X>' reconstruit, et le
        type d'élément déclaré prime sur celui du new (comportement maison).
        """
        m = re.fullmatch(r"List<(\w+)>", type_name)
        if m and isinstance(value, NewList):
            elem = m.group(1)
            return ("List<{}>".format(elem),
                    NewList(element_type=elem, init_values=value.init_values))
        m = re.fullmatch(r"Set<(\w+)>", type_name)
        if m and isinstance(value, NewSet):
            elem = m.group(1)
            return ("Set<{}>".format(elem),
                    NewSet(element_type=elem, init_values=value.init_values))
        m = re.fullmatch(r"Map<(\w+)\s*,\s*(\w+)>", type_name)
        if m and isinstance(value, NewMap):
            k, v = m.group(1), m.group(2)
            return ("Map<{},{}>".format(k, v), NewMap(key_type=k, value_type=v))
        return None

    def _soql_text(self, expr_ctx):
        """Texte brut '[SELECT ...]' si l'expression est un littéral SOQL."""
        AP = self.AP
        if isinstance(expr_ctx, AP.PrimaryExpressionContext):
            primary = expr_ctx.primary()
            if isinstance(primary, AP.SoqlPrimaryContext):
                return _src(primary)
        return None

    def _expr_stmt(self, ctx) -> list:
        """Mappe une expression en position statement."""
        AP = self.AP

        if isinstance(ctx, AP.AssignExpressionContext):
            return self._assign_stmt(ctx)

        if isinstance(ctx, AP.PostOpExpressionContext) or \
                isinstance(ctx, AP.PreOpExpressionContext):
            inner = ctx.expression()
            target = self.expr(inner)
            if isinstance(target, Variable):
                if ctx.INC() is not None:
                    return [Increment(var_name=target.name)]
                if ctx.DEC() is not None:
                    return [Decrement(var_name=target.name)]
            raise _Unsupported("++/-- sur expression")

        expr = self.expr(ctx)
        if isinstance(expr, MethodCall):
            if expr.obj == "System" and expr.method == "debug" and len(expr.args) == 1:
                return [SystemDebug(expr=expr.args[0])]
            return [MethodCallStmt(call=expr)]
        if isinstance(expr, ChainedCall):
            return [MethodCallStmt(call=expr)]
        raise _Unsupported("expression en statement")

    def _assign_stmt(self, ctx) -> list:
        op = ctx.getChild(1).getText()
        target_ctx, value_ctx = ctx.expression(0), ctx.expression(1)
        target = self.expr(target_ctx)

        if op == "=":
            value_soql = self._soql_text(value_ctx)
            if isinstance(target, Variable):
                if value_soql is not None:
                    return [SOQLAssign(type_name=None, var_name=target.name,
                                       soql=value_soql, is_list=False)]
                value = self.expr(value_ctx)
                # Parité maison : `l = new List<X>()` produit un VarDecl
                normalized = self._normalize_assign_collection(value)
                if normalized is not None:
                    return [VarDecl(type_name=normalized, var_name=target.name,
                                    value=value)]
                return [Assign(var_name=target.name, value=value)]
            if isinstance(target, FieldAccess):
                return [FieldSet(obj=target.obj, field=target.field,
                                 value=self.expr(value_ctx))]
            if isinstance(target, ArrayAccess) and isinstance(target.array, Variable):
                index_ctx = target_ctx.expression(1)
                return [FieldSet(obj=target.array.name, field=_src(index_ctx),
                                 value=self.expr(value_ctx))]
            raise _Unsupported("cible d'affectation")

        if op in ("+=", "-=", "*=", "/="):
            simple_op = op[0]
            right = self.expr(value_ctx)
            if isinstance(target, Variable):
                return [Assign(var_name=target.name,
                               value=BinaryOp(left=Variable(name=target.name),
                                              op=simple_op, right=right))]
            if isinstance(target, FieldAccess):
                return [FieldSet(obj=target.obj, field=target.field,
                                 value=BinaryOp(left=target, op=simple_op,
                                                right=right))]
        raise _Unsupported("affectation composée")

    @staticmethod
    def _normalize_assign_collection(value):
        if isinstance(value, NewList) and re.fullmatch(r"\w+", value.element_type):
            return "List<{}>".format(value.element_type)
        if isinstance(value, NewSet) and re.fullmatch(r"\w+", value.element_type):
            return "Set<{}>".format(value.element_type)
        if isinstance(value, NewMap) and re.fullmatch(r"\w+", value.key_type) \
                and re.fullmatch(r"\w+", value.value_type):
            return "Map<{},{}>".format(value.key_type, value.value_type)
        return None

    # ------------------------------------------------------------------ #
    # Expressions
    # ------------------------------------------------------------------ #

    def expr(self, ctx) -> Expr:
        AP = self.AP

        if isinstance(ctx, AP.PrimaryExpressionContext):
            return self._primary(ctx.primary())

        if isinstance(ctx, AP.SubExpressionContext):
            return self.expr(ctx.expression())

        if isinstance(ctx, AP.DotExpressionContext):
            return self._dot(ctx)

        if isinstance(ctx, AP.MethodCallExpressionContext):
            return self._method_call(ctx.methodCall())

        if isinstance(ctx, AP.ArrayExpressionContext):
            return ArrayAccess(array=self.expr(ctx.expression(0)),
                               index=self.expr(ctx.expression(1)))

        if isinstance(ctx, AP.NewExpressionContext):
            return self._creator(ctx.creator())

        if isinstance(ctx, AP.CastExpressionContext):
            return CastExpr(target_type=ctx.typeRef().getText(),
                            expr=self.expr(ctx.expression()))

        if isinstance(ctx, AP.NegExpressionContext):
            if ctx.BANG() is not None:
                return UnaryOp(op="!", operand=self.expr(ctx.expression()))
            raise _Unsupported("opérateur ~")

        if isinstance(ctx, AP.PreOpExpressionContext):
            inner = self.expr(ctx.expression())
            if ctx.SUB() is not None:
                # Parité maison : -x → 0 - x
                return BinaryOp(left=IntegerLiteral(value=0), op="-", right=inner)
            if ctx.ADD() is not None:
                return inner
            raise _Unsupported("++/-- en expression")

        if isinstance(ctx, (AP.Arth1ExpressionContext, AP.Arth2ExpressionContext,
                            AP.LogAndExpressionContext, AP.LogOrExpressionContext,
                            AP.BitAndExpressionContext, AP.BitOrExpressionContext,
                            AP.BitNotExpressionContext)):
            return BinaryOp(left=self.expr(ctx.expression(0)),
                            op=ctx.getChild(1).getText(),
                            right=self.expr(ctx.expression(1)))

        if isinstance(ctx, AP.CmpExpressionContext):
            op = "".join(ch.getText() for ch in ctx.children[1:-1])
            return BinaryOp(left=self.expr(ctx.expression(0)), op=op,
                            right=self.expr(ctx.expression(1)))

        if isinstance(ctx, AP.EqualityExpressionContext):
            op = ctx.getChild(1).getText()
            if op not in ("==", "!="):
                raise _Unsupported("opérateur {}".format(op))
            return BinaryOp(left=self.expr(ctx.expression(0)), op=op,
                            right=self.expr(ctx.expression(1)))

        if isinstance(ctx, AP.InstanceOfExpressionContext):
            return BinaryOp(left=self.expr(ctx.expression()), op="instanceof",
                            right=Variable(name=ctx.typeRef().getText()))

        if isinstance(ctx, AP.CoalExpressionContext):
            # Parité maison : a ?? b → (a != null) ? a : b
            left = self.expr(ctx.expression(0))
            return Ternary(
                condition=BinaryOp(left=left, op="!=", right=NullLiteral()),
                then_expr=left,
                else_expr=self.expr(ctx.expression(1)),
            )

        if isinstance(ctx, AP.CondExpressionContext):
            return Ternary(condition=self.expr(ctx.expression(0)),
                           then_expr=self.expr(ctx.expression(1)),
                           else_expr=self.expr(ctx.expression(2)))

        raise _Unsupported(type(ctx).__name__)

    def _primary(self, ctx) -> Expr:
        AP = self.AP
        if isinstance(ctx, AP.ThisPrimaryContext):
            return Variable(name="this")
        if isinstance(ctx, AP.SuperPrimaryContext):
            return Variable(name="super")
        if isinstance(ctx, AP.IdPrimaryContext):
            return Variable(name=ctx.id_().getText())
        if isinstance(ctx, AP.TypeRefPrimaryContext):
            # Parité maison : Type.class → StringLiteral('Type')
            return StringLiteral(value=_src(ctx.typeRef()))
        if isinstance(ctx, AP.SoqlPrimaryContext):
            return StringLiteral(value=_src(ctx))
        if isinstance(ctx, AP.SoslPrimaryContext):
            return StringLiteral(value=_src(ctx))
        if isinstance(ctx, AP.LiteralPrimaryContext):
            return self._literal(ctx.literal())
        raise _Unsupported(type(ctx).__name__)

    def _literal(self, ctx) -> Expr:
        if ctx.IntegerLiteral() is not None:
            return IntegerLiteral(value=int(ctx.getText()))
        if ctx.LongLiteral() is not None:
            return IntegerLiteral(value=int(ctx.getText().rstrip("lL")))
        if ctx.NumberLiteral() is not None:
            # Parité maison : les décimaux sont des IntegerLiteral à valeur float
            return IntegerLiteral(value=float(ctx.getText().rstrip("dD")))
        if ctx.StringLiteral() is not None:
            return StringLiteral(value=_unquote(ctx.getText()))
        if ctx.MultilineStringLiteral() is not None:
            return StringLiteral(value=_unquote(ctx.getText()))
        if ctx.BooleanLiteral() is not None:
            return BooleanLiteral(value=ctx.getText().lower() == "true")
        if ctx.NULL() is not None:
            return NullLiteral()
        raise _Unsupported("littéral")

    def _dot(self, ctx) -> Expr:
        base = self.expr(ctx.expression())
        if ctx.dotMethodCall() is not None:
            dmc = ctx.dotMethodCall()
            method = dmc.anyId().getText()
            args = self._args(dmc.expressionList())
            if isinstance(base, Variable):
                return MethodCall(obj=base.name, method=method, args=args)
            return ChainedCall(target=base, method=method, args=args)
        member = ctx.anyId().getText()
        # Parité maison : Type.class → StringLiteral (cas expr.class résiduel)
        if member == "class" and isinstance(base, Variable):
            return StringLiteral(value=base.name)
        if isinstance(base, Variable):
            return FieldAccess(obj=base.name, field=member)
        return ChainedCall(target=base, method=member, args=[])

    def _method_call(self, ctx) -> Expr:
        args = self._args(ctx.expressionList())
        if ctx.SUPER() is not None:
            return MethodCall(obj="_super", method="_init", args=args)
        if ctx.THIS() is not None:
            raise _Unsupported("this(...)")
        return MethodCall(obj="_self", method=ctx.id_().getText(), args=args)

    def _args(self, expr_list_ctx) -> list:
        if expr_list_ctx is None:
            return []
        return [self.expr(e) for e in expr_list_ctx.expression()]

    def _creator(self, ctx) -> Expr:
        AP = self.AP
        pairs = ctx.createdName().idCreatedNamePair()
        head = pairs[0]
        head_name = head.anyId().getText()
        type_args = head.typeList().typeRef() if head.typeList() is not None else None

        # Collections typées : new List<T>, new Set<T>, new Map<K,V>
        if head_name.lower() in ("list", "set", "map") and type_args is not None:
            return self._collection_creator(ctx, head_name, type_args)

        class_name = ".".join(p.anyId().getText() for p in pairs)

        if ctx.arrayCreatorRest() is not None:
            acr = ctx.arrayCreatorRest()
            if acr.expression() is not None:
                return NewArray(element_type=class_name,
                                size=self.expr(acr.expression()))
            values = []
            if acr.arrayInitializer() is not None:
                values = [self.expr(e)
                          for e in acr.arrayInitializer().expression()]
            return NewList(element_type=class_name, init_values=values)

        if ctx.classCreatorRest() is not None:
            arg_list = ctx.classCreatorRest().arguments().expressionList()
            exprs = arg_list.expression() if arg_list is not None else []
            if not exprs:
                return NewSObject(sobject_type=class_name, fields={})
            fields = self._sobject_fields(exprs)
            if fields is not None:
                return NewSObject(sobject_type=class_name, fields=fields)
            return NewInstance(class_name=class_name,
                               args=[self.expr(e) for e in exprs])

        if ctx.noRest() is not None:
            return NewSObject(sobject_type=class_name, fields={})

        raise _Unsupported("créateur {}".format(class_name))

    def _sobject_fields(self, exprs):
        """{field: Expr} si tous les args sont `Nom = valeur`, sinon None."""
        AP = self.AP
        fields = {}
        for e in exprs:
            if not isinstance(e, AP.AssignExpressionContext) \
                    or e.getChild(1).getText() != "=":
                return None
            target = e.expression(0)
            if not isinstance(target, AP.PrimaryExpressionContext) \
                    or not isinstance(target.primary(), AP.IdPrimaryContext):
                return None
            fields[target.primary().id_().getText()] = self.expr(e.expression(1))
        return fields

    def _collection_creator(self, ctx, kind, type_args) -> Expr:
        kind = kind.lower()
        if kind == "map":
            key_type = _src(type_args[0])
            value_type = _src(type_args[1]) if len(type_args) > 1 else "Object"
            if ctx.mapCreatorRest() is not None:
                entries = [(self.expr(p.expression(0)), self.expr(p.expression(1)))
                           for p in ctx.mapCreatorRest().mapCreatorRestPair()]
                return NewMapInit(key_type=key_type, value_type=value_type,
                                  entries=entries)
            if ctx.noRest() is not None:
                return NewMapInit(key_type=key_type, value_type=value_type,
                                  entries=[])
            return NewMap(key_type=key_type, value_type=value_type)

        elem_type = _src(type_args[0])
        values = []
        if ctx.setCreatorRest() is not None:
            values = [self.expr(e) for e in ctx.setCreatorRest().expression()]
        elif ctx.classCreatorRest() is not None:
            arg_list = ctx.classCreatorRest().arguments().expressionList()
            if arg_list is not None:
                values = [self.expr(e) for e in arg_list.expression()]
        if kind == "list":
            return NewList(element_type=elem_type, init_values=values)
        return NewSet(element_type=elem_type, init_values=values)


# ---------------------------------------------------------------------- #
# API publique
# ---------------------------------------------------------------------- #

def parse_full_class(source: str) -> ClassDef:
    """Parse une classe Apex complète via ANTLR → ClassDef."""
    tree, parser_cls = _parse(source, "compilationUnit")
    return _Builder(parser_cls).build_compilation_unit(tree)


_EVENT_MAP = {
    "before insert": "before_insert",
    "before update": "before_update",
    "after insert": "after_insert",
    "after update": "after_update",
    "before delete": "before_delete",
    "after delete": "after_delete",
}


def parse_trigger(source: str):
    """Parse un fichier .trigger → (name, sobject, events, body_stmts)."""
    tree, parser_cls = _parse(source, "triggerUnit")
    builder = _Builder(parser_cls)

    ids = tree.id_()
    name, sobject = ids[0].getText(), ids[1].getText()

    events = []
    for case in tree.triggerCase():
        timing = case.getChild(0).getText().lower()
        operation = case.getChild(1).getText().lower()
        key = "{} {}".format(timing, operation)
        if key in _EVENT_MAP:
            events.append(_EVENT_MAP[key])

    body_stmts = []
    for member in tree.triggerBlock().triggerBlockMember():
        if member.statement() is not None:
            body_stmts.extend(builder.stmt(member.statement()))

    return name, sobject, events, body_stmts
