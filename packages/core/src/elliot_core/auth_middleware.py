from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_BYPASS_PATHS = {"/healthz", "/"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Rejects requests missing X-Elliot-Key when ELLIOT_API_KEY env var is set."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        key = os.environ.get("ELLIOT_API_KEY")
        if not key or request.url.path in _BYPASS_PATHS:
            return await call_next(request)
        provided = request.headers.get("X-Elliot-Key", "")
        if provided != key:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
