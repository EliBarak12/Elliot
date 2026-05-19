"""Append-only NDJSON audit log for tool invocations."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

from elliot_core.redaction import redact_audit_arguments

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024


def _max_bytes() -> int:
    raw = os.environ.get("ELLIOT_AUDIT_LOG_MAX_BYTES", "")
    try:
        return max(64 * 1024, int(raw)) if raw else _DEFAULT_MAX_BYTES
    except ValueError:
        return _DEFAULT_MAX_BYTES


class AuditLog:
    """Append-only NDJSON audit log. Thread-safe.

    The file is size-rotated: once it exceeds the configured cap it is moved
    aside to ``<name>.1`` (one generation kept) and a fresh file is started,
    so the log cannot grow without bound.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._rotated = self._path.with_name(self._path.name + ".1")
        self._lock = Lock()
        self._max_bytes = _max_bytes()

    def record(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        result_row_count: int,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        # CLAUDE.md "Never log: secret values, API keys, raw query results".
        # `arguments` may contain agent-supplied auth tokens or API keys; the
        # redactor masks any value whose key name matches a sensitive pattern.
        entry: dict[str, Any] = {
            "ts": time.time(),
            "tool_id": tool_id,
            "arguments": redact_audit_arguments(arguments),
            "result_row_count": result_row_count,
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            entry["error"] = error
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            self._maybe_rotate()

    def _maybe_rotate(self) -> None:
        """Rotate the log aside once it exceeds the size cap (caller holds lock)."""
        try:
            if self._path.stat().st_size <= self._max_bytes:
                return
        except OSError:
            return
        # os.replace is atomic and overwrites any existing previous generation.
        os.replace(self._path, self._rotated)

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            lines: list[str] = []
            if self._path.exists():
                lines = self._path.read_text(encoding="utf-8").splitlines()
            if len(lines) < n and self._rotated.exists():
                prev = self._rotated.read_text(encoding="utf-8").splitlines()
                lines = prev + lines
        return [json.loads(line) for line in lines[-n:] if line.strip()]
