"""Tests for the install.py auto-registration script."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


def _run_install(project_root: Path) -> None:
    """Import and execute install.py with PROJECT_ROOT redirected to tmp dir."""
    script = Path(__file__).parent.parent / "scripts" / "install.py"
    # Patch PROJECT_ROOT before the module-level code runs
    with (
        patch.object(
            sys.modules.get("builtins", __builtins__),  # type: ignore[arg-type]
            "__import__",
            wraps=__import__,
        ),
        patch("subprocess.run", side_effect=FileNotFoundError),
        patch("pathlib.Path.home", return_value=project_root / "home"),
    ):
        # Inject a custom PROJECT_ROOT by executing the script source with overrides
        source = script.read_text()
        source = source.replace(
            "PROJECT_ROOT = Path(__file__).parent.parent.parent.parent",
            f"PROJECT_ROOT = Path({str(project_root)!r})",
        )
        exec(compile(source, str(script), "exec"), {"__file__": str(script)})  # noqa: S102


def test_install_creates_mcp_json(tmp_path: Path):
    with patch("subprocess.run", side_effect=FileNotFoundError):
        _run_install(tmp_path)
    mcp_json = tmp_path / ".mcp.json"
    assert mcp_json.exists()
    data = json.loads(mcp_json.read_text())
    assert "elliot" in data["mcpServers"]
    assert data["mcpServers"]["elliot"]["url"] == "http://localhost:3000/mcp/"


def test_install_creates_codex_config(tmp_path: Path):
    with patch("subprocess.run", side_effect=FileNotFoundError):
        _run_install(tmp_path)
    codex_config = tmp_path / ".codex" / "config.toml"
    assert codex_config.exists()
    assert "[mcp_servers.elliot]" in codex_config.read_text()


def test_install_idempotent_mcp_json(tmp_path: Path):
    """Running twice does not duplicate the elliot entry."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        _run_install(tmp_path)
        _run_install(tmp_path)
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert list(data["mcpServers"].keys()).count("elliot") == 1


def test_install_idempotent_codex_config(tmp_path: Path):
    """Running twice does not duplicate [mcp_servers.elliot]."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        _run_install(tmp_path)
        _run_install(tmp_path)
    content = (tmp_path / ".codex" / "config.toml").read_text()
    assert content.count("[mcp_servers.elliot]") == 1


def test_install_exits_0(tmp_path: Path):
    """Script should not raise."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        _run_install(tmp_path)  # no exception means exit 0 equivalent
