"""Tests for elliot_mcp_plugin.resources: cross-agent reference docs via MCP."""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.resources import register_resources


def test_register_resources_returns_count():
    mcp = FastMCP("test")
    count = register_resources(mcp)
    # 3 inline docs (principles, error-codes, install) + 4 templates
    assert count == 7


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
        "VALIDATION_INVALID_PARAMS",
        "TOOL_NOT_FOUND",
        "SOURCE_UNREACHABLE",
        "AUTH_FAILED",
        "INTERNAL_ERROR",
    ):
        assert code in text


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
