"""Tests for the mcp-plugin CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_MINIMAL_CONNECTOR = {
    "name": "CLI Test",
    "slug": "cli-test",
    "version": "1.0.0",
    "sources": [],
    "tools": [],
    "skills": [],
}


def _invoke(args: list[str]) -> int:
    """Run the CLI main() with given sys.argv and return exit code (or 0 on success)."""
    from elliot_mcp_plugin.cli import main

    with patch("sys.argv", ["elliot-mcp", *args]):
        try:
            main()
            return 0
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0


class TestCLIMain:
    def test_runs_stdio_with_connector_file(self, tmp_path: Path) -> None:
        connector_file = tmp_path / "test.connector.json"
        connector_file.write_text(json.dumps(_MINIMAL_CONNECTOR))

        # AsyncMock returns a coroutine that asyncio.run() can actually run
        with patch("elliot_mcp_plugin.cli.run_stdio", new=AsyncMock(return_value=None)):
            code = _invoke(["--connector", str(connector_file)])

        assert code == 0

    def test_exits_1_on_connector_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "missing.connector.json"
        code = _invoke(["--connector", str(missing)])
        assert code == 1
        captured = capsys.readouterr()
        # Fatal errors are logged as structured JSON to stderr.
        assert "cli.fatal" in captured.err
        assert "missing.connector.json" in captured.err

    def test_exits_0_on_keyboard_interrupt(self, tmp_path: Path) -> None:
        connector_file = tmp_path / "test.connector.json"
        connector_file.write_text(json.dumps(_MINIMAL_CONNECTOR))

        async def _raise() -> None:
            raise KeyboardInterrupt

        with patch("elliot_mcp_plugin.cli.run_stdio", new=AsyncMock(side_effect=KeyboardInterrupt)):
            code = _invoke(["--connector", str(connector_file)])

        assert code == 0

    def test_exits_1_on_generic_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        connector_file = tmp_path / "test.connector.json"
        connector_file.write_text(json.dumps(_MINIMAL_CONNECTOR))

        with patch(
            "elliot_mcp_plugin.cli.run_stdio",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            code = _invoke(["--connector", str(connector_file)])

        assert code == 1
        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_secrets_passed_to_run_stdio(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector_file = tmp_path / "test.connector.json"
        connector_file.write_text(json.dumps(_MINIMAL_CONNECTOR))
        monkeypatch.setenv("ELLIOT_SECRET_API_KEY", "tok-123")

        mock_run = AsyncMock(return_value=None)
        with patch("elliot_mcp_plugin.cli.run_stdio", new=mock_run):
            _invoke(["--connector", str(connector_file)])

        _config, secrets = mock_run.call_args[0]
        assert secrets.get("api_key") == "tok-123"

    def test_configure_logging_is_called(self, tmp_path: Path) -> None:
        connector_file = tmp_path / "test.connector.json"
        connector_file.write_text(json.dumps(_MINIMAL_CONNECTOR))

        with (
            patch("elliot_mcp_plugin.cli.configure_logging") as mock_log_cfg,
            patch("elliot_mcp_plugin.cli.run_stdio", new=AsyncMock(return_value=None)),
        ):
            _invoke(["--connector", str(connector_file)])

        mock_log_cfg.assert_called_once()
