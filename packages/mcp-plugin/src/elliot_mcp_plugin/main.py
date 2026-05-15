"""FastAPI + uvicorn HTTP server that exposes the Elliot MCP plugin."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from elliot_core.auth_middleware import ApiKeyMiddleware
from elliot_core.http_middleware import AgentIdentityMiddleware
from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

session = ElliotSession(cwd=os.environ.get("ELLIOT_WORKSPACE", "."))
session.load()

mcp = create_elliot_server(session)
# Initialize the session manager by calling streamable_http_app once at module level
_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not os.environ.get("ELLIOT_API_KEY"):
        log.warning(
            "auth.disabled",
            service="mcp-plugin",
            message=(
                "ELLIOT_API_KEY is not set: the plugin is accepting unauthenticated "
                "requests. This is acceptable for localhost-only development; set "
                "ELLIOT_API_KEY before exposing the service on a non-loopback bind."
            ),
        )
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
    ],
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
)

app.mount("/mcp", _mcp_app)
