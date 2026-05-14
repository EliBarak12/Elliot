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
        # Session tracker NDJSON written
        sess_lines = sessions_path.read_text().strip().splitlines()
        assert len(sess_lines) == 1
        sess = json.loads(sess_lines[0])
        assert sess["session_id"] == "test-req-123"
        assert sess["total_tool_calls"] == 1
    finally:
        os.environ.pop("ELLIOT_AUDIT_LOG", None)
        os.environ.pop("ELLIOT_SESSIONS_LOG", None)
        os.environ.pop("ELLIOT_DB_URL", None)


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
