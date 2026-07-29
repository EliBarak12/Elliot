"""Tests for elliot_mcp_plugin.resources: cross-agent reference docs via MCP."""

from __future__ import annotations

import json

import pytest

from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.resources import register_resources


def test_register_resources_returns_count():
    mcp = FastMCP("test")
    count = register_resources(mcp)
    # 4 inline docs (principles, error-codes, install, authentication) + 4 templates
    assert count == 8


def test_resource_uris_use_elliot_scheme():
    mcp = FastMCP("test")
    register_resources(mcp)
    uris = {str(r.uri) for r in mcp._resource_manager._resources.values()}
    assert any(u.startswith("elliot://docs/") for u in uris)
    assert any(u.startswith("elliot://templates/") for u in uris)


def test_inline_docs_registered():
    mcp = FastMCP("test")
    register_resources(mcp)
    uris = {str(r.uri) for r in mcp._resource_manager._resources.values()}
    assert "elliot://docs/principles" in uris
    assert "elliot://docs/error-codes" in uris
    assert "elliot://docs/install" in uris
    assert "elliot://docs/authentication" in uris


def test_template_resources_registered():
    mcp = FastMCP("test")
    register_resources(mcp)
    uris = {str(r.uri) for r in mcp._resource_manager._resources.values()}
    assert "elliot://templates/rest-api-key" in uris
    assert "elliot://templates/postgres-readonly" in uris
    assert "elliot://templates/paginated-rest" in uris
    assert "elliot://templates/openapi-petstore" in uris


@pytest.mark.asyncio
async def test_principles_resource_content():
    mcp = FastMCP("test")
    register_resources(mcp)
    contents = await mcp.read_resource("elliot://docs/principles")
    text = contents[0].content
    assert "Five Principles" in text
    assert "verb-first" in text.lower()
    assert "context window" in text.lower()


@pytest.mark.asyncio
async def test_error_codes_resource_lists_known_codes():
    mcp = FastMCP("test")
    register_resources(mcp)
    contents = await mcp.read_resource("elliot://docs/error-codes")
    text = contents[0].content
    for code in (
        # Real published-runtime codes an agent hits calling a connector's tools.
        "MISSING_PARAM",
        "INVALID_PARAM_TYPE",
        "CONFIRMATION_REQUIRED",
        "UPSTREAM_FETCH_FAILED",
        "TOOL_NOT_FOUND",
        "AUTH_FAILED",
        # Builder-surface validation envelope.
        "VALIDATION_INVALID_PARAMS",
        "INTERNAL_ERROR",
    ):
        assert code in text
    # Phantom codes that were never raised must not reappear in the reference.
    assert "SOURCE_UNREACHABLE" not in text
    assert "QUERY_TIMEOUT" not in text


@pytest.mark.asyncio
async def test_authentication_resource_covers_per_user_auth():
    mcp = FastMCP("test")
    register_resources(mcp)
    contents = await mcp.read_resource("elliot://docs/authentication")
    text = contents[0].content
    # The per-user auth capability and its placeholder must be documented.
    assert "per_user" in text
    assert "{{ user_oauth:" in text
    assert "AUTH_REQUIRED" in text
    # The live-fetch / execution modes must be documented (corrects the
    # "frozen snapshot only" misconception).
    assert "rest_query_params" in text
    assert "api_mapping" in text


@pytest.mark.asyncio
async def test_install_resource_covers_three_install_paths():
    mcp = FastMCP("test")
    register_resources(mcp)
    contents = await mcp.read_resource("elliot://docs/install")
    text = contents[0].content
    assert "marketplace add" in text.lower()
    assert "npx" in text.lower() or "standalone" in text.lower()
    assert "mcpServers" in text or "mcp_servers" in text


@pytest.mark.asyncio
async def test_install_resource_documents_local_run():
    mcp = FastMCP("test")
    register_resources(mcp)
    contents = await mcp.read_resource("elliot://docs/install")
    text = contents[0].content
    # The OSS engine's install doc documents running the stack yourself; the
    # hosted Elliot Cloud builder swaps in its own localhost-free copy in the
    # cloud layer.
    assert "localhost" in text
    assert "make dev" in text


@pytest.mark.asyncio
async def test_template_resource_is_valid_json():
    mcp = FastMCP("test")
    register_resources(mcp)
    contents = await mcp.read_resource("elliot://templates/rest-api-key")
    text = contents[0].content
    # Templates must parse as valid JSON — they ship as the seed for new connectors
    parsed = json.loads(text)
    assert "name" in parsed
    assert "sources" in parsed
    assert "tools" in parsed


@pytest.mark.asyncio
async def test_template_mime_type_is_json():
    mcp = FastMCP("test")
    register_resources(mcp)
    for r in mcp._resource_manager._resources.values():
        if str(r.uri).startswith("elliot://templates/"):
            assert r.mime_type == "application/json"
