"""Tests for ObservationStore (SQLite in-process)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from elliot_connector_runtime.observation_store import ObservationStore, _ToolCall


@pytest.fixture()
def store(tmp_path: Path) -> ObservationStore:
    return ObservationStore(f"sqlite:///{tmp_path}/obs.db")


def test_write_and_read_tool_call(store: ObservationStore) -> None:
    store.write_tool_call(None, "list_animals", {}, 5, 87, 43.0)
    calls = store.recent_tool_calls(10)
    assert len(calls) == 1
    assert calls[0]["tool_id"] == "list_animals"
    assert calls[0]["result_row_count"] == 5
    assert calls[0]["result_token_estimate"] == 87


def test_session_lifecycle(store: ObservationStore) -> None:
    store.open_session("abc", agent_hint="test-agent")
    store.write_tool_call("abc", "get_pet", {"id": 1}, 1, 22, 12.0)
    store.close_session("abc")
    sessions = store.recent_sessions(5)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "abc"
    assert sessions[0]["total_tool_calls"] == 1
    assert sessions[0]["total_tokens_estimated"] == 22


def test_open_session_idempotent(store: ObservationStore) -> None:
    store.open_session("dup")
    store.open_session("dup")
    sessions = store.recent_sessions(10)
    assert len(sessions) == 1


def test_close_session_unknown_is_noop(store: ObservationStore) -> None:
    store.close_session("ghost")
    assert store.recent_sessions() == []


def test_token_efficiency_aggregation(store: ObservationStore) -> None:
    store.write_tool_call(None, "list_animals", {}, 10, 200, 50.0)
    store.write_tool_call(None, "list_animals", {}, 10, 400, 60.0)
    metrics = store.token_efficiency()
    row = next(m for m in metrics if m["tool_id"] == "list_animals")
    assert row["call_count"] == 2
    assert row["avg_tokens"] == pytest.approx(300.0, abs=1)


def test_filtered_tool_calls(store: ObservationStore) -> None:
    store.write_tool_call(None, "tool_a", {}, 1, 10, 5.0)
    store.write_tool_call(None, "tool_b", {}, 2, 20, 6.0)
    calls = store.recent_tool_calls(10, tool_id="tool_a")
    assert all(c["tool_id"] == "tool_a" for c in calls)
    assert len(calls) == 1


def test_prune_deletes_old_records(store: ObservationStore) -> None:
    with Session(store._engine) as db:
        db.add(_ToolCall(ts=1.0, tool_id="old", duration_ms=1.0))
        db.commit()
    deleted = store.prune()
    assert deleted >= 1
    assert store.recent_tool_calls(10) == []


def test_error_recorded_correctly(store: ObservationStore) -> None:
    store.write_tool_call(None, "bad_tool", {}, 0, 0, 5.0, error="SQL error")
    calls = store.recent_tool_calls(10)
    assert calls[0]["error"] == "SQL error"


def test_empty_token_efficiency(store: ObservationStore) -> None:
    assert store.token_efficiency() == []
