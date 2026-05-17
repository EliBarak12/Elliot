"""Tests for SessionTracker."""

from __future__ import annotations

from pathlib import Path

from elliot_connector_runtime.session_tracker import (
    SessionEvent,
    SessionTracker,
    _estimate_tokens,
)


def test_session_full_lifecycle(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session(agent_hint="test-agent")

    tracker.record_tools_list(sid, tool_count=3, duration_ms=10.0)
    tracker.record_tool_call(sid, "list_animals", {}, 2, [{"id": 1}, {"id": 2}], 43.0)

    session = tracker.close_session(sid)
    assert session is not None
    assert session.total_tool_calls == 1
    assert session.error_count == 0
    assert session.total_tokens_estimated > 0
    assert session.total_duration_ms > 0


def test_session_persisted_to_file(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session()
    tracker.record_tool_call(sid, "ping", {}, 1, [{"ok": 1}], 5.0)
    tracker.close_session(sid)

    sessions = tracker.tail(10)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == sid
    assert sessions[0]["total_tool_calls"] == 1


def test_agent_identity_persisted_with_session(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    identity = {
        "client": "claude-code",
        "client_version": "1.42.0",
        "model": "claude-opus-4-7",
        "modality": None,
        "user_agent": "agent-claude-code/1.42.0 claude-opus-4-7",
    }
    sid = tracker.start_session(agent_hint="claude-code claude-opus-4-7", agent_identity=identity)
    tracker.record_tool_call(sid, "ping", {}, 1, [{"ok": 1}], 5.0)
    tracker.close_session(sid)

    sessions = tracker.tail(10)
    assert sessions[0]["agent_identity"]["client"] == "claude-code"
    assert sessions[0]["agent_identity"]["model"] == "claude-opus-4-7"
    assert sessions[0]["agent_hint"] == "claude-code claude-opus-4-7"


def test_tail_empty_when_no_file(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    assert tracker.tail() == []


def test_tail_respects_n(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    for _ in range(5):
        sid = tracker.start_session()
        tracker.close_session(sid)

    assert len(tracker.tail(3)) == 3
    assert len(tracker.tail(10)) == 5


def test_record_unknown_session_is_noop(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    tracker.record_tool_call("nonexistent", "t", {}, 0, [], 0.0)
    assert tracker.tail() == []


def test_close_unknown_session_returns_none(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    assert tracker.close_session("ghost") is None


def test_error_recorded_in_session(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session()
    tracker.record_tool_call(sid, "bad_tool", {}, 0, [], 5.0, error="SQL error")
    session = tracker.close_session(sid)
    assert session is not None
    assert session.error_count == 1


def test_estimate_tokens_returns_positive() -> None:
    assert _estimate_tokens([{"id": 1, "name": "Widget"}]) > 0


def test_estimate_tokens_fallback() -> None:
    assert _estimate_tokens(object()) >= 1


def test_session_accumulates_multiple_calls(tmp_path: Path) -> None:
    """A session stays open and groups every call from one connection."""
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session(session_id="conn-1")
    for i in range(3):
        tracker.record_tool_call(sid, f"tool_{i}", {}, 1, [{"id": i}], 5.0)

    sessions = tracker.tail(10)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "conn-1"
    assert sessions[0]["total_tool_calls"] == 3
    assert len(sessions[0]["events"]) == 3


def test_tail_merges_active_and_closed(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    closed = tracker.start_session(session_id="closed-1")
    tracker.record_tool_call(closed, "ping", {}, 1, [{"ok": 1}], 5.0)
    tracker.close_session(closed)

    active = tracker.start_session(session_id="active-1")
    tracker.record_tool_call(active, "ping", {}, 1, [{"ok": 1}], 5.0)

    ids = {s["session_id"] for s in tracker.tail(10)}
    assert ids == {"closed-1", "active-1"}


def test_sweep_idle_flushes_stale_sessions(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session(session_id="stale-1")
    tracker.record_tool_call(sid, "ping", {}, 1, [{"ok": 1}], 5.0)
    # Force the session to look idle.
    tracker._active[sid].last_activity = 0.0

    swept = tracker.sweep_idle(ttl_seconds=60.0)
    assert swept == ["stale-1"]
    assert sid not in tracker._active
    assert tracker.tail(10)[0]["session_id"] == "stale-1"


def test_flush_all_closes_open_sessions(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    tracker.start_session(session_id="a")
    tracker.start_session(session_id="b")
    tracker.flush_all()
    assert tracker._active == {}
    assert len(tracker.tail(10)) == 2


def test_signals_flag_errors_and_large_results(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session(session_id="s")
    big = [{"v": "x" * 4000}]
    tracker.record_tool_call(sid, "fetch", {}, 1, big, 5.0)
    tracker.record_tool_call(sid, "fetch", {}, 0, [], 5.0, error="SQL error")
    tracker.record_tool_call(sid, "fetch", {}, 0, [], 5.0, error="SQL error")

    signals = tracker.tail(1)[0]["signals"]
    kinds = {s["type"] for s in signals}
    assert "errors" in kinds
    assert "large_result" in kinds
    # error followed by the same tool == a retry
    assert "retry" in kinds


def test_summary_describes_tool_path(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session(session_id="s")
    tracker.record_tool_call(sid, "list_animals", {}, 1, [{"id": 1}], 5.0)
    tracker.record_tool_call(sid, "get_animal", {}, 1, [{"id": 1}], 5.0)

    summary = tracker.tail(1)[0]["summary"]
    assert summary == "list_animals → get_animal"


def test_append_ingested_creates_hook_session(tmp_path: Path) -> None:
    """Hook-ingested traces carry reasoning, prompt and final output."""
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    identity = {"client": "claude-code", "client_version": "1.x", "model": "claude-opus-4-7"}
    events = [
        SessionEvent(
            ts=1.0,
            type="tool_call",
            tool_id="list_animals",
            arguments={"species": "dog"},
            result_rows=2,
            duration_ms=12.0,
            reasoning="I should list the animals.",
        )
    ]
    session = tracker.append_ingested(
        "claude-code:abc",
        identity,
        events,
        user_prompt="show me the dogs",
        final_output="Here are the dogs.",
    )
    assert session.source == "hook"
    assert session.user_prompt == "show me the dogs"
    assert session.final_output == "Here are the dogs."

    out = tracker.tail(1)[0]
    assert out["agent_identity"]["client"] == "claude-code"
    assert out["events"][0]["reasoning"] == "I should list the animals."
    assert out["user_prompt"] == "show me the dogs"


def test_append_ingested_accumulates_across_calls(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    ev = lambda tid: SessionEvent(ts=1.0, type="tool_call", tool_id=tid)  # noqa: E731
    tracker.append_ingested("codex:run", {"client": "codex"}, [ev("a")])
    tracker.append_ingested("codex:run", {"client": "codex"}, [ev("b")])
    out = tracker.tail(1)[0]
    assert out["total_tool_calls"] == 2
    assert out["source"] == "hook"


def test_result_preview_recorded_for_tool_call(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    sid = tracker.start_session(session_id="s")
    tracker.record_tool_call(sid, "fetch", {}, 1, [{"name": "Rex"}], 5.0)
    preview = tracker.tail(1)[0]["events"][0]["result_preview"]
    assert preview is not None and "Rex" in preview


def test_subscribe_receives_published_updates(tmp_path: Path) -> None:
    tracker = SessionTracker(tmp_path / "sessions.ndjson")
    queue = tracker.subscribe()
    sid = tracker.start_session(session_id="s")
    tracker.record_tool_call(sid, "ping", {}, 1, [{"ok": 1}], 5.0)

    payload = queue.get_nowait()
    assert payload["session_id"] == "s"

    # Drain, then unsubscribe — no further frames should arrive.
    while not queue.empty():
        queue.get_nowait()
    tracker.unsubscribe(queue)
    tracker.record_tool_call(sid, "ping", {}, 1, [{"ok": 1}], 5.0)
    assert queue.empty()
