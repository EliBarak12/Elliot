"""FastAPI + uvicorn HTTP server that exposes the Elliot MCP plugin."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from elliot_core.auth_middleware import ApiKeyMiddleware, enforce_auth_configured
from elliot_core.http_middleware import AgentIdentityMiddleware
from elliot_mcp_plugin import __version__
from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

session = ElliotSession(cwd=os.environ.get("ELLIOT_WORKSPACE", "."))

mcp = create_elliot_server(session)
# Initialize the session manager by calling streamable_http_app once at module level
_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Fail-closed: raise (refuse to serve) if ELLIOT_API_KEY is unset while
    # ELLIOT_ENV is production/staging; otherwise log a warning. The helper
    # itself decides which.
    enforce_auth_configured("mcp-plugin")
    # Load session state at startup, not import time, so merely importing
    # this module (tests, tooling) performs no disk I/O.
    session.load()
    async with mcp.session_manager.run():
        yield
    session.save()


app = FastAPI(lifespan=lifespan)
# Order matters: Starlette's add_middleware inserts each call at index 0, so
# the LAST call wraps the others. Adding ApiKey first and CORS second makes
# CORS the outermost wrapper, which is required so that browser preflight
# (OPTIONS) is answered before the auth check runs.
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(AgentIdentityMiddleware)
_studio_origin = os.environ.get("ELLIOT_STUDIO_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_studio_origin],
    allow_headers=[
        "Content-Type",
        "X-Elliot-Key",
        "Authorization",
        "x-client-name",
        "Mcp-Session-Id",
        # The MCP TypeScript SDK (>=1.10) tags every request with this header
        # so the server can negotiate protocol version. Browser preflight will
        # fail without it in the allow-list — Studio cannot reach :3000/mcp.
        "Mcp-Protocol-Version",
    ],
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
)


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, str]:
    """Liveness probe for container/orchestrator healthchecks. Unauthenticated
    (``/health`` + ``/healthz`` are in ApiKeyMiddleware's bypass list)."""
    return {"status": "ok", "service": "mcp-plugin", "version": __version__}


app.mount("/mcp", _mcp_app)
