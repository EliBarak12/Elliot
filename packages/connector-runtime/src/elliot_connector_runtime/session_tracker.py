"""Structured per-agent-session tracking for the connector runtime."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import structlog

from elliot_core.tokens import estimate_tokens

log = structlog.get_logger(__name__)

# A result this large is worth surfacing — agents pay for every token.
_LARGE_RESULT_TOKENS = 500
# A call slower than this is worth flagging in the trace.
_SLOW_CALL_MS = 3000.0
# Error codes that mean the agent got the tool's *contract* wrong — it sent a
# parameter the tool rejected (missing, wrong type, out-of-range/enum, or a name
# the tool doesn't accept). A run that hits these is runtime proof that a tool's
# parameter contract wasn't clear enough for the agent to call it right the first
# time (principle 1) — the most actionable thing a connector author can see,
# distinct from an upstream/auth failure that isn't the contract's fault.
# Public so the cloud's per-tool insights classify a contract miss against the
# exact same code set the runtime's trace signal uses — one source of truth, no
# drift between "the trace flagged a contract miss" and "the dashboard did".
CONTRACT_MISS_CODES = frozenset(
    {
        # FastMCP rejects a missing/wrong-typed required arg against the tool
        # schema BEFORE the handler runs — the most common contract miss.
        "VALIDATION_INVALID_PARAMS",
        # Elliot's own deeper param validation (enums, ranges, unknown names).
        "MISSING_PARAM",
        "INVALID_PARAM_TYPE",
        "INVALID_PARAM_VALUE",
        "UNKNOWN_PARAM",
    }
)


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
    # The structured error code (e.g. MISSING_PARAM, UPSTREAM_FETCH_FAILED) when
    # the call failed — lets the trace classify a failure at a glance and powers
    # the contract-miss signal, without parsing the human-facing message.
    error_code: str | None = None
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

        # A refinement of `errors`: how many failures were the agent getting the
        # tool's parameter contract wrong (vs an upstream/auth failure that isn't
        # the author's to fix). This is the signal that points an author straight
        # at a tool whose description/enum/type wasn't clear enough.
        contract_misses = sum(1 for e in calls if e.error_code in CONTRACT_MISS_CODES)
        if contract_misses:
            out.append(
                {
                    "type": "contract_miss",
                    "severity": "medium",
                    "message": f"{contract_misses} call(s) sent a parameter the tool rejected",
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
                    "error_code": e.error_code,
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


# The token estimate lives in elliot_core.tokens so the runtime trace, the
# observation store, the eval budgets, and the footprint grade all count the
# signature metric identically. Aliased to the private name this module and
# server.py already import.
_estimate_tokens = estimate_tokens


_PREVIEW_MAX_CHARS = 800


def _result_preview(data: Any) -> str | None:
    """A short, bounded, REDACTED preview of a tool's output for the console.

    Only the first few rows are kept and the whole thing is capped — enough
    for a user to see *what* came back without dumping a full result set. The
    sample is run through the same redactor as the recorded arguments before it
    is serialized, so a secret an upstream API returns in its response body (an
    ``access_token`` field, a bearer string) never lands unredacted in the
    session log or the Agent Console — matching the "never log secrets/PII"
    policy the arguments already follow.
    """
    from elliot_core.redaction import redact_value

    try:
        sample = data[:3] if isinstance(data, list) else data
        text = json.dumps(redact_value(sample), default=str)
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
        error_code: str | None = None,
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
                    error_code=error_code,
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


# ── Stateless-fragment stitching ──────────────────────────────────────────────
# On a stateless transport (the only kind the 2026-07-28 MCP revision has),
# each request may arrive as its own one-shot "session" fragment. Cooperating
# clients echo Elliot's server-minted handle (see elliot_core.session_handle),
# so their fragments share a session id and group exactly; everything else is
# stitched by agent identity + idle gap. Shared by the local runtime's
# /v1/sessions and Elliot Cloud's observability (which previously carried its
# own copy of this logic).

STITCH_IDLE_GAP_S = 900.0  # 15 min between calls ends a logical session


def _identity_key(identity: dict[str, Any] | None) -> tuple[str | None, str | None]:
    ident = identity or {}
    return (ident.get("client"), ident.get("model"))


# (ts, parent_session_id, identity, agent_hint, event_dict)
_Flat = tuple[float, str, dict[str, Any] | None, str | None, dict[str, Any]]


def stitch_stateless_fragments(
    raw: list[dict[str, Any]], *, idle_gap_s: float = STITCH_IDLE_GAP_S
) -> list[dict[str, Any]]:
    """Stitch wire-observed session fragments into per-agent journeys.

    Hook-sourced sessions arrive whole and pass through untouched. Fragments
    that share an explicit Elliot session handle (``es_…`` or any
    client-supplied correlation id that repeated) merge exactly — regardless
    of the idle gap, because a shared handle IS the journey. Remaining
    single-shot fragments are flattened, sorted by time, and grouped into
    runs of the same agent identity within ``idle_gap_s``. Each group is
    rebuilt as a real ``AgentSession`` so totals, behaviour signals and the
    summary come from the same code the live tracker uses. The earliest
    fragment's id becomes the logical session's stable id, so a trace URL
    keeps resolving as more calls extend the run.
    """
    from elliot_core.session_handle import is_minted_handle

    kept: list[dict[str, Any]] = []
    by_handle: dict[str, list[dict[str, Any]]] = {}
    loose: list[dict[str, Any]] = []

    sid_counts: dict[str, int] = {}
    wire: list[dict[str, Any]] = []
    for s in raw:
        if (s.get("source") or "mcp") == "hook":
            kept.append(s)
            continue
        wire.append(s)
        sid = str(s.get("session_id") or "")
        sid_counts[sid] = sid_counts.get(sid, 0) + 1

    for s in wire:
        sid = str(s.get("session_id") or "")
        # An Elliot-minted handle is exact by construction; any other id that
        # recurs across fragments was a deliberate client correlation id.
        if sid and (is_minted_handle(sid) or sid_counts.get(sid, 0) > 1):
            by_handle.setdefault(sid, []).append(s)
        else:
            loose.append(s)

    def _flatten(fragments: list[dict[str, Any]]) -> list[_Flat]:
        flat: list[_Flat] = []
        for s in fragments:
            sid = str(s.get("session_id") or "")
            ident = s.get("agent_identity") if isinstance(s.get("agent_identity"), dict) else None
            hint = s.get("agent_hint")
            base_ts = float(s.get("started_at") or 0.0)
            for e in s.get("events") or []:
                ts = float(e.get("ts") or base_ts)
                flat.append((ts, sid, ident, hint, e))
        flat.sort(key=lambda t: t[0])
        return flat

    def _rebuild(run: list[_Flat], session_id: str | None = None) -> dict[str, Any]:
        first = run[0]
        events = [
            SessionEvent(
                ts=float(e.get("ts") or 0.0),
                type=e.get("type") or "tool_call",
                tool_id=e.get("tool_id"),
                arguments=e.get("arguments") if isinstance(e.get("arguments"), dict) else None,
                result_rows=e.get("result_rows"),
                result_token_estimate=e.get("result_token_estimate"),
                duration_ms=float(e.get("duration_ms") or 0.0),
                error=e.get("error"),
                error_code=e.get("error_code"),
                result_preview=e.get("result_preview"),
                reasoning=e.get("reasoning"),
            )
            for (_ts, _sid, _ident, _hint, e) in run
        ]
        session = AgentSession(
            session_id=session_id or first[1],
            started_at=first[0],
            agent_hint=first[3],
            agent_identity=first[2],
            events=events,
            last_activity=run[-1][0],
            source="mcp",
        )
        return session.to_dict()

    for sid, fragments in by_handle.items():
        flat = _flatten(fragments)
        if flat:
            kept.append(_rebuild(flat, session_id=sid))

    runs: list[list[_Flat]] = []
    for item in _flatten(loose):
        if runs:
            prev = runs[-1][-1]
            same_identity = _identity_key(item[2]) == _identity_key(prev[2])
            within_gap = item[0] - prev[0] <= idle_gap_s
            if same_identity and within_gap:
                runs[-1].append(item)
                continue
        runs.append([item])
    for run in runs:
        kept.append(_rebuild(run))

    kept.sort(key=lambda d: float(d.get("started_at") or 0.0), reverse=True)
    return kept
