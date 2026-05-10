"""Thread-safe in-process cache for ConnectorConfig objects with TTL and mtime invalidation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from elliot_core.types.connector import ConnectorConfig

from .loader import load_connector


@dataclass
class _CacheEntry:
    config: ConnectorConfig
    loaded_at: float
    mtime: float


class ConnectorCache:
    """
    Thread-safe in-process cache for ConnectorConfig objects.

    Re-reads a file when its mtime changes OR when the TTL expires,
    whichever comes first.
    """

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[Path, _CacheEntry] = {}
        self._lock = Lock()

    def get(self, path: str | Path) -> ConnectorConfig:
        p = Path(path).resolve()
        now = time.monotonic()
        current_mtime = p.stat().st_mtime if p.exists() else 0.0

        with self._lock:
            entry = self._entries.get(p)
            if entry is not None:
                age = now - entry.loaded_at
                if age < self._ttl and entry.mtime == current_mtime:
                    return entry.config

            config = load_connector(p)
            self._entries[p] = _CacheEntry(
                config=config,
                loaded_at=now,
                mtime=current_mtime,
            )
            return config

    def invalidate(self, path: str | Path) -> None:
        p = Path(path).resolve()
        with self._lock:
            self._entries.pop(p, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
