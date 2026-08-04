"""Persistent store for managed ("elliot") sources.

A managed source has no upstream — Elliot IS the system of record. Each
connector gets one SQLite database file holding one table per managed source,
created from the source's declared :class:`~elliot_core.types.source.ManagedColumn`
schema plus four system columns:

* ``_id``          — server-minted row id (uuid4 hex), the handle update/delete
                     tools target.
* ``_owner_id``    — the end user who inserted the row. Drives row-level
                     scoping for ``user_scoped`` sources.
* ``_created_at``  — ISO-8601 UTC insert timestamp.
* ``_updated_at``  — ISO-8601 UTC last-mutation timestamp.

Row-level scoping is enforced HERE, not in the tools: reads filter to the
allowed owner ids and mutations refuse rows outside them, so no authored SQL
or tool mapping can widen a user's access. ``allowed_owner_ids=None`` means
unscoped (the local single-user mode, or a ``user_scoped=False`` shared table).
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog

from elliot_core.errors import ElliotError, NotFoundError
from elliot_core.sql import safe_ident
from elliot_core.types.source import ManagedColumn, SourceConfig
from elliot_core.types.sqlite import ColumnMeta, FlattenedTable, FlattenResult

log = structlog.get_logger(__name__)

# Column names the store owns; a declared column may not collide with them.
SYSTEM_COLUMNS = ("_id", "_owner_id", "_created_at", "_updated_at")

_TYPE_TO_SQLITE: dict[str, str] = {
    "string": "TEXT",
    "integer": "INTEGER",
    "number": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
}

# Env var the hosting layer sets to place the store; default matches the other
# runtime artifacts (.elliot/audit.ndjson, .elliot/observations.db).
MANAGED_DB_ENV = "ELLIOT_MANAGED_DB"
DEFAULT_MANAGED_DB = ".elliot/managed.db"


def managed_db_path() -> str:
    """Resolve the managed-store path from the environment (or the default)."""
    import os

    return os.environ.get(MANAGED_DB_ENV, "").strip() or DEFAULT_MANAGED_DB


def managed_table_name(source: SourceConfig) -> str:
    """The SQLite table a managed source's rows live in."""
    return source.table_name or source.name or source.id


def _column_sqlite_type(col: ManagedColumn) -> Literal["INTEGER", "REAL", "TEXT"]:
    mapped = _TYPE_TO_SQLITE[col.type]
    return mapped if mapped in ("INTEGER", "REAL") else "TEXT"  # type: ignore[return-value]


