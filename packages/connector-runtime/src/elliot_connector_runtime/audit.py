"""Append-only NDJSON audit log for tool invocations."""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any


class AuditLog:
    """Append-only NDJSON audit log. Thread-safe."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def record(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        result_row_count: int,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "tool_id": tool_id,
            "arguments": arguments,
            "result_row_count": result_row_count,
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            entry["error"] = error
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-n:] if line.strip()]
