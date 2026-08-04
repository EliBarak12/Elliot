"""Published-runtime behavior for managed ("elliot") sources.

The critical property under test: managed rows are scoped PER CALLER at
execution time — two users hitting the same runtime instance in sequence must
each see only their own rows (no shared-engine cache leakage), and mutations
must respect ownership and write grants.
"""

from __future__ import annotations

import pytest

from elliot_connector_runtime.executor import ToolExecutor
from elliot_core.errors import ElliotError
from elliot_core.sqlite.managed_store import ManagedStore
from elliot_core.types import ConnectorConfig
from elliot_core.user_identity import (
    UserScope,
    reset_current_user_scope,
    set_current_user_scope,
)

CONFIG = ConnectorConfig.model_validate(
    {
        "name": "todo-app",
        "slug": "todo-app",
        "version": "1.0.0",
        "sources": [
            {
                "id": "tasks",
                "name": "tasks",
                "type": "elliot",
                "table_name": "tasks",
                "columns": [
                    {"name": "title", "type": "string", "required": True},
                    {"name": "done", "type": "boolean"},
                ],
            }
        ],
        "tools": [
            {
                "id": "add_task",
                "name": "add_task",
                "description": "Creates a task owned by the calling user.",
                "category": "WRITE",
                "source_ids": ["tasks"],
                "parameters": [
                    {"name": "title", "type": "string", "required": True, "description": "Title"},
                ],
                "data_mapping": {
                    "operation": "insert",
                    "column_params": {"title": "title"},
                },
            },
            {
                "id": "list_tasks",
                "name": "list_tasks",
                "description": "Returns the calling user's tasks.",
                "category": "READ",
                "source_ids": ["tasks"],
                "sql": 'SELECT _id, title, _owner_id FROM "tasks" ORDER BY _created_at',
            },
            {
                "id": "delete_task",
                "name": "delete_task",
                "description": "Deletes a task by its _id.",
                "category": "WRITE",
                "source_ids": ["tasks"],
                "parameters": [
                    {"name": "task_id", "type": "string", "required": True, "description": "_id"},
                ],
                "data_mapping": {"operation": "delete", "key_param": "task_id"},
            },
        ],
    }
)


def _scope(user: str, *, readable: tuple[str, ...] = (), writable: tuple[str, ...] = ()):
    return UserScope(user_id=user, readable_owner_ids=readable, writable_owner_ids=writable)


class _As:
    """Context manager binding a user scope for the duration of a call."""

    def __init__(self, scope: UserScope) -> None:
        self._scope = scope
        self._token = None

    def __enter__(self):
        self._token = set_current_user_scope(self._scope)
        return self

    def __exit__(self, *exc):
        reset_current_user_scope(self._token)
        return False


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(CONFIG, {}, managed_store=ManagedStore(":memory:"))


def _tool(tool_id: str):
    return next(t for t in CONFIG.tools if t.id == tool_id)


async def test_rows_do_not_leak_between_users(executor):
    with _As(_scope("alice")):
        await executor.execute(_tool("add_task"), {"title": "alice task"})
    with _As(_scope("bob")):
        await executor.execute(_tool("add_task"), {"title": "bob task"})

    # Same executor instance, sequential calls by different users: each must
    # see only their own rows even though reads go through SQLite each time.
    with _As(_scope("alice")):
        result = await executor.execute(_tool("list_tasks"), {})
        assert [r["title"] for r in result.rows] == ["alice task"]
    with _As(_scope("bob")):
        result = await executor.execute(_tool("list_tasks"), {})
        assert [r["title"] for r in result.rows] == ["bob task"]


async def test_read_grant_widens_visibility(executor):
    with _As(_scope("alice")):
        await executor.execute(_tool("add_task"), {"title": "shared with bob"})
    with _As(_scope("bob", readable=("alice",))):
        result = await executor.execute(_tool("list_tasks"), {})
        assert [r["_owner_id"] for r in result.rows] == ["alice"]


async def test_delete_respects_write_grants(executor):
    with _As(_scope("alice")):
        created = await executor.execute(_tool("add_task"), {"title": "guarded"})
        row_id = created.rows[0]["_id"]

    # A read-only grant must NOT allow deletion.
    with _As(_scope("bob", readable=("alice",))), pytest.raises(ElliotError):
        await executor.execute(_tool("delete_task"), {"task_id": row_id})

    # A write grant does.
    with _As(_scope("bob", readable=("alice",), writable=("alice",))):
        result = await executor.execute(_tool("delete_task"), {"task_id": row_id})
        assert result.rows[0]["deleted"] is True


async def test_unscoped_local_mode_sees_everything(executor):
    with _As(_scope("alice")):
        await executor.execute(_tool("add_task"), {"title": "a"})
    with _As(_scope("bob")):
        await executor.execute(_tool("add_task"), {"title": "b"})
    # No identity bound at all — the local single-user runtime.
    result = await executor.execute(_tool("list_tasks"), {})
    assert len(result.rows) == 2
