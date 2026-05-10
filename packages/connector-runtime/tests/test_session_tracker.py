"""Tests for SessionTracker."""

from __future__ import annotations

from pathlib import Path

from elliot_connector_runtime.session_tracker import SessionTracker, _estimate_tokens


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
