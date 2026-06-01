"""Structured per-agent-session tracking for the connector runtime."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

# A result this large is worth surfacing — agents pay for every token.
_LARGE_RESULT_TOKENS = 500
# A call slower than this is worth flagging in the trace.
_SLOW_CALL_MS = 3000.0


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
    # A short, bounded preview of what the tool returned (the call's output).
    result_preview: str | None = None
    # The agent's reasoning around this call — only populated by a harness
    # hook adapter (Claude Code etc.); never available from MCP traffic.
    reasoning: str | None = None


@dataclass
class AgentSession:
    session_id: str
    started_at: float
    agent_hint: str | None
    agent_identity: dict[str, Any] | None = None
    events: list[SessionEvent] = field(default_factory=list)
    last_activity: float = 0.0
    # "mcp" — observed from the wire; "hook" — ingested from a harness hook.
    source: str = "mcp"
    # The user's prompt and the agent's final answer — only a harness hook
    # adapter can supply these; MCP traffic never carries them.
    user_prompt: str | None = None
    final_output: str | None = None

    def __post_init__(self) -> None:
        if not self.last_activity:
            self.last_activity = self.started_at

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

    @property
    def signals(self) -> list[dict[str, Any]]:
        """Behaviour signals inferred from the tool-call trace alone.

        These let a user see *how* an agent used the connector without any
        access to the agent's prompt or reasoning — only the calls it made
        and the results it got back.
        """
        out: list[dict[str, Any]] = []
        calls = [e for e in self.events if e.type == "tool_call"]

        if self.error_count:
            out.append(
                {
                    "type": "errors",
                    "severity": "high",
                    "message": f"{self.error_count} call(s) failed",
                }
            )

        retries = sum(
            1
            for prev, cur in zip(self.events, self.events[1:], strict=False)
            if prev.error and cur.tool_id is not None and cur.tool_id == prev.tool_id
        )
        if retries:
            out.append(
                {
                    "type": "retry",
                    "severity": "medium",
                    "message": f"{retries} retry after an error",
                }
            )

        large = [e for e in calls if (e.result_token_estimate or 0) > _LARGE_RESULT_TOKENS]
        if large:
            out.append(
                {
                    "type": "large_result",
                    "severity": "medium",
                    "message": f"{len(large)} call(s) returned over {_LARGE_RESULT_TOKENS} tokens",
                }
            )

        signatures = Counter(
            (e.tool_id, json.dumps(e.arguments or {}, sort_keys=True, default=str))
            for e in calls
            if e.tool_id is not None
        )
        redundant = sum(c - 1 for c in signatures.values() if c > 1)
        if redundant:
            out.append(
                {
                    "type": "redundant",
                    "severity": "low",
                    "message": f"{redundant} repeated call(s) with identical arguments",
                }
            )

        slow = [e for e in calls if e.duration_ms > _SLOW_CALL_MS]
        if slow:
            out.append(
                {
                    "type": "slow",
                    "severity": "low",
                    "message": f"{len(slow)} call(s) slower than {_SLOW_CALL_MS / 1000:.0f}s",
                }
            )

        return out

    @property
    def summary(self) -> str:
        """Plain-language one-liner describing the agent's path through the connector."""
        calls = [e.tool_id or "tool" for e in self.events if e.type == "tool_call"]
        if not calls:
            return "No tool calls recorded yet."
        if len(calls) <= 8:
            return " → ".join(calls)
        counts = Counter(calls)
        return ", ".join(f"{tid}×{n}" for tid, n in counts.most_common(6))

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "agent_hint": self.agent_hint,
            "agent_identity": self.agent_identity,
            "source": self.source,
            "user_prompt": self.user_prompt,
            "final_output": self.final_output,
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
                    "result_preview": e.result_preview,
                    "reasoning": e.reasoning,
                }
                for e in self.events
            ],
            "total_tool_calls": self.total_tool_calls,
            "total_tokens_estimated": self.total_tokens_estimated,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "error_count": self.error_count,
            "signals": self.signals,
            "summary": self.summary,
        }


