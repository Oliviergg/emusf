"""PgOrg - Org Salesforce connectée à PostgreSQL (données réelles)."""

from __future__ import annotations

import re
from typing import Optional

import psycopg2
import psycopg2.extras

from .parser import SOQLQuery, parse_soql
from .schema import SchemaRegistry, RelationshipMeta


# Mapping des noms de champs Salesforce → noms de colonnes PG (lowercase)
# Les colonnes PG sont en snake_case lowercase, les champs SF en CamelCase
def sf_to_pg_column(field: str) -> str:
    """Convertit un nom de champ Salesforce en nom de colonne PG."""
    return field.lower()


def pg_to_sf_field(col: str, field_map: dict) -> str:
    """Retrouve le nom SF original depuis le nom PG."""
    return field_map.get(col, col)


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
        query = parse_soql(soql, context)
        return self._execute(query)

    def _execute(
        self, query: SOQLQuery, parent_sobject: Optional[str] = None
    ) -> list:
        sobject_name = query.sobject

        if parent_sobject:
            meta = self.sf_schema.resolve(query.sobject, parent_sobject)
            if meta:
                sobject_name = meta.sobject_name
            else:
                raise Exception(
                    "Relation '{}' inconnue sur '{}'".format(
                        query.sobject, parent_sobject
                    )
                )

        # Construire le mapping champ SF → colonne PG
        pg_table = "{}.{}".format(self.schema_name, sobject_name.lower())

        # Les champs SOQL sont en CamelCase, PG en lowercase
        pg_fields = []
        sf_fields = query.fields if query.fields else ["*"]
        field_map = {}  # pg_col → sf_field

        for f in sf_fields:
            pg_col = sf_to_pg_column(f)
            pg_fields.append(pg_col)
            field_map[pg_col] = f

        select_clause = ", ".join(pg_fields)
        sql = "SELECT {} FROM {}".format(select_clause, pg_table)

        # WHERE — convertir les noms de champs en lowercase
        params = []
        if query.where:
            where_pg = self._convert_where(query.where, params)
            sql += " WHERE " + where_pg
        if query.order_by:
            sql += " ORDER BY " + query.order_by.lower()
        if query.limit:
            sql += " LIMIT {}".format(query.limit)

        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        raw_rows = cur.fetchall()
        cur.close()

        # Reconvertir les clés PG → noms SF
        rows = []
        for raw in raw_rows:
            row = {}
            for pg_col, val in raw.items():
                sf_field = field_map.get(pg_col, pg_col)
                row[sf_field] = val
            rows.append(row)

        # Sous-requêtes
        if query.subqueries:
            for row in rows:
                parent_id = row.get("Id") or row.get("id")
                for relation_name, sub in query.subqueries.items():
                    meta = self.sf_schema.resolve(relation_name, sobject_name)
                    if not meta:
                        raise Exception(
                            "Relation '{}' inconnue sur '{}'".format(
                                relation_name, sobject_name
                            )
                        )
                    sub_with_where = SOQLQuery(
                        fields=sub.fields,
                        sobject=relation_name,
                        where="{} = '{}'".format(meta.fk_column, parent_id),
                    )
                    row[relation_name] = self._execute(
                        sub_with_where, parent_sobject=sobject_name
                    )

        return rows

    def _convert_where(self, where: str, params: list) -> str:
        """
        Convertit une clause WHERE SOQL en SQL PG.
        - Noms de champs en lowercase
        - Les valeurs quotées restent telles quelles
        """
        # Convertir les identifiants (pas les strings) en lowercase
        result = ""
        in_string = False
        token = ""

        for ch in where:
            if ch == "'":
                if in_string:
                    result += token + ch
                    token = ""
                    in_string = False
                else:
                    # Flush le token courant en lowercase
                    result += token.lower()
                    token = ""
                    result += ch
                    in_string = True
            elif in_string:
                token += ch
            else:
                token += ch

        # Flush le dernier token
        if token:
            if in_string:
                result += token
            else:
                result += token.lower()

        return result
