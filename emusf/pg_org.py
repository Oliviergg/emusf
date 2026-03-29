"""PgOrg - Org Salesforce connectée à PostgreSQL (données réelles)."""

from __future__ import annotations

from typing import Optional

import psycopg2
import psycopg2.extras

from .soql_compiler import compile_soql, CompiledQuery, SoqlCompiler
from .soql_ast import SoqlComparison, SoqlAnd, SoqlLiteral
from .soql_parser import parse as soql_parse
from .schema import SchemaRegistry, RelationshipMeta


# Mapping des noms de champs Salesforce → noms de colonnes PG (lowercase)
def sf_to_pg_column(field: str) -> str:
    """Convertit un nom de champ Salesforce en nom de colonne PG."""
    return field.lower()


class PgOrg:
    """
    Org Salesforce connectée à une base PostgreSQL.
    Les données viennent d'un export Salesforce dans le schema 'data'.
    """

    def __init__(self, dsn: str, schema: str = "data"):
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True
        self.schema_name = schema
        self.sf_schema = SchemaRegistry()
        self._tables: dict = {}

        # Charger les métadonnées des tables existantes
        self._load_table_meta()

        # Relations standard
        self.sf_schema.register(RelationshipMeta(
            plural_name="Contacts",
            sobject_name="Contact",
            fk_column="AccountId",
            parent_sobject="Account",
        ))

    def _load_table_meta(self):
        """Charge les colonnes de chaque table du schema."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """, [self.schema_name])
        for table, col in cur.fetchall():
            if table not in self._tables:
                self._tables[table] = []
            self._tables[table].append(col)
        cur.close()

    def get_columns(self, sobject: str) -> list:
        """Retourne les colonnes disponibles pour un SObject."""
        return self._tables.get(sobject.lower(), [])

    def execute_soql(self, soql: str, context: Optional[dict] = None) -> list:
        """Exécute une requête SOQL contre PostgreSQL."""
        if context is None:
            context = {}
        cq = compile_soql(soql, context, schema=self.schema_name, sf_schema=self.sf_schema)
        return self._execute(cq)

    def _execute(self, cq: CompiledQuery) -> list:
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(cq.sql, cq.params)
        raw_rows = cur.fetchall()
        cur.close()

        # COUNT() → entier (retourné comme liste vide de N éléments pour compat)
        if cq.is_count:
            count_val = raw_rows[0]["count"] if raw_rows else 0
            return [{}] * count_val

        # Agrégats (GROUP BY) → retourner les dicts bruts
        if cq.is_aggregate:
            return [dict(row) for row in raw_rows]

        # Mapping PG cols → noms SF
        field_map = {}
        for sf_name in cq.fields:
            field_map[sf_name.lower()] = sf_name
        # Ajouter les alias de champs relationnels
        for pg_alias, sf_name in cq.field_aliases.items():
            field_map[pg_alias] = sf_name

        rows = []
        for raw in raw_rows:
            row = {"_sobject_type": cq.sobject}
            for pg_col, val in raw.items():
                sf_field = field_map.get(pg_col, pg_col)
                # Champs relationnels (__r) : imbriquer dans un sous-dict
                if "." in sf_field and ("__r." in sf_field or sf_field[0].isupper()):
                    parts = sf_field.split(".", 1)
                    rel_name = parts[0]
                    child_field = parts[1]
                    if rel_name not in row:
                        row[rel_name] = {}
                    row[rel_name][child_field] = val
                else:
                    row[sf_field] = val
            rows.append(row)

        # Sous-requêtes enfant
        if cq.subqueries:
            for row in rows:
                parent_id = row.get("Id") or row.get("id")
                for sub_sel in cq.subqueries:
                    rel_name = sub_sel.relationship
                    meta = self.sf_schema.resolve(rel_name, cq.sobject)
                    if not meta:
                        raise Exception(
                            "Relation '{}' inconnue sur '{}'".format(rel_name, cq.sobject))

                    # Injecter la condition FK dans l'AST de la sous-requête
                    fk_cond = SoqlComparison(
                        field=meta.fk_column,
                        op="=",
                        value=SoqlLiteral(value=parent_id),
                    )
                    sub_ast = sub_sel.query
                    if sub_ast.where:
                        sub_ast_where = SoqlAnd(left=sub_ast.where, right=fk_cond)
                    else:
                        sub_ast_where = fk_cond

                    # Résoudre le nom réel du SObject via la relation
                    from .soql_ast import SoqlSelect
                    patched = SoqlSelect(
                        fields=sub_ast.fields,
                        from_object=meta.sobject_name,
                        where=sub_ast_where,
                        subqueries=sub_ast.subqueries,
                        order_by=sub_ast.order_by,
                        limit=sub_ast.limit,
                    )
                    compiler = SoqlCompiler(self.schema_name, {})
                    sub_cq = compiler.compile(patched)
                    row[rel_name] = self._execute(sub_cq)

        return rows
