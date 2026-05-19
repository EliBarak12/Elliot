"""Tests for elliot_core.plugin_export: connector -> installable plugin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_core.errors import ElliotError
from elliot_core.plugin_export import export_plugin

_CONNECTOR = {
    "name": "Acme API",
    "slug": "acme-api",
    "version": "2.1.0",
    "description": "Read-only access to Acme widgets.",
}


def _write_connector(tmp_path: Path, data: dict | None = None) -> Path:
    path = tmp_path / "acme.connector.json"
    path.write_text(json.dumps(data or _CONNECTOR), encoding="utf-8")
    return path


def test_export_writes_all_plugin_files(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    written = export_plugin(connector, out)

    rel = {p.relative_to(out).as_posix() for p in written}
    assert rel == {
        "acme-api.connector.json",
        ".mcp.json",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".codex-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
        "README.md",
    }
    for path in written:
        assert path.exists()


def test_connector_file_is_copied_verbatim(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    copied = (out / "acme-api.connector.json").read_text(encoding="utf-8")
    assert json.loads(copied) == _CONNECTOR


def test_mcp_json_runs_connector_over_stdio(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    data = json.loads((out / ".mcp.json").read_text(encoding="utf-8"))
    server = data["mcpServers"]["acme-api"]
    assert server["command"] == "elliot-mcp"
    assert server["args"] == [
        "--connector",
        "${CLAUDE_PLUGIN_ROOT}/acme-api.connector.json",
    ]


def test_claude_plugin_manifest_is_valid(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    data = json.loads((out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["name"] == "acme-api"
    assert data["version"] == "2.1.0"
    assert data["mcpServers"] == "./.mcp.json"


def test_claude_marketplace_source_is_relative(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    data = json.loads((out / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    entry = data["plugins"][0]
    assert entry["name"] == "acme-api"
    assert entry["source"] == "./"
    assert data["owner"]["name"]


def test_codex_plugin_manifest_has_inline_mcp_and_interface(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    data = json.loads((out / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["name"] == "acme-api"
    server = data["mcpServers"]["acme-api"]
    assert server["command"] == "elliot-mcp"
    assert data["interface"]["displayName"] == "Acme API"
    assert data["interface"]["category"] == "Productivity"


def test_codex_marketplace_uses_local_source(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    data = json.loads(
        (out / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    entry = data["plugins"][0]
    assert entry["source"] == {"source": "local", "path": "./"}
    assert entry["policy"]["installation"] == "AVAILABLE"
    assert entry["category"] == "Productivity"


def test_readme_mentions_both_hosts(tmp_path: Path):
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Claude Code" in readme
    assert "Codex" in readme
    assert "elliot-mcp-plugin" in readme


def test_missing_connector_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        export_plugin(tmp_path / "nope.connector.json", tmp_path / "out")


def test_invalid_connector_raises_elliot_error(tmp_path: Path):
    bad = tmp_path / "bad.connector.json"
    bad.write_text('{"name": "missing slug and version"}', encoding="utf-8")
    with pytest.raises(ElliotError):
        export_plugin(bad, tmp_path / "out")
