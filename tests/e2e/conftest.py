"""Shared pytest fixtures for the project-wide E2E suite.

All tests in this directory are marked ``e2e`` automatically — they boot
real services, hit real HTTP, and (for the Claude layer) spend real tokens.
The mandatory pre-push pytest run does not target this directory, so these
only run when invoked explicitly (``make e2e`` or ``uv run pytest tests/e2e``).
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator

import pytest

from .helpers.mock_apis import MockAPIServer
from .helpers.stack import StackEndpoints, elliot_stack


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark everything under ``tests/e2e/`` with ``@pytest.mark.e2e``."""
    e2e = pytest.mark.e2e
    for item in items:
        if "tests/e2e/" in str(item.fspath):
            item.add_marker(e2e)


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    # Fall through: let the OS pick.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def mock_apis() -> Iterator[MockAPIServer]:
    """Bring up the 4-domain mock API on a single port for the whole session.

    The agent + MCP tests both point ``elliot_discover_source`` at this
    server's ``/users``, ``/products``, ``/orders``, ``/reviews`` paths.
    Setting ``ELLIOT_E2E_API_MODE=real`` skips this fixture so tests can run
    against actual public hosts when the network policy permits it.
    """
    if os.environ.get("ELLIOT_E2E_API_MODE") == "real":
        yield MockAPIServer(host="unused", port=0)  # type: ignore[misc]
        return

    server = MockAPIServer(port=_free_port(8181))
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="session")
def api_base_url(mock_apis: MockAPIServer) -> str:
    """Base URL the connector will use for each REST source."""
    if os.environ.get("ELLIOT_E2E_API_MODE") == "real":
        # Convention: the four real public hosts whose shapes our mocks
        # mirror. Each test should still pass against the live endpoints
        # because the JSON schemas line up.
        return os.environ.get("ELLIOT_E2E_API_BASE", "https://jsonplaceholder.typicode.com")
    return mock_apis.base_url


@pytest.fixture(scope="module")
def stack(api_base_url: str) -> Iterator[StackEndpoints]:
    """Boot the full Elliot stack (plugin + runtime + studio) per test module."""
    with elliot_stack() as endpoints:
        # Make the mock API host visible to the agent without it having to
        # guess. The agent uses Elliot tools which read this from the env.
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.fixture(scope="module")
def stack_no_studio(api_base_url: str) -> Iterator[StackEndpoints]:
    """Lighter stack for layers that don't need the React UI (Layer 1 & 2)."""
    with elliot_stack(skip_studio=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)
