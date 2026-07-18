"""Shim psycopg2 → sqlite3 pour exécuter emusf sans PostgreSQL (Pyodide).

Émule le sous-ensemble de l'API psycopg2 utilisé par emusf (PgOrg/PgTestOrg) :
    - psycopg2.connect(dsn) / Connection.autocommit / commit / rollback
    - Connection.cursor(cursor_factory=RealDictCursor)
    - psycopg2.extras.RealDictCursor
    - psycopg2.errors.UndefinedTable / UndefinedColumn

Le SQL "PostgreSQL" émis par emusf est traduit à la volée vers SQLite :
    - placeholders %s → ?
    - schémas PG (test.account) → bases ATTACH-ées en mémoire
    - information_schema.columns / pg_tables → sqlite_master + PRAGMA
    - TRUNCATE a, b CASCADE → DELETE FROM ...
    - DROP TABLE ... CASCADE / ADD COLUMN IF NOT EXISTS
    - ILIKE → LIKE (le LIKE SQLite est insensible à la casse en ASCII)
    - (col)::boolean → fonction SQL pg_bool() enregistrée côté Python

Ce module est destiné au navigateur (Pyodide) mais fonctionne sous CPython :
il permet aussi de lancer la suite pytest sans serveur PostgreSQL.
"""

from __future__ import annotations

import datetime
import re
import sqlite3

from . import errors
from . import extras
from . import extensions  # noqa: F401 — compat import
from .errors import (  # noqa: F401 — API psycopg2
    Error, Warning, InterfaceError, DatabaseError, DataError,
    OperationalError, IntegrityError, InternalError, ProgrammingError,
    NotSupportedError,
)

__version__ = "2.9.0 (emusf sqlite shim)"

apilevel = "2.0"
threadsafety = 2
paramstyle = "pyformat"

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

# Schéma qualifié après un mot-clé introduisant un nom de table
_SCHEMA_REF = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+(?:NOT\s+)?EXISTS)?)\s+"
    r"({i})\.({i})".format(i=_IDENT),
    re.IGNORECASE,
)

_TRUNCATE = re.compile(r"^\s*TRUNCATE\s+(.*?)(\s+CASCADE)?\s*$",
                       re.IGNORECASE | re.DOTALL)
_ADD_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+({i})\.({i})\s+ADD\s+COLUMN\s+"
    r"(IF\s+NOT\s+EXISTS\s+)?({i})\s+(.*)$".format(i=_IDENT),
    re.IGNORECASE | re.DOTALL,
)
_INFO_SCHEMA_COLS = re.compile(r"information_schema\.columns", re.IGNORECASE)
_PG_TABLES = re.compile(r"\bpg_tables\b", re.IGNORECASE)
_BOOL_CAST = re.compile(r"\(({i}(?:\.{i})?)\)::boolean".format(i=_IDENT),
                        re.IGNORECASE)
_ANY_CAST = re.compile(r"::({i})".format(i=_IDENT))
_COUNT_STAR = re.compile(r"^(\s*SELECT\s+)COUNT\(\*\)(\s+FROM\b)",
                         re.IGNORECASE)
_NO_SUCH_COLUMN = re.compile(r"no such column:?\s+([\w.\"]+)", re.IGNORECASE)
_HAS_NO_COLUMN = re.compile(r"has no column named\s+([\w\"]+)", re.IGNORECASE)


def _pg_bool(value):
    """Équivalent SQLite de ::boolean PostgreSQL (colonne TEXT/INT/BOOL)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in ("t", "true", "1", "yes", "on", "y"):
        return 1
    if text in ("f", "false", "0", "no", "off", "n", ""):
        return 0
    return None


def _adapt_param(value):
    """Convertit un paramètre psycopg2 en valeur acceptée par sqlite3."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, (dict, list, set, tuple)):
        return str(value)
    return value


