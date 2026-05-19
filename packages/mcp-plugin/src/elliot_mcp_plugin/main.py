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

# Static service identity returned by the unauthenticated health endpoints.
# Docker compose runs `curl -f http://localhost:3000/healthz` as the plugin
# healthcheck (see docker-compose.yml); without this route compose would hang
# `depends_on: condition: service_healthy` and Studio would never start. We
# expose both `/healthz` (Kubernetes/compose convention) and `/health` (the
# shape the connector-runtime already serves) so the Studio monitor can probe
# either service uniformly.
_SERVICE_NAME = "mcp-plugin"

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


@app.get("/healthz")
@app.get("/health")
async def healthz() -> dict[str, str]:
    """Liveness probe — unauthenticated, no session/connector dependency.

    Returns 200 + a small JSON document the moment the ASGI app is up. Used by
    the docker-compose healthcheck (`curl -f http://localhost:3000/healthz`)
    and by Studio's service monitor. Must not touch the ElliotSession,
    connectors, or any external dependency: a liveness probe answers
    "is this process accepting connections" and nothing more.

    The ApiKeyMiddleware bypass list (`elliot_core.auth_middleware._BYPASS_PATHS`)
    already contains both `/healthz` and `/health`, so this route is reachable
    with no `X-Elliot-Key` header even when `ELLIOT_API_KEY` is set.
    """
    return {"status": "ok", "service": _SERVICE_NAME, "version": __version__}


app.mount("/mcp", _mcp_app)
