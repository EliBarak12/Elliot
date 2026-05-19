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


_RegisteredCallNext = Callable[[Request], Awaitable[Response]]
__all__ = [
    "RequestLoggingMiddleware",
    "AgentIdentityMiddleware",
    "_RegisteredCallNext",
]
