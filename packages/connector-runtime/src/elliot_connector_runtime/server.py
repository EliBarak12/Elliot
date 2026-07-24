"""FastAPI + FastMCP HTTP server exposing connector tools on port 3001."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from elliot_core.agent_identity import (
    AgentIdentity,
    get_current_agent_identity,
    merge_client_info,
    set_current_agent_identity,
)
from elliot_core.auth_middleware import ApiKeyMiddleware, enforce_auth_configured
from elliot_core.error_middleware import register_error_handlers
from elliot_core.http_middleware import AgentIdentityMiddleware, UserIdentityMiddleware
from elliot_core.user_identity import get_current_user_id

from .audit import AuditLog
from .cache import ConnectorCache
from .credential_resolver import ExecutorPool
from .executor import ToolExecutor
from .loader import ConnectorLoadError
from .mcp_oauth import MCPAuthMiddleware, TokenStore, register_mcp_oauth
from .oauth_routes import register_oauth_routes
from .oauth_store import CredentialVault
from .observation_store import ObservationStore
from .protocols.openai import register_openai_routes
from .session_tracker import SessionTracker
from .task_store import TaskStore, get_task_store
from .trace_ingest import IngestPayload

log = structlog.get_logger(__name__)

_cache = ConnectorCache(ttl_seconds=30)
_start_time = time.time()

# Audit finding H7: no upper bound on request body size, so an agent could
# POST an arbitrarily large MCP `initialize` body and exhaust memory.
# 4 MB is generous for any legitimate MCP/JSON-RPC payload and small enough
# that a misbehaving client can't OOM the worker. Configurable via env.
_DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024


def _max_body_bytes() -> int:
    raw = os.environ.get("ELLIOT_MAX_REQUEST_BODY_BYTES", "")
    try:
        v = int(raw) if raw else _DEFAULT_MAX_BODY_BYTES
        return max(1024, v)
    except ValueError:
        return _DEFAULT_MAX_BODY_BYTES


class BodySizeLimitMiddleware:
    """Reject requests whose body exceeds the configured cap.

    Two enforcement paths:

    * Content-Length present — authoritative; we short-circuit with a 413
      before the body is read so we never materialize the bytes.
    * No Content-Length (chunked transfer-encoding) — we drain the ASGI
      ``receive`` stream ourselves, counting bytes; the moment the running
      total exceeds the cap we abort with a 413 without ever invoking the
      downstream app. An under-limit body is buffered (bounded by the cap)
      and replayed to the app intact.

    Only request-body bytes are counted; the response side is passed straight
    through, so MCP streaming responses (the mounted /mcp app) are untouched.

    Implemented as a raw ASGI middleware rather than ``BaseHTTPMiddleware``
    so the wrapped ``receive`` reaches the downstream app unbuffered.
    """

    def __init__(self, app: Any, max_bytes: int) -> None:
        self._app = app
        self._max = max_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        cl = headers.get("content-length")
        if cl is not None:
            try:
                if int(cl.decode("latin-1")) > self._max:
                    await self._reject(send)
                    return
            except ValueError:
                # Malformed Content-Length — let the next layer decide.
                pass
            # Content-Length is authoritative — no need to count bytes.
            await self._app(scope, receive, send)
            return

        # Chunked upload (no Content-Length): drain and count the body before
        # handing it to the app. We stop the instant the running total crosses
        # the cap, so at most one chunk past the limit is ever buffered.
        buffered: list[dict[str, Any]] = []
        seen = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                buffered.append(message)
                if message.get("type") == "http.disconnect":
                    break
                continue
            seen += len(message.get("body", b"") or b"")
            if seen > self._max:
                # Over the cap: reject now — the downstream app is never
                # invoked, so no partial body reaches a route handler.
                await self._reject(send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        # Under the cap — replay the buffered messages to the app verbatim.
        replay = iter(buffered)

        async def _replaying_receive() -> Any:
            try:
                return next(replay)
            except StopIteration:
                # Body exhausted — mirror Starlette and report disconnect.
                return await receive()

        await self._app(scope, _replaying_receive, send)

    async def _reject(self, send: Any) -> None:
        response = JSONResponse(
            {
                "error": {
                    "code": "BODY_TOO_LARGE",
                    "message": f"Request body exceeds {self._max} bytes",
                }
            },
            status_code=413,
        )
        await response(
            {"type": "http"},
            self._empty_receive,
            send,
        )

    @staticmethod
    async def _empty_receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}


def _build_limiter() -> Limiter:
    limit = os.environ.get("ELLIOT_RATE_LIMIT", "120/minute")
    # ELLIOT_RATE_LIMIT_STORAGE_URI: a shared backend (e.g. redis://host:6379,
    # memcached://host:11211) for the rate-limit counters. When set, the cap
    # is enforced consistently across every uvicorn worker / replica. When
    # unset slowapi falls back to per-process in-memory storage, which means
    # the limit only holds within a single worker — see the warning below.
    storage_uri = os.environ.get("ELLIOT_RATE_LIMIT_STORAGE_URI", "").strip()
    if storage_uri:
        log.info("rate_limit.storage", backend=storage_uri.split("://")[0])
        return Limiter(
            key_func=get_remote_address,
            default_limits=[limit],
            storage_uri=storage_uri,
        )
    log.warning(
        "rate_limit.in_memory",
        detail=(
            "ELLIOT_RATE_LIMIT_STORAGE_URI is not set: rate-limit counters are "
            "per-process and do NOT hold across multiple uvicorn workers or "
            "instances. Set a redis:// or memcached:// URI in production."
        ),
    )
    return Limiter(key_func=get_remote_address, default_limits=[limit])


def _session_idle_ttl() -> float:
    """Seconds of inactivity after which an agent session is flushed to disk."""
    raw = os.environ.get("ELLIOT_SESSION_IDLE_TTL", "")
    try:
        return max(5.0, float(raw)) if raw else 300.0
    except ValueError:
        return 300.0


async def _session_idle_sweeper(
    tracker: SessionTracker,
    store: ObservationStore | None = None,
) -> None:
    """Periodically close agent sessions that have gone idle.

    A session stays open while the agent's MCP connection is active; this
    loop flushes the ones that have stopped sending tool calls so the
    NDJSON log and observation store reflect completed runs. The same swept
    session ids are closed in the observation store so its per-session
    rollup (tool counts, tokens, duration) is finalised too.
    """
    ttl = _session_idle_ttl()
    interval = min(ttl, 30.0)
    while True:
        await asyncio.sleep(interval)
        with contextlib.suppress(Exception):
            closed = tracker.sweep_idle(ttl)
            if closed:
                log.info("session.idle_swept", count=len(closed))
                if store is not None:
                    for sid in closed:
                        with contextlib.suppress(Exception):
                            store.close_session(sid)


def _require_destructive_confirmation() -> bool:
    """Whether WRITE/ACTION tool calls must include ``confirm=True``.

    Toggled with ``ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION``. Off by default
    so existing connectors keep working; turn it on to enforce the AX
    interactivity pattern for sensitive operations.
    """
    raw = os.environ.get("ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _identity_payload(identity: AgentIdentity | None) -> dict[str, Any] | None:
    if identity is None:
        return None
    payload = identity.to_dict()
    return payload if any(payload.values()) else None


def _capability_names(capabilities: Any) -> tuple[str, ...] | None:
    """Reduce an MCP ``ClientCapabilities`` object to the names the client
    advertised (``roots``, ``sampling``, ``elicitation``, ``experimental``).

    The handshake sends a present-but-empty object for each supported
    capability and ``None`` for the rest, so a non-None attribute means
    "supported". Returns ``None`` when nothing was advertised."""
    if capabilities is None:
        return None
    names = [
        name
        for name in ("roots", "sampling", "elicitation", "experimental")
        if getattr(capabilities, name, None) is not None
    ]
    return tuple(names) if names else None


def _agent_hint_from_identity(identity: AgentIdentity | None) -> str:
    """Best-effort string for the legacy ``agent_hint`` column."""
    if identity is None:
        return "mcp"
    label = identity.display()
    return label if label and label != "unknown" else "mcp"


def _current_session_and_identity(mcp: FastMCP) -> tuple[str | None, dict[str, Any] | None]:
    """Best-effort (session_id, identity) for the in-flight MCP request.

    Mirrors the correlation logic in ``_register_tool``'s handler: prefer the
    stable ``mcp-session-id`` header, fall back to the per-call request id, and
    enrich the contextvar identity with ``clientInfo`` from the handshake.
    """
    session_id: str | None = None
    client_name: str | None = None
    client_version: str | None = None
    with contextlib.suppress(Exception):
        ctx = mcp.get_context()
        with contextlib.suppress(Exception):
            session_id = ctx.request_id
        with contextlib.suppress(Exception):
            request = ctx.request_context.request
            if request is not None:
                mcp_session_id = request.headers.get("mcp-session-id")
                if mcp_session_id:
                    session_id = mcp_session_id
        with contextlib.suppress(Exception):
            client_params = ctx.session.client_params
            if client_params is not None and client_params.clientInfo is not None:
                client_name = client_params.clientInfo.name
                client_version = client_params.clientInfo.version
    identity = get_current_agent_identity()
    if client_name:
        with contextlib.suppress(Exception):
            identity = merge_client_info(identity, client_name, client_version)
    return session_id, _identity_payload(identity)


def _result_truncated(result: Any) -> bool:
    """Whether the executor capped this result at ELLIOT_MAX_RESULT_ROWS.

    ``QueryResult`` carries a top-level ``truncated`` flag; the legacy
    ``ToolResult`` keeps it inside ``meta``. Read whichever is present so the
    truncation marker survives regardless of the result type.
    """
    flag = getattr(result, "truncated", None)
    if flag is not None:
        return bool(flag)
    meta = getattr(result, "meta", None)
    if isinstance(meta, dict):
        return bool(meta.get("truncated", False))
    return False


def _payload_for(result: Any) -> dict[str, Any]:
    """Build the agent-facing tool result.

    Always carries an ``estimated_tokens`` count of the returned rows — token
    cost is a first-class signal the agent can use to decide whether to narrow
    a request, not just an internal metric — plus the truncation marker + note
    when the set was capped.
    """
    from .session_tracker import _estimate_tokens

    rows = getattr(result, "rows", []) or []
    payload: dict[str, Any] = {
        "rows": rows,
        "count": len(rows),
        "estimated_tokens": _estimate_tokens(rows),
    }
    if _result_truncated(result):
        payload["truncated"] = True
        payload["truncation_note"] = _truncation_note(result)
    return payload


def _truncation_note(result: Any) -> str:
    """Actionable guidance for an agent whose result was capped (principle 3).

    A bare ``truncated: true`` tells the agent the set is incomplete but not
    what to do about it. Spell out that this is a partial result and the
    concrete next step — narrow the request — so the agent recovers instead
    of either trying to process a context-blowing dump or silently treating a
    capped set as the whole answer.
    """
    from .executor import max_result_rows, max_result_tokens

    cap = max_result_rows()
    reason = getattr(result, "truncation_reason", None)
    if reason == "token_budget":
        # The rows fit the row cap but were too large (fat fields) to fit the
        # per-call token budget, so fewer were returned.
        total = getattr(result, "total_rows", None)
        returned = len(getattr(result, "rows", []) or [])
        scope = (
            f"Returned {returned} of {total} matching rows"
            if isinstance(total, int)
            else f"Returned {returned} rows"
        )
        return (
            f"{scope}: the full set exceeded the {max_result_tokens()}-token per-call "
            "budget (the rows carry large fields). Select only the fields you need "
            "(narrow return_fields), or add a tighter filter, then call again."
        )
    if reason == "source_cap":
        # The upstream snapshot was capped before this query ran, so the rows
        # returned may be missing matches that no client-side filter recovers.
        return (
            f"The data source backing this tool was capped at {cap} rows when it "
            "was fetched, so this result may be missing matching rows. Treat it as "
            "incomplete: prefer a tool that filters upstream (passes the filter to "
            "the source), or ask the connector author to add server-side filtering "
            "or pagination to this source."
        )
    total = getattr(result, "total_rows", None)
    if isinstance(total, int) and total > cap:
        scope = f"Returned the first {cap} of {total} matching rows"
    else:
        scope = f"Returned the first {cap} rows; more rows matched but were not included"
    return (
        f"{scope}. This is a partial result, not the complete answer — narrow the "
        "request (add or tighten a filter, or pass a smaller limit) so the full "
        "result fits, then call again."
    )


async def _emit_runtime_log(ctx: Any, level: str, data: dict[str, Any]) -> None:
    """Emit a structured MCP log notification (``notifications/message``).

    Surfaces Elliot's per-call observability — tool, rows, latency, truncation,
    error code — to the agent's MCP client in real time via the spec's
    ``logging`` capability, so principle 4 ("every call observable") is visible
    inline in the agent's session, not only in the dashboard. A client that sets
    a higher minimum level simply won't be sent the lower-severity events.

    Metadata only: per the MCP logging security guidance it never carries row
    data, arguments, or secrets — just counts, durations, and codes. Best-effort:
    a logging failure must never break the tool call, so everything is
    suppressed and a missing context is a no-op.
    """
    if ctx is None:
        return
    with contextlib.suppress(Exception):
        await ctx.session.send_log_message(
            level=level,
            data=data,
            logger="elliot.runtime",
            related_request_id=ctx.request_id,
        )


def _slug_prefix(connector_slug: str | None) -> str:
    """Return an MCP-tool-name-safe ``{slug}_`` prefix, or ``""`` when unslugged.

    The built-in feedback and task tools are namespaced under the connector's
    slug so they read as part of *that* connector and don't collide when an
    agent connects to several Elliot connectors at once (every connector would
    otherwise expose identically named ``submit_feedback`` / ``get_task`` tools).
    Non-identifier characters in the slug (e.g. the hyphen in ``postgres-readonly``)
    are folded to ``_`` so the result is a valid MCP tool name.
    """
    if not connector_slug:
        return ""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", connector_slug).strip("_")
    return f"{safe}_" if safe else ""


def _feedback_tool_name(prefix: str) -> str:
    return f"{prefix}submit_feedback" if prefix else "submit_feedback"


def _task_tool_name(prefix: str) -> str:
    # No slug: keep the historical ``elliot_get_task`` name for backward compat.
    return f"{prefix}get_task" if prefix else "elliot_get_task"


def _suggest(tool_id: str, avg_tokens: float, max_tokens: float) -> str | None:
    if avg_tokens > 1000:
        return f"Average {avg_tokens:.0f} tokens is very high. Add LIMIT clause or SELECT only needed columns."
    if max_tokens > 2000:
        return (
            f"Peak {max_tokens:.0f} tokens. Add a LIMIT or pagination parameter to cap result size."
        )
    if avg_tokens > 300:
        return "Consider adding LIMIT or selecting fewer columns to reduce token cost."
    return None


def create_runtime_server(
    config: Any,
    executor: ToolExecutor,
    audit: AuditLog | None = None,
    tracker: SessionTracker | None = None,
    store: ObservationStore | None = None,
    executor_pool: ExecutorPool | None = None,
) -> FastMCP:
    """
    Build a FastMCP server whose tool list mirrors the connector's ToolDefinitions.
    Registers tools, resources (schema/sample/source status), and prompts (skills).

    When audit / tracker / store are supplied, MCP tool invocations are recorded
    so observability matches the OpenAI-protocol path.
    """
    import json

    from elliot_core.types import ConnectorConfig

    cfg: ConnectorConfig = config
    connector_slug = getattr(cfg, "slug", None)
    prefix = _slug_prefix(connector_slug)
    feedback_tool_name = _feedback_tool_name(prefix)
    task_tool_name = _task_tool_name(prefix)

    instructions = (
        cfg.instructions
        if cfg.instructions
        else (
            f"This MCP server exposes tools for the '{cfg.name}' connector. "
            f"It wraps {len(cfg.sources)} data source(s) across {len(cfg.tools)} tool(s). "
            "Use list_tools to see available tools, then call them with the required parameters."
        )
    )
    # Tell the agent the connector ships a feedback tool and to use it — the
    # tool only exists when there's an observation store to persist to, so the
    # instruction is conditional on the same thing the registration is.
    if store is not None:
        instructions = (
            instructions.rstrip()
            + f"\n\nAfter calling a tool, report how it worked with `{feedback_tool_name}` "
            "(outcome 'success', 'failure', or 'partial') so the connector author "
            "can see what to improve."
        )
    # streamable_http_path="/" so that mounting at /mcp exposes the MCP
    # endpoint at /mcp/ (matching the plugin and the docs), not /mcp/mcp/.
    # serverInfo.name is the connector's public identity — it is what MCP
    # clients (Claude, Cursor) and graders display. A hardcoded
    # "elliot-runtime" made every published connector anonymous.
    mcp = FastMCP(cfg.name or "elliot-runtime", instructions=instructions, streamable_http_path="/")

    task_store = get_task_store()
    for tool_def in cfg.tools:
        _register_tool(
            mcp,
            executor,
            tool_def,
            task_store,
            audit=audit,
            tracker=tracker,
            store=store,
            connector_slug=connector_slug,
            executor_pool=executor_pool,
            task_tool_name=task_tool_name,
        )

    _register_resources(mcp, cfg, executor, json)
    _register_prompts(mcp, cfg)
    _register_task_tool(mcp, task_store, task_tool_name)
    if store is not None:
        _register_feedback_tool(mcp, store, connector_slug, feedback_tool_name)

    _register_logging(mcp)
    _register_validation_capture(mcp, store, tracker, connector_slug)

    return mcp


def _register_validation_capture(
    mcp: FastMCP,
    store: ObservationStore | None,
    tracker: SessionTracker | None,
    connector_slug: str | None,
) -> None:
    """Record argument-validation failures, which FastMCP rejects BEFORE the tool
    handler runs.

    FastMCP validates a tool's arguments against its schema and rejects a bad
    call (missing or wrong-typed required parameter) before the handler executes,
    so those failures never reach the handler's observation recording — yet
    "an agent keeps calling my tool with the wrong parameters" is one of the most
    common real-world failures and, uncaptured, leaves the connector owner seeing
    a 0% error rate while agents struggle. Wrap the tool manager's call_tool
    (which ``FastMCP.call_tool`` resolves at call time, so the wrap takes effect)
    and, on a ``ToolError`` whose cause is a pydantic ``ValidationError`` — the
    stable signal that this is a pre-handler validation failure and not a handler
    error (which is already recorded) — write one error observation. Best-effort:
    it never changes the call result and never raises into the call path.
    """
    if store is None and tracker is None:
        return

    import pydantic
    from mcp.server.fastmcp.exceptions import ToolError

    tool_manager = mcp._tool_manager
    orig_call = tool_manager.call_tool

    async def _wrapped(name: str, arguments: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return await orig_call(name, arguments, *args, **kwargs)
        except ToolError as exc:
            if isinstance(exc.__cause__, pydantic.ValidationError):
                with contextlib.suppress(Exception):
                    _record_validation_failure(
                        mcp, store, tracker, connector_slug, name, arguments, exc
                    )
            raise

    tool_manager.call_tool = _wrapped  # type: ignore[method-assign]


def _record_validation_failure(
    mcp: FastMCP,
    store: ObservationStore | None,
    tracker: SessionTracker | None,
    connector_slug: str | None,
    tool_id: str,
    arguments: dict[str, Any],
    exc: Exception,
) -> None:
    """Write one error observation for an argument-validation failure."""
    session_id, identity_payload = _current_session_and_identity(mcp)
    if not session_id:
        return
    # Single compact line — never the full multi-line pydantic dump.
    first_line = next((ln for ln in str(exc).splitlines() if ln.strip()), "")
    reason = first_line[:200] if first_line else "argument validation failed"
    error = f"[VALIDATION_INVALID_PARAMS] {reason}"
    agent_hint = _agent_hint_from_identity(get_current_agent_identity())
    if store is not None:
        store.open_session(
            session_id,
            agent_hint=agent_hint,
            connector_slug=connector_slug,
            agent_identity=identity_payload,
        )
        store.write_tool_call(
            session_id=session_id,
            tool_id=tool_id,
            arguments=arguments,
            result_row_count=0,
            result_token_estimate=0,
            duration_ms=0.0,
            error=error,
            connector_slug=connector_slug,
        )
    if tracker is not None:
        tracker.record_tool_call(
            session_id=session_id,
            tool_id=tool_id,
            arguments=arguments,
            result_rows=0,
            result_data=[],
            duration_ms=0.0,
            error=error,
        )


def _register_logging(mcp: FastMCP) -> None:
    """Advertise the MCP ``logging`` capability and accept ``logging/setLevel``.

    The runtime streams per-call observability as ``notifications/message`` (see
    ``_emit_runtime_log``), but the spec requires a server that emits logs to
    declare the ``logging`` capability — which the lowlevel server only does when
    a ``set_logging_level`` handler is registered. Without this, a compliant
    client (e.g. Claude) is not told it can receive Elliot's logs and a
    ``logging/setLevel`` call fails with "Method not found". Registering the
    handler both advertises the capability and lets the client choose its
    minimum severity; the lowlevel session then filters notifications to that
    level automatically.
    """
    from mcp import types

    @mcp._mcp_server.set_logging_level()  # type: ignore[no-untyped-call, untyped-decorator]
    async def _set_level(level: types.LoggingLevel) -> None:  # pragma: no cover - thin shim
        # The ServerSession records the level and filters send_log_message on it;
        # we only need to accept the request so the capability is advertised.
        return None


def _register_tool(
    mcp: FastMCP,
    executor: ToolExecutor,
    tool_def: Any,
    task_store: TaskStore,
    audit: AuditLog | None = None,
    tracker: SessionTracker | None = None,
    store: ObservationStore | None = None,
    connector_slug: str | None = None,
    executor_pool: ExecutorPool | None = None,
    task_tool_name: str = "elliot_get_task",
) -> None:
    from elliot_core.errors import ElliotError, to_mcp_error_content
    from elliot_core.types import ToolDefinition

    td: ToolDefinition = tool_def
    read_only = td.category == "READ"
    is_destructive = td.category in ("WRITE", "ACTION")
    annotations = ToolAnnotations(
        title=td.name,
        readOnlyHint=read_only,
        destructiveHint=is_destructive,
        idempotentHint=read_only,
        openWorldHint=True,
    )
    run_async: bool = getattr(td, "run_async", False)
    require_confirmation = is_destructive and _require_destructive_confirmation()

    def _observe_blocking(
        tool_id: str,
        arguments: dict[str, Any],
        result_rows: list[dict[str, Any]],
        duration_ms: float,
        error: str | None,
        session_id: str | None,
        identity: Any,
    ) -> None:
        """Record one tool call to audit log, session tracker, and observation
        store. All three do blocking I/O (file appends, synchronous SQLAlchemy
        writes), so this runs in a worker thread — never on the event loop."""
        row_count = len(result_rows)
        # Estimate tokens up-front so the audit row, the observation store, and
        # /v1/sessions all report the same per-call figure.
        from .session_tracker import _estimate_tokens

        token_estimate = _estimate_tokens(result_rows)
        if audit is not None:
            with contextlib.suppress(Exception):
                audit.record(
                    tool_id,
                    arguments,
                    row_count,
                    duration_ms,
                    error=error,
                    session_id=session_id,
                    tokens_estimate=token_estimate,
                )
        identity_payload = _identity_payload(identity)
        agent_hint = _agent_hint_from_identity(identity)
        if session_id is not None:
            if tracker is not None:
                with contextlib.suppress(Exception):
                    tracker.get_or_start_session(
                        session_id,
                        agent_hint=agent_hint,
                        agent_identity=identity_payload,
                    )
                    tracker.record_tool_call(
                        session_id=session_id,
                        tool_id=tool_id,
                        arguments=arguments,
                        result_rows=row_count,
                        result_data=result_rows,
                        duration_ms=duration_ms,
                        error=error,
                    )
                    # The session stays open and accumulates every call from
                    # this MCP connection — the idle sweeper flushes it later.
            if store is not None:
                with contextlib.suppress(Exception):
                    store.open_session(
                        session_id,
                        agent_hint=agent_hint,
                        connector_slug=connector_slug,
                        agent_identity=identity_payload,
                    )
                    store.write_tool_call(
                        session_id=session_id,
                        tool_id=tool_id,
                        arguments=arguments,
                        result_row_count=row_count,
                        result_token_estimate=token_estimate,
                        duration_ms=duration_ms,
                        error=error,
                        connector_slug=connector_slug,
                    )
                    # Do NOT close the session here: it stays open and
                    # accumulates every call from this MCP connection. The
                    # idle sweeper / shutdown closes it (mirroring the
                    # SessionTracker lifecycle), so the observation-store
                    # rollup reflects a completed run, not a single call.

    async def _observe(
        tool_id: str,
        arguments: dict[str, Any],
        result_rows: list[dict[str, Any]],
        duration_ms: float,
        error: str | None,
        session_id: str | None,
    ) -> None:
        """Capture the request-scoped agent identity, then offload the blocking
        audit/tracker/observation-store writes to a worker thread."""
        identity = get_current_agent_identity()
        await run_in_threadpool(
            _observe_blocking,
            tool_id,
            arguments,
            result_rows,
            duration_ms,
            error,
            session_id,
            identity,
        )

    async def _handler(**kwargs: Any) -> dict[str, Any]:
        import time

        from mcp.server.fastmcp import Context

        ctx: Context[Any, Any, Any] | None = None
        session_id: str | None = None
        mcp_session_id: str | None = None
        client_name: str | None = None
        client_version: str | None = None
        protocol_version: str | None = None
        capabilities: tuple[str, ...] | None = None
        with contextlib.suppress(Exception):
            ctx = mcp.get_context()
        await _emit_runtime_log(ctx, "debug", {"event": "tool.call.start", "tool": td.id})
        if ctx is not None:
            # request_id is per-call — only a last-resort correlation id.
            with contextlib.suppress(Exception):
                session_id = ctx.request_id
            # Prefer the MCP protocol session id (stable for the whole agent
            # connection) so a multi-step run groups into one trace.
            header_client: str | None = None
            header_client_version: str | None = None
            header_model: str | None = None
            with contextlib.suppress(Exception):
                request = ctx.request_context.request
                if request is not None:
                    mcp_session_id = request.headers.get("mcp-session-id")
                    # Explicit override headers — set by gateways/clients that
                    # want to label themselves (and the only signal available
                    # when the per-tenant runtime can't reach the handshake's
                    # clientInfo, e.g. behind the cloud's stateless transport).
                    header_client = request.headers.get("x-client-name")
                    header_client_version = request.headers.get("x-client-version")
                    # MCP carries no model field, so a client volunteers it here.
                    header_model = request.headers.get("x-model") or request.headers.get(
                        "x-model-name"
                    )
            # clientInfo / protocolVersion / capabilities from the MCP
            # `initialize` handshake — the spec-backed signals.
            with contextlib.suppress(Exception):
                client_params = ctx.session.client_params
                if client_params is not None:
                    if client_params.clientInfo is not None:
                        client_name = client_params.clientInfo.name
                        client_version = client_params.clientInfo.version
                    protocol_version = getattr(client_params, "protocolVersion", None)
                    capabilities = _capability_names(getattr(client_params, "capabilities", None))
            # Fall back to the explicit header when the handshake didn't surface
            # a client — otherwise every real call records as "unknown".
            if not client_name and header_client:
                client_name = header_client
                client_version = client_version or header_client_version
        if mcp_session_id:
            session_id = mcp_session_id
        if client_name or protocol_version or capabilities or header_model:
            with contextlib.suppress(Exception):
                set_current_agent_identity(
                    merge_client_info(
                        get_current_agent_identity(),
                        client_name,
                        client_version,
                        protocol_version=protocol_version,
                        capabilities=capabilities,
                        model=header_model,
                    )
                )

        if require_confirmation:
            confirmed = bool(kwargs.pop("confirm", False))
            if not confirmed:
                exc = ElliotError(
                    "CONFIRMATION_REQUIRED",
                    (
                        f"Tool '{td.id}' is {td.category}. Re-call with confirm=true "
                        "after the user authorises this destructive operation."
                    ),
                    {"tool_id": td.id, "category": td.category},
                )
                await _observe(td.id, kwargs, [], 0.0, str(exc), session_id)
                error_content = to_mcp_error_content(exc)
                raise ValueError(error_content["text"])
        else:
            kwargs.pop("confirm", None)

        # Per-user auth (boundary 2): resolve the executor bound to THIS end
        # user's upstream credential. For shared-auth connectors this returns
        # the single shared executor. A missing/expired credential surfaces as
        # an actionable AUTH_REQUIRED error carrying the connect URL.
        active_executor = executor
        if executor_pool is not None:
            try:
                active_executor = await executor_pool.get_executor(
                    get_current_user_id(), td.source_ids or None
                )
            except ElliotError as exc:
                await _observe(td.id, kwargs, [], 0.0, str(exc), session_id)
                error_content = to_mcp_error_content(exc)
                raise ValueError(error_content["text"]) from exc

        if run_async:

            async def _work() -> dict[str, Any]:
                result = await active_executor.execute(td, kwargs)
                return _payload_for(result)

            task_id = task_store.submit(td.id, _work())
            return {
                "status": "accepted",
                "task_id": task_id,
                "message": (
                    f"Running in background. "
                    f"Call {task_tool_name}(task_id='{task_id}') to retrieve results."
                ),
            }

        t0 = time.monotonic()
        try:
            result = await active_executor.execute(td, kwargs)
            duration_ms = round((time.monotonic() - t0) * 1000, 1)
            await _observe(td.id, kwargs, result.rows, duration_ms, None, session_id)
            await _emit_runtime_log(
                ctx,
                "info",
                {
                    "event": "tool.call.complete",
                    "tool": td.id,
                    "rows": len(result.rows),
                    "duration_ms": duration_ms,
                    "truncated": _result_truncated(result),
                },
            )
            # Agent-facing result: rows + count + a token estimate, plus the
            # truncation marker/note when the set was capped (by row cap, source
            # cap, or the per-call token budget).
            return _payload_for(result)
        except Exception as exc:
            # Every failure must be observed — not just ElliotError. A tool
            # backed by a REST source fails with httpx.HTTPStatusError /
            # ExecutorError / a timeout, none of which are ElliotError. If
            # those escaped unobserved the failed call would never reach the
            # audit log, so metrics reported a 100% success rate.
            duration_ms = round((time.monotonic() - t0) * 1000, 1)
            elliot_exc = (
                exc
                if isinstance(exc, ElliotError)
                else ElliotError("TOOL_EXECUTION_ERROR", str(exc))
            )
            await _observe(td.id, kwargs, [], duration_ms, str(elliot_exc), session_id)
            error_content = to_mcp_error_content(elliot_exc)
            await _emit_runtime_log(
                ctx,
                "warning",
                {"event": "tool.call.error", "tool": td.id, "code": elliot_exc.code},
            )
            raise ValueError(error_content["text"]) from exc

    _handler.__name__ = td.id
    _handler.__doc__ = td.description

    params = []
    for p in td.parameters:
        if p.type == "integer":
            base: Any = int
        elif p.type == "number":
            base = float
        elif p.type == "boolean":
            base = bool
        else:
            base = str
        # Carry the author's parameter description and allowed values into the
        # MCP inputSchema the agent reads. Without this, the contract the linter
        # enforces — every parameter described, closed value sets declared as
        # enums — never reaches the consuming agent, so it cannot tell what a
        # parameter means or which values are valid and guesses wrong (e.g.
        # passing "active" to a status that only accepts "open"). This is the
        # core of principle 1: tool descriptions, parameters included, are the
        # contract.
        field_kwargs: dict[str, Any] = {}
        if p.description.strip():
            field_kwargs["description"] = p.description.strip()
        if p.enum:
            field_kwargs["json_schema_extra"] = {"enum": list(p.enum)}
        annotation: Any = Annotated[base, Field(**field_kwargs)] if field_kwargs else base
        default = inspect.Parameter.empty if p.required else None
        params.append(
            inspect.Parameter(
                p.name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )
    if require_confirmation:
        params.append(
            inspect.Parameter(
                "confirm",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Annotated[
                    bool,
                    Field(
                        description=(
                            "Safety gate for this destructive operation. Leave false to have "
                            "the call rejected with CONFIRMATION_REQUIRED; set true only after "
                            "the user has authorised the change, then re-call to execute it."
                        )
                    ),
                ],
                default=False,
            )
        )
    object.__setattr__(
        _handler,
        "__signature__",
        inspect.Signature(params, return_annotation=dict[str, Any]),
    )
    _handler.__annotations__["return"] = dict[str, Any]

    mcp.tool(name=td.id, title=td.name, description=td.description, annotations=annotations)(
        _handler
    )


def _register_task_tool(
    mcp: FastMCP, task_store: TaskStore, task_tool_name: str = "elliot_get_task"
) -> None:
    """Register the background-task polling tool.

    Named ``{connector_slug}_get_task`` so it reads as part of the connector
    (and doesn't collide across connectors); falls back to the historical
    ``elliot_get_task`` when the connector has no slug.
    """

    @mcp.tool(
        name=task_tool_name,
        description=(
            "Poll the result of a background tool execution. "
            "Use when a previous tool call returned status='accepted' with a task_id. "
            "Returns status ('pending'|'running'|'completed'|'failed') and result when done."
        ),
    )
    def elliot_get_task(task_id: str) -> dict[str, Any]:
        """Retrieve background task status and result by task_id."""
        record = task_store.get(task_id)
        if record is None:
            raise ValueError(
                f"TASK_NOT_FOUND: No task with id '{task_id}'. "
                "Tasks expire after 1 hour. Check the task_id and retry."
            )
        return record.to_dict()


_FEEDBACK_OUTCOMES = ("success", "failure", "partial")


def _register_feedback_tool(
    mcp: FastMCP,
    store: ObservationStore,
    connector_slug: str | None,
    feedback_tool_name: str = "submit_feedback",
) -> None:
    """Register the agent-feedback tool — a built-in present on every connector.

    The agent calls it to tell the connector author how a tool behaved: why it
    was chosen, what was passed in and returned, and whether the call succeeded,
    failed, or only partly worked. Feedback is persisted to the observation
    store and surfaced in Studio's Agent Console.

    The name is namespaced under the connector's slug
    (``{slug}_submit_feedback``) so it reads as part of *this* connector and
    doesn't collide when an agent has several Elliot connectors connected at
    once. Connectors with no slug keep the plain ``submit_feedback`` name.
    """
    from elliot_core.errors import ElliotError, to_mcp_error_content

    annotations = ToolAnnotations(
        title="Submit agent feedback",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )

    @mcp.tool(
        name=feedback_tool_name,
        title="Submit agent feedback",
        description=(
            "Report how one of this connector's tools worked so the connector "
            "author can improve it. Call after using a tool when the result is "
            "worth noting — a clean success, a failure, or a partial result. "
            "Args: tool_id (the tool you used); outcome (one of 'success', "
            "'failure', 'partial'); why_chosen (why you picked this tool); "
            "input_summary (the input you passed); output_summary (what you got "
            "back); detail (failure description or any notes)."
        ),
        annotations=annotations,
    )
    async def submit_feedback(
        tool_id: str,
        outcome: str,
        why_chosen: str = "",
        input_summary: str = "",
        output_summary: str = "",
        detail: str = "",
    ) -> dict[str, Any]:
        normalized = (outcome or "").strip().lower()
        if normalized not in _FEEDBACK_OUTCOMES:
            exc = ElliotError(
                "VALIDATION_INVALID_OUTCOME",
                (f"outcome must be one of {list(_FEEDBACK_OUTCOMES)}; got {outcome!r}."),
                {"field": "outcome", "allowed": list(_FEEDBACK_OUTCOMES)},
            )
            raise ValueError(to_mcp_error_content(exc)["text"])

        session_id, identity = _current_session_and_identity(mcp)

        def _persist() -> None:
            store.write_feedback(
                tool_id=tool_id,
                outcome=normalized,
                session_id=session_id,
                connector_slug=connector_slug,
                why_chosen=why_chosen,
                input_summary=input_summary,
                output_summary=output_summary,
                detail=detail,
                agent_identity=identity,
            )

        try:
            await run_in_threadpool(_persist)
        except Exception as exc:
            elliot_exc = ElliotError("FEEDBACK_WRITE_FAILED", str(exc))
            raise ValueError(to_mcp_error_content(elliot_exc)["text"]) from exc

        log.info("agent.feedback.recorded", tool_id=tool_id, outcome=normalized)
        return {
            "status": "recorded",
            "tool_id": tool_id,
            "outcome": normalized,
            "message": "Feedback recorded for the connector author.",
        }


_REDACTED = "***"
# Nested mapping keys that may hold a secret value under an arbitrary,
# author-chosen sub-key. We mask the whole block rather than relying on a
# sub-key name check.
_SECRET_BLOCK_KEYS = ("auth", "headers", "config_snapshot", "credentials")


def _redact_secret_blocks(node: Any) -> None:
    """Recursively mask whole ``auth`` / ``headers`` / ``credentials`` blocks.

    ``resolve_secrets`` may have substituted literal secret values into a
    source's auth block or custom request headers. Header/field names are
    author-chosen (``X-Internal-Key``, ``X-Tenant``) so a key-name blocklist
    cannot catch them — mask the whole sub-mapping structurally instead.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() in _SECRET_BLOCK_KEYS and value is not None:
                node[key] = _REDACTED
            else:
                _redact_secret_blocks(value)
    elif isinstance(node, list):
        for item in node:
            _redact_secret_blocks(item)


def _register_resources(mcp: FastMCP, cfg: Any, executor: ToolExecutor, json: Any) -> None:
    """Register MCP Resources: connector schema, per-tool sample rows, source status."""
    from elliot_core.types import ConnectorConfig

    c: ConnectorConfig = cfg

    @mcp.resource("connector://schema")
    def connector_schema() -> str:
        """Full connector definition including all sources, tools, and skills.

        The in-memory ``ConnectorConfig`` has had ``resolve_secrets`` applied
        to it during loader hydration, so source URLs / auth headers may
        contain literal secret values. Redaction is layered:

        1. ``redact_value`` masks any key whose name looks secret-bearing
           (substring match — catches ``private_key``, ``db_password``, …).
        2. The entire ``auth`` block of every source is masked structurally —
           a connector author can name an auth field anything, so a key-name
           check alone is not enough.
        3. Any ``headers`` mapping is masked structurally — custom header
           names (``X-Internal-Key``, ``X-Tenant``) won't match a blocklist.
        4. URL userinfo / token-bearing query params are stripped.
        """
        from elliot_core.redaction import redact_url, redact_value

        snapshot = redact_value(c.model_dump())
        for source in snapshot.get("sources", []) or []:
            if not isinstance(source, dict):
                continue
            if source.get("url"):
                source["url"] = redact_url(source.get("url"))
            _redact_secret_blocks(source)
        return json.dumps(snapshot, indent=2, default=str)

    for tool_def in c.tools:
        _register_sample_resource(mcp, executor, tool_def, json)

    for source in c.sources:
        _register_source_status_resource(mcp, source)


def _register_sample_resource(
    mcp: FastMCP, executor: ToolExecutor, tool_def: Any, json: Any
) -> None:
    tool_id = tool_def.id
    tool_name = tool_def.name

    @mcp.resource(
        f"connector://sample/{tool_id}",
        description=f"Sample rows from {tool_name} (up to 5). Does not count against the agent's context budget.",
    )
    async def sample_resource() -> str:
        try:
            result = await executor.execute(tool_def, {})
            sample = result.rows[:5]
            return json.dumps({"tool": tool_id, "sample_rows": sample}, default=str)
        except Exception as exc:
            return json.dumps({"tool": tool_id, "error": str(exc)})

    sample_resource.__name__ = f"sample_{tool_id}"


def _register_source_status_resource(mcp: FastMCP, source: Any) -> None:
    source_id = source.id
    source_name = source.name
    table_name = getattr(source, "table_name", None) or source.id

    @mcp.resource(
        f"source://{source_id}/status",
        description=f"Connectivity status for source '{source_name}'.",
    )
    def source_status() -> str:
        import json as _json

        return _json.dumps(
            {
                "source_id": source_id,
                "name": source_name,
                "type": source.type,
                # `table_name` is what the connector's tool SQL is authored
                # against — surface it so agents can confirm which table
                # name matches which configured source.
                "table_name": table_name,
            }
        )

    source_status.__name__ = f"status_{source_id}"


def _register_prompts(mcp: FastMCP, cfg: Any) -> None:
    """Expose each SkillDefinition as an MCP Prompt so agents can retrieve step-by-step workflows."""
    from elliot_core.types import ConnectorConfig

    c: ConnectorConfig = cfg
    for skill in c.skills:
        _register_skill_prompt(mcp, skill)


def _register_skill_prompt(mcp: FastMCP, skill: Any) -> None:
    skill_id = skill.id
    skill_name = skill.name
    skill_description = skill.description
    steps = skill.steps
    input_params = skill.input_parameters

    param_names = [p.name for p in input_params]

    def _make_prompt_fn(params: list[str]) -> Any:
        if not params:

            def prompt_fn() -> list[dict[str, Any]]:
                step_lines = "\n".join(
                    f"  Step {i + 1} ({s.alias}): call {s.tool_id} with {s.params}"
                    for i, s in enumerate(steps)
                )
                return [
                    {
                        "role": "user",
                        "content": (
                            f"Execute the '{skill_name}' workflow.\n\nSteps:\n{step_lines}"
                        ),
                    }
                ]

            prompt_fn.__name__ = skill_id
            prompt_fn.__doc__ = skill_description
            return prompt_fn
        else:

            def prompt_fn_with_args(**kwargs: str) -> list[dict[str, Any]]:
                step_lines = "\n".join(
                    f"  Step {i + 1} ({s.alias}): call {s.tool_id} with {s.params}"
                    for i, s in enumerate(steps)
                )
                args_display = ", ".join(f"{k}={v}" for k, v in kwargs.items())
                return [
                    {
                        "role": "user",
                        "content": (
                            f"Execute '{skill_name}' with inputs: {args_display}\n\nSteps:\n{step_lines}"
                        ),
                    }
                ]

            # Build signature so FastMCP can introspect parameter names,
            # and also set __annotations__ so pydantic's validate_call can
            # resolve type hints via typing.get_type_hints.
            sig_params = [
                inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=str)
                for name in params
            ]
            object.__setattr__(prompt_fn_with_args, "__signature__", inspect.Signature(sig_params))
            prompt_fn_with_args.__annotations__ = {name: str for name in params}
            prompt_fn_with_args.__annotations__["return"] = list[dict[str, Any]]
            prompt_fn_with_args.__name__ = skill_id
            prompt_fn_with_args.__doc__ = skill_description
            return prompt_fn_with_args

    prompt_fn = _make_prompt_fn(param_names)
    mcp.prompt(name=skill_id, description=skill_description)(prompt_fn)


