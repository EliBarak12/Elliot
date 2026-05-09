"""FastAPI + FastMCP HTTP server exposing connector tools on port 3001."""

from __future__ import annotations

import inspect
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP

from .cache import ConnectorCache
from .executor import ToolExecutor

_cache = ConnectorCache(ttl_seconds=30)


def create_runtime_server(connector_path: str, secrets: dict[str, str]) -> FastMCP:
    """
    Build a FastMCP server whose tool list mirrors the connector's ToolDefinitions.
    Called once at startup; the connector is cached and auto-reloaded on mtime change.
    """
    mcp = FastMCP("elliot-runtime")

    config = _cache.get(connector_path)
    executor = ToolExecutor(config, secrets)

    for tool_def in config.tools:
        _register_tool(mcp, executor, tool_def)

    return mcp


def _register_tool(mcp: FastMCP, executor: ToolExecutor, tool_def: Any) -> None:
    from elliot_core.types import ToolDefinition

    td: ToolDefinition = tool_def

    async def _handler(**kwargs: Any) -> Any:
        result = await executor.execute(td, kwargs)
        return result.rows

    _handler.__name__ = td.id
    _handler.__doc__ = td.description

    params = []
    for p in td.parameters:
        if p.type == "integer":
            annotation: Any = int
        elif p.type == "number":
            annotation = float
        elif p.type == "boolean":
            annotation = bool
        else:
            annotation = str
        default = inspect.Parameter.empty if p.required else None
        params.append(
            inspect.Parameter(
                p.name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )
    object.__setattr__(_handler, "__signature__", inspect.Signature(params))

    mcp.tool()(_handler)


def create_app(
    connector_path: str | None = None,
    secrets: dict[str, str] | None = None,
) -> FastAPI:
    connector_path = connector_path or os.environ.get("ELLIOT_CONNECTOR", "connector.json")
    secrets = secrets or {}

    mcp = create_runtime_server(connector_path, secrets)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/mcp", mcp.streamable_http_app())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "connector": connector_path or ""}

    return app


# Entry point: uvicorn elliot_connector_runtime.server:app
app = create_app()
