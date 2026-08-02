from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .agent_identity import (
    parse_agent_identity,
    reset_current_agent_identity,
    set_current_agent_identity,
)
from .session_handle import (
    SESSION_HEADER,
    get_current_session_handle,
    reset_current_session_handle,
    resolve_inbound,
    set_current_session_handle,
)
from .user_identity import (
    parse_user_id,
    reset_current_user_id,
    set_current_user_id,
)

log = structlog.get_logger("http")


class RequestLoggingMiddleware:
    """Tag each request with an id, log it, and surface it as X-Request-Id.

    Implemented as pure ASGI rather than BaseHTTPMiddleware: the latter runs
    the downstream app in a separate task, so the request_id contextvar bound
    here would never reach the route handlers' log lines.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        t0 = time.monotonic()
        status_code = 500

        async def _send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                duration_ms=round((time.monotonic() - t0) * 1000, 1),
            )


class AgentIdentityMiddleware:
    """Bind the parsed agent identity to a contextvar for the request lifetime.

    Implemented as a pure ASGI middleware (not BaseHTTPMiddleware) because the
    latter runs the downstream app in a separate task, which would isolate the
    contextvar from FastMCP tool handlers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        identity = parse_agent_identity(headers)
        token = set_current_agent_identity(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            with contextlib.suppress(LookupError, ValueError):
                reset_current_agent_identity(token)


class ElliotSessionMiddleware:
    """Resolve the Elliot session handle for the request and echo it back.

    Protocol sessions no longer exist on the 2026-07-28 MCP path, so Elliot
    tracks its own: the handle is resolved from headers (or minted), bound to
    a contextvar for the request lifetime, and echoed as the
    ``Elliot-Session-Id`` response header. The response header is read from
    the contextvar *at send time* so a handle upgraded mid-request from MCP
    ``_meta`` (see ``mcp_compat.session_meta_middleware``) wins over the one
    resolved here. Pure ASGI for the same contextvar-propagation reason as
    the neighbouring middlewares.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        handle = resolve_inbound(headers)
        token = set_current_session_handle(handle)

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                current = get_current_session_handle() or handle
                out_headers = list(message.get("headers", []))
                out_headers.append(
                    (SESSION_HEADER.lower().encode("latin-1"), current.value.encode("latin-1"))
                )
                message = {**message, "headers": out_headers}
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            with contextlib.suppress(LookupError, ValueError):
                reset_current_session_handle(token)


class UserIdentityMiddleware:
    """Bind the end-user id (auth boundary 1) to a contextvar per request.

    Pure ASGI (not BaseHTTPMiddleware) so the contextvar survives into FastMCP
    tool handlers, which run in the same task. The user id is read from the
    ``X-Elliot-User`` header; per-user credential resolution downstream keys the
    vault on it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        user_id = parse_user_id(headers)
        token = set_current_user_id(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            with contextlib.suppress(LookupError, ValueError):
                reset_current_user_id(token)


_RegisteredCallNext = Callable[[Request], Awaitable[Response]]
__all__ = [
    "RequestLoggingMiddleware",
    "AgentIdentityMiddleware",
    "ElliotSessionMiddleware",
    "UserIdentityMiddleware",
    "_RegisteredCallNext",
]
