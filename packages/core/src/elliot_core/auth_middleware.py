from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_BYPASS_PATHS = {"/healthz", "/health", "/"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Rejects requests missing X-Elliot-Key when ELLIOT_API_KEY env var is set.

    Also accepts ``Authorization: Bearer <key>`` so browser clients that cannot
    set custom request headers from a cross-origin context can authenticate.
    Comparison is constant-time to prevent timing attacks against the API key.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        key = os.environ.get("ELLIOT_API_KEY")
        # OPTIONS preflight is handled by CORSMiddleware; skip auth so that
        # cross-origin browser requests can complete their preflight check.
        if not key or request.method == "OPTIONS" or request.url.path in _BYPASS_PATHS:
            return await call_next(request)
        provided = request.headers.get("X-Elliot-Key", "")
        if not provided:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided = auth_header[len("Bearer ") :]
        if not hmac.compare_digest(provided.encode("utf-8"), key.encode("utf-8")):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
