from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .agent_identity import (
    parse_agent_identity,
    reset_current_agent_identity,
    set_current_agent_identity,
)

log = structlog.get_logger("http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        request_id = str(uuid.uuid4())[:8]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - t0) * 1000, 1)

        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-Id"] = request_id
        return response


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
