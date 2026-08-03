"""Tests for the onboarding MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.onboarding_tools import register_onboarding_tools

_OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "Demo API", "version": "2.0.0"},
    "paths": {"/items": {"get": {"operationId": "listItems", "summary": "List items"}}},
}

_POSTMAN = {
    "info": {
        "name": "Demo API",
        "_postman_id": "x",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        {
            "name": "List Items",
            "request": {"method": "GET", "url": "https://api.demo.com/items"},
        }
    ],
}


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_onboarding_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):  # type: ignore[no-untyped-def]
    return mcp._tool_manager._tools[name].fn


def test_record_product_intent_stores_on_session(mcp: FastMCP, session: ElliotSession) -> None:
    result = _tool(mcp, "elliot_record_product_intent")(
        agent_consumers=["support bot"],
        jobs_to_be_done=["find a customer's orders"],
        sensitive_fields=["ssn"],
    )
    assert result["status"] == "recorded"
    assert result["jobs_to_be_done"] == 1
    assert session.product_intent is not None
    assert session.product_intent.sensitive_fields == ["ssn"]


def test_record_product_intent_persists(mcp: FastMCP, session: ElliotSession) -> None:
    _tool(mcp, "elliot_record_product_intent")(jobs_to_be_done=["job a"])
    reloaded = ElliotSession(cwd=str(Path(session.workspace._dir).parent))
    reloaded.load()
    assert reloaded.product_intent is not None
    assert reloaded.product_intent.jobs_to_be_done == ["job a"]


def test_get_product_intent_empty(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_get_product_intent")()
    assert result["recorded"] is False


def test_get_product_intent_after_record(mcp: FastMCP) -> None:
    _tool(mcp, "elliot_record_product_intent")(notes="hello")
    result = _tool(mcp, "elliot_get_product_intent")()
    assert result["recorded"] is True
    assert result["intent"]["notes"] == "hello"


def test_import_openapi(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")(json.dumps(_OPENAPI))
    assert result["status"] == "imported"
    assert result["format"] == "openapi"
    assert result["proposed"]["tools"]


def test_import_postman(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")(json.dumps(_POSTMAN))
    assert result["status"] == "imported"
    assert result["format"] == "postman"


def test_import_bad_json(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")("{not json")
    assert "text" in result or "error" in result


def test_import_unrecognised_json(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")(json.dumps({"random": "object"}))
    assert "text" in result or "error" in result


_OPENAPI_YAML = """
openapi: 3.0.0
info:
  title: Yaml Demo
  version: "1.0"
servers:
  - url: https://yaml.demo.com
paths:
  /items:
    get:
      operationId: listItems
      summary: List items
      responses:
        "200": {}
"""

_SWAGGER2 = {
    "swagger": "2.0",
    "info": {"title": "Legacy Demo", "version": "1.0"},
    "host": "legacy.demo.com",
    "basePath": "/v1",
    "paths": {
        "/items": {"get": {"operationId": "listItems", "responses": {"200": {"description": "ok"}}}}
    },
}

_OPENAPI_WITH_AUTH = {
    "openapi": "3.0.0",
    "info": {"title": "Auth Demo", "version": "1.0"},
    "servers": [{"url": "https://auth.demo.com"}],
    "components": {"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}}},
    "paths": {"/items": {"get": {"operationId": "listItems", "responses": {"200": {}}}}},
}


def test_import_pasted_yaml(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")(_OPENAPI_YAML)
    assert result["status"] == "imported"
    assert result["format"] == "openapi"
    assert result["proposed"]["slug"] == "yaml-demo"


def test_import_swagger2_is_converted(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")(json.dumps(_SWAGGER2))
    assert result["status"] == "imported"
    assert result["proposed"]["sources"][0]["base_url"] == "https://legacy.demo.com/v1"
    assert any("Swagger 2.0" in w for w in result["proposed"]["warnings"])


def test_import_surfaces_auth_block_and_secret_names(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")(json.dumps(_OPENAPI_WITH_AUTH))
    assert result["status"] == "imported"
    auth = result["proposed"]["sources"][0]["auth"]
    assert auth["type"] == "api_key"
    assert auth["header_name"] == "X-Key"
    assert "AUTH_DEMO_API_KEY" in result["next"]


def test_import_unparseable_text_is_actionable(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_import_api_collection")("just some prose, not a spec")
    text = str(result)
    assert "UNRECOGNISED_COLLECTION" in text or "error" in result
