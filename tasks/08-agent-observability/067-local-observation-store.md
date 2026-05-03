# Task 067 — Local SQLite Observation Store

## Goal
Replace the two append-only NDJSON files (`.elliot/audit.ndjson`, `.elliot/sessions.ndjson`) with a single local SQLite database (`.elliot/observations.db`). All tool call records, agent sessions, and session events are written there. The REST endpoints query the DB directly instead of scanning flat files. The Studio gains filtering, date ranges, and real aggregations.

## Why
NDJSON flat files work for a single-day prototype but break quickly:
- Reading the last 20 sessions requires reading the whole file
- You cannot query by date, tool_id, or error without loading everything into memory
- No retention / rotation — files grow forever
- Token efficiency metrics (`/v1/metrics/token-efficiency`) have to re-aggregate on every request

SQLite is already in the Python stdlib (`sqlite3`), needs no migration tooling, and gives the user a single file they can open in any DB browser to inspect their agent traffic.

## File to create

### `packages/connector-runtime/src/elliot_connector_runtime/observation_store.py`

```python
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    UNIQUE NOT NULL,
    started_at    REAL    NOT NULL,
    ended_at      REAL,
    agent_hint    TEXT,
    connector_slug TEXT,
    total_tool_calls     INTEGER DEFAULT 0,
    total_tokens_estimated INTEGER DEFAULT 0,
    total_duration_ms    REAL    DEFAULT 0,
    error_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    REFERENCES agent_sessions(session_id),
    ts            REAL    NOT NULL,
    tool_id       TEXT    NOT NULL,
    arguments     TEXT,          -- JSON blob
    result_row_count   INTEGER DEFAULT 0,
    result_token_estimate INTEGER DEFAULT 0,
    duration_ms   REAL    DEFAULT 0,
    error         TEXT,
    connector_slug TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_id  ON tool_calls(tool_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts       ON tool_calls(ts);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON agent_sessions(started_at);
"""

_RETENTION_DAYS = 30
_MAX_ROWS = 50_000  # hard cap per table


class ObservationStore:
    """Thread-safe SQLite store for all agent observation data."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        with self._connect() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ writes

    def write_tool_call(
        self,
        session_id: str | None,
        tool_id: str,
        arguments: dict,
        result_row_count: int,
        result_token_estimate: int,
        duration_ms: float,
        error: str | None = None,
        connector_slug: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls
                    (session_id, ts, tool_id, arguments,
                     result_row_count, result_token_estimate,
                     duration_ms, error, connector_slug)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    time.time(),
                    tool_id,
                    json.dumps(arguments, default=str),
                    result_row_count,
                    result_token_estimate,
                    round(duration_ms, 2),
                    error,
                    connector_slug,
                ),
            )

    def open_session(
        self,
        session_id: str,
        agent_hint: str | None = None,
        connector_slug: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_sessions
                    (session_id, started_at, agent_hint, connector_slug)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, time.time(), agent_hint, connector_slug),
            )

    def close_session(self, session_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_sessions
                SET
                    ended_at               = ?,
                    total_tool_calls       = (SELECT COUNT(*)  FROM tool_calls WHERE session_id = ? AND error IS NULL),
                    total_tokens_estimated = (SELECT COALESCE(SUM(result_token_estimate), 0) FROM tool_calls WHERE session_id = ?),
                    total_duration_ms      = (SELECT COALESCE(SUM(duration_ms), 0)           FROM tool_calls WHERE session_id = ?),
                    error_count            = (SELECT COUNT(*)  FROM tool_calls WHERE session_id = ? AND error IS NOT NULL)
                WHERE session_id = ?
                """,
                (time.time(), session_id, session_id, session_id, session_id, session_id),
            )

    # ------------------------------------------------------------------ reads

    def recent_sessions(self, n: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions ORDER BY started_at DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_tool_calls(self, n: int = 100, tool_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if tool_id:
                rows = conn.execute(
                    "SELECT * FROM tool_calls WHERE tool_id = ? ORDER BY ts DESC LIMIT ?",
                    (tool_id, n),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tool_calls ORDER BY ts DESC LIMIT ?", (n,)
                ).fetchall()
        return [dict(r) for r in rows]

    def token_efficiency(self) -> list[dict]:
        """Per-tool aggregation used by /v1/metrics/token-efficiency."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    tool_id,
                    COUNT(*)                              AS call_count,
                    AVG(result_token_estimate)            AS avg_tokens,
                    MAX(result_token_estimate)            AS max_tokens,
                    AVG(duration_ms)                      AS avg_duration_ms,
                    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS error_count
                FROM tool_calls
                GROUP BY tool_id
                ORDER BY avg_tokens DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- retention

    def prune(self) -> int:
        """Delete records older than RETENTION_DAYS or beyond MAX_ROWS. Returns rows deleted."""
        cutoff = time.time() - (_RETENTION_DAYS * 86400)
        with self._lock, self._connect() as conn:
            r1 = conn.execute(
                "DELETE FROM tool_calls WHERE ts < ?", (cutoff,)
            ).rowcount
            r2 = conn.execute(
                "DELETE FROM agent_sessions WHERE started_at < ?", (cutoff,)
            ).rowcount
            # Hard cap: keep newest MAX_ROWS
            conn.execute(
                f"""
                DELETE FROM tool_calls WHERE id NOT IN (
                    SELECT id FROM tool_calls ORDER BY ts DESC LIMIT {_MAX_ROWS}
                )
                """
            )
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        return r1 + r2
```

