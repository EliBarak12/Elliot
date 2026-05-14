"""Workspace-level pytest fixtures.

Several audit-driven defenses (SSRF DNS check, file_reader containment,
…) reject inputs that legitimate tests legitimately use (e.g. tmp_path
under /tmp, mocked respx hosts that don't exist on the public internet).
These autouse fixtures relax those defenses for the test suite without
weakening them in production.
"""

from __future__ import annotations

import socket
from collections.abc import Generator
from typing import Any

import pytest

# ── SSRF: resolve example.com-family to a public IP ───────────────────────


_REAL_GETADDRINFO = socket.getaddrinfo
_EXAMPLE_PUBLIC_IP = "93.184.216.34"  # example.com canonical address


def _patched_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Resolve example.com-family hostnames to a public IP without DNS."""
    if isinstance(host, str) and (host == "example.com" or host.endswith(".example.com")):
        port = args[0] if args else 0
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (_EXAMPLE_PUBLIC_IP, port if isinstance(port, int) else 0),
            )
        ]
    return _REAL_GETADDRINFO(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def _ssrf_resolve_example_hosts(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Make `*.example.com` resolve to a public IP for SSRF validate_url checks."""
    monkeypatch.setattr(socket, "getaddrinfo", _patched_getaddrinfo)
    yield


# ── File reader: allow absolute paths under tmp_path during tests ─────────


@pytest.fixture(autouse=True)
def _allow_absolute_file_paths(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Tests legitimately use tmp_path (under /tmp) which is outside the project tree.

    The file_reader containment check (audit fix H3) defaults to rejecting
    such paths in production. Enable the opt-out for the test suite so
    fixtures keep working without each test having to set the env var.
    """
    monkeypatch.setenv("ELLIOT_FILE_READER_ALLOW_ABSOLUTE", "1")
    yield
