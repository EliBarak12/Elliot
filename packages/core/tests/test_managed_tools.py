"""Managed-source tools end to end: validator, linter, and executor write path."""

from __future__ import annotations

import pytest

from elliot_core.errors import ElliotError
from elliot_core.linter import lint_connector
from elliot_core.sqlite.managed_store import ManagedStore
from elliot_core.tools.executor import ToolExecutor
from elliot_core.tools.validator import validate_tool_definition
from elliot_core.types import ConnectorConfig, ManagedColumn, SourceConfig
from elliot_core.user_identity import (
    UserScope,
    reset_current_user_scope,
    set_current_user_scope,
)


def _source() -> SourceConfig:
    return SourceConfig(
        id="tasks",
        name="tasks",
        type="elliot",
        table_name="tasks",
        columns=[
            ManagedColumn(name="title", required=True),
            ManagedColumn(name="done", type="boolean"),
        ],
    )


def _insert_tool() -> dict:
    return {
        "id": "add_task",
        "name": "add_task",
        "description": "Creates a task for the calling user.",
        "category": "WRITE",
        "source_ids": ["tasks"],
        "parameters": [
            {"name": "title", "type": "string", "required": True, "description": "Task title"},
            {"name": "done", "type": "boolean", "required": False, "description": "Done flag"},
        ],
        "data_mapping": {
            "operation": "insert",
            "column_params": {"title": "title", "done": "done"},
        },
    }


def _config(tools: list[dict]) -> ConnectorConfig:
    return ConnectorConfig.model_validate(
        {
            "name": "todo-app",
            "slug": "todo-app",
            "version": "1.0.0",
            "description": "Managed to-do app",
            "sources": [_source().model_dump()],
            "tools": tools,
        }
    )


class TestValidator:
    def test_data_mapping_satisfies_write_requirement(self):
        tool = validate_tool_definition(_insert_tool())
        assert tool.data_mapping is not None

    def test_write_without_any_mapping_rejected(self):
        bad = _insert_tool()
        bad.pop("data_mapping")
        with pytest.raises(ElliotError):
            validate_tool_definition(bad)

    def test_both_mappings_rejected(self):
        bad = _insert_tool()
        bad["api_mapping"] = {"method": "POST", "body_params": ["title"]}
        with pytest.raises(ElliotError):
            validate_tool_definition(bad)

    def test_undeclared_column_param_rejected(self):
        bad = _insert_tool()
        bad["data_mapping"]["column_params"] = {"title": "missing_param"}
        with pytest.raises(ElliotError):
            validate_tool_definition(bad)

    def test_update_requires_key_param(self):
        bad = _insert_tool()
        bad["data_mapping"] = {"operation": "update", "column_params": {"title": "title"}}
        with pytest.raises(ElliotError):
            validate_tool_definition(bad)

    def test_insert_requires_column_params(self):
        bad = _insert_tool()
        bad["data_mapping"] = {"operation": "insert", "column_params": {}}
        with pytest.raises(ElliotError):
            validate_tool_definition(bad)


class TestLinter:
    def test_clean_managed_connector_has_no_data_errors(self):
        issues = lint_connector(_config([_insert_tool()]))
        assert not [i for i in issues if i.code.startswith(("DATA_MAPPING", "MANAGED_SOURCE"))]

    def test_managed_source_without_columns_flagged(self):
        config = _config([])
        config.sources[0].columns = []
        codes = {i.code for i in lint_connector(config)}
        assert "MANAGED_SOURCE_NO_COLUMNS" in codes

    def test_unknown_column_flagged(self):
        tool = _insert_tool()
        tool["data_mapping"]["column_params"] = {"nope": "title"}
        codes = {i.code for i in lint_connector(_config([tool]))}
        assert "DATA_MAPPING_UNKNOWN_COLUMN" in codes

    def test_required_column_unmapped_flagged(self):
        tool = _insert_tool()
        tool["data_mapping"]["column_params"] = {"done": "done"}
        codes = {i.code for i in lint_connector(_config([tool]))}
        assert "DATA_MAPPING_REQUIRED_COLUMN_UNMAPPED" in codes

    def test_data_mapping_on_rest_source_flagged(self):
        tool = _insert_tool()
        config = _config([tool])
        config.sources[0].type = "rest"
        config.sources[0].url = "https://example.com"
        codes = {i.code for i in lint_connector(config)}
        assert "DATA_MAPPING_SOURCE_TYPE" in codes


