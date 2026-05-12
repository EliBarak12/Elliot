"""Tests for ConnectorLoader and ConnectorCache."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from elliot_connector_runtime import (
    ConnectorCache,
    ConnectorLoadError,
    discover_connectors,
    load_connector,
)

MINIMAL: dict = {
    "name": "Test",
    "slug": "test",
    "version": "1.0.0",
    "sources": [],
    "tools": [],
    "skills": [],
}


def write_connector(
    tmp_path: Path, name: str = "test.connector.json", data: dict = MINIMAL
) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# load_connector
# ---------------------------------------------------------------------------


def test_load_connector_ok(tmp_path: Path):
    p = write_connector(tmp_path)
    cfg = load_connector(p)
    assert cfg.slug == "test"


def test_load_connector_missing(tmp_path: Path):
    with pytest.raises(ConnectorLoadError, match="not found"):
        load_connector(tmp_path / "missing.json")


def test_load_connector_bad_json(tmp_path: Path):
    p = tmp_path / "bad.connector.json"
    p.write_text("{not json}")
    with pytest.raises(ConnectorLoadError, match="Invalid JSON"):
        load_connector(p)


def test_load_connector_wrong_suffix(tmp_path: Path):
    p = tmp_path / "test.yaml"
    p.write_text("{}")
    with pytest.raises(ConnectorLoadError, match="Expected .json"):
        load_connector(p)


def test_load_connector_schema_error(tmp_path: Path):
    p = tmp_path / "bad_schema.json"
    p.write_text(json.dumps({"name": "Missing required fields"}))
    with pytest.raises(ConnectorLoadError, match="Schema validation"):
        load_connector(p)


# ---------------------------------------------------------------------------
# discover_connectors
# ---------------------------------------------------------------------------


def test_discover_connectors(tmp_path: Path):
    write_connector(tmp_path, "a.connector.json")
    write_connector(tmp_path, "b.connector.json")
    (tmp_path / "not-a-connector.json").write_text("{}")
    found = discover_connectors(tmp_path)
    assert len(found) == 2
    assert all(p.name.endswith(".connector.json") for p in found)


def test_discover_connectors_nested(tmp_path: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    write_connector(sub, "nested.connector.json")
    found = discover_connectors(tmp_path)
    assert len(found) == 1


def test_discover_connectors_nonexistent_dir(tmp_path: Path):
    found = discover_connectors(tmp_path / "ghost")
    assert found == []


def test_discover_connectors_sorted(tmp_path: Path):
    write_connector(tmp_path, "z.connector.json")
    write_connector(tmp_path, "a.connector.json")
    found = discover_connectors(tmp_path)
    assert found[0].name == "a.connector.json"


# ---------------------------------------------------------------------------
# ConnectorCache
# ---------------------------------------------------------------------------


def test_cache_returns_same_object(tmp_path: Path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=60)
    first = cache.get(p)
    second = cache.get(p)
    assert first is second


def test_cache_invalidate(tmp_path: Path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=60)
    first = cache.get(p)
    cache.invalidate(p)
    second = cache.get(p)
    assert first is not second


def test_cache_clear(tmp_path: Path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=60)
    cache.get(p)
    cache.clear()
    assert cache._entries == {}


def test_cache_reloads_on_mtime_change(tmp_path: Path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=9999)
    first = cache.get(p)
    updated = {**MINIMAL, "version": "2.0.0"}
    p.write_text(json.dumps(updated))
    os.utime(p, (time.time() + 1, time.time() + 1))
    second = cache.get(p)
    assert second is not first
    assert second.version == "2.0.0"


def test_cache_reloads_on_ttl_expiry(tmp_path: Path):
    p = write_connector(tmp_path)
    cache = ConnectorCache(ttl_seconds=0)
    first = cache.get(p)
    second = cache.get(p)
    assert first is not second


def test_cache_invalidate_nonexistent_path(tmp_path: Path):
    cache = ConnectorCache()
    cache.invalidate(tmp_path / "ghost.json")  # should not raise


def test_load_connector_invalid_json_raises(tmp_path: Path):
    bad = tmp_path / "bad.connector.json"
    bad.write_text("THIS IS NOT JSON {{{")
    with pytest.raises(ConnectorLoadError):
        load_connector(str(bad))


def test_load_connector_with_resolved_secret(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONNECTOR_DISPLAY_NAME", "Test Connector")
    data = {**MINIMAL, "name": "{{ env:CONNECTOR_DISPLAY_NAME }}"}
    p = write_connector(tmp_path, "secret.connector.json", data)
    cfg = load_connector(p)
    assert cfg.slug == "test"


def test_load_connector_missing_secret_raises(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MISSING_SECRET_VAR", raising=False)
    data = {**MINIMAL, "name": "{{ env:MISSING_SECRET_VAR }}"}
    p = write_connector(tmp_path, "missing_secret.connector.json", data)
    with pytest.raises(ConnectorLoadError, match="MISSING_SECRET_VAR"):
        load_connector(p)
