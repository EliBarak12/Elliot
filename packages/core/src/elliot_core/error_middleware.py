from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from elliot_core.errors import ElliotError
from elliot_core.redaction import redact_value

# Audit Medium 30: previously the code → status map used prefix matching
# (``"AUTH"`` → 401). That accidentally classified codes like ``AUTH_OK_FORCED``
# as 401, so we keep an exact-match table here and only fall back to a small
# allow-listed prefix family for the validation case.
_CODE_TO_STATUS: dict[str, int] = {
    "NOT_FOUND": 404,
    "VALIDATION_ERROR": 422,
    "INVALID_TOOL": 422,
    "INVALID_PARAM_TYPE": 422,
    "INVALID_SQL": 422,
    "INVALID_IDENTIFIER": 422,
    "MISSING_PARAM": 422,
    "AUTH_FAILED": 401,
    "FORBIDDEN": 403,
    "PATH_ESCAPE": 403,
    "SSRF_BLOCKED": 403,
    "TIMEOUT": 504,
    "UPSTREAM_FETCH_FAILED": 502,
    "RATE_LIMIT_EXCEEDED": 429,
    "BODY_TOO_LARGE": 413,
}

# Narrow prefix fallbacks — only the families where we genuinely want every
# member to share a status.
_PREFIX_FALLBACK: tuple[tuple[str, int], ...] = (
    ("VALIDATION_", 422),
    ("AUTH_", 401),
)


def _status_for(error: ElliotError) -> int:
    code = error.code or ""
    if code in _CODE_TO_STATUS:
        return _CODE_TO_STATUS[code]
    for prefix, status in _PREFIX_FALLBACK:
        if code.startswith(prefix):
            return status
    return 500


def register_error_handlers(app: FastAPI) -> None:
    """Wire ElliotError and generic exception handlers into a FastAPI app.

    All handlers emit the same ``{"error": {"code", "message", "detail"}}``
    shape. The explicit ``RequestValidationError`` / ``HTTPException`` handlers
    are required because the catch-all ``Exception`` handler would otherwise
    shadow FastAPI's built-ins and turn 422s / 404s into opaque 500s.
    """

    @app.exception_handler(ElliotError)
    async def _elliot_handler(request: Request, exc: ElliotError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    # detail is free-form Any and may carry SQL fragments or
                    # PII — redact before it reaches the client.
                    "detail": redact_value(exc.detail),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed.",
                    "detail": redact_value(exc.errors()),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": str(exc.detail) if exc.detail else "Request failed.",
                    "detail": None,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _generic_handler(request: Request, exc: Exception) -> JSONResponse:
        from elliot_core.logging_config import get_logger

        get_logger("error_handler").exception("unhandled_error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred.",
                    "detail": None,
                }
            },
        )
