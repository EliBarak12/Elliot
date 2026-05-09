"""FastAPI + FastMCP HTTP server exposing connector tools on port 3001."""

from __future__ import annotations

import inspect
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP

from .audit import AuditLog
from .cache import ConnectorCache
from .executor import ToolExecutor
from .loader import ConnectorLoadError
from .protocols.openai import register_openai_routes

_cache = ConnectorCache(ttl_seconds=30)


def create_runtime_server(config: Any, executor: ToolExecutor) -> FastMCP:
    """
    Build a FastMCP server whose tool list mirrors the connector's ToolDefinitions.
    """
    from elliot_core.types import ConnectorConfig

    cfg: ConnectorConfig = config
    mcp = FastMCP("elliot-runtime")

    for tool_def in cfg.tools:
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
    audit_path = os.environ.get("ELLIOT_AUDIT_LOG", ".elliot/audit.ndjson")

    try:
        config = _cache.get(connector_path)
    except ConnectorLoadError:
        # Connector not yet available — return a minimal app so the module can be imported.
        _app = FastAPI()

        @_app.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "no_connector", "connector": connector_path or ""}

        return _app

    executor = ToolExecutor(config, secrets)
    audit = AuditLog(audit_path)

    mcp = create_runtime_server(config, executor)

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

    openai_router = APIRouter(prefix="/v1")
    register_openai_routes(openai_router, config, executor, audit)
    app.include_router(openai_router)

    @app.get("/v1/audit")
    async def get_audit(n: int = 100) -> list[dict[str, Any]]:
        return audit.tail(n)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "connector": connector_path or ""}

    return app


# Entry point: uvicorn elliot_connector_runtime.server:app
app = create_app()
