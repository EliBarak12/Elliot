"""Tests for the trace-hook MCP tools (install / status / uninstall)."""

from __future__ import annotations

from pathlib import Path

import pytest

from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.trace_tools import register_trace_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_trace_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):  # type: ignore[no-untyped-def]
    return mcp._tool_manager._tools[name].fn


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Path.home() at a temp dir so installs don't touch the real ~/."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_status_reports_all_harnesses(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_trace_hook_status")()
    names = {h["harness"] for h in result["harnesses"]}
    assert names == {"claude-code", "codex", "cursor"}
    assert all(h["installed"] is False for h in result["harnesses"])
    assert "runtime_url" in result


def test_install_then_status_then_uninstall(mcp: FastMCP) -> None:
    installed = _tool(mcp, "elliot_install_trace_hook")(harness="claude-code")
    assert installed["status"] == "installed"
    assert installed["harness"] == "claude-code"
    assert Path(installed["config_path"]).exists()

    status = _tool(mcp, "elliot_trace_hook_status")()
    claude = next(h for h in status["harnesses"] if h["harness"] == "claude-code")
    assert claude["installed"] is True

    removed = _tool(mcp, "elliot_uninstall_trace_hook")(harness="claude-code")
    assert removed["status"] == "removed"

    status_after = _tool(mcp, "elliot_trace_hook_status")()
    claude_after = next(h for h in status_after["harnesses"] if h["harness"] == "claude-code")
    assert claude_after["installed"] is False


def test_install_rejects_unknown_harness(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_install_trace_hook")(harness="bogus")
    assert "VALIDATION_UNKNOWN_HARNESS" in result["text"]


def test_runtime_url_honours_env(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELLIOT_RUNTIME_URL", "http://example.test:9000/")
    result = _tool(mcp, "elliot_trace_hook_status")()
    assert result["runtime_url"] == "http://example.test:9000"
