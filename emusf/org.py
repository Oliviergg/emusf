"""FakeOrg - simule une org Salesforce avec SQLite en mémoire."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Optional, Callable

from .parser import SOQLQuery, parse_soql
from .schema import SchemaRegistry, RelationshipMeta

# Préfixes d'Id par SObject (convention Salesforce)
SOBJECT_PREFIX = {
    "Account": "001",
    "Contact": "003",
    "Opportunity": "006",
    "Case": "500",
    "Lead": "00Q",
    "Task": "00T",
}


class DmlResult:
    """Résultat d'une opération DML."""

    def __init__(self, success: bool, record_ids: list, errors: list = None):
        self.success = success
        self.record_ids = record_ids
        self.errors = errors or []

    def __repr__(self):
        if self.success:
            return "DmlResult(success=True, ids={})".format(self.record_ids)
        return "DmlResult(success=False, errors={})".format(self.errors)


class FakeOrg:
    """
    Simule une org Salesforce avec une base SQLite en mémoire.
    Supporte SOQL, INSERT, UPDATE avec triggers before/after.
    """

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.schema = SchemaRegistry()
        self._tables: dict = {}
        self._triggers: dict = {}  # {'before_insert': {'Account': [fn]}, ...}
        self._id_counters: dict = {}  # auto-increment par SObject

    def create_sobject(self, name: str, columns: dict):
        """
        Crée un SObject (table) dans l'org.
        columns: {'Name': 'TEXT', 'Active__c': 'INTEGER DEFAULT 0', ...}
        """
        col_defs = ", ".join("{} {}".format(col, dtype) for col, dtype in columns.items())
        sql = "CREATE TABLE {} (Id TEXT PRIMARY KEY, {})".format(name, col_defs)
        self.conn.execute(sql)
        self.conn.commit()
        self._tables[name] = ["Id"] + list(columns.keys())

    def register_relationship(
        self,
        plural_name: str,
        child_sobject: str,
        fk_column: str,
        parent_sobject: str,
    ):
        """Enregistre une relation parent-enfant (ex: Account → Contacts)."""
        self.schema.register(
            RelationshipMeta(
                plural_name=plural_name,
                sobject_name=child_sobject,
                fk_column=fk_column,
                parent_sobject=parent_sobject,
            )
        )

    def insert(self, sobject: str, records: list) -> DmlResult:
        """
        Insert des enregistrements dans un SObject.
        Auto-génère les Id si absents. Déclenche les triggers.
        """
        # Auto-generate Ids
        for record in records:
            if "Id" not in record:
                record["Id"] = self._generate_id(sobject)

        # Before insert triggers
        self._fire_triggers("before_insert", sobject, records)

        for record in records:
            columns = ", ".join(record.keys())
            placeholders = ", ".join(["?" for _ in record])
            self.conn.execute(
                "INSERT INTO {} ({}) VALUES ({})".format(sobject, columns, placeholders),
                list(record.values()),
            )
        self.conn.commit()

        # After insert triggers
        self._fire_triggers("after_insert", sobject, records)

        return DmlResult(
            success=True,
            record_ids=[r["Id"] for r in records],
        )

    def update(self, sobject: str, records: list) -> DmlResult:
        """
        Update des enregistrements. Chaque record doit avoir un 'Id'.
        Déclenche les triggers before/after update.
        """
        # Charger les old values pour Trigger.old
        old_records = []
        for record in records:
            cursor = self.conn.execute(
                "SELECT * FROM {} WHERE Id = ?".format(sobject),
                [record["Id"]],
            )
            row = cursor.fetchone()
            if row:
                old_records.append(dict(row))

        # Before update triggers (reçoivent new et old)
        self._fire_triggers("before_update", sobject, records, old_records=old_records)

        for record in records:
            record_id = record["Id"]
            fields = {k: v for k, v in record.items() if k != "Id"}
            if not fields:
                continue
            set_clause = ", ".join("{} = ?".format(k) for k in fields.keys())
            values = list(fields.values()) + [record_id]
            self.conn.execute(
                "UPDATE {} SET {} WHERE Id = ?".format(sobject, set_clause),
                values,
            )
        self.conn.commit()

        # After update triggers
        self._fire_triggers("after_update", sobject, records, old_records=old_records)

        return DmlResult(
            success=True,
            record_ids=[r["Id"] for r in records],
        )

    def delete(self, sobject: str, record_ids: list) -> DmlResult:
        """Delete des enregistrements par Id."""
        # Charger les records pour les triggers
        records = []
        for rid in record_ids:
            cursor = self.conn.execute(
                "SELECT * FROM {} WHERE Id = ?".format(sobject), [rid]
            )
            row = cursor.fetchone()
            if row:
                records.append(dict(row))

        self._fire_triggers("before_delete", sobject, records)

        for rid in record_ids:
            self.conn.execute(
                "DELETE FROM {} WHERE Id = ?".format(sobject), [rid]
            )
        self.conn.commit()

        self._fire_triggers("after_delete", sobject, records)

        return DmlResult(success=True, record_ids=record_ids)

    # --- Triggers ---

    def add_trigger(self, event: str, sobject: str, callback: Callable):
        """
        Enregistre un trigger.
        event: 'before_insert', 'after_insert', 'before_update', 'after_update',
               'before_delete', 'after_delete'
        callback: fn(records, old_records=None)
        """
        if event not in self._triggers:
            self._triggers[event] = {}
        if sobject not in self._triggers[event]:
            self._triggers[event][sobject] = []
        self._triggers[event][sobject].append(callback)

    def _fire_triggers(self, event: str, sobject: str, records: list,
                       old_records: list = None):
        """Déclenche tous les triggers enregistrés pour cet événement."""
        callbacks = self._triggers.get(event, {}).get(sobject, [])
        for cb in callbacks:
            cb(records, old_records=old_records)

    def _generate_id(self, sobject: str) -> str:
        """Génère un Id Salesforce-like : prefix + compteur."""
        prefix = SOBJECT_PREFIX.get(sobject, "0XX")
        count = self._id_counters.get(sobject, 0) + 1
        self._id_counters[sobject] = count
        return "{}{}".format(prefix, str(count).zfill(12))

    def execute_soql(self, soql: str, context: Optional[dict] = None) -> list:
        """Exécute une requête SOQL et retourne les résultats."""
        if context is None:
            context = {}
        query = parse_soql(soql, context)
        return self._execute(query)

    def _execute(
        self, query: SOQLQuery, parent_sobject: Optional[str] = None
    ) -> list:
        sobject_name = query.sobject
        fk_column = None

        if parent_sobject:
            meta = self.schema.resolve(query.sobject, parent_sobject)
            if meta:
                sobject_name = meta.sobject_name
                fk_column = meta.fk_column
            else:
                raise Exception(
                    "Relation '{}' inconnue sur '{}' — vérifier le SchemaRegistry".format(
                        query.sobject, parent_sobject
                    )
                )

        fields = ", ".join(query.fields) if query.fields else "*"
        sql = "SELECT {} FROM {}".format(fields, sobject_name)
        if query.where:
            sql += " WHERE {}".format(query.where)

        cursor = self.conn.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]

        if query.subqueries:
            for row in rows:
                parent_id = row.get("Id")
                for relation_name, sub in query.subqueries.items():
                    meta = self.schema.resolve(relation_name, sobject_name)
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
