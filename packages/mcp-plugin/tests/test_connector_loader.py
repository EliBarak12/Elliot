import json
import os

import pytest

from elliot_core.errors import ElliotError
from elliot_mcp_plugin.connector_loader import load_connector, load_secrets

_CONNECTOR = {
    "name": "Test",
    "slug": "test",
    "version": "0.1.0",
    "description": "Test connector",
    "sources": [{"id": "s1", "name": "Source 1", "type": "file", "path": "/tmp/data.csv"}],
    "tools": [],
}


def test_load_from_file(tmp_path):
    p = tmp_path / "connector.json"
    p.write_text(json.dumps(_CONNECTOR))
    config = load_connector(str(p))
    assert config.slug == "test"


def test_load_from_env_path(tmp_path, monkeypatch):
    p = tmp_path / "connector.json"
    p.write_text(json.dumps(_CONNECTOR))
    monkeypatch.setenv("ELLIOT_CONNECTOR_PATH", str(p))
    config = load_connector()
    assert config.name == "Test"


def test_load_from_env_json(monkeypatch):
    monkeypatch.setenv("ELLIOT_CONNECTOR_JSON", json.dumps(_CONNECTOR))
    config = load_connector()
    assert config.description == "Test connector"


def test_env_path_takes_priority_over_env_json(tmp_path, monkeypatch):
    p = tmp_path / "connector.json"
    other = dict(_CONNECTOR, slug="from-file")
    p.write_text(json.dumps(other))
    monkeypatch.setenv("ELLIOT_CONNECTOR_PATH", str(p))
    monkeypatch.setenv("ELLIOT_CONNECTOR_JSON", json.dumps(_CONNECTOR))
    config = load_connector()
    assert config.slug == "from-file"


def test_missing_raises(monkeypatch):
    monkeypatch.delenv("ELLIOT_CONNECTOR_PATH", raising=False)
    monkeypatch.delenv("ELLIOT_CONNECTOR_JSON", raising=False)
    with pytest.raises(ElliotError) as exc_info:
        load_connector()
    assert exc_info.value.code == "CONNECTOR_NOT_FOUND"


def test_explicit_path_not_found_raises():
    with pytest.raises(ElliotError) as exc_info:
        load_connector("/nonexistent/path.json")
    assert exc_info.value.code == "CONNECTOR_NOT_FOUND"


def test_load_secrets(monkeypatch):
    monkeypatch.setenv("ELLIOT_SECRET_API_KEY", "abc123")
    monkeypatch.setenv("ELLIOT_SECRET_DB_PASS", "secret")
    secrets = load_secrets()
    assert secrets["api_key"] == "abc123"
    assert secrets["db_pass"] == "secret"


def test_load_secrets_empty(monkeypatch):
    for k in [k for k in os.environ if k.startswith("ELLIOT_SECRET_")]:
        monkeypatch.delenv(k, raising=False)
    assert load_secrets() == {}


def test_load_connector_invalid_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON {{{")
    with pytest.raises(ElliotError) as exc_info:
        load_connector(str(bad))
    assert exc_info.value.code == "INVALID_CONNECTOR"


def test_from_file_os_error_raises_invalid_connector(tmp_path):
    # tmp_path is a directory — exists() returns True but read_text() raises IsADirectoryError
    with pytest.raises(ElliotError) as exc_info:
        load_connector(str(tmp_path))
    assert exc_info.value.code == "INVALID_CONNECTOR"
