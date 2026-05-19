"""Tests for elliot_core.cli (lint and eval subcommands)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_core.types import ConnectorConfig

GOOD_CONNECTOR = {
    "name": "Test",
    "slug": "test",
    "version": "1.0.0",
    "sources": [],
    "tools": [
        {
            "id": "list_items",
            "name": "List Items",
            "description": "Return all items from the items table",
            "category": "READ",
            "source_ids": [],
            "sql": "SELECT id, name FROM items WHERE (:f IS NULL OR name = :f) LIMIT 50",
            "parameters": [
                {
                    "name": "filter_name",
                    "type": "string",
                    "required": False,
                    "description": "Filter by item name",
                }
            ],
        }
    ],
    "skills": [],
}

BAD_CONNECTOR = {
    "name": "Bad",
    "slug": "bad",
    "version": "1.0.0",
    "sources": [],
    "tools": [
        {
            "id": "x",
            "name": "X",
            "description": "Bad",  # too short
            "category": "READ",
            "source_ids": [],
            "sql": "SELECT * FROM items",  # unbounded
            "parameters": [],
        }
    ],
    "skills": [],
}


def _write_connector(tmp_path: Path, data: dict) -> Path:  # type: ignore[type-arg]
    p = tmp_path / "test.connector.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# _load_connector helper
# ---------------------------------------------------------------------------


def test_load_connector_valid(tmp_path: Path) -> None:
    from elliot_core.cli import _load_connector

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    config = _load_connector(str(p))
    assert isinstance(config, ConnectorConfig)
    assert config.slug == "test"


def test_load_connector_missing_file_exits(tmp_path: Path) -> None:
    from elliot_core.cli import _load_connector

    with pytest.raises(SystemExit):
        _load_connector(str(tmp_path / "nonexistent.json"))


# ---------------------------------------------------------------------------
# _cmd_lint via argparse simulation
# ---------------------------------------------------------------------------


def test_cmd_lint_clean_connector_exits_0(tmp_path: Path) -> None:
    import argparse

    from elliot_core.cli import _cmd_lint

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    args = argparse.Namespace(path=str(p))
    with pytest.raises(SystemExit) as exc_info:
        _cmd_lint(args)
    assert exc_info.value.code == 0


def test_cmd_lint_bad_connector_exits_1(tmp_path: Path) -> None:
    import argparse

    from elliot_core.cli import _cmd_lint

    p = _write_connector(tmp_path, BAD_CONNECTOR)
    args = argparse.Namespace(path=str(p))
    with pytest.raises(SystemExit) as exc_info:
        _cmd_lint(args)
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------


def test_main_no_command_exits_1(monkeypatch) -> None:
    import sys

    from elliot_core.cli import main

    monkeypatch.setattr(sys, "argv", ["elliot"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_lint_clean_exits_0(tmp_path: Path, monkeypatch) -> None:
    import sys

    from elliot_core.cli import main

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    monkeypatch.setattr(sys, "argv", ["elliot", "lint", str(p)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_main_lint_bad_exits_1(tmp_path: Path, monkeypatch) -> None:
    import sys

    from elliot_core.cli import main

    p = _write_connector(tmp_path, BAD_CONNECTOR)
    monkeypatch.setattr(sys, "argv", ["elliot", "lint", str(p)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# init subcommand
# ---------------------------------------------------------------------------


def test_cmd_init_list_templates(capsys: pytest.CaptureFixture[str]) -> None:
    import argparse

    from elliot_core.cli import _cmd_init

    args = argparse.Namespace(list=True, template=None, output=None)
    _cmd_init(args)
    out = capsys.readouterr().out
    assert "rest-api-key" in out
    assert "postgres-readonly" in out


def test_cmd_init_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from elliot_core.cli import _cmd_init

    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(list=False, template="rest-api-key", output=None)
    _cmd_init(args)
    assert (tmp_path / "rest-api-key.connector.json").exists()


def test_cmd_init_unknown_template_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from elliot_core.cli import _cmd_init

    args = argparse.Namespace(list=False, template="no-such-template", output=None)
    with pytest.raises(SystemExit):
        _cmd_init(args)


def test_cmd_init_custom_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from elliot_core.cli import _cmd_init

    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(list=False, template="paginated-rest", output="my.connector.json")
    _cmd_init(args)
    assert (tmp_path / "my.connector.json").exists()


# ---------------------------------------------------------------------------
# export-plugin subcommand
# ---------------------------------------------------------------------------


def test_cmd_export_plugin_creates_plugin_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from elliot_core.cli import _cmd_export_plugin

    monkeypatch.chdir(tmp_path)
    connector = _write_connector(tmp_path, GOOD_CONNECTOR)
    args = argparse.Namespace(path=str(connector), out=str(tmp_path / "p"), force=False)
    _cmd_export_plugin(args)
    assert (tmp_path / "p" / ".codex-plugin" / "plugin.json").exists()
    assert (tmp_path / "p" / ".claude-plugin" / "plugin.json").exists()
    assert (tmp_path / "p" / ".mcp.json").exists()


def test_cmd_export_plugin_missing_file_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from elliot_core.cli import _cmd_export_plugin

    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(path=str(tmp_path / "nope.connector.json"), out=None, force=False)
    with pytest.raises(SystemExit):
        _cmd_export_plugin(args)


def test_cmd_export_plugin_nonempty_dir_needs_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from elliot_core.cli import _cmd_export_plugin

    monkeypatch.chdir(tmp_path)
    connector = _write_connector(tmp_path, GOOD_CONNECTOR)
    out = tmp_path / "p"
    out.mkdir()
    (out / "existing.txt").write_text("keep me", encoding="utf-8")

    args = argparse.Namespace(path=str(connector), out=str(out), force=False)
    with pytest.raises(SystemExit):
        _cmd_export_plugin(args)

    args_forced = argparse.Namespace(path=str(connector), out=str(out), force=True)
    _cmd_export_plugin(args_forced)
    assert (out / ".mcp.json").exists()


# ---------------------------------------------------------------------------
# status subcommand
# ---------------------------------------------------------------------------


def test_cmd_status_all_down_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    import httpx

    from elliot_core.cli import _cmd_status

    def raise_connect_error(*a: object, **kw: object) -> None:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", raise_connect_error)

    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        _cmd_status(args)
    assert exc_info.value.code == 1


def test_cmd_status_all_up_exits_0(monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    import httpx

    from elliot_core.cli import _cmd_status

    fake_response = type(
        "R", (), {"status_code": 200, "json": lambda self: {"connector": "pets"}}
    )()

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: fake_response)
    # Patch DB check to succeed
    monkeypatch.setattr(
        "elliot_core.cli._cmd_status",
        _cmd_status,
    )

    args = argparse.Namespace()

    import sys

    original = sys.modules.get("elliot_connector_runtime.observation_store")

    class _FakeStore:
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        def recent_tool_calls(self, *a: object) -> list[object]:
            return []

    fake_mod = type(sys)("fake")
    fake_mod.ObservationStore = _FakeStore  # type: ignore[attr-defined]
    sys.modules["elliot_connector_runtime.observation_store"] = fake_mod  # type: ignore[assignment]
    try:
        # Should exit 0 — no services down
        try:
            _cmd_status(args)
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        if original is None:
            del sys.modules["elliot_connector_runtime.observation_store"]
        else:
            sys.modules["elliot_connector_runtime.observation_store"] = original


# ---------------------------------------------------------------------------
# connect subcommand — Codex registration
# ---------------------------------------------------------------------------


def test_write_codex_toml_creates_file(tmp_path: Path) -> None:
    from elliot_core.cli import _write_codex_toml

    config = tmp_path / ".codex" / "config.toml"
    changed = _write_codex_toml(config, "http://localhost:3000/mcp/")

    assert changed is True
    content = config.read_text(encoding="utf-8")
    assert "[mcp_servers.elliot]" in content
    assert 'url = "http://localhost:3000/mcp/"' in content


def test_write_codex_toml_idempotent(tmp_path: Path) -> None:
    from elliot_core.cli import _write_codex_toml

    config = tmp_path / ".codex" / "config.toml"
    _write_codex_toml(config, "http://localhost:3000/mcp/")
    changed = _write_codex_toml(config, "http://localhost:3000/mcp/")

    assert changed is False
    assert config.read_text(encoding="utf-8").count("[mcp_servers.elliot]") == 1


def test_write_codex_toml_updates_stale_url(tmp_path: Path) -> None:
    from elliot_core.cli import _write_codex_toml

    config = tmp_path / ".codex" / "config.toml"
    _write_codex_toml(config, "http://localhost:9999/mcp")
    changed = _write_codex_toml(config, "http://localhost:3000/mcp/")

    assert changed is True
    content = config.read_text(encoding="utf-8")
    assert 'url = "http://localhost:3000/mcp/"' in content
    assert "9999" not in content
    assert content.count("[mcp_servers.elliot]") == 1


def test_write_codex_toml_preserves_other_sections(tmp_path: Path) -> None:
    from elliot_core.cli import _write_codex_toml

    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        '[mcp_servers.other]\nurl = "http://other/mcp"\n',
        encoding="utf-8",
    )

    _write_codex_toml(config, "http://localhost:3000/mcp/")

    content = config.read_text(encoding="utf-8")
    assert "[mcp_servers.other]" in content
    assert 'url = "http://other/mcp"' in content
    assert "[mcp_servers.elliot]" in content


# ---------------------------------------------------------------------------
# connect subcommand — OpenClaw registration
# ---------------------------------------------------------------------------


def test_write_openclaw_json_creates_nested_structure(tmp_path: Path) -> None:
    from elliot_core.cli import _write_openclaw_json

    config = tmp_path / ".openclaw" / "openclaw.json"
    changed = _write_openclaw_json(config, "elliot", "http://localhost:3000/mcp/")

    assert changed is True
    data = json.loads(config.read_text(encoding="utf-8"))
    entry = data["mcp"]["servers"]["elliot"]
    assert entry == {"transport": "streamable-http", "url": "http://localhost:3000/mcp/"}


def test_write_openclaw_json_idempotent(tmp_path: Path) -> None:
    from elliot_core.cli import _write_openclaw_json

    config = tmp_path / ".openclaw" / "openclaw.json"
    _write_openclaw_json(config, "elliot", "http://localhost:3000/mcp/")
    changed = _write_openclaw_json(config, "elliot", "http://localhost:3000/mcp/")

    assert changed is False


def test_write_openclaw_json_preserves_other_servers(tmp_path: Path) -> None:
    from elliot_core.cli import _write_openclaw_json

    config = tmp_path / ".openclaw" / "openclaw.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"mcp": {"servers": {"other": {"transport": "stdio"}}}}),
        encoding="utf-8",
    )

    _write_openclaw_json(config, "elliot", "http://localhost:3000/mcp/")

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["mcp"]["servers"]["other"] == {"transport": "stdio"}
    assert data["mcp"]["servers"]["elliot"]["url"] == "http://localhost:3000/mcp/"


def test_cmd_connect_registers_openclaw_when_dir_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from elliot_core.cli import _cmd_connect

    home = tmp_path / "home"
    (home / ".openclaw").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("ELLIOT_PLUGIN_URL", raising=False)

    _cmd_connect(argparse.Namespace(runtime=False, runtime_only=False))

    openclaw_config = home / ".openclaw" / "openclaw.json"
    assert openclaw_config.exists()
    data = json.loads(openclaw_config.read_text(encoding="utf-8"))
    entry = data["mcp"]["servers"]["elliot"]
    assert entry["transport"] == "streamable-http"
    # Trailing slash required so strict MCP clients don't drop the POST body
    # on a 307 redirect.
    assert entry["url"] == "http://localhost:3000/mcp/"


def test_cmd_connect_registers_codex_when_dir_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from elliot_core.cli import _cmd_connect

    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("ELLIOT_PLUGIN_URL", raising=False)

    _cmd_connect(argparse.Namespace(runtime=False, runtime_only=False))

    codex_config = tmp_path / ".codex" / "config.toml"
    assert codex_config.exists()
    content = codex_config.read_text(encoding="utf-8")
    assert "[mcp_servers.elliot]" in content
    # Trailing slash is required for strict MCP clients (Codex/rmcp) that
    # drop POST bodies on a 307 redirect.
    assert 'url = "http://localhost:3000/mcp/"' in content


def test_cmd_connect_runtime_skips_when_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--runtime probe must skip writing config when /mcp/ is not alive."""
    import argparse

    from elliot_core.cli import _cmd_connect

    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("ELLIOT_PLUGIN_URL", raising=False)
    monkeypatch.delenv("ELLIOT_RUNTIME_URL", raising=False)
    # Point runtime probe at an unused port so the probe is guaranteed to fail.
    monkeypatch.setenv("ELLIOT_RUNTIME_URL", "http://127.0.0.1:1")

    _cmd_connect(argparse.Namespace(runtime=True, runtime_only=False))

    codex_config = tmp_path / ".codex" / "config.toml"
    content = codex_config.read_text(encoding="utf-8")
    # Plugin section gets written; runtime section is skipped because probe failed.
    assert "[mcp_servers.elliot]" in content
    assert "[mcp_servers.elliot-runtime]" not in content


