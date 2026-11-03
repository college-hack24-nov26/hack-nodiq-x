#!/usr/bin/env python3
"""
services/pgcompat.py

Compatibility layer for running SQLite-style queries on PostgreSQL.

db.py and auth.py use SQLite syntax, so this module translates the
queries before sending them to PostgreSQL. This avoids having to
change the existing database code.

The main translations are:
    ?                       -> %s
    INSERT OR REPLACE INTO  -> INSERT ... ON CONFLICT DO UPDATE
    INSERT OR IGNORE INTO   -> INSERT ... ON CONFLICT DO NOTHING
    rowid                   -> seq
    REAL                    -> DOUBLE PRECISION
    PRAGMA table_info(t)    -> information_schema query

PGRow provides the same basic access patterns as sqlite3.Row,
including positional and column-name lookups.

Connections use autocommit because the existing application already
calls commit() after writes.

Rate limiting still uses its own SQLite database in
services/rate_limit.py.
"""

import re
import threading

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.errors
except ImportError:
    # PostgreSQL support is optional in SQLite-only environments.
    psycopg2 = None


class PGRow(dict):
    """Allow rows to be accessed by index or column name."""

    def __init__(self, mapping, order):
        super().__init__(mapping)
        self._order = list(order)

    def __getitem__(self, key):
        if isinstance(key, int):
            return dict.__getitem__(self, self._order[key])
        return dict.__getitem__(self, key)

    def keys(self):
        return list(self._order)


class PGCursor:
    """Small wrapper around a psycopg2 cursor."""

    def __init__(self, pg_cursor):
        self._cur = pg_cursor

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        names = [d[0] for d in self._cur.description or []]
        return PGRow(dict(zip(names, row)), names)

    def fetchall(self):
        names = [d[0] for d in self._cur.description or []]
        return [
            PGRow(dict(zip(names, row)), names)
            for row in self._cur.fetchall()
        ]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass


class PGConnection:
    """Expose a SQLite-like interface for a PostgreSQL connection."""

    def __init__(self, dsn):
        if psycopg2 is None:
            raise RuntimeError(
                "psycopg2-binary is not installed — required for the "
                "supabase backend (pip install psycopg2-binary)"
            )

        self._conn = psycopg2.connect(dsn, connect_timeout=10)
        self._conn.autocommit = True

        # Several request threads can use the same connection. Keep
        # database operations serialized so they don't interfere with
        # each other. RLock is needed because some helpers call execute()
        # while the lock is already held.
        self._io_lock = threading.RLock()

    # ------------------------------------------------------------ helpers --

    @staticmethod
    def _translate(sql: str) -> str:
        out = sql

        # Convert SQLite placeholders and rowid references.
        out = out.replace("?", "%s")
        out = re.sub(r"\browid\b", "seq", out)

        # Convert INSERT OR REPLACE into a PostgreSQL upsert.
        m = re.match(
            r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]*)\)\s*"
            r"VALUES\s*\(([^)]*)\)\s*$",
            out,
            re.IGNORECASE,
        )
        if m:
            table, cols, vals = m.groups()
            col_list = [c.strip() for c in cols.split(",") if c.strip()]
            assign = ", ".join(
                f"{c} = EXCLUDED.{c}"
                for c in col_list
                if c.lower() != "id"
            )
            out = (
                f"INSERT INTO {table} ({cols}) VALUES ({vals}) "
                f"ON CONFLICT DO UPDATE SET {assign}"
            )

        elif "OR IGNORE" in out.upper():
            out = re.sub(
                r"INSERT\s+OR\s+IGNORE\s+INTO",
                "INSERT INTO",
                out,
                flags=re.IGNORECASE,
            )
            out = out.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

        return out

    @staticmethod
    def _translate_ddl(script: str) -> list[str]:
        stmts = []

        for raw in re.split(r";\s*(?:\n|$)", script):
            s = raw.strip()
            if not s:
                continue

            if s.upper().startswith("PRAGMA"):
                continue

            s = re.sub(
                r"\bREAL\b",
                "DOUBLE PRECISION",
                s,
                flags=re.IGNORECASE,
            )
            s = re.sub(r"\browid\b", "seq", s, flags=re.IGNORECASE)

            # PostgreSQL uses BIGSERIAL for this SQLite column definition.
            s = re.sub(
                r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
                "BIGSERIAL PRIMARY KEY",
                s,
                flags=re.IGNORECASE,
            )
            stmts.append(s)

        return stmts

    # ----------------------------------------------------- sqlite surface --

    def _pk_columns(self, table: str) -> list[str]:
        """Return the table's primary-key columns."""

        with self._io_lock:
            cached = getattr(self, "_pk_cache", None)
            if cached is None:
                cached = {}
                self._pk_cache = cached

            if table not in cached:
                with self._conn.cursor() as cur:
                    cur.execute(
                        "SELECT kcu.column_name FROM information_schema.table_constraints tc "
                        "JOIN information_schema.key_column_usage kcu "
                        "ON tc.constraint_name = kcu.constraint_name "
                        "AND tc.table_schema = kcu.table_schema "
                        "WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'",
                        (table,),
                    )
                    cached[table] = [r[0] for r in cur.fetchall()]

            return cached[table]

    def execute(self, sql, params=()):
        with self._io_lock:
            stripped = sql.strip()

            if stripped.upper().startswith("PRAGMA"):
                pragma = self._pragma_table_info(stripped)
                if pragma is not None:
                    return pragma
                return PGCursor(_EmptyResult())

            translated = self._translate(sql)

            # Use the primary key as the conflict target for upserts.
            m = re.search(
                r"INSERT\s+INTO\s+(\w+).*ON CONFLICT DO UPDATE",
                translated,
                re.IGNORECASE | re.DOTALL,
            )
            if m and "ON CONFLICT (" not in translated.upper():
                pk = self._pk_columns(m.group(1))
                if pk:
                    translated = translated.replace(
                        "ON CONFLICT DO UPDATE",
                        f"ON CONFLICT ({', '.join(pk)}) DO UPDATE",
                    )

            cur = self._conn.cursor()
            values = []

            for p in params:
                if p is None:
                    values.append(None)
                elif isinstance(p, bool):
                    values.append(int(p))
                elif isinstance(p, (int, float)):
                    # Let PostgreSQL coerce numeric values to the column type.
                    values.append(str(p))
                else:
                    values.append(p)

            try:
                if values:
                    # Escape literal percent signs without changing %s
                    # placeholders used by psycopg2.
                    translated = re.sub(r"%(?!s)", "%%", translated)
                    cur.execute(translated, values)
                else:
                    cur.execute(translated)

            except psycopg2.errors.DuplicateColumn:
                # A concurrent startup may have added the same column.
                cur.close()
                return PGCursor(_EmptyResult())

            return PGCursor(cur)

    def executescript(self, script):
        with self._io_lock:
            for stmt in self._translate_ddl(script):
                with self._conn.cursor() as cur:
                    cur.execute(stmt)
            return True

    def cursor(self):
        return _SQLiteStyleCursor(self)

    def commit(self):
        # Kept for compatibility with the existing SQLite code.
        return True

    def rollback(self):
        with self._io_lock:
            try:
                self._conn.rollback()
            except Exception:
                pass

    def close(self):
        with self._io_lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def table_columns(self, table):
        with self._io_lock:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s",
                    (table,),
                )
                return {r[0] for r in cur.fetchall()}

    def _pragma_table_info(self, sql: str):
        """Handle PRAGMA table_info() using PostgreSQL metadata."""

        with self._io_lock:
            m = re.match(
                r"\s*PRAGMA\s+table_info\((\w+)\)\s*$",
                sql,
                re.IGNORECASE,
            )
            if not m:
                return None

            cols = self.table_columns(m.group(1))

        class _PragmaRow(dict):
            def __getitem__(self, k):
                if k == "name":
                    return dict.__getitem__(self, "name")
                return dict.__getitem__(self, k)

        return PGCursor(
            _PragmaResult([{"name": c} for c in sorted(cols)])
        )

    def set_schema(self, name: str):
        """Switch to a separate schema, creating it if necessary."""

        with self._io_lock:
            with self._conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{name}"')
                cur.execute(f'SET search_path TO "{name}"')


