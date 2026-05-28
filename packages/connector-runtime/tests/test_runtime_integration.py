"""
Integration tests for elliot-connector-runtime.

These tests spin up the FastAPI app via TestClient (no real server process)
and mock outbound HTTP calls with respx.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from elliot_connector_runtime.audit import AuditLog
from elliot_connector_runtime.server import create_app

MINIMAL_CONNECTOR = {
    "name": "Pets",
    "slug": "pets",
    "version": "1.0.0",
    "sources": [
        {
            "id": "animals",
            "name": "Animals API",
            "type": "rest",
            "url": "https://api.example.com/animals",
            "data_path": "items",
        }
    ],
    "tools": [
        {
            "id": "list_animals",
            "name": "List animals",
            "description": "Return all animals",
            "category": "READ",
            "sql": "SELECT * FROM animals",
            "parameters": [],
        }
    ],
    "skills": [],
}


@pytest.fixture()
def connector_file(tmp_path: Path) -> Path:
    p = tmp_path / "pets.connector.json"
    p.write_text(json.dumps(MINIMAL_CONNECTOR))
    return p


@pytest.fixture()
def app(connector_file: Path):
    return create_app(connector_path=str(connector_file), secrets={})


@pytest.fixture()
def client(app):
    return TestClient(app)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_key_middleware_registered(app) -> None:
    """Auth must be wired into the runtime so /v1/* routes are not open."""
    from elliot_core.auth_middleware import ApiKeyMiddleware

    middleware_types = [m.cls for m in app.user_middleware]
    assert ApiKeyMiddleware in middleware_types


def test_runtime_requires_api_key_when_set(
    connector_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    app = create_app(connector_path=str(connector_file), secrets={})
    client = TestClient(app)
    # /health is in the bypass set; /v1/audit is not.
    assert client.get("/health").status_code == 200
    assert client.get("/v1/audit").status_code == 401
    assert client.get("/v1/audit", headers={"X-Elliot-Key": "secret"}).status_code == 200
    assert client.get("/v1/audit", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_slowapi_middleware_registered(app) -> None:
    """The rate limiter must be wired (audit H5)."""
    from slowapi.middleware import SlowAPIMiddleware

    middleware_types = [m.cls for m in app.user_middleware]
    assert SlowAPIMiddleware in middleware_types


def test_body_size_middleware_rejects_oversize(
    connector_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit H7: a request with Content-Length above the cap must be 413'd
    before any body is materialised."""
    monkeypatch.setenv("ELLIOT_MAX_REQUEST_BODY_BYTES", "1024")
    app = create_app(connector_path=str(connector_file), secrets={})
    client = TestClient(app)
    big = "x" * 4096
    resp = client.post(
        "/v1/audit",
        headers={"Content-Type": "application/json"},
        content=big,
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "BODY_TOO_LARGE"


def test_body_size_middleware_rejects_chunked_oversize(
    connector_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chunked upload (no Content-Length) above the cap must still be 413'd.

    The middleware counts bytes off the receive stream and aborts once the
    running total exceeds ELLIOT_MAX_REQUEST_BODY_BYTES. /v1/trace/ingest is a
    POST that parses its body, so the counting wrapper actually runs.
    """
    monkeypatch.setenv("ELLIOT_MAX_REQUEST_BODY_BYTES", "1024")
    app = create_app(connector_path=str(connector_file), secrets={})
    client = TestClient(app)

    def _chunks():
        # Each chunk is small; the total exceeds the 1 KiB cap. Passing a
        # generator makes httpx send a chunked request with no Content-Length.
        for _ in range(8):
            yield b"x" * 512

    resp = client.post(
        "/v1/trace/ingest",
        headers={"Content-Type": "application/json"},
        content=_chunks(),
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "BODY_TOO_LARGE"


def test_body_size_middleware_allows_chunked_under_limit(
    connector_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chunked request under the cap passes through to the route untouched."""
    monkeypatch.setenv("ELLIOT_MAX_REQUEST_BODY_BYTES", "1048576")
    app = create_app(connector_path=str(connector_file), secrets={})
    client = TestClient(app)

    payload = b'{"harness":"test","session_id":"s1","events":[]}'

    def _chunks():
        yield payload

    # A small chunked POST to the ingest endpoint must succeed (200), proving
    # the body cap did not fire on an under-limit chunked request.
    resp = client.post(
        "/v1/trace/ingest",
        headers={"Content-Type": "application/json"},
        content=_chunks(),
    )
    assert resp.status_code != 413
    assert resp.status_code == 200


def test_audit_record_and_tail(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.ndjson")
    log.record("tool_x", {"a": 1}, result_row_count=5, duration_ms=12.3)
    log.record("tool_y", {}, result_row_count=0, duration_ms=0.5, error="timeout")

    entries = log.tail(10)
    assert len(entries) == 2
    assert entries[0]["tool_id"] == "tool_x"
    assert entries[1]["error"] == "timeout"


def test_audit_tail_empty(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "missing.ndjson")
    assert log.tail() == []


def test_audit_tail_limit(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.ndjson")
    for i in range(20):
        log.record(f"tool_{i}", {}, result_row_count=i, duration_ms=1.0)
    entries = log.tail(5)
    assert len(entries) == 5
    assert entries[-1]["tool_id"] == "tool_19"


def test_audit_endpoint(client: TestClient) -> None:
    resp = client.get("/v1/audit")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_openai_tools_schema(connector_file: Path) -> None:
    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.protocols.openai import build_openai_tools

    cache = ConnectorCache()
    config = cache.get(connector_file)
    tools = build_openai_tools(config)

    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "list_animals"


def test_openai_parse_tool_message() -> None:
    from elliot_connector_runtime.protocols.openai import _parse_tool_message

    # Bare tool id (back-compat).
    assert _parse_tool_message("list_animals") == ("list_animals", {})
    # JSON object with arguments — previously dropped.
    tid, args = _parse_tool_message('{"tool": "list_animals", "arguments": {"species": "cat"}}')
    assert tid == "list_animals"
    assert args == {"species": "cat"}


def test_openai_chat_completions_unknown_tool(client: TestClient) -> None:
    """An unknown tool returns a structured error, not a 500."""
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "tool", "content": "no_such_tool"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    content = json.loads(body["choices"][0]["message"]["content"])
    assert content["error"]["code"] == "TOOL_NOT_FOUND"


def test_openai_chat_completions_advertises_tools(client: TestClient) -> None:
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert any(t["function"]["name"] == "list_animals" for t in resp.json()["tools"])


async def test_connector_schema_resource_redacts_secrets() -> None:
    """The `connector://schema` resource must never leak resolved secret
    values — auth blocks, custom headers, URL userinfo / token query params."""
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_connector_runtime.server import create_runtime_server
    from elliot_core.types import ConnectorConfig

    cfg = ConnectorConfig.model_validate(
        {
            "name": "Pets",
            "slug": "pets",
            "version": "1.0.0",
            "sources": [
                {
                    "id": "animals",
                    "name": "Animals API",
                    "type": "rest",
                    # userinfo + token-bearing query param both carry secrets.
                    "url": "https://u:URLSECRET@api.example.com/animals?api_key=QUERYSECRET",
                    # auth.secret_key has been resolve_secrets'd to a literal.
                    "auth": {
                        "type": "bearer",
                        "secret_key": "RESOLVED_TOKEN_VALUE",
                        # A custom header name a key-name blocklist wouldn't catch.
                        "header_name": "X-Internal-Key",
                    },
                    # config_snapshot is an arbitrary dict that may hold secrets
                    # under author-chosen keys.
                    "config_snapshot": {"x_tenant_pass": "SNAPSHOTSECRET"},
                }
            ],
            "tools": [
                {
                    "id": "t",
                    "name": "T",
                    "description": "d",
                    "category": "READ",
                    "sql": "SELECT * FROM animals",
                    "parameters": [],
                }
            ],
            "skills": [],
        }
    )
    executor = ToolExecutor(cfg, secrets={})
    mcp = create_runtime_server(cfg, executor)
    contents = list(await mcp.read_resource("connector://schema"))
    body = contents[0].content
    assert isinstance(body, str)
    for secret in (
        "URLSECRET",
        "QUERYSECRET",
        "RESOLVED_TOKEN_VALUE",
        "SNAPSHOTSECRET",
    ):
        assert secret not in body, f"{secret!r} leaked in connector://schema"
    # Non-secret structure must still be present.
    assert "animals" in body
    assert "api.example.com" in body


def test_redact_secret_blocks_masks_nested_auth_and_headers() -> None:
    """_redact_secret_blocks masks whole auth/headers/credentials sub-mappings
    regardless of the inner key names."""
    from elliot_connector_runtime.server import _redact_secret_blocks

    node: dict = {
        "url": "https://x",
        "auth": {"weird_field": "tok"},
        "nested": {
            "headers": {"X-Anything": "val"},
            "credentials": {"u": "p"},
            "safe": {"keep": "me"},
        },
        "items": [{"auth": {"a": "b"}}],
    }
    _redact_secret_blocks(node)
    assert node["auth"] == "***"
    assert node["nested"]["headers"] == "***"
    assert node["nested"]["credentials"] == "***"
    assert node["nested"]["safe"] == {"keep": "me"}
    assert node["items"][0]["auth"] == "***"
    assert node["url"] == "https://x"


@respx.mock
async def test_executor_full_flow(connector_file: Path) -> None:
    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.executor import ToolExecutor

    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": 1, "name": "Rex", "species": "dog"}]},
        )
    )

    cache = ConnectorCache()
    config = cache.get(connector_file)
    executor = ToolExecutor(config, secrets={})
    tool = config.tools[0]

    result = await executor.execute(tool, {})
    assert len(result.rows) == 1
    assert result.rows[0]["name"] == "Rex"


def test_loader_schema_validation_error(tmp_path: Path) -> None:
    from elliot_connector_runtime.loader import ConnectorLoadError, load_connector

    bad = tmp_path / "bad.connector.json"
    bad.write_text(json.dumps({"name": "Missing required fields"}))
    with pytest.raises(ConnectorLoadError, match="Schema validation failed"):
        load_connector(bad)


# ── Bug #6 regression: MCP mounted at /mcp/ (not /mcp/mcp/) ──────────────────


def test_mcp_endpoint_mounted_at_mcp_slash(app) -> None:
    """The FastMCP sub-app must expose its transport at '/' so the outer
    mount at '/mcp' lands the streamable endpoint at '/mcp/' — matching the
    docs and every .mcp.json config. Before the fix, the sub-app exposed
    '/mcp' which left the endpoint at '/mcp/mcp/'.
    """
    mcp_mount = next(r for r in app.routes if getattr(r, "path", None) == "/mcp")
    sub_app_routes = [getattr(r, "path", None) for r in getattr(mcp_mount.app, "routes", [])]
    assert "/" in sub_app_routes, (
        f"Expected MCP sub-app to expose '/' so mount lands at /mcp/, "
        f"got sub-app routes: {sub_app_routes}"
    )
    assert "/mcp" not in sub_app_routes, (
        "MCP sub-app should not still expose '/mcp' (would result in /mcp/mcp/)."
    )


def test_mcp_post_does_not_307_redirect(app) -> None:
    """Regression: strict MCP clients (Codex/rmcp) drop the POST body when
    FastAPI emits a 307 from /mcp to /mcp/. With redirect_slashes=False the
    endpoint must respond directly at /mcp/ without redirecting.

    We run TestClient under `with ... as` so the FastMCP lifespan initializes
    the streamable_http session manager (otherwise the inner app raises
    'Task group is not initialized').
    """
    body = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "regression-probe", "version": "0.0.1"},
        },
    }
    with TestClient(app) as client:
        resp = client.post(
            "/mcp/",
            json=body,
            headers={"Accept": "application/json, text/event-stream"},
            follow_redirects=False,
        )
        # Whatever MCP returns (success, 400 about session, etc.), what we
        # MUST NOT see is a 307 — that's the bug we're guarding against.
        assert resp.status_code != 307, (
            f"FastAPI emitted a redirect from /mcp/ — strict MCP clients "
            f"would drop the body. status={resp.status_code} headers={dict(resp.headers)}"
        )

        # The slash-less form must also not 307 (so users who hand-write
        # the URL without trailing slash still don't lose their POST body).
        resp_no_slash = client.post(
            "/mcp",
            json=body,
            headers={"Accept": "application/json, text/event-stream"},
            follow_redirects=False,
        )
        assert resp_no_slash.status_code != 307, (
            f"FastAPI still redirects /mcp → /mcp/. status={resp_no_slash.status_code}"
        )


# ── Bug #5 regression: skills with inputs no longer crash startup ────────────


def test_runtime_loads_connector_with_parameterized_skill(tmp_path: Path) -> None:
    """A connector with a skill that has input_parameters used to crash
    create_app at import time because the dynamic prompt fn lacked
    __annotations__, breaking pydantic.validate_call."""
    cfg = {
        **MINIMAL_CONNECTOR,
        "skills": [
            {
                "id": "lookup_pet",
                "name": "Lookup pet",
                "description": "Look up a pet by id",
                "input_parameters": [
                    {
                        "name": "pet_id",
                        "type": "string",
                        "required": True,
                        "description": "ID",
                    }
                ],
                "steps": [
                    {
                        "alias": "fetch",
                        "tool_id": "list_animals",
                        "params": {"id": "{{skill.input.pet_id}}"},
                    }
                ],
            }
        ],
    }
    p = tmp_path / "skill.connector.json"
    p.write_text(json.dumps(cfg))
    # Used to raise KeyError: 'pet_id'
    app = create_app(connector_path=str(p), secrets={})
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"


# ── Bug #9 regression: MCP tool calls write to audit + observation store ─────


def test_mcp_tool_call_writes_observability(tmp_path: Path) -> None:
    """When invoked via the runtime MCP, a tool call must populate the audit log,
    the session tracker, and the observation store — same coverage as the OpenAI
    protocol path. Drives the handler directly to avoid streamable-HTTP plumbing.
    """
    cfg_path = tmp_path / "pets.connector.json"
    cfg_path.write_text(json.dumps(MINIMAL_CONNECTOR))

    audit_path = tmp_path / "audit.ndjson"
    sessions_path = tmp_path / "sessions.ndjson"
    db_url = f"sqlite:///{tmp_path / 'obs.db'}"

    import os

    os.environ["ELLIOT_AUDIT_LOG"] = str(audit_path)
    os.environ["ELLIOT_SESSIONS_LOG"] = str(sessions_path)
    os.environ["ELLIOT_DB_URL"] = db_url
    try:
        from elliot_connector_runtime.audit import AuditLog as _AuditLog

        # Build the components the way create_app() does, then drive the MCP
        # handler we register so we can assert the side effects directly.
        from elliot_connector_runtime.cache import ConnectorCache
        from elliot_connector_runtime.executor import ToolExecutor
        from elliot_connector_runtime.observation_store import (
            ObservationStore as _Store,
        )
        from elliot_connector_runtime.server import create_runtime_server
        from elliot_connector_runtime.session_tracker import (
            SessionTracker as _Tracker,
        )

        config = ConnectorCache().get(cfg_path)
        executor = ToolExecutor(config, secrets={})
        audit = _AuditLog(audit_path)
        tracker = _Tracker(sessions_path)
        store = _Store(db_url)

        # Stub the source fetch so we don't hit the network.
        async def _fake(tool, args):  # type: ignore[no-untyped-def]
            from elliot_core.types.tool import ToolResult

            return ToolResult(rows=[{"id": 1, "name": "Rex"}], meta={})

        executor.execute = _fake  # type: ignore[assignment]

        mcp = create_runtime_server(config, executor, audit=audit, tracker=tracker, store=store)
        # The handler is registered on the FastMCP tool manager. Pull it out
        # via the underlying manager and invoke it directly with a request_id
        # equivalent so observability can correlate.
        import asyncio

        tool = mcp._tool_manager.get_tool("list_animals")
        assert tool is not None

        # Run the wrapped handler. ctx.get_context() will raise outside an MCP
        # session — the handler catches that and continues with session_id=None.
        # To still exercise the observability writes, we provide a session via
        # a temporary monkey patch.
        class _Ctx:
            request_id = "test-req-123"

            async def info(self, *a, **k):  # type: ignore[no-untyped-def]
                pass

            async def warning(self, *a, **k):  # type: ignore[no-untyped-def]
                pass

        def _get_ctx():  # type: ignore[no-untyped-def]
            return _Ctx()

        mcp.get_context = _get_ctx  # type: ignore[assignment]
        asyncio.run(tool.fn())  # call with no kwargs (list_animals takes none)

        # Audit log written
        entries = audit.tail(10)
        assert len(entries) == 1
        assert entries[0]["tool_id"] == "list_animals"
        assert entries[0]["result_row_count"] == 1
        # Observation store written
        calls = store.recent_tool_calls(10)
        assert len(calls) == 1
        assert calls[0]["tool_id"] == "list_animals"
        # Session tracker holds the run as one live, still-open session — it
        # accumulates calls until the idle sweeper or shutdown flushes it.
        live = tracker.tail(10)
        assert len(live) == 1
        assert live[0]["session_id"] == "test-req-123"
        assert live[0]["total_tool_calls"] == 1
        # Flushing closes it and writes the NDJSON line.
        tracker.close_session("test-req-123")
        sess_lines = sessions_path.read_text().strip().splitlines()
        assert len(sess_lines) == 1
        assert json.loads(sess_lines[0])["session_id"] == "test-req-123"
    finally:
        os.environ.pop("ELLIOT_AUDIT_LOG", None)
        os.environ.pop("ELLIOT_SESSIONS_LOG", None)
        os.environ.pop("ELLIOT_DB_URL", None)


def test_mcp_tool_call_records_non_elliot_error(tmp_path: Path) -> None:
    """A non-ElliotError failure (HTTP error, executor error, timeout) must
    still be recorded in the audit log and session tracker. If it isn't, the
    failed call is invisible and metrics wrongly report a 100% success rate.
    """
    cfg_path = tmp_path / "pets.connector.json"
    cfg_path.write_text(json.dumps(MINIMAL_CONNECTOR))

    audit_path = tmp_path / "audit.ndjson"

    import os

    os.environ["ELLIOT_AUDIT_LOG"] = str(audit_path)
    try:
        from elliot_connector_runtime.audit import AuditLog as _AuditLog
        from elliot_connector_runtime.cache import ConnectorCache
        from elliot_connector_runtime.executor import ToolExecutor
        from elliot_connector_runtime.server import create_runtime_server
        from elliot_connector_runtime.session_tracker import (
            SessionTracker as _Tracker,
        )

        config = ConnectorCache().get(cfg_path)
        executor = ToolExecutor(config, secrets={})
        audit = _AuditLog(audit_path)
        tracker = _Tracker(tmp_path / "sessions.ndjson")

        # A plain RuntimeError stands in for httpx.HTTPStatusError / ExecutorError
        # — anything that is not an ElliotError.
        async def _boom(tool, args):  # type: ignore[no-untyped-def]
            raise RuntimeError("upstream returned 500")

        executor.execute = _boom  # type: ignore[assignment]

        mcp = create_runtime_server(config, executor, audit=audit, tracker=tracker)

        import asyncio

        tool = mcp._tool_manager.get_tool("list_animals")
        assert tool is not None

        class _Ctx:
            request_id = "err-req-1"

            async def info(self, *a, **k):  # type: ignore[no-untyped-def]
                pass

            async def warning(self, *a, **k):  # type: ignore[no-untyped-def]
                pass

        mcp.get_context = lambda: _Ctx()  # type: ignore[assignment]

        with pytest.raises(ValueError):
            asyncio.run(tool.fn())

        # The failed call must appear in the audit log with an error set.
        entries = audit.tail(10)
        assert len(entries) == 1
        assert entries[0]["tool_id"] == "list_animals"
        assert "500" in entries[0]["error"]

        # And in the session tracker as a failed event.
        live = tracker.tail(10)
        assert len(live) == 1
        assert live[0]["error_count"] == 1
    finally:
        os.environ.pop("ELLIOT_AUDIT_LOG", None)


def test_cache_ttl_expiry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TTL expiry is verified by advancing the monotonic clock, not by
    real-time sleep. ttl_seconds=0.01 + time.sleep(0.05) was flaky on slow
    CI hosts."""
    import elliot_connector_runtime.cache as cache_module

    p = tmp_path / "test.connector.json"
    p.write_text(json.dumps(MINIMAL_CONNECTOR))

    fake_now = [1000.0]

    def _now() -> float:
        return fake_now[0]

    monkeypatch.setattr(cache_module.time, "monotonic", _now)
    cache = cache_module.ConnectorCache(ttl_seconds=10.0)
    first = cache.get(p)
    fake_now[0] += 11.0  # Advance past the TTL.
    second = cache.get(p)
    assert first is not second


def test_v1_health_no_sources(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded")
    assert "connector" in data
    assert data["connector"]["slug"] == "pets"
    assert "sources" in data
    assert "observation_db" in data
    assert "uptime_seconds" in data


def test_v1_health_with_rest_source(tmp_path: Path) -> None:
    connector = {
        **MINIMAL_CONNECTOR,
        "sources": [
            {
                "id": "api",
                "name": "API",
                "type": "rest",
                "url": "https://api.unreachable.invalid",
            }
        ],
    }
    p = tmp_path / "conn.connector.json"
    p.write_text(json.dumps(connector))
    app = create_app(connector_path=str(p))
    c = TestClient(app)
    resp = c.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["sources"][0]["status"] == "error"


def test_prune_endpoint(client: TestClient) -> None:
    resp = client.post("/v1/observations/prune")
    assert resp.status_code == 200
    assert "deleted" in resp.json()


def test_feedback_endpoint_returns_list(client: TestClient) -> None:
    resp = client.get("/v1/feedback")
    assert resp.status_code == 200
    assert resp.json()["feedback"] == []


def test_feedback_tool_registered_and_records(tmp_path: Path) -> None:
    """Every running connector exposes a built-in submit_feedback tool; calling
    it persists the agent's report to the observation store with the right
    connector slug and agent identity."""
    import asyncio

    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_connector_runtime.observation_store import ObservationStore as _Store
    from elliot_connector_runtime.server import create_runtime_server
    from elliot_core.agent_identity import (
        AgentIdentity,
        reset_current_agent_identity,
        set_current_agent_identity,
    )

    cfg_path = tmp_path / "pets.connector.json"
    cfg_path.write_text(json.dumps(MINIMAL_CONNECTOR))
    store = _Store(f"sqlite:///{tmp_path / 'obs.db'}")

    config = ConnectorCache().get(cfg_path)
    executor = ToolExecutor(config, secrets={})
    mcp = create_runtime_server(config, executor, store=store)

    class _Ctx:
        request_id = "fb-req-1"

        async def info(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

        async def warning(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

    mcp.get_context = lambda: _Ctx()  # type: ignore[assignment]

    tool = mcp._tool_manager.get_tool("submit_feedback")
    assert tool is not None

    identity = AgentIdentity(client="claude-code", model="claude-opus-4-7")
    token = set_current_agent_identity(identity)
    try:
        result = asyncio.run(
            tool.fn(
                tool_id="list_animals",
                outcome="Success",  # mixed case must be normalised
                why_chosen="It returns every animal in one call",
                input_summary="no params",
                output_summary="1 row",
                detail="clean",
            )
        )
    finally:
        reset_current_agent_identity(token)

    assert result["status"] == "recorded"
    assert result["outcome"] == "success"

    feedback = store.recent_feedback(10)
    assert len(feedback) == 1
    assert feedback[0]["tool_id"] == "list_animals"
    assert feedback[0]["outcome"] == "success"
    assert feedback[0]["connector_slug"] == "pets"
    assert feedback[0]["agent_client"] == "claude-code"


def test_feedback_tool_rejects_invalid_outcome(tmp_path: Path) -> None:
    import asyncio

    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_connector_runtime.observation_store import ObservationStore as _Store
    from elliot_connector_runtime.server import create_runtime_server

    cfg_path = tmp_path / "pets.connector.json"
    cfg_path.write_text(json.dumps(MINIMAL_CONNECTOR))
    store = _Store(f"sqlite:///{tmp_path / 'obs.db'}")
    config = ConnectorCache().get(cfg_path)
    executor = ToolExecutor(config, secrets={})
    mcp = create_runtime_server(config, executor, store=store)

    class _Ctx:
        request_id = "fb-req-2"

        async def info(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

        async def warning(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

    mcp.get_context = lambda: _Ctx()  # type: ignore[assignment]
    tool = mcp._tool_manager.get_tool("submit_feedback")
    assert tool is not None

    with pytest.raises(ValueError, match="VALIDATION_INVALID_OUTCOME"):
        asyncio.run(tool.fn(tool_id="list_animals", outcome="great"))
    assert store.recent_feedback(10) == []


def test_feedback_tool_absent_without_store(tmp_path: Path) -> None:
    """Without an observation store the feedback tool is not registered — it has
    nowhere to persist to, so we don't advertise a tool that can't deliver."""
    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_connector_runtime.server import create_runtime_server

    cfg_path = tmp_path / "pets.connector.json"
    cfg_path.write_text(json.dumps(MINIMAL_CONNECTOR))
    config = ConnectorCache().get(cfg_path)
    executor = ToolExecutor(config, secrets={})
    mcp = create_runtime_server(config, executor)
    assert mcp._tool_manager.get_tool("submit_feedback") is None


def test_agent_identity_middleware_registered(app) -> None:
    """The AX identity middleware must be wired so tool handlers can attribute
    calls to the actual client/model rather than a generic 'mcp' bucket.
    """
    from elliot_core.http_middleware import AgentIdentityMiddleware

    middleware_types = [m.cls for m in app.user_middleware]
    assert AgentIdentityMiddleware in middleware_types


def test_agent_identity_recorded_via_middleware(tmp_path: Path) -> None:
    """End-to-end: a request with an AX-format User-Agent populates the parsed
    identity on the session row written by an MCP tool call.
    """
    import asyncio

    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_connector_runtime.observation_store import ObservationStore as _Store
    from elliot_connector_runtime.server import create_runtime_server
    from elliot_connector_runtime.session_tracker import SessionTracker as _Tracker
    from elliot_core.agent_identity import (
        AgentIdentity,
        reset_current_agent_identity,
        set_current_agent_identity,
    )

    cfg_path = tmp_path / "pets.connector.json"
    cfg_path.write_text(json.dumps(MINIMAL_CONNECTOR))
    sessions_path = tmp_path / "sessions.ndjson"
    db_url = f"sqlite:///{tmp_path / 'obs.db'}"

    config = ConnectorCache().get(cfg_path)
    executor = ToolExecutor(config, secrets={})
    tracker = _Tracker(sessions_path)
    store = _Store(db_url)

    async def _fake(tool, args):  # type: ignore[no-untyped-def]
        from elliot_core.types.tool import ToolResult

        return ToolResult(rows=[{"id": 1}], meta={})

    executor.execute = _fake  # type: ignore[assignment]

    mcp = create_runtime_server(config, executor, tracker=tracker, store=store)

    class _Ctx:
        request_id = "ax-req-001"

        async def info(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

        async def warning(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

    mcp.get_context = lambda: _Ctx()  # type: ignore[assignment]

    identity = AgentIdentity(
        client="claude-code",
        client_version="1.42.0",
        model="claude-opus-4-7",
        user_agent="agent-claude-code/1.42.0 claude-opus-4-7",
    )
    token = set_current_agent_identity(identity)
    try:
        tool = mcp._tool_manager.get_tool("list_animals")
        assert tool is not None
        asyncio.run(tool.fn())
    finally:
        reset_current_agent_identity(token)

    sessions = store.recent_sessions(5)
    assert sessions[0]["agent_client"] == "claude-code"
    assert sessions[0]["agent_model"] == "claude-opus-4-7"
    assert sessions[0]["agent_hint"].startswith("claude-code/")


def test_destructive_tool_requires_confirmation_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION on, a WRITE tool must reject
    calls that don't pass confirm=true with a CONFIRMATION_REQUIRED error, and
    must accept calls that do.
    """
    import asyncio

    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_connector_runtime.server import create_runtime_server

    monkeypatch.setenv("ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION", "true")

    write_connector = {
        **MINIMAL_CONNECTOR,
        "tools": [
            {
                "id": "delete_animal",
                "name": "Delete animal",
                "description": "Delete an animal by id",
                "category": "WRITE",
                "sql": "DELETE FROM animals WHERE id = :id",
                "parameters": [
                    {"name": "id", "type": "integer", "required": True, "description": "Animal id"}
                ],
            }
        ],
    }
    cfg_path = tmp_path / "write.connector.json"
    cfg_path.write_text(json.dumps(write_connector))
    config = ConnectorCache().get(cfg_path)
    executor = ToolExecutor(config, secrets={})

    captured_args: dict[str, dict] = {}

    async def _fake(tool, args):  # type: ignore[no-untyped-def]
        from elliot_core.types.tool import ToolResult

        captured_args["last"] = args
        return ToolResult(rows=[{"deleted": args.get("id")}], meta={})

    executor.execute = _fake  # type: ignore[assignment]

    mcp = create_runtime_server(config, executor)

    class _Ctx:
        request_id = "confirm-req"

        async def info(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

        async def warning(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

    mcp.get_context = lambda: _Ctx()  # type: ignore[assignment]

    tool = mcp._tool_manager.get_tool("delete_animal")
    assert tool is not None

    # The handler must expose a `confirm` parameter so agents can discover the
    # gate from the tool schema.
    import inspect as _inspect

    sig = _inspect.signature(tool.fn)
    assert "confirm" in sig.parameters

    with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
        asyncio.run(tool.fn(id=1))
    assert "last" not in captured_args  # executor was not called

    # Re-call with confirm=true → succeeds and executor sees the original args
    # (no `confirm` kwarg leaks through).
    asyncio.run(tool.fn(id=1, confirm=True))
    assert captured_args["last"] == {"id": 1}


def test_read_tool_does_not_require_confirmation_even_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The confirmation gate is scoped to WRITE/ACTION; READ tools stay open."""
    import asyncio

    from elliot_connector_runtime.cache import ConnectorCache
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_connector_runtime.server import create_runtime_server

    monkeypatch.setenv("ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION", "true")

    cfg_path = tmp_path / "pets.connector.json"
    cfg_path.write_text(json.dumps(MINIMAL_CONNECTOR))
    config = ConnectorCache().get(cfg_path)
    executor = ToolExecutor(config, secrets={})

    async def _fake(tool, args):  # type: ignore[no-untyped-def]
        from elliot_core.types.tool import ToolResult

        return ToolResult(rows=[{"id": 1}], meta={})

    executor.execute = _fake  # type: ignore[assignment]

    mcp = create_runtime_server(config, executor)

    class _Ctx:
        request_id = "read-req"

        async def info(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

        async def warning(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

    mcp.get_context = lambda: _Ctx()  # type: ignore[assignment]

    tool = mcp._tool_manager.get_tool("list_animals")
    assert tool is not None
    import inspect as _inspect

    sig = _inspect.signature(tool.fn)
    assert "confirm" not in sig.parameters
    # No exception
    asyncio.run(tool.fn())


# ---------------------------------------------------------------------------
# No-connector fallback app
# ---------------------------------------------------------------------------


def test_no_connector_app_health_reports_missing(tmp_path: Path) -> None:
    """When the connector path does not exist, /health says no_connector."""
    missing = tmp_path / "absent" / "connector.json"
    app = create_app(connector_path=str(missing), secrets={})
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["status"] == "no_connector"
    assert body["connector"] == str(missing)


def test_no_connector_app_mcp_returns_503_not_404(tmp_path: Path) -> None:
    """The /mcp endpoint must exist even with no connector — clients should
    get an actionable 503, never a bare 404 that looks like a broken URL."""
    missing = tmp_path / "absent" / "connector.json"
    app = create_app(connector_path=str(missing), secrets={})
    client = TestClient(app)
    resp = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "RUNTIME_NO_CONNECTOR"


def test_no_connector_app_health_flips_when_connector_appears(tmp_path: Path) -> None:
    """Once a connector is written to the watched path, /health surfaces it."""
    path = tmp_path / "later.connector.json"
    app = create_app(connector_path=str(path), secrets={})
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "no_connector"

    path.write_text(json.dumps(MINIMAL_CONNECTOR))
    assert client.get("/health").json()["status"] == "connector_available"
