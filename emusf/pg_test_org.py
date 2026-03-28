"""PgTestOrg - Org de test avec DML contre PostgreSQL (schema isolé, rollback entre tests)."""

from __future__ import annotations

import uuid
from typing import Optional, Callable

from .pg_org import PgOrg, sf_to_pg_column
from .org import DmlResult, SOBJECT_PREFIX


class PgTestOrg(PgOrg):
    """
    Org de test : INSERT/UPDATE/DELETE contre un schema PG dédié.
    Supporte les triggers before/after comme FakeOrg.
    Rollback automatique entre les tests.
    """

    def __init__(self, dsn: str, schema: str = "test"):
        super().__init__(dsn, schema)
        self.conn.autocommit = False  # On contrôle les transactions
        self._triggers = {}
        self._id_counters = {}

    def begin(self):
        """Début d'un test — savepoint."""
        cur = self.conn.cursor()
        cur.execute("SAVEPOINT test_start")
        cur.close()

    def rollback(self):
        """Fin d'un test — rollback au savepoint."""
        cur = self.conn.cursor()
        cur.execute("ROLLBACK TO SAVEPOINT test_start")
        cur.close()

    def truncate_all(self):
        """Vide toutes les tables du schema test."""
        try:
            self.conn.rollback()
        except Exception:
            pass
        cur = self.conn.cursor()
        for table in self._tables:
            try:
                cur.execute("TRUNCATE {}.{} CASCADE".format(self.schema_name, table))
            except Exception:
                self.conn.rollback()
        self.conn.commit()
        cur.close()
        self._id_counters = {}

    # --- DML ---

    def insert(self, sobject: str, records: list) -> DmlResult:
        """Insert des enregistrements. Auto-génère les Id."""
        for record in records:
            if "Id" not in record and "id" not in record:
                record["Id"] = self._generate_id(sobject)

        self._fire_triggers("before_insert", sobject, records)

        cur = self.conn.cursor()
        for record in records:
            pg_record = {sf_to_pg_column(k): v for k, v in record.items()
                         if not k.startswith("_")}  # skip internal keys
            # Filter to valid columns only
            valid_cols = set(self.get_columns(sobject))
            if valid_cols:
                pg_record = {k: v for k, v in pg_record.items() if k in valid_cols}
            if not pg_record:
                continue
            # Filter out non-serializable values
            pg_record = {k: (str(v) if isinstance(v, (dict, list, set, bool)) else v)
                         for k, v in pg_record.items()}
            columns = ", ".join(pg_record.keys())
            placeholders = ", ".join(["%s"] * len(pg_record))
            try:
                cur.execute(
                    "INSERT INTO {}.{} ({}) VALUES ({})".format(
                        self.schema_name, sobject.lower(), columns, placeholders
                    ),
                    list(pg_record.values()),
                )
            except Exception:
                self.conn.rollback()
        self.conn.commit()
        cur.close()

        self._fire_triggers("after_insert", sobject, records)

        return DmlResult(
            success=True,
            record_ids=[r.get("Id", r.get("id")) for r in records],
        )

    def update(self, sobject: str, records: list) -> DmlResult:
        """Update des enregistrements. Chaque record doit avoir un Id."""
        self._fire_triggers("before_update", sobject, records)

        cur = self.conn.cursor()
        for record in records:
            record_id = record.get("Id", record.get("id"))
            pg_record = {sf_to_pg_column(k): v for k, v in record.items()
                         if k.lower() != "id" and not k.startswith("_")}
            valid_cols = set(self.get_columns(sobject))
            if valid_cols:
                pg_record = {k: v for k, v in pg_record.items() if k in valid_cols}
            if not pg_record:
                continue
            pg_record = {k: (str(v) if isinstance(v, (dict, list, set, bool)) else v)
                         for k, v in pg_record.items()}
            set_clause = ", ".join("{} = %s".format(k) for k in pg_record.keys())
            try:
                cur.execute(
                    "UPDATE {}.{} SET {} WHERE id = %s".format(
                        self.schema_name, sobject.lower(), set_clause
                    ),
                    list(pg_record.values()) + [record_id],
                )
            except Exception:
                self.conn.rollback()
        self.conn.commit()
        cur.close()

        self._fire_triggers("after_update", sobject, records)

        return DmlResult(
            success=True,
            record_ids=[r.get("Id", r.get("id")) for r in records],
        )

    def delete(self, sobject: str, record_ids: list) -> DmlResult:
        """Delete des enregistrements par Id."""
        self._fire_triggers("before_delete", sobject, [{"Id": rid} for rid in record_ids])

        cur = self.conn.cursor()
        for rid in record_ids:
            cur.execute(
                "DELETE FROM {}.{} WHERE id = %s".format(
                    self.schema_name, sobject.lower()
                ),
                [rid],
            )
        self.conn.commit()
        cur.close()

        self._fire_triggers("after_delete", sobject, [{"Id": rid} for rid in record_ids])
        return DmlResult(success=True, record_ids=record_ids)

    # --- Triggers ---

    def add_trigger(self, event: str, sobject: str, callback: Callable):
        if event not in self._triggers:
            self._triggers[event] = {}
        if sobject not in self._triggers[event]:
            self._triggers[event][sobject] = []
        self._triggers[event][sobject].append(callback)

    def _fire_triggers(self, event: str, sobject: str, records: list,
                       old_records: list = None):
        callbacks = self._triggers.get(event, {}).get(sobject, [])
        for cb in callbacks:
            cb(records, old_records=old_records)

    def _generate_id(self, sobject: str) -> str:
        prefix = SOBJECT_PREFIX.get(sobject, "0XX")
        count = self._id_counters.get(sobject, 0) + 1
        self._id_counters[sobject] = count
        return "{}{}".format(prefix, str(count).zfill(12))
