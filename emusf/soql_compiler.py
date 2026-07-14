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
    parent_joins: dict = field(default_factory=dict)  # alias → (sf_rel, fk_col, parent_table)


class SoqlCompiler:
    """Compile un AST SOQL en SQL paramétré + params."""

    def __init__(self, schema: str, context: dict, sf_schema=None):
        self.schema = schema
        self.context = context
        self.params = []
        self.sf_schema = sf_schema  # SchemaRegistry (optionnel)
        self._joins: dict = {}  # alias → (fk_column, parent_table)

    def _resolve_relationship_field(self, field_name: str, sobject: str):
        """Résout un champ __r en (alias_pg, col_pg, sf_rel_name).
        Retourne None si ce n'est pas un champ relationnel ou si non résolu."""
        if "__r." not in field_name and "." not in field_name:
            return None
        parts = field_name.split(".", 1)
        rel_ref = parts[0]  # ex: "LLM_Prompt__r" ou "Account"
        child_field = parts[1]  # ex: "Name"

        # Custom relationship (__r suffix)
        if rel_ref.endswith("__r"):
            rel_name = rel_ref[:-3]  # strip __r
        else:
            rel_name = rel_ref  # standard relationship (Account, etc.)

        if not self.sf_schema:
            return None

        meta = self.sf_schema.resolve_parent(rel_name, sobject)
        if not meta:
            return None

        alias = rel_ref.lower()
        if alias not in self._joins:
            self._joins[alias] = (meta.fk_column.lower(), meta.parent_sobject.lower())
        return alias, child_field.lower(), rel_ref

    def compile(self, ast: SoqlSelect) -> CompiledQuery:
        sobject = ast.from_object
        table = "{}.{}".format(self.schema, sobject.lower())
        main_alias = "t0"

        # Détecter COUNT() sans champ
        is_count = (
            len(ast.fields) == 1
            and isinstance(ast.fields[0], SoqlAggregate)
            and ast.fields[0].function == "COUNT"
            and ast.fields[0].field is None
        )

        # Détecter les requêtes avec agrégats
        is_aggregate = any(isinstance(f, SoqlAggregate) for f in ast.fields)

        # Pré-scan : résoudre les relations __r pour savoir si on a besoin de JOINs
        if self.sf_schema:
            for f in ast.fields:
                if isinstance(f, SoqlField) and ("__r." in f.name or ("." in f.name and not f.name.startswith("_"))):
                    self._resolve_relationship_field(f.name, sobject)

        use_joins = bool(self._joins)

        # SELECT
        sf_fields = []
        field_aliases = {}
        parent_joins_info = {}
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
                    # Champ relationnel résolu ?
                    rel = self._resolve_relationship_field(f.name, sobject) if use_joins else None
                    if rel:
                        alias_tbl, pg_col, sf_rel = rel
                        sf_name = f.name  # ex: "LLM_Prompt__r.Id"
                        pg_alias = "{}_{}".format(alias_tbl, pg_col)
                        select_parts.append("{}.{} AS {}".format(alias_tbl, pg_col, pg_alias))
                        field_aliases[pg_alias] = sf_name
                        sf_fields.append(sf_name)
                    else:
                        pg_col = f.name.lower()
                        # Ignorer les champs relationnels non résolus (pas de schema)
                        if "." in pg_col:
                            pg_col = pg_col.replace(".", "__")
                        if use_joins:
                            select_parts.append("{}.{}".format(main_alias, pg_col))
                        else:
                            select_parts.append(pg_col)
                        sf_fields.append(f.name)
            select_clause = ", ".join(select_parts)

        if use_joins:
            sql = "SELECT {} FROM {} {}".format(select_clause, table, main_alias)
            for alias, (fk_col, parent_table) in self._joins.items():
                parent_tbl = "{}.{}".format(self.schema, parent_table)
                sql += " LEFT JOIN {} {} ON {}.{} = {}.id".format(
                    parent_tbl, alias, main_alias, fk_col, alias)
                parent_joins_info[alias] = (fk_col, parent_table)
        else:
            sql = "SELECT {} FROM {}".format(select_clause, table)

        # WHERE
        if ast.where:
            where_sql = self._compile_expr(ast.where, main_alias if use_joins else None, sobject)
            sql += " WHERE " + where_sql

        use_alias = use_joins

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
                if use_alias and "." not in s:
                    s = "{}.{}".format(main_alias, s)
                if item.direction == "DESC":
                    s += " DESC"
                if item.nulls:
                    s += " NULLS " + item.nulls
                parts.append(s)
            sql += " ORDER BY " + ", ".join(parts)

        # LIMIT
        if ast.limit is not None:
            limit = ast.limit
            if isinstance(limit, SoqlBindVar):  # LIMIT :variable
                limit = int(self._resolve_bind(limit.path))
            sql += " LIMIT {}".format(int(limit))

        return CompiledQuery(
            sql=sql,
            params=self.params,
            sobject=sobject,
            fields=sf_fields,
            field_aliases=field_aliases,
            subqueries=ast.subqueries,
            is_count=is_count,
            is_aggregate=is_aggregate,
            parent_joins=parent_joins_info,
        )

    def _compile_aggregate(self, agg: SoqlAggregate) -> str:
        if agg.field:
            return "{}({})".format(agg.function, agg.field.lower())
        return "{}(*)".format(agg.function)

    # === Expressions ===

    def _qualify_col(self, col: str, main_alias: str = None, sobject: str = None) -> str:
        """Qualifie un nom de colonne avec l'alias de table si nécessaire."""
        if main_alias and "." in col:
            # Champ relationnel (__r) dans WHERE
            parts = col.split(".", 1)
            rel_ref = parts[0]
            if rel_ref in self._joins:
                return "{}.{}".format(rel_ref, parts[1])
            # Essayer de résoudre la relation
            if sobject and self.sf_schema:
                rel_name = rel_ref[:-3] if rel_ref.endswith("__r") else rel_ref
                meta = self.sf_schema.resolve_parent(rel_name, sobject)
                if meta:
                    if rel_ref not in self._joins:
                        self._joins[rel_ref] = (meta.fk_column.lower(), meta.parent_sobject.lower())
                    return "{}.{}".format(rel_ref, parts[1])
        if main_alias and "." not in col:
            return "{}.{}".format(main_alias, col)
        return col

    def _compile_expr(self, expr: SoqlExpr, main_alias: str = None, sobject: str = None) -> str:
        if isinstance(expr, SoqlAnd):
            l = self._compile_expr(expr.left, main_alias, sobject)
            r = self._compile_expr(expr.right, main_alias, sobject)
            return "({} AND {})".format(l, r)

        if isinstance(expr, SoqlOr):
            l = self._compile_expr(expr.left, main_alias, sobject)
            r = self._compile_expr(expr.right, main_alias, sobject)
            return "({} OR {})".format(l, r)

        if isinstance(expr, SoqlNot):
            inner = self._compile_expr(expr.operand, main_alias, sobject)
            return "(NOT {})".format(inner)

        if isinstance(expr, SoqlNullCheck):
            col = self._qualify_col(expr.field.lower(), main_alias, sobject)
            if expr.is_null:
                return "{} IS NULL".format(col)
            return "{} IS NOT NULL".format(col)

        if isinstance(expr, SoqlComparison):
            return self._compile_comparison(expr, main_alias, sobject)

        if isinstance(expr, SoqlIn):
            return self._compile_in(expr, main_alias, sobject)

        raise Exception("Expression SOQL inconnue: {}".format(type(expr).__name__))

    def _compile_comparison(self, cmp: SoqlComparison, main_alias: str = None, sobject: str = None) -> str:
        col = self._qualify_col(cmp.field.lower(), main_alias, sobject)
        value = self._resolve_value(cmp.value)

        # Si la valeur résolue est None, convertir en IS NULL / IS NOT NULL
        if value is None:
            if cmp.op == "=":
                return "{} IS NULL".format(col)
            elif cmp.op == "!=":
                return "{} IS NOT NULL".format(col)

        # Comparaison à un booléen : les tables auto-créées stockent tout en
        # TEXT ('True'/'False'), donc caster la colonne en boolean pour que
        # 'IsDeleted = false' fonctionne (no-op sur une vraie colonne boolean)
        if isinstance(value, bool):
            self.params.append(value)
            return "({})::boolean {} %s".format(col, cmp.op)

        self.params.append(value)
        return "{} {} %s".format(col, cmp.op)

    def _compile_in(self, in_expr: SoqlIn, main_alias: str = None, sobject: str = None) -> str:
        col = self._qualify_col(in_expr.field.lower(), main_alias, sobject)
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


def compile_soql(soql: str, context: dict = None, schema: str = "data", sf_schema=None) -> CompiledQuery:
    """Point d'entrée : SOQL string → CompiledQuery (SQL paramétré + params)."""
    if context is None:
        context = {}
    ast = parse(soql)
    compiler = SoqlCompiler(schema, context, sf_schema=sf_schema)
    return compiler.compile(ast)
