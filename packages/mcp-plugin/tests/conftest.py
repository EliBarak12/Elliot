"""Shared fixtures for mcp-plugin tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession


@pytest.fixture()
def session(tmp_path: Path) -> Generator[ElliotSession]:
    s = ElliotSession(cwd=str(tmp_path))
    yield s
    s.engine.close()


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    return create_elliot_server(session)