class _PragmaResult:
    def __init__(self, rows):
        self._rows = rows
        self.rowcount = len(rows)
        self.description = [("name",)]

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows = list(self._rows)
        self._rows.clear()
        return [PGRow(r, list(r.keys())) for r in rows]

    def close(self):
        pass

    def ping(self):
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True


class _EmptyResult:
    """Empty result returned for ignored statements."""

    def __init__(self):
        self.rowcount = -1
        self.description = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class _SQLiteStyleCursor:
    """Provide the usual SQLite cursor methods."""

    def __init__(self, conn: PGConnection):
        self._conn = conn

    def execute(self, sql, params=()):
        self._last = self._conn.execute(sql, params)
        return self

    def fetchone(self):
        return self._last.fetchone()

    def fetchall(self):
        return self._last.fetchall()

    @property
    def rowcount(self):
        return self._last.rowcount


class PGPool:
    """Reuse PostgreSQL connections for each schema."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conns: dict[str | None, PGConnection] = {}
        self._lock = threading.Lock()

    def get(self, schema: str | None = None) -> PGConnection:
        with self._lock:
            conn = self._conns.get(schema)

            if conn is not None and not self._alive(conn):
                # Reconnect if the pooled connection is no longer usable.
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None

            if conn is None:
                conn = PGConnection(self._dsn)
                if schema:
                    conn.set_schema(schema)
                self._conns[schema] = conn

            return conn

    @staticmethod
    def _alive(conn: "PGConnection") -> bool:
        # Check the socket without issuing another database query.
        with conn._io_lock:
            try:
                if conn._conn.closed:
                    return False
                conn._conn.fileno()
                return True
            except Exception:
                return False

    def reset(self, schema: str | None = None):
        """Close and remove one connection or all pooled connections."""

        with self._lock:
            if schema is None:
                targets = list(self._conns.values())
                self._conns.clear()
            else:
                targets = (
                    [self._conns.pop(schema)]
                    if schema in self._conns
                    else []
                )

            for conn in targets:
                try:
                    conn.close()
                except Exception:
                    pass