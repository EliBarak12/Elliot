"""Builder tools for managed sources: elliot_create_data_source / elliot_create_data_tool."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.source_tools import register_source_tools
from elliot_mcp_plugin.tools.tool_tools import register_tool_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_source_tools(server, session)
    register_tool_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):
    fn = mcp._tool_manager._tools[name].fn
    if inspect.iscoroutinefunction(fn):

        def sync_wrapper(*args, **kwargs):
            return asyncio.run(fn(*args, **kwargs))

        return sync_wrapper
    return fn


def _is_error(out: dict) -> bool:
    """Builder tools surface failures either as {"error": ...} or as the
    to_mcp_error_content shape {"type": "text", "text": "[CODE] ..."}."""
    return "error" in out or (
        out.get("type") == "text" and str(out.get("text", "")).startswith("[")
    )


_COLUMNS = [
    {"name": "title", "type": "string", "required": True, "description": "Task title"},
    {"name": "done", "type": "boolean"},
]


def _create_source(mcp: FastMCP) -> dict:
    return _tool(mcp, "elliot_create_data_source")(name="tasks", columns=_COLUMNS)


class TestCreateDataSource:
    def test_creates_source_and_empty_table(self, mcp, session):
        out = _create_source(mcp)
        assert out.get("table_name") == "tasks", out
        src = session.sources[out["source_id"]]
        assert src.type == "elliot"
        assert [c.name for c in src.columns] == ["title", "done"]
        assert src.user_scoped is True
        # The empty table is queryable at design time.
        cols = {c["name"] for c in session.engine.get_table_schema("tasks")}
        assert {"_id", "_owner_id", "title", "done"} <= cols

    def test_rejects_reserved_column_names(self, mcp):
        out = _tool(mcp, "elliot_create_data_source")(name="bad", columns=[{"name": "_owner_id"}])
        assert _is_error(out), out

    def test_rejects_empty_columns(self, mcp):
        out = _tool(mcp, "elliot_create_data_source")(name="bad", columns=[])
        assert _is_error(out), out

    def test_rejects_duplicate_table(self, mcp):
        assert not _is_error(_create_source(mcp))
        assert _is_error(_create_source(mcp))


class TestCreateDataTool:
    def test_insert_tool_created_with_mapping(self, mcp, session):
        source_id = _create_source(mcp)["source_id"]
        out = _tool(mcp, "elliot_create_data_tool")(
            name="add_task",
            description="Creates a task for the calling user.",
            source_id=source_id,
            operation="insert",
            parameters=[
                {"name": "title", "type": "string", "required": True, "description": "Title"},
                {"name": "done", "type": "boolean", "required": False, "description": "Done"},
            ],
            column_params={"title": "title", "done": "done"},
        )
        assert out.get("status") == "created", out
        tool = session.registry.get(out["tool_id"])
        assert tool.category == "WRITE"
        assert tool.data_mapping.operation == "insert"
        assert tool.data_mapping.column_params == {"title": "title", "done": "done"}

    def test_update_requires_key_param(self, mcp):
        source_id = _create_source(mcp)["source_id"]
        out = _tool(mcp, "elliot_create_data_tool")(
            name="update_task",
            description="Updates a task title.",
            source_id=source_id,
            operation="update",
            parameters=[
                {"name": "title", "type": "string", "required": True, "description": "Title"},
            ],
            column_params={"title": "title"},
        )
        assert _is_error(out), out

    def test_unknown_column_rejected(self, mcp):
        source_id = _create_source(mcp)["source_id"]
        out = _tool(mcp, "elliot_create_data_tool")(
            name="add_task",
            description="Creates a task for the calling user.",
            source_id=source_id,
            operation="insert",
            parameters=[
                {"name": "nope", "type": "string", "required": True, "description": "x"},
            ],
            column_params={"nope": "nope"},
        )
        assert _is_error(out), out

    def test_unrouted_param_rejected(self, mcp):
        source_id = _create_source(mcp)["source_id"]
        out = _tool(mcp, "elliot_create_data_tool")(
            name="add_task",
            description="Creates a task for the calling user.",
            source_id=source_id,
            operation="insert",
            parameters=[
                {"name": "title", "type": "string", "required": True, "description": "Title"},
                {"name": "stray", "type": "string", "required": False, "description": "unused"},
            ],
            column_params={"title": "title"},
        )
        assert _is_error(out), out

    def test_rest_source_rejected(self, mcp, session):
        from elliot_core.types.source import SourceConfig

        session.sources["api1"] = SourceConfig.model_validate(
            {"id": "api1", "type": "rest", "name": "api1", "url": "https://api.example.com"}
        )
        out = _tool(mcp, "elliot_create_data_tool")(
            name="add_task",
            description="Creates a task for the calling user.",
            source_id="api1",
            operation="insert",
            parameters=[
                {"name": "title", "type": "string", "required": True, "description": "Title"},
            ],
            column_params={"title": "title"},
        )
        assert _is_error(out), out

    def test_delete_tool_preview_refused(self, mcp, session):
        from elliot_mcp_plugin.tools.tool_tools import preview_tool

        source_id = _create_source(mcp)["source_id"]
        out = _tool(mcp, "elliot_create_data_tool")(
            name="delete_task",
            description="Deletes a task by its id.",
            source_id=source_id,
            operation="delete",
            parameters=[
                {"name": "task_id", "type": "string", "required": True, "description": "_id"},
            ],
            key_param="task_id",
        )
        assert out.get("status") == "created", out
        from elliot_core.errors import ElliotError

        with pytest.raises(ElliotError) as exc:
            preview_tool(session, out["tool_id"], {"task_id": "x"})
        assert exc.value.code == "ACTION_PREVIEW_UNAVAILABLE"
