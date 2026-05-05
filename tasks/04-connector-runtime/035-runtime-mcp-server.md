# Task 035 — Runtime: MCP HTTP Server

## Goal
Implement `server.py` in `packages/connector-runtime/src/elliot_connector_runtime/` — a FastAPI + FastMCP HTTP server that exposes a loaded connector's tools as MCP tools on port 3001.

## File to create

### `src/elliot_connector_runtime/server.py`

```python
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP

from .cache import ConnectorCache
from .executor import ToolExecutor
from .loader import ConnectorLoadError


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
        # Close over a snapshot of tool_def (Python loop-variable capture fix)
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

    import inspect
    params = []
    for p in td.parameters:
        annotation = str if p.type == "string" else (int if p.type == "integer" else Any)
        default = inspect.Parameter.empty if p.required else None
        params.append(
            inspect.Parameter(p.name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation, default=default)
        )
    _handler.__signature__ = inspect.Signature(params)

    mcp.tool()(_handler)


def create_app(connector_path: str | None = None, secrets: dict[str, str] | None = None) -> FastAPI:
    connector_path = connector_path or os.environ.get("ELLIOT_CONNECTOR", "connector.json")
    secrets = secrets or {}

    mcp = create_runtime_server(connector_path, secrets)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
    async def health() -> dict:
        return {"status": "ok", "connector": connector_path}

    return app


# Entry point: uvicorn elliot_connector_runtime.server:app
app = create_app()
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ELLIOT_CONNECTOR` | `connector.json` | Path to `.connector.json` file to serve |
| `ELLIOT_SECRETS_FILE` | — | Optional path to JSON secrets file |

## Running

```bash
ELLIOT_CONNECTOR=./my-api.connector.json \
  uv run uvicorn elliot_connector_runtime.server:app --port 3001 --reload \
  --app-dir packages/connector-runtime/src
```

## Procfile entry (add to root Procfile)

```
runtime: uv run uvicorn elliot_connector_runtime.server:app --port 3001 --reload --app-dir packages/connector-runtime/src
```

## Notes
- Port 3001 (plugin is on 3000, runtime is on 3001)
- TTL cache of 30 s — connector file changes are picked up quickly without restart
- `_register_tool` reconstructs the function signature so FastMCP can generate correct JSON Schema for each tool's parameters
- Studio connects to runtime the same way it connects to the plugin (StreamableHTTPClientTransport), just pointing at `:3001`
