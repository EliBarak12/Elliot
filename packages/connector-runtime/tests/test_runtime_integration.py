"""
Integration tests for elliot-connector-runtime.

These tests spin up the FastAPI app via TestClient (no real server process)
and mock outbound HTTP calls with respx.
"""

from __future__ import annotations

import json
import time
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


def test_cache_ttl_expiry(tmp_path: Path) -> None:
    import elliot_connector_runtime.cache as cache_module

    p = tmp_path / "test.connector.json"
    p.write_text(json.dumps(MINIMAL_CONNECTOR))

    cache = cache_module.ConnectorCache(ttl_seconds=0.01)
    first = cache.get(p)

    time.sleep(0.05)
    second = cache.get(p)
    assert first is not second
