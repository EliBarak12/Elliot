"""Tests for elliot_core.http SSRF defenses."""

from __future__ import annotations

import asyncio
import socket
from typing import Any
from unittest import mock

import httpx
import pytest

from elliot_core.http import (
    SSRFError,
    safe_client,
    validate_url,
)

# ── scheme & userinfo ──────────────────────────────────────────────────────


def test_validate_url_rejects_empty():
    with pytest.raises(SSRFError, match="empty"):
        validate_url("")


def test_validate_url_rejects_file_scheme():
    with pytest.raises(SSRFError, match="scheme"):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_gopher_scheme():
    with pytest.raises(SSRFError, match="scheme"):
        validate_url("gopher://example.com/")


def test_validate_url_rejects_data_scheme():
    with pytest.raises(SSRFError, match="scheme"):
        validate_url("data:text/plain,hello")


def test_validate_url_rejects_userinfo():
    with pytest.raises(SSRFError, match="userinfo"):
        validate_url("http://user:pass@example.com/")


def test_validate_url_rejects_missing_host():
    with pytest.raises(SSRFError, match="host"):
        validate_url("http:///path")


# ── IP blocking via DNS ────────────────────────────────────────────────────


def _mock_getaddrinfo(*ips: str) -> Any:
    """Build a getaddrinfo side-effect that returns the given IPs."""

    def _inner(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
        return [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in ips]

    return _inner


def test_validate_url_rejects_loopback_ip():
    with (
        mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("127.0.0.1")),
        pytest.raises(SSRFError, match="non-public"),
    ):
        validate_url("http://attacker.example.com/")


def test_validate_url_rejects_aws_metadata_ip():
    with (
        mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("169.254.169.254")),
        pytest.raises(SSRFError, match="non-public"),
    ):
        validate_url("http://attacker.example.com/")


def test_validate_url_rejects_rfc1918():
    for ip in ("10.0.0.1", "172.16.1.1", "192.168.1.1"):
        with (
            mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo(ip)),
            pytest.raises(SSRFError, match="non-public"),
        ):
            validate_url("http://attacker.example.com/")


def test_validate_url_rejects_gcp_metadata_hostname():
    # Pre-resolution name match — should fail before DNS even runs.
    with pytest.raises(SSRFError, match="cloud metadata"):
        validate_url("http://metadata.google.internal/computeMetadata/v1/")


def test_validate_url_accepts_public_ip():
    with mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("93.184.216.34")):
        validate_url("https://example.com/path")


def test_validate_url_rejects_when_any_ip_is_private():
    # IPv4 + IPv6 — if either is private, reject.
    with (
        mock.patch(
            "socket.getaddrinfo",
            side_effect=_mock_getaddrinfo("93.184.216.34", "127.0.0.1"),
        ),
        pytest.raises(SSRFError, match="non-public"),
    ):
        validate_url("http://attacker.example.com/")


def test_validate_url_dns_failure_blocked():
    def _gaierror(*_a: Any, **_kw: Any) -> Any:
        raise socket.gaierror("no such host")

    with (
        mock.patch("socket.getaddrinfo", side_effect=_gaierror),
        pytest.raises(SSRFError, match="DNS"),
    ):
        validate_url("http://does-not-resolve.example.invalid/")


# ── allow_private opt-in ───────────────────────────────────────────────────


def test_validate_url_allow_private_kwarg():
    with mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("127.0.0.1")):
        validate_url("http://internal.example.com/", allow_private=True)


def test_validate_url_allow_private_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_SSRF_ALLOW_PRIVATE", "1")
    with mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("10.0.0.1")):
        validate_url("http://internal.example.com/")


# ── safe_client defaults ───────────────────────────────────────────────────


def test_safe_client_default_no_redirects():
    client = safe_client()
    try:
        assert client.follow_redirects is False
    finally:
        # AsyncClient must be closed via aclose(); for the sync default test
        # we drop the reference and rely on GC. (Tested for attribute only.)
        pass


