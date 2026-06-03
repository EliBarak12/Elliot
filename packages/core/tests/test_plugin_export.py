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

_CONNECTOR_WITH_SKILL = {
    "name": "Acme API",
    "slug": "acme-api",
    "version": "2.1.0",
    "description": "Read-only access to Acme widgets.",
    "tools": [
        {
            "id": "list_widgets",
            "name": "List Widgets",
            "description": "Return every widget in the catalog",
            "category": "READ",
            "source_ids": [],
            "sql": "SELECT id, name FROM widgets LIMIT 50",
            "parameters": [],
        }
    ],
    "skills": [
        {
            "id": "daily-report",
            "name": "Daily Report",
            "description": "Generate the daily widget report",
            "steps": [{"alias": "widgets", "tool_id": "list_widgets", "params": {}}],
            "input_parameters": [],
        }
    ],
}


_CONNECTOR_WITH_PROSE_SKILL = {
    "name": "Acme API",
    "slug": "acme-api",
    "version": "2.1.0",
    "description": "Read-only access to Acme widgets.",
    "tools": [
        {
            "id": "list_widgets",
            "name": "List Widgets",
            "description": "Return every widget in the catalog",
            "category": "READ",
            "sql": "SELECT id, name FROM widgets LIMIT 50",
        }
    ],
    "skills": [
        {
            "id": "triage-defects",
            "name": "Triage Defects",
            "description": "Decide which widgets to recall",
            "when_to_use": "When the user reports a defective batch.",
            "instructions": (
                "## How to triage\n\n"
                "First list the widgets, then branch: recall any flagged unsafe, "
                "otherwise note them for review."
            ),
        }
    ],
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
        "skills/acme-api-guide/SKILL.md",
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
    # Codex discovers bundled skills via the manifest `skills` path.
    assert data["skills"] == "./skills/"


def test_usage_skill_is_generated_with_tool_prefix(tmp_path: Path):
    """Every export ships a usage skill that references mcp__<slug>__* tools."""
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)
    skill = (out / "skills" / "acme-api-guide" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    assert "allowed-tools: mcp__acme-api__*" in skill
    assert "mcp__acme-api__<tool-id>" in skill


def test_workflow_skill_generated_from_connector_skill(tmp_path: Path):
    """A connector `skills` workflow becomes its own SKILL.md in the plugin."""
    connector = _write_connector(tmp_path, _CONNECTOR_WITH_SKILL)
    out = tmp_path / "out"
    export_plugin(connector, out)
    skill = (out / "skills" / "daily-report" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: daily-report" in skill
    assert "## Steps" in skill
    # The step must point at the connector tool under the slug-named server.
    assert "mcp__acme-api__list_widgets" in skill
    # The usage skill must list the connector's tool too.
    guide = (out / "skills" / "acme-api-guide" / "SKILL.md").read_text(encoding="utf-8")
    assert "mcp__acme-api__list_widgets" in guide


def test_prose_skill_renders_author_instructions_and_when_to_use(tmp_path: Path):
    """A prose skill exports its author instructions + when_to_use verbatim."""
    connector = _write_connector(tmp_path, _CONNECTOR_WITH_PROSE_SKILL)
    out = tmp_path / "out"
    export_plugin(connector, out)
    skill = (out / "skills" / "triage-defects" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: triage-defects" in skill
    # Author's when_to_use wins over the generated default.
    assert "when_to_use: When the user reports a defective batch." in skill
    # The author's markdown body is present verbatim.
    assert "## How to triage" in skill
    assert "branch: recall any flagged unsafe" in skill
    # Pure-prose skill has no generated step list.
    assert "## Steps" not in skill


def test_skill_with_prose_and_steps_renders_both(tmp_path: Path):
    data = {
        **_CONNECTOR_WITH_PROSE_SKILL,
        "skills": [
            {
                **_CONNECTOR_WITH_PROSE_SKILL["skills"][0],
                "steps": [{"alias": "w", "tool_id": "list_widgets", "params": {}}],
            }
        ],
    }
    connector = _write_connector(tmp_path, data)
    out = tmp_path / "out"
    export_plugin(connector, out)
    skill = (out / "skills" / "triage-defects" / "SKILL.md").read_text(encoding="utf-8")
    assert "## How to triage" in skill
    # When prose is present, the chain is framed as a reference, not "## Steps".
    assert "## Tool sequence" in skill
    assert "mcp__acme-api__list_widgets" in skill


def test_exported_plugin_links_to_elliot_cloud(tmp_path: Path):
    """Manifests, marketplaces, and README all point home at elliot-cloud.com."""
    connector = _write_connector(tmp_path)
    out = tmp_path / "out"
    export_plugin(connector, out)

    claude = json.loads((out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert claude["author"]["url"] == "https://elliot-cloud.com"
    assert claude["homepage"] == "https://elliot-cloud.com"

    codex = json.loads((out / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert codex["author"]["url"] == "https://elliot-cloud.com"
    assert codex["homepage"] == "https://elliot-cloud.com"

    claude_mkt = json.loads(
        (out / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert claude_mkt["owner"]["url"] == "https://elliot-cloud.com"

    codex_mkt = json.loads(
        (out / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert codex_mkt["owner"]["url"] == "https://elliot-cloud.com"

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "https://elliot-cloud.com" in readme


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
