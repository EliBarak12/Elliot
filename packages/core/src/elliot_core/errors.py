from __future__ import annotations

from typing import Any


class ElliotError(Exception):
    code: str = "INTERNAL_ERROR"

    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


# ── Typed subclasses ────────────────────────────────────────────────────────


class ValidationError(ElliotError):
    """Bad input from caller (maps to HTTP 422)."""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__("VALIDATION_ERROR", message, detail)


class NotFoundError(ElliotError):
    """Requested resource does not exist (maps to HTTP 404)."""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__("NOT_FOUND", message, detail)


class AuthError(ElliotError):
    """Missing or invalid credentials (maps to HTTP 401)."""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__("AUTH_FAILED", message, detail)


class SourceFetchError(ElliotError):
    """Upstream data source returned an error (maps to HTTP 502)."""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__("UPSTREAM_FETCH_FAILED", message, detail)


class RateLimitError(ElliotError):
    """Rate limit exceeded (maps to HTTP 429)."""

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__("RATE_LIMIT_EXCEEDED", message, detail)


# ── Error code constants ────────────────────────────────────────────────────

INVALID_TOOL = "INVALID_TOOL"
MISSING_PARAM = "MISSING_PARAM"
INVALID_PARAM_TYPE = "INVALID_PARAM_TYPE"
SOURCE_FETCH_FAILED = "UPSTREAM_FETCH_FAILED"
FILE_NOT_FOUND = "FILE_NOT_FOUND"
FILE_PARSE_ERROR = "FILE_PARSE_ERROR"
TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
TOOL_NAME_CONFLICT = "TOOL_NAME_CONFLICT"
INVALID_CONNECTOR = "INVALID_CONNECTOR"
SESSION_LOAD_FAILED = "SESSION_LOAD_FAILED"
SESSION_SAVE_FAILED = "SESSION_SAVE_FAILED"


# ── Helpers ────────────────────────────────────────────────────────────────


def is_elliot_error(err: object) -> bool:
    return isinstance(err, ElliotError)


def to_mcp_error_content(err: object) -> dict[str, str]:
    if isinstance(err, ElliotError):
        return {"type": "text", "text": f"[{err.code}] {err.message}"}
    return {"type": "text", "text": f"Unexpected error: {err}"}
