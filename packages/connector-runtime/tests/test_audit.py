"""Tests for the NDJSON audit log."""

from __future__ import annotations

from pathlib import Path

from elliot_connector_runtime.audit import AuditLog


def test_record_and_tail(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.ndjson")
    log.record("list_users", {"limit": 10}, 5, 12.3)
    log.record("get_user", {"id": 1}, 1, 4.0, error="boom")
    rows = log.tail(10)
    assert len(rows) == 2
    assert rows[0]["tool_id"] == "list_users"
    assert rows[1]["error"] == "boom"


def test_record_redacts_secrets(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.ndjson")
    log.record("call", {"api_key": "sk-secret"}, 0, 1.0)
    assert log.tail(1)[0]["arguments"]["api_key"] == "***"


def test_tail_empty_when_no_file(tmp_path: Path) -> None:
    assert AuditLog(tmp_path / "missing.ndjson").tail() == []


def test_log_rotates_at_size_cap(tmp_path: Path) -> None:
    """Once the file exceeds the cap it rotates so it cannot grow unbounded."""
    path = tmp_path / "audit.ndjson"
    log = AuditLog(path)
    for i in range(3000):
        log.record(f"tool_{i}", {"i": i}, i, 1.0)
    # The rotated generation exists and the live file stays within the cap.
    assert path.with_name("audit.ndjson.1").exists()
    assert path.stat().st_size <= log._max_bytes
    # tail still returns the most recent records after rotation.
    rows = log.tail(5)
    assert len(rows) == 5
    assert rows[-1]["tool_id"] == "tool_2999"
