from __future__ import annotations

import sqlite3
from typing import Any

from elliot_core.types.sqlite import FlattenedTable, FlattenResult


class SQLiteEngine:
    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.commit()

    def load_table(self, table: FlattenedTable) -> None:
        cols = ", ".join(
            f'"{c.name}" {c.sqlite_type}{"" if c.nullable else " NOT NULL"}' for c in table.columns
        )
        self._conn.execute(f'DROP TABLE IF EXISTS "{table.name}"')
        self._conn.execute(f'CREATE TABLE "{table.name}" ({cols})')
        placeholders = ", ".join(["?"] * len(table.columns))
        col_names = [c.name for c in table.columns]
        self._conn.executemany(
            f'INSERT INTO "{table.name}" VALUES ({placeholders})',
            [tuple(row.get(n) for n in col_names) for row in table.rows],
        )
        self._conn.commit()

    def load_result(self, result: FlattenResult) -> None:
        self.load_table(result.primary_table)
        for t in result.related_tables:
            self.load_table(t)

    def ingest(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        """Load a list of dicts into a SQLite table, inferring columns from the first row."""
        if not rows:
            self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            self._conn.execute(f'CREATE TABLE "{table_name}" (_empty INTEGER)')
            self._conn.commit()
            return
        cols = list(rows[0].keys())
        col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
        self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        self._conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')
        placeholders = ", ".join(["?"] * len(cols))
        self._conn.executemany(
            f'INSERT INTO "{table_name}" VALUES ({placeholders})',
            [
                tuple(str(row.get(c)) if row.get(c) is not None else None for c in cols)
                for row in rows
            ],
        )
        self._conn.commit()

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cursor = self._conn.execute(sql, params or {})
        return [dict(row) for row in cursor.fetchall()]

    def get_table_names(self) -> list[str]:
        rows = self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return [row[0] for row in rows]

    def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        return [dict(row) for row in rows]

    def get_table_stats(self, table_name: str) -> dict[str, int]:
        row = self._conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
        return {"row_count": row[0]}

    def profile_column(self, table_name: str, col: str) -> dict[str, Any]:
        sql = f"""
            SELECT
                MIN("{col}") as min_val,
                MAX("{col}") as max_val,
                SUM(CASE WHEN "{col}" IS NULL THEN 1 ELSE 0 END) as null_count,
                COUNT(DISTINCT "{col}") as distinct_count
            FROM "{table_name}"
        """
        row = dict(self._conn.execute(sql).fetchone())
        top = self._conn.execute(
            f'SELECT "{col}", COUNT(*) as n FROM "{table_name}" '
            f'GROUP BY "{col}" ORDER BY n DESC LIMIT 5'
        ).fetchall()
        row["top_values"] = [r[0] for r in top]
        return row

    def close(self) -> None:
        self._conn.close()