def test_probe_mcp_initialize_treats_400_as_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FastMCP rejects an anonymous probe with HTTP 400 — that's still a live endpoint."""
    import urllib.error

    from elliot_core.cli import _probe_mcp_initialize

    class _FakeHTTPError(urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__("http://x", 400, "Bad Request", {}, None)  # type: ignore[arg-type]

    def _fake_urlopen(req: object, timeout: float = 0) -> None:
        raise _FakeHTTPError()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ok, reason = _probe_mcp_initialize("http://localhost:9999/mcp/")
    assert ok is True
    assert reason is None


def test_probe_mcp_initialize_returns_false_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error

    from elliot_core.cli import _probe_mcp_initialize

    def _fake_urlopen(req: object, timeout: float = 0) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ok, reason = _probe_mcp_initialize("http://localhost:1/mcp/")
    assert ok is False
    assert reason is not None and "connection refused" in reason


# ---------------------------------------------------------------------------
# _cmd_scan
# ---------------------------------------------------------------------------


def test_cmd_scan_clean_connector_exits_0(tmp_path: Path) -> None:
    import argparse

    from elliot_core.cli import _cmd_scan

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    args = argparse.Namespace(path=str(p))
    with pytest.raises(SystemExit) as exc_info:
        _cmd_scan(args)
    assert exc_info.value.code == 0


def test_cmd_scan_bad_connector_exits_1(tmp_path: Path) -> None:
    import argparse

    from elliot_core.cli import _cmd_scan

    p = _write_connector(tmp_path, BAD_CONNECTOR)
    args = argparse.Namespace(path=str(p))
    with pytest.raises(SystemExit) as exc_info:
        _cmd_scan(args)
    assert exc_info.value.code == 1


def test_main_scan_dispatch(tmp_path: Path, monkeypatch) -> None:
    import sys

    from elliot_core.cli import main

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    monkeypatch.setattr(sys, "argv", ["elliot", "scan", str(p)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
