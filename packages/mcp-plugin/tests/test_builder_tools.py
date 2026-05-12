"""Tests for agentic builder tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_mcp_plugin.tools.builder_tools import (
    _drafts,
    add_tool_to_draft,
    analyze_api_spec,
    create_draft,
    discard_draft,
    list_drafts,
    list_saved_connectors,
    remove_tool_from_draft,
    run_draft_lint,
    save_draft,
    update_tool_in_draft,
)

PROPOSED = {
    "name": "Pets",
    "slug": "pets",
    "version": "1.0.0",
    "sources": [
        {
            "id": "api",
            "name": "API",
            "type": "rest",
            "base_url": "https://api.pets.com",
            "auth_hint": None,
        }
    ],
    "tools": [
        {
            "id": "list_pets",
            "name": "List Pets",
            "description": "Return all pets",
            "category": "READ",
            "http_method": "GET",
            "http_path": "/pets",
            "parameters": [],
            "response_fields": ["id", "name"],
            "token_risk": "low",
        }
    ],
    "warnings": [],
}


@pytest.fixture(autouse=True)
def clear_drafts() -> None:
    _drafts.clear()


def test_create_draft_returns_draft_id() -> None:
    result = create_draft(json.dumps(PROPOSED))
    assert "draft_id" in result
    assert result["tool_count"] == 1


def test_list_drafts_shows_active() -> None:
    create_draft(json.dumps(PROPOSED))
    drafts = list_drafts()
    assert len(drafts) == 1
    assert drafts[0]["name"] == "Pets"


def test_update_tool_changes_description() -> None:
    r = create_draft(json.dumps(PROPOSED))
    did = r["draft_id"]
    result = update_tool_in_draft(did, "list_pets", '{"description": "Return all available pets"}')
    assert result["ok"] is True
    assert result["tool"]["description"] == "Return all available pets"


def test_update_unknown_tool_returns_error() -> None:
    r = create_draft(json.dumps(PROPOSED))
    result = update_tool_in_draft(r["draft_id"], "no_such_tool", '{"description": "x"}')
    assert "error" in result


def test_remove_tool_from_draft() -> None:
    r = create_draft(json.dumps(PROPOSED))
    did = r["draft_id"]
    result = remove_tool_from_draft(did, "list_pets")
    assert result["removed"] == 1
    assert len(_drafts[did]["tools"]) == 0


def test_add_tool_to_draft() -> None:
    r = create_draft(json.dumps(PROPOSED))
    did = r["draft_id"]
    new_tool = {
        "id": "get_pet",
        "name": "Get Pet",
        "description": "Return a pet",
        "category": "READ",
    }
    result = add_tool_to_draft(did, json.dumps(new_tool))
    assert result["total_tools"] == 2


def test_run_draft_lint_returns_issues() -> None:
    draft = {
        "name": "Bad",
        "slug": "bad",
        "version": "1.0.0",
        "sources": [],
        "tools": [
            {
                "id": "x",
                "name": "X",
                "description": "Bad",
                "category": "READ",
                "source_ids": [],
                "sql": "SELECT * FROM t",
                "parameters": [],
            }
        ],
        "skills": [],
    }
    r = create_draft(json.dumps(draft))
    result = run_draft_lint(r["draft_id"])
    assert "issues" in result
    assert result["errors"] >= 0


def test_save_draft_writes_file(tmp_path: Path) -> None:
    r = create_draft(json.dumps(PROPOSED))
    did = r["draft_id"]
    result = save_draft(did, "pets.connector.json", str(tmp_path))
    assert (tmp_path / "pets.connector.json").exists()
    assert result["tools"] == 1
    assert did not in _drafts


def test_discard_draft_removes_it() -> None:
    r = create_draft(json.dumps(PROPOSED))
    did = r["draft_id"]
    result = discard_draft(did)
    assert result["discarded"] is True
    assert did not in _drafts


def test_discard_unknown_returns_false() -> None:
    result = discard_draft("notexist")
    assert result["discarded"] is False


def test_list_saved_connectors(tmp_path: Path) -> None:
    (tmp_path / "pets.connector.json").write_text(
        json.dumps({"name": "Pets", "slug": "pets", "version": "1.0", "tools": []})
    )
    connectors = list_saved_connectors(str(tmp_path))
    assert len(connectors) == 1
    assert connectors[0]["slug"] == "pets"


def test_analyze_api_spec_invalid_returns_error() -> None:
    result = analyze_api_spec('{"info": {"title": "no openapi key"}}')
    assert "error" in result


def test_update_draft_not_found_returns_error() -> None:
    result = update_tool_in_draft("badid", "tool", "{}")
    assert "error" in result


def test_register_builder_tools_registers_all_tools() -> None:
    from mcp.server.fastmcp import FastMCP

    from elliot_mcp_plugin.tools.builder_tools import register_builder_tools

    mcp = FastMCP("test")
    register_builder_tools(mcp)
    names = {t for t in mcp._tool_manager._tools}
    expected = {
        "elliot_analyze_api_spec",
        "elliot_create_draft",
        "elliot_list_drafts",
        "elliot_update_tool_in_draft",
        "elliot_remove_tool_from_draft",
        "elliot_add_tool_to_draft",
        "elliot_run_draft_lint",
        "elliot_save_draft",
        "elliot_discard_draft",
        "elliot_list_saved_connectors",
    }
    assert expected.issubset(names)


def test_registered_list_drafts_and_create_draft(tmp_path: Path) -> None:
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from elliot_mcp_plugin.tools.builder_tools import _drafts, register_builder_tools

    _drafts.clear()
    mcp = FastMCP("test")
    register_builder_tools(mcp)

    tools = mcp._tool_manager._tools

    async def run() -> None:
        drafts = await tools["elliot_list_drafts"].run({})
        assert drafts == []

        draft = await tools["elliot_create_draft"].run(
            {"proposed_connector_json": json.dumps({"name": "X", "slug": "x", "tools": []})}
        )
        assert "draft_id" in draft

        drafts2 = await tools["elliot_list_drafts"].run({})
        assert len(drafts2) == 1

        did = draft["draft_id"]
        discarded = await tools["elliot_discard_draft"].run({"draft_id": did})
        assert discarded["discarded"] is True

    asyncio.run(run())


def test_registered_list_saved_connectors(tmp_path: Path) -> None:
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from elliot_mcp_plugin.tools.builder_tools import register_builder_tools

    mcp = FastMCP("test")
    register_builder_tools(mcp)
    tools = mcp._tool_manager._tools

    async def run() -> None:
        result = await tools["elliot_list_saved_connectors"].run({"connectors_dir": str(tmp_path)})
        assert result == []

    asyncio.run(run())
