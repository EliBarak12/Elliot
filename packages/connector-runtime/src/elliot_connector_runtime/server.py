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
from mcp.types import ToolAnnotations
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
from .task_store import TaskStore, get_task_store

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
    Registers tools, resources (schema/sample/source status), and prompts (skills).
    """
    import json

    from elliot_core.types import ConnectorConfig

    cfg: ConnectorConfig = config
    instructions = (
        cfg.instructions
        if cfg.instructions
        else (
            f"This MCP server exposes tools for the '{cfg.name}' connector. "
            f"It wraps {len(cfg.sources)} data source(s) across {len(cfg.tools)} tool(s). "
            "Use list_tools to see available tools, then call them with the required parameters."
        )
    )
    mcp = FastMCP("elliot-runtime", instructions=instructions)

    task_store = get_task_store()
    for tool_def in cfg.tools:
        _register_tool(mcp, executor, tool_def, task_store)

    _register_resources(mcp, cfg, executor, json)
    _register_prompts(mcp, cfg)
    _register_task_tool(mcp, task_store)

    return mcp


def _register_tool(
    mcp: FastMCP, executor: ToolExecutor, tool_def: Any, task_store: TaskStore
) -> None:
    from elliot_core.errors import ElliotError, to_mcp_error_content
    from elliot_core.types import ToolDefinition

    td: ToolDefinition = tool_def
    read_only = td.category == "READ"
    annotations = ToolAnnotations(
        title=td.name,
        readOnlyHint=read_only,
        destructiveHint=td.category in ("WRITE", "ACTION"),
        idempotentHint=read_only,
        openWorldHint=True,
    )
    run_async: bool = getattr(td, "run_async", False)

    async def _handler(**kwargs: Any) -> dict[str, Any]:
        if run_async:

            async def _work() -> dict[str, Any]:
                result = await executor.execute(td, kwargs)
                return {"rows": result.rows, "count": len(result.rows)}

            task_id = task_store.submit(td.id, _work())
            return {
                "status": "accepted",
                "task_id": task_id,
                "message": (
                    f"Running in background. "
                    f"Call elliot_get_task(task_id='{task_id}') to retrieve results."
                ),
            }
        try:
            result = await executor.execute(td, kwargs)
            return {"rows": result.rows, "count": len(result.rows)}
        except ElliotError as exc:
            error_content = to_mcp_error_content(exc)
            raise ValueError(error_content["text"]) from exc

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
    object.__setattr__(
        _handler,
        "__signature__",
        inspect.Signature(params, return_annotation=dict[str, Any]),
    )
    _handler.__annotations__["return"] = dict[str, Any]

    mcp.tool(name=td.id, title=td.name, description=td.description, annotations=annotations)(
        _handler
    )


def _register_task_tool(mcp: FastMCP, task_store: TaskStore) -> None:
    """Register elliot_get_task so agents can poll background task results."""

    @mcp.tool(
        name="elliot_get_task",
        description=(
            "Poll the result of a background tool execution. "
            "Use when a previous tool call returned status='accepted' with a task_id. "
            "Returns status ('pending'|'running'|'completed'|'failed') and result when done."
        ),
    )
    def elliot_get_task(task_id: str) -> dict[str, Any]:
        """Retrieve background task status and result by task_id."""
        record = task_store.get(task_id)
        if record is None:
            raise ValueError(
                f"TASK_NOT_FOUND: No task with id '{task_id}'. "
                "Tasks expire after 1 hour. Check the task_id and retry."
            )
        return record.to_dict()


def _register_resources(mcp: FastMCP, cfg: Any, executor: ToolExecutor, json: Any) -> None:
    """Register MCP Resources: connector schema, per-tool sample rows, source status."""
    from elliot_core.types import ConnectorConfig

    c: ConnectorConfig = cfg

    @mcp.resource("connector://schema")
    def connector_schema() -> str:
        """Full connector definition including all sources, tools, and skills."""
        return c.model_dump_json(indent=2)

    for tool_def in c.tools:
        _register_sample_resource(mcp, executor, tool_def, json)

    for source in c.sources:
        _register_source_status_resource(mcp, source)


def _register_sample_resource(
    mcp: FastMCP, executor: ToolExecutor, tool_def: Any, json: Any
) -> None:
    tool_id = tool_def.id
    tool_name = tool_def.name

    @mcp.resource(
        f"connector://sample/{tool_id}",
        description=f"Sample rows from {tool_name} (up to 5). Does not count against the agent's context budget.",
    )
    async def sample_resource() -> str:
        try:
            result = await executor.execute(tool_def, {})
            sample = result.rows[:5]
            return json.dumps({"tool": tool_id, "sample_rows": sample}, default=str)
        except Exception as exc:
            return json.dumps({"tool": tool_id, "error": str(exc)})

    sample_resource.__name__ = f"sample_{tool_id}"


def _register_source_status_resource(mcp: FastMCP, source: Any) -> None:
    source_id = source.id
    source_name = source.name

    @mcp.resource(
        f"source://{source_id}/status",
        description=f"Connectivity status for source '{source_name}'.",
    )
    def source_status() -> str:
        return f'{{"source_id": "{source_id}", "name": "{source_name}", "type": "{source.type}"}}'

    source_status.__name__ = f"status_{source_id}"


def _register_prompts(mcp: FastMCP, cfg: Any) -> None:
    """Expose each SkillDefinition as an MCP Prompt so agents can retrieve step-by-step workflows."""
    from elliot_core.types import ConnectorConfig

    c: ConnectorConfig = cfg
    for skill in c.skills:
        _register_skill_prompt(mcp, skill)


def _register_skill_prompt(mcp: FastMCP, skill: Any) -> None:
    skill_id = skill.id
    skill_name = skill.name
    skill_description = skill.description
    steps = skill.steps
    input_params = skill.input_parameters

    param_names = [p.name for p in input_params]

    def _make_prompt_fn(params: list[str]) -> Any:
        if not params:

            def prompt_fn() -> list[dict[str, Any]]:
                step_lines = "\n".join(
                    f"  Step {i + 1} ({s.alias}): call {s.tool_id} with {s.params}"
                    for i, s in enumerate(steps)
                )
                return [
                    {
                        "role": "user",
                        "content": (
                            f"Execute the '{skill_name}' workflow.\n\nSteps:\n{step_lines}"
                        ),
                    }
                ]

            prompt_fn.__name__ = skill_id
            prompt_fn.__doc__ = skill_description
            return prompt_fn
        else:

            def prompt_fn_with_args(**kwargs: str) -> list[dict[str, Any]]:
                step_lines = "\n".join(
                    f"  Step {i + 1} ({s.alias}): call {s.tool_id} with {s.params}"
                    for i, s in enumerate(steps)
                )
                args_display = ", ".join(f"{k}={v}" for k, v in kwargs.items())
                return [
                    {
                        "role": "user",
                        "content": (
                            f"Execute '{skill_name}' with inputs: {args_display}\n\nSteps:\n{step_lines}"
                        ),
                    }
                ]

            # Build signature so FastMCP can introspect parameter names
            sig_params = [
                inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=str)
                for name in params
            ]
            object.__setattr__(prompt_fn_with_args, "__signature__", inspect.Signature(sig_params))
            prompt_fn_with_args.__name__ = skill_id
            prompt_fn_with_args.__doc__ = skill_description
            return prompt_fn_with_args

    prompt_fn = _make_prompt_fn(param_names)
    mcp.prompt(name=skill_id, description=skill_description)(prompt_fn)


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

    task_store = get_task_store()

    @app.get("/v1/tasks")
    async def list_tasks(limit: int = 20) -> list[dict[str, Any]]:
        return task_store.list_recent(limit)

    @app.get("/v1/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, Any]:
        record = task_store.get(task_id)
        if record is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return record.to_dict()

    @app.post("/v1/tasks/prune")
    async def prune_tasks() -> dict[str, int]:
        return {"deleted": task_store.prune()}

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
