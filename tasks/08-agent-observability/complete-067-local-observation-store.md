# Task 067 — Observation Store (SQLite default / MySQL optional)

## Goal
Replace the two append-only NDJSON files (`.elliot/audit.ndjson`, `.elliot/sessions.ndjson`) with a single **SQLAlchemy-backed observation store** that works against **SQLite out of the box** and against a **remote MySQL** when the user sets `ELLIOT_DB_URL`.

All tool call records, agent sessions, and aggregation queries go through this store. The REST endpoints query it directly. The Studio gains filtering, date ranges, and real aggregations.

## Why SQLAlchemy Core (not raw sqlite3)
- One codebase runs against both SQLite and MySQL — no two code paths, no schema rewrites
- Connection pooling, reconnect logic, and dialect differences are handled by SQLAlchemy
- The user upgrades from local to remote by changing one env var, nothing else
- `sqlalchemy` is already common in the Python ecosystem; `pymysql` is the pure-Python MySQL driver (no C compiler needed)

## Dependencies to add

```toml
# packages/connector-runtime/pyproject.toml
[project]
dependencies = [
    "sqlalchemy>=2.0",
    "pymysql>=1.1",          # MySQL driver; only used when DB_URL is mysql://
    # existing deps ...
]
```

## File to create

### `packages/connector-runtime/src/elliot_connector_runtime/observation_store.py`

```python
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import (
    Column, Float, Integer, String, Text,
    create_engine, text,
)
from sqlalchemy.orm import DeclarativeBase, Session


_RETENTION_DAYS = 30
_MAX_ROWS = 50_000


class _Base(DeclarativeBase):
    pass


class _AgentSession(_Base):
    __tablename__ = "agent_sessions"
    id                      = Column(Integer, primary_key=True, autoincrement=True)
    session_id              = Column(String(32), unique=True, nullable=False, index=True)
    started_at              = Column(Float,  nullable=False)
    ended_at                = Column(Float)
    agent_hint              = Column(String(255))
    connector_slug          = Column(String(128))
    total_tool_calls        = Column(Integer, default=0)
    total_tokens_estimated  = Column(Integer, default=0)
    total_duration_ms       = Column(Float,   default=0)
    error_count             = Column(Integer, default=0)


class _ToolCall(_Base):
    __tablename__ = "tool_calls"
    id                      = Column(Integer, primary_key=True, autoincrement=True)
    session_id              = Column(String(32), index=True)
    ts                      = Column(Float,  nullable=False, index=True)
    tool_id                 = Column(String(128), nullable=False, index=True)
    arguments               = Column(Text)        # JSON blob
    result_row_count        = Column(Integer, default=0)
    result_token_estimate   = Column(Integer, default=0)
    duration_ms             = Column(Float,   default=0)
    error                   = Column(Text)
    connector_slug          = Column(String(128))


class ObservationStore:
    """
    Dual-backend observation store.

    SQLite (default):
        store = ObservationStore()                          # uses .elliot/observations.db
        store = ObservationStore("sqlite:////tmp/test.db")  # absolute path

    MySQL (remote):
        store = ObservationStore("mysql+pymysql://user:pass@host:3306/elliot")
    """

    def __init__(self, db_url: str = "sqlite:///.elliot/observations.db") -> None:
        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        self._engine = create_engine(
            db_url,
            pool_pre_ping=True,     # detect dropped connections (important for remote MySQL)
            connect_args=connect_args,
        )
        _Base.metadata.create_all(self._engine)

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
        with Session(self._engine) as db:
            db.add(_ToolCall(
                session_id=session_id,
                ts=time.time(),
                tool_id=tool_id,
                arguments=json.dumps(arguments, default=str),
                result_row_count=result_row_count,
                result_token_estimate=result_token_estimate,
                duration_ms=round(duration_ms, 2),
                error=error,
                connector_slug=connector_slug,
            ))
            db.commit()

    def open_session(
        self,
        session_id: str,
        agent_hint: str | None = None,
        connector_slug: str | None = None,
    ) -> None:
        with Session(self._engine) as db:
            existing = db.get(_AgentSession, session_id)
            if existing is None:
                db.add(_AgentSession(
                    session_id=session_id,
                    started_at=time.time(),
                    agent_hint=agent_hint,
                    connector_slug=connector_slug,
                ))
                db.commit()

    def close_session(self, session_id: str) -> None:
        with Session(self._engine) as db:
            session = db.query(_AgentSession).filter_by(session_id=session_id).first()
            if session is None:
                return
            calls = db.query(_ToolCall).filter_by(session_id=session_id).all()
            session.ended_at              = time.time()
            session.total_tool_calls      = sum(1 for c in calls if not c.error)
            session.total_tokens_estimated = sum(c.result_token_estimate or 0 for c in calls)
            session.total_duration_ms     = sum(c.duration_ms or 0 for c in calls)
            session.error_count           = sum(1 for c in calls if c.error)
            db.commit()

    # ------------------------------------------------------------------ reads

    def recent_sessions(self, n: int = 20) -> list[dict]:
        with Session(self._engine) as db:
            rows = (
                db.query(_AgentSession)
                .order_by(_AgentSession.started_at.desc())
                .limit(n)
                .all()
            )
        return [_row_to_dict(r) for r in rows]

    def recent_tool_calls(
        self, n: int = 100, tool_id: str | None = None
    ) -> list[dict]:
        with Session(self._engine) as db:
            q = db.query(_ToolCall).order_by(_ToolCall.ts.desc())
            if tool_id:
                q = q.filter(_ToolCall.tool_id == tool_id)
            rows = q.limit(n).all()
        return [_row_to_dict(r) for r in rows]

    def token_efficiency(self) -> list[dict]:
        """Per-tool aggregation for /v1/metrics/token-efficiency."""
        with Session(self._engine) as db:
            rows = db.execute(text("""
                SELECT
                    tool_id,
                    COUNT(*)                                     AS call_count,
                    AVG(result_token_estimate)                   AS avg_tokens,
                    MAX(result_token_estimate)                   AS max_tokens,
                    AVG(duration_ms)                             AS avg_duration_ms,
                    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS error_count
                FROM tool_calls
                GROUP BY tool_id
                ORDER BY avg_tokens DESC
            """)).fetchall()
        return [dict(r._mapping) for r in rows]

    # --------------------------------------------------------------- retention

    def prune(self) -> int:
        """Delete records older than RETENTION_DAYS. Returns total rows deleted."""
        cutoff = time.time() - (_RETENTION_DAYS * 86400)
        with Session(self._engine) as db:
            r1 = db.query(_ToolCall).filter(_ToolCall.ts < cutoff).delete()
            r2 = db.query(_AgentSession).filter(_AgentSession.started_at < cutoff).delete()
            db.commit()
        return r1 + r2


def _row_to_dict(row: Any) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
```

