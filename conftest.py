"""Workspace-level pytest fixtures.

The SSRF validator (``elliot_core.http.validate_url``) does a real
``socket.getaddrinfo`` lookup. In sandboxed test environments DNS resolution
can fail for the canonical example hostnames the test suite uses
(``api.example.com``, ``host.example.com``), which would turn an SSRF
defence into a test-suite breaker.

This autouse fixture maps any ``*.example.com`` hostname to a public IP for
DNS-resolution checks only. Real network I/O is mocked via ``respx``.
"""

from __future__ import annotations

import socket
from collections.abc import Generator
from typing import Any

import pytest

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
def _ssrf_resolve_example_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Make `*.example.com` resolve to a public IP for SSRF validate_url checks."""
    monkeypatch.setattr(socket, "getaddrinfo", _patched_getaddrinfo)
    yield