@pytest.fixture
def scoped_user_a():
    token = set_current_user_scope(UserScope(user_id="user-a", email="a@example.com"))
    yield
    reset_current_user_scope(token)


class TestExecutorDataWrite:
    def _executor(self, store: ManagedStore, extra_tools: list[dict] | None = None) -> ToolExecutor:
        read_tool = {
            "id": "list_tasks",
            "name": "list_tasks",
            "description": "Returns the caller's tasks.",
            "category": "READ",
            "source_ids": ["tasks"],
            "sql": 'SELECT _id, title, done FROM "tasks" ORDER BY _created_at',
        }
        config = _config([_insert_tool(), read_tool, *(extra_tools or [])])
        return ToolExecutor(config, managed_store=store)

    @pytest.mark.asyncio
    async def test_insert_then_read_back(self, scoped_user_a):
        store = ManagedStore(":memory:")
        executor = self._executor(store)
        result = await executor.execute("add_task", {"title": "write tests", "done": False})
        assert result.meta["fetch_mode"] == "data_write"
        assert result.rows[0]["_owner_id"] == "user-a"

        read = await executor.execute("list_tasks", {})
        assert [r["title"] for r in read.rows] == ["write tests"]

    @pytest.mark.asyncio
    async def test_read_is_scoped_to_caller(self, scoped_user_a):
        store = ManagedStore(":memory:")
        store.insert_row(_source(), {"title": "someone elses"}, "user-b")
        executor = self._executor(store)
        read = await executor.execute("list_tasks", {})
        assert read.rows == []

    @pytest.mark.asyncio
    async def test_update_and_delete_via_key_param(self, scoped_user_a):
        store = ManagedStore(":memory:")
        update_tool = {
            "id": "complete_task",
            "name": "complete_task",
            "description": "Marks a task as done.",
            "category": "WRITE",
            "source_ids": ["tasks"],
            "parameters": [
                {"name": "task_id", "type": "string", "required": True, "description": "Row _id"},
                {"name": "done", "type": "boolean", "required": True, "description": "Done flag"},
            ],
            "data_mapping": {
                "operation": "update",
                "column_params": {"done": "done"},
                "key_param": "task_id",
            },
        }
        delete_tool = {
            "id": "delete_task",
            "name": "delete_task",
            "description": "Deletes a task by id.",
            "category": "WRITE",
            "source_ids": ["tasks"],
            "parameters": [
                {"name": "task_id", "type": "string", "required": True, "description": "Row _id"},
            ],
            "data_mapping": {"operation": "delete", "key_param": "task_id"},
        }
        executor = self._executor(store, [update_tool, delete_tool])
        created = await executor.execute("add_task", {"title": "x"})
        row_id = created.rows[0]["_id"]

        updated = await executor.execute("complete_task", {"task_id": row_id, "done": True})
        assert updated.rows[0]["done"] == 1

        deleted = await executor.execute("delete_task", {"task_id": row_id})
        assert deleted.rows[0]["deleted"] is True

    @pytest.mark.asyncio
    async def test_update_missing_key_value_rejected(self, scoped_user_a):
        store = ManagedStore(":memory:")
        update_tool = {
            "id": "rename_task",
            "name": "rename_task",
            "description": "Renames a task.",
            "category": "WRITE",
            "source_ids": ["tasks"],
            "parameters": [
                {"name": "task_id", "type": "string", "required": False, "description": "Row _id"},
                {"name": "title", "type": "string", "required": True, "description": "New title"},
            ],
            "data_mapping": {
                "operation": "update",
                "column_params": {"title": "title"},
                "key_param": "task_id",
            },
        }
        executor = self._executor(store, [update_tool])
        with pytest.raises(ElliotError) as exc:
            await executor.execute("rename_task", {"title": "y"})
        assert exc.value.code == "VALIDATION_REQUIRED"