## Replace AuditLog + SessionTracker

`ObservationStore` takes over both responsibilities:

| Old | New |
|---|---|
| `AuditLog.record(...)` | `store.write_tool_call(session_id=None, ...)` |
| `SessionTracker.start_session()` | `store.open_session(session_id, agent_hint)` |
| `SessionTracker.record_tool_call(...)` | `store.write_tool_call(session_id, ...)` |
| `SessionTracker.close_session()` | `store.close_session(session_id)` |
| `AuditLog.tail(n)` | `store.recent_tool_calls(n)` |
| `SessionTracker.tail(n)` | `store.recent_sessions(n)` |

Keep `AuditLog` and `SessionTracker` as thin wrappers that delegate to `ObservationStore` during the transition so task 036 and task 060 tests still pass.

## Update REST endpoints in `server.py`

```python
import os
from .observation_store import ObservationStore

db_path = os.environ.get("ELLIOT_OBSERVATIONS_DB", ".elliot/observations.db")
store = ObservationStore(db_path)

@app.get("/v1/sessions")
async def get_sessions(n: int = 20):
    return store.recent_sessions(n)

@app.get("/v1/audit")
async def get_audit(n: int = 100, tool_id: str | None = None):
    return store.recent_tool_calls(n, tool_id=tool_id)

@app.get("/v1/metrics/token-efficiency")
async def token_efficiency():
    rows = store.token_efficiency()
    return [
        {
            **row,
            "risk": "high" if row["avg_tokens"] > 1000 else "medium" if row["avg_tokens"] > 300 else "low",
            "suggestion": _suggest(row["tool_id"], row["avg_tokens"], row["max_tokens"]),
        }
        for row in rows
    ]

@app.post("/v1/observations/prune")
async def prune_observations():
    deleted = store.prune()
    return {"deleted": deleted}
```

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ELLIOT_OBSERVATIONS_DB` | `.elliot/observations.db` | Path to SQLite file |
| `ELLIOT_RETENTION_DAYS` | `30` | Days to keep records (future: read by `prune()`) |

## What the user gets

- **One file** at `.elliot/observations.db` — open it in TablePlus, DB Browser for SQLite, or DBeaver to inspect every agent call ever made
- **Fast filtered queries** — `GET /v1/audit?tool_id=list_animals` returns only that tool's calls
- **Aggregated metrics** that don't re-scan the whole file on every request
- **Automatic retention** — `prune()` runs on startup and removes anything older than 30 days
- **No extra dependencies** — `sqlite3` is Python stdlib

## Tests

```python
def test_write_and_read_tool_call(tmp_path):
    store = ObservationStore(tmp_path / "obs.db")
    store.write_tool_call(None, "list_animals", {}, 5, 87, 43.0)
    calls = store.recent_tool_calls(10)
    assert len(calls) == 1
    assert calls[0]["tool_id"] == "list_animals"

def test_session_lifecycle(tmp_path):
    store = ObservationStore(tmp_path / "obs.db")
    store.open_session("abc", agent_hint="test")
    store.write_tool_call("abc", "get_pet", {"id": 1}, 1, 22, 12.0)
    store.close_session("abc")
    sessions = store.recent_sessions(5)
    assert sessions[0]["session_id"] == "abc"
    assert sessions[0]["total_tool_calls"] == 1

def test_token_efficiency_aggregation(tmp_path):
    store = ObservationStore(tmp_path / "obs.db")
    store.write_tool_call(None, "list_animals", {}, 10, 200, 50.0)
    store.write_tool_call(None, "list_animals", {}, 10, 400, 60.0)
    metrics = store.token_efficiency()
    row = next(m for m in metrics if m["tool_id"] == "list_animals")
    assert row["call_count"] == 2
    assert row["avg_tokens"] == 300.0

def test_prune_removes_old_records(tmp_path):
    import time
    store = ObservationStore(tmp_path / "obs.db")
    # Insert a record with a very old timestamp
    store._path  # ensure created
    import sqlite3
    conn = sqlite3.connect(store._path)
    conn.execute("INSERT INTO tool_calls (ts, tool_id, duration_ms) VALUES (?, 'old_tool', 1.0)", (1.0,))
    conn.commit()
    conn.close()
    deleted = store.prune()
    assert deleted >= 1
```

## Estimate
4–5 hours
