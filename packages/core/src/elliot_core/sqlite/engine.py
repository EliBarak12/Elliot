from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from typing import Any

from elliot_core.errors import ElliotError
from elliot_core.sql import safe_ident
from elliot_core.types.sqlite import FlattenedTable, FlattenResult

# SQLite authorizer action codes that the engine refuses unconditionally.
# Even if validate_tool_sql / safe_ident were bypassed, a sqlite3 authorizer
# fires *during* statement preparation, so it catches ATTACH / DETACH / CREATE
# TRIGGER inside a single statement that smuggled past the regex guard.
_DENIED_ACTIONS: frozenset[int] = frozenset(
    {
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    }
)

# Pragmas the engine itself issues during normal operation. Anything outside
# this allowlist is denied — a tool's SQL has no business toggling
# journal_mode, schema_version, foreign_keys, or anything else at query time.
_ALLOWED_PRAGMAS: frozenset[str] = frozenset(
    {
        "foreign_keys",
        "table_info",
        "table_xinfo",
        "index_list",
        "index_info",
        "index_xinfo",
        "foreign_key_list",
        "database_list",
    }
)


def _authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    _db_name: str | None,
    _source: str | None,
) -> int:
    """sqlite3 ``set_authorizer`` callback. Returns DENY / OK per action.

    Fires for every SQL action during prepare/step, so a single-statement
    ``SELECT ... ATTACH ...`` (if such a parse were possible) or a smuggled
    ``CREATE TRIGGER`` inside an otherwise valid statement is rejected
    before any row reaches the application. The pragma allowlist keeps the
    engine's own ``PRAGMA foreign_keys = ON`` and ``PRAGMA table_info(...)``
    working while denying everything else (e.g. ``PRAGMA writable_schema``,
    ``PRAGMA temp_store``).
    """
    if action in _DENIED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        pragma = (arg1 or "").lower()
        if pragma not in _ALLOWED_PRAGMAS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_OK


def _bindable(value: Any) -> Any:
    """Coerce a Python value to something sqlite3 can bind as a `?` parameter."""
    if value is None or isinstance(value, (str, int, float, bytes)):
        return value
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, default=str)
    return str(value)


def _ingest_value(value: Any) -> Any:
    """Stringify a value for the all-TEXT ingest path, preserving NULLs."""
    if value is None:
        return None
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, default=str)
    return str(value)