@functools.lru_cache(maxsize=1)
def _encoder() -> Any | None:
    """Return a tiktoken encoder if available, else ``None``.

    A token count is only as good as the tokenizer. When ``tiktoken`` is
    installed we use ``cl100k_base`` (a solid cross-model proxy) for a real
    count instead of a heuristic. When it isn't installed — or its BPE vocab
    can't be loaded (e.g. offline) — we fall back to chars/4. Cached so the
    vocab loads at most once per process.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _estimate_tokens(data: Any) -> int:
    """Estimate the token cost of a result.

    Uses a real tokenizer (tiktoken ``cl100k_base``) when available; otherwise
    falls back to the chars/4 heuristic. Both paths are model-approximate — the
    figure powers the token-efficiency dashboard and eval gates, not billing.
    """
    try:
        text = json.dumps(data, default=str)
    except Exception:
        return 0
    enc = _encoder()
    if enc is not None:
        with contextlib.suppress(Exception):
            return max(1, len(enc.encode(text)))
    return max(1, len(text) // 4)


_PREVIEW_MAX_CHARS = 800


def _result_preview(data: Any) -> str | None:
    """A short, bounded preview of a tool's output for the console.

    Only the first few rows are kept and the whole thing is capped — enough
    for a user to see *what* came back without dumping a full result set.
    """
    try:
        sample = data[:3] if isinstance(data, list) else data
        text = json.dumps(sample, default=str)
    except Exception:
        return None
    if len(text) > _PREVIEW_MAX_CHARS:
        return text[:_PREVIEW_MAX_CHARS] + "…"
    return text


class SessionTracker:
    """Tracks one agent session per MCP connection.

    A session stays open and accumulates events for the whole lifetime of an
    agent's MCP connection — it is keyed on the MCP session id, not on a
    single request — so a multi-step agent run shows as one trace. Sessions
    are flushed to NDJSON when they close (idle sweep or shutdown).

    Subscribers can receive live session updates via :meth:`subscribe`.
    """

    def __init__(self, sessions_path: str | Path) -> None:
        self._path = Path(sessions_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, AgentSession] = {}
        self._lock = Lock()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    # ----------------------------------------------------------- pub/sub

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a queue that receives a session dict on every update."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def _publish(self, session: AgentSession) -> None:
        """Fan a session snapshot out to all live subscribers (non-blocking)."""
        with self._lock:
            subs = list(self._subscribers)
        if not subs:
            return
        payload = session.to_dict()
        for queue in subs:
            # A slow consumer drops updates; the next event carries the full
            # session state anyway, so nothing is permanently lost.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    # --------------------------------------------------------- lifecycle

    def start_session(
        self,
        agent_hint: str | None = None,
        session_id: str | None = None,
        agent_identity: dict[str, Any] | None = None,
    ) -> str:
        """Create a new session. If session_id is given, use it as the key; otherwise generate one."""
        sid = session_id or uuid.uuid4().hex[:8]
        with self._lock:
            session = AgentSession(
                session_id=sid,
                started_at=time.time(),
                agent_hint=agent_hint,
                agent_identity=agent_identity,
            )
            self._active[sid] = session
        log.info(
            "session.started",
            session_id=sid,
            agent_hint=agent_hint,
            agent_client=(agent_identity or {}).get("client"),
            agent_model=(agent_identity or {}).get("model"),
        )
        self._publish(session)
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
            session.last_activity = time.time()
        self._publish(session)

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
                    result_preview=_result_preview(result_data),
                )
            )
            session.last_activity = time.time()
        log.info(
            "session.tool_call",
            session_id=session_id,
            tool_id=tool_id,
            result_rows=result_rows,
            error=error,
        )
        self._publish(session)

    def append_ingested(
        self,
        session_id: str,
        agent_identity: dict[str, Any] | None,
        events: list[SessionEvent],
        *,
        user_prompt: str | None = None,
        final_output: str | None = None,
    ) -> AgentSession:
        """Append hook-sourced events to a session, creating it if new.

        This is how a harness hook adapter (Claude Code, Codex, Cursor) feeds
        the console — it carries the agent's reasoning, the user's prompt and
        the agent's final answer, none of which MCP traffic can see.
        """
        with self._lock:
            session = self._active.get(session_id)
            if session is None:
                session = AgentSession(
                    session_id=session_id,
                    started_at=time.time(),
                    agent_hint=(agent_identity or {}).get("client"),
                    agent_identity=agent_identity,
                    source="hook",
                )
                self._active[session_id] = session
            if agent_identity:
                session.agent_identity = agent_identity
            if user_prompt:
                session.user_prompt = user_prompt
            if final_output:
                session.final_output = final_output
            session.events.extend(events)
            session.last_activity = time.time()
        log.info(
            "session.ingested",
            session_id=session_id,
            events=len(events),
            client=(agent_identity or {}).get("client"),
        )
        self._publish(session)
        return session

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
        self._publish(session)
        return session

    def sweep_idle(self, ttl_seconds: float) -> list[str]:
        """Close sessions with no activity for ``ttl_seconds``. Returns closed ids."""
        now = time.time()
        with self._lock:
            stale = [sid for sid, s in self._active.items() if now - s.last_activity > ttl_seconds]
        for sid in stale:
            self.close_session(sid)
        return stale

    def flush_all(self) -> None:
        """Close every active session — used on graceful shutdown."""
        with self._lock:
            sids = list(self._active.keys())
        for sid in sids:
            self.close_session(sid)

    # ------------------------------------------------------------- reads

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the most recent sessions, merging live and closed ones.

        Active in-memory sessions take precedence over their closed copy on
        disk so the console reflects an agent's run while it is still going.
        """
        merged: dict[str, dict[str, Any]] = {}
        if self._path.exists():
            lines = self._path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if not line.strip():
                    continue
                record = json.loads(line)
                merged[record["session_id"]] = record
        with self._lock:
            for session in self._active.values():
                merged[session.session_id] = session.to_dict()
        ordered = sorted(merged.values(), key=lambda d: d.get("started_at", 0.0), reverse=True)
        return ordered[:n]
