from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from elliot_core.errors import ElliotError

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
    """Wire ElliotError and generic exception handlers into a FastAPI app."""

    @app.exception_handler(ElliotError)
    async def _elliot_handler(request: Request, exc: ElliotError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "detail": exc.detail,
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
