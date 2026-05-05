# Task 058 — FastAPI Error Middleware

## Goal
Add a global exception handler to both FastAPI apps that converts `ElliotError` subclasses (and unexpected exceptions) into consistent JSON error responses, and returns MCP-compatible error content for tool call failures.

## Background
Task 052 defined `ElliotError` in `elliot_core/errors.py`. The FastAPI apps currently let exceptions propagate as HTTP 500 with unstructured tracebacks. This task wires up a handler so every error — validation, auth, executor, loader — returns a predictable envelope.

## File to create

### `packages/connector-runtime/src/elliot_connector_runtime/error_middleware.py`

```python
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from elliot_core.errors import ElliotError


# Map ElliotError.code prefixes to HTTP status codes
_CODE_TO_STATUS: dict[str, int] = {
    "NOT_FOUND": 404,
    "VALIDATION": 422,
    "AUTH": 401,
    "FORBIDDEN": 403,
    "TIMEOUT": 504,
    "UPSTREAM": 502,
}


def _status_for(error: ElliotError) -> int:
    code = getattr(error, "code", "") or ""
    for prefix, status in _CODE_TO_STATUS.items():
        if code.startswith(prefix):
            return status
    return 500


def register_error_handlers(app: FastAPI) -> None:
    """Call inside create_app() after app is constructed."""

    @app.exception_handler(ElliotError)
    async def elliot_error_handler(request: Request, exc: ElliotError) -> JSONResponse:
        status = _status_for(exc)
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": getattr(exc, "code", "INTERNAL_ERROR"),
                    "message": str(exc),
                    "details": getattr(exc, "details", None),
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        from .logging_config import get_logger
        log = get_logger("error_handler")
        log.exception("unhandled_error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred.",
                    "details": None,
                }
            },
        )
```

## Same pattern for `elliot-mcp-plugin`

Create `packages/mcp-plugin/src/elliot_mcp_plugin/error_middleware.py` with identical content (adjust the import path for `logging_config`).

## Wire into `server.py`

```python
from .error_middleware import register_error_handlers

def create_app(...) -> FastAPI:
    ...
    app = FastAPI(lifespan=lifespan)
    register_error_handlers(app)   # ← add this line
    ...
```

## MCP tool error format

When a tool execution fails inside `executor.py`, raise a typed error:

```python
from elliot_core.errors import ElliotError

class ExecutorError(ElliotError):
    code = "UPSTREAM_FETCH_FAILED"
```

The MCP SDK wraps tool exceptions automatically as `isError: true` content — no extra work needed at the MCP layer.

## Error code convention

| Prefix | Meaning | HTTP |
|---|---|---|
| `NOT_FOUND` | Resource missing | 404 |
| `VALIDATION` | Bad input | 422 |
| `AUTH` | Missing/invalid credentials | 401 |
| `FORBIDDEN` | Credential present but denied | 403 |
| `TIMEOUT` | Upstream took too long | 504 |
| `UPSTREAM` | Upstream returned error | 502 |
| anything else | Unexpected | 500 |

## Tests (`test_error_middleware.py`)

```python
from fastapi.testclient import TestClient
from elliot_connector_runtime.server import create_app
from elliot_core.errors import ElliotError

class _NotFound(ElliotError):
    code = "NOT_FOUND_THING"

def test_elliot_error_returns_404(connector_file):
    app = create_app(connector_path=str(connector_file), secrets={})

    @app.get("/raise")
    async def _raise():
        raise _NotFound("thing not found")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/raise")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND_THING"

def test_generic_error_returns_500(connector_file):
    app = create_app(connector_path=str(connector_file), secrets={})

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("oops")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
```
