"""FastAPI + FastMCP HTTP server exposing connector tools on port 3001."""

from __future__ import annotations

import inspect
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .audit import AuditLog
from .cache import ConnectorCache
from .executor import ToolExecutor
from .loader import ConnectorLoadError
from .observation_store import ObservationStore
from .protocols.openai import register_openai_routes
from .session_tracker import SessionTracker

_cache = ConnectorCache(ttl_seconds=30)
_start_time = time.time()


def _build_limiter() -> Limiter:
    import os

    limit = os.environ.get("ELLIOT_RATE_LIMIT", "120/minute")
    return Limiter(key_func=get_remote_address, default_limits=[limit])


def _suggest(tool_id: str, avg_tokens: float, max_tokens: float) -> str | None:
    if avg_tokens > 1000:
        return f"Average {avg_tokens:.0f} tokens is very high. Add LIMIT clause or SELECT only needed columns."
    if max_tokens > 2000:
        return (
            f"Peak {max_tokens:.0f} tokens. Add a LIMIT or pagination parameter to cap result size."
        )
    if avg_tokens > 300:
        return "Consider adding LIMIT or selecting fewer columns to reduce token cost."
    return None


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
    sessions_path = os.environ.get("ELLIOT_SESSIONS_LOG", ".elliot/sessions.ndjson")
    db_url = os.environ.get("ELLIOT_DB_URL", "sqlite:///.elliot/observations.db")

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
    tracker = SessionTracker(sessions_path)
    store = ObservationStore(db_url)

    mcp = create_runtime_server(config, executor)

    _mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        async with mcp.session_manager.run():
            yield

    limiter = _build_limiter()
    app = FastAPI(lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/mcp", _mcp_app)

    openai_router = APIRouter(prefix="/v1")
    register_openai_routes(openai_router, config, executor, audit)
    app.include_router(openai_router)

    @app.get("/v1/audit")
    async def get_audit(n: int = 100) -> list[dict[str, Any]]:
        return audit.tail(n)

    @app.get("/v1/sessions")
    async def get_sessions(n: int = 20) -> list[dict[str, Any]]:
        return tracker.tail(n)

    @app.get("/v1/metrics/token-efficiency")
    async def token_efficiency() -> dict[str, Any]:
        rows = store.token_efficiency()
        tools = [
            {
                **row,
                "risk": (
                    "high"
                    if (row["avg_tokens"] or 0) > 1000
                    else "medium"
                    if (row["avg_tokens"] or 0) > 300
                    else "low"
                ),
                "suggestion": _suggest(
                    str(row["tool_id"]),
                    float(row["avg_tokens"] or 0),
                    float(row["max_tokens"] or 0),
                ),
            }
            for row in rows
        ]
        return {"tools": tools, "sessions_analysed": len(store.recent_sessions(200))}

    @app.post("/v1/observations/prune")
    async def prune_observations() -> dict[str, int]:
        return {"deleted": store.prune()}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "connector": connector_path or ""}

    @app.get("/v1/health")
    async def detailed_health() -> dict[str, Any]:
        sources_out: list[dict[str, Any]] = []
        all_ok = True
        for source in config.sources:
            try:
                t0 = time.monotonic()
                await _ping_source(source)
                latency = round((time.monotonic() - t0) * 1000, 1)
                sources_out.append(
                    {"id": source.id, "type": source.type, "status": "ok", "latency_ms": latency}
                )
            except Exception as exc:
                sources_out.append(
                    {"id": source.id, "type": source.type, "status": "error", "error": str(exc)}
                )
                all_ok = False

        db_status = "ok"
        db_count = 0
        try:
            db_count = len(store.recent_tool_calls(10000))
        except Exception:
            db_status = "error"
            all_ok = False

        return {
            "status": "healthy" if all_ok else "degraded",
            "connector": {
                "slug": config.slug,
                "name": config.name,
                "version": config.version,
                "tool_count": len(config.tools),
                "source_count": len(config.sources),
            },
            "sources": sources_out,
            "observation_db": {"status": db_status, "tool_calls_total": db_count},
            "uptime_seconds": int(time.time() - _start_time),
        }

    return app


async def _ping_source(source: Any) -> None:
    """Lightweight reachability check for a source."""
    import httpx

    if source.type == "rest":
        async with httpx.AsyncClient(timeout=3) as client:
            await client.head(source.url or "")
    # DB and file sources: skip ping — they're checked when tools execute


# Entry point: uvicorn elliot_connector_runtime.server:app
app = create_app()
