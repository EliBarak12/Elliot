"""Tests for load_connectors_dir (multi-connector runtime)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_connector_runtime import ConnectorLoadError, load_connectors_dir

CONNECTOR_A = {
    "name": "Pets",
    "slug": "pets",
    "version": "1.0.0",
    "sources": [],
    "tools": [],
    "skills": [],
}

CONNECTOR_B = {
    "name": "Users",
    "slug": "users",
    "version": "1.0.0",
    "sources": [],
    "tools": [],
    "skills": [],
}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_directory_returns_all(tmp_path: Path) -> None:
    write_json(tmp_path / "pets.connector.json", CONNECTOR_A)
    write_json(tmp_path / "users.connector.json", CONNECTOR_B)
    configs = load_connectors_dir(tmp_path)
    assert len(configs) == 2
    assert "pets" in configs
    assert "users" in configs


def test_load_directory_keyed_by_slug(tmp_path: Path) -> None:
    write_json(tmp_path / "pets.connector.json", CONNECTOR_A)
    configs = load_connectors_dir(tmp_path)
    assert configs["pets"].name == "Pets"


def test_skips_invalid_connector(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_json(tmp_path / "pets.connector.json", CONNECTOR_A)
    (tmp_path / "bad.connector.json").write_text("{not valid json}")
    configs = load_connectors_dir(tmp_path)
    assert "bad" not in configs
    assert "pets" in configs


def test_raises_when_directory_empty(tmp_path: Path) -> None:
    with pytest.raises(ConnectorLoadError, match="No valid connectors"):
        load_connectors_dir(tmp_path)


def test_raises_when_all_invalid(tmp_path: Path) -> None:
    (tmp_path / "bad.connector.json").write_text("{invalid}")
    with pytest.raises(ConnectorLoadError, match="No valid connectors"):
        load_connectors_dir(tmp_path)