class Connection:
    """Connexion psycopg2-like adossée à une base SQLite en mémoire."""

    def __init__(self, dsn: str = ""):
        self.dsn = dsn
        self._db = sqlite3.connect(":memory:", isolation_level=None,
                                   check_same_thread=False)
        self._db.create_function("pg_bool", 1, _pg_bool)
        self._schemas: set[str] = set()
        self._autocommit = False
        self._in_txn = False
        self.closed = 0

    # --- API psycopg2 ---

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool):
        if self._in_txn:
            # psycopg2 refuse le changement en pleine transaction
            raise ProgrammingError(
                "set_session cannot be used inside a transaction")
        self._autocommit = bool(value)

    def cursor(self, name=None, cursor_factory=None):
        if cursor_factory is extras.RealDictCursor:
            return extras.RealDictCursor(self)
        return Cursor(self)

    def commit(self):
        if self._in_txn:
            self._db.execute("COMMIT")
            self._in_txn = False

    def rollback(self):
        if self._in_txn:
            self._db.execute("ROLLBACK")
            self._in_txn = False

    def close(self):
        try:
            self.rollback()
        except Exception:
            pass
        self._db.close()
        self.closed = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    # --- Interne ---

    def _ensure_schema(self, name: str):
        """ATTACH une base mémoire pour émuler un schéma PostgreSQL."""
        name = name.lower()
        if name in self._schemas or name in ("main", "temp", "sqlite_master"):
            return
        # ATTACH est interdit dans une transaction ouverte
        was_in_txn = self._in_txn
        if was_in_txn:
            self._db.execute("COMMIT")
            self._in_txn = False
        self._db.execute("ATTACH DATABASE ':memory:' AS {}".format(name))
        self._schemas.add(name)
        if was_in_txn:
            self._db.execute("BEGIN")
            self._in_txn = True

    def _begin_if_needed(self):
        if not self._autocommit and not self._in_txn:
            self._db.execute("BEGIN")
            self._in_txn = True

    def _raw_execute(self, sql: str, params):
        try:
            return self._db.execute(sql, params)
        except sqlite3.OperationalError as e:
            raise _map_operational_error(e) from e
        except sqlite3.IntegrityError as e:
            raise errors.UniqueViolation(str(e)) from e
        except sqlite3.Error as e:
            raise DatabaseError(str(e)) from e


def _map_operational_error(e: sqlite3.OperationalError):
    msg = str(e)
    low = msg.lower()
    if "no such table" in low:
        table = msg.split(":", 1)[-1].strip()
        return errors.UndefinedTable(
            'relation "{}" does not exist'.format(table))
    m = _NO_SUCH_COLUMN.search(msg) or _HAS_NO_COLUMN.search(msg)
    if m:
        # t0.foo → foo, pour coller au format d'erreur PostgreSQL
        col = m.group(1).strip('"').rsplit(".", 1)[-1]
        return errors.UndefinedColumn(
            'column "{}" does not exist'.format(col))
    if "duplicate column name" in low:
        return errors.DuplicateColumn(msg)
    return OperationalError(msg)