## Wire into `server.py`

```python
import os
from .observation_store import ObservationStore

# SQLite by default; point at MySQL with ELLIOT_DB_URL
db_url = os.environ.get("ELLIOT_DB_URL", "sqlite:///.elliot/observations.db")
store = ObservationStore(db_url)

# Run retention on startup (non-blocking is fine for local SQLite)
import threading
threading.Thread(target=store.prune, daemon=True).start()

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
    return {"deleted": store.prune()}
```

## Environment variables

| Variable | Default | Example (MySQL) |
|---|---|---|
| `ELLIOT_DB_URL` | `sqlite:///.elliot/observations.db` | `mysql+pymysql://user:pass@db.myhost.com:3306/elliot` |

The secret in the MySQL URL should use the `{{ env:VAR }}` pattern from task 066:
```
ELLIOT_DB_URL=mysql+pymysql://{{ env:DB_USER }}:{{ env:DB_PASS }}@db.myhost.com:3306/elliot
```

## Migration path for users

```
# Start: local SQLite (zero config)
# Just run the server, .elliot/observations.db is created automatically.

# Later: switch to remote MySQL
# 1. Create the database:  CREATE DATABASE elliot CHARACTER SET utf8mb4;
# 2. Set the env var:       ELLIOT_DB_URL=mysql+pymysql://user:pass@host/elliot
# 3. Restart the runtime.  Tables are auto-created on first connection.
```

No migration script needed — `_Base.metadata.create_all()` is idempotent.

## Replace AuditLog + SessionTracker

| Old | New |
|---|---|
| `AuditLog.record(...)` | `store.write_tool_call(session_id=None, ...)` |
| `SessionTracker.start_session()` | `store.open_session(session_id, agent_hint)` |
| `SessionTracker.record_tool_call(...)` | `store.write_tool_call(session_id, ...)` |
| `SessionTracker.close_session()` | `store.close_session(session_id)` |
| `AuditLog.tail(n)` | `store.recent_tool_calls(n)` |
| `SessionTracker.tail(n)` | `store.recent_sessions(n)` |

Keep `AuditLog` and `SessionTracker` as thin wrappers delegating to `ObservationStore` so existing task 036 and task 060 tests still pass without changes.

## Tests

```python
import pytest
from elliot_connector_runtime.observation_store import ObservationStore

@pytest.fixture
def store(tmp_path):
    return ObservationStore(f"sqlite:///{tmp_path}/obs.db")

def test_write_and_read_tool_call(store):
    store.write_tool_call(None, "list_animals", {}, 5, 87, 43.0)
    calls = store.recent_tool_calls(10)
    assert len(calls) == 1
    assert calls[0]["tool_id"] == "list_animals"

def test_session_lifecycle(store):
    store.open_session("abc", agent_hint="test")
    store.write_tool_call("abc", "get_pet", {"id": 1}, 1, 22, 12.0)
    store.close_session("abc")
    sessions = store.recent_sessions(5)
    assert sessions[0]["session_id"] == "abc"
    assert sessions[0]["total_tool_calls"] == 1

def test_token_efficiency_aggregation(store):
    store.write_tool_call(None, "list_animals", {}, 10, 200, 50.0)
    store.write_tool_call(None, "list_animals", {}, 10, 400, 60.0)
    metrics = store.token_efficiency()
    row = next(m for m in metrics if m["tool_id"] == "list_animals")
    assert row["call_count"] == 2
    assert row["avg_tokens"] == 300.0

def test_prune(store):
    from sqlalchemy.orm import Session
    from elliot_connector_runtime.observation_store import _ToolCall
    with Session(store._engine) as db:
        db.add(_ToolCall(ts=1.0, tool_id="old", duration_ms=1.0))
        db.commit()
    deleted = store.prune()
    assert deleted >= 1

def test_filtered_tool_calls(store):
    store.write_tool_call(None, "tool_a", {}, 1, 10, 5.0)
    store.write_tool_call(None, "tool_b", {}, 2, 20, 6.0)
    calls = store.recent_tool_calls(10, tool_id="tool_a")
    assert all(c["tool_id"] == "tool_a" for c in calls)
```

## Estimate
4–5 hours
