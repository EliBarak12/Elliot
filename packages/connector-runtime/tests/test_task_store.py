"""Tests for elliot_connector_runtime.task_store."""

from __future__ import annotations

import asyncio
import time

import pytest

from elliot_connector_runtime.task_store import (
    _TASK_TTL_SECONDS,
    TaskRecord,
    TaskStore,
    get_task_store,
    make_async_tool_wrapper,
)

# ---------------------------------------------------------------------------
# TaskRecord
# ---------------------------------------------------------------------------


def test_task_record_to_dict_fields():
    rec = TaskRecord(task_id="abc123", tool_id="search_users")
    d = rec.to_dict()
    assert d["task_id"] == "abc123"
    assert d["tool_id"] == "search_users"
    assert d["status"] == "pending"
    assert d["result"] is None
    assert d["error"] is None
    assert d["duration_ms"] is None
    assert "created_at" in d
    assert "updated_at" in d


# ---------------------------------------------------------------------------
# TaskStore.submit + get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_returns_task_id_and_record_is_queryable():
    store = TaskStore()

    async def _coro() -> dict:
        return {"rows": [{"id": 1}], "count": 1}

    task_id = store.submit("list_items", _coro())
    assert len(task_id) == 12

    rec = store.get(task_id)
    assert rec is not None
    assert rec.tool_id == "list_items"

    # Allow the background coroutine to complete
    await asyncio.sleep(0)
    rec = store.get(task_id)
    assert rec is not None
    assert rec.status == "completed"
    assert rec.result == {"rows": [{"id": 1}], "count": 1}
    assert rec.duration_ms is not None


@pytest.mark.asyncio
async def test_submit_failed_coro_records_error():
    store = TaskStore()

    async def _bad() -> dict:
        raise RuntimeError("db connection refused")

    task_id = store.submit("broken_tool", _bad())
    await asyncio.sleep(0)

    rec = store.get(task_id)
    assert rec is not None
    assert rec.status == "failed"
    assert "db connection refused" in (rec.error or "")
    assert rec.duration_ms is not None


def test_get_unknown_task_returns_none():
    store = TaskStore()
    assert store.get("nonexistent") is None


# ---------------------------------------------------------------------------
# TaskStore.prune
# ---------------------------------------------------------------------------


def test_prune_removes_stale_completed_tasks():
    store = TaskStore()
    rec = TaskRecord(task_id="old1", tool_id="t", status="completed")
    rec.updated_at = time.time() - _TASK_TTL_SECONDS - 1
    store._tasks["old1"] = rec

    # Also add a fresh completed task — should NOT be pruned
    fresh = TaskRecord(task_id="fresh1", tool_id="t", status="completed")
    store._tasks["fresh1"] = fresh

    # Add a still-running task — should NOT be pruned
    running = TaskRecord(task_id="run1", tool_id="t", status="running")
    running.updated_at = time.time() - _TASK_TTL_SECONDS - 1
    store._tasks["run1"] = running

    removed = store.prune()
    assert removed == 1
    assert "old1" not in store._tasks
    assert "fresh1" in store._tasks
    assert "run1" in store._tasks


def test_prune_removes_stale_failed_tasks():
    store = TaskStore()
    rec = TaskRecord(task_id="fail1", tool_id="t", status="failed")
    rec.updated_at = time.time() - _TASK_TTL_SECONDS - 1
    store._tasks["fail1"] = rec

    removed = store.prune()
    assert removed == 1
    assert "fail1" not in store._tasks


def test_prune_empty_store_returns_zero():
    store = TaskStore()
    assert store.prune() == 0


# ---------------------------------------------------------------------------
# TaskStore.list_recent
# ---------------------------------------------------------------------------


def test_list_recent_returns_sorted_descending():
    store = TaskStore()
    for i in range(5):
        rec = TaskRecord(task_id=f"t{i}", tool_id="search")
        rec.created_at = time.time() + i
        store._tasks[f"t{i}"] = rec

    result = store.list_recent(limit=3)
    assert len(result) == 3
    assert result[0]["task_id"] == "t4"
    assert result[1]["task_id"] == "t3"
    assert result[2]["task_id"] == "t2"


def test_list_recent_default_limit():
    store = TaskStore()
    for i in range(25):
        store._tasks[f"t{i}"] = TaskRecord(task_id=f"t{i}", tool_id="x")
    result = store.list_recent()
    assert len(result) == 20


# ---------------------------------------------------------------------------
# get_task_store singleton
# ---------------------------------------------------------------------------


def test_get_task_store_returns_same_instance():
    a = get_task_store()
    b = get_task_store()
    assert a is b


# ---------------------------------------------------------------------------
# make_async_tool_wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_async_tool_wrapper_returns_accepted():
    store = TaskStore()

    async def _factory(**kwargs: object) -> dict:
        return {"rows": [], "count": 0}

    wrapper = make_async_tool_wrapper("my_tool", _factory, store)
    result = await wrapper(limit=10)
    assert result["status"] == "accepted"
    assert "task_id" in result
    assert "my_tool" in result["message"]
