"""Structured per-agent-session tracking for the connector runtime."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)


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
    agent_identity: dict[str, Any] | None = None
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "agent_hint": self.agent_hint,
            "agent_identity": self.agent_identity,
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
        self._active: dict[str, AgentSession] = {}
        self._lock = Lock()

    def start_session(
        self,
        agent_hint: str | None = None,
        session_id: str | None = None,
        agent_identity: dict[str, Any] | None = None,
    ) -> str:
        """Create a new session. If session_id is given, use it as the key; otherwise generate one."""
        sid = session_id or uuid.uuid4().hex[:8]
        with self._lock:
            self._active[sid] = AgentSession(
                session_id=sid,
                started_at=time.time(),
                agent_hint=agent_hint,
                agent_identity=agent_identity,
            )
        log.info(
            "session.started",
            session_id=sid,
            agent_hint=agent_hint,
            agent_client=(agent_identity or {}).get("client"),
            agent_model=(agent_identity or {}).get("model"),
        )
        return sid

    def get_or_start_session(
        self,
        session_id: str,
        agent_hint: str | None = None,
        agent_identity: dict[str, Any] | None = None,
    ) -> str:
        """Return session_id if already active; otherwise create it."""
        with self._lock:
            if session_id in self._active:
                return session_id
        return self.start_session(
            agent_hint=agent_hint,
            session_id=session_id,
            agent_identity=agent_identity,
        )

    def record_tools_list(self, session_id: str, tool_count: int, duration_ms: float) -> None:
        with self._lock:
            session = self._active.get(session_id)
            if session is None:
                return
            session.events.append(
                SessionEvent(
                    ts=time.time(),
                    type="tools_list",
                    result_rows=tool_count,
                    duration_ms=duration_ms,
                )
            )

    def record_tool_call(
        self,
        session_id: str,
        tool_id: str,
        arguments: dict[str, Any],
        result_rows: int,
        result_data: Any,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        with self._lock:
            session = self._active.get(session_id)
            if session is None:
                return
            # Redact secret-bearing argument fields before persisting to
            # the session log — same policy as AuditLog.record.
            from elliot_core.redaction import redact_audit_arguments

            session.events.append(
                SessionEvent(
                    ts=time.time(),
                    type="tool_call",
                    tool_id=tool_id,
                    arguments=redact_audit_arguments(arguments),
                    result_rows=result_rows,
                    result_token_estimate=_estimate_tokens(result_data),
                    duration_ms=duration_ms,
                    error=error,
                )
            )
        log.info(
            "session.tool_call",
            session_id=session_id,
            tool_id=tool_id,
            result_rows=result_rows,
            error=error,
        )

    def close_session(self, session_id: str) -> AgentSession | None:
        with self._lock:
            session = self._active.pop(session_id, None)
        if session is None:
            return None
        line = json.dumps(session.to_dict(), separators=(",", ":")) + "\n"
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        log.info(
            "session.closed",
            session_id=session_id,
            tool_calls=session.total_tool_calls,
            tokens=session.total_tokens_estimated,
        )
        return session

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-n:] if line.strip()]