def managed_flat_table(source: SourceConfig, rows: list[dict[str, Any]]) -> FlattenResult:
    """Shape managed rows for :meth:`SQLiteEngine.load_result`.

    The generic flattener would overwrite each row's ``_id`` with its own
    sequential counter — destroying the very handle update/delete tools
    target — so managed sources build their table meta straight from the
    declared schema instead of inferring it.
    """
    columns = [
        ColumnMeta(name="_id", sqlite_type="TEXT", nullable=False),
        ColumnMeta(name="_owner_id", sqlite_type="TEXT", nullable=False),
        ColumnMeta(name="_created_at", sqlite_type="TEXT"),
        ColumnMeta(name="_updated_at", sqlite_type="TEXT"),
    ] + [ColumnMeta(name=c.name, sqlite_type=_column_sqlite_type(c)) for c in source.columns]
    return FlattenResult(
        primary_table=FlattenedTable(name=managed_table_name(source), columns=columns, rows=rows)
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _bind_value(col: ManagedColumn, value: Any) -> Any:
    """Coerce a validated tool argument to its SQLite representation."""
    if value is None:
        return None
    if col.type == "boolean":
        return 1 if bool(value) else 0
    if isinstance(value, (list, dict, tuple)):
        import json

        return json.dumps(value, default=str)
    return value


class ManagedStore:
    """SQLite-file-backed row store for one connector's managed sources.

    Thread-safe the same way :class:`SQLiteEngine` is: one connection with
    ``check_same_thread=False`` plus an RLock serializing statements.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if self._path != ":memory:":
            # WAL keeps concurrent tool calls from blocking each other on the
            # cloud's shared per-connector store.
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.commit()
        log.info("managed_store.open", path=self._path)

    # ── schema ────────────────────────────────────────────────────────────

    def ensure_table(self, source: SourceConfig) -> None:
        """Create the source's table if missing; add newly declared columns.

        Additive only — a republish that declares a new column ALTERs it in,
        but existing columns (and their data) are never dropped or retyped, so
        app data survives schema evolution.
        """
        self._require_managed(source)
        table = safe_ident(managed_table_name(source))
        cols = self._declared(source)
        with self._lock:
            defs = ", ".join(
                [
                    "_id TEXT PRIMARY KEY",
                    "_owner_id TEXT NOT NULL",
                    "_created_at TEXT",
                    "_updated_at TEXT",
                ]
                + [f"{safe_ident(c.name)} {_TYPE_TO_SQLITE[c.type]}" for c in cols]
            )
            self._conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({defs})")
            existing = {
                row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for c in cols:
                if c.name not in existing:
                    self._conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {safe_ident(c.name)} "
                        f"{_TYPE_TO_SQLITE[c.type]}"
                    )
                    log.info("managed_store.column_added", table=source.table_name, column=c.name)
            index_name = ("idx_" + managed_table_name(source) + "_owner")[:63]
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS {safe_ident(index_name)} ON {table} (_owner_id)"
            )
            self._conn.commit()

    # ── reads ─────────────────────────────────────────────────────────────

    def read_rows(
        self,
        source: SourceConfig,
        allowed_owner_ids: list[str] | None,
    ) -> list[dict[str, Any]]:
        """All rows the caller may see, oldest first.

        ``allowed_owner_ids=None`` (unscoped) or ``user_scoped=False`` returns
        every row; otherwise only rows whose ``_owner_id`` is in the list.
        """
        self.ensure_table(source)
        table = safe_ident(managed_table_name(source))
        sql = f"SELECT * FROM {table}"  # noqa: S608 - identifier via safe_ident
        params: list[Any] = []
        if source.user_scoped and allowed_owner_ids is not None:
            placeholders = ", ".join(["?"] * len(allowed_owner_ids)) or "NULL"
            sql += f" WHERE _owner_id IN ({placeholders})"
            params = list(allowed_owner_ids)
        sql += " ORDER BY _created_at, _id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── mutations ─────────────────────────────────────────────────────────

    def insert_row(
        self,
        source: SourceConfig,
        values: dict[str, Any],
        owner_id: str,
    ) -> dict[str, Any]:
        """Insert one row stamped with ``owner_id``; returns the stored row."""
        self.ensure_table(source)
        cols = {c.name: c for c in self._declared(source)}
        unknown = sorted(set(values) - set(cols))
        if unknown:
            raise ElliotError(
                "UNKNOWN_COLUMN",
                f"Source '{source.id}' has no column(s): {', '.join(unknown)}. "
                f"Declared columns: {', '.join(sorted(cols))}.",
                detail={"unknown": unknown},
            )
        missing = sorted(
            name for name, c in cols.items() if c.required and values.get(name) is None
        )
        if missing:
            raise ElliotError(
                "VALIDATION_REQUIRED",
                f"Missing required column value(s): {', '.join(missing)}.",
                detail={"missing": missing},
            )
        table = safe_ident(managed_table_name(source))
        now = _now_iso()
        row_id = uuid.uuid4().hex
        names = ["_id", "_owner_id", "_created_at", "_updated_at", *values.keys()]
        binds = [row_id, owner_id, now, now] + [_bind_value(cols[n], v) for n, v in values.items()]
        quoted = ", ".join(safe_ident(n) for n in names)
        placeholders = ", ".join(["?"] * len(names))
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",  # noqa: S608
                binds,
            )
            self._conn.commit()
        log.info("managed_store.insert", table=managed_table_name(source), row_id=row_id)
        return self._get_row(source, row_id)

    def update_row(
        self,
        source: SourceConfig,
        row_id: str,
        values: dict[str, Any],
        allowed_owner_ids: list[str] | None,
    ) -> dict[str, Any]:
        """Update columns of one row the caller owns (or was granted write on)."""
        self.ensure_table(source)
        if not values:
            raise ElliotError("VALIDATION_ERROR", "Update needs at least one column value to set.")
        cols = {c.name: c for c in self._declared(source)}
        unknown = sorted(set(values) - set(cols))
        if unknown:
            raise ElliotError(
                "UNKNOWN_COLUMN",
                f"Source '{source.id}' has no column(s): {', '.join(unknown)}.",
                detail={"unknown": unknown},
            )
        table = safe_ident(managed_table_name(source))
        sets = ", ".join(f"{safe_ident(n)} = ?" for n in values) + ", _updated_at = ?"
        binds: list[Any] = [_bind_value(cols[n], v) for n, v in values.items()]
        binds.append(_now_iso())
        where, where_binds = self._row_guard(source, row_id, allowed_owner_ids)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE {table} SET {sets} WHERE {where}",  # noqa: S608
                binds + where_binds,
            )
            self._conn.commit()
        if cur.rowcount == 0:
            raise self._row_missing(source, row_id)
        log.info("managed_store.update", table=managed_table_name(source), row_id=row_id)
        return self._get_row(source, row_id)

    def delete_row(
        self,
        source: SourceConfig,
        row_id: str,
        allowed_owner_ids: list[str] | None,
    ) -> dict[str, Any]:
        """Delete one row the caller owns (or was granted write on)."""
        self.ensure_table(source)
        table = safe_ident(managed_table_name(source))
        where, where_binds = self._row_guard(source, row_id, allowed_owner_ids)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM {table} WHERE {where}",  # noqa: S608
                where_binds,
            )
            self._conn.commit()
        if cur.rowcount == 0:
            raise self._row_missing(source, row_id)
        log.info("managed_store.delete", table=managed_table_name(source), row_id=row_id)
        return {"deleted": True, "_id": row_id}

    # ── helpers ───────────────────────────────────────────────────────────

    def _row_guard(
        self,
        source: SourceConfig,
        row_id: str,
        allowed_owner_ids: list[str] | None,
    ) -> tuple[str, list[Any]]:
        where = "_id = ?"
        binds: list[Any] = [str(row_id)]
        if source.user_scoped and allowed_owner_ids is not None:
            placeholders = ", ".join(["?"] * len(allowed_owner_ids)) or "NULL"
            where += f" AND _owner_id IN ({placeholders})"
            binds.extend(allowed_owner_ids)
        return where, binds

    @staticmethod
    def _row_missing(source: SourceConfig, row_id: str) -> NotFoundError:
        # One error for "not there" and "not yours" — telling them apart would
        # let a caller probe for other users' row ids.
        return NotFoundError(
            f"No row '{row_id}' in source '{source.id}' that you can modify. "
            "Look the row up with a READ tool first — you can only modify rows "
            "you own or were granted write access to."
        )

    def _get_row(self, source: SourceConfig, row_id: str) -> dict[str, Any]:
        table = safe_ident(managed_table_name(source))
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM {table} WHERE _id = ?",  # noqa: S608
                [row_id],
            ).fetchone()
        if row is None:
            raise self._row_missing(source, row_id)
        return dict(row)

    @staticmethod
    def _require_managed(source: SourceConfig) -> None:
        if source.type != "elliot":
            raise ElliotError(
                "INVALID_SOURCE",
                f"Source '{source.id}' is type '{source.type}', not a managed 'elliot' source.",
            )

    @staticmethod
    def _declared(source: SourceConfig) -> list[ManagedColumn]:
        for col in source.columns:
            if col.name.lower() in SYSTEM_COLUMNS or col.name.startswith("_"):
                raise ElliotError(
                    "INVALID_SOURCE",
                    f"Managed column name '{col.name}' is reserved — column names "
                    "may not start with '_' (system columns: "
                    f"{', '.join(SYSTEM_COLUMNS)}).",
                )
        return list(source.columns)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "DEFAULT_MANAGED_DB",
    "MANAGED_DB_ENV",
    "SYSTEM_COLUMNS",
    "ManagedStore",
    "managed_db_path",
    "managed_flat_table",
    "managed_table_name",
]
