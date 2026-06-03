# Task 057 — Structured Logging

## Goal
Add consistent, structured JSON logging to both Python services (`elliot-mcp-plugin` and `elliot-connector-runtime`) using `structlog`, with FastAPI request/response middleware and log-level control via environment variable.

## Package targets
- `packages/mcp-plugin/src/elliot_mcp_plugin/logging_config.py`
- `packages/connector-runtime/src/elliot_connector_runtime/logging_config.py`
- Middleware wired into both `server.py` files

## File to create (shared pattern, one copy per package)

### `src/<package>/logging_config.py`

```python
from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging() -> None:
    """Call once at process startup (before creating FastAPI app)."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
    )

    # Also capture stdlib logging (uvicorn, httpx, etc.) as JSON
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

## FastAPI request logging middleware

Add to each `server.py` `create_app()` after the CORS middleware:

```python
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from elliot_connector_runtime.logging_config import get_logger  # or mcp_plugin

log = get_logger("http")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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

app.add_middleware(RequestLoggingMiddleware)
```

## Startup call

At the top of each `server.py`, before `create_app()` is called:

```python
from .logging_config import configure_logging
configure_logging()
```

## Dependency

Add to each package's `pyproject.toml` `[project] dependencies`:

```toml
"structlog>=24.1",
```

## Environment variables

| Variable | Default | Values |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Log output example

```json
{"event": "request", "method": "POST", "path": "/v1/tools/list_animals", "status": 200, "duration_ms": 43.2, "request_id": "a3f9b1c2", "level": "info", "timestamp": "2026-05-03T10:00:00Z"}
```

## Coverage targets

| Module | Goal |
|---|---|
| `logging_config.py` | 90%+ |
| Middleware | tested via `TestClient` checking `X-Request-Id` header and log output |
