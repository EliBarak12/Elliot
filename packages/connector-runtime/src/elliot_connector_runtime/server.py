"""FastAPI + FastMCP HTTP server exposing connector tools on port 3001."""

from __future__ import annotations

import contextlib
import inspect
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from elliot_core.agent_identity import AgentIdentity, get_current_agent_identity
from elliot_core.auth_middleware import ApiKeyMiddleware
from elliot_core.http_middleware import AgentIdentityMiddleware

from .audit import AuditLog
from .cache import ConnectorCache
from .executor import ToolExecutor
from .loader import ConnectorLoadError
from .observation_store import ObservationStore
from .protocols.openai import register_openai_routes
from .session_tracker import SessionTracker
from .task_store import TaskStore, get_task_store

log = structlog.get_logger(__name__)

_cache = ConnectorCache(ttl_seconds=30)
_start_time = time.time()

# Audit finding H7: no upper bound on request body size, so an agent could
# POST an arbitrarily large MCP `initialize` body and exhaust memory.
# 4 MB is generous for any legitimate MCP/JSON-RPC payload and small enough
# that a misbehaving client can't OOM the worker. Configurable via env.
_DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024


def _max_body_bytes() -> int:
    raw = os.environ.get("ELLIOT_MAX_REQUEST_BODY_BYTES", "")
    try:
        v = int(raw) if raw else _DEFAULT_MAX_BODY_BYTES
        return max(1024, v)
    except ValueError:
        return _DEFAULT_MAX_BODY_BYTES


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured cap.

    For unchunked requests the Content-Length header is authoritative; we
    short-circuit before the request body is read so we don't materialize
    the bytes into memory. Chunked uploads (no Content-Length) currently
    pass through — see follow-up if streaming uploads become a thing.
    """

    def __init__(self, app: Any, max_bytes: int) -> None:
        super().__init__(app)
        self._max = max_bytes

    async def dispatch(
        self,
        request: Request,
        call_next: Any,
    ) -> Response:
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > self._max:
                    return JSONResponse(
                        {
                            "error": {
                                "code": "BODY_TOO_LARGE",
                                "message": f"Request body exceeds {self._max} bytes",
                            }
                        },
                        status_code=413,
                    )
            except ValueError:
                # Malformed Content-Length — let the next layer decide.
                pass
        return await call_next(request)


def _build_limiter() -> Limiter:
    import os

    limit = os.environ.get("ELLIOT_RATE_LIMIT", "120/minute")
    return Limiter(key_func=get_remote_address, default_limits=[limit])


def _require_destructive_confirmation() -> bool:
    """Whether WRITE/ACTION tool calls must include ``confirm=True``.

    Toggled with ``ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION``. Off by default
    so existing connectors keep working; turn it on to enforce the AX
    interactivity pattern for sensitive operations.
    """
    raw = os.environ.get("ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _identity_payload(identity: AgentIdentity | None) -> dict[str, Any] | None:
    if identity is None:
        return None
    payload = identity.to_dict()
    return payload if any(payload.values()) else None


def _agent_hint_from_identity(identity: AgentIdentity | None) -> str:
    """Best-effort string for the legacy ``agent_hint`` column."""
    if identity is None:
        return "mcp"
    label = identity.display()
    return label if label and label != "unknown" else "mcp"


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


def create_runtime_server(
    config: Any,
    executor: ToolExecutor,
    audit: AuditLog | None = None,
    tracker: SessionTracker | None = None,
    store: ObservationStore | None = None,
) -> FastMCP:
    """
    Build a FastMCP server whose tool list mirrors the connector's ToolDefinitions.
    Registers tools, resources (schema/sample/source status), and prompts (skills).

    When audit / tracker / store are supplied, MCP tool invocations are recorded
    so observability matches the OpenAI-protocol path.
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
    # streamable_http_path="/" so that mounting at /mcp exposes the MCP
    # endpoint at /mcp/ (matching the plugin and the docs), not /mcp/mcp/.
    mcp = FastMCP("elliot-runtime", instructions=instructions, streamable_http_path="/")

    task_store = get_task_store()
    connector_slug = getattr(cfg, "slug", None)
    for tool_def in cfg.tools:
        _register_tool(
            mcp,
            executor,
            tool_def,
            task_store,
            audit=audit,
            tracker=tracker,
            store=store,
            connector_slug=connector_slug,
        )

    _register_resources(mcp, cfg, executor, json)
    _register_prompts(mcp, cfg)
    _register_task_tool(mcp, task_store)

    return mcp


