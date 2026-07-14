"""PgTestOrg - Org de test avec DML contre PostgreSQL (schema isolé, rollback entre tests)."""

from __future__ import annotations

import uuid
from typing import Optional, Callable

from .pg_org import PgOrg, sf_to_pg_column
from .dml import DmlResult, SOBJECT_PREFIX, DEFAULT_POD, DEFAULT_START_COUNTER, generate_sf_id
from .schema import RelationshipMeta

# Mapping types alternatifs → PostgreSQL pour create_sobject()
_TYPE_MAP = {
    "REAL": "DOUBLE PRECISION",
}


class PgTestOrg(PgOrg):
    """
    Org de test : INSERT/UPDATE/DELETE contre un schema PG dédié.
    Supporte les triggers before/after, création dynamique de tables.
    Rollback automatique entre les tests.
    """

    def __init__(self, dsn: str, schema: str = "test"):
        super().__init__(dsn, schema)
        self.conn.autocommit = False  # On contrôle les transactions
        self._triggers = {}
        self._id_counters = {}
        self._dirty_tables = set()  # Tables modified since last truncate
        self._created_tables = set()  # Tables créées dynamiquement (à DROP au cleanup)

    # --- Schema dynamique ---

    def create_sobject(self, name: str, columns: dict):
        """Crée (ou recrée) une table dans le schema test.

        columns: {'Name': 'TEXT', 'Active__c': 'INTEGER DEFAULT 0', ...}
        Les types courants sont mappés vers PG (ex: REAL → DOUBLE PRECISION).
        Drop la table existante pour garantir le bon schéma.
        """
        table = name.lower()
        col_defs = []
        col_names = ["id"]
        for col, dtype in columns.items():
            pg_type = dtype
            for src_type, pg_replacement in _TYPE_MAP.items():
                pg_type = pg_type.replace(src_type, pg_replacement)
            col_defs.append("{} {}".format(col.lower(), pg_type))
            col_names.append(col.lower())

        # Forcer autocommit pour le DDL (évite les locks entre connexions)
        old_autocommit = self.conn.autocommit
        try:
            self.conn.rollback()  # fermer toute transaction ouverte
            self.conn.autocommit = True
            cur = self.conn.cursor()
            cur.execute("DROP TABLE IF EXISTS {}.{} CASCADE".format(
                self.schema_name, table))
            cur.execute("CREATE TABLE {}.{} (id TEXT PRIMARY KEY, {})".format(
                self.schema_name, table, ", ".join(col_defs)))
            cur.close()
        finally:
            self.conn.autocommit = old_autocommit

        self._tables[table] = col_names
        self._created_tables.add(table)

    def register_relationship(
        self,
        plural_name: str,
        child_sobject: str,
        fk_column: str,
        parent_sobject: str,
    ):
        """Enregistre une relation parent-enfant (ex: Account → Contacts)."""
        self.sf_schema.register(
            RelationshipMeta(
                plural_name=plural_name,
                sobject_name=child_sobject,
                fk_column=fk_column,
                parent_sobject=parent_sobject,
            )
        )

    # --- Isolation ---

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
        """Vide uniquement les tables qui ont été modifiées."""
        try:
            self.conn.rollback()
        except Exception:
            pass
        if not self._dirty_tables:
            self._id_counters = {}
            return
        cur = self.conn.cursor()
        # Only truncate tables we actually wrote to
        tables_to_clean = list(self._dirty_tables)
        if tables_to_clean:
            try:
                cur.execute("TRUNCATE {} CASCADE".format(
                    ", ".join("{}.{}".format(self.schema_name, t) for t in tables_to_clean)
                ))
            except Exception:
                self.conn.rollback()
                # Fallback: truncate one by one
                for table in tables_to_clean:
                    try:
                        cur.execute("TRUNCATE {}.{} CASCADE".format(self.schema_name, table))
                    except Exception:
                        self.conn.rollback()
        self.conn.commit()
        cur.close()
        self._dirty_tables = set()
        self._id_counters = {}
        # Drop dynamically created tables (autocommit pour éviter les locks)
        if self._created_tables:
            self.conn.autocommit = True
            cur = self.conn.cursor()
            for table in self._created_tables:
                try:
                    cur.execute("DROP TABLE IF EXISTS {}.{} CASCADE".format(
                        self.schema_name, table))
                except Exception:
                    pass
            cur.close()
            self.conn.autocommit = False
            for table in self._created_tables:
                self._tables.pop(table, None)
            self._created_tables = set()

    # --- DML ---

    def _auto_create_table(self, sobject: str, records: list):
        """Crée automatiquement la table si elle n'existe pas (toutes colonnes TEXT)."""
        table = sobject.lower()
        if table in self._tables:
            return
        cols = {sf_to_pg_column(k): "TEXT" for r in records for k in r.keys()
                if k != "Id" and not k.startswith("_")}
        if not cols:
            return
        self.create_sobject(sobject, {k: v for k, v in cols.items()})

    def _execute(self, cq):
        """Comme PgOrg._execute, mais une table absente renvoie 0 lignes :
        les tables sont créées paresseusement à l'insert, alors que dans
        Salesforce l'objet existe toujours (SELECT avant tout insert = vide)."""
        import psycopg2.errors
        try:
            return super()._execute(cq)
        except psycopg2.errors.UndefinedTable:
            return []

    def _auto_extend_table(self, sobject: str, records: list):
        """Ajoute les colonnes manquantes (TEXT) quand un record porte des
        champs inconnus de la table — miroir de _auto_create_table pour les
        tables existantes (ex: champ posé par un trigger ou un flow)."""
        table = sobject.lower()
        if table not in self._tables:
            return
        known = set(self._tables[table])
        new_cols = []
        for record in records:
            for key in record.keys():
                if key.lower() == "id" or key.startswith("_"):
                    continue
                col = sf_to_pg_column(key)
                if col not in known:
                    new_cols.append(col)
                    known.add(col)
        if not new_cols:
            return
        cur = self.conn.cursor()
        for col in new_cols:
            cur.execute("ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS {} TEXT".format(
                self.schema_name, table, col))
        cur.close()
        self._tables[table].extend(new_cols)

    def insert(self, sobject: str, records: list) -> DmlResult:
        """Insert des enregistrements. Auto-génère les Id. Auto-crée la table si absente."""
        for record in records:
            if "Id" not in record and "id" not in record:
                record["Id"] = self._generate_id(sobject)

        self._fire_triggers("before_insert", sobject, records)

        # Auto-create table if needed (et auto-extend si elle existe déjà)
        self._auto_create_table(sobject, records)
        self._auto_extend_table(sobject, records)
        self._dirty_tables.add(sobject.lower())

        cur = self.conn.cursor()
        for record in records:
            pg_record = {sf_to_pg_column(k): v for k, v in record.items()
                         if not k.startswith("_")}  # skip internal keys
            # Auto-add missing columns (ex: champs ajoutés par un trigger)
            valid_cols = set(self.get_columns(sobject))
            if valid_cols:
                for col in pg_record:
                    if col not in valid_cols:
                        try:
                            cur.execute("ALTER TABLE {}.{} ADD COLUMN {} TEXT".format(
                                self.schema_name, sobject.lower(), col))
                            self.conn.commit()
                            self._tables.setdefault(sobject.lower(), []).append(col)
                            valid_cols.add(col)
                        except Exception:
                            self.conn.rollback()
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
        self._auto_extend_table(sobject, records)
        self._dirty_tables.add(sobject.lower())

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
        self._dirty_tables.add(sobject.lower())

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
        count = self._id_counters.get(sobject, DEFAULT_START_COUNTER) + 1
        self._id_counters[sobject] = count
        return generate_sf_id(prefix, DEFAULT_POD, count)
