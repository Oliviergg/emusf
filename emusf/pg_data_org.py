"""PgDataOrg - DML sur les données Salesforce exportées (schema data).

Contrairement à PgTestOrg (bac à sable), cette org écrit sur l'export réel :
- rollback par défaut : les DML s'accumulent dans une transaction unique,
  annulée en fin de run sauf commit() explicite (flag --commit)
- schéma strict : jamais de CREATE/ALTER — table ou colonne absente → DmlException
- valeurs adaptées aux types réels des colonnes (boolean, numeric, timestamp...)
- Ids générés avec le pod émulateur 'Zz', distinct des pods Salesforce réels
- triggers before/after optionnels (désactivés par défaut)
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime

from .pg_org import PgOrg, sf_to_pg_column
from .dml import (DmlResult, DmlException, SOBJECT_PREFIX, EMUSF_POD,
                  DEFAULT_START_COUNTER, generate_sf_id, decode62)
from .triggers_registry import TriggerMixin


class PgDataOrg(TriggerMixin, PgOrg):
    """Org data avec DML transactionnel sur l'export Salesforce réel."""

    def __init__(self, dsn: str, schema: str = "data", triggers_enabled: bool = False):
        super().__init__(dsn, schema)
        self.conn.autocommit = False  # une seule transaction pour tout le run
        self.triggers_enabled = triggers_enabled
        self._triggers = {}
        self._id_counters = {}
        self.pending_dml = 0  # écritures en attente de commit/rollback

    # --- Transaction ---

    def commit(self):
        """Commit final explicite (flag --commit) : persiste les écritures."""
        self.conn.commit()
        self.pending_dml = 0

    def rollback_all(self):
        """Rollback final (défaut) : annule toutes les écritures du run."""
        self.conn.rollback()
        self.pending_dml = 0

    @contextmanager
    def _savepoint(self):
        """Un statement raté n'avorte que lui-même : les écritures en attente
        et la session survivent."""
        cur = self.conn.cursor()
        cur.execute("SAVEPOINT emusf_stmt")
        try:
            yield
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT emusf_stmt")
            cur.close()
            raise
        else:
            cur.execute("RELEASE SAVEPOINT emusf_stmt")
            cur.close()

    def _on_statement_error(self):
        # No-op : le savepoint a déjà restauré la transaction ; un rollback
        # complet balaierait les écritures en attente.
        pass

    def _execute(self, cq):
        with self._savepoint():
            return super()._execute(cq)

    # --- Validation stricte (le schéma data n'est jamais modifié) ---

    def _validate_and_map(self, op: str, sobject: str, records: list) -> tuple:
        """Vérifie table et colonnes, retourne (table, [records PG adaptés])."""
        table = sobject.lower()
        if table not in self._tables:
            raise DmlException(
                "{} {} : SObject inconnu (table {}.{} absente — "
                "le schéma {} n'est jamais modifié)".format(
                    op, sobject, self.schema_name, table, self.schema_name))
        known = set(self._tables[table])
        pg_records = []
        for record in records:
            pg_record = {}
            for key, value in record.items():
                if key.startswith("_"):
                    continue
                col = sf_to_pg_column(key)
                if col not in known:
                    raise DmlException(
                        "{} {} : champ '{}' inconnu (colonne {}.{}.{} absente — "
                        "le schéma {} n'est jamais modifié)".format(
                            op, sobject, key, self.schema_name, table, col,
                            self.schema_name))
                pg_record[col] = self._adapt_value(table, col, value)
            pg_records.append(pg_record)
        return table, pg_records

    def _adapt_value(self, table: str, col: str, value):
        """Adapte une valeur Python au type PG réel de la colonne."""
        if value is None:
            return None
        dtype = self._column_types.get(table, {}).get(col, "")
        if dtype == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                return value.strip().lower() in ("true", "t", "1", "yes")
            return bool(value)
        if dtype in ("text", "character varying", "character"):
            if isinstance(value, bool):
                return "true" if value else "false"  # convention Salesforce
            if isinstance(value, (dict, list, set)):
                return str(value)
            if not isinstance(value, str):
                return str(value)
            return value
        # numeric / integer / date / timestamp... : psycopg2 + cast PG gèrent
        # int, float, date, datetime et chaînes ISO ; échec de cast → savepoint
        # + DmlException dans le DML appelant
        if isinstance(value, (int, float, date, datetime, str)):
            return value
        return str(value)

    # --- DML (mêmes signatures que PgTestOrg : duck-typing interpréteur) ---

    def insert(self, sobject: str, records: list) -> DmlResult:
        """Insert all-or-nothing dans la transaction en cours."""
        for record in records:
            if "Id" not in record and "id" not in record:
                record["Id"] = self._generate_id(sobject)

        if self.triggers_enabled:
            self._fire_triggers("before_insert", sobject, records)

        table, pg_records = self._validate_and_map("INSERT", sobject, records)
        with self._savepoint():
            cur = self.conn.cursor()
            for i, pg_record in enumerate(pg_records):
                columns = ", ".join(pg_record.keys())
                placeholders = ", ".join(["%s"] * len(pg_record))
                try:
                    cur.execute(
                        "INSERT INTO {}.{} ({}) VALUES ({})".format(
                            self.schema_name, table, columns, placeholders),
                        list(pg_record.values()))
                except Exception as e:
                    cur.close()
                    raise DmlException("INSERT {} ligne {} : {}".format(
                        sobject, i + 1, e)) from e
            cur.close()
        self.pending_dml += len(pg_records)

        if self.triggers_enabled:
            self._fire_triggers("after_insert", sobject, records)

        return DmlResult(
            success=True,
            record_ids=[r.get("Id", r.get("id")) for r in records],
        )

    def update(self, sobject: str, records: list) -> DmlResult:
        """Update all-or-nothing. Chaque record doit avoir un Id."""
        if self.triggers_enabled:
            self._fire_triggers("before_update", sobject, records)

        table, pg_records = self._validate_and_map("UPDATE", sobject, records)
        with self._savepoint():
            cur = self.conn.cursor()
            for i, (record, pg_record) in enumerate(zip(records, pg_records)):
                record_id = record.get("Id", record.get("id"))
                if not record_id:
                    cur.close()
                    raise DmlException(
                        "UPDATE {} ligne {} : Id manquant".format(sobject, i + 1))
                pg_record = {k: v for k, v in pg_record.items() if k != "id"}
                if not pg_record:
                    continue
                set_clause = ", ".join("{} = %s".format(k) for k in pg_record.keys())
                try:
                    cur.execute(
                        "UPDATE {}.{} SET {} WHERE id = %s".format(
                            self.schema_name, table, set_clause),
                        list(pg_record.values()) + [record_id])
                except Exception as e:
                    cur.close()
                    raise DmlException("UPDATE {} ligne {} : {}".format(
                        sobject, i + 1, e)) from e
            cur.close()
        self.pending_dml += len(records)

        if self.triggers_enabled:
            self._fire_triggers("after_update", sobject, records)

        return DmlResult(
            success=True,
            record_ids=[r.get("Id", r.get("id")) for r in records],
        )

    def delete(self, sobject: str, record_ids: list) -> DmlResult:
        """Delete all-or-nothing par Id."""
        if self.triggers_enabled:
            self._fire_triggers("before_delete", sobject,
                                [{"Id": rid} for rid in record_ids])

        table, _ = self._validate_and_map("DELETE", sobject, [])
        with self._savepoint():
            cur = self.conn.cursor()
            for rid in record_ids:
                try:
                    cur.execute(
                        "DELETE FROM {}.{} WHERE id = %s".format(
                            self.schema_name, table),
                        [rid])
                except Exception as e:
                    cur.close()
                    raise DmlException("DELETE {} {} : {}".format(
                        sobject, rid, e)) from e
            cur.close()
        self.pending_dml += len(record_ids)

        if self.triggers_enabled:
            self._fire_triggers("after_delete", sobject,
                                [{"Id": rid} for rid in record_ids])
        return DmlResult(success=True, record_ids=record_ids)

    # --- Génération d'Id sans collision avec les Ids réels ---

    def _generate_id(self, sobject: str) -> str:
        prefix = SOBJECT_PREFIX.get(sobject) or self._infer_prefix(sobject)
        if sobject not in self._id_counters:
            self._id_counters[sobject] = self._seed_counter(sobject, prefix)
        self._id_counters[sobject] += 1
        return generate_sf_id(prefix, EMUSF_POD, self._id_counters[sobject])

    def _infer_prefix(self, sobject: str) -> str:
        """Préfixe inconnu du mapping : lu sur une ligne existante, sinon 0XX."""
        table = sobject.lower()
        if table in self._tables:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT id FROM {}.{} WHERE id IS NOT NULL LIMIT 1".format(
                    self.schema_name, table))
                row = cur.fetchone()
                if row and row[0] and len(row[0]) >= 3:
                    return row[0][:3]
            except Exception:
                pass
            finally:
                cur.close()
        return "0XX"

    def _seed_counter(self, sobject: str, prefix: str) -> int:
        """Reprend le compteur après le plus grand Id émulateur déjà persisté
        (survit aux re-runs avec --commit), sinon compteur de départ."""
        table = sobject.lower()
        if table in self._tables:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    "SELECT max(id) FROM {}.{} WHERE id LIKE %s".format(
                        self.schema_name, table),
                    [prefix + EMUSF_POD + "%"])
                row = cur.fetchone()
                if row and row[0] and len(row[0]) >= 15:
                    return decode62(row[0][5:15])
            except Exception:
                pass
            finally:
                cur.close()
        return DEFAULT_START_COUNTER
