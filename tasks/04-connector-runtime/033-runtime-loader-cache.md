# Task 033 — Runtime: Connector Loader & Cache

## Goal
Implement `loader.py` and `cache.py` inside `packages/connector-runtime/src/elliot_connector_runtime/` to load `.connector.json` files from disk and cache them with a TTL.

## Package location
`packages/connector-runtime/` — `elliot-connector-runtime` Python package.

## Files to create

### `src/elliot_connector_runtime/loader.py`

```python
from __future__ import annotations

import json
from pathlib import Path

from elliot_core.types import ConnectorConfig


class ConnectorLoadError(Exception):
    pass


def load_connector(path: str | Path) -> ConnectorConfig:
    p = Path(path)
    if not p.exists():
        raise ConnectorLoadError(f"Connector file not found: {p}")
    if p.suffix != ".json":
        raise ConnectorLoadError(f"Expected .json file, got: {p.suffix}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectorLoadError(f"Invalid JSON in {p}: {exc}") from exc
    try:
        return ConnectorConfig.model_validate(data)
    except Exception as exc:
        raise ConnectorLoadError(f"Schema validation failed for {p}: {exc}") from exc


def discover_connectors(directory: str | Path) -> list[Path]:
    """Return sorted list of *.connector.json paths under directory."""
    d = Path(directory)
    if not d.is_dir():
        return []
    return sorted(d.rglob("*.connector.json"))
```

### `src/elliot_connector_runtime/cache.py`

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from elliot_core.types import ConnectorConfig

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
```

### `src/elliot_connector_runtime/__init__.py`

```python
from .cache import ConnectorCache
from .loader import ConnectorLoadError, discover_connectors, load_connector

__all__ = [
    "ConnectorCache",
    "ConnectorLoadError",
    "discover_connectors",
    "load_connector",
]
```

## Tests (`packages/connector-runtime/tests/test_loader_cache.py`)

```python
import json
import time
from pathlib import Path

import pytest

from elliot_connector_runtime import (
    ConnectorCache,
    ConnectorLoadError,
    discover_connectors,
    load_connector,
)

MINIMAL = {
    "name": "Test",
    "slug": "test",
    "version": "1.0.0",
    "sources": [],
    "tools": [],
    "skills": [],
}


def write_connector(tmp_path: Path, name: str = "test.connector.json", data: dict = MINIMAL) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def test_load_connector_ok(tmp_path):
    p = write_connector(tmp_path)
    cfg = load_connector(p)
    assert cfg.slug == "test"


def test_load_connector_missing(tmp_path):
    with pytest.raises(ConnectorLoadError, match="not found"):
        load_connector(tmp_path / "missing.json")


def test_load_connector_bad_json(tmp_path):
    p = tmp_path / "bad.connector.json"
    p.write_text("{not json}")
    with pytest.raises(ConnectorLoadError, match="Invalid JSON"):
        load_connector(p)


def test_load_connector_wrong_suffix(tmp_path):
    p = tmp_path / "test.yaml"
    p.write_text("{}")
    with pytest.raises(ConnectorLoadError, match="Expected .json"):
        load_connector(p)


def test_discover_connectors(tmp_path):
    write_connector(tmp_path, "a.connector.json")
    write_connector(tmp_path, "b.connector.json")
    (tmp_path / "not-a-connector.json").write_text("{}")
    found = discover_connectors(tmp_path)
    assert len(found) == 2
    assert all(p.name.endswith(".connector.json") for p in found)


def test_cache_returns_same_object(tmp_path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=60)
    first = cache.get(p)
    second = cache.get(p)
    assert first is second


def test_cache_invalidate(tmp_path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=60)
    first = cache.get(p)
    cache.invalidate(p)
    second = cache.get(p)
    assert first is not second


def test_cache_reloads_on_mtime_change(tmp_path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=9999)
    first = cache.get(p)
    updated = {**MINIMAL, "version": "2.0.0"}
    p.write_text(json.dumps(updated))
    import os
    os.utime(p, (time.time() + 1, time.time() + 1))
    second = cache.get(p)
    assert second is not first
    assert second.version == "2.0.0"
```

## Notes
- `discover_connectors` uses `rglob` so nested project directories work.
- `ConnectorCache` is NOT async — it uses a threading `Lock`. The runtime FastAPI app runs in a single process with uvicorn, so this is sufficient.
- TTL default is 60 s; tests that need instant expiry pass `ttl_seconds=0`.