class Cursor:
    """Curseur psycopg2-like : traduit le SQL PG vers SQLite à la volée."""

    as_dict = False

    def __init__(self, connection: Connection):
        self.connection = connection
        self._cursor = None
        self._prefetched = None  # résultats synthétiques (information_schema…)
        self.rowcount = -1
        self.description = None
        self.closed = False

    # --- Exécution ---

    def execute(self, sql: str, params=None):
        conn = self.connection
        params = [_adapt_param(p) for p in (params or [])]
        self._prefetched = None
        self._cursor = None
        self.description = None
        self.rowcount = -1

        # Requêtes catalogue → synthèse depuis sqlite_master / PRAGMA
        if _INFO_SCHEMA_COLS.search(sql):
            self._prefetched = self._information_schema_columns(params)
            self.rowcount = len(self._prefetched)
            return
        if _PG_TABLES.search(sql):
            self._prefetched = self._pg_tables(params)
            self.rowcount = len(self._prefetched)
            return

        # TRUNCATE a.b, c.d [CASCADE] → DELETE FROM
        m = _TRUNCATE.match(sql)
        if m:
            total = 0
            for target in m.group(1).split(","):
                target = target.strip()
                if not target:
                    continue
                self._attach_for(target)
                conn._begin_if_needed()
                cur = conn._raw_execute("DELETE FROM {}".format(target), [])
                total += cur.rowcount
            self.rowcount = total
            return

        # ALTER TABLE ... ADD COLUMN [IF NOT EXISTS] col TYPE
        m = _ADD_COLUMN.match(sql)
        if m:
            schema, table, if_not_exists, column, col_type = (
                m.group(1).lower(), m.group(2).lower(), m.group(3),
                m.group(4).lower(), m.group(5))
            conn._ensure_schema(schema)
            existing = {r[1].lower() for r in conn._db.execute(
                "PRAGMA {}.table_info({})".format(schema, table))}
            if column in existing:
                if if_not_exists:
                    self.rowcount = 0
                    return
                raise errors.DuplicateColumn(
                    'column "{}" of relation "{}" already exists'.format(
                        column, table))
            conn._begin_if_needed()
            conn._raw_execute("ALTER TABLE {}.{} ADD COLUMN {} {}".format(
                schema, table, column, _translate_types(col_type)), [])
            self.rowcount = 0
            return

        translated = self._translate(sql)
        conn._begin_if_needed()
        self._cursor = conn._raw_execute(translated, params)
        self.rowcount = self._cursor.rowcount
        if self._cursor.description:
            self.description = [(d[0], None, None, None, None, None, None)
                                for d in self._cursor.description]

    def _translate(self, sql: str) -> str:
        conn = self.connection
        # ATTACH des schémas référencés (FROM test.account, INTO data.x…)
        for m in _SCHEMA_REF.finditer(sql):
            conn._ensure_schema(m.group(1))
        sql = sql.replace("%s", "?")
        sql = re.sub(r"\bILIKE\b", "LIKE", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s+CASCADE\b", "", sql, flags=re.IGNORECASE)
        sql = _BOOL_CAST.sub(r"pg_bool(\1)", sql)
        sql = _ANY_CAST.sub("", sql)  # autres casts ::type → no-op
        sql = _COUNT_STAR.sub(r"\1COUNT(*) AS count\2", sql)
        sql = _translate_types(sql)
        return sql

    def _attach_for(self, qualified: str):
        if "." in qualified:
            self.connection._ensure_schema(qualified.split(".", 1)[0])

    # --- Catalogue ---

    def _information_schema_columns(self, params):
        """(table_name, column_name, data_type) pour un schéma donné."""
        schema = (params[0] if params else "main").lower()
        conn = self.connection
        try:
            conn._ensure_schema(schema)
        except Exception:
            return []
        rows = []
        tables = conn._db.execute(
            "SELECT name FROM {}.sqlite_master WHERE type = 'table' "
            "ORDER BY name".format(schema)).fetchall()
        for (table,) in tables:
            for cid, name, col_type, *_ in conn._db.execute(
                    "PRAGMA {}.table_info({})".format(schema, table)):
                rows.append((table, name, (col_type or "text").lower()))
        return rows

    def _pg_tables(self, params):
        schema = (params[0] if params else "main").lower()
        conn = self.connection
        try:
            conn._ensure_schema(schema)
        except Exception:
            return []
        return conn._db.execute(
            "SELECT name FROM {}.sqlite_master WHERE type = 'table' "
            "ORDER BY name".format(schema)).fetchall()

    # --- Fetch ---

    def _rows(self, raw_rows):
        if self.as_dict and self._cursor is not None:
            cols = [d[0] for d in (self._cursor.description or [])]
            return [extras.RealDictRow(zip(cols, row)) for row in raw_rows]
        return raw_rows

    def fetchone(self):
        if self._prefetched is not None:
            return self._prefetched.pop(0) if self._prefetched else None
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._rows([row])[0]

    def fetchall(self):
        if self._prefetched is not None:
            rows, self._prefetched = self._prefetched, []
            return rows
        if self._cursor is None:
            return []
        return self._rows(self._cursor.fetchall())

    def fetchmany(self, size=None):
        if self._prefetched is not None:
            size = size or len(self._prefetched)
            rows, self._prefetched = (self._prefetched[:size],
                                      self._prefetched[size:])
            return rows
        if self._cursor is None:
            return []
        return self._rows(self._cursor.fetchmany(size or 1))

    def close(self):
        self.closed = True
        self._cursor = None
        self._prefetched = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row


# Mapping types PG → SQLite (SQLite accepte presque tout, mais on normalise)
_TYPE_REPLACEMENTS = [
    (re.compile(r"\bDOUBLE\s+PRECISION\b", re.IGNORECASE), "REAL"),
    (re.compile(r"\bBIGINT\b", re.IGNORECASE), "INTEGER"),
    (re.compile(r"\bSERIAL\b", re.IGNORECASE), "INTEGER"),
    (re.compile(r"\bTIMESTAMPTZ\b", re.IGNORECASE), "TEXT"),
    (re.compile(r"\bTIMESTAMP(\s+WITH(?:OUT)?\s+TIME\s+ZONE)?\b",
                re.IGNORECASE), "TEXT"),
]


def _translate_types(sql: str) -> str:
    for pattern, replacement in _TYPE_REPLACEMENTS:
        sql = pattern.sub(replacement, sql)
    return sql


def connect(dsn=None, **kwargs) -> Connection:
    """Ouvre une 'connexion' — la DSN PostgreSQL est acceptée et ignorée."""
    return Connection(dsn or "")
