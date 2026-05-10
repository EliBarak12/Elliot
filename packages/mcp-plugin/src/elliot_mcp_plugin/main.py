"""FastAPI + uvicorn HTTP server that exposes the Elliot MCP plugin."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession

session = ElliotSession(cwd=os.environ.get("ELLIOT_WORKSPACE", "."))
session.load()

mcp = create_elliot_server(session)
# Initialize the session manager by calling streamable_http_app once at module level
_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with mcp.session_manager.run():
        yield
    session.save()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_headers=["*"],
    allow_methods=["*"],
)

app.mount("/mcp", _mcp_app)
