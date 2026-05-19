from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

import structlog
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)

_BYPASS_PATHS = {"/healthz", "/health", "/"}
# Environments where missing auth configuration is a hard failure.
_PROTECTED_ENVS = {"production", "staging"}


def enforce_auth_configured(service_name: str) -> None:
    """Fail fast if API-key auth is unconfigured in a protected environment.

    Services call this at startup. When ``ELLIOT_ENV`` is ``production`` or
    ``staging`` (case-insensitive) and ``ELLIOT_API_KEY`` is empty/unset, the
    middleware would silently pass every request through — auth failing open.
    In that case this raises :class:`RuntimeError`. In dev/test/blank
    environments it only logs a structlog warning so local workflows are not
    blocked.

    Args:
        service_name: Human-readable name of the calling service, for logs.
    """
    api_key = os.environ.get("ELLIOT_API_KEY", "").strip()
    env = os.environ.get("ELLIOT_ENV", "").strip().lower()
    if api_key:
        return
    if env in _PROTECTED_ENVS:
        raise RuntimeError(
            f"{service_name}: ELLIOT_API_KEY is not set but ELLIOT_ENV='{env}'. "
            "Refusing to start with authentication disabled in a "
            f"{env} environment. Set ELLIOT_API_KEY."
        )
    log.warning(
        "auth.unconfigured",
        service=service_name,
        env=env or "(unset)",
        detail="ELLIOT_API_KEY is not set; API requests will NOT be authenticated",
    )


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
            return JSONResponse(
                {
                    "error": {
                        "code": "AUTH_FAILED",
                        "message": "Missing or invalid API key.",
                        "detail": None,
                    }
                },
                status_code=401,
            )
        return await call_next(request)