def create_app(
    connector_path: str | None = None,
    secrets: dict[str, str] | None = None,
) -> FastAPI:
    # Default MUST match where elliot_export_connector writes and where
    # elliot_start_runtime points (.elliot/connector.json) — otherwise the
    # runtime looks in the wrong place and starts with no connector.
    connector_path = connector_path or os.environ.get("ELLIOT_CONNECTOR", ".elliot/connector.json")
    secrets = secrets or {}
    audit_path = os.environ.get("ELLIOT_AUDIT_LOG", ".elliot/audit.ndjson")
    sessions_path = os.environ.get("ELLIOT_SESSIONS_LOG", ".elliot/sessions.ndjson")
    db_url = os.environ.get("ELLIOT_DB_URL", "sqlite:///.elliot/observations.db")

    try:
        config = _cache.get(connector_path)
    except ConnectorLoadError:
        # No connector at this path yet. Return a minimal app so the module
        # still imports — but mount /mcp so clients get an actionable 503
        # instead of a bare 404, and re-check the connector on every /health
        # call so an operator can see once one becomes available.
        _app = FastAPI(redirect_slashes=False)
        _path = connector_path or ""

        def _no_connector_error() -> dict[str, dict[str, str]]:
            return {
                "error": {
                    "code": "RUNTIME_NO_CONNECTOR",
                    "message": (
                        f"The connector runtime has no connector loaded (looked for "
                        f"'{_path}'). Build and export a connector with "
                        f"elliot_build_connector + elliot_export_connector, then start "
                        f"the runtime with elliot_start_runtime."
                    ),
                }
            }

        @_app.get("/health")
        async def _health() -> dict[str, str]:
            try:
                _cache.get(_path)
            except ConnectorLoadError:
                return {"status": "no_connector", "connector": _path}
            # A connector has appeared since startup — the runtime must be
            # restarted (elliot_start_runtime) to actually serve it.
            return {"status": "connector_available", "connector": _path}

        @_app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
        @_app.api_route("/mcp/", methods=["GET", "POST", "DELETE", "OPTIONS"])
        @_app.api_route("/mcp/{rest:path}", methods=["GET", "POST", "DELETE", "OPTIONS"])
        async def _mcp_unavailable() -> JSONResponse:
            return JSONResponse(status_code=503, content=_no_connector_error())

        # The /v1/* observability + task routes only exist on the connector-loaded
        # app. Without this catch-all, Studio's Dashboard / Agent Console / Metrics
        # get a bare 404 (rendered as "no data yet") and nothing signals that the
        # runtime is simply waiting for a connector. Return the same actionable 503
        # so Studio can show a real empty state.
        @_app.api_route(
            "/v1/{rest:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        )
        async def _v1_unavailable() -> JSONResponse:
            return JSONResponse(status_code=503, content=_no_connector_error())

        return _app

    executor = ToolExecutor(config, secrets)
    audit = AuditLog(audit_path)
    tracker = SessionTracker(sessions_path)
    store = ObservationStore(db_url)

    # Per-user auth: a vault + executor pool serve per-user credentials. The
    # pool is a no-op passthrough for connectors whose sources are all
    # shared-auth, so single-tenant connectors behave exactly as before.
    vault_path = os.environ.get("ELLIOT_VAULT_DB", ".elliot/credentials.db")
    vault = CredentialVault(vault_path)
    pool = ExecutorPool(config, secrets, vault=vault)

    mcp = create_runtime_server(
        config, executor, audit=audit, tracker=tracker, store=store, executor_pool=pool
    )

    _mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        # Fail-closed: raise if ELLIOT_API_KEY is unset in production/staging,
        # otherwise log a warning. The helper decides which.
        enforce_auth_configured("connector-runtime")
        sweeper = asyncio.create_task(_session_idle_sweeper(tracker, store))
        async with mcp.session_manager.run():
            yield
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sweeper
        # Flush any still-open agent sessions so the trace survives shutdown.
        with contextlib.suppress(Exception):
            tracker.flush_all()
        # Audit H7: cancel any in-flight background tasks so we don't leave
        # them in `running` state after the loop closes.
        with contextlib.suppress(Exception):
            await get_task_store().cancel_all()

    limiter = _build_limiter()
    # redirect_slashes=False so that a POST to /mcp does not 307-redirect to
    # /mcp/. Strict MCP clients (Codex / rmcp) discard the POST body on the
    # redirect and the JSON-RPC `initialize` handshake fails. Auto-config in
    # `elliot connect` and `elliot_get_connection_config` writes the URL with
    # a trailing slash so clients reach FastMCP directly.
    app = FastAPI(lifespan=lifespan, redirect_slashes=False)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    # Wire ElliotError + generic exception handlers so raw exceptions and DB
    # errors are returned as structured {error:{code,message}} JSON instead of
    # leaking a default Starlette 500 with a stack trace.
    register_error_handlers(app)
    # Order matters: Starlette inserts each add_middleware at index 0, so the
    # LAST call wraps the others. Final stack (outermost first):
    #   CORS  →  BodySizeLimit  →  SlowAPI  →  ApiKey  →  app
    # CORS first so preflight (OPTIONS) is answered before anything else;
    # body-size cap rejects oversized requests before they reach rate-limit
    # accounting; SlowAPI rate-limits both authed and unauthed traffic so
    # the auth check itself can't be brute-forced; ApiKey is innermost so
    # it runs on the surviving requests only.
    app.add_middleware(ApiKeyMiddleware)
    # Audit finding H5: the rate limiter was instantiated but never enforced
    # because SlowAPIMiddleware was missing. Wire it now so the
    # ELLIOT_RATE_LIMIT env var actually takes effect on every route.
    app.add_middleware(SlowAPIMiddleware)
    # Body-size cap (audit H7). Outer real middleware so a huge request is
    # rejected before any downstream layer materialises it.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=_max_body_bytes())
    # Bind the parsed AX agent identity to a contextvar so tool handlers can
    # attribute calls to a specific client/model rather than a generic 'mcp'.
    app.add_middleware(AgentIdentityMiddleware)
    # End-user identity (auth boundary 1). Two modes:
    #   * Default: trust an X-Elliot-User header (gateway / manual config).
    #   * ELLIOT_MCP_OAUTH=1: Elliot is the MCP OAuth authorization server, so a
    #     client like Claude shows a native Connect button; the bearer it mints
    #     carries the user id and a 401 challenge advertises the metadata. The
    #     same Connect chains the upstream per-user connect (boundary 2).
    mcp_oauth_enabled = os.environ.get("ELLIOT_MCP_OAUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    token_store = TokenStore() if mcp_oauth_enabled else None
    if token_store is not None:
        app.add_middleware(MCPAuthMiddleware, store=token_store)
    else:
        app.add_middleware(UserIdentityMiddleware)
    studio_origin = os.environ.get("ELLIOT_STUDIO_ORIGIN", "http://localhost:5173")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[studio_origin],
        allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-Elliot-Key",
            "Authorization",
            "x-client-name",
            "Mcp-Session-Id",
            # MCP TS SDK >=1.10 sends Mcp-Protocol-Version on every call;
            # without it the browser preflight fails.
            "Mcp-Protocol-Version",
            "X-Elliot-User",
        ],
    )
    # Per-user OAuth connect/callback endpoints (auth boundary 2).
    register_oauth_routes(app, config, secrets, vault, pool)
    # MCP OAuth authorization server (auth boundary 1) + chained upstream connect.
    if token_store is not None:
        register_mcp_oauth(app, config, secrets, vault, pool, token_store)
    app.mount("/mcp", _mcp_app)

    openai_router = APIRouter(prefix="/v1")
    register_openai_routes(openai_router, config, executor, audit)
    app.include_router(openai_router)

    @app.get("/v1/audit")
    async def get_audit(n: int = 100) -> list[dict[str, Any]]:
        return audit.tail(n)

    @app.get("/v1/sessions")
    async def get_sessions(n: int = 20) -> list[dict[str, Any]]:
        return tracker.tail(n)

    @app.get("/v1/sessions/stream")
    async def stream_sessions(request: Request) -> StreamingResponse:
        """Server-Sent Events: a snapshot, then a frame per session update."""

        async def _events() -> AsyncIterator[str]:
            queue = tracker.subscribe()
            try:
                snapshot = json.dumps(tracker.tail(20), default=str)
                yield f"event: snapshot\ndata: {snapshot}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    except TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    yield f"event: update\ndata: {json.dumps(payload, default=str)}\n\n"
            finally:
                tracker.unsubscribe(queue)

        return StreamingResponse(
            _events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/trace/ingest")
    async def ingest_trace(payload: IngestPayload) -> dict[str, Any]:
        """Receive a normalized trace from a harness hook adapter.

        Claude Code / Codex / Cursor adapters POST the agent's reasoning, the
        user's prompt and the tool calls here — data MCP traffic cannot see.
        The trace is merged into the live console feed and the metrics store.
        """
        from elliot_core.redaction import redact_audit_arguments

        from .session_tracker import SessionEvent

        slug = getattr(config, "slug", None)
        session_id = f"{payload.harness}:{payload.session_id}"
        identity = {
            "client": payload.harness,
            "client_version": payload.harness_version,
            "model": payload.model,
            "modality": None,
            "user_agent": None,
        }
        events = [
            SessionEvent(
                ts=ev.ts or time.time(),
                type="tool_call",
                tool_id=ev.tool_id,
                arguments=redact_audit_arguments(ev.arguments),
                result_rows=ev.result_rows,
                result_token_estimate=ev.result_token_estimate or None,
                duration_ms=ev.duration_ms,
                error=ev.error,
                result_preview=ev.result_preview,
                reasoning=ev.reasoning,
            )
            for ev in payload.events
        ]

        def _persist() -> None:
            """Tracker + observation-store writes are blocking I/O — keep them
            off the event loop so a large ingest can't stall the server."""
            tracker.append_ingested(
                session_id,
                identity,
                events,
                user_prompt=payload.user_prompt,
                final_output=payload.final_output,
            )
            with contextlib.suppress(Exception):
                store.open_session(
                    session_id,
                    agent_hint=payload.harness,
                    connector_slug=slug,
                    agent_identity=identity,
                )
                for ev in payload.events:
                    store.write_tool_call(
                        session_id=session_id,
                        tool_id=ev.tool_id,
                        arguments=ev.arguments,
                        result_row_count=ev.result_rows,
                        result_token_estimate=ev.result_token_estimate,
                        duration_ms=ev.duration_ms,
                        error=ev.error,
                        connector_slug=slug,
                    )

        await run_in_threadpool(_persist)
        return {"status": "ok", "session_id": session_id, "events": len(events)}

    @app.get("/v1/metrics/token-efficiency")
    async def token_efficiency() -> dict[str, Any]:
        rows = store.token_efficiency()
        tools = [
            {
                **row,
                "risk": (
                    "high"
                    if (row["avg_tokens"] or 0) > 1000
                    else "medium"
                    if (row["avg_tokens"] or 0) > 300
                    else "low"
                ),
                "suggestion": _suggest(
                    str(row["tool_id"]),
                    float(row["avg_tokens"] or 0),
                    float(row["max_tokens"] or 0),
                ),
            }
            for row in rows
        ]
        return {"tools": tools, "sessions_analysed": len(store.recent_sessions(200))}

    @app.get("/v1/metrics/harnesses")
    async def harness_metrics() -> dict[str, Any]:
        """Per-harness rollup — how Claude Code / Codex / Cursor / MCP traffic
        each exercise this connector."""
        return {"harnesses": store.harness_breakdown()}

    @app.get("/v1/feedback")
    async def get_feedback(n: int = 50, connector_slug: str | None = None) -> dict[str, Any]:
        """Agent feedback submitted via the built-in submit_feedback tool."""
        return {"feedback": store.recent_feedback(n, connector_slug=connector_slug)}

    @app.post("/v1/observations/prune")
    async def prune_observations() -> dict[str, int]:
        return {"deleted": store.prune()}

    task_store = get_task_store()

    @app.get("/v1/tasks")
    async def list_tasks(limit: int = 20) -> list[dict[str, Any]]:
        return task_store.list_recent(limit)

    @app.get("/v1/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, Any]:
        record = task_store.get(task_id)
        if record is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return record.to_dict()

    @app.post("/v1/tasks/prune")
    async def prune_tasks() -> dict[str, int]:
        return {"deleted": task_store.prune()}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "connector": connector_path or ""}

    @app.get("/v1/health")
    async def detailed_health() -> dict[str, Any]:
        sources_out: list[dict[str, Any]] = []
        all_ok = True
        for source in config.sources:
            try:
                t0 = time.monotonic()
                await _ping_source(source)
                latency = round((time.monotonic() - t0) * 1000, 1)
                sources_out.append(
                    {"id": source.id, "type": source.type, "status": "ok", "latency_ms": latency}
                )
            except Exception as exc:
                sources_out.append(
                    {"id": source.id, "type": source.type, "status": "error", "error": str(exc)}
                )
                all_ok = False

        db_status = "ok"
        db_count = 0
        try:
            db_count = len(store.recent_tool_calls(10000))
        except Exception:
            db_status = "error"
            all_ok = False

        return {
            "status": "healthy" if all_ok else "degraded",
            "connector": {
                "slug": config.slug,
                "name": config.name,
                "version": config.version,
                "tool_count": len(config.tools),
                "source_count": len(config.sources),
            },
            "sources": sources_out,
            "observation_db": {"status": db_status, "tool_calls_total": db_count},
            "uptime_seconds": int(time.time() - _start_time),
        }

    return app


async def _ping_source(source: Any) -> None:
    """Lightweight reachability check for a source."""
    from urllib.parse import urlsplit

    from elliot_core.http import SSRFError, safe_client, validate_url

    if source.type == "rest":
        url = source.url or ""
        try:
            ips = validate_url(url)
        except SSRFError as exc:
            # /v1/health must not be usable as an SSRF probe — surface the
            # block to the caller without making the HEAD request.
            raise RuntimeError(f"SSRF_BLOCKED: {exc.message}") from exc
        # Pin the connection to the validated IP so a DNS rebind between
        # validate_url and the HEAD request can't redirect to a private host.
        host = urlsplit(url).hostname or ""
        pinned_hosts = {host: ips[0]} if (host and ips) else None
        async with safe_client(timeout=3, pinned_hosts=pinned_hosts) as client:
            await client.head(url)
    # DB and file sources: skip ping — they're checked when tools execute


# Entry point: uvicorn elliot_connector_runtime.server:app
app = create_app()
