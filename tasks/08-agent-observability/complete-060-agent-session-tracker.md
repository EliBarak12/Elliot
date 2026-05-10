# Task 060 — Agent Session Tracker

## Goal
Replace the flat `AuditLog` with a structured `SessionTracker` that groups all MCP events from one agent connection into a single session record. Every tool discovery and tool call is captured with timing, result size, and token estimates.

## Why
The audit log records individual tool calls. It cannot answer: “what did the agent do in this session?”, “how many tools did it discover before calling one?”, “did it retry the same tool?”. Sessions are the unit of agent behaviour.

## File to create

### `packages/connector-runtime/src/elliot_connector_runtime/session_tracker.py`

```python
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal


@dataclass
class SessionEvent:
    ts: float
    type: Literal["tools_list", "tool_call"]
    tool_id: str | None = None
    arguments: dict[str, Any] | None = None
    result_rows: int | None = None
    result_token_estimate: int | None = None
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class AgentSession:
    session_id: str
    started_at: float
    agent_hint: str | None
    events: list[SessionEvent] = field(default_factory=list)

    @property
    def total_tool_calls(self) -> int:
        return sum(1 for e in self.events if e.type == "tool_call")

    @property
    def total_tokens_estimated(self) -> int:
        return sum(e.result_token_estimate or 0 for e in self.events)

    @property
    def total_duration_ms(self) -> float:
        return sum(e.duration_ms for e in self.events)

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.events if e.error)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "agent_hint": self.agent_hint,
            "events": [
                {
                    "ts": e.ts,
                    "type": e.type,
                    "tool_id": e.tool_id,
                    "arguments": e.arguments,
                    "result_rows": e.result_rows,
                    "result_token_estimate": e.result_token_estimate,
                    "duration_ms": round(e.duration_ms, 2),
                    "error": e.error,
                }
                for e in self.events
            ],
            "total_tool_calls": self.total_tool_calls,
            "total_tokens_estimated": self.total_tokens_estimated,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "error_count": self.error_count,
        }


def _estimate_tokens(data: Any) -> int:
    """Rough token estimate: characters / 4."""
    try:
        return max(1, len(json.dumps(data, default=str)) // 4)
    except Exception:
        return 0


class SessionTracker:
    """
    Tracks one agent session per MCP connection.
    Sessions are flushed to NDJSON on close.
    """

    def __init__(self, sessions_path: str | Path) -> None:
        self._path = Path(sessions_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, AgentSession] = {}  # session_id -> session
        self._lock = Lock()

    def start_session(self, agent_hint: str | None = None) -> str:
        session_id = uuid.uuid4().hex[:8]
        with self._lock:
            self._active[session_id] = AgentSession(
                session_id=session_id,
                started_at=time.time(),
                agent_hint=agent_hint,
            )
        return session_id

    def record_tools_list(self, session_id: str, tool_count: int, duration_ms: float) -> None:
        with self._lock:
            session = self._active.get(session_id)
            if session is None:
                return
            session.events.append(SessionEvent(
                ts=time.time(),
                type="tools_list",
                result_rows=tool_count,
                duration_ms=duration_ms,
            ))

    def record_tool_call(
        self,
        session_id: str,
        tool_id: str,
        arguments: dict,
        result_rows: int,
        result_data: Any,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        with self._lock:
            session = self._active.get(session_id)
            if session is None:
                return
            session.events.append(SessionEvent(
                ts=time.time(),
                type="tool_call",
                tool_id=tool_id,
                arguments=arguments,
                result_rows=result_rows,
                result_token_estimate=_estimate_tokens(result_data),
                duration_ms=duration_ms,
                error=error,
            ))

    def close_session(self, session_id: str) -> AgentSession | None:
        with self._lock:
            session = self._active.pop(session_id, None)
        if session is None:
            return None
        line = json.dumps(session.to_dict(), separators=(",", ":")) + "\n"
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        return session

    def tail(self, n: int = 20) -> list[dict]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-n:] if line.strip()]
```

## Wire into `server.py`

```python
import os
from .session_tracker import SessionTracker

sessions_path = os.environ.get("ELLIOT_SESSIONS_LOG", ".elliot/sessions.ndjson")
tracker = SessionTracker(sessions_path)

# On each MCP connection start:
session_id = tracker.start_session(agent_hint=request.headers.get("User-Agent"))

# After tools/list:
tracker.record_tools_list(session_id, tool_count=len(tools), duration_ms=ms)

# After each tools/call:
tracker.record_tool_call(session_id, tool_id, arguments, result_rows, result_data, ms, error)

# On connection close:
tracker.close_session(session_id)
```

## REST endpoint (add to `server.py`)

```python
@app.get("/v1/sessions")
async def get_sessions(n: int = 20) -> list:
    return tracker.tail(n)
```

## Environment variables

| Variable | Default |
|---|---|
| `ELLIOT_SESSIONS_LOG` | `.elliot/sessions.ndjson` |

## Tests

```python
def test_session_full_lifecycle(tmp_path):
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session(agent_hint="test-agent")
    tracker.record_tools_list(sid, tool_count=3, duration_ms=10.0)
    tracker.record_tool_call(sid, "list_animals", {}, 2, [{"id":1},{"id":2}], 43.0)
    session = tracker.close_session(sid)
    assert session.total_tool_calls == 1
    assert session.error_count == 0
    assert session.total_tokens_estimated > 0

    sessions = tracker.tail(1)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == sid
```
