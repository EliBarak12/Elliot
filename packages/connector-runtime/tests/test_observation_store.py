"""Tests for ObservationStore (SQLite in-process)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from elliot_connector_runtime.observation_store import (
    ObservationStore,
    _AgentFeedback,
    _ToolCall,
)


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


def test_session_rollups_stay_current_without_close(store: ObservationStore) -> None:
    """Regression: MCP-over-HTTP clients rarely close cleanly, so the per-agent
    breakdown must be correct from the denormalized session counters as calls
    land — not only after close_session. Each call must bump the live totals."""
    store.open_session("s1", agent_identity={"client": "cursor"})
    store.write_tool_call("s1", "list", {}, 3, 50, 10.0)
    store.write_tool_call("s1", "list", {}, 1, 20, 12.0)
    store.write_tool_call("s1", "list", {}, 0, 0, 5.0, error="boom")

    sess = next(s for s in store.recent_sessions(10) if s["session_id"] == "s1")
    assert sess["total_tool_calls"] == 2  # successes only
    assert sess["error_count"] == 1
    assert sess["total_tokens_estimated"] == 70
    assert sess["total_duration_ms"] == 27.0

    # close_session recomputes from the tool_calls table — must match, not double.
    store.close_session("s1")
    sess = next(s for s in store.recent_sessions(10) if s["session_id"] == "s1")
    assert sess["total_tool_calls"] == 2
    assert sess["error_count"] == 1


def test_session_persists_model_protocol_and_capabilities(store: ObservationStore) -> None:
    """The spec-backed handshake fields (protocol/capabilities) and the
    client-volunteered model must round-trip onto the session row."""
    store.open_session(
        "s1",
        agent_identity={
            "client": "claude-code",
            "model": "claude-opus-4-8",
            "protocol_version": "2025-06-18",
            "capabilities": ["roots", "sampling"],
        },
    )
    sess = next(s for s in store.recent_sessions(10) if s["session_id"] == "s1")
    assert sess["agent_model"] == "claude-opus-4-8"
    assert sess["agent_protocol_version"] == "2025-06-18"
    assert sess["agent_capabilities"] == "roots,sampling"


def test_handshake_upsert_unions_capabilities(store: ObservationStore) -> None:
    """The initialize-handshake facts upsert per client and capabilities union
    so a later call advertising fewer never drops one."""
    store.record_handshake("Claude-Code", "2025-06-18", ("roots", "sampling"))
    store.record_handshake("claude-code", "2025-06-18", ("elicitation",))
    hs = store.client_handshakes()
    assert "claude-code" in hs  # keyed lowercase, both calls merged
    assert hs["claude-code"]["protocol_version"] == "2025-06-18"
    assert set(hs["claude-code"]["capabilities"]) == {"roots", "sampling", "elicitation"}


def test_write_tool_call_redacts_secret_arguments(store: ObservationStore) -> None:
    """Secret-bearing argument fields must be masked before they hit the DB.

    The observation store must apply the same redaction policy as the audit
    log / session tracker so the DB never persists raw API keys or tokens.
    """
    import json

    store.write_tool_call(
        None,
        "call_api",
        {"api_key": "super-secret-value", "limit": 10},
        1,
        20,
        5.0,
    )
    calls = store.recent_tool_calls(10)
    assert len(calls) == 1
    persisted = json.loads(calls[0]["arguments"])
    assert persisted["api_key"] == "***"
    assert persisted["limit"] == 10
    assert "super-secret-value" not in calls[0]["arguments"]


def test_harness_breakdown_groups_by_agent_client(store: ObservationStore) -> None:
    store.open_session("s1", agent_identity={"client": "claude-code"})
    store.write_tool_call("s1", "list", {}, 1, 50, 10.0)
    store.write_tool_call("s1", "list", {}, 0, 0, 10.0, error="boom")
    store.open_session("s2", agent_identity={"client": "cursor"})
    store.write_tool_call("s2", "list", {}, 1, 30, 10.0)

    breakdown = {row["harness"]: row for row in store.harness_breakdown()}
    assert breakdown["claude-code"]["tool_calls"] == 2
    assert breakdown["claude-code"]["errors"] == 1
    assert breakdown["claude-code"]["tokens"] == 50
    assert breakdown["claude-code"]["sessions"] == 1
    assert breakdown["cursor"]["tool_calls"] == 1
    assert breakdown["cursor"]["errors"] == 0


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


def test_write_and_read_feedback(store: ObservationStore) -> None:
    store.write_feedback(
        tool_id="list_animals",
        outcome="success",
        session_id="s1",
        connector_slug="pets",
        why_chosen="I needed the full animal list to answer the question",
        input_summary="species=dog",
        output_summary="3 rows returned",
        detail="worked first try",
        agent_identity={"client": "claude-code", "model": "claude-opus-4-7"},
    )
    feedback = store.recent_feedback(10)
    assert len(feedback) == 1
    row = feedback[0]
    assert row["tool_id"] == "list_animals"
    assert row["outcome"] == "success"
    assert row["why_chosen"].startswith("I needed")
    assert row["input_summary"] == "species=dog"
    assert row["output_summary"] == "3 rows returned"
    assert row["agent_client"] == "claude-code"
    assert row["agent_model"] == "claude-opus-4-7"


def test_recent_feedback_filters_by_connector(store: ObservationStore) -> None:
    store.write_feedback(tool_id="t", outcome="success", connector_slug="alpha")
    store.write_feedback(tool_id="t", outcome="failure", connector_slug="beta")
    only_beta = store.recent_feedback(10, connector_slug="beta")
    assert len(only_beta) == 1
    assert only_beta[0]["outcome"] == "failure"
    assert len(store.recent_feedback(10)) == 2


def test_prune_deletes_old_feedback(store: ObservationStore) -> None:
    with Session(store._engine) as db:
        db.add(_AgentFeedback(ts=1.0, tool_id="old", outcome="success"))
        db.commit()
    deleted = store.prune()
    assert deleted >= 1
    assert store.recent_feedback(10) == []


def test_sqlite_uses_wal_mode(store: ObservationStore) -> None:
    """A file-backed SQLite store runs in WAL mode for concurrent access."""
    from sqlalchemy import text as sa_text

    with Session(store._engine) as db:
        mode = db.execute(sa_text("PRAGMA journal_mode")).scalar()
    assert str(mode).lower() == "wal"