class SQLiteEngine:
    """In-memory SQLite wrapper.

    The connection is opened with ``check_same_thread=False`` so it can be
    used across threads (FastMCP threadpool, asyncio executors). A reentrant
    lock serializes every statement: SQLite itself is fine cross-thread, but
    interleaved SAVEPOINT/INSERT sequences from two threads would corrupt each
    other's transactions.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Install the authorizer before any other statement so even
        # initialization is subject to the deny-by-default policy. The
        # bootstrap PRAGMA below is in `_ALLOWED_PRAGMAS`.
        self._conn.set_authorizer(_authorizer)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.commit()

    def load_table(self, table: FlattenedTable, *, commit: bool = True) -> None:
        with self._lock:
            # Identifier validation defends against malicious table/column
            # names (which can arrive from connector definitions). safe_ident
            # raises ElliotError("INVALID_IDENTIFIER") outside the regex.
            quoted_table = safe_ident(table.name)
            self._conn.execute(f"DROP TABLE IF EXISTS {quoted_table}")
            if not table.columns:
                # Zero-column tables arise from empty JSON arrays / all-empty
                # objects (e.g. `"teaserBlocks": []` in nested payloads).
                # SQLite rejects `CREATE TABLE foo ()` with a syntax error
                # near `)`, so emit a placeholder marker column — same shape
                # as ingest() uses.
                self._conn.execute(f"CREATE TABLE {quoted_table} (_empty INTEGER)")
                if commit:
                    self._conn.commit()
                return
            cols = ", ".join(
                f"{safe_ident(c.name)} {c.sqlite_type}{'' if c.nullable else ' NOT NULL'}"
                for c in table.columns
            )
            self._conn.execute(f"CREATE TABLE {quoted_table} ({cols})")
            placeholders = ", ".join(["?"] * len(table.columns))
            col_names = [c.name for c in table.columns]
            self._conn.executemany(
                f"INSERT INTO {quoted_table} VALUES ({placeholders})",
                [tuple(_bindable(row.get(n)) for n in col_names) for row in table.rows],
            )
            if commit:
                self._conn.commit()

    def load_result(self, result: FlattenResult) -> None:
        """Atomically load primary + related tables. Rolls back all on any failure."""
        with self._lock:
            created: list[str] = []
            try:
                self._conn.execute("SAVEPOINT load_result")
                created.append(result.primary_table.name)
                self.load_table(result.primary_table, commit=False)
                for t in result.related_tables:
                    created.append(t.name)
                    self.load_table(t, commit=False)
                self._conn.execute("RELEASE SAVEPOINT load_result")
                self._conn.commit()
            except Exception:
                self._conn.execute("ROLLBACK TO SAVEPOINT load_result")
                self._conn.execute("RELEASE SAVEPOINT load_result")
                # Drop any tables already created in this savepoint window so
                # callers never see partial state after an ingest failure.
                # Names were validated by load_table -> safe_ident; if cleanup
                # is reached we still re-validate defensively.
                for name in created:
                    with contextlib.suppress(sqlite3.Error, ElliotError):
                        self._conn.execute(f"DROP TABLE IF EXISTS {safe_ident(name)}")
                self._conn.commit()
                raise

    def ingest(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        """Load a list of dicts into a SQLite table, inferring columns from the first row.

        Transactional: on any failure the table is rolled back so the database
        is never left with a partial / half-populated table.
        """
        with self._lock:
            quoted_table = safe_ident(table_name)
            try:
                self._conn.execute("SAVEPOINT ingest")
                if not rows:
                    self._conn.execute(f"DROP TABLE IF EXISTS {quoted_table}")
                    self._conn.execute(f"CREATE TABLE {quoted_table} (_empty INTEGER)")
                else:
                    cols = list(rows[0].keys())
                    # Validate each column name. Rejecting bad columns here
                    # means callers can't sneak DDL through dict keys.
                    col_defs = ", ".join(f"{safe_ident(c)} TEXT" for c in cols)
                    self._conn.execute(f"DROP TABLE IF EXISTS {quoted_table}")
                    self._conn.execute(f"CREATE TABLE {quoted_table} ({col_defs})")
                    placeholders = ", ".join(["?"] * len(cols))
                    self._conn.executemany(
                        f"INSERT INTO {quoted_table} VALUES ({placeholders})",
                        [tuple(_ingest_value(row.get(c)) for c in cols) for row in rows],
                    )
                self._conn.execute("RELEASE SAVEPOINT ingest")
                self._conn.commit()
            except Exception:
                self._conn.execute("ROLLBACK TO SAVEPOINT ingest")
                self._conn.execute("RELEASE SAVEPOINT ingest")
                with contextlib.suppress(sqlite3.Error):
                    self._conn.execute(f"DROP TABLE IF EXISTS {quoted_table}")
                self._conn.commit()
                raise

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            try:
                cursor = self._conn.execute(sql, params or {})
                return [dict(row) for row in cursor.fetchall()]
            except sqlite3.Error as exc:
                raise ElliotError("INVALID_SQL", str(exc)) from exc

    def get_table_names(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return [row[0] for row in rows]

    def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        quoted_table = safe_ident(table_name)
        with self._lock:
            rows = self._conn.execute(f"PRAGMA table_info({quoted_table})").fetchall()
        return [dict(row) for row in rows]

    def get_table_stats(self, table_name: str) -> dict[str, int]:
        quoted_table = safe_ident(table_name)
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
        return {"row_count": row[0]}

    def profile_column(self, table_name: str, col: str) -> dict[str, Any]:
        quoted_table = safe_ident(table_name)
        quoted_col = safe_ident(col)
        sql = f"""
            SELECT
                MIN({quoted_col}) as min_val,
                MAX({quoted_col}) as max_val,
                SUM(CASE WHEN {quoted_col} IS NULL THEN 1 ELSE 0 END) as null_count,
                COUNT(DISTINCT {quoted_col}) as distinct_count
            FROM {quoted_table}
        """
        with self._lock:
            row = dict(self._conn.execute(sql).fetchone())
            top = self._conn.execute(
                f"SELECT {quoted_col}, COUNT(*) as n FROM {quoted_table} "
                f"GROUP BY {quoted_col} ORDER BY n DESC LIMIT 5"
            ).fetchall()
        row["top_values"] = [r[0] for r in top]
        return row

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()
