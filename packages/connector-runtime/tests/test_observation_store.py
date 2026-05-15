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


def test_open_session_persists_agent_identity(store: ObservationStore) -> None:
    store.open_session(
        "ident",
        agent_hint="claude-code claude-opus-4-7",
        agent_identity={
            "client": "claude-code",
            "client_version": "1.42.0",
            "model": "claude-opus-4-7",
            "modality": None,
            "user_agent": "agent-claude-code/1.42.0 claude-opus-4-7",
        },
    )
    sessions = store.recent_sessions(10)
    row = next(s for s in sessions if s["session_id"] == "ident")
    assert row["agent_client"] == "claude-code"
    assert row["agent_client_version"] == "1.42.0"
    assert row["agent_model"] == "claude-opus-4-7"
    assert row["user_agent"].startswith("agent-claude-code/")


def test_observation_store_migrates_old_schema(tmp_path: Path) -> None:
    """A pre-existing agent_sessions table without identity columns is upgraded in place."""
    from sqlalchemy import create_engine
    from sqlalchemy import text as sa_text

    db_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{db_path}")
    with legacy_engine.begin() as conn:
        conn.execute(
            sa_text(
                """
                CREATE TABLE agent_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id VARCHAR(32) UNIQUE NOT NULL,
                    started_at FLOAT NOT NULL,
                    ended_at FLOAT,
                    agent_hint VARCHAR(255),
                    connector_slug VARCHAR(128),
                    total_tool_calls INTEGER DEFAULT 0,
                    total_tokens_estimated INTEGER DEFAULT 0,
                    total_duration_ms FLOAT DEFAULT 0,
                    error_count INTEGER DEFAULT 0
                )
                """
            )
        )
    legacy_engine.dispose()

    store = ObservationStore(f"sqlite:///{db_path}")
    store.open_session(
        "post-migration",
        agent_identity={"client": "cursor", "model": "claude-sonnet-4-5"},
    )
    sessions = store.recent_sessions(10)
    assert sessions[0]["agent_client"] == "cursor"
    assert sessions[0]["agent_model"] == "claude-sonnet-4-5"


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
