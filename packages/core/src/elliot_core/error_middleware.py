from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from elliot_core.errors import ElliotError

_CODE_TO_STATUS: dict[str, int] = {
    "NOT_FOUND": 404,
    "VALIDATION": 422,
    "AUTH": 401,
    "FORBIDDEN": 403,
    "TIMEOUT": 504,
    "UPSTREAM": 502,
    "RATE_LIMIT": 429,
}


def _status_for(error: ElliotError) -> int:
    code = error.code or ""
    for prefix, status in _CODE_TO_STATUS.items():
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