def _register_tool(
    mcp: FastMCP,
    executor: ToolExecutor,
    tool_def: Any,
    task_store: TaskStore,
    audit: AuditLog | None = None,
    tracker: SessionTracker | None = None,
    store: ObservationStore | None = None,
    connector_slug: str | None = None,
) -> None:
    from elliot_core.errors import ElliotError, to_mcp_error_content
    from elliot_core.types import ToolDefinition

    td: ToolDefinition = tool_def
    read_only = td.category == "READ"
    is_destructive = td.category in ("WRITE", "ACTION")
    annotations = ToolAnnotations(
        title=td.name,
        readOnlyHint=read_only,
        destructiveHint=is_destructive,
        idempotentHint=read_only,
        openWorldHint=True,
    )
    run_async: bool = getattr(td, "run_async", False)
    require_confirmation = is_destructive and _require_destructive_confirmation()

    def _observe(
        tool_id: str,
        arguments: dict[str, Any],
        result_rows: list[dict[str, Any]],
        duration_ms: float,
        error: str | None,
        session_id: str | None,
    ) -> None:
        """Record one tool call to audit log, session tracker, and observation store."""
        row_count = len(result_rows)
        if audit is not None:
            with contextlib.suppress(Exception):
                audit.record(tool_id, arguments, row_count, duration_ms, error=error)
        identity = get_current_agent_identity()
        identity_payload = _identity_payload(identity)
        agent_hint = _agent_hint_from_identity(identity)
        token_estimate = 0
        if session_id is not None:
            if tracker is not None:
                with contextlib.suppress(Exception):
                    tracker.get_or_start_session(
                        session_id,
                        agent_hint=agent_hint,
                        agent_identity=identity_payload,
                    )
                    tracker.record_tool_call(
                        session_id=session_id,
                        tool_id=tool_id,
                        arguments=arguments,
                        result_rows=row_count,
                        result_data=result_rows,
                        duration_ms=duration_ms,
                        error=error,
                    )
                    # Each MCP request is its own short-lived session — flush
                    # to NDJSON now so /v1/sessions reflects activity immediately.
                    tracker.close_session(session_id)
                # mirror SessionTracker's internal token estimate so the
                # observation store agrees with /v1/sessions
                from .session_tracker import _estimate_tokens

                token_estimate = _estimate_tokens(result_rows)
            if store is not None:
                with contextlib.suppress(Exception):
                    store.open_session(
                        session_id,
                        agent_hint=agent_hint,
                        connector_slug=connector_slug,
                        agent_identity=identity_payload,
                    )
                    store.write_tool_call(
                        session_id=session_id,
                        tool_id=tool_id,
                        arguments=arguments,
                        result_row_count=row_count,
                        result_token_estimate=token_estimate,
                        duration_ms=duration_ms,
                        error=error,
                        connector_slug=connector_slug,
                    )
                    store.close_session(session_id)

    async def _handler(**kwargs: Any) -> dict[str, Any]:
        import time

        from mcp.server.fastmcp import Context

        ctx: Context[Any, Any, Any] | None = None
        session_id: str | None = None
        with contextlib.suppress(Exception):
            ctx = mcp.get_context()
            await ctx.info(f"tool.call.start: {td.id}", logger="elliot.runtime")
        if ctx is not None:
            # Use the FastMCP request_id as a session correlation id so every
            # MCP-driven invocation is traceable in the observation store.
            with contextlib.suppress(Exception):
                session_id = ctx.request_id

        if require_confirmation:
            confirmed = bool(kwargs.pop("confirm", False))
            if not confirmed:
                exc = ElliotError(
                    "CONFIRMATION_REQUIRED",
                    (
                        f"Tool '{td.id}' is {td.category}. Re-call with confirm=true "
                        "after the user authorises this destructive operation."
                    ),
                    {"tool_id": td.id, "category": td.category},
                )
                _observe(td.id, kwargs, [], 0.0, str(exc), session_id)
                error_content = to_mcp_error_content(exc)
                raise ValueError(error_content["text"])
        else:
            kwargs.pop("confirm", None)

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

        t0 = time.monotonic()
        try:
            result = await executor.execute(td, kwargs)
            duration_ms = round((time.monotonic() - t0) * 1000, 1)
            _observe(td.id, kwargs, result.rows, duration_ms, None, session_id)
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.info(
                        f"tool.call.complete: {td.id} rows={len(result.rows)} duration_ms={duration_ms}",
                        logger="elliot.runtime",
                    )
            return {"rows": result.rows, "count": len(result.rows)}
        except ElliotError as exc:
            duration_ms = round((time.monotonic() - t0) * 1000, 1)
            _observe(td.id, kwargs, [], duration_ms, str(exc), session_id)
            error_content = to_mcp_error_content(exc)
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.warning(
                        f"tool.call.error: {td.id} code={exc.code}",
                        logger="elliot.runtime",
                    )
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
    if require_confirmation:
        params.append(
            inspect.Parameter(
                "confirm",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=bool,
                default=False,
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
        """Full connector definition including all sources, tools, and skills.

        The in-memory ``ConnectorConfig`` has had ``resolve_secrets`` applied
        to it during loader hydration, so source URLs / auth headers may
        contain literal secret values. We mask known-secret fields and
        redact URL userinfo / token-bearing query params before serializing.
        """
        from elliot_core.redaction import redact_url, redact_value

        snapshot = redact_value(c.model_dump())
        for source in snapshot.get("sources", []) or []:
            if isinstance(source, dict) and source.get("url"):
                source["url"] = redact_url(source.get("url"))
        return json.dumps(snapshot, indent=2, default=str)

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
    table_name = getattr(source, "table_name", None) or source.id

    @mcp.resource(
        f"source://{source_id}/status",
        description=f"Connectivity status for source '{source_name}'.",
    )
    def source_status() -> str:
        import json as _json

        return _json.dumps(
            {
                "source_id": source_id,
                "name": source_name,
                "type": source.type,
                # `table_name` is what the connector's tool SQL is authored
                # against — surface it so agents can confirm which table
                # name matches which configured source.
                "table_name": table_name,
            }
        )

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

            # Build signature so FastMCP can introspect parameter names,
            # and also set __annotations__ so pydantic's validate_call can
            # resolve type hints via typing.get_type_hints.
            sig_params = [
                inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=str)
                for name in params
            ]
            object.__setattr__(prompt_fn_with_args, "__signature__", inspect.Signature(sig_params))
            prompt_fn_with_args.__annotations__ = {name: str for name in params}
            prompt_fn_with_args.__annotations__["return"] = list[dict[str, Any]]
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

    mcp = create_runtime_server(config, executor, audit=audit, tracker=tracker, store=store)

    _mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        async with mcp.session_manager.run():
            yield
        # Audit H7: cancel any in-flight background tasks so we don't leave
        # them in `running` state after the loop closes.
        with contextlib.suppress(Exception):
            await get_task_store().cancel_all()

    limiter = _build_limiter()
    # redirect_slashes=False so that a POST to /mcp does not 307-redirect to
    # /mcp/. Strict MCP clients (Codex / rmcp) discard the POST body on the
    # redirect and the JSON-RPC `initialize` handshake fails. Auto-config in
    # `elliot connect` and `elliot_get_connection_config` writes the URL with
    # a trailing slash so clients reach FastMCP directly.
    app = FastAPI(lifespan=lifespan, redirect_slashes=False)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    if not os.environ.get("ELLIOT_API_KEY"):
        log.warning(
            "auth.disabled",
            service="connector-runtime",
            message=(
                "ELLIOT_API_KEY is not set: the runtime is accepting unauthenticated "
                "requests. This is acceptable for localhost-only development; set "
                "ELLIOT_API_KEY before exposing the service on a non-loopback bind."
            ),
        )
    # Order matters: Starlette inserts each add_middleware at index 0, so the
    # LAST call wraps the others. Final stack (outermost first):
    #   CORS  →  BodySizeLimit  →  SlowAPI  →  ApiKey  →  app
    # CORS first so preflight (OPTIONS) is answered before anything else;
    # body-size cap rejects oversized requests before they reach rate-limit
    # accounting; SlowAPI rate-limits both authed and unauthed traffic so
    # the auth check itself can't be brute-forced; ApiKey is innermost so
    # it runs on the surviving requests only.
    app.add_middleware(ApiKeyMiddleware)
    # Audit finding H5: the rate limiter was instantiated but never enforced
    # because SlowAPIMiddleware was missing. Wire it now so the
    # ELLIOT_RATE_LIMIT env var actually takes effect on every route.
    app.add_middleware(SlowAPIMiddleware)
    # Body-size cap (audit H7). Outer real middleware so a huge request is
    # rejected before any downstream layer materialises it.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=_max_body_bytes())
    # Bind the parsed AX agent identity to a contextvar so tool handlers can
    # attribute calls to a specific client/model rather than a generic 'mcp'.
    app.add_middleware(AgentIdentityMiddleware)
    studio_origin = os.environ.get("ELLIOT_STUDIO_ORIGIN", "http://localhost:5173")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[studio_origin],
        allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-Elliot-Key",
            "Authorization",
            "x-client-name",
            "Mcp-Session-Id",
            # MCP TS SDK >=1.10 sends Mcp-Protocol-Version on every call;
            # without it the browser preflight fails.
            "Mcp-Protocol-Version",
        ],
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
    from elliot_core.http import SSRFError, safe_client, validate_url

    if source.type == "rest":
        url = source.url or ""
        try:
            validate_url(url)
        except SSRFError as exc:
            # /v1/health must not be usable as an SSRF probe — surface the
            # block to the caller without making the HEAD request.
            raise RuntimeError(f"SSRF_BLOCKED: {exc.message}") from exc
        async with safe_client(timeout=3) as client:
            await client.head(url)
    # DB and file sources: skip ping — they're checked when tools execute


# Entry point: uvicorn elliot_connector_runtime.server:app
app = create_app()
