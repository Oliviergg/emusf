"""Compilateur SOQL → SQL paramétré pour PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .soql_ast import (
    SoqlSelect, SoqlField, SoqlAggregate, SoqlSubSelect, SoqlOrderItem,
    SoqlExpr, SoqlAnd, SoqlOr, SoqlNot,
    SoqlComparison, SoqlIn, SoqlNullCheck,
    SoqlValue, SoqlLiteral, SoqlBindVar, SoqlDateLiteral,
)
from .soql_parser import parse


@dataclass
class CompiledQuery:
    sql: str
    params: list
    sobject: str
    fields: list[str]  # noms SF originaux pour le mapping retour
    field_aliases: dict = field(default_factory=dict)  # alias → nom PG
    subqueries: list = field(default_factory=list)  # list[SoqlSubSelect] non compilées
    is_count: bool = False
    is_aggregate: bool = False


class SoqlCompiler:
    """Compile un AST SOQL en SQL paramétré + params."""

    def __init__(self, schema: str, context: dict):
        self.schema = schema
        self.context = context
        self.params = []

    def compile(self, ast: SoqlSelect) -> CompiledQuery:
        sobject = ast.from_object
        table = "{}.{}".format(self.schema, sobject.lower())

        # Détecter COUNT() sans champ
        is_count = (
            len(ast.fields) == 1
            and isinstance(ast.fields[0], SoqlAggregate)
            and ast.fields[0].function == "COUNT"
            and ast.fields[0].field is None
        )

        # Détecter les requêtes avec agrégats
        is_aggregate = any(isinstance(f, SoqlAggregate) for f in ast.fields)

        # SELECT
        sf_fields = []
        field_aliases = {}
        if is_count:
            select_clause = "COUNT(*)"
        else:
            select_parts = []
            for f in ast.fields:
                if isinstance(f, SoqlAggregate):
                    col = self._compile_aggregate(f)
                    alias = f.alias or f.function.lower()
                    select_parts.append("{} AS {}".format(col, alias))
                    field_aliases[alias] = alias
                    sf_fields.append(alias)
                else:
                    pg_col = f.name.lower()
                    select_parts.append(pg_col)
                    sf_fields.append(f.name)
            select_clause = ", ".join(select_parts)

        sql = "SELECT {} FROM {}".format(select_clause, table)

        # WHERE
        if ast.where:
            where_sql = self._compile_expr(ast.where)
            sql += " WHERE " + where_sql

        # GROUP BY
        if ast.group_by:
            sql += " GROUP BY " + ", ".join(g.lower() for g in ast.group_by)

        # HAVING
        if ast.having:
            sql += " HAVING " + self._compile_expr(ast.having)

        # ORDER BY
        if ast.order_by and not is_count:
            parts = []
            for item in ast.order_by:
                s = item.field.lower()
                if item.direction == "DESC":
                    s += " DESC"
                if item.nulls:
                    s += " NULLS " + item.nulls
                parts.append(s)
            sql += " ORDER BY " + ", ".join(parts)

        # LIMIT
        if ast.limit is not None:
            sql += " LIMIT {}".format(ast.limit)

        return CompiledQuery(
            sql=sql,
            params=self.params,
            sobject=sobject,
            fields=sf_fields,
            field_aliases=field_aliases,
            subqueries=ast.subqueries,
            is_count=is_count,
            is_aggregate=is_aggregate,
        )

    def _compile_aggregate(self, agg: SoqlAggregate) -> str:
        if agg.field:
            return "{}({})".format(agg.function, agg.field.lower())
        return "{}(*)".format(agg.function)

    # === Expressions ===

    def _compile_expr(self, expr: SoqlExpr) -> str:
        if isinstance(expr, SoqlAnd):
            l = self._compile_expr(expr.left)
            r = self._compile_expr(expr.right)
            return "({} AND {})".format(l, r)

        if isinstance(expr, SoqlOr):
            l = self._compile_expr(expr.left)
            r = self._compile_expr(expr.right)
            return "({} OR {})".format(l, r)

        if isinstance(expr, SoqlNot):
            inner = self._compile_expr(expr.operand)
            return "(NOT {})".format(inner)

        if isinstance(expr, SoqlNullCheck):
            col = expr.field.lower()
            if expr.is_null:
                return "{} IS NULL".format(col)
            return "{} IS NOT NULL".format(col)

        if isinstance(expr, SoqlComparison):
            return self._compile_comparison(expr)

        if isinstance(expr, SoqlIn):
            return self._compile_in(expr)

        raise Exception("Expression SOQL inconnue: {}".format(type(expr).__name__))

    def _compile_comparison(self, cmp: SoqlComparison) -> str:
        col = cmp.field.lower()
        value = self._resolve_value(cmp.value)

        # Si la valeur résolue est None, convertir en IS NULL / IS NOT NULL
        if value is None:
            if cmp.op == "=":
                return "{} IS NULL".format(col)
            elif cmp.op == "!=":
                return "{} IS NOT NULL".format(col)

        self.params.append(value)
        return "{} {} %s".format(col, cmp.op)

    def _compile_in(self, in_expr: SoqlIn) -> str:
        col = in_expr.field.lower()
        neg = "NOT " if in_expr.negated else ""

        # Sous-requête : IN (SELECT ...)
        if isinstance(in_expr.values, SoqlSelect):
            sub_compiler = SoqlCompiler(self.schema, self.context)
            sub_result = sub_compiler.compile(in_expr.values)
            self.params.extend(sub_result.params)
            return "{} {}IN ({})".format(col, neg, sub_result.sql)

        # Liste de valeurs ou bind var unique
        values = in_expr.values
        if len(values) == 1 and isinstance(values[0], SoqlBindVar):
            resolved = self._resolve_bind(values[0].path)
            if isinstance(resolved, (list, set, tuple)):
                items = list(resolved)
                if not items:
                    return "FALSE" if not in_expr.negated else "TRUE"
                placeholders = ", ".join(["%s"] * len(items))
                # Extraire les Id des SObjects si nécessaire
                for item in items:
                    if isinstance(item, dict):
                        self.params.append(item.get("Id", item.get("id", str(item))))
                    else:
                        self.params.append(item)
                return "{} {}IN ({})".format(col, neg, placeholders)
            else:
                # Valeur unique
                self.params.append(resolved)
                return "{} {} %s".format(col, "!=" if in_expr.negated else "=")

        # Liste littérale
        placeholders = []
        for v in values:
            resolved = self._resolve_value(v)
            self.params.append(resolved)
            placeholders.append("%s")
        return "{} {}IN ({})".format(col, neg, ", ".join(placeholders))

    # === Résolution des valeurs ===

    def _resolve_value(self, val: SoqlValue):
        if isinstance(val, SoqlLiteral):
            return val.value

        if isinstance(val, SoqlBindVar):
            return self._resolve_bind(val.path)

        if isinstance(val, SoqlDateLiteral):
            if val.keyword == "TODAY":
                from datetime import date
                return date.today()
            if val.keyword == "YESTERDAY":
                from datetime import date, timedelta
                return date.today() - timedelta(days=1)
            return None

        return None

    def _resolve_bind(self, path: str):
        """Résout une bind variable depuis le contexte."""
        # Essayer le chemin complet d'abord (ClassName.CONSTANT)
        if path in self.context:
            return self._convert_value(self.context[path])

        # Chemin doté : obj.field
        parts = path.split(".")
        value = self.context.get(parts[0])
        for part in parts[1:]:
            if isinstance(value, dict):
                found = value.get(part)
                if found is None:
                    # Lookup case-insensitive
                    for k, v in value.items():
                        if k.lower() == part.lower():
                            found = v
                            break
                value = found
            else:
                value = None
                break

        return self._convert_value(value)

    def _convert_value(self, value):
        """Convertit une valeur Apex en valeur SQL."""
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            # Date dict → string ISO
            if value.get("_type") == "Date":
                return "{}-{:02d}-{:02d}".format(value["year"], value["month"], value["day"])
            if value.get("_type") == "DateTime":
                return "{}-{:02d}-{:02d}".format(
                    value.get("year", 2000), value.get("month", 1), value.get("day", 1))
            # SObject → Id
            return value.get("Id", value.get("id", str(value)))
        if isinstance(value, (list, set)):
            return value  # Gardé tel quel pour IN clauses
        return str(value)


def compile_soql(soql: str, context: dict = None, schema: str = "data") -> CompiledQuery:
    """Point d'entrée : SOQL string → CompiledQuery (SQL paramétré + params)."""
    if context is None:
        context = {}
    ast = parse(soql)
    compiler = SoqlCompiler(schema, context)
    return compiler.compile(ast)