def test_safe_client_explicit_follow_redirects():
    client = safe_client(follow_redirects=True)
    try:
        assert client.follow_redirects is True
    finally:
        pass


# ── DNS-rebinding / IP pinning ─────────────────────────────────────────────


def test_validate_url_returns_resolved_ips():
    """validate_url returns the vetted IPs so callers can pin the connection."""
    with mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("93.184.216.34")):
        ips = validate_url("https://example.com/path")
    assert ips == ["93.184.216.34"]


def test_validate_url_returns_literal_ip():
    """When the host is already a literal IP it is returned as-is."""
    ips = validate_url("https://93.184.216.34/")
    assert ips == ["93.184.216.34"]


def test_safe_client_pinned_transport_used():
    """When pinned_hosts is supplied the client uses the pinning transport."""
    from elliot_core.http import _PinnedTransport

    client = safe_client(pinned_hosts={"example.com": "93.184.216.34"})
    assert isinstance(client._transport, _PinnedTransport)


def test_pinned_transport_rejects_unvalidated_host(monkeypatch: pytest.MonkeyPatch):
    """A request to a host with no pin (e.g. an un-validated redirect target)
    fails closed rather than connecting unvalidated — the DNS-rebinding fix.

    The conftest autouse fixture sets ELLIOT_HTTP_DISABLE_PINNING so respx
    mocks match; this test exercises the *real* rewrite behavior, so it must
    explicitly clear that flag — production never sets it.
    """
    monkeypatch.delenv("ELLIOT_HTTP_DISABLE_PINNING", raising=False)
    from elliot_core.http import _PinnedTransport

    transport = _PinnedTransport({"example.com": "93.184.216.34"})
    request = httpx.Request("GET", "https://attacker.example.org/")
    with pytest.raises(SSRFError, match="not pre-validated"):
        asyncio.run(transport.handle_async_request(request))


def test_pinned_transport_rewrites_host_keeps_sni(monkeypatch: pytest.MonkeyPatch):
    """The transport connects to the pinned IP but keeps SNI on the real host.

    Clears ELLIOT_HTTP_DISABLE_PINNING (set by the conftest autouse fixture)
    so the genuine host-rewrite path is exercised.
    """
    monkeypatch.delenv("ELLIOT_HTTP_DISABLE_PINNING", raising=False)
    from elliot_core.http import _PinnedTransport

    transport = _PinnedTransport({"example.com": "93.184.216.34"})
    captured: dict[str, Any] = {}

    async def _fake_super(self: Any, request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        captured["host"] = request.url.host
        captured["sni"] = request.extensions.get("sni_hostname")
        captured["host_header"] = request.headers.get("Host")
        return httpx.Response(200)

    with mock.patch.object(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super):
        request = httpx.Request("GET", "https://example.com/path")
        asyncio.run(transport.handle_async_request(request))

    assert captured["host"] == "93.184.216.34"  # socket connects to the vetted IP
    assert captured["sni"] == "example.com"  # TLS SNI stays on the real host
    assert captured["host_header"] == "example.com"  # Host header preserved


def test_pinned_transport_disable_flag_makes_it_transparent(monkeypatch: pytest.MonkeyPatch):
    """With ELLIOT_HTTP_DISABLE_PINNING set, the transport performs no host
    rewrite — it stays in the request path but is transparent. This is the
    test-only escape hatch; production never sets the var."""
    monkeypatch.setenv("ELLIOT_HTTP_DISABLE_PINNING", "1")
    from elliot_core.http import _PinnedTransport

    transport = _PinnedTransport({"example.com": "93.184.216.34"})
    captured: dict[str, Any] = {}

    async def _fake_super(self: Any, request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        captured["host"] = request.url.host
        return httpx.Response(200)

    with mock.patch.object(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super):
        # An un-pinned host would normally fail closed; with the flag set it
        # passes through untouched.
        request = httpx.Request("GET", "https://unpinned.example.org/path")
        asyncio.run(transport.handle_async_request(request))

    assert captured["host"] == "unpinned.example.org"  # no rewrite
