"""Tests for the harness trace-hook installer."""

from __future__ import annotations

import json
from pathlib import Path

from elliot_core.trace.installer import default_settings_path, install, uninstall


def test_default_settings_paths() -> None:
    assert default_settings_path("claude-code").name == "settings.json"
    assert default_settings_path("codex").name == "config.toml"
    assert default_settings_path("cursor").name == "hooks.json"


def test_install_claude_code_writes_hooks(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    install("claude-code", settings_path=settings, python="python3")

    data = json.loads(settings.read_text())
    hooks = data["hooks"]
    assert set(hooks) == {"PostToolUse", "UserPromptSubmit", "Stop"}
    # PostToolUse is scoped to MCP tools.
    assert hooks["PostToolUse"][0]["matcher"] == "mcp__.*"
    cmd = hooks["PostToolUse"][0]["hooks"][0]["command"]
    assert "elliot_core.trace.hook_adapter" in cmd
    assert "--harness claude-code" in cmd


def test_install_claude_code_is_idempotent(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    install("claude-code", settings_path=settings, python="python3")
    install("claude-code", settings_path=settings, python="python3")

    hooks = json.loads(settings.read_text())["hooks"]
    # Exactly one Elliot entry per event, not two.
    assert len(hooks["PostToolUse"]) == 1


def test_install_preserves_existing_hooks(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "my-own"}]}]}}
        )
    )
    install("claude-code", settings_path=settings, python="python3")

    commands = [
        h["command"]
        for entry in json.loads(settings.read_text())["hooks"]["PostToolUse"]
        for h in entry["hooks"]
    ]
    assert "my-own" in commands
    assert any("elliot_core.trace.hook_adapter" in c for c in commands)


def test_uninstall_claude_code_removes_only_elliot(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "my-own"}]}]}}
        )
    )
    install("claude-code", settings_path=settings, python="python3")
    uninstall("claude-code", settings_path=settings)

    commands = [
        h["command"]
        for entry in json.loads(settings.read_text())["hooks"].get("PostToolUse", [])
        for h in entry["hooks"]
    ]
    assert commands == ["my-own"]


def test_install_cursor_writes_hooks(tmp_path: Path) -> None:
    settings = tmp_path / "hooks.json"
    install("cursor", settings_path=settings, python="python3")

    data = json.loads(settings.read_text())
    assert data["version"] == 1
    assert set(data["hooks"]) == {"afterMCPExecution", "beforeSubmitPrompt"}
    assert "--harness cursor" in data["hooks"]["afterMCPExecution"][0]["command"]


def test_install_codex_appends_toml_block(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5"\n')
    install("codex", settings_path=config, python="python3")

    text = config.read_text()
    assert 'model = "gpt-5"' in text  # existing config preserved
    assert "[[hooks.PostToolUse]]" in text
    assert 'matcher = "mcp__.*"' in text
    assert "--harness codex" in text


def test_install_codex_is_idempotent(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    install("codex", settings_path=config, python="python3")
    install("codex", settings_path=config, python="python3")
    assert config.read_text().count("[[hooks.PostToolUse]]") == 1


def test_uninstall_codex_strips_block(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5"\n')
    install("codex", settings_path=config, python="python3")
    uninstall("codex", settings_path=config)

    text = config.read_text()
    assert "[[hooks.PostToolUse]]" not in text
    assert 'model = "gpt-5"' in text
