"""Background task store for long-running connector tool executions.

When a tool call is expected to exceed ELLIOT_TASK_THRESHOLD_MS (default 5000 ms),
callers can submit it here and poll for the result via the REST endpoint or the
elliot_get_task MCP tool rather than blocking the MCP connection.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

TaskStatus = Literal["pending", "running", "completed", "failed"]

TASK_THRESHOLD_MS = int(os.environ.get("ELLIOT_TASK_THRESHOLD_MS", "5000"))
_TASK_TTL_SECONDS = 3600  # retain completed tasks for 1 hour


@dataclass
class TaskRecord:
    task_id: str
    tool_id: str
    status: TaskStatus = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tool_id": self.tool_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "duration_ms": self.duration_ms,
        }


class TaskStore:
    """In-memory store for background tool executions."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        # Keep strong references to in-flight asyncio.Task objects so the
        # event loop cannot garbage-collect them mid-await (audit H7) and so
        # we can cancel them cleanly on app shutdown.
        self._inflight: dict[str, asyncio.Task[None]] = {}

    def submit(
        self,
        tool_id: str,
        coro: Coroutine[Any, Any, dict[str, Any]],
    ) -> str:
        task_id = uuid.uuid4().hex[:12]
        record = TaskRecord(task_id=task_id, tool_id=tool_id, status="pending")
        self._tasks[task_id] = record
        task = asyncio.ensure_future(self._run(record, coro))
        self._inflight[task_id] = task

        def _cleanup(_t: asyncio.Task[None], tid: str = task_id) -> None:
            self._inflight.pop(tid, None)

        task.add_done_callback(_cleanup)
        log.info("task.submitted", task_id=task_id, tool_id=tool_id)
        return task_id

    async def _run(
        self,
        record: TaskRecord,
        coro: Coroutine[Any, Any, dict[str, Any]],
    ) -> None:
        record.status = "running"
        record.updated_at = time.time()
        t0 = time.monotonic()
        try:
            record.result = await coro
            record.status = "completed"
            log.info("task.completed", task_id=record.task_id, tool_id=record.tool_id)
        except asyncio.CancelledError:
            record.status = "failed"
            record.error = "cancelled (server shutting down)"
            log.info("task.cancelled", task_id=record.task_id)
            raise
        except Exception as exc:
            record.error = str(exc)
            record.status = "failed"
            log.warning("task.failed", task_id=record.task_id, error=str(exc))
        finally:
            record.duration_ms = round((time.monotonic() - t0) * 1000, 1)
            record.updated_at = time.time()

    async def cancel_all(self) -> int:
        """Cancel every in-flight task. Called on app shutdown so we never
        leave tasks marked ``running`` after the loop closes (audit H7).
        Returns the number of tasks cancelled."""
        tasks = list(self._inflight.values())
        if not tasks:
            return 0
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("task.cancel_all", count=len(tasks))
        return len(tasks)

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def prune(self) -> int:
        cutoff = time.time() - _TASK_TTL_SECONDS
        stale = [
            tid
            for tid, rec in self._tasks.items()
            if rec.status in ("completed", "failed") and rec.updated_at < cutoff
        ]
        for tid in stale:
            del self._tasks[tid]
        return len(stale)

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        sorted_tasks = sorted(self._tasks.values(), key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in sorted_tasks[:limit]]


# Module-level singleton — shared across the app lifetime
_store = TaskStore()


def get_task_store() -> TaskStore:
    return _store


def make_async_tool_wrapper(
    tool_id: str,
    coro_factory: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
    store: TaskStore,
) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    """
    Wrap a coroutine factory so that calls are submitted to the task store
    instead of blocking. Returns a dict with task_id that the agent can poll.
    """

    async def wrapper(**kwargs: Any) -> dict[str, Any]:
        task_id = store.submit(tool_id, coro_factory(**kwargs))
        return {
            "status": "accepted",
            "task_id": task_id,
            "message": (
                f"Tool '{tool_id}' is running in the background. "
                f"Call elliot_get_task(task_id='{task_id}') to retrieve results."
            ),
        }

    return wrapper
